from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import cast

from qurantext.config.paths import QURAN_DB_PATH
from qurantext.config.settings import get_settings
from qurantext.core.alignment import align_canonical_word_timings, refine_word_timings
from qurantext.core.arabic import normalize_alignment_ar
from qurantext.core.lecture_matching import (
    detect_quran_mentions_in_lecture,
    select_lecture_timeline,
)
from qurantext.core.preamble import extract_preamble, trim_leading_preamble
from qurantext.core.quran_parser import parse_ayat
from qurantext.core.range_matching import (
    ayah_entry,
    ayat_in_detected_range,
    build_warnings,
    detect_first_ayah,
    detect_last_ayah,
    select_recitation_timeline,
)
from qurantext.data.quran_db import QuranDataError, ensure_quran_db
from qurantext.io.readers import extract_matching_words, load_json
from qurantext.io.writers import write_json
from qurantext.services.transcription import transcribe_audio
from qurantext.utils.progress import CancelToken, ConsoleProgress, ProgressCallback, report


def _is_ayah_marker(token: str) -> bool:
    """Return True if *token* is an ayah-number marker (Arabic-Indic digits only).

    Mirrors ``frame_renderer._is_ayah_marker`` so canonical word timings are
    indexed over the same non-marker words the renderer highlights.
    """
    stripped = token.strip()
    return bool(stripped) and all("٠" <= c <= "٩" for c in stripped)


def assign_recitation_word_timings(
    mentions: list[dict],
    recitation_ayat: list[dict],
    words: list[dict],
    *,
    offset: float = 0.0,
    bridge_max: float = 0.6,
) -> None:
    """Attach word timings and re-derive each card's display window, in place.

    Recitation is a forced-alignment problem over KNOWN text, so the whole
    transcript is aligned against the whole detected range ONCE — every
    canonical (non-marker) word gets its real onset. Each mention then takes the
    slice of that global alignment covering its ``from_ayah..to_ayah`` and its
    ``start_time``/``end_time`` are set from those words' true onsets.

    The previous per-chunk approach windowed the transcript by each match's
    *fuzzy* start/end (coarse 5–35-word windows, step 3); at a chunk boundary
    that could drop a whole ayah and make the card switch lag the reciter by
    seconds. Deriving the window from the aligned words instead makes cards tile
    the recitation with no gap and switch exactly on the next chunk's first word.
    """
    range_tokens: list[tuple[int, str]] = []  # (ayah_num, token) in recital order
    for ayah in recitation_ayat:
        for token in str(ayah["text_raw"]).split():
            if not _is_ayah_marker(token):
                range_tokens.append((ayah["ayah_num"], token))

    range_norms = [normalize_alignment_ar(token) for _, token in range_tokens]
    global_timings = align_canonical_word_timings(words, range_norms)
    # Steady the raw CTC timings: monotonic starts (kill backward jitter),
    # gap-free onset-anchored ends (keyframe-ready spans, and cards that abut
    # cleanly), and a global offset to cancel any consistent highlight lag/lead.
    global_timings = refine_word_timings(global_timings, offset=offset, bridge_max=bridge_max)

    for match in mentions:
        from_ayah, to_ayah = match["from_ayah"], match["to_ayah"]
        word_timings = [
            {"word": token, "start": global_timings[i]["start"], "end": global_timings[i]["end"]}
            for i, (ayah_num, token) in enumerate(range_tokens)
            if from_ayah <= ayah_num <= to_ayah
        ]
        match["word_timings"] = word_timings
        starts = [w["start"] for w in word_timings if isinstance(w["start"], (int, float))]
        ends = [w["end"] for w in word_timings if isinstance(w["end"], (int, float))]
        if starts:
            match["start_time"] = round(min(starts), 2)
        if ends:
            match["end_time"] = round(max(ends), 2)


def count_whisperx_segments(data: dict | list) -> int:
    """Count top-level WhisperX segments/items in a loaded JSON response."""
    if isinstance(data, dict):
        return len(data.get("segments", []))
    if isinstance(data, list):
        return len(data)
    return 0


def default_whisperx_raw_path(output_path: str | Path) -> Path:
    """Place raw WhisperX JSON next to the main result file."""
    output_path = Path(output_path)
    return output_path.with_name(f"{output_path.stem}_whisperx_raw.json")


def run_detection(
    *,
    quran: str | Path,
    output: str | Path,
    mode: str = "range",
    whisperx: str | Path | None = None,
    audio: str | Path | None = None,
    surah: str | None = None,
    head_words: int | None = None,
    tail_words: int | None = None,
    search_range: int | None = None,
    low_conf: float | None = None,
    max_span: int | None = None,
    lecture_threshold: float | None = None,
    min_matched_words: int | None = None,
    echo: bool = True,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> dict:
    """Run the detect-range workflow in range, lecture, or recitation mode."""
    if (whisperx is None) == (audio is None):
        raise ValueError("Exactly one of whisperx or audio must be provided.")

    out_path = Path(output)
    settings = get_settings()
    range_settings = settings.range_matching
    lecture_settings = settings.lecture_matching

    resolved_head_words = cast(
        int, head_words if head_words is not None else range_settings.head_words
    )
    resolved_tail_words = cast(
        int, tail_words if tail_words is not None else range_settings.tail_words
    )
    resolved_search_range = cast(
        int,
        search_range if search_range is not None else range_settings.search_range,
    )
    resolved_low_conf = cast(
        float,
        low_conf if low_conf is not None else range_settings.low_conf,
    )
    resolved_max_span = cast(int, max_span if max_span is not None else lecture_settings.max_span)
    resolved_lecture_threshold = cast(
        float, lecture_threshold if lecture_threshold is not None else lecture_settings.min_score
    )
    resolved_min_matched_words = cast(
        int,
        min_matched_words if min_matched_words is not None else lecture_settings.min_matched_words,
    )

    # Stage output goes through the progress reporter, so a user interface gets
    # the same information as the terminal. `echo` stays as the convenience it
    # always was: it simply supplies the console reporter when no other is given.
    if progress is None and echo:
        progress = ConsoleProgress()

    def emit(message: str = "") -> None:
        report(progress, "detect", message)

    emit(f"[1/4] Parsing Quran text: {quran}")
    effective_surah = None if mode == "lecture" else surah
    ayat = parse_ayat(quran, surah_filter=effective_surah)
    if not ayat:
        raise ValueError("No ayat parsed. Check --quran path, encoding, and --surah spelling.")
    n_surahs = len({ayah["surah_num"] for ayah in ayat})
    emit(f"      {len(ayat)} ayat parsed across {n_surahs} surah(s).")
    if mode == "lecture" and surah is not None:
        emit("      Note: ignoring --surah in lecture mode; scanning the full Quran.")

    if whisperx is not None:
        emit(f"[2/4] Loading WhisperX JSON: {whisperx}")
        wx_path = Path(whisperx)
        if not wx_path.exists():
            raise FileNotFoundError(f"WhisperX file not found: {whisperx}")
        try:
            wx_data = load_json(wx_path)
        except json.JSONDecodeError as error:
            raise ValueError(f"Failed to parse WhisperX JSON '{whisperx}': {error}") from error

        transcript_source = "whisperx_json"
        transcript_input_path = str(wx_path.resolve())
        whisperx_raw_output_path = str(wx_path.resolve())
        whisperx_model_ref = None
        whisperx_segment_count = count_whisperx_segments(wx_data)
    else:
        assert audio is not None
        emit(f"[2/4] Transcribing audio with WhisperX: {audio}")
        service_result = transcribe_audio(audio, save_raw_to=default_whisperx_raw_path(out_path))
        wx_data = service_result.output
        transcript_source = "audio"
        transcript_input_path = str(Path(audio).resolve())
        whisperx_raw_output_path = service_result.raw_output_path
        whisperx_model_ref = service_result.model_ref
        whisperx_segment_count = service_result.segment_count
        emit(
            f"      WhisperX raw JSON saved to {service_result.raw_output_path} "
            f"({service_result.segment_count} segments, {service_result.word_count} words)."
        )

    words = extract_matching_words(wx_data)
    if not words:
        raise ValueError("No word tokens extracted from WhisperX output.")
    duration = words[-1]["end"] - words[0]["start"]
    emit(
        f"      {len(words)} word tokens extracted ({duration:.1f}s, "
        f"{words[0]['start']:.2f}s – {words[-1]['end']:.2f}s)."
    )

    head_n = min(resolved_head_words, len(words))
    tail_n = min(resolved_tail_words, len(words))
    s_range = min(resolved_search_range, len(ayat))
    global_search = n_surahs > 1 and surah is None

    if mode == "lecture":
        emit("[3/4] Detecting Quran mentions inside lecture...")
        # Back candidate selection with the persisted citation n-gram index: on
        # lecture audio most windows are speech, not quotes, so the index skips
        # them before any fuzzy scoring (~10× faster, same final boundaries). If
        # the store can't be prepared, fall back to the in-memory path so
        # detection never hard-fails on a missing/unwritable DB.
        conn = None
        try:
            conn = ensure_quran_db(quran, QURAN_DB_PATH)
        except (OSError, sqlite3.DatabaseError, QuranDataError) as error:
            emit(f"      Note: citation index unavailable ({error}); using in-memory matcher.")
        try:
            # Lecture cards show exactly the single ayah being mentioned: a
            # teacher quotes one ayah, explains, then quotes the next. Force
            # single-ayah spans (max_span=1) and block range-merging
            # (max_merged_ayat=1) so each card is one ayah — a continuously
            # recited passage still surfaces as its individual ayat in sequence,
            # which the renderer latches one at a time. (Multi-ayah spans remain
            # the default for recitation mode, which has its own call below.)
            mentions = detect_quran_mentions_in_lecture(
                ayat,
                words,
                max_span=1,
                max_merged_ayat=1,
                min_window_words=lecture_settings.min_window_words,
                max_window_words=lecture_settings.max_window_words,
                window_step=lecture_settings.window_step,
                min_score=resolved_lecture_threshold,
                min_matched_words=resolved_min_matched_words,
                candidate_limit=lecture_settings.candidate_limit,
                conn=conn,
                db_strategy="ngram" if conn is not None else "word_overlap",
                progress=progress,
                cancel=cancel,
            )
        finally:
            if conn is not None:
                conn.close()
        # Resolve overlapping/competing single-ayah detections into a clean
        # one-ayah-at-a-time timeline so each card shows exactly the ayah being
        # mentioned (see select_lecture_timeline).
        mentions = select_lecture_timeline(mentions)
        result = {
            "matches": mentions,
            "meta": {
                "input_type": transcript_source,
                "input_path": transcript_input_path,
                "whisperx_raw_output_path": whisperx_raw_output_path,
                "whisperx_model_ref": whisperx_model_ref,
                "whisperx_segments": whisperx_segment_count,
                "total_ayat_in_file": len(ayat),
                "whisperx_words": len(words),
                "audio_start_s": words[0]["start"],
                "audio_end_s": words[-1]["end"],
                "audio_duration_s": round(duration, 2),
                "mode": "lecture",
                "max_span": resolved_max_span,
                "lecture_threshold": resolved_lecture_threshold,
                "min_matched_words": resolved_min_matched_words,
                "surah_filter_ignored": surah is not None,
            },
        }
        emit(f"[4/4] Writing result → {out_path}")
        write_json(result, out_path)

        emit()
        emit("=" * 64)
        if not mentions:
            emit("No Qur'an ayat detected.")
        else:
            for match in mentions:
                ayah_range = (
                    f"#{match['from_ayah']}"
                    if match["from_ayah"] == match["to_ayah"]
                    else f"#{match['from_ayah']}–{match['to_ayah']}"
                )
                emit(
                    f"{match['surah_name']} {ayah_range} "
                    f"({match['start_time']:.2f}s–{match['end_time']:.2f}s, conf {match['confidence']:.2f})"
                )
                emit(f"Detected: {match['detected_text']}")
                emit("Quran:")
                emit(match["full_text"])
                emit("-" * 64)

        emit(f"\nSaved to: {out_path.resolve()}\n")
        return result

    mode_label = "global" if global_search else f"search_range={s_range}"
    emit(f"[3/4] Detecting range  (head={head_n} words, tail={tail_n} words, {mode_label}) …")
    first_ayah, first_conf = detect_first_ayah(
        ayat,
        words,
        head_n,
        s_range,
        global_search=global_search,
        position_threshold=range_settings.position_threshold,
        position_threshold_global=range_settings.position_threshold_global,
        high_conf_position=range_settings.high_conf_position,
        min_words_global=range_settings.min_words_global,
    )
    last_ayah, last_conf = detect_last_ayah(
        ayat,
        words,
        tail_n,
        s_range,
        global_search=global_search,
        first_ayah=first_ayah,
        position_threshold=range_settings.position_threshold,
        position_threshold_global=range_settings.position_threshold_global,
        high_conf_position=range_settings.high_conf_position,
        min_words_global=range_settings.min_words_global,
    )
    warnings = build_warnings(
        first_ayah,
        first_conf,
        last_ayah,
        last_conf,
        words,
        resolved_low_conf,
        global_search=global_search,
    )

    if mode == "recitation":
        emit("[3/4] Refining recitation matches inside detected range...")
        recitation_ayat = ayat_in_detected_range(ayat, first_ayah, last_ayah)
        # This call dominates recitation mode — roughly 99% of its runtime, and
        # it prints nothing while it works. Backing it with the citation n-gram
        # index (conn + db_strategy="ngram"), the lever that makes lecture mode
        # fast, was tried and REJECTED. Measured on the 914-word Al-Furqan
        # recitation, full surah detected:
        #
        #     in-memory   583 s   22 cards, 74 of 77 ayat, no gap over 1.6 s
        #     ngram       369 s   16 cards, 66 of 77 ayat, gaps up to 39 s
        #
        # Only 1.6x faster, because the index earns its speed by skipping windows
        # with no exact phrase hit — common in a tafseer where most speech is not
        # quotation, rare in continuous recitation where nearly every window hits
        # (see the docstring on detect_quran_mentions_in_lecture). Paying eight
        # dropped ayat and half-minute holes on screen for that is a bad trade.
        #
        # The real fix is not a faster matcher: with the surah and ayah range
        # known, recitation is forced alignment over known text and this whole
        # detection stage goes away.
        raw_mentions = detect_quran_mentions_in_lecture(
            recitation_ayat,
            words,
            max_span=resolved_max_span,
            min_window_words=lecture_settings.min_window_words,
            max_window_words=lecture_settings.max_window_words,
            window_step=lecture_settings.window_step,
            min_score=resolved_lecture_threshold,
            min_matched_words=resolved_min_matched_words,
            candidate_limit=lecture_settings.candidate_limit,
            max_merged_ayat=resolved_max_span,
            progress=progress,
            cancel=cancel,
        )
        mentions = select_recitation_timeline(
            raw_mentions,
            recitation_ayat,
            max_span=resolved_max_span,
        )

        # Attach per-word timestamps for the video highlight and re-derive each
        # card's display window from those aligned onsets (see the helper).
        assign_recitation_word_timings(
            mentions,
            recitation_ayat,
            words,
            offset=settings.alignment.highlight_offset_s,
            bridge_max=settings.alignment.bridge_max_s,
        )

        # A leading istiʿādha/basmala is stripped from the canonical text, so the
        # matcher folds that audio into the first ayah — pulling its start time to
        # the top of the recording and shifting its word highlights. Emit the
        # preamble as its own timed card(s) and trim the first ayah back to where
        # it actually begins.
        preamble_matches, boundary_time = extract_preamble(words)
        if preamble_matches and boundary_time is not None:
            trim_leading_preamble(mentions, boundary_time)
            mentions = preamble_matches + mentions

        result = {
            "first_ayah": ayah_entry(first_ayah, first_conf),
            "last_ayah": ayah_entry(last_ayah, last_conf),
            "matches": mentions,
            "warnings": warnings,
            "meta": {
                "input_type": transcript_source,
                "input_path": transcript_input_path,
                "whisperx_raw_output_path": whisperx_raw_output_path,
                "whisperx_model_ref": whisperx_model_ref,
                "whisperx_segments": whisperx_segment_count,
                "total_ayat_in_file": len(ayat),
                "recitation_ayat_scanned": len(recitation_ayat),
                "whisperx_words": len(words),
                "audio_start_s": words[0]["start"],
                "audio_end_s": words[-1]["end"],
                "audio_duration_s": round(duration, 2),
                "mode": "recitation",
                "max_span": resolved_max_span,
                "lecture_threshold": resolved_lecture_threshold,
                "min_matched_words": resolved_min_matched_words,
                "head_words_used": head_n,
                "tail_words_used": tail_n,
                "search_range_used": s_range,
                "global_search": global_search,
                "detected_surah_num": first_ayah["surah_num"],
                "detected_surah_name": first_ayah["surah_name"],
                "preamble_segments": [m["preamble_kind"] for m in preamble_matches],
            },
        }
        emit(f"[4/4] Writing result → {out_path}")
        write_json(result, out_path)

        emit()
        emit("=" * 64)
        emit(
            f"Detected range: {first_ayah['surah_name']} #{first_ayah['ayah_num']}–#{last_ayah['ayah_num']} (matches: {len(mentions)})"
        )
        if warnings:
            emit("Warnings:")
            for msg in warnings:
                emit(f"- {msg}")
        for match in mentions:
            ayah_range = (
                f"#{match['from_ayah']}"
                if match["from_ayah"] == match["to_ayah"]
                else f"#{match['from_ayah']}–{match['to_ayah']}"
            )
            emit(
                f"{match['surah_name']} {ayah_range} "
                f"({match['start_time']:.2f}s–{match['end_time']:.2f}s, conf {match['confidence']:.2f})"
            )
        emit(f"\nSaved to: {out_path.resolve()}\n")
        return result

    result = {
        "first_ayah": ayah_entry(first_ayah, first_conf),
        "last_ayah": ayah_entry(last_ayah, last_conf),
        "warnings": warnings,
        "meta": {
            "input_type": transcript_source,
            "input_path": transcript_input_path,
            "whisperx_raw_output_path": whisperx_raw_output_path,
            "whisperx_model_ref": whisperx_model_ref,
            "whisperx_segments": whisperx_segment_count,
            "total_ayat_in_file": len(ayat),
            "whisperx_words": len(words),
            "audio_start_s": words[0]["start"],
            "audio_end_s": words[-1]["end"],
            "audio_duration_s": round(duration, 2),
            "head_words_used": head_n,
            "tail_words_used": tail_n,
            "search_range_used": s_range,
            "global_search": global_search,
        },
    }
    emit(f"[4/4] Writing result → {out_path}")
    write_json(result, out_path)

    separator = "═" * 64
    fa = result["first_ayah"]
    la = result["last_ayah"]
    emit(f"\n{separator}")
    emit(f"  First ayah │ {fa['surah_name']} — #{fa['ayah_num']}  (conf {fa['confidence']:.2f})")
    emit(f"             │ {fa['text'][:70]}")
    emit()
    emit(f"  Last ayah  │ {la['surah_name']} — #{la['ayah_num']}  (conf {la['confidence']:.2f})")
    emit(f"             │ {la['text'][:70]}")
    if warnings:
        emit()
        emit("  ⚠  Warnings:")
        for msg in warnings:
            emit(f"     • {msg}")
    emit(separator)
    emit(f"\nSaved to: {out_path.resolve()}\n")
    return result

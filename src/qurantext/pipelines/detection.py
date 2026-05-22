from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from qurantext.config.settings import get_settings
from qurantext.core.lecture_matching import detect_quran_mentions_in_lecture
from qurantext.core.quran_parser import parse_ayat
from qurantext.core.range_matching import (
    ayah_entry,
    ayat_in_detected_range,
    build_warnings,
    detect_first_ayah,
    detect_last_ayah,
    select_recitation_timeline,
)
from qurantext.io.readers import extract_matching_words, load_json
from qurantext.io.writers import write_json
from qurantext.services.transcription import WhisperXServiceError, transcribe_audio


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
        float,
        lecture_threshold if lecture_threshold is not None else lecture_settings.min_score
    )
    resolved_min_matched_words = cast(
        int,
        min_matched_words
        if min_matched_words is not None
        else lecture_settings.min_matched_words
    )

    def emit(message: str = "") -> None:
        if echo:
            print(message)

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
        mentions = detect_quran_mentions_in_lecture(
            ayat,
            words,
            max_span=resolved_max_span,
            min_window_words=lecture_settings.min_window_words,
            max_window_words=lecture_settings.max_window_words,
            window_step=lecture_settings.window_step,
            min_score=resolved_lecture_threshold,
            min_matched_words=resolved_min_matched_words,
            candidate_limit=lecture_settings.candidate_limit,
        )
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
        )
        mentions = select_recitation_timeline(
            raw_mentions,
            recitation_ayat,
            max_span=resolved_max_span,
        )
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


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone detect-range compatibility CLI parser."""
    parser = argparse.ArgumentParser(
        description="Detect Quran content in a WhisperX transcription.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    settings = get_settings()
    parser.add_argument(
        "--quran",
        required=True,
        help="Path to Qalun Quran text file (single-surah or full Quran).",
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--whisperx",
        help="Path to an existing WhisperX JSON transcription output.",
    )
    source_group.add_argument(
        "--audio",
        help="Path to an audio file to transcribe with WhisperX via Replicate.",
    )
    parser.add_argument("--output", default="result.json", help="Path for the output JSON.")
    parser.add_argument(
        "--surah",
        default=None,
        help=(
            "Optional: surah name to restrict search to (as it appears in the file, "
            "e.g. 'سُورَةُ الفُرقَانِ'). Used in range/recitation modes; lecture mode always scans the full Quran."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["range", "lecture", "recitation"],
        default="range",
        help=(
            "range = detect first/last ayah; lecture = detect Quran mentions in lecture audio; "
            "recitation = detect range, then emit timestamped ayah spans inside it."
        ),
    )
    parser.add_argument(
        "--head-words",
        type=int,
        default=settings.range_matching.head_words,
        help="WhisperX words from the start used for first-ayah detection.",
    )
    parser.add_argument(
        "--tail-words",
        type=int,
        default=settings.range_matching.tail_words,
        help="WhisperX words from the end used for last-ayah detection.",
    )
    parser.add_argument(
        "--search-range",
        type=int,
        default=settings.range_matching.search_range,
        help="Number of candidate ayat scanned from each end of the surah.",
    )
    parser.add_argument(
        "--low-conf",
        type=float,
        default=settings.range_matching.low_conf,
        help="Confidence threshold below which a warning is emitted.",
    )
    parser.add_argument(
        "--max-span",
        type=int,
        default=settings.lecture_matching.max_span,
        help="Maximum number of consecutive ayat to match in lecture mode.",
    )
    parser.add_argument(
        "--lecture-threshold",
        type=float,
        default=settings.lecture_matching.min_score,
        help="Minimum confidence for accepting Quran matches in lecture mode.",
    )
    parser.add_argument(
        "--min-matched-words",
        type=int,
        default=settings.lecture_matching.min_matched_words,
        help="Minimum overlapping Quran words required in lecture mode.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the standalone detect-range compatibility CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        run_detection(
            quran=args.quran,
            output=args.output,
            mode=args.mode,
            whisperx=args.whisperx,
            audio=args.audio,
            surah=args.surah,
            head_words=args.head_words,
            tail_words=args.tail_words,
            search_range=args.search_range,
            low_conf=args.low_conf,
            max_span=args.max_span,
            lecture_threshold=args.lecture_threshold,
            min_matched_words=args.min_matched_words,
            echo=True,
        )
    except (FileNotFoundError, ValueError, WhisperXServiceError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0

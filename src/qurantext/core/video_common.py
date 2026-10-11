from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from qurantext.config.settings import get_settings
from qurantext.io.readers import extract_segments, load_json


def ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format ``H:MM:SS.cs``."""
    if not math.isfinite(seconds):
        raise ValueError(f"Timestamp must be finite, got: {seconds!r}")

    total_centiseconds = max(0, int(round(seconds * 100)))
    hours, remainder = divmod(total_centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def escape_ass(text: str) -> str:
    """Escape ASS-sensitive characters and convert newlines to ``\\N``."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    escaped = normalized.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
    return escaped.replace("\n", r"\N")


def ayah_label(match: dict[str, Any]) -> str:
    """Return a user-facing label for one ayah or an ayah range."""
    surah_name = str(match.get("surah_name") or "سورة غير معروفة").strip()
    from_ayah = match.get("from_ayah")
    to_ayah = match.get("to_ayah")

    if isinstance(from_ayah, int) and isinstance(to_ayah, int):
        if from_ayah == to_ayah:
            return f"{surah_name} - الآية {from_ayah}"
        # A hyphen, not an en dash: the bundled Qaloon font has no en dash and draws a blank.
        return f"{surah_name} - الآيات {from_ayah} - {to_ayah}"

    return surah_name


def lecture_intro_lines(matches: list[dict[str, Any]]) -> tuple[str, str] | None:
    """Return ``(surah_name, tadabbur_line)`` for a lecture's opening card.

    The intro announces which ayat the lecture ponders: the surah of the first
    detected ayah, plus the span from the lowest to the highest ayah number
    found within that surah (e.g. ``"تدبر الآيات من الآية 7 إلى الآية 11"``).
    Returns ``None`` when no ayah numbering is available to announce.
    """
    ordered = sorted(matches, key=lambda m: float(m.get("_start_time", math.inf)))

    surah_name = ""
    for match in ordered:
        name = str(match.get("surah_name") or "").strip()
        if name and isinstance(match.get("from_ayah"), int):
            surah_name = name
            break
    if not surah_name:
        return None

    lows: list[int] = []
    highs: list[int] = []
    for match in ordered:
        if str(match.get("surah_name") or "").strip() != surah_name:
            continue
        from_ayah = match.get("from_ayah")
        to_ayah = match.get("to_ayah")
        if isinstance(from_ayah, int):
            lows.append(from_ayah)
            highs.append(to_ayah if isinstance(to_ayah, int) else from_ayah)

    if not lows:
        return None
    from_ayah = min(lows)
    to_ayah = max(highs)

    if from_ayah == to_ayah:
        line = f"تدبر الآية {from_ayah}"
    else:
        line = f"تدبر الآيات من الآية {from_ayah} إلى الآية {to_ayah}"
    return surah_name, line


def _card_surah(card: dict[str, Any]) -> int | str | None:
    surah_num = card.get("surah_num")
    if isinstance(surah_num, int):
        return surah_num
    return str(card.get("surah_name") or "").strip() or None


def _card_span(card: dict[str, Any]) -> tuple[float, float] | None:
    try:
        start = float(card.get("_start_time", card.get("start_time")))
        end = float(card.get("_end_time", card.get("end_time")))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(start) and math.isfinite(end)):
        return None
    return start, end


def cards_on_screen(
    cards: list[dict[str, Any]], mode: str | None, studied_surah: int | None = None
) -> list[dict[str, Any]]:
    """The cards a video draws, out of every card detected for a job.

    A lecture's card shows the surah it studies. Ayat the speaker quotes from
    another surah to explain it are left off the card, which keeps holding the
    studied ayah through the quote; they still appear in the captions, which
    carry everything said. Cards without a surah are kept. A recitation keeps
    every card, since it states its own range and quotes nothing.

    *studied_surah* is the person's own choice (``JobSettings.studied_surah``)
    and is obeyed as given — even when only one surah was heard, and even when
    none of its ayat was, which leaves only the opening title card: the person
    knows which surah the lecture is about better than a count of seconds does.
    Without a choice the studied surah is guessed as the one heard for the most
    time, a tie going to the one heard first.

    The export, the single-frame preview and the review window's live frame all
    call this, so none of them shows a card the others leave out.
    """
    if str(mode or "").lower() != "lecture":
        return list(cards)

    if studied_surah is not None:
        return [
            card
            for card in cards
            if _card_surah(card) is None or card.get("surah_num") == studied_surah
        ]

    heard: dict[int | str, float] = {}
    first: dict[int | str, float] = {}
    for card in cards:
        surah = _card_surah(card)
        span = _card_span(card)
        if surah is None or span is None:
            continue
        start, end = span
        heard[surah] = heard.get(surah, 0.0) + max(0.0, end - start)
        first[surah] = min(first.get(surah, math.inf), start)
    if len(heard) <= 1:
        return list(cards)

    studied = max(heard, key=lambda surah: (heard[surah], -first[surah]))
    return [card for card in cards if _card_surah(card) in (None, studied)]


def has_surah_cards(cards: list[dict[str, Any]], surah: int) -> bool:
    """Whether any of *cards* is an ayah of *surah*.

    A chosen studied surah with no card leaves a lecture with only its opening
    title card, which the review window points out rather than leave a person
    wondering where the ayat went.
    """
    return any(card.get("surah_num") == surah for card in cards)


def warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr)


def _coerce_time(value: Any, field_name: str, match_index: int) -> float:
    try:
        time_value = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"match #{match_index}: invalid {field_name} value {value!r}") from error

    if not math.isfinite(time_value):
        raise ValueError(f"match #{match_index}: {field_name} must be finite")

    return time_value


def _match_confidence(match: dict[str, Any]) -> float:
    try:
        confidence = float(match.get("confidence", 0.0))
    except (TypeError, ValueError):
        return 0.0
    return confidence if math.isfinite(confidence) else 0.0


def _match_display_text(match: dict[str, Any], match_index: int) -> str:
    for key in ("full_text", "full_ayah_text", "text"):
        value = match.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    raise ValueError(
        f"match #{match_index}: missing display text; expected one of "
        f"'full_text', 'full_ayah_text', or 'text'"
    )


def _bridge_match_gaps(matches: list[dict[str, Any]], midpoint_threshold: float) -> None:
    """Close black-screen gaps between consecutive groups, mutating in place.

    Each match only displays during ``[_start_time, _end_time]``, so any gap
    before the next group's first detected word renders as a black screen while
    the reciter is already moving on. Two regimes, by gap size:

    * Gap ``<= midpoint_threshold`` — pull the next group's start back to the
      previous group's end, so the next part appears the instant the previous one
      finishes (small gaps are usually just words the matcher missed).
    * Gap ``> midpoint_threshold`` — a genuine pause; meet in the middle so the
      previous card holds for the first half and the next card appears for the
      second half, instead of sitting idle for the whole pause.

    Overlapping/nested matches are left untouched (no gap to bridge).
    """
    prev_match: dict[str, Any] | None = None
    for match in sorted(matches, key=lambda m: float(m["_start_time"])):
        start = float(match["_start_time"])
        end = float(match["_end_time"])
        if prev_match is not None:
            prev_end = float(prev_match["_end_time"])
            gap = start - prev_end
            if gap > 0:
                if gap <= midpoint_threshold:
                    match["_start_time"] = prev_end
                    match["_duration"] = end - prev_end
                else:
                    midpoint = prev_end + gap / 2.0
                    prev_match["_end_time"] = midpoint
                    prev_match["_duration"] = midpoint - float(prev_match["_start_time"])
                    match["_start_time"] = midpoint
                    match["_duration"] = end - midpoint
        if prev_match is None or end >= float(prev_match["_end_time"]):
            prev_match = match


def validated_matches(
    matches: list[dict[str, Any]], *, bridge_gaps: bool = True
) -> list[dict[str, Any]]:
    """Validate and enrich timed match dictionaries for rendering.

    When *bridge_gaps* is true (the ASS renderer and the default), gaps between
    consecutive matches are closed so the previous card never collapses to black.
    The frame renderer passes ``bridge_gaps=False`` because it *latches* the
    centred ayah instead: the last detected ayah holds until the next one is
    detected, so bridging would only fight that behaviour.
    """
    valid_matches: list[dict[str, Any]] = []
    for match_index, match in enumerate(matches, start=1):
        try:
            start_time = _coerce_time(match.get("start_time"), "start_time", match_index)
            end_time = _coerce_time(match.get("end_time"), "end_time", match_index)
            if end_time <= start_time:
                raise ValueError(
                    f"match #{match_index}: end_time ({end_time}) must be greater than "
                    f"start_time ({start_time})"
                )
            enriched = dict(match)
            enriched["_display_text"] = _match_display_text(match, match_index)
            enriched["_start_time"] = start_time
            enriched["_end_time"] = end_time
            enriched["_duration"] = end_time - start_time
            enriched["_confidence"] = _match_confidence(match)
            enriched["_word_timings"] = list(match.get("word_timings") or [])
            valid_matches.append(enriched)
        except ValueError as error:
            warn(f"Skipping {error}.")

    if bridge_gaps:
        _bridge_match_gaps(valid_matches, get_settings().video.gap_midpoint_threshold)
    return valid_matches


def load_caption_segments(matches_path: Path) -> list[dict[str, Any]]:
    """Load live-transcript caption segments referenced by a matches JSON file.

    The detection step records the raw WhisperX transcript path in
    ``meta.whisperx_raw_output_path``. This reads that transcript and returns one
    ``{"text", "start", "end"}`` entry per WhisperX segment, in time order, for
    the bottom caption band. Captions are best-effort: any problem (missing meta,
    moved/unreadable transcript) logs a warning and returns ``[]`` so the video
    still renders, just without live captions.
    """
    try:
        payload = json.loads(Path(matches_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        warn(f"Could not read matches file for captions ({error}); rendering without captions.")
        return []
    if not isinstance(payload, dict):
        return []

    meta = payload.get("meta")
    # Live captions are a lecture-only feature: a recitation video shows the
    # certified ayah text alone, no spoken-transcript band. Skip silently.
    if isinstance(meta, dict) and str(meta.get("mode") or "").lower() == "recitation":
        return []
    raw_path = meta.get("whisperx_raw_output_path") if isinstance(meta, dict) else None
    if not raw_path:
        warn("Matches file has no transcript path in meta; rendering without live captions.")
        return []

    # The stored path is absolute, but fall back to the transcript sitting next
    # to the matches file in case the project was moved between machines.
    candidates = [Path(raw_path), Path(matches_path).parent / Path(raw_path).name]
    transcript_path = next((p for p in candidates if p.exists()), None)
    if transcript_path is None:
        warn(f"Transcript '{raw_path}' not found; rendering without live captions.")
        return []

    try:
        data = load_json(transcript_path)
    except (OSError, json.JSONDecodeError) as error:
        warn(
            f"Could not parse transcript '{transcript_path}' ({error}); rendering without captions."
        )
        return []

    segments: list[dict[str, Any]] = []
    # Keep the raw spoken text verbatim (strip-only normalizer) so non-Arabic or
    # punctuation-only segments are not dropped from the captions.
    for segment in extract_segments(data, normalizer=lambda text: (text or "").strip()):
        try:
            start = float(segment["start"])
            end = float(segment["end"])
        except (KeyError, TypeError, ValueError):
            continue

        # Prefer the per-word tokens: building the caption text from them keeps
        # the displayed words in lock-step with their timings, so the renderer
        # can highlight the spoken word (the Nth token IS the Nth timing). Fall
        # back to the verbatim segment text when a segment carries no word data.
        word_timings = [
            {"word": w["word"], "start": float(w["start"]), "end": float(w["end"])}
            for w in (segment.get("words") or [])
        ]
        if word_timings:
            text = " ".join(w["word"] for w in word_timings)
        else:
            text = str(segment.get("text_raw") or "").strip()

        if not text or not math.isfinite(start) or not math.isfinite(end) or end < start:
            continue
        segments.append({"text": text, "start": start, "end": end, "word_timings": word_timings})

    segments.sort(key=lambda seg: seg["start"])
    return segments


def bundled_binary_dir() -> Path | None:
    """The folder the running application lives in, when it is a packaged build.

    A packaged app ships FFmpeg beside its own executable, and the person who
    double-clicks it has not put anything on PATH. Looking here first is what
    makes that work.
    """
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent


def require_binary(binary_name: str, install_hint: str | None = None) -> str:
    """Locate a helper binary: beside the application first, then on PATH.

    Order matters. A packaged build must use the FFmpeg it shipped with rather
    than whatever happens to be installed, so the version it was tested against
    is the one that runs.
    """
    bundled = bundled_binary_dir()
    if bundled is not None:
        for candidate in (bundled / binary_name, bundled / f"{binary_name}.exe"):
            if candidate.is_file():
                return str(candidate)

    binary_path = cast(str | None, shutil.which(binary_name))
    if binary_path:
        return binary_path

    hint = f" {install_hint}" if install_hint else ""
    where = " (looked beside the application and on PATH)" if bundled else " in PATH"
    raise RuntimeError(f"{binary_name} was not found{where}.{hint}")


def get_audio_duration(audio_path: Path) -> float:
    """Read audio duration in seconds using ffprobe."""
    ffprobe_path = require_binary(
        "ffprobe",
        "Install FFmpeg/ffprobe and try again.",
    )
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        str(audio_path),
    ]

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "ffprobe could not be executed. Install FFmpeg/ffprobe and ensure it is in PATH."
        ) from error

    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "unknown ffprobe error").strip()
        raise RuntimeError(f"ffprobe failed while reading audio duration: {details}")

    raw_value = (completed.stdout or "").strip()
    try:
        duration = float(raw_value)
    except ValueError as error:
        raise RuntimeError(f"ffprobe returned an invalid duration: {raw_value!r}") from error

    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError(f"ffprobe returned a non-positive duration: {duration!r}")
    return duration


def validate_input_file(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"{label} is not a file: {path}")


def validate_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise ValueError("--width and --height must both be positive integers")


def validate_fps(fps: int) -> None:
    if fps <= 0:
        raise ValueError("--fps must be a positive integer")


def load_matches(matches_path: Path) -> list[dict[str, Any]]:
    try:
        with matches_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as error:
        raise ValueError(f"Failed to parse JSON '{matches_path}': {error}") from error

    if not isinstance(payload, dict):
        raise ValueError("Lecture JSON root must be an object containing a 'matches' list")

    matches = payload.get("matches")
    if matches is None:
        raise ValueError("Lecture JSON is missing the required 'matches' field")
    if not isinstance(matches, list):
        raise ValueError("Lecture JSON field 'matches' must be a list")

    normalized_matches: list[dict[str, Any]] = []
    for index, item in enumerate(matches, start=1):
        if not isinstance(item, dict):
            warn(f"Skipping non-object entry at matches[{index - 1}].")
            continue
        normalized_matches.append(item)
    return normalized_matches

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from qurantext.config.settings import get_settings


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
        return f"{surah_name} - الآيات {from_ayah} – {to_ayah}"

    return surah_name


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


def _bridge_match_gaps(
    matches: list[dict[str, Any]], midpoint_threshold: float
) -> None:
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


def validated_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and enrich timed match dictionaries for rendering."""
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

    _bridge_match_gaps(valid_matches, get_settings().video.gap_midpoint_threshold)
    return valid_matches


def require_binary(binary_name: str, install_hint: str | None = None) -> str:
    binary_path = cast(str | None, shutil.which(binary_name))
    if binary_path:
        return binary_path

    hint = f" {install_hint}" if install_hint else ""
    raise RuntimeError(f"{binary_name} was not found in PATH.{hint}")


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

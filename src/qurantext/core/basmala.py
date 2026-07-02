"""Splice a shipped basmala in front of a recitation video.

Rather than rely on detecting the spoken basmala inside every recitation, the
project ships one clean basmala (``input/basmala/basmala.mp3``) and prepends it
to the recitation at render time — but only when the recording does not already
open with one. The rules (see :func:`should_prepend_basmala`):

* recitation mode only;
* skip At-Tawbah (Surah 9), the one surah with no opening basmala;
* skip when the leading audio already contains a basmala (``preamble.py``
  detected one), so we never double it;
* the basmala file must exist on disk.

When it applies, the basmala audio is concatenated in front of the recitation,
every match/word timing is shifted by the basmala's duration, and a static
(un-highlighted) basmala card is inserted to cover ``[0, duration]``. Detection
stays the authority on whether a basmala is present — this only fills the gap.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qurantext.config.paths import BASMALA_AUDIO_PATH
from qurantext.core.preamble import BASMALA_DISPLAY, BASMALA_LABEL
from qurantext.core.video_common import get_audio_duration, require_binary

# At-Tawbah is the sole surah with no opening basmala, so never prepend one.
SURAH_AT_TAWBAH = 9


@dataclass(frozen=True, slots=True)
class BasmalaPrepend:
    """Result of splicing the basmala: the concatenated audio and new matches."""

    audio_path: Path  # concatenated basmala + recitation (temporary file)
    matches: list[dict[str, Any]]  # basmala card + timing-shifted originals
    offset: float  # seconds the recitation timeline was pushed back


def load_matches_meta(matches_path: str | Path) -> dict[str, Any]:
    """Return the ``meta`` object from a matches JSON file, or ``{}`` on any problem."""
    try:
        payload = json.loads(Path(matches_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    meta = payload.get("meta")
    return meta if isinstance(meta, dict) else {}


def should_prepend_basmala(meta: dict[str, Any], basmala_path: Path = BASMALA_AUDIO_PATH) -> bool:
    """Decide whether to splice our basmala before this recitation (see module docstring)."""
    if str(meta.get("mode") or "").lower() != "recitation":
        return False
    if meta.get("detected_surah_num") == SURAH_AT_TAWBAH:
        return False
    if "basmala" in (meta.get("preamble_segments") or []):
        return False
    return basmala_path.exists()


def basmala_card(duration: float) -> dict[str, Any]:
    """Build a static (un-highlighted) basmala card spanning ``[0, duration]``.

    It carries no ``word_timings``, so the frame renderer shows the whole line
    without a moving highlight — a still basmala frame for the audio's length.
    """
    return {
        "kind": "preamble",
        "preamble_kind": "basmala",
        "surah_name": BASMALA_LABEL,
        "from_ayah": None,
        "to_ayah": None,
        "confidence": 1.0,
        "start_time": 0.0,
        "end_time": round(duration, 2),
        "text": BASMALA_DISPLAY,
        "full_text": BASMALA_DISPLAY,
        "detected_text": "",
        "word_timings": [],
    }


def _shift_time(value: Any, delta: float) -> Any:
    """Shift a numeric timestamp by *delta*; leave non-numeric values untouched."""
    if isinstance(value, (int, float)):
        return round(float(value) + delta, 2)
    return value


def offset_matches(matches: list[dict[str, Any]], delta: float) -> list[dict[str, Any]]:
    """Return *matches* with every card and word start/end pushed back by *delta*.

    Originals are left untouched (shallow-copied); the recitation keeps its whole
    internal timeline, just relocated to start after the prepended basmala.
    """
    shifted: list[dict[str, Any]] = []
    for match in matches:
        new = dict(match)
        new["start_time"] = _shift_time(match.get("start_time"), delta)
        new["end_time"] = _shift_time(match.get("end_time"), delta)
        word_timings = match.get("word_timings")
        if word_timings:
            new["word_timings"] = [
                {
                    **wt,
                    "start": _shift_time(wt.get("start"), delta),
                    "end": _shift_time(wt.get("end"), delta),
                }
                for wt in word_timings
            ]
        shifted.append(new)
    return shifted


def concat_basmala_audio(basmala_path: Path, recitation_path: Path, out_path: Path) -> None:
    """Concatenate ``basmala`` then ``recitation`` into ``out_path`` via FFmpeg.

    Re-encodes through the concat filter so mismatched sample rates/codecs
    between the two sources still join cleanly.
    """
    ffmpeg_path = require_binary("ffmpeg", "Install FFmpeg and try again.")
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(basmala_path),
        "-i",
        str(recitation_path),
        "-filter_complex",
        "[0:a][1:a]concat=n=2:v=0:a=1[out]",
        "-map",
        "[out]",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_path),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "unknown FFmpeg error").strip()
        raise RuntimeError(f"FFmpeg failed while prepending the basmala audio: {details}")


def maybe_prepend_basmala(
    matches_path: str | Path,
    matches: list[dict[str, Any]],
    audio_path: Path,
    *,
    work_dir: Path,
    basmala_path: Path = BASMALA_AUDIO_PATH,
) -> BasmalaPrepend | None:
    """Splice the shipped basmala before *audio_path* when the rules allow it.

    Returns ``None`` (and touches nothing) when no basmala should be prepended.
    Otherwise concatenates the audio into a temporary file inside *work_dir* and
    returns the new audio path plus timing-shifted matches with a basmala card.
    The caller owns the temporary file and should delete it after rendering.
    """
    meta = load_matches_meta(matches_path)
    if not should_prepend_basmala(meta, basmala_path):
        return None

    duration = get_audio_duration(basmala_path)
    work_dir.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        prefix=f"{audio_path.stem}.basmala.",
        suffix=".m4a",
        dir=work_dir,
        delete=False,
    )
    handle.close()
    concat_path = Path(handle.name)
    try:
        concat_basmala_audio(basmala_path, audio_path, concat_path)
    except RuntimeError:
        concat_path.unlink(missing_ok=True)
        raise

    new_matches = [basmala_card(duration)] + offset_matches(matches, duration)
    return BasmalaPrepend(audio_path=concat_path, matches=new_matches, offset=round(duration, 2))

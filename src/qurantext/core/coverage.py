"""Find recited audio that no word covers.

The recogniser can drop speech outright. On Al-Furqān 7-11 it reports a
7.5-second gap between two words, and the waveform in that gap sits two tenths
of a decibel from the level of known recitation either side — seven seconds of
recitation with no word on it. The highlight simply holds while the reciter
carries on. See docs/findings/forced-alignment-prototype.md.

This finds those stretches from the waveform alone. No model, no confidence
score, nothing to train: a gap between words either carries speech-level energy
or it does not. That matters because the same prototype showed an aligner's own
confidence is *higher* where it is wrong, so confidence cannot be what tells a
reviewer where to look. This can.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qurantext.core.video_common import require_binary

__all__ = ["UncoveredSpeech", "find_uncovered_speech", "speech_levels", "uncovered_from_levels"]

#: Analysis frame length. Long enough to be stable, short enough to place a gap.
FRAME_SECONDS = 0.25
#: How far above the noise floor a frame must sit to count as speech.
DEFAULT_MARGIN_DB = 8.0
#: Shorter stretches are breaths and word junctures, not dropped recitation.
DEFAULT_MIN_SECONDS = 1.5


@dataclass(frozen=True, slots=True)
class UncoveredSpeech:
    """A stretch of speech-level audio that no word timing covers."""

    start: float
    end: float
    mean_db: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def describe(self) -> str:
        return (
            f"{self.duration:.1f}s of audio at {self.mean_db:.0f} dBFS carries no word "
            f"({self.start:.1f}s–{self.end:.1f}s)"
        )


def speech_levels(
    audio_path: str | Path, *, frame_seconds: float = FRAME_SECONDS
) -> tuple[list[float], list[float], float]:
    """Return ``(frame_start_times, frame_levels_db, noise_floor_db)``.

    Decodes through FFmpeg to 16 kHz mono, which is both cheap and the same
    representation the recogniser works from.
    """
    import math

    ffmpeg_path = require_binary("ffmpeg", "Install FFmpeg and try again.")
    completed = subprocess.run(
        [
            ffmpeg_path,
            "-v",
            "error",
            "-i",
            str(audio_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "f32le",
            "-",
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        details = (completed.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"FFmpeg failed while reading audio levels: {details}")

    try:
        import numpy as np
    except ModuleNotFoundError as error:  # pragma: no cover - numpy is a dependency
        raise RuntimeError("coverage analysis requires numpy") from error

    samples = np.frombuffer(completed.stdout, dtype=np.float32)
    sample_rate = 16000
    hop = max(1, int(sample_rate * frame_seconds))
    usable = (len(samples) // hop) * hop
    if usable < hop:
        return [], [], -math.inf

    frames = samples[:usable].reshape(-1, hop)
    rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1) + 1e-12)
    db = 20.0 * np.log10(rms)
    floor = float(np.percentile(db, 5))
    times = [i * hop / sample_rate for i in range(len(db))]
    return times, [float(x) for x in db], floor


def find_uncovered_speech(
    audio_path: str | Path,
    word_timings: list[dict[str, Any]],
    *,
    min_seconds: float = DEFAULT_MIN_SECONDS,
    margin_db: float = DEFAULT_MARGIN_DB,
    frame_seconds: float = FRAME_SECONDS,
) -> list[UncoveredSpeech]:
    """Stretches of speech-level audio that fall outside every word's span.

    *word_timings* are ``{"start", "end"}`` dicts; entries without usable
    numbers are ignored rather than treated as covering everything.
    """
    times, levels, floor = speech_levels(audio_path, frame_seconds=frame_seconds)
    return uncovered_from_levels(
        times,
        levels,
        floor,
        word_timings,
        min_seconds=min_seconds,
        margin_db=margin_db,
        frame_seconds=frame_seconds,
    )


def uncovered_from_levels(
    times: list[float],
    levels: list[float],
    floor: float,
    word_timings: list[dict[str, Any]],
    *,
    min_seconds: float = DEFAULT_MIN_SECONDS,
    margin_db: float = DEFAULT_MARGIN_DB,
    frame_seconds: float = FRAME_SECONDS,
) -> list[UncoveredSpeech]:
    """:func:`find_uncovered_speech` on levels already read by :func:`speech_levels`.

    Decoding is the slow half: seconds and hundreds of megabytes for an hour
    of audio. The review window decodes once and re-checks coverage from the
    same levels after every edit, which takes milliseconds. *frame_seconds*
    must be the value the levels were read with.
    """
    if not times:
        return []

    spans = [
        (float(w["start"]), float(w["end"]))
        for w in word_timings
        if isinstance(w.get("start"), (int, float)) and isinstance(w.get("end"), (int, float))
    ]
    spans.sort()

    # Mark every frame a word span touches. Spans overlap and nest freely, so
    # this is painted directly rather than inferred from a sorted walk.
    covered = [False] * len(times)
    for start, end in spans:
        first = max(0, int(start / frame_seconds))
        last = min(len(times) - 1, int((end - 1e-9) / frame_seconds))
        for index in range(first, last + 1):
            covered[index] = True

    threshold = floor + margin_db
    runs: list[list[int]] = []
    for index, level in enumerate(levels):
        if level <= threshold or covered[index]:
            continue
        if runs and index == runs[-1][-1] + 1:
            runs[-1].append(index)
        else:
            runs.append([index])

    found: list[UncoveredSpeech] = []
    for run in runs:
        start = times[run[0]]
        end = times[run[-1]] + frame_seconds
        if end - start < min_seconds:
            continue
        mean_db = sum(levels[i] for i in run) / len(run)
        found.append(UncoveredSpeech(start=round(start, 2), end=round(end, 2), mean_db=mean_db))
    return found

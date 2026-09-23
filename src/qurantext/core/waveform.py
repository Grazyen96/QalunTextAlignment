"""Waveform peaks for the review editor.

The editor draws the recording so a reviewer can see where speech is and where
a word's timing sits against it. Drawing needs only the loudest and quietest
sample in each hundredth of a second, so the audio is streamed through FFmpeg
and reduced as it arrives: an hour of lecture is about 2.9 MB of peaks, where
decoding it whole would hold about 230 MB.

Peaks are cached beside the project, keyed by the audio's bytes, so reopening a
job does not decode the recording again.
"""

from __future__ import annotations

import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from qurantext.core.video_common import require_binary
from qurantext.services.transcript_cache import audio_digest

__all__ = ["Peaks", "compute_peaks", "load_or_compute_peaks"]


@dataclass(frozen=True, slots=True)
class Peaks:
    """Per-bin minimum and maximum sample, ``rate`` bins per second."""

    mins: np.ndarray
    maxs: np.ndarray
    rate: float
    duration: float


def compute_peaks(
    audio: Path,
    *,
    per_second: int = 100,
    sample_rate: int = 16000,
    chunk_seconds: float = 10.0,
) -> Peaks:
    """Stream *audio* through FFmpeg and keep only min/max per bin."""
    ffmpeg = require_binary("ffmpeg", "Install FFmpeg and try again.")
    hop = sample_rate // per_second
    chunk_bytes = max(4, int(sample_rate * chunk_seconds) * 4)
    mins: list[np.ndarray] = []
    maxs: list[np.ndarray] = []
    pending = b""
    carry = np.empty(0, dtype=np.float32)
    total = 0
    with tempfile.TemporaryFile() as errors_file:
        process = subprocess.Popen(
            [
                ffmpeg,
                "-v",
                "error",
                "-i",
                str(audio),
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-f",
                "f32le",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=errors_file,
        )
        try:
            assert process.stdout is not None
            while True:
                block = process.stdout.read(chunk_bytes)
                if not block:
                    break
                block = pending + block
                usable = len(block) - len(block) % 4
                pending = block[usable:]
                samples = np.concatenate([carry, np.frombuffer(block[:usable], dtype=np.float32)])
                total += usable // 4
                whole = (len(samples) // hop) * hop
                if whole:
                    frames = samples[:whole].reshape(-1, hop)
                    mins.append(frames.min(axis=1))
                    maxs.append(frames.max(axis=1))
                carry = samples[whole:]
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stdout is not None:
                process.stdout.close()

        if process.returncode != 0:
            errors_file.seek(0)
            details = errors_file.read().decode("utf-8", "replace").strip()
            raise RuntimeError(f"FFmpeg could not read the audio for the waveform: {details}")

    if len(carry):
        mins.append(np.array([carry.min()], dtype=np.float32))
        maxs.append(np.array([carry.max()], dtype=np.float32))

    empty = np.empty(0, dtype=np.float32)
    return Peaks(
        mins=np.concatenate(mins).astype(np.float32) if mins else empty,
        maxs=np.concatenate(maxs).astype(np.float32) if maxs else empty,
        rate=float(per_second),
        duration=total / sample_rate,
    )


def load_or_compute_peaks(audio: Path, cache_file: Path, *, per_second: int = 100) -> Peaks:
    """Peaks for *audio*, from *cache_file* when it was made from the same bytes."""
    digest = audio_digest(Path(audio))
    try:
        with np.load(cache_file) as cached:
            if str(cached["digest"]) == digest and float(cached["rate"]) == per_second:
                return Peaks(
                    mins=cached["mins"],
                    maxs=cached["maxs"],
                    rate=float(cached["rate"]),
                    duration=float(cached["duration"]),
                )
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, EOFError):
        pass

    peaks = compute_peaks(Path(audio), per_second=per_second)
    try:
        Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
        with Path(cache_file).open("wb") as handle:
            np.savez(
                handle,
                mins=peaks.mins,
                maxs=peaks.maxs,
                rate=peaks.rate,
                duration=peaks.duration,
                digest=digest,
            )
    except OSError:
        pass  # a cache that cannot be written costs a re-decode next time, nothing more
    return peaks

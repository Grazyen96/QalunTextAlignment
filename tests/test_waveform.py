"""Waveform peaks: enough to draw an hour of audio without holding it in memory."""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from qurantext.core import waveform
from qurantext.core.waveform import compute_peaks, load_or_compute_peaks

_FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(not _FFMPEG, reason="needs ffmpeg")


def _tone(path, seconds=3.0, source="sine=frequency=440:sample_rate=16000"):
    subprocess.run(
        [_FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", source, "-t", str(seconds), str(path)],
        check=True,
    )
    return path


def test_a_tone_gives_one_bin_per_hundredth_with_its_amplitude(tmp_path) -> None:
    peaks = compute_peaks(_tone(tmp_path / "t.wav"))
    assert peaks.rate == 100
    assert len(peaks.maxs) == len(peaks.mins) == 300
    assert peaks.duration == pytest.approx(3.0, abs=0.02)
    assert float(np.median(peaks.maxs)) == pytest.approx(0.125, abs=0.01)
    assert float(np.median(peaks.mins)) == pytest.approx(-0.125, abs=0.01)


def test_silence_is_flat(tmp_path) -> None:
    peaks = compute_peaks(_tone(tmp_path / "s.wav", source="anullsrc=r=16000:cl=mono"))
    assert float(np.abs(peaks.maxs).max()) == 0.0


def test_chunk_size_does_not_change_the_result(tmp_path) -> None:
    audio = _tone(tmp_path / "t.wav", seconds=1.0)
    whole = compute_peaks(audio)
    ragged = compute_peaks(audio, chunk_seconds=0.013)
    np.testing.assert_array_equal(whole.maxs, ragged.maxs)
    np.testing.assert_array_equal(whole.mins, ragged.mins)


def test_the_cache_is_reused_until_the_audio_changes(tmp_path, monkeypatch) -> None:
    audio = _tone(tmp_path / "t.wav", seconds=1.0)
    cache = tmp_path / "t.peaks.npz"
    first = load_or_compute_peaks(audio, cache)
    assert cache.exists()

    calls = []
    real = waveform.compute_peaks
    monkeypatch.setattr(waveform, "compute_peaks", lambda *a, **k: calls.append(1) or real(*a, **k))
    again = load_or_compute_peaks(audio, cache)
    assert calls == []
    np.testing.assert_array_equal(first.maxs, again.maxs)

    _tone(audio, seconds=2.0)
    changed = load_or_compute_peaks(audio, cache)
    assert calls == [1] and len(changed.maxs) == 200


def test_unreadable_audio_says_so(tmp_path) -> None:
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not audio")
    with pytest.raises(RuntimeError, match="FFmpeg"):
        compute_peaks(bad)

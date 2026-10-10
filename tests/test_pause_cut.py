from __future__ import annotations

import numpy as np

from qurantext.core.pause_cut import SAMPLE_RATE, PauseCutter

SR = SAMPLE_RATE


def _noise(seconds: float, seed: int = 0) -> np.ndarray:
    return (np.random.default_rng(seed).standard_normal(int(seconds * SR)) * 0.3).astype(np.float32)


def _run(audio: np.ndarray, block_seconds: float = 1.0, **kw):
    cutter = PauseCutter(**kw)
    windows = []
    step = int(block_seconds * SR)
    for i in range(0, len(audio), step):
        windows += cutter.feed(audio[i : i + step])
    return windows + cutter.flush()


def test_a_short_clip_is_one_window() -> None:
    windows = _run(_noise(5))
    assert len(windows) == 1
    assert windows[0][0] == 0 and len(windows[0][1]) == 5 * SR


def test_windows_never_exceed_28_seconds_and_cover_everything() -> None:
    audio = _noise(200)
    windows = _run(audio)
    assert all(len(w) <= 28 * SR for _, w in windows)
    assert sum(len(w) for _, w in windows) == len(audio)
    starts = [s for s, _ in windows]
    assert starts == sorted(starts) and starts[0] == 0
    for (s, w), (s2, _) in zip(windows, windows[1:], strict=False):
        assert s + len(w) == s2


def test_the_cut_lands_on_the_pause() -> None:
    audio = _noise(40)
    audio[int(22.0 * SR) : int(22.3 * SR)] = 0.0  # a waqf
    windows = _run(audio)
    assert abs(len(windows[0][1]) / SR - 22.0) <= 0.1


def test_silence_only_audio_is_one_window_per_28s() -> None:
    windows = _run(np.zeros(60 * SR, dtype=np.float32))
    assert sum(len(w) for _, w in windows) == 60 * SR
    assert all(len(w) <= 28 * SR for _, w in windows)


def test_the_buffer_stays_bounded_on_long_audio() -> None:
    cutter = PauseCutter()
    block = _noise(1)
    for _ in range(600):  # ten minutes
        cutter.feed(block)
        assert cutter.buffered_samples < 29 * SR


def test_an_empty_feed_is_harmless() -> None:
    cutter = PauseCutter()
    assert cutter.feed(np.zeros(0, dtype=np.float32)) == []
    assert cutter.flush() == []

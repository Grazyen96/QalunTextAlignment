"""Cut a stream of audio into recognisable windows, at pauses.

The recogniser takes at most about thirty seconds at a time. Cutting blindly
splits a word in two, so each cut lands on the quietest tenth of a second in the
window's last ten seconds, which in recitation is nearly always a waqf. Audio is
fed in blocks as it is decoded, so an hour-long lecture is never in memory whole.
"""

from __future__ import annotations

import numpy as np

__all__ = ["SAMPLE_RATE", "PauseCutter"]

SAMPLE_RATE = 16000


class PauseCutter:
    """Accumulates audio blocks and hands back windows of at most *max_seconds*."""

    def __init__(
        self,
        *,
        max_seconds: float = 28.0,
        search_seconds: float = 10.0,
        frame_seconds: float = 0.1,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        self._max = int(max_seconds * sample_rate)
        self._search = int(search_seconds * sample_rate)
        self._frame = int(frame_seconds * sample_rate)
        self._buf = np.zeros(0, dtype=np.float32)
        self._offset = 0

    @property
    def buffered_samples(self) -> int:
        return len(self._buf)

    def feed(self, block: np.ndarray) -> list[tuple[int, np.ndarray]]:
        if len(block):
            self._buf = np.concatenate([self._buf, block.astype(np.float32, copy=False)])
        windows = []
        while len(self._buf) >= self._max:
            cut = self._quietest_cut()
            windows.append((self._offset, self._buf[:cut].copy()))
            self._buf = self._buf[cut:]
            self._offset += cut
        return windows

    def flush(self) -> list[tuple[int, np.ndarray]]:
        if not len(self._buf):
            return []
        window = (self._offset, self._buf.copy())
        self._offset += len(self._buf)
        self._buf = np.zeros(0, dtype=np.float32)
        return [window]

    def _quietest_cut(self) -> int:
        lo = self._max - self._search
        region = self._buf[lo : self._max]
        frames = len(region) // self._frame
        if frames == 0:
            return self._max
        rms = np.sqrt(
            np.mean(region[: frames * self._frame].reshape(frames, self._frame) ** 2, axis=1)
        )
        cut = lo + int(np.argmin(rms)) * self._frame
        return cut if cut > 0 else self._max

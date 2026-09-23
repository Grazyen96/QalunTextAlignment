"""Playback behind a small interface, so the window never depends on Qt Multimedia directly.

The window always talks to a :class:`Player`. Most of the time that is a
:class:`QtPlayer` wrapping ``QMediaPlayer``; in a build without Qt Multimedia
Addons, or when construction fails for any other reason, :func:`create_player`
falls back to the base :class:`Player`, which is a real, usable object whose
methods are safe no-ops — the window still opens, the waveform and word strip
still work, and only sound and the live playhead are unavailable. Tests use
:class:`FakePlayer`, which behaves like a real player without touching Qt
Multimedia at all.

Position is smoothed by :class:`PlaybackClock`, pure Python with no Qt, so it
is trivial to test on its own.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from qurantext.gui.i18n import t

__all__ = ["RATES", "FakePlayer", "PlaybackClock", "Player", "QtPlayer", "create_player"]

#: Playback speeds offered in the window, fastest first.
RATES = (1.0, 0.75, 0.5)


class PlaybackClock:
    """Where playback is now, between the player's coarse position reports.

    Qt reports the position every few tens of milliseconds, which makes a
    running highlight stutter. Between reports this extrapolates on a monotonic
    clock at the playback rate, re-anchors on every report, and never steps
    backwards on a report that is merely a little late — only a seek or a real
    jump (more than :data:`JUMP_S`) moves it back.
    """

    JUMP_S = 0.25

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._anchor = 0.0
        self._anchor_at = now()
        self._playing = False
        self._rate = 1.0
        self._last = 0.0

    def _extrapolated(self) -> float:
        if not self._playing:
            return self._anchor
        return self._anchor + (self._now() - self._anchor_at) * self._rate

    def _anchor_to(self, position: float) -> None:
        self._anchor = float(position)
        self._anchor_at = self._now()

    def report(self, position_s: float) -> None:
        current = self._extrapolated()
        if position_s < current - self.JUMP_S:
            self._last = float(position_s)
        self._anchor_to(position_s)

    def seek(self, position_s: float) -> None:
        self._anchor_to(position_s)
        self._last = float(position_s)

    def set_playing(self, playing: bool) -> None:
        self._anchor_to(self._extrapolated())
        self._playing = bool(playing)

    def set_rate(self, rate: float) -> None:
        self._anchor_to(self._extrapolated())
        self._rate = float(rate)

    def position(self) -> float:
        value = self._extrapolated()
        if self._playing:
            value = max(value, self._last)
        self._last = value
        return value


class Player(QObject):
    """The interface the window uses, and an unavailable player by default.

    A subclass that fails to construct (missing Addons, a bad device) is
    replaced by a bare ``Player``: every method is a safe no-op, ``seek``
    still records the position so a click on the waveform still moves the
    playhead, and ``reason`` explains why there is no sound.
    """

    #: Whether playback just started or stopped.
    playing_changed = Signal(bool)
    #: The loaded media's duration, in seconds.
    duration_changed = Signal(float)
    #: Something went wrong; carries a message already fit to show a person.
    error = Signal(str)

    def __init__(self, parent: QObject | None = None, *, reason: str = "") -> None:
        super().__init__(parent)
        self._reason = reason
        self._position = 0.0
        self._duration = 0.0
        self._rate = 1.0

    @property
    def available(self) -> bool:
        return False

    @property
    def reason(self) -> str:
        return self._reason

    def load(self, path: Path) -> None:
        pass

    def play(self) -> None:
        pass

    def pause(self) -> None:
        pass

    def toggle(self) -> None:
        pass

    def seek(self, seconds: float) -> None:
        self._position = float(seconds)

    def position(self) -> float:
        return self._position

    def duration(self) -> float:
        return self._duration

    def is_playing(self) -> bool:
        return False

    def set_rate(self, rate: float) -> None:
        self._rate = float(rate)

    def rate(self) -> float:
        return self._rate


class FakePlayer(Player):
    """A player that behaves like a real one without touching Qt Multimedia.

    Tests drive it with an injectable clock, so they can advance playback time
    explicitly instead of waiting on a real audio device.
    """

    def __init__(
        self,
        duration: float = 60.0,
        *,
        now: Callable[[], float] = time.monotonic,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._load_duration = duration
        self._clock = PlaybackClock(now)
        self._playing = False

    @property
    def available(self) -> bool:
        return True

    def load(self, path: Path) -> None:
        self._duration = self._load_duration
        self.duration_changed.emit(self._duration)

    def play(self) -> None:
        if self._playing:
            return
        self._playing = True
        self._clock.set_playing(True)
        self.playing_changed.emit(True)

    def pause(self) -> None:
        if not self._playing:
            return
        self._playing = False
        self._clock.set_playing(False)
        self.playing_changed.emit(False)

    def toggle(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    def seek(self, seconds: float) -> None:
        self._clock.seek(seconds)

    def position(self) -> float:
        return self._clock.position()

    def is_playing(self) -> bool:
        return self._playing

    def set_rate(self, rate: float) -> None:
        self._rate = float(rate)
        self._clock.set_rate(rate)


class QtPlayer(Player):
    """Real playback: ``QMediaPlayer`` plus ``QAudioOutput``, smoothed by :class:`PlaybackClock`."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        #: Stashed so every other method can use them without importing Addons itself.
        self._make_url = QUrl.fromLocalFile
        self._playing_state = QMediaPlayer.PlaybackState.PlayingState

        self._clock = PlaybackClock()
        self._media_player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._media_player.setAudioOutput(self._audio_output)
        self._media_player.positionChanged.connect(self._on_position_changed)
        self._media_player.durationChanged.connect(self._on_duration_changed)
        self._media_player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._media_player.errorOccurred.connect(self._on_error_occurred)

    @property
    def available(self) -> bool:
        return True

    def _on_position_changed(self, position_ms: int) -> None:
        self._clock.report(position_ms / 1000.0)

    def _on_duration_changed(self, duration_ms: int) -> None:
        self._duration = duration_ms / 1000.0
        self.duration_changed.emit(self._duration)

    def _on_playback_state_changed(self, state: object) -> None:
        playing = state == self._playing_state
        self._clock.set_playing(playing)
        self.playing_changed.emit(playing)

    def _on_error_occurred(self, error: object, error_string: str) -> None:
        self.error.emit(error_string)

    def load(self, path: Path) -> None:
        self._media_player.setSource(self._make_url(str(path)))

    def play(self) -> None:
        self._media_player.play()

    def pause(self) -> None:
        self._media_player.pause()

    def toggle(self) -> None:
        if self.is_playing():
            self.pause()
        else:
            self.play()

    def seek(self, seconds: float) -> None:
        self._clock.seek(seconds)
        self._media_player.setPosition(int(seconds * 1000))

    def position(self) -> float:
        return max(0.0, min(self._clock.position(), self._duration))

    def is_playing(self) -> bool:
        return self._media_player.playbackState() == self._playing_state

    def set_rate(self, rate: float) -> None:
        self._rate = float(rate)
        self._media_player.setPlaybackRate(rate)


def create_player(parent: QObject | None = None) -> Player:
    """The best player available: real playback, or an unavailable one that explains why."""
    try:
        from PySide6 import QtMultimedia  # noqa: F401
    except Exception as error:  # noqa: BLE001 - any failure falls back gracefully
        return Player(parent, reason=t("player.unavailable", details=str(error)))
    try:
        return QtPlayer(parent)
    except Exception as error:  # noqa: BLE001 - any failure falls back gracefully
        return Player(parent, reason=t("player.unavailable", details=str(error)))

"""Playback: a smoothed clock, a fake for tests, and a graceful absence."""

from __future__ import annotations

import builtins

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from qurantext.gui.review.player import RATES, PlaybackClock


class _Now:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def test_the_clock_runs_between_reports_at_the_rate() -> None:
    now = _Now()
    clock = PlaybackClock(now)
    clock.report(10.0)
    clock.set_playing(True)
    now.t += 0.5
    assert clock.position() == pytest.approx(10.5)
    clock.set_rate(0.5)
    now.t += 1.0
    assert clock.position() == pytest.approx(11.0)


def test_the_clock_holds_when_paused() -> None:
    now = _Now()
    clock = PlaybackClock(now)
    clock.report(3.0)
    now.t += 5.0
    assert clock.position() == 3.0


def test_a_slightly_late_report_does_not_run_the_clock_backwards() -> None:
    now = _Now()
    clock = PlaybackClock(now)
    clock.report(10.0)
    clock.set_playing(True)
    now.t += 0.3
    seen = clock.position()
    clock.report(10.2)
    assert clock.position() >= seen


def test_a_seek_or_a_real_jump_resets_it() -> None:
    now = _Now()
    clock = PlaybackClock(now)
    clock.report(50.0)
    clock.set_playing(True)
    now.t += 1.0
    clock.seek(5.0)
    assert clock.position() == pytest.approx(5.0)
    clock.report(1.0)
    assert clock.position() == pytest.approx(1.0)


def test_rates_offered() -> None:
    assert RATES == (1.0, 0.75, 0.5)


def test_fake_player_plays_seeks_and_signals(qt_app) -> None:
    from qurantext.gui.review.player import FakePlayer

    now = _Now()
    player = FakePlayer(duration=30.0, now=now)
    states, durations = [], []
    player.playing_changed.connect(states.append)
    player.duration_changed.connect(durations.append)
    player.load(__import__("pathlib").Path("x.mp3"))
    assert durations == [30.0] and player.available
    player.seek(4.0)
    player.play()
    now.t += 2.0
    assert player.position() == pytest.approx(6.0)
    player.toggle()
    assert states == [True, False] and not player.is_playing()


def test_without_qt_multimedia_the_player_explains_itself(qt_app, monkeypatch) -> None:
    from qurantext.gui.review import player as player_module

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith("PySide6.QtMultimedia"):
            raise ImportError("No module named 'PySide6.QtMultimedia'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    player = player_module.create_player()
    assert not player.available
    assert "QtMultimedia" in player.reason
    player.play()
    assert not player.is_playing()


def test_qt_player_loads_when_multimedia_is_installed(qt_app, tmp_path) -> None:
    pytest.importorskip("PySide6.QtMultimedia")
    from qurantext.gui.review.player import QtPlayer, create_player

    assert isinstance(create_player(), QtPlayer)

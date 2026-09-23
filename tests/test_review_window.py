"""The review window, assembled, with a fake player."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from qurantext.gui.review.player import FakePlayer  # noqa: E402
from qurantext.jobs.project import Project, load_project, save_project  # noqa: E402


class _Now:
    t = 0.0

    def __call__(self):
        return self.t


def _project(tmp_path):
    cards = [
        {
            "surah_num": 25,
            "from_ayah": 7,
            "to_ayah": 7,
            "full_text": "a b",
            "confidence": 1.0,
            "start_time": 0.0,
            "end_time": 10.0,
            "word_timings": [
                {"word": "a", "start": 1.0, "end": 2.0},
                {"word": "b", "start": 2.0, "end": 3.0},
            ],
        }
    ]
    matches = tmp_path / "m.json"
    matches.write_text(
        json.dumps({"matches": cards, "meta": {"mode": "recitation"}}), encoding="utf-8"
    )
    project = Project(audio=tmp_path / "missing.mp3", cards=cards, matches=matches)
    save_project(project, tmp_path / "m.qalun.json")
    return project


def _window(qt_app, tmp_path):
    from qurantext.gui.review.window import ReviewWindow

    now = _Now()
    player = FakePlayer(duration=10.0, now=now)
    window = ReviewWindow(_project(tmp_path), player=player)
    window.resize(1100, 800)
    return window, player, now


def test_it_opens_on_a_missing_recording_and_says_so(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    QTest.qWait(50)
    assert "missing.mp3" in window.warnings.text()


def test_keyboard_steps_and_sets_edges_at_the_playhead(qt_app, tmp_path) -> None:
    window, player, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Right)
    assert window.strip.selected.word == 1
    player.seek(2.4)
    QTest.keyClick(window, Qt.Key.Key_BracketLeft)
    assert window.session.words()[1].start == pytest.approx(2.4)
    QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert window.session.words()[1].start == 2.0


def test_nudge_moves_the_end_by_fifty_milliseconds(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
    assert window.session.words()[0].end == pytest.approx(2.05)


def test_ctrl_s_saves_and_the_title_loses_its_marker(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
    assert window.windowTitle().endswith("*")
    QTest.keyClick(window, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert not window.windowTitle().endswith("*")
    assert load_project(window.session.project.path).cards[0]["word_timings"][0]["end"] == 2.05


@pytest.mark.parametrize(
    ("answer", "closes", "saved"),
    [("cancel", False, False), ("discard", True, False), ("save", True, True)],
)
def test_closing_with_changes_asks(qt_app, tmp_path, monkeypatch, answer, closes, saved) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
    monkeypatch.setattr(window, "_confirm_discard", lambda: answer)
    window.close()
    assert window.isVisible() is (not closes)
    stored = load_project(window.session.project.path).cards[0]["word_timings"][0]["end"]
    assert (stored == 2.05) is saved


def test_without_playback_the_window_still_edits(qt_app, tmp_path) -> None:
    from qurantext.gui.review.player import Player
    from qurantext.gui.review.window import ReviewWindow

    window = ReviewWindow(_project(tmp_path), player=Player(reason="no audio backend"))
    window.show()
    assert not window.play_button.isEnabled()
    assert "no audio backend" in window.play_button.toolTip()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
    assert window.session.dirty


def test_shift_nudges_by_ten_milliseconds(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period, Qt.KeyboardModifier.ShiftModifier)
    assert window.session.words()[0].end == pytest.approx(2.01)


def test_gaps_are_listed_with_a_jump_that_seeks_and_stale_checks_are_dropped(
    qt_app, tmp_path
) -> None:
    from qurantext.core.coverage import UncoveredSpeech

    window, player, _ = _window(qt_app, tmp_path)
    gap = UncoveredSpeech(start=4.0, end=6.0, mean_db=-20.0)
    window._on_coverage((window._coverage_generation - 1, [gap]))
    assert "Jump" not in window.warnings.text()
    window._on_coverage((window._coverage_generation, [gap]))
    assert "2.0 s at 4.0–6.0 s" in window.warnings.text()
    window.warnings.linkActivated.emit("4.000")
    assert player.position() == pytest.approx(4.0)
    assert window.time_label.text() == "00:04.00"


def test_the_zoom_slider_runs_from_the_whole_recording_to_one_second(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.zoom_slider.setValue(window.zoom_slider.maximum())
    assert window.viewport.span == pytest.approx(1.0)
    window.zoom_slider.setValue(0)
    assert window.viewport.span == pytest.approx(window.viewport.duration)

"""The review window, assembled, with a fake player."""

from __future__ import annotations

import json
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from qurantext.gui.review.player import FakePlayer  # noqa: E402
from qurantext.jobs.project import (  # noqa: E402
    Project,
    load_project,
    project_path_for,
    save_project,
)
from tests.media_helpers import MEDIA_AVAILABLE, MEDIA_REASON, build_job  # noqa: E402


@pytest.fixture(autouse=True)
def _no_window_outlives_its_test(qt_app):
    """Hide and delete every window a test leaves open.

    A window left shown can become the active one once a later test spins the
    event loop, and a ``QShortcut`` fires for the active window, so a later
    test's key clicks would edit the earlier test's window instead of its own.
    """
    yield
    from PySide6.QtCore import QEvent

    for widget in qt_app.topLevelWidgets():
        widget.hide()
        widget.deleteLater()
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class _Now:
    t = 0.0

    def __call__(self):
        return self.t


def _wait_for(condition, timeout_ms):
    """Spin the event loop until *condition()* holds (PySide6's QTest has no qWaitFor)."""
    deadline = time.monotonic() + timeout_ms / 1000
    while not condition():
        if time.monotonic() > deadline:
            return False
        QTest.qWait(20)
    return True


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


def _levels_with_speech_between(start, end):
    """Synthetic speech levels: 10 s of silence at -60 dB, loud from *start* to *end*."""
    times = [i * 0.25 for i in range(40)]
    levels = [-10.0 if start <= t < end else -60.0 for t in times]
    return times, levels, -60.0


def test_gaps_are_listed_with_a_jump_and_rechecked_from_the_cached_levels(qt_app, tmp_path) -> None:
    window, player, _ = _window(qt_app, tmp_path)
    window.show()
    window._on_levels(_levels_with_speech_between(4.0, 6.0))
    assert "2.0 s at 4.0–6.0 s" in window.warnings.text()
    window.warnings.linkActivated.emit("4.000")
    assert player.position() == pytest.approx(4.0)
    assert window.time_label.text() == "00:04.00"

    window._coverage_timer.setInterval(0)
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Right)
    player.seek(6.0)
    QTest.keyClick(window, Qt.Key.Key_BracketRight)
    assert _wait_for(lambda: "covered by a word" in window.warnings.text(), 1000)
    assert "Jump" not in window.warnings.text()


def test_the_zoom_slider_runs_from_the_whole_recording_to_one_second(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.zoom_slider.setValue(window.zoom_slider.maximum())
    assert window.viewport.span == pytest.approx(1.0)
    window.zoom_slider.setValue(0)
    assert window.viewport.span == pytest.approx(window.viewport.duration)


def test_a_notice_that_arrives_twice_is_listed_once(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.warnings.add_notice("FFmpeg failed")
    window.warnings.add_notice("FFmpeg failed")
    assert window.warnings.text().count("FFmpeg failed") == 1


def test_a_caption_editor_stays_open_while_the_recording_plays(qt_app, tmp_path) -> None:
    from PySide6.QtWidgets import QAbstractItemView

    from qurantext.gui.review.window import ReviewWindow
    from qurantext.jobs.project import CaptionCue

    def cue(start, first, second):
        words = [
            {"word": first, "start": start, "end": start + 1.0},
            {"word": second, "start": start + 1.0, "end": start + 2.0},
        ]
        return CaptionCue(start, start + 2.0, f"{first} {second}", words=words)

    project = Project(
        audio=tmp_path / "missing.mp3",
        mode="lecture",
        captions=[cue(0.0, "one", "two"), cue(2.0, "three", "four")],
    )
    player = FakePlayer(duration=4.0, now=_Now())
    window = ReviewWindow(project, player=player)
    window.show()
    listing = window.segment_list
    # As a double-click does: the edited cell becomes current, then its editor opens.
    listing.setCurrentCell(0, 2)
    listing.editItem(listing.item(0, 2))
    assert listing.state() == QAbstractItemView.State.EditingState
    for position in (0.2, 0.5, 1.5, 2.5, 3.0):
        player.seek(position)
        window._tick()
        assert listing.state() == QAbstractItemView.State.EditingState, position


def test_a_window_shown_again_after_closing_still_asks_about_changes(
    qt_app, tmp_path, monkeypatch
) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    window.close()
    assert not window.isVisible()
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
    asked = []
    monkeypatch.setattr(window, "_confirm_discard", lambda: asked.append(True) or "cancel")
    window.close()
    assert asked
    assert window.isVisible()


def test_a_nudge_moves_the_edge_last_grabbed(qt_app, tmp_path) -> None:
    from PySide6.QtCore import QPoint

    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    strip = window.strip
    x = round(window.viewport.x_for(1.0, strip.width()))
    at = QPoint(x, strip.height() // 2)
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    assert strip.last_edge == "start"
    QTest.keyClick(window, Qt.Key.Key_Period)
    assert window.session.words()[0].start == pytest.approx(1.05)
    assert window.session.words()[0].end == pytest.approx(2.0)
    QTest.keyClick(window, Qt.Key.Key_Right)
    assert strip.last_edge == "end"


@pytest.mark.skipif(not MEDIA_AVAILABLE, reason=MEDIA_REASON)
def test_a_real_recording_is_read_in_the_background_and_close_stops_it(qt_app, tmp_path) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.window import ReviewWindow

    audio, matches = build_job(tmp_path, seconds=6.0)
    project = Project.from_match_file(matches, audio)
    save_project(project, project_path_for(matches))
    player = FakePlayer(duration=6.0)
    window = ReviewWindow(project, player=player)
    window.show()

    def read() -> bool:
        text = window.warnings.text()
        return window.waveform.peaks is not None and (t("review.covered") in text or "Jump" in text)

    assert _wait_for(read, 30000)
    player.play()
    assert window._timer.isActive()
    window.close()
    assert window._jobs.active == 0
    assert not player.is_playing()
    assert not window._timer.isActive()


def test_a_later_measured_length_keeps_the_chosen_zoom(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window._set_duration(12.0)
    window.zoom_slider.setValue(window.zoom_slider.maximum())
    assert window.viewport.span == pytest.approx(1.0)
    window._set_duration(12.5)
    assert window.viewport.duration == pytest.approx(12.5)
    assert window.viewport.span == pytest.approx(1.0)


def test_remove_selected_deletes_the_row_and_undo_restores_it(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    assert len(window.session.project.cards) == 1
    window.segment_list.selectRow(0)
    window.remove_button.click()
    assert len(window.session.project.cards) == 0
    QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert len(window.session.project.cards) == 1


def test_remove_with_nothing_selected_says_so_without_a_modal(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    window.segment_list.clearSelection()
    window.remove_button.click()
    from qurantext.gui.i18n import t

    assert window.statusBar().currentMessage() == t("review.remove_none")
    assert len(window.session.project.cards) == 1


@pytest.mark.skipif(not MEDIA_AVAILABLE, reason=MEDIA_REASON)
def test_export_writes_the_chosen_formats_and_saves_first(qt_app, tmp_path, store) -> None:
    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.session import CARD, ReviewSession, WordRef

    audio, matches = build_job(tmp_path)
    project = Project.from_match_file(matches, audio)
    save_project(project, tmp_path / "job.qalun.json")
    session = ReviewSession(project)
    session.retime(WordRef(CARD, 0, 1), start=0.45)
    dialog = ExportDialog(session, db_path=store)
    dialog.set_formats(("srt", "vtt"))
    dialog.set_destination(tmp_path / "out", "clip")
    written = dialog.export()
    assert sorted(p.suffix for p in written) == [".srt", ".vtt"]
    assert not session.dirty, "unsaved edits are saved before exporting"


def test_export_on_the_video_timeline_is_offered_only_after_a_render(qt_app, tmp_path) -> None:
    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.session import ReviewSession

    project = _project(tmp_path)
    assert not ExportDialog(ReviewSession(project)).video_timeline_available()
    project.record_render(tmp_path / "v.mp4", preset="social", basmala_offset_s=1.0)
    dialog = ExportDialog(ReviewSession(project))
    assert dialog.video_timeline_available() and dialog.timeline() == "video"


def test_render_with_corrections_saves_then_renders_the_project(
    qt_app, tmp_path, monkeypatch
) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.gui.jobs import JobOutcome

    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
    seen = {}

    def fake_render(project, **kwargs):
        seen["end"] = project.cards[0]["word_timings"][0]["end"]
        seen["saved"] = load_project(project.path).cards[0]["word_timings"][0]["end"]
        return JobOutcome(
            matches=project.matches, video=tmp_path / "v.mp4", cards=1, mode="recitation"
        )

    monkeypatch.setattr(jobs_module, "run_render", fake_render)
    monkeypatch.setattr(
        window, "_announce_render", lambda outcome: seen.setdefault("done", outcome)
    )
    window.render_requested.emit()
    # PySide6's QTest has no qWaitFor; _wait_for above (in this file) is its replacement.
    assert _wait_for(lambda: "done" in seen, 5000)
    assert seen["end"] == 2.05 and seen["saved"] == 2.05


def test_render_disables_editing_actions_until_done(qt_app, tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.gui.jobs import JobOutcome

    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
    seen = {}

    def fake_render(project, **kwargs):
        return JobOutcome(
            matches=project.matches, video=tmp_path / "v.mp4", cards=1, mode="recitation"
        )

    monkeypatch.setattr(jobs_module, "run_render", fake_render)
    monkeypatch.setattr(
        window, "_announce_render", lambda outcome: seen.setdefault("done", outcome)
    )
    assert window.session.can_undo
    window.render_requested.emit()
    assert not window.render_button.isEnabled()
    assert not window.undo_button.isEnabled()
    assert not window.remove_button.isEnabled()
    # "done" (set by _announce_render) and the button re-enabling (set by the
    # worker's separate `done` signal) are two different queued callbacks, so
    # wait for the one this test actually checks rather than the other.
    assert _wait_for(lambda: not window._rendering, 5000)
    assert "done" in seen
    assert window.render_button.isEnabled()
    assert window.undo_button.isEnabled()
    assert window.remove_button.isEnabled()

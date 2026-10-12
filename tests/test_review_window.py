"""The review window, assembled, with a fake player."""

from __future__ import annotations

import html
import json
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from qurantext.gui.i18n import t  # noqa: E402
from qurantext.gui.review.player import FakePlayer  # noqa: E402
from qurantext.jobs.project import (  # noqa: E402
    CaptionCue,
    Project,
    load_project,
    project_path_for,
    save_project,
)
from tests.media_helpers import MEDIA_AVAILABLE, MEDIA_REASON, build_job  # noqa: E402
from tests.qt_helpers import spin as _spin  # noqa: E402
from tests.qt_helpers import wait_for as _wait_for  # noqa: E402


@pytest.fixture(autouse=True)
def _no_window_outlives_its_test(qt_app):
    """Hide and delete every window a test leaves open.

    A window left shown can become the active one once a later test spins the
    event loop, and a ``QShortcut`` fires for the active window, so a later
    test's key clicks would edit the earlier test's window instead of its own.

    It also lets go of any modifier a test's hand-made key press left held: Qt
    keeps the last press's modifiers as the application's, and a later
    ``selectRow`` reads a leftover Shift as "extend the selection" and selects
    nothing.
    """
    yield
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QWidget

    QTest.keyRelease(QWidget(), Qt.Key.Key_Shift)
    for widget in qt_app.topLevelWidgets():
        widget.hide()
        widget.deleteLater()
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def _no_real_settings(monkeypatch, tmp_path):
    """A window built without ``prefs`` gets settings under tmp_path, never the person's.

    "Use for new videos" writes the default look; a test clicking it on a
    window made without ``prefs`` would otherwise write to the real settings.
    """
    from PySide6.QtCore import QSettings

    from qurantext.gui.prefs import Prefs
    from qurantext.gui.review import window as window_module

    ini = str(tmp_path / "window-prefs.ini")
    monkeypatch.setattr(
        window_module, "Prefs", lambda: Prefs(QSettings(ini, QSettings.Format.IniFormat))
    )


class _Now:
    t = 0.0

    def __call__(self):
        return self.t


def test_waiting_lets_worker_threads_run_python(qt_app) -> None:
    """``_wait_for`` must release the GIL while it spins the event loop.

    ``QTest.qWait`` holds it throughout, so a worker thread needing it again
    and again (every signal it emits, every Python line) crawls, and one that
    needs it while holding a Qt lock the UI thread wants deadlocks — the full
    suite hung that way inside ``_wait_for``. This worker takes the GIL back
    50 times; while ``QTest.qWait`` spun, each took up to a whole wait slice.
    """
    import threading

    done = threading.Event()

    def worker() -> None:
        for _ in range(50):
            time.sleep(0.001)  # gives the GIL up, then needs it back
        done.set()

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert _wait_for(done.is_set, 500)
    finally:
        thread.join()


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
    _spin(50)
    assert "missing.mp3" in window.warnings.text()


def test_keyboard_steps_and_sets_edges_at_the_playhead(qt_app, tmp_path) -> None:
    window, player, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Left)
    assert window.strip.selected.word == 1
    player.seek(2.4)
    QTest.keyClick(window, Qt.Key.Key_BracketLeft)
    assert window.session.words()[1].start == pytest.approx(2.4)
    QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert window.session.words()[1].start == 2.0


def test_left_steps_to_the_next_word_and_right_to_the_previous(qt_app, tmp_path) -> None:
    window, player, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Left)
    assert window.strip.selected.word == 0, "from no selection, Left starts at the first word"
    QTest.keyClick(window, Qt.Key.Key_Left)
    assert window.strip.selected.word == 1
    assert player.position() == pytest.approx(2.0)
    QTest.keyClick(window, Qt.Key.Key_Right)
    assert window.strip.selected.word == 0
    assert player.position() == pytest.approx(1.0)
    QTest.keyClick(window, Qt.Key.Key_Right)
    assert window.strip.selected.word == 0, "nothing before the first word"


def test_right_from_no_selection_starts_at_the_last_word(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    assert window.strip.selected.word == 1


def test_the_nudge_row_puts_earlier_on_the_right_in_english_too(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    _spin(20)
    bar = window.selection_bar
    assert bar.snap_button.x() < bar.plus_button.x() < bar.minus_button.x()


def test_the_nudge_row_tabs_from_the_left_in_english(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    bar = window.selection_bar
    assert bar.snap_button.nextInFocusChain() is bar.plus_button
    assert bar.plus_button.nextInFocusChain() is bar.minus_button


def test_comma_moves_the_edge_left_and_period_moves_it_right(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Left)
    width = window.strip.width()

    def end_x() -> float:
        return window.viewport.x_for(window.session.words()[0].end, width)

    before = end_x()
    QTest.keyClick(window, Qt.Key.Key_Comma)  # "<": left on screen, later in time
    assert window.session.words()[0].end == pytest.approx(2.05)
    assert end_x() < before
    QTest.keyClick(window, Qt.Key.Key_Period)  # ">": right on screen, earlier in time
    QTest.keyClick(window, Qt.Key.Key_Period)
    assert window.session.words()[0].end == pytest.approx(1.95)
    assert end_x() > before
    QTest.keyClick(window, Qt.Key.Key_Comma, Qt.KeyboardModifier.ShiftModifier)
    assert window.session.words()[0].end == pytest.approx(1.96)
    QTest.keyClick(window, Qt.Key.Key_Period, Qt.KeyboardModifier.ShiftModifier)
    assert window.session.words()[0].end == pytest.approx(1.95)
    # A real Shift+, / Shift+. on a US layout arrives as "<" / ">".
    QTest.keyClick(window, Qt.Key.Key_Less, Qt.KeyboardModifier.ShiftModifier)
    assert window.session.words()[0].end == pytest.approx(1.96)
    QTest.keyClick(window, Qt.Key.Key_Greater, Qt.KeyboardModifier.ShiftModifier)
    assert window.session.words()[0].end == pytest.approx(1.95)


def test_nudge_moves_the_end_by_fifty_milliseconds(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Comma)
    assert window.session.words()[0].end == pytest.approx(2.05)


def test_a_nudge_and_its_opposite_leave_nothing_to_save(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    before = json.loads(json.dumps(window.session.project.cards))
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Comma)
    assert window.session.words()[1].start == pytest.approx(2.05)
    QTest.keyClick(window, Qt.Key.Key_Period)
    assert window.session.project.cards == before
    assert not window.session.dirty
    assert not window.windowTitle().endswith("*")


def test_ctrl_s_saves_and_the_title_loses_its_marker(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Comma)
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
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Comma)
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
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Comma)
    assert window.session.dirty


def test_shift_nudges_by_ten_milliseconds(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Comma, Qt.KeyboardModifier.ShiftModifier)
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
    assert "2.0 s at 00:04.0–00:06.0" in window.warnings.text()
    window.warnings.linkActivated.emit("4.000")
    assert player.position() == pytest.approx(4.0)
    assert window.time_label.text() == "00:04.00"

    window._coverage_timer.setInterval(0)
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Left)
    player.seek(6.0)
    QTest.keyClick(window, Qt.Key.Key_BracketRight)
    assert _wait_for(lambda: "covered by a word" in window.warnings.text(), 1000)
    assert "Jump" not in window.warnings.text()


def test_a_card_with_no_word_timings_still_flags_its_loud_audio_as_uncovered(
    qt_app, tmp_path
) -> None:
    """Carried from the old editor's "nothing to check" case (no word timings at
    all): rather than a special message saying there is nothing to compare, an
    absent word simply covers nothing, so any loud stretch shows as a gap."""
    cards = [
        {
            "surah_num": 25,
            "from_ayah": 7,
            "to_ayah": 7,
            "full_text": "a b",
            "confidence": 1.0,
            "start_time": 0.0,
            "end_time": 10.0,
        }
    ]
    matches = tmp_path / "m.json"
    matches.write_text(
        json.dumps({"matches": cards, "meta": {"mode": "recitation"}}), encoding="utf-8"
    )
    project = Project(audio=tmp_path / "missing.mp3", cards=cards, matches=matches)
    save_project(project, tmp_path / "m.qalun.json")

    from qurantext.gui.review.window import ReviewWindow

    window = ReviewWindow(project, player=FakePlayer(duration=10.0, now=_Now()))
    window.show()
    assert window.session.coverage_words() == []

    window._on_levels(_levels_with_speech_between(4.0, 6.0))
    assert "2.0 s at 00:04.0–00:06.0" in window.warnings.text()


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
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Comma)
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
    QTest.keyClick(window, Qt.Key.Key_Comma)
    assert window.session.words()[0].start == pytest.approx(1.05)
    assert window.session.words()[0].end == pytest.approx(2.0)
    QTest.keyClick(window, Qt.Key.Key_Left)
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


def test_remove_with_nothing_selected_is_not_offered(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    window.segment_list.clearSelection()
    assert not window.remove_button.isEnabled()
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
    names = ", ".join(p.name for p in written)
    assert dialog._result_label.text() == f"Wrote 2 files: {names}"


@pytest.mark.parametrize(
    ("typed", "written"),
    [
        ("Tafsir 25.7-11", ["Tafsir 25.7-11.srt", "Tafsir 25.7-11.vtt"]),
        ("Dars 12.10.2024", ["Dars 12.10.2024.srt", "Dars 12.10.2024.vtt"]),
        ("talk.srt", ["talk.srt", "talk.vtt"]),
        # The video's own name typed in: its suffix goes, as a subtitle suffix does.
        ("talk.mp4", ["talk.srt", "talk.vtt"]),
        ("Tafsir 25.7-11.MOV", ["Tafsir 25.7-11.srt", "Tafsir 25.7-11.vtt"]),
    ],
)
def test_export_keeps_every_dot_in_the_name(qt_app, tmp_path, monkeypatch, typed, written) -> None:
    """The name is a stem: "Tafsir 25.7-11" must not be written as "Tafsir 25.srt"."""
    from qurantext.gui.review import export_dialog as module
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs import project_render

    monkeypatch.setattr(project_render, "get_audio_duration", lambda path: 10.0)
    project = Project(
        audio=tmp_path / "talk.mp3", mode="lecture", captions=[CaptionCue(1.0, 2.0, "line")]
    )
    save_project(project, tmp_path / "job.qalun.json")
    dialog = module.ExportDialog(ReviewSession(project))
    dialog.set_formats(("srt", "vtt"))
    dialog.set_destination(tmp_path / "out", typed)
    assert sorted(p.name for p in dialog.export()) == written
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == written


def test_export_on_the_video_timeline_is_offered_only_after_a_render(qt_app, tmp_path) -> None:
    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.session import ReviewSession

    project = _project(tmp_path)
    dialog = ExportDialog(ReviewSession(project))
    assert not dialog.video_timeline_available()
    assert not dialog._video_radio.isEnabled()
    assert dialog.timeline() == "audio"
    project.record_render(tmp_path / "v.mp4", preset="social", basmala_offset_s=1.0)
    dialog = ExportDialog(ReviewSession(project))
    assert dialog.video_timeline_available() and dialog.timeline() == "video"


def test_export_rejects_a_blank_file_name_inline(qt_app, tmp_path) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.session import ReviewSession

    project = _project(tmp_path)
    dialog = ExportDialog(ReviewSession(project))
    dialog.set_destination(tmp_path / "out", "  ")
    assert dialog.export() == []
    assert dialog._result_label.text() == t("export.no_name")


def test_export_is_the_dialogs_default_button(qt_app, tmp_path) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.session import ReviewSession

    dialog = ExportDialog(ReviewSession(_project(tmp_path)))
    # Showing the dialog is what used to hand the default to Choose…, so check it shown.
    dialog.show()
    _spin(0)
    assert dialog._go_button.isDefault()
    assert not dialog._choose_button.isDefault()
    assert isinstance(dialog.buttons, QDialogButtonBox)
    assert dialog.buttons.buttonRole(dialog._go_button) == QDialogButtonBox.ButtonRole.AcceptRole
    assert dialog.buttons.buttonRole(dialog.close_button) == QDialogButtonBox.ButtonRole.RejectRole
    assert dialog._show_button.isHidden()
    layout = dialog.layout()
    assert layout.indexOf(dialog._result_label) < layout.indexOf(dialog.buttons)

    # Return in the name field presses Export, not Choose…; record instead of writing.
    pressed: list[str] = []
    dialog._go_button.clicked.disconnect(dialog.export)
    dialog._go_button.clicked.connect(lambda: pressed.append("export"))
    dialog._choose_button.clicked.disconnect(dialog._choose_folder)
    dialog._choose_button.clicked.connect(lambda: pressed.append("choose"))
    dialog._name_field.setFocus()
    QTest.keyClick(dialog._name_field, Qt.Key.Key_Return)
    _spin(0)
    assert pressed == ["export"]
    dialog.hide()


def test_the_folder_field_shows_the_start_of_the_path(qt_app, tmp_path) -> None:
    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.session import ReviewSession

    dialog = ExportDialog(ReviewSession(_project(tmp_path)))
    deep = tmp_path / ("a-rather-long-folder-name-" * 6)
    dialog.set_destination(deep, "take")
    assert dialog._folder_field.cursorPosition() == 0
    assert dialog._folder_field.toolTip() == str(deep)
    typed = str(tmp_path / "typed-by-hand")
    dialog._folder_field.setText(typed)
    assert dialog._folder_field.toolTip() == typed


def test_export_shows_a_save_failure_inline_instead_of_raising(qt_app, tmp_path) -> None:
    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.session import CARD, ReviewSession, WordRef

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
    # No path: never saved, so ReviewSession.save() must raise ValueError.
    project = Project(audio=tmp_path / "missing.mp3", cards=cards)
    session = ReviewSession(project)
    session.retime(WordRef(CARD, 0, 1), start=0.45)
    assert session.dirty
    dialog = ExportDialog(session)
    dialog.set_destination(tmp_path / "out", "clip")
    written = dialog.export()
    assert written == []
    assert dialog._result_label.text() == (
        "The subtitles were not written: This project has no file to write back to."
    )


def test_render_with_corrections_saves_then_renders_the_project(
    qt_app, tmp_path, monkeypatch
) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.gui.jobs import JobOutcome

    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Comma)
    seen = {}

    def fake_render(project, **kwargs):
        seen["end"] = project.cards[0]["word_timings"][0]["end"]
        seen["saved"] = load_project(project.path).cards[0]["word_timings"][0]["end"]
        return JobOutcome(matches=project.matches, video=tmp_path / "v.mp4", cards=1)

    monkeypatch.setattr(jobs_module, "run_render", fake_render)
    monkeypatch.setattr(
        window, "_announce_render", lambda outcome: seen.setdefault("done", outcome)
    )
    window.render_requested.emit()
    # PySide6's QTest has no qWaitFor; _wait_for above (in this file) is its replacement.
    assert _wait_for(lambda: "done" in seen, 5000)
    assert seen["end"] == 2.05 and seen["saved"] == 2.05


def test_render_with_corrections_uses_the_jobs_own_choices(qt_app, tmp_path, monkeypatch) -> None:
    """The review names no preset or subtitles of its own: ``run_render`` reads the job's."""
    from qurantext.gui import jobs as jobs_module
    from qurantext.gui.jobs import JobOutcome

    window, _, _ = _window(qt_app, tmp_path)
    window.session.project.render = {"preset": "high", "width": 1920, "height": 1080}
    window.show()
    seen = {}

    def fake_render(project, **kwargs):
        seen["kwargs"] = kwargs
        return JobOutcome(matches=project.matches, video=tmp_path / "v.mp4", cards=1)

    monkeypatch.setattr(jobs_module, "run_render", fake_render)
    monkeypatch.setattr(
        window, "_announce_render", lambda outcome: seen.setdefault("done", outcome)
    )
    window.render_requested.emit()
    assert _wait_for(lambda: "done" in seen, 5000)
    assert set(seen["kwargs"]) == {"progress", "cancel"}


def _captioned_job(tmp_path, subtitles: str, preset: str = "social"):
    from qurantext.jobs.project import CaptionCue, JobSettings, set_job_settings

    project = _project(tmp_path)
    project.captions = [
        CaptionCue(
            1.0,
            3.0,
            "hello world",
            words=[
                {"word": "hello", "start": 1.0, "end": 2.0},
                {"word": "world", "start": 2.0, "end": 3.0},
            ],
        )
    ]
    set_job_settings(project, JobSettings(preset=preset, subtitles=subtitles))
    return project


@pytest.mark.parametrize(
    ("subtitles", "band"), [("sidecar", False), ("burn", True), ("both", True)]
)
def test_the_frame_reserves_the_caption_band_only_when_it_is_burned_in(
    qt_app, tmp_path, monkeypatch, subtitles, band
) -> None:
    """A sidecar-only render drops the band (``jobs/export.py``), so the preview must too."""
    import numpy as np

    from qurantext.gui.review import frame_view
    from qurantext.gui.review.window import ReviewWindow

    calls = []
    monkeypatch.setattr(
        frame_view,
        "render_frame_pillow",
        lambda *a, **k: calls.append(k) or np.zeros((480, 270, 3), np.uint8),
    )
    window = ReviewWindow(
        _captioned_job(tmp_path, subtitles), player=FakePlayer(duration=10.0, now=_Now())
    )
    window.frame_view.show_at(1.5, force=True)
    assert calls and calls[-1]["reserve_caption_band"] is band


def test_the_frames_shape_follows_the_jobs_preset_before_any_render(qt_app, tmp_path) -> None:
    from qurantext.gui.review.window import ReviewWindow

    window = ReviewWindow(
        _captioned_job(tmp_path, "burn", preset="high"),
        player=FakePlayer(duration=10.0, now=_Now()),
    )
    hint = window.frame_view.sizeHint()
    assert hint.width() > hint.height(), "a 1920x1080 job previews in landscape"


def test_render_disables_editing_actions_until_done(qt_app, tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.gui.jobs import JobOutcome

    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Comma)
    seen = {}

    def fake_render(project, **kwargs):
        return JobOutcome(matches=project.matches, video=tmp_path / "v.mp4", cards=1)

    monkeypatch.setattr(jobs_module, "run_render", fake_render)
    monkeypatch.setattr(
        window, "_announce_render", lambda outcome: seen.setdefault("done", outcome)
    )
    assert window.session.can_undo
    # A selected row, so the remove button's state is the render's doing, not the selection's.
    window.segment_list.selectRow(0)
    assert window.remove_button.isEnabled()
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


def test_editing_is_blocked_everywhere_while_a_render_runs(qt_app, tmp_path, monkeypatch) -> None:
    import threading

    from PySide6.QtWidgets import QAbstractItemView

    from qurantext.gui import jobs as jobs_module
    from qurantext.gui.jobs import JobOutcome
    from qurantext.gui.review.player import FakePlayer
    from qurantext.gui.review.window import ReviewWindow
    from qurantext.jobs.project import CaptionCue

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
        json.dumps({"matches": cards, "meta": {"mode": "lecture"}}), encoding="utf-8"
    )
    captions = [
        CaptionCue(
            4.0,
            5.0,
            "hello world",
            words=[
                {"word": "hello", "start": 4.0, "end": 4.5},
                {"word": "world", "start": 4.5, "end": 5.0},
            ],
        )
    ]
    project = Project(
        audio=tmp_path / "missing.mp3",
        mode="lecture",
        cards=cards,
        captions=captions,
        matches=matches,
    )
    save_project(project, tmp_path / "m.qalun.json")

    player = FakePlayer(duration=10.0, now=_Now())
    window = ReviewWindow(project, player=player)
    window.show()

    # An edit before the render starts, so Ctrl+Z during the block has
    # something real to (not) undo.
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Comma)
    edited_end = window.session.words()[0].end
    caption_text_before = window.session.project.captions[0].text

    release = threading.Event()

    def fake_render(rendered_project, **kwargs):
        release.wait(timeout=5)
        rendered_project.record_render(tmp_path / "v.mp4", preset="social", basmala_offset_s=0.0)
        return JobOutcome(matches=rendered_project.matches, video=tmp_path / "v.mp4", cards=1)

    monkeypatch.setattr(jobs_module, "run_render", fake_render)
    monkeypatch.setattr(window, "_announce_render", lambda outcome: None)
    window.render_requested.emit()
    assert window._rendering

    # Shortcuts do nothing while blocked.
    QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(window, Qt.Key.Key_Comma)
    assert window.session.words()[0].end == pytest.approx(edited_end)

    # A genuine double-click cannot open the caption cell for editing either.
    row = window.segment_list._row_by_segment[("caption", 0)]
    rect = window.segment_list.visualItemRect(window.segment_list.item(row, 2))
    QTest.mouseDClick(
        window.segment_list.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        rect.center(),
    )
    assert window.segment_list.state() != QAbstractItemView.State.EditingState
    assert window.session.project.captions[0].text == caption_text_before

    release.set()
    assert _wait_for(lambda: not window._rendering, 5000)
    assert window.session.project.render is not None
    assert not window.session.dirty


def test_no_render_announcement_after_the_window_is_closed(qt_app, tmp_path, monkeypatch) -> None:
    import threading

    from qurantext.gui import jobs as jobs_module
    from qurantext.gui.jobs import JobOutcome

    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    release = threading.Event()
    seen: dict[str, object] = {}

    def fake_render(project, **kwargs):
        release.wait(timeout=5)
        return JobOutcome(matches=project.matches, video=tmp_path / "v.mp4", cards=1)

    monkeypatch.setattr(jobs_module, "run_render", fake_render)
    monkeypatch.setattr(
        window, "_announce_render", lambda outcome: seen.setdefault("announced", True)
    )
    monkeypatch.setattr(
        window, "_say_render", lambda kind, text: seen.setdefault("said", (kind, text))
    )

    window.render_requested.emit()
    assert window._rendering
    window.close()
    assert window._closed

    release.set()
    assert _wait_for(lambda: not window._rendering, 5000)
    assert "announced" not in seen
    assert "said" not in seen


def test_the_live_project_is_updated_even_though_the_render_finishes_after_close(
    qt_app, tmp_path, monkeypatch
) -> None:
    """The render's outcome lands on the live project whether or not the
    window is still open to announce it: only the announcement is skipped."""
    import threading

    from qurantext.gui import jobs as jobs_module
    from qurantext.gui.jobs import JobOutcome

    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    release = threading.Event()

    def fake_render(project, **kwargs):
        release.wait(timeout=5)
        project.record_render(tmp_path / "v.mp4", preset="social", basmala_offset_s=0.0)
        return JobOutcome(matches=project.matches, video=tmp_path / "v.mp4", cards=1)

    monkeypatch.setattr(jobs_module, "run_render", fake_render)
    monkeypatch.setattr(window, "_announce_render", lambda outcome: None)

    window.render_requested.emit()
    assert window._rendering
    window.close()
    assert window._closed
    assert window.session.project.render is None

    release.set()
    assert _wait_for(lambda: not window._rendering, 5000)
    assert window.session.project.render is not None


def test_cancelling_a_render_brings_the_buttons_back(qt_app, tmp_path, monkeypatch) -> None:
    import threading

    from qurantext.gui import jobs as jobs_module
    from qurantext.gui.i18n import t
    from qurantext.gui.jobs import JobOutcome

    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    release = threading.Event()

    def fake_render(project, *, cancel, **kwargs):
        release.wait(timeout=5)
        cancel.raise_if_cancelled("render")
        return JobOutcome(matches=project.matches, video=tmp_path / "v.mp4", cards=1)

    monkeypatch.setattr(jobs_module, "run_render", fake_render)
    seen = {}
    monkeypatch.setattr(window, "_say_render", lambda kind, text: seen.setdefault(kind, text))

    window.render_requested.emit()
    assert window._rendering
    token = window._render_cancel
    assert token is not None
    window._cancel_render()
    assert token.cancelled

    release.set()
    assert _wait_for(lambda: not window._rendering, 5000)
    assert seen.get("cancelled") == t("render.cancelled")
    assert window.render_button.isEnabled()


def test_an_accepted_close_says_so_and_a_refused_one_does_not(
    qt_app, tmp_path, monkeypatch
) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    closed = []
    window.closed.connect(lambda: closed.append(True))
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Comma)
    monkeypatch.setattr(window, "_confirm_discard", lambda: "cancel")
    window.close()
    assert not closed
    monkeypatch.setattr(window, "_confirm_discard", lambda: "discard")
    window.close()
    assert closed == [True]
    assert window._jobs.active == 0


def test_discard_puts_the_saved_state_back(qt_app, tmp_path, monkeypatch) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Comma)
    assert window.session.dirty
    monkeypatch.setattr(window, "_confirm_discard", lambda: "discard")
    window.close()
    assert not window.session.dirty
    assert window.session.words()[0].end == 2.0


def _three_cue_window(tmp_path, words=("one", "two", "three")):
    from qurantext.gui.review.window import ReviewWindow
    from qurantext.jobs.project import CaptionCue

    def cue(start, word):
        return CaptionCue(
            start, start + 1.0, word, words=[{"word": word, "start": start, "end": start + 1.0}]
        )

    project = Project(
        audio=tmp_path / "missing.mp3",
        mode="lecture",
        captions=[cue(2.0 * index, word) for index, word in enumerate(words)],
    )
    player = FakePlayer(duration=2.0 * len(words), now=_Now())
    window = ReviewWindow(project, player=player)
    window.resize(1100, 800)
    return window, player


def test_playback_marks_rows_but_remove_only_takes_what_was_selected(qt_app, tmp_path) -> None:
    window, player = _three_cue_window(tmp_path)
    window.show()
    for position in (0.5, 2.5, 4.5):
        player.seek(position)
        window._tick()
    # The playhead's marks are not a selection, so there is nothing to remove.
    assert not window.remove_button.isEnabled()
    assert len(window.session.project.captions) == 3


def test_removing_an_earlier_caption_drops_the_strip_selection(qt_app, tmp_path) -> None:
    from qurantext.gui.review.session import CAPTION, WordRef

    window, _ = _three_cue_window(tmp_path)
    window.show()
    window.strip.select(WordRef(CAPTION, 1, 0))
    window.segment_list.selectRow(0)
    window.remove_button.click()
    assert len(window.session.project.captions) == 2
    # Index 1 is now the old "three": keeping the ref would quietly select another word.
    assert window.strip.selected is None
    from qurantext.gui.i18n import t

    assert window.selection_bar.label.text() == t("review.no_selection")
    window.strip.select(WordRef(CAPTION, 1, 0))
    QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert len(window.session.project.captions) == 3
    assert window.strip.selected is None


def test_removing_several_rows_drops_a_strip_selection_that_would_name_another_word(
    qt_app, tmp_path
) -> None:
    from PySide6.QtCore import QItemSelectionModel

    from qurantext.gui.review.session import CAPTION, WordRef

    window, _ = _three_cue_window(tmp_path, words=("zero", "one", "two", "three"))
    window.show()
    window.strip.select(WordRef(CAPTION, 1, 0))
    window.segment_list.selectRow(0)
    model = window.segment_list.selectionModel()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    model.select(window.segment_list.model().index(3, 0), flags)
    window.remove_button.click()
    assert [cue.text for cue in window.session.project.captions] == ["one", "two"]
    # Index 1 now names "two": a nudge would retime a word nobody picked.
    assert window.strip.selected is None


def test_removing_the_selected_last_row_raises_nothing_in_a_slot(
    qt_app, tmp_path, monkeypatch
) -> None:
    import sys

    from qurantext.gui.review.session import CAPTION, WordRef

    raised: list[BaseException] = []
    monkeypatch.setattr(sys, "excepthook", lambda _type, value, _tb: raised.append(value))
    window, _ = _three_cue_window(tmp_path)
    window.show()
    window.strip.select(WordRef(CAPTION, 2, 0))
    window.segment_list.selectRow(2)
    window.remove_button.click()
    assert len(window.session.project.captions) == 2
    assert window.strip.selected is None
    assert raised == []


def test_without_playback_the_strip_says_so_briefly_and_the_button_has_the_details(
    qt_app, tmp_path
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.player import Player
    from qurantext.gui.review.window import ReviewWindow

    reason = t("player.unavailable", details="no audio backend")
    window = ReviewWindow(_project(tmp_path), player=Player(reason=reason))
    assert t("player.unavailable_short") in window.warnings.text()
    assert t("player.unavailable_short") == (
        "Playback is off: install PySide6-Addons to hear the recording."
    )
    assert "no audio backend" not in window.warnings.text()
    assert "no audio backend" in window.play_button.toolTip()


def test_a_missing_recording_is_shown_on_the_waveform(qt_app, tmp_path) -> None:
    from qurantext.gui.i18n import t

    window, _, _ = _window(qt_app, tmp_path)
    assert window.waveform.placeholder() == t("waveform.missing")


def test_the_strip_says_the_recording_is_being_checked_until_the_levels_arrive(
    qt_app, tmp_path
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.window import ReviewWindow

    project = _project(tmp_path)
    project.audio = tmp_path / "unreadable.mp3"
    project.audio.write_bytes(b"")
    window = ReviewWindow(project, player=FakePlayer(duration=10.0, now=_Now()))
    assert t("review.checking") in window.warnings.text()
    window._on_levels(_levels_with_speech_between(4.0, 6.0))
    assert t("review.checking") not in window.warnings.text()
    assert "2.0 s at 00:04.0–00:06.0" in window.warnings.text()
    assert _wait_for(lambda: window._jobs.active == 0, 10000)


def test_saves_made_by_the_export_dialog_are_announced(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Comma)
    saved = []
    window.saved.connect(saved.append)
    dialog = window._make_export_dialog()
    dialog.set_destination(tmp_path / "out", "clip")
    dialog.export()
    assert saved == [window.session.project.path]
    assert not window.session.dirty


def test_a_finished_render_is_announced_as_a_save(qt_app, tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.gui.jobs import JobOutcome

    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    saved = []
    window.saved.connect(saved.append)

    def fake_render(project, **kwargs):
        return JobOutcome(matches=project.matches, video=tmp_path / "v.mp4", cards=1)

    monkeypatch.setattr(jobs_module, "run_render", fake_render)
    monkeypatch.setattr(window, "_announce_render", lambda outcome: None)
    window.render_requested.emit()
    assert not window.reviewed_button.isEnabled(), "no marking as reviewed mid-render"
    assert _wait_for(lambda: not window._rendering, 5000)
    assert saved == [window.session.project.path]
    assert window.reviewed_button.isEnabled()


def test_the_export_dialog_closes_and_says_when_the_render_is_stale(qt_app, tmp_path) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.session import CARD, ReviewSession, WordRef

    project = _project(tmp_path)
    project.record_render(tmp_path / "v.mp4", preset="social", basmala_offset_s=1.0)
    session = ReviewSession(project)
    dialog = ExportDialog(session)
    assert dialog._video_radio.text() == t("export.match_video")
    session.retime(WordRef(CARD, 0, 0), end=2.5)
    dialog = ExportDialog(session)
    assert dialog._video_radio.text() == t("export.match_video_stale")
    assert t("export.match_video_stale") == (
        "Match the rendered video (includes the basmala at the start)"
        " — rendered before your latest changes"
    )
    dialog.show()
    dialog.close_button.click()
    assert not dialog.isVisible()


def test_the_frame_shape_follows_the_jobs_preset_over_an_older_render(tmp_path) -> None:
    """A job re-run as landscape must not keep showing the portrait of its last render."""
    from pathlib import Path

    from qurantext.gui.review.window import _is_portrait
    from qurantext.jobs.project import JobSettings, set_job_settings

    project = Project(audio=Path("a.mp3"), cards=[])
    assert _is_portrait(project), "the default preset is portrait"

    project.record_render(
        tmp_path / "a.mp4", preset="social", basmala_offset_s=0.0, width=1080, height=1920
    )
    set_job_settings(project, JobSettings(preset="high"))
    assert not _is_portrait(project)

    unrecorded = Project(audio=Path("a.mp3"), cards=[])
    unrecorded.record_render(
        tmp_path / "a.mp4", preset=None, basmala_offset_s=0.0, width=1920, height=1080
    )
    assert not _is_portrait(unrecorded), "no choice recorded: the render's own size"


#: What each punctuation key types on the Arabic (101) layout, and what the window should do.
_ARABIC_LAYOUT_PRESSES = [
    # (Latin key, Arabic letter it types, Shift, the edited word, its edge, the new value)
    ("[", "ج", False, 1, "start", 2.4),  # ج
    ("]", "د", False, 0, "end", 2.4),  # د
    # "," moves the edge left on the right-to-left timeline (later), "." right (earlier).
    (",", "و", False, 0, "end", 2.05),  # و
    (".", "ز", False, 0, "end", 1.95),  # ز
    (",", "و", True, 0, "end", 2.01),
    (".", "ز", True, 0, "end", 1.99),
]


def _layout_press(platform, latin, letter, modifiers=Qt.KeyboardModifier.NoModifier):
    """A press of the physical *latin* key while an Arabic layout makes it type *letter*.

    Qt reports the letter as the key and the text, and the physical key only as
    the native code: the scan code, or on macOS the virtual key code.
    """
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    from qurantext.gui.review.window import SCANCODE_KEYS

    qt_key = {"[": Qt.Key.Key_BracketLeft, "]": Qt.Key.Key_BracketRight}.get(latin)
    qt_key = qt_key or {",": Qt.Key.Key_Comma, ".": Qt.Key.Key_Period}[latin]
    (code,) = [c for c, k in SCANCODE_KEYS[platform].items() if k == qt_key]
    scan, virtual = (0, code) if platform == "macos" else (code, 0)
    return QKeyEvent(QEvent.Type.KeyPress, ord(letter), modifiers, scan, virtual, 0, letter)


@pytest.mark.parametrize("platform", ["xkb", "windows", "macos"])
@pytest.mark.parametrize(
    ("latin", "letter", "shift", "word", "edge", "value"), _ARABIC_LAYOUT_PRESSES
)
def test_shortcuts_follow_the_physical_key_on_an_arabic_layout(
    qt_app, tmp_path, monkeypatch, platform, latin, letter, shift, word, edge, value
) -> None:
    from PySide6.QtWidgets import QApplication

    from qurantext.gui.review import window as window_module

    monkeypatch.setattr(window_module, "_platform_family", lambda: platform)
    window, player, _ = _window(qt_app, tmp_path)
    window.show()
    for _ in range(word + 1):
        QTest.keyClick(window, Qt.Key.Key_Left)
    player.seek(2.4)
    modifiers = Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier
    event = _layout_press(platform, latin, letter, modifiers)
    QApplication.sendEvent(window, event)
    assert event.isAccepted()
    assert getattr(window.session.words()[word], edge) == pytest.approx(value)


def test_the_physical_key_table_is_read_for_this_platform(qt_app, tmp_path) -> None:
    from PySide6.QtWidgets import QApplication

    from qurantext.gui.review.window import _platform_family

    window, player, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Left)
    QApplication.sendEvent(window, _layout_press(_platform_family(), ".", "ز"))
    assert window.session.words()[0].end == pytest.approx(1.95)


@pytest.mark.parametrize(
    ("text", "modifiers"),
    [
        ("x", Qt.KeyboardModifier.NoModifier),  # a Latin layout's own key there: not a shortcut
        ("", Qt.KeyboardModifier.NoModifier),  # a dead key
        ("ز", Qt.KeyboardModifier.ControlModifier),  # Ctrl+ is Qt's own Latin fallback
        ("ز", Qt.KeyboardModifier.AltModifier),
    ],
)
def test_only_an_unmatched_non_latin_key_is_read_by_its_physical_place(
    qt_app, tmp_path, text, modifiers
) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    from qurantext.gui.review.window import SCANCODE_KEYS, _platform_family

    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Left)
    platform = _platform_family()
    (code,) = [c for c, k in SCANCODE_KEYS[platform].items() if k == Qt.Key.Key_Period]
    scan, virtual = (0, code) if platform == "macos" else (code, 0)
    key = ord(text) if text else int(Qt.Key.Key_unknown)
    QApplication.sendEvent(
        window, QKeyEvent(QEvent.Type.KeyPress, key, modifiers, scan, virtual, 0, text)
    )
    assert window.session.words()[0].end == 2.0
    assert not window.session.dirty


def test_the_toolbar_and_transport_say_their_shortcuts(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    assert "Ctrl+S" in window.save_button.toolTip()
    assert "Ctrl+Z" in window.undo_button.toolTip()
    assert "Ctrl+Shift+Z" in window.redo_button.toolTip()
    assert "Space" in window.play_button.toolTip()
    assert "." in window.selection_bar.minus_button.toolTip()
    assert "," in window.selection_bar.plus_button.toolTip()
    assert window.selection_bar.minus_button.toolTip() == t(
        "review.tip_fine", action=t("review.minus"), keys="."
    )


def test_the_shortcut_hint_elides_to_the_window_and_keeps_its_full_text(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.resize(window.minimumSizeHint())
    window.show()
    _spin(50)
    label = window.hint_label
    assert label.toolTip() == t("review.shortcuts")
    assert label.fontMetrics().horizontalAdvance(label.text()) <= label.width()
    assert label.text().endswith("…")
    window.resize(2400, 800)
    _spin(50)
    assert window.hint_label.text() == t("review.shortcuts")


def test_zoom_is_the_sliders_buddy(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    assert window.zoom_label.buddy() is window.zoom_slider


def test_remove_waits_for_a_selected_row(qt_app, tmp_path) -> None:
    window, _ = _three_cue_window(tmp_path)
    assert not window.remove_button.isEnabled()
    window.segment_list.selectRow(1)
    assert window.remove_button.isEnabled()
    window.segment_list.clearSelection()
    assert not window.remove_button.isEnabled()


def test_a_small_window_keeps_rows_in_the_list_and_shrinks_the_frame(qt_app, tmp_path) -> None:
    window, _ = _three_cue_window(tmp_path)
    window.resize(1000, 640)
    window.show()
    _spin(100)
    assert window.segment_list.height() >= 150
    frame = window.frame_view
    assert frame.height() < 480
    assert frame.pixmap().height() <= frame.height()
    assert frame.pixmap().width() <= frame.width()


# -- the Look panel ----------------------------------------------------------------


def test_the_look_panel_drives_the_preview_and_undo(qt_app, tmp_path) -> None:
    from qurantext.config.paths import DEFAULT_FONT_PATH

    if not DEFAULT_FONT_PATH.exists():
        pytest.skip("needs the bundled font")
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    _spin(50)
    before = window.frame_view.pixmap().toImage()
    window.look_panel.palette_buttons["ink_on_paper"].click()
    assert window.frame_view.pixmap().toImage() != before
    assert window.undo_button.isEnabled()
    assert window.windowTitle().endswith("*")
    window.undo_button.click()
    assert window.frame_view.pixmap().toImage() == before
    assert window.look_panel.status_label.text() == "Night gold"
    assert not window.undo_button.isEnabled() and window.redo_button.isEnabled()
    window.redo_button.click()
    assert window.look_panel.status_label.text() == "Ink on paper"


def test_the_look_panel_sits_right_of_the_frame(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    _spin(50)
    frame = window.frame_view.mapTo(window, window.frame_view.rect().topRight())
    panel = window.look_scroll.mapTo(window, window.look_scroll.rect().topLeft())
    waveform = window.waveform.mapTo(window, window.waveform.rect().topLeft())
    assert frame.x() <= panel.x() < waveform.x()


def test_discarding_puts_the_look_panel_back(qt_app, tmp_path, monkeypatch) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    window.look_panel.palette_buttons["rose"].click()
    monkeypatch.setattr(window, "_confirm_discard", lambda: "discard")
    window.close()
    assert window.look_panel.status_label.text() == "Night gold"


def test_use_for_new_videos_confirms_in_the_status_bar(qt_app, tmp_path, prefs) -> None:
    from qurantext.core.looks import PRESETS
    from qurantext.gui.review.window import ReviewWindow

    window = ReviewWindow(
        _project(tmp_path), player=FakePlayer(duration=10.0, now=_Now()), prefs=prefs
    )
    window.look_panel.palette_buttons["emerald"].click()
    window.look_panel.default_button.click()
    assert prefs.default_look == PRESETS["emerald"]
    assert window.statusBar().currentMessage() == t("look.default_saved")


def test_a_render_s_look_warnings_reach_the_strip(qt_app, tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.gui.jobs import JobOutcome

    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    seen = {}

    def fake_render(project, **kwargs):
        return JobOutcome(
            matches=project.matches,
            video=tmp_path / "v.mp4",
            cards=1,
            look_warnings=("image_unreadable",),
        )

    monkeypatch.setattr(jobs_module, "run_render", fake_render)
    monkeypatch.setattr(
        window, "_announce_render", lambda outcome: seen.setdefault("done", outcome)
    )
    window.render_requested.emit()
    assert _wait_for(lambda: "done" in seen, 5000)
    assert html.escape(t("look.image_unreadable")) in window.warnings.text()


def test_a_missing_look_image_is_said_on_opening(qt_app, tmp_path) -> None:
    from dataclasses import replace

    from qurantext.core.looks import NIGHT_GOLD, Background
    from qurantext.gui.review.window import ReviewWindow
    from qurantext.jobs.look_assets import set_project_look

    project = _project(tmp_path)
    gone = tmp_path / "m.qalun.look" / "gone.png"
    background = Background("image", NIGHT_GOLD.frame_bg, NIGHT_GOLD.frame_bg, gone, dim=0.35)
    set_project_look(project, replace(NIGHT_GOLD, background=background))
    save_project(project, project.path)
    window = ReviewWindow(load_project(project.path), player=FakePlayer(duration=10.0, now=_Now()))
    assert html.escape(t("look.image_missing")) in window.warnings.text()


def test_a_look_problem_leaves_the_strip_once_the_look_is_fixed(qt_app, tmp_path) -> None:
    from dataclasses import replace

    from qurantext.core.looks import NIGHT_GOLD, Background
    from qurantext.gui.review.window import ReviewWindow
    from qurantext.jobs.look_assets import set_project_look

    project = _project(tmp_path)
    gone = tmp_path / "m.qalun.look" / "gone.png"
    background = Background("image", NIGHT_GOLD.frame_bg, NIGHT_GOLD.frame_bg, gone, dim=0.35)
    set_project_look(project, replace(NIGHT_GOLD, background=background))
    save_project(project, project.path)
    window = ReviewWindow(load_project(project.path), player=FakePlayer(duration=10.0, now=_Now()))
    missing = html.escape(t("look.image_missing"))
    assert missing in window.warnings.text()
    window.look_panel.reset_button.click()
    assert missing not in window.warnings.text()
    assert "missing.mp3" in window.warnings.text(), "the strip's other lines stay"
    window.undo_button.click()
    assert missing in window.warnings.text(), "undo brings the image, and its problem, back"


def test_a_window_without_prefs_never_touches_the_real_settings(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.look_panel.palette_buttons["rose"].click()
    window.look_panel.default_button.click()
    assert (tmp_path / "window-prefs.ini").is_file()


# -- the surah on the cards ---------------------------------------------------------


def _lecture_window(qt_app, tmp_path):
    """A lecture on al-Fatiha that quotes al-Baqara once."""
    from qurantext.gui.review.window import ReviewWindow
    from qurantext.jobs.project import CaptionCue

    studied = {
        "surah_num": 1,
        "surah_name": "الفاتحة",
        "from_ayah": 1,
        "to_ayah": 1,
        "full_text": "x",
        "confidence": 1.0,
        "start_time": 1.0,
        "end_time": 6.0,
    }
    quote = dict(
        studied, surah_num=2, surah_name="البقرة", from_ayah=255, to_ayah=255, start_time=7.0
    )
    quote["end_time"] = 8.0
    project = Project(
        audio=tmp_path / "missing.mp3",
        mode="lecture",
        cards=[studied, quote],
        captions=[CaptionCue(0.0, 2.0, "one", words=[{"word": "one", "start": 0.0, "end": 2.0}])],
    )
    save_project(project, tmp_path / "dars.qalun.json")
    window = ReviewWindow(project, player=FakePlayer(duration=10.0, now=_Now()))
    window.resize(1100, 800)
    return window


def test_the_surah_picker_is_offered_for_a_lecture_only(qt_app, tmp_path, monkeypatch) -> None:
    from qurantext.gui.review import window as window_module

    monkeypatch.setattr(window_module, "stored_surah_names", lambda: {})  # no store built
    window = _lecture_window(qt_app, tmp_path)
    box = window.studied_surah_box
    assert not box.isHidden() and not window.studied_surah_label.isHidden()
    assert box.count() == 115 and box.itemData(0) is None
    assert box.itemText(0) == t("surah.detect") and box.currentIndex() == 0
    assert "البقرة" in box.itemText(box.findData(2)), "without a store, named from the cards"
    assert box.itemText(box.findData(3)) == t("surah.number", num=3)

    recitation, _, _ = _window(qt_app, tmp_path)
    assert recitation.studied_surah_box.isHidden()


def test_choosing_the_surah_redraws_the_frame_and_marks_the_job_unsaved(
    qt_app, tmp_path, monkeypatch
) -> None:
    window = _lecture_window(qt_app, tmp_path)
    redraws = []
    monkeypatch.setattr(window.frame_view, "show_at", lambda t, force=False: redraws.append(force))
    box = window.studied_surah_box
    box.setCurrentIndex(box.findData(2))
    assert window.session.studied_surah == 2
    assert redraws == [True]
    assert window.session.frame_inputs(7.5)[0]["surah_num"] == 2
    assert window.session.frame_inputs(3.0)[0] is None, "al-Fatiha left the card"
    assert window.windowTitle().endswith("*") and window.save_button.isEnabled()
    assert window.undo_button.isEnabled()


def test_undo_redo_save_and_discard_bring_the_picker_along(qt_app, tmp_path) -> None:
    window = _lecture_window(qt_app, tmp_path)
    box = window.studied_surah_box
    box.setCurrentIndex(box.findData(2))
    window.undo()
    assert box.currentData() is None and window.session.studied_surah is None
    window.redo()
    assert box.currentData() == 2
    assert window.save()
    assert load_project(window.session.project.path).export["studied_surah"] == 2
    assert box.currentData() == 2 and not window.save_button.isEnabled()
    box.setCurrentIndex(box.findData(1))
    window.session.revert()  # what Discard does on close
    window._after_edit()
    assert box.currentData() == 2 and window.session.studied_surah == 2


def test_a_chosen_surah_with_no_card_is_said_in_the_warnings(qt_app, tmp_path) -> None:
    window = _lecture_window(qt_app, tmp_path)
    box = window.studied_surah_box
    box.setCurrentIndex(box.findData(114))
    _spin(20)
    text = html.unescape(window.warnings.text())
    assert "114" in text and "opening title card" in text
    assert window.warnings.isVisibleTo(window)
    box.setCurrentIndex(0)
    assert "opening title card" not in html.unescape(window.warnings.text())


# -- hand-made ayah cards --------------------------------------------------------


@pytest.fixture
def db(store):
    """The word-level store the suite builds once per module (``conftest.store``)."""
    return store


def _quote(surah, ayah, start, end, text="نص"):
    return {
        "surah_num": surah,
        "from_ayah": ayah,
        "to_ayah": ayah,
        "text": text,
        "full_text": text,
        "confidence": 0.9,
        "start_time": start,
        "end_time": end,
    }


def _quoting_lecture_window(qt_app, tmp_path, db, *, cards=None, captions=()):
    """A 100 s lecture quoting 25:7 at 10–20 s and 25:8 at 30–40 s (the session tests' lecture)."""
    from qurantext.gui.review.window import ReviewWindow

    if cards is None:
        cards = [
            _quote(25, 7, 10.0, 20.0, "وقالوا مال هذا الرسول"),
            _quote(25, 8, 30.0, 40.0, "أو يلقى إليه كنز"),
        ]
    project = Project(
        audio=tmp_path / "missing.mp3", mode="lecture", cards=cards, captions=list(captions)
    )
    save_project(project, tmp_path / "dars.qalun.json")
    window = ReviewWindow(project, player=FakePlayer(duration=100.0, now=_Now()), db_path=db)
    window.resize(1100, 800)
    return window


def _picker_answers(monkeypatch, choice, *, accept=True) -> list:
    """Answer every ayah picker with *choice* (or Cancel); returns what each one opened on."""
    from PySide6.QtWidgets import QDialog

    from qurantext.gui.review.ayah_picker import AyahPicker

    opened = []

    def answer(picker):
        opened.append(
            (picker.surah_box.currentData(), picker.from_spin.value(), picker.to_spin.value())
        )
        picker.playing_while_open = picker.parent().player.is_playing()
        return QDialog.DialogCode.Accepted if accept else QDialog.DialogCode.Rejected

    monkeypatch.setattr(AyahPicker, "exec", answer)
    monkeypatch.setattr(AyahPicker, "choice", lambda _picker: choice)
    return opened


def _frame_at(window, seconds):
    window.seek(seconds)
    return window.frame_view.pixmap().toImage()


def test_show_ayah_is_offered_only_in_lectures(qt_app, tmp_path, db) -> None:
    lecture = _quoting_lecture_window(qt_app, tmp_path, db)
    assert not lecture.show_ayah_button.isHidden()
    assert lecture.show_ayah_button.text() == t("review.show_ayah")
    assert lecture.show_ayah_button.toolTip() == t("review.show_ayah.tip")
    recitation, _, _ = _window(qt_app, tmp_path)
    assert recitation.show_ayah_button.isHidden()


def test_show_ayah_inserts_at_the_playhead_and_redraws(qt_app, tmp_path, db, monkeypatch) -> None:
    window = _quoting_lecture_window(qt_app, tmp_path, db)
    opened = _picker_answers(monkeypatch, (25, 7, 7))
    before = _frame_at(window, 26.0)
    window.seek(25.0)
    window.show_ayah_button.click()
    assert opened == [(25, 7, 7)], "opened on the card on screen, 25:7"
    cards = window.session.project.cards
    assert len(cards) == 3
    new = cards[1]
    assert (new["surah_num"], new["from_ayah"], new["start_time"]) == (25, 7, 25.0)
    assert window.session.is_manual(1)
    assert _frame_at(window, 26.0) != before, "the frame shows the store's text now"
    assert window.undo_button.isEnabled() and window.windowTitle().endswith("*")
    window.undo_button.click()
    assert len(window.session.project.cards) == 2 and not window.session.dirty


def test_show_ayah_before_any_card_opens_on_the_chosen_surah(
    qt_app, tmp_path, db, monkeypatch
) -> None:
    window = _quoting_lecture_window(qt_app, tmp_path, db)
    window.studied_surah_box.setCurrentIndex(window.studied_surah_box.findData(3))
    opened = _picker_answers(monkeypatch, (25, 1, 1), accept=False)
    window.seek(2.0)
    window.show_ayah_button.click()
    assert opened == [(3, 1, 1)], "the chosen surah, though 25 is the one heard"


def test_show_ayah_before_any_card_opens_on_the_guessed_surah(
    qt_app, tmp_path, db, monkeypatch
) -> None:
    """Left on "Detect automatically", the picker opens on the surah the cards keep to."""
    cards = [_quote(2, 255, 5.0, 6.0), _quote(25, 7, 10.0, 20.0), _quote(25, 8, 30.0, 40.0)]
    window = _quoting_lecture_window(qt_app, tmp_path, db, cards=cards)
    assert window.session.studied_surah is None
    opened = _picker_answers(monkeypatch, (25, 1, 1), accept=False)
    window.seek(2.0)
    window.show_ayah_button.click()
    assert opened == [(25, 1, 1)]


def test_show_ayah_with_no_surah_to_go_by_opens_on_al_fatiha(
    qt_app, tmp_path, db, monkeypatch
) -> None:
    window = _quoting_lecture_window(qt_app, tmp_path, db, cards=[])
    opened = _picker_answers(monkeypatch, (1, 1, 1), accept=False)
    window.show_ayah_button.click()
    assert opened == [(1, 1, 1)]


@pytest.mark.parametrize("chosen", [None, 25])
def test_show_ayah_opens_on_the_card_on_screen_not_a_hidden_quote(
    qt_app, tmp_path, db, monkeypatch, chosen
) -> None:
    """A quote from another surah is off the card; the picker opens on what the frame shows."""
    cards = [
        _quote(25, 7, 10.0, 20.0),
        _quote(2, 255, 22.0, 24.0),
        _quote(25, 8, 40.0, 50.0),
        _quote(25, 9, 60.0, 70.0),
    ]
    window = _quoting_lecture_window(qt_app, tmp_path, db, cards=cards)
    if chosen is not None:
        window.studied_surah_box.setCurrentIndex(window.studied_surah_box.findData(chosen))
    opened = _picker_answers(monkeypatch, (25, 1, 1), accept=False)
    window.seek(30.0)
    window.show_ayah_button.click()
    assert window.session.frame_inputs(30.0)[0]["from_ayah"] == 7
    assert opened == [(25, 7, 7)]


def test_show_ayah_opens_on_the_whole_range_on_screen(qt_app, tmp_path, db, monkeypatch) -> None:
    cards = [dict(_quote(25, 7, 10.0, 20.0), to_ayah=9)]
    window = _quoting_lecture_window(qt_app, tmp_path, db, cards=cards)
    opened = _picker_answers(monkeypatch, (25, 1, 1), accept=False)
    window.seek(15.0)
    window.show_ayah_button.click()
    assert opened == [(25, 7, 9)]


def test_playback_pauses_while_the_picker_is_open(qt_app, tmp_path, db, monkeypatch) -> None:
    from qurantext.gui.review.ayah_picker import AyahPicker

    window = _quoting_lecture_window(qt_app, tmp_path, db)
    _picker_answers(monkeypatch, (25, 7, 7), accept=False)
    seen = []
    answer = AyahPicker.exec

    def watch(picker):
        result = answer(picker)
        seen.append(picker.playing_while_open)
        return result

    monkeypatch.setattr(AyahPicker, "exec", watch)
    window.player.play()
    window.show_ayah_button.click()
    assert seen == [False] and not window.player.is_playing()


def test_cancel_changes_nothing(qt_app, tmp_path, db, monkeypatch) -> None:
    window = _quoting_lecture_window(qt_app, tmp_path, db)
    _picker_answers(monkeypatch, (25, 7, 7), accept=False)
    window.seek(25.0)
    window.show_ayah_button.click()
    window.segment_list.card_ayah_requested.emit(0)
    assert len(window.session.project.cards) == 2
    assert not window.session.dirty and not window.undo_button.isEnabled()


def test_a_refused_card_is_said_and_changes_nothing(qt_app, tmp_path, db, monkeypatch) -> None:
    from qurantext.gui.review import window as window_module

    window = _quoting_lecture_window(qt_app, tmp_path, db)
    _picker_answers(monkeypatch, (25, 9, 7))  # a range the surah does not have
    said = []
    monkeypatch.setattr(window_module.QMessageBox, "warning", lambda *args: said.append(args[2]))
    window.seek(25.0)
    window.show_ayah_button.click()
    assert said == [t("session.manual_bad_reference", surah=25, first=9, last=7)]
    assert len(window.session.project.cards) == 2 and not window.session.dirty


def test_double_click_and_menu_change_a_cards_ayah(qt_app, tmp_path, db, monkeypatch) -> None:
    from qurantext.gui.review.segment_list import MANUAL_MARK

    window = _quoting_lecture_window(qt_app, tmp_path, db)
    opened = _picker_answers(monkeypatch, (2, 255, 255))
    table = window.segment_list
    table.cellDoubleClicked.emit(0, 0)
    assert opened == [(25, 7, 7)], "opened on the card's own surah and range"
    card = window.session.project.cards[0]
    assert (card["surah_num"], card["from_ayah"], card["to_ayah"]) == (2, 255, 255)
    assert (card["start_time"], card["end_time"]) == (10.0, 20.0)
    assert window.session.is_manual(0)
    assert table.item(0, 0).text().startswith(MANUAL_MARK)

    table.cellDoubleClicked.emit(1, 2)  # the text cell: no picker
    assert len(opened) == 1
    menu = table.context_menu_at(table.visualItemRect(table.item(1, 0)).center())
    assert [action.text() for action in menu.actions()] == [t("segments.change_ayah")]
    menu.actions()[0].trigger()
    assert window.session.project.cards[1]["surah_num"] == 2
    assert table.item(1, 0).text().startswith(MANUAL_MARK)
    assert window.session.undo() and window.session.undo() and not window.session.dirty


def test_a_recitation_offers_no_change_ayah(qt_app, tmp_path, monkeypatch) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    opened = _picker_answers(monkeypatch, (2, 255, 255))
    table = window.segment_list
    table.cellDoubleClicked.emit(0, 0)
    assert opened == []
    assert table.context_menu_at(table.visualItemRect(table.item(0, 0)).center()) is None


def test_a_manual_other_surah_card_shows_in_the_preview_under_a_chosen_surah(
    qt_app, tmp_path, db, monkeypatch
) -> None:
    window = _quoting_lecture_window(qt_app, tmp_path, db)
    box = window.studied_surah_box
    box.setCurrentIndex(box.findData(25))
    _picker_answers(monkeypatch, (2, 255, 255))
    window.seek(50.0)
    before = window.frame_view.pixmap().toImage()
    window.show_ayah_button.click()
    card, _caption, _band = window.session.frame_inputs(50.5)
    assert (card["surah_num"], card["from_ayah"]) == (2, 255)
    assert _frame_at(window, 50.5) != before


def _send_mouse(widget, kind, point) -> None:
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    buttons = (
        Qt.MouseButton.NoButton
        if kind == QMouseEvent.Type.MouseButtonRelease
        else Qt.MouseButton.LeftButton
    )
    event = QMouseEvent(
        kind,
        QPointF(point),
        QPointF(widget.mapToGlobal(point)),
        Qt.MouseButton.LeftButton,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, event)


def test_a_real_double_click_on_a_cards_ayah_cell_opens_the_picker(
    qt_app, tmp_path, db, monkeypatch
) -> None:
    """In a lecture the caption at a card's start is listed far below the cards.

    The first click seeks to the card's start; if the list then scrolled to that
    caption, the second press would land on another row and no double-click
    would be seen (and the caption under it would be clicked instead).
    """
    from PySide6.QtCore import QEvent

    from qurantext.jobs.project import CaptionCue

    captions = [
        CaptionCue(float(i), i + 1.0, f"w{i}", words=[{"word": f"w{i}", "start": i, "end": i + 1}])
        for i in range(100)
    ]
    window = _quoting_lecture_window(qt_app, tmp_path, db, captions=captions)
    window.resize(1280, 800)
    window.show()
    _spin(20)
    opened = _picker_answers(monkeypatch, (25, 8, 8), accept=False)
    table = window.segment_list
    asked = []
    table.card_ayah_requested.connect(asked.append)
    viewport = table.viewport()
    centre = table.visualItemRect(table.item(1, 0)).center()  # 25:8, at 30 s
    for kind in (
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.MouseButtonRelease,
    ):
        _send_mouse(viewport, kind, centre)
    assert asked == [1] and opened == [(25, 8, 8)]
    assert window.player.position() == 30.0, "the playhead stays at the card's start"
    assert sorted({index.row() for index in table.selectedIndexes()}) == [1]
    assert table.verticalScrollBar().value() == 0


@pytest.mark.parametrize("language", ["en", "ar"])
def test_a_lecture_window_fits_a_1280_px_screen_while_rendering(
    qt_app, tmp_path, db, language
) -> None:
    """With the Episode button and "Episode: on" beside Render, idle and rendering."""
    from qurantext.gui.language import apply_language
    from qurantext.jobs.episode_assets import EpisodeChoice

    apply_language(qt_app, language)
    window = _quoting_lecture_window(qt_app, tmp_path, db)
    window.session.set_episode(EpisodeChoice(tmp_path / "intro.mp4", None, tmp_path / "end.mp4"))
    window._after_edit()
    window.show()
    _spin(20)
    assert not window.episode_label.isHidden() and not window.episode_button.isHidden()
    assert window.minimumSizeHint().width() <= 1280
    window._render_progress_key = "render.running_recitation"  # the longest step's words
    window._set_render_running(True)
    try:
        assert window.minimumSizeHint().width() <= 1280
        assert not window.render_progress.isHidden() and not window.render_cancel_button.isHidden()
        assert window.episode_button.isHidden() and not window.episode_label.isHidden()
    finally:
        window._set_render_running(False)
    assert not window.render_button.isHidden() and not window.episode_button.isHidden()


def test_card_changes_wait_for_a_running_render(qt_app, tmp_path, db, monkeypatch) -> None:
    window = _quoting_lecture_window(qt_app, tmp_path, db)
    opened = _picker_answers(monkeypatch, (2, 255, 255))
    table = window.segment_list
    window._set_render_running(True)
    try:
        assert not window.show_ayah_button.isEnabled()
        table.cellDoubleClicked.emit(0, 0)
        menu = table.context_menu_at(table.visualItemRect(table.item(0, 0)).center())
        assert not menu.actions()[0].isEnabled()
        assert opened == []
    finally:
        window._set_render_running(False)
    assert window.show_ayah_button.isEnabled()
    menu = table.context_menu_at(table.visualItemRect(table.item(0, 0)).center())
    assert menu.actions()[0].isEnabled()


def test_the_card_placed_or_changed_is_selected_in_the_list(
    qt_app, tmp_path, db, monkeypatch
) -> None:
    from qurantext.jobs.project import CaptionCue

    captions = [CaptionCue(24.0, 28.0, "spoken", words=[])]
    window = _quoting_lecture_window(qt_app, tmp_path, db, captions=captions)
    _picker_answers(monkeypatch, (25, 9, 9))
    table = window.segment_list
    window.seek(25.0)
    window.show_ayah_button.click()
    assert sorted({index.row() for index in table.selectedIndexes()}) == [1]
    assert table.item(1, 0).text().endswith("25:9")
    table.selectRow(3)  # the caption
    menu = table.context_menu_at(table.visualItemRect(table.item(2, 0)).center())
    menu.actions()[0].trigger()
    assert sorted({index.row() for index in table.selectedIndexes()}) == [2]


@pytest.mark.parametrize("stop", ["cancelled", "failed"])
def test_a_render_stopped_after_its_record_was_saved_keeps_that_record(
    qt_app, tmp_path, monkeypatch, stop
) -> None:
    """A lecture rendered and recorded, then stopped in a later step (its episode, say).

    The project file holds the new record; the live project must take it
    too, or the session's next save writes the old record back over it.
    """
    from qurantext.gui import jobs as jobs_module
    from qurantext.jobs.project import load_project, save_project
    from qurantext.utils.progress import JobCancelled

    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    assert window.session.project.render is None
    saved_paths: list = []
    window.saved.connect(saved_paths.append)

    def recorded_then_stopped(project, **kwargs):
        # What render_project does: record the lecture's render and save the file ...
        project.record_render(
            tmp_path / "v.mp4", preset="social", basmala_offset_s=0.0, width=8, height=8, fps=1
        )
        save_project(project, project.path)
        # ... and then a later step stops.
        if stop == "cancelled":
            raise JobCancelled("episode")
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(jobs_module, "run_render", recorded_then_stopped)
    said: dict = {}
    monkeypatch.setattr(window, "_say_render", lambda kind, text: said.setdefault(kind, text))

    window.render_requested.emit()
    assert _wait_for(lambda: not window._rendering, 5000)

    assert stop in said
    assert window.session.project.render is not None
    assert window.session.project.render["video"] == (tmp_path / "v.mp4").resolve()
    assert saved_paths == [window.session.project.path]
    # The person's next edit and save keeps the record the render wrote.
    window.session.project.cards[0]["end_time"] += 0.25
    save_project(window.session.project, window.session.project.path)
    assert load_project(window.session.project.path).render is not None


def test_a_render_stopped_before_any_record_changes_nothing(qt_app, tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module

    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    saved_paths: list = []
    window.saved.connect(saved_paths.append)

    def failed(project, **kwargs):
        raise RuntimeError("no FFmpeg")

    monkeypatch.setattr(jobs_module, "run_render", failed)
    monkeypatch.setattr(window, "_say_render", lambda kind, text: None)
    window.render_requested.emit()
    assert _wait_for(lambda: not window._rendering, 5000)

    assert window.session.project.render is None and saved_paths == []


# -- the episode ------------------------------------------------------------------


def _episode_answers(monkeypatch, choice, *, accept=True) -> list:
    """Answer every Episode dialog with *choice* (or Cancel); returns the dialogs opened."""
    from PySide6.QtWidgets import QDialog

    from qurantext.gui.review import episode_dialog
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    monkeypatch.setattr(episode_dialog, "list_jobs", lambda *a, **k: [])
    opened = []

    def answer(dialog):
        opened.append(dialog)
        return QDialog.DialogCode.Accepted if accept else QDialog.DialogCode.Rejected

    monkeypatch.setattr(EpisodeDialog, "exec", answer)
    monkeypatch.setattr(EpisodeDialog, "choice", lambda _dialog: choice)
    return opened


def test_the_episode_button_is_offered_for_a_lecture_only(qt_app, tmp_path) -> None:
    window = _lecture_window(qt_app, tmp_path)
    assert not window.episode_button.isHidden()
    assert window.episode_button.text() == t("review.episode")
    assert window.episode_button.toolTip() == t("review.episode.tip")
    assert window.episode_label.isHidden(), "no part chosen yet"
    recitation, _, _ = _window(qt_app, tmp_path)
    assert recitation.episode_button.isHidden() and recitation.episode_label.isHidden()


def test_the_episode_button_opens_the_dialog_and_sets_the_episode(
    qt_app, tmp_path, monkeypatch
) -> None:
    from qurantext.jobs.episode_assets import EpisodeChoice

    window = _lecture_window(qt_app, tmp_path)
    choice = EpisodeChoice(None, tmp_path / "r.qalun.json", None)
    opened = _episode_answers(monkeypatch, choice)
    window.episode_button.click()
    assert len(opened) == 1 and opened[0].parent() is window
    assert window.session.episode.recitation == (tmp_path / "r.qalun.json").resolve()
    assert window.undo_button.isEnabled() and window.windowTitle().endswith("*")
    assert not window.episode_label.isHidden()


def test_a_cancelled_episode_dialog_changes_nothing(qt_app, tmp_path, monkeypatch) -> None:
    from qurantext.jobs.episode_assets import EpisodeChoice

    window = _lecture_window(qt_app, tmp_path)
    _episode_answers(
        monkeypatch, EpisodeChoice(None, tmp_path / "r.qalun.json", None), accept=False
    )
    window.episode_button.click()
    assert window.session.episode.is_empty and not window.session.can_undo


def test_episode_on_follows_undo_redo_and_discard(qt_app, tmp_path, monkeypatch) -> None:
    from qurantext.jobs.episode_assets import EpisodeChoice

    window = _lecture_window(qt_app, tmp_path)
    _episode_answers(monkeypatch, EpisodeChoice(tmp_path / "intro.mp4", None, None))
    window.episode_button.click()
    assert not window.episode_label.isHidden()
    assert window.episode_label.text() == t("review.episode_on")
    window.undo()
    assert window.episode_label.isHidden()
    window.redo()
    assert not window.episode_label.isHidden()
    window.session.revert()  # what Discard does on close
    window._after_edit()
    assert window.episode_label.isHidden()


def _held_render(monkeypatch, tmp_path, *, ending: str):
    """A render that waits for its release, then finishes, is cancelled or fails."""
    import threading

    from qurantext.gui import jobs as jobs_module
    from qurantext.gui.jobs import JobOutcome

    release = threading.Event()

    def fake_render(project, *, cancel, **kwargs):
        release.wait(timeout=5)
        if ending == "cancelled":
            cancel.cancel()
            cancel.raise_if_cancelled("render")
        if ending == "failed":
            raise RuntimeError("no FFmpeg")
        return JobOutcome(matches=project.matches, video=tmp_path / "v.mp4", cards=1)

    monkeypatch.setattr(jobs_module, "run_render", fake_render)
    return release


@pytest.mark.parametrize("ending", ["finished", "cancelled", "failed"])
def test_the_episode_button_hides_while_a_render_runs(
    qt_app, tmp_path, monkeypatch, ending
) -> None:
    window = _lecture_window(qt_app, tmp_path)
    window.show()
    release = _held_render(monkeypatch, tmp_path, ending=ending)
    monkeypatch.setattr(window, "_announce_render", lambda outcome: None)
    monkeypatch.setattr(window, "_say_render", lambda kind, text: None)
    opened = _episode_answers(monkeypatch, None)

    window.render_requested.emit()
    assert window._rendering
    assert window.episode_button.isHidden() and not window.episode_button.isEnabled()
    window._open_episode_dialog()
    assert opened == [], "the episode waits for the render"
    release.set()
    assert _wait_for(lambda: not window._rendering, 5000)
    assert not window.episode_button.isHidden() and window.episode_button.isEnabled()


def test_a_render_s_episode_error_reaches_the_strip(qt_app, tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.gui.jobs import JobOutcome

    window = _lecture_window(qt_app, tmp_path)
    window.show()
    why = t("episode.error.cancelled")
    outcomes = [
        JobOutcome(
            matches=tmp_path / "m.json", video=tmp_path / "v.mp4", cards=1, episode_error=why
        ),
        JobOutcome(
            matches=tmp_path / "m.json",
            video=tmp_path / "v.mp4",
            cards=1,
            episode_video=tmp_path / "v – episode.mp4",
        ),
    ]
    monkeypatch.setattr(jobs_module, "run_render", lambda project, **kw: outcomes.pop(0))
    announced: list = []
    monkeypatch.setattr(window, "_announce_render", announced.append)

    window.render_requested.emit()
    assert _wait_for(lambda: len(announced) == 1 and not window._rendering, 5000)
    assert html.escape(why) in window.warnings.text()
    assert window.warnings.isVisibleTo(window)

    window.render_requested.emit()  # the next render made its episode: the line goes
    assert _wait_for(lambda: len(announced) == 2 and not window._rendering, 5000)
    assert html.escape(why) not in window.warnings.text()


def test_the_render_message_names_the_episode_or_why_it_was_not_made(tmp_path) -> None:
    from qurantext.gui.i18n import path_text
    from qurantext.gui.jobs import JobOutcome
    from qurantext.gui.review.window import render_finished_text

    video = tmp_path / "v.mp4"
    done = t("render.done", path=path_text(video))
    plain = JobOutcome(matches=tmp_path / "m.json", video=video, cards=1)
    assert render_finished_text(plain) == done
    written = JobOutcome(
        matches=plain.matches, video=video, cards=1, episode_video=tmp_path / "v – episode.mp4"
    )
    assert render_finished_text(written) == (
        f"{done}\n\n{t('review.episode_written', name='v – episode.mp4')}"
    )
    why = t("episode.error.cancelled")
    failed = JobOutcome(matches=plain.matches, video=video, cards=1, episode_error=why)
    assert render_finished_text(failed) == f"{done}\n\n{why}"


def test_the_render_progress_names_each_step_of_an_episode(qt_app, tmp_path, monkeypatch) -> None:
    from qurantext.jobs.episode_assets import EpisodeChoice
    from qurantext.utils.progress import ProgressEvent

    window = _lecture_window(qt_app, tmp_path)
    window.session.set_episode(EpisodeChoice(tmp_path / "intro.mp4", None, None))
    window.session.save()
    release = _held_render(monkeypatch, tmp_path, ending="finished")
    monkeypatch.setattr(window, "_announce_render", lambda outcome: None)
    window.render_requested.emit()
    try:
        bar = window.render_progress
        assert bar.format() == t("render.running_lecture", percent=0)
        window._on_render_progress(ProgressEvent("render", "frames", fraction=0.5))
        assert bar.format() == t("render.running_lecture", percent=50)
        window._on_render_progress(
            ProgressEvent("episode_recitation", t("job.stage.episode_recitation"), translated=True)
        )
        assert bar.format() == t("render.running_recitation", percent=0) and bar.value() == 0
        assert bar.toolTip() == t("job.stage.episode_recitation")
        window._on_render_progress(ProgressEvent("episode_recitation", "x", fraction=0.3))
        assert bar.format() == t("render.running_recitation", percent=30)
        window._on_render_progress(ProgressEvent("episode_join", "x", fraction=0.9))
        assert bar.format() == t("render.running_join", percent=90)
    finally:
        release.set()
        assert _wait_for(lambda: not window._rendering, 5000)


def test_a_render_without_an_episode_keeps_its_plain_progress(
    qt_app, tmp_path, monkeypatch
) -> None:
    from qurantext.utils.progress import ProgressEvent

    window = _lecture_window(qt_app, tmp_path)
    release = _held_render(monkeypatch, tmp_path, ending="finished")
    monkeypatch.setattr(window, "_announce_render", lambda outcome: None)
    window.render_requested.emit()
    try:
        window._on_render_progress(ProgressEvent("render", "frames", fraction=0.5))
        assert window.render_progress.format() == t("render.running", percent=50)
    finally:
        release.set()
        assert _wait_for(lambda: not window._rendering, 5000)


def test_notices_handed_in_stay_in_the_strip(qt_app, tmp_path) -> None:
    window = _lecture_window(qt_app, tmp_path)
    notice = t("episode.seed.missing", part=t("episode.part.intro"))
    window.show_notices((notice,))
    assert html.escape(notice) in window.warnings.text()

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


def _spin(ms: int) -> None:
    """Run the event loop for about *ms*, never holding the GIL while it waits.

    Not ``QTest.qWait``: PySide6 keeps the GIL for the whole of that call, so a
    worker thread that needs it while holding a Qt lock the UI thread wants
    deadlocks the two (the full suite hung that way). ``processEvents`` and
    ``sendPostedEvents`` release it, and so does ``time.sleep``.
    """
    from PySide6.QtCore import QCoreApplication, QEvent

    deadline = time.monotonic() + ms / 1000
    while True:
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        left = deadline - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(0.005, left))


def _wait_for(condition, timeout_ms):
    """Spin the event loop until *condition()* holds (PySide6's QTest has no qWaitFor)."""
    deadline = time.monotonic() + timeout_ms / 1000
    while not condition():
        if time.monotonic() > deadline:
            return False
        _spin(20)
    return True


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


def test_a_nudge_and_its_opposite_leave_nothing_to_save(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    before = json.loads(json.dumps(window.session.project.cards))
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
    assert window.session.words()[1].start == pytest.approx(2.05)
    QTest.keyClick(window, Qt.Key.Key_Comma)
    assert window.session.project.cards == before
    assert not window.session.dirty
    assert not window.windowTitle().endswith("*")


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
    assert "2.0 s at 4.0–6.0 s" in window.warnings.text()


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
    names = ", ".join(p.name for p in written)
    assert dialog._result_label.text() == f"Wrote 2 files: {names}"


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
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
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
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
    seen = {}

    def fake_render(project, **kwargs):
        return JobOutcome(matches=project.matches, video=tmp_path / "v.mp4", cards=1)

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
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
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
    QTest.keyClick(window, Qt.Key.Key_Period)
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
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
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
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
    assert window.session.dirty
    monkeypatch.setattr(window, "_confirm_discard", lambda: "discard")
    window.close()
    assert not window.session.dirty
    assert window.session.words()[0].end == 2.0


def _three_cue_window(tmp_path):
    from qurantext.gui.review.window import ReviewWindow
    from qurantext.jobs.project import CaptionCue

    def cue(start, word):
        return CaptionCue(
            start, start + 1.0, word, words=[{"word": word, "start": start, "end": start + 1.0}]
        )

    project = Project(
        audio=tmp_path / "missing.mp3",
        mode="lecture",
        captions=[cue(0.0, "one"), cue(2.0, "two"), cue(4.0, "three")],
    )
    player = FakePlayer(duration=6.0, now=_Now())
    window = ReviewWindow(project, player=player)
    window.resize(1100, 800)
    return window, player


def test_playback_marks_rows_but_remove_only_takes_what_was_selected(qt_app, tmp_path) -> None:
    from qurantext.gui.i18n import t

    window, player = _three_cue_window(tmp_path)
    window.show()
    for position in (0.5, 2.5, 4.5):
        player.seek(position)
        window._tick()
    window.remove_button.click()
    assert len(window.session.project.captions) == 3
    assert window.statusBar().currentMessage() == t("review.remove_none")


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
    assert "2.0 s at 4.0–6.0 s" in window.warnings.text()
    assert _wait_for(lambda: window._jobs.active == 0, 10000)


def test_saves_made_by_the_export_dialog_are_announced(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
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
    (",", "و", False, 0, "end", 1.95),  # و
    (".", "ز", False, 0, "end", 2.05),  # ز
    (",", "و", True, 0, "end", 1.99),
    (".", "ز", True, 0, "end", 2.01),
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
        QTest.keyClick(window, Qt.Key.Key_Right)
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
    QTest.keyClick(window, Qt.Key.Key_Right)
    QApplication.sendEvent(window, _layout_press(_platform_family(), ".", "ز"))
    assert window.session.words()[0].end == pytest.approx(2.05)


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
    QTest.keyClick(window, Qt.Key.Key_Right)
    platform = _platform_family()
    (code,) = [c for c, k in SCANCODE_KEYS[platform].items() if k == Qt.Key.Key_Period]
    scan, virtual = (0, code) if platform == "macos" else (code, 0)
    key = ord(text) if text else int(Qt.Key.Key_unknown)
    QApplication.sendEvent(
        window, QKeyEvent(QEvent.Type.KeyPress, key, modifiers, scan, virtual, 0, text)
    )
    assert window.session.words()[0].end == 2.0
    assert not window.session.dirty

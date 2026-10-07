"""The review window's widgets, driven offscreen."""

from __future__ import annotations

import time

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from qurantext.core.waveform import Peaks  # noqa: E402
from qurantext.gui.review.viewport import Viewport  # noqa: E402


def test_viewport_maps_time_and_pixels(qt_app) -> None:
    vp = Viewport()
    vp.set_duration(100.0)
    vp.set_window(10.0, 20.0)
    assert vp.x_for(20.0, 400) == pytest.approx(200.0)
    assert vp.t_for(100.0, 400) == pytest.approx(15.0)


def test_viewport_clamps_and_zooms_around_an_anchor(qt_app) -> None:
    vp = Viewport()
    vp.set_duration(100.0)
    vp.set_window(95.0, 20.0)
    assert (vp.start, vp.span) == (80.0, 20.0)
    before = vp.x_for(90.0, 500)
    vp.zoom(2.0, 90.0)
    assert vp.span == pytest.approx(10.0)
    assert vp.x_for(90.0, 500) == pytest.approx(before)
    vp.zoom(1000.0, 90.0)
    assert vp.span == Viewport.MIN_SPAN_S


def test_zooming_to_the_limit_keeps_the_anchor_under_the_pointer(qt_app) -> None:
    vp = Viewport()
    vp.set_duration(100.0)
    vp.set_window(80.0, 20.0)
    vp.zoom(1000.0, 90.0)
    assert vp.span == Viewport.MIN_SPAN_S
    assert vp.x_for(90.0, 500) == pytest.approx(250.0)


def test_viewport_follows_the_playhead(qt_app) -> None:
    vp = Viewport()
    vp.set_duration(100.0)
    vp.set_window(0.0, 10.0)
    seen = []
    vp.changed.connect(lambda: seen.append(vp.start))
    vp.follow(5.0)
    assert seen == []
    vp.follow(12.0)
    assert vp.start == pytest.approx(11.0)


def test_waveform_click_asks_to_seek(qt_app) -> None:
    from qurantext.gui.review.waveform_view import WaveformView

    vp = Viewport()
    vp.set_duration(10.0)
    vp.set_window(0.0, 10.0)
    view = WaveformView(vp)
    view.resize(500, 90)
    view.set_peaks(
        Peaks(
            mins=-np.ones(1000, np.float32) / 2,
            maxs=np.ones(1000, np.float32) / 2,
            rate=100.0,
            duration=10.0,
        )
    )
    asked = []
    view.seek_requested.connect(asked.append)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(250, 45))
    assert asked and asked[0] == pytest.approx(5.0, abs=0.05)


def test_waveform_paints_without_peaks_and_with_gaps(qt_app) -> None:
    from qurantext.gui.review.waveform_view import WaveformView

    vp = Viewport()
    vp.set_duration(10.0)
    view = WaveformView(vp)
    view.resize(300, 90)
    view.set_gaps([(2.0, 4.0)])
    view.set_playhead(3.0)
    assert not view.grab().isNull()


def _strip(qt_app):
    from qurantext.gui.review.session import ReviewSession
    from qurantext.gui.review.word_strip import WordStrip
    from qurantext.jobs.project import Project

    cards = [
        {
            "surah_num": 25,
            "from_ayah": 7,
            "to_ayah": 7,
            "full_text": "a b c",
            "confidence": 1.0,
            "start_time": 0.0,
            "end_time": 10.0,
            "word_timings": [
                {"word": "a", "start": 1.0, "end": 2.0},
                {"word": "b", "start": 2.0, "end": 3.0},
                {"word": "c", "start": 3.0, "end": 4.0},
            ],
        }
    ]
    session = ReviewSession(Project(audio=__import__("pathlib").Path("a.mp3"), cards=cards))
    vp = Viewport()
    vp.set_duration(10.0)
    vp.set_window(0.0, 10.0)
    strip = WordStrip(vp, session)
    strip.resize(1000, 34)
    return session, strip


def test_clicking_a_word_selects_it_and_seeks(qt_app) -> None:
    session, strip = _strip(qt_app)
    seeks = []
    strip.seek_requested.connect(seeks.append)
    QTest.mouseClick(strip, Qt.MouseButton.LeftButton, pos=QPoint(250, 17))
    assert strip.selected.word == 1 and seeks == [pytest.approx(2.0)]


def test_dragging_an_edge_retimes_through_the_session_as_one_undo(qt_app) -> None:
    session, strip = _strip(qt_app)
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, pos=QPoint(200, 17))
    for x in (210, 230, 250):
        QTest.mouseMove(strip, QPoint(x, 17))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, pos=QPoint(250, 17))
    words = session.words()
    assert words[1].start == pytest.approx(2.5, abs=0.02)
    assert words[0].end == pytest.approx(2.5, abs=0.02)
    session.undo()
    assert session.words()[1].start == 2.0
    assert not session.can_undo


@pytest.mark.parametrize(
    "modifier", [Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.AltModifier]
)
def test_dragging_a_joined_edge_with_ctrl_or_alt_leaves_the_neighbour(qt_app, modifier) -> None:
    session, strip = _strip(qt_app)
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, modifier, QPoint(200, 17))
    QTest.mouseMove(strip, QPoint(180, 17))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, modifier, QPoint(180, 17))
    words = session.words()
    assert words[0].end == pytest.approx(1.8, abs=0.02)
    assert words[1].start == 2.0, "detached: the next word stays where it was"


def test_shift_dragging_ripples_the_rest(qt_app) -> None:
    session, strip = _strip(qt_app)
    QTest.mousePress(
        strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, QPoint(250, 17)
    )
    QTest.mouseMove(strip, QPoint(300, 17))
    QTest.mouseRelease(
        strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, QPoint(300, 17)
    )
    assert [w.start for w in session.words()] == pytest.approx([1.0, 2.5, 3.5], abs=0.02)


def test_losing_focus_mid_drag_closes_the_gesture(qt_app) -> None:
    """A genuine focus change (not a synthetic event) mid-drag closes the gesture.

    ``WordStrip`` is a child widget: it never receives ``ActivationChange``
    (only a top-level widget does), and with the default ``Qt.NoFocus``
    policy it never receives ``FocusOut`` either, since it never holds focus
    in the first place. ``ClickFocus`` fixes both: a press gives the strip
    real focus, so moving focus elsewhere delivers a real ``FocusOut``. This
    is exercised end to end — a real top-level window, a real second
    focusable widget, ``other.setFocus()`` — rather than a synthetic
    ``QFocusEvent`` sent straight to the strip, which passed even before
    ``ClickFocus`` was added and so did not catch the bug.
    """
    from PySide6.QtWidgets import QLineEdit, QWidget

    from qurantext.gui.review.session import CARD, WordRef

    session, strip = _strip(qt_app)
    container = QWidget()
    strip.setParent(container)
    strip.move(0, 0)
    strip.resize(1000, 34)
    other = QLineEdit(container)
    other.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    other.move(0, 40)
    other.resize(200, 24)
    container.resize(1000, 80)
    container.show()
    qt_app.processEvents()

    QTest.mousePress(strip, Qt.MouseButton.LeftButton, pos=QPoint(200, 17))
    assert strip.hasFocus(), "a press must give the strip real focus (ClickFocus policy)"
    QTest.mouseMove(strip, QPoint(210, 17))
    assert session.can_undo  # the edge drag already opened a gesture

    other.setFocus(Qt.FocusReason.MouseFocusReason)
    qt_app.processEvents()
    assert other.hasFocus()
    assert not strip.hasFocus()  # the strip really lost focus; this is not a synthetic event

    # A retime from outside the strip, after the gesture was closed by the
    # real FocusOut, must open an undo entry of its own rather than merging
    # into the drag.
    session.retime(WordRef(CARD, 0, 2), end=4.5)
    assert session.words()[2].end == pytest.approx(4.5)

    assert session.undo()
    assert session.words()[2].end == pytest.approx(4.0)
    assert session.undo()
    assert session.words()[1].start == pytest.approx(2.0)
    assert not session.can_undo

    container.close()


def test_an_edge_is_grabbed_from_eight_pixels_away(qt_app) -> None:
    session, strip = _strip(qt_app)
    first = session.words()[0]
    x_end = strip._viewport.x_for(first.end, strip.width())
    assert strip._hit_test(x_end - 7) == ("end", first.ref)
    assert strip._hit_test(x_end + 7)[0] in ("end", "start")
    assert strip.EDGE_PX == 8


def test_the_strip_is_tall_enough_to_hit(qt_app) -> None:
    _, strip = _strip(qt_app)
    assert strip.sizeHint().height() == 44


def test_the_edge_under_the_pointer_is_highlighted_until_the_pointer_leaves(qt_app) -> None:
    from PySide6.QtCore import QEvent

    session, strip = _strip(qt_app)
    strip.show()
    first = session.words()[0]
    x_end = strip._viewport.x_for(first.end, strip.width())
    QTest.mouseMove(strip, QPoint(int(x_end), strip.height() // 2))
    assert strip.hovered_edge == ("end", first.ref)
    QTest.mouseMove(strip, QPoint(int(x_end) + 40, strip.height() // 2))
    assert strip.hovered_edge is None
    QTest.mouseMove(strip, QPoint(int(x_end), strip.height() // 2))
    qt_app.sendEvent(strip, QEvent(QEvent.Type.Leave))
    assert strip.hovered_edge is None


def test_the_playhead_red_comes_from_the_palette(qt_app) -> None:
    from qurantext.gui.review import waveform_view, word_strip

    assert not hasattr(waveform_view, "_PLAYHEAD_COLOR")
    assert not hasattr(word_strip, "_PLAYHEAD_OUTLINE")
    assert not hasattr(word_strip, "_EDITED_DOT")


def test_a_selection_that_no_longer_exists_is_dropped(qt_app) -> None:
    session, strip = _strip(qt_app)
    strip.select(session.words()[2].ref)
    changes = []
    strip.selection_changed.connect(changes.append)

    session.remove_card(0)
    strip.refresh()

    assert strip.selected is None
    assert changes == [None]


def _long_lecture_session(total_words: int = 5000, total_seconds: float = 3000.0):
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import CaptionCue, Project

    words_per_cue = 5
    cues = total_words // words_per_cue
    word_len = total_seconds / total_words
    captions = []
    t = 0.0
    for i in range(cues):
        words = []
        for j in range(words_per_cue):
            words.append({"word": f"w{i}_{j}", "start": t, "end": t + word_len})
            t += word_len
        text = " ".join(w["word"] for w in words)
        captions.append(CaptionCue(words[0]["start"], words[-1]["end"], text, words=words))
    project = Project(
        audio=__import__("pathlib").Path("dars.mp3"), mode="lecture", cards=[], captions=captions
    )
    return ReviewSession(project)


def test_strip_paints_a_long_lecture_quickly(qt_app) -> None:
    from qurantext.gui.review.word_strip import WordStrip

    session = _long_lecture_session()
    assert len(session.words()) == 5000

    vp = Viewport()
    vp.set_duration(3000.0)
    vp.set_window(1500.0, 60.0)
    strip = WordStrip(vp, session)
    strip.resize(1000, 34)

    strip.grab()  # warm up: font metrics, palette lookups, etc.
    calls = 20
    started = time.perf_counter()
    for _ in range(calls):
        strip.grab()
    elapsed_ms = (time.perf_counter() - started) * 1000 / calls
    assert elapsed_ms < 8.0, f"grab() averaged {elapsed_ms:.3f} ms over {calls} calls"


def test_frame_view_draws_the_active_card(qt_app) -> None:
    from qurantext.config.paths import DEFAULT_FONT_PATH
    from qurantext.gui.review.frame_view import FrameView

    if not DEFAULT_FONT_PATH.exists():
        pytest.skip("needs the bundled font")
    session, _ = _strip(qt_app)
    view = FrameView(session)
    view.show_at(2.5, force=True)
    assert view.pixmap() is not None and not view.pixmap().isNull()
    assert (view.pixmap().width(), view.pixmap().height()) == (270, 480)


def test_frame_view_throttles_while_playing(qt_app, monkeypatch) -> None:
    from qurantext.gui.review import frame_view as module

    session, _ = _strip(qt_app)
    calls = []
    monkeypatch.setattr(
        module,
        "render_frame_pillow",
        lambda *a, **k: calls.append(a[0]) or np.zeros((480, 270, 3), np.uint8),
    )
    view = module.FrameView(session)
    for t in (1.0, 1.05, 1.1):
        view.show_at(t)
    view.show_at(1.15, force=True)
    assert calls == [1.0, 1.15]


def test_segment_list_locks_quran_text_and_seeks(qt_app) -> None:
    from qurantext.gui.review.segment_list import SegmentList

    session, _ = _strip(qt_app)
    table = SegmentList(session)
    assert table.rowCount() == 1
    text_item = table.item(0, 2)
    assert not (text_item.flags() & Qt.ItemFlag.ItemIsEditable)
    seeks = []
    table.seek_requested.connect(seeks.append)
    table.cellClicked.emit(0, 0)
    assert seeks == [pytest.approx(0.0)]


def test_segment_list_edits_caption_text_through_the_session(qt_app) -> None:
    from qurantext.gui.review.segment_list import SegmentList
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import CaptionCue, Project

    project = Project(
        audio=__import__("pathlib").Path("d.mp3"),
        mode="lecture",
        captions=[CaptionCue(0.0, 1.0, "misheard", words=[])],
    )
    session = ReviewSession(project)
    table = SegmentList(session)
    row = next(
        r
        for r in range(table.rowCount())
        if table.item(r, 0).data(Qt.ItemDataRole.UserRole) == ("caption", 0)
    )
    table.item(row, 2).setText("corrected")
    assert session.project.captions[0].text == "corrected" and session.can_undo


def test_frame_view_uses_the_lecture_intro_before_the_first_card(qt_app, monkeypatch) -> None:
    from qurantext.core.frame_renderer import placeholder_lines
    from qurantext.gui.review import frame_view as module
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import CaptionCue, Project

    cards = [
        {
            "surah_num": 25,
            "surah_name": "الفرقان",
            "from_ayah": 7,
            "to_ayah": 11,
            "full_text": "a b c",
            "confidence": 1.0,
            "start_time": 5.0,
            "end_time": 10.0,
        }
    ]
    project = Project(
        audio=__import__("pathlib").Path("d.mp3"),
        mode="lecture",
        cards=cards,
        captions=[CaptionCue(0.0, 4.0, "intro speech", words=[])],
    )
    session = ReviewSession(project)
    calls = []
    monkeypatch.setattr(
        module,
        "render_frame_pillow",
        lambda *a, **k: calls.append(k) or np.zeros((480, 270, 3), np.uint8),
    )
    view = module.FrameView(session)
    view.show_at(1.0, force=True)

    expected = placeholder_lines(session.validated_cards(), reserve_caption_band=True)
    assert (calls[0]["title"], calls[0]["placeholder_subtitle"]) == expected


def test_removing_a_row_clears_the_selection(qt_app) -> None:
    from qurantext.gui.review.segment_list import SegmentList
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import CaptionCue, Project

    cards = [
        {
            "surah_num": 25,
            "from_ayah": 7,
            "to_ayah": 7,
            "full_text": "a b c",
            "start_time": 0.0,
            "end_time": 1.0,
        }
    ]
    project = Project(
        audio=__import__("pathlib").Path("d.mp3"),
        mode="lecture",
        cards=cards,
        captions=[CaptionCue(1.0, 2.0, "spoken", words=[])],
    )
    session = ReviewSession(project)
    table = SegmentList(session)
    assert table.rowCount() == 2
    table.selectRow(0)
    assert table.selectedIndexes()
    assert table.remove_selected()
    assert table.rowCount() == 1
    assert not table.selectedIndexes()


def _three_cue_session():
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import CaptionCue, Project

    def cue(start, word):
        return CaptionCue(
            start, start + 1.0, word, words=[{"word": word, "start": start, "end": start + 1.0}]
        )

    project = Project(
        audio=__import__("pathlib").Path("d.mp3"),
        mode="lecture",
        captions=[cue(0.0, "one"), cue(2.0, "two"), cue(4.0, "three")],
    )
    return ReviewSession(project)


def test_the_playhead_row_is_marked_without_being_selected(qt_app) -> None:
    from qurantext.gui.review.segment_list import SegmentList

    table = SegmentList(_three_cue_session())
    table.highlight_at(0.5)
    table.highlight_at(2.5)
    assert not table.selectedIndexes()
    assert table.currentRow() == -1
    assert table.item(1, 2).background().style() != Qt.BrushStyle.NoBrush
    assert table.item(0, 2).background().style() == Qt.BrushStyle.NoBrush


def test_an_edge_dragged_past_its_neighbour_and_back_leaves_the_neighbour(qt_app) -> None:
    session, strip = _strip(qt_app)
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, pos=QPoint(200, 17))
    for x in (300, 350, 200):
        QTest.mouseMove(strip, QPoint(x, 17))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, pos=QPoint(200, 17))
    words = session.words()
    assert (words[0].end, words[1].start, words[1].end) == (2.0, 2.0, 3.0)


def test_a_ripple_dragged_past_the_clamp_and_back_ends_where_it_began(qt_app) -> None:
    session, strip = _strip(qt_app)
    shift = Qt.KeyboardModifier.ShiftModifier
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, shift, QPoint(350, 17))
    for x in (100, 0, 350):
        QTest.mouseMove(strip, QPoint(x, 17))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, shift, QPoint(350, 17))
    words = session.words()
    assert (words[1].end, words[2].start, words[2].end) == (3.0, 3.0, 4.0)


def test_segment_list_stretches_the_text_and_names_the_speech_rows(qt_app) -> None:
    from PySide6.QtWidgets import QHeaderView

    from qurantext.gui.i18n import t
    from qurantext.gui.review.segment_list import SegmentList

    table = SegmentList(_three_cue_session())
    header = table.horizontalHeader()
    assert header.sectionResizeMode(2) == QHeaderView.ResizeMode.Stretch
    for column in (0, 1, 3):
        assert header.sectionResizeMode(column) == QHeaderView.ResizeMode.ResizeToContents
    assert table.item(0, 0).text() == t("segments.speech") == "Speech"


def test_the_waveform_says_when_the_recording_is_missing(qt_app) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.waveform_view import WaveformView

    view = WaveformView(Viewport())
    assert view.placeholder() == t("waveform.reading")
    view.set_missing()
    assert view.placeholder() == t("waveform.missing") == "The recording is not available."


def test_the_last_waveform_column_ends_at_the_window(qt_app) -> None:
    from qurantext.gui.review.waveform_view import column_extremes

    # 10 s at 10 bins/s: quiet for the first 5 s, loud after.
    maxs = np.array([0.1] * 50 + [0.9] * 50, np.float32)
    peaks = Peaks(mins=-maxs, maxs=maxs, rate=10.0, duration=10.0)
    col_min, col_max = column_extremes(peaks, 0.0, 4.0, 4)
    assert col_max.tolist() == pytest.approx([0.1] * 4)
    assert col_min.tolist() == pytest.approx([-0.1] * 4)


def test_the_warnings_strip_lists_five_gaps_then_counts_the_rest(qt_app) -> None:
    from qurantext.core.coverage import UncoveredSpeech
    from qurantext.gui.review.warnings_strip import WarningsStrip

    strip = WarningsStrip()
    strip.set_gaps([UncoveredSpeech(float(i), i + 0.5, -20.0) for i in range(8)])
    assert strip.text().count("Jump") == 5
    assert "8 stretches of speech have no word:" in strip.text()
    assert "…and 3 more" in strip.text()
    assert "0.5 s at 0.0–0.5 s" in strip.text()


def test_the_warnings_strip_counts_a_single_gap_in_the_singular(qt_app) -> None:
    from qurantext.core.coverage import UncoveredSpeech
    from qurantext.gui.review.warnings_strip import WarningsStrip

    strip = WarningsStrip()
    strip.set_gaps([UncoveredSpeech(4.0, 6.0, -20.0)])
    assert "1 stretch of speech has no word:" in strip.text()
    assert "2.0 s at 4.0–6.0 s" in strip.text()


def test_the_selection_bar_shows_the_span_as_one_value(qt_app) -> None:
    from qurantext.gui.review.selection_bar import SelectionBar
    from qurantext.gui.review.session import CARD, TimelineWord, WordRef

    bar = SelectionBar()
    bar.show_word(
        TimelineWord(ref=WordRef(CARD, 0, 0), text="ٱلۡحَمۡدُ", start=1.5, end=2.25, edited=False)
    )
    # The Quran word is isolated even in English: leading the line unisolated,
    # it would lay the line out right to left and draw "2.25 → 1.50".
    assert bar.label.text() == "\u2068ٱلۡحَمۡدُ\u2069  1.50 → 2.25 s"


def test_the_segment_list_shows_a_row_s_times_as_one_span(qt_app) -> None:
    from qurantext.gui.review.segment_list import SegmentList

    session, _ = _strip(qt_app)
    table = SegmentList(session)
    assert table.item(0, 1).text() == "0.00–10.00"


def test_the_warnings_strip_says_it_is_checking_until_the_first_result(qt_app) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.warnings_strip import WarningsStrip

    strip = WarningsStrip()
    strip.set_checking(True)
    assert t("review.checking") in strip.text()
    assert t("review.checking") == "Checking the recording for speech with no word…"
    strip.set_gaps([])
    assert t("review.checking") not in strip.text()
    assert t("review.covered") in strip.text()


def test_jobs_that_end_at_once_are_let_go_safely(qt_app) -> None:
    """Dropping a finished thread before its OS thread exits crashed the process."""
    from PySide6.QtCore import QObject

    from qurantext.gui.review.background import BackgroundJobs

    class _Sink(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.failures = 0

        def failed(self, _message: str) -> None:
            self.failures += 1

        def finished(self, _result: object) -> None:
            pass

    def job(progress, cancel):
        raise ValueError("unreadable")

    sink = _Sink()
    jobs = BackgroundJobs()
    for _ in range(40):
        jobs.start(job, on_finished=sink.finished, on_failed=sink.failed)
        jobs.start(job, on_finished=sink.finished, on_failed=sink.failed)
        deadline = time.monotonic() + 5
        while jobs.active and time.monotonic() < deadline:
            _spin_briefly(qt_app)
    _spin_briefly(qt_app)
    assert jobs.active == 0 and sink.failures == 80


def _spin_briefly(qt_app) -> None:
    """Deliver what the workers sent, then sleep a moment, never holding the GIL.

    Not ``QTest.qWait``: PySide6 keeps the GIL for the whole of that call, so a
    worker needing it while holding a Qt lock the UI thread wants deadlocks the two.
    """
    qt_app.processEvents()
    time.sleep(0.005)
    qt_app.processEvents()


def test_threads_still_lingering_at_exit_are_joined_within_a_bound(qt_app, monkeypatch) -> None:
    """What ``gui/app.py`` waits for after the event loop ends, and for how long at most."""
    import threading

    from PySide6.QtCore import QThread

    from qurantext.gui.review import background

    release = threading.Event()

    class _Slow(QThread):
        def run(self) -> None:
            release.wait(10)

    monkeypatch.setattr(background, "_LINGERING", [])
    thread = _Slow()
    thread.start()
    background._LINGERING.append((thread, None))

    started = time.monotonic()
    assert not background.join_lingering(100), "still running: the bound gives up"
    assert time.monotonic() - started < 2
    assert background._LINGERING, "an unfinished thread stays parked"

    release.set()
    assert background.join_lingering(5000)
    assert background._LINGERING == []


def test_background_jobs_dropped_off_the_ui_thread_park_everything(qt_app, monkeypatch) -> None:
    """A finaliser runs on whichever thread drops the last reference: under the cyclic
    GC, possibly a worker. There it must not join a thread or drop a finished worker
    (deleting a Python-made QObject off the UI thread is what deadlocked 8572c7a's
    window); it parks every entry for the UI thread's next stop to let go of."""
    import threading

    from PySide6.QtCore import QObject

    from qurantext.gui.review import background
    from qurantext.gui.review.background import BackgroundJobs

    class _Sink(QObject):
        def finished(self, _result: object) -> None:
            pass

        def failed(self, _message: str) -> None:
            pass

    def at_once(progress, cancel):
        return None

    def until_cancelled(progress, cancel):
        while not cancel.cancelled:
            time.sleep(0.005)

    monkeypatch.setattr(background, "_LINGERING", [])
    sink = _Sink()
    jobs = BackgroundJobs()
    jobs.start(at_once, on_finished=sink.finished, on_failed=sink.failed)
    jobs.start(until_cancelled, on_finished=sink.finished, on_failed=sink.failed)
    first = jobs._running[0][0]
    deadline = time.monotonic() + 5
    while not first.isFinished() and time.monotonic() < deadline:
        _spin_briefly(qt_app)
    assert first.isFinished()

    worker_thread = threading.Thread(target=jobs.__del__)
    worker_thread.start()
    worker_thread.join(5)

    assert jobs._running == []
    assert len(background._LINGERING) == 2, "the finished one is parked, not joined and dropped"
    assert background.join_lingering(5000), "the running one was cancelled"
    _spin_briefly(qt_app)

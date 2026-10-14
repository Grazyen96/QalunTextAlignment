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
    # Right to left: a quarter of the way in from the left is three quarters through the window.
    assert vp.t_for(100.0, 400) == pytest.approx(25.0)
    assert vp.t_for(300.0, 400) == pytest.approx(15.0)


def test_the_viewport_runs_right_to_left(qt_app) -> None:
    vp = Viewport()
    vp.set_duration(100.0)
    vp.set_window(10.0, 20.0)
    # The window's start is at the right edge, its end at the left.
    assert vp.x_for(10.0, 400) == pytest.approx(400.0)
    assert vp.x_for(30.0, 400) == pytest.approx(0.0)
    assert vp.t_for(400.0, 400) == pytest.approx(10.0)
    assert vp.t_for(0.0, 400) == pytest.approx(30.0)
    # Later time lies further left.
    assert vp.x_for(12.0, 400) > vp.x_for(13.0, 400)
    # The two mappings undo each other both ways.
    for x in (0.0, 1.0, 37.5, 200.0, 399.0, 400.0):
        assert vp.x_for(vp.t_for(x, 400), 400) == pytest.approx(x)
    for t in (10.0, 11.25, 20.0, 29.9, 30.0):
        assert vp.t_for(vp.x_for(t, 400), 400) == pytest.approx(t)


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
    # The followed playhead sits 10 % in from the right edge, the runway to its left.
    assert vp.x_for(12.0, 500) == pytest.approx(450.0)


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


def test_a_click_at_the_waveforms_far_right_seeks_to_the_windows_start(qt_app) -> None:
    from qurantext.gui.review.waveform_view import WaveformView

    vp = Viewport()
    vp.set_duration(100.0)
    vp.set_window(30.0, 10.0)
    view = WaveformView(vp)
    view.resize(500, 90)
    asked = []
    view.seek_requested.connect(asked.append)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(499, 45))
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(0, 45))
    assert asked == [pytest.approx(30.0, abs=0.05), pytest.approx(40.0, abs=0.05)]


def test_the_waveform_draws_the_windows_start_at_the_right(qt_app) -> None:
    from PySide6.QtGui import QPalette

    from qurantext.gui.review.waveform_view import WaveformView

    # 10 s at 10 bins/s: loud for the first 5 s, silent after.
    maxs = np.array([0.9] * 50 + [0.0] * 50, np.float32)
    vp = Viewport()
    vp.set_duration(10.0)
    vp.set_window(0.0, 10.0)
    view = WaveformView(vp)
    view.resize(200, 90)
    view.set_peaks(Peaks(mins=-maxs, maxs=maxs, rate=10.0, duration=10.0))
    view.set_playhead(9.95)  # out of the way, at the far left
    image = view.grab().toImage()
    background = view.palette().color(QPalette.ColorRole.Base)  # the panel
    near_top = 10  # only a loud column reaches this high
    assert image.pixelColor(150, near_top) != background, "the first 5 s are drawn on the right"
    assert image.pixelColor(50, near_top) == background, "the silent last 5 s on the left"


def test_a_gap_band_is_drawn_from_its_end_on_the_left_to_its_start_on_the_right(qt_app) -> None:
    from PySide6.QtGui import QPalette

    from qurantext.gui.review.waveform_view import WaveformView

    vp = Viewport()
    vp.set_duration(10.0)
    vp.set_window(0.0, 10.0)
    view = WaveformView(vp)
    view.resize(200, 90)
    view.set_gaps([(2.0, 4.0)])
    view.set_playhead(9.95)  # out of the way, at the far left
    image = view.grab().toImage()
    background = view.palette().color(QPalette.ColorRole.Base)  # the panel
    row = 5  # above the "reading" placeholder text
    # 2-4 s is x 120-160 right to left; left to right it would be x 40-80.
    for x in (122, 125, 140, 155, 158):
        assert image.pixelColor(x, row) != background, x
    for x in (45, 60, 75, 110, 170):
        assert image.pixelColor(x, row) == background, x


def _playhead_columns(view) -> list[int]:
    from qurantext.gui.colors import playhead_color

    image = view.grab().toImage()
    red = playhead_color(view.palette())
    return [x for x in range(view.width()) if image.pixelColor(x, 45) == red]


def test_a_playhead_outside_the_window_is_not_drawn(qt_app) -> None:
    from qurantext.gui.review.waveform_view import WaveformView

    vp = Viewport()
    vp.set_duration(100.0)
    vp.set_window(50.0, 10.0)
    view = WaveformView(vp)
    view.resize(200, 90)
    view.set_playhead(20.0)  # before the window: not pinned to its right edge
    assert _playhead_columns(view) == []
    view.set_playhead(70.0)  # after it: not pinned to its left edge
    assert _playhead_columns(view) == []
    view.set_playhead(55.0)
    # Halfway: column 99 holds [55, 55.05); the 2 px line spans it and its left neighbour.
    assert _playhead_columns(view) == [98, 99]


@pytest.mark.parametrize(("duration", "span"), [(100.0, 10.0), (7.3, 2.1), (3.7, 1.3)])
def test_a_playhead_at_the_recordings_end_is_drawn_at_the_left(qt_app, duration, span) -> None:
    from qurantext.gui.review.waveform_view import WaveformView

    vp = Viewport()
    vp.set_duration(duration)
    vp.set_window(0.0, span)
    vp.follow(duration)  # playback finished: the window goes as far as it can
    assert vp.start + vp.span == pytest.approx(duration)
    view = WaveformView(vp)
    view.resize(200, 90)
    view.set_playhead(duration)  # exactly start + span: x is 0 (or -4e-14 after rounding)
    assert _playhead_columns(view) == [0]
    view.set_playhead(duration + 0.01)  # past the window's end: still hidden
    assert _playhead_columns(view) == []
    view.set_playhead(vp.start - 0.01)  # before its start: still hidden
    assert _playhead_columns(view) == []


def test_a_playhead_at_the_windows_start_is_drawn(qt_app) -> None:
    from qurantext.gui.colors import playhead_color
    from qurantext.gui.review.waveform_view import WaveformView

    vp = Viewport()
    vp.set_duration(10.0)
    vp.set_window(0.0, 10.0)
    view = WaveformView(vp)
    view.resize(200, 90)
    view.set_playhead(0.0)
    image = view.grab().toImage()
    assert image.pixelColor(199, 45) == playhead_color(view.palette())


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
    QTest.mouseClick(strip, Qt.MouseButton.LeftButton, pos=QPoint(750, 17))  # 2.5 s
    assert strip.selected.word == 1 and seeks == [pytest.approx(2.0)]


def test_the_first_word_is_drawn_at_the_right(qt_app) -> None:
    session, strip = _strip(qt_app)
    a, b, c = session.words()
    # Right to left: a (1-2 s) spans x 800-900, b 700-800, c 600-700.
    assert strip._hit_test(850) == ("body", a.ref)
    assert strip._hit_test(750) == ("body", b.ref)
    assert strip._hit_test(650) == ("body", c.ref)
    assert strip._hit_test(150) is None  # 8.5 s: no word there
    # A box's right edge is its start, its left edge its end.
    assert strip._hit_test(900) == ("start", a.ref)
    assert strip._hit_test(600) == ("end", c.ref)
    # The selected word's fill (the accent) covers its own box and not the earlier word's.
    from PySide6.QtGui import QColor

    from qurantext.gui import theme

    strip.select(b.ref)
    image = strip.grab().toImage()
    highlight = QColor(theme.current_tokens().accent)
    assert image.pixelColor(720, 6) == highlight
    assert image.pixelColor(880, 6) != highlight


def test_dragging_a_words_right_edge_moves_its_start_and_left_edge_its_end(qt_app) -> None:
    session, strip = _strip(qt_app)
    # a (1-2 s) is x 800-900: its right edge (900, shared with no word) is its start.
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, pos=QPoint(900, 17))
    QTest.mouseMove(strip, QPoint(880, 17))  # to the left: later
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, pos=QPoint(880, 17))
    a = session.words()[0]
    assert (strip.selected, strip.last_edge) == (a.ref, "start")
    assert a.start == pytest.approx(1.2, abs=0.02)
    assert a.end == 2.0
    # c (3-4 s) is x 600-700: its left edge (600) is its end; dragged left, it moves later.
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, pos=QPoint(600, 17))
    QTest.mouseMove(strip, QPoint(550, 17))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, pos=QPoint(550, 17))
    c = session.words()[2]
    assert (strip.selected, strip.last_edge) == (c.ref, "end")
    assert c.end == pytest.approx(4.5, abs=0.02)
    assert c.start == 3.0
    # A drag to the right makes the same edge earlier.
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, pos=QPoint(550, 17))
    QTest.mouseMove(strip, QPoint(620, 17))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, pos=QPoint(620, 17))
    assert session.words()[2].end == pytest.approx(3.8, abs=0.02)


def test_dragging_an_edge_retimes_through_the_session_as_one_undo(qt_app) -> None:
    session, strip = _strip(qt_app)
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, pos=QPoint(800, 17))
    for x in (790, 770, 750):
        QTest.mouseMove(strip, QPoint(x, 17))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, pos=QPoint(750, 17))
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
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, modifier, QPoint(800, 17))
    QTest.mouseMove(strip, QPoint(820, 17))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, modifier, QPoint(820, 17))
    words = session.words()
    assert words[0].end == pytest.approx(1.8, abs=0.02)
    assert words[1].start == 2.0, "detached: the next word stays where it was"


def test_shift_dragging_ripples_the_rest(qt_app) -> None:
    session, strip = _strip(qt_app)
    QTest.mousePress(
        strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, QPoint(750, 17)
    )
    QTest.mouseMove(strip, QPoint(700, 17))  # to the left: half a second later
    QTest.mouseRelease(
        strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, QPoint(700, 17)
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

    QTest.mousePress(strip, Qt.MouseButton.LeftButton, pos=QPoint(800, 17))
    assert strip.hasFocus(), "a press must give the strip real focus (ClickFocus policy)"
    QTest.mouseMove(strip, QPoint(790, 17))
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
    # Right to left, the first word's body lies to the right of its end.
    assert strip._hit_test(x_end + 7) == ("end", first.ref)
    assert strip._hit_test(x_end - 7)[0] in ("end", "start")
    assert strip.EDGE_PX == 8


def test_the_strip_is_tall_enough_to_hit(qt_app) -> None:
    _, strip = _strip(qt_app)
    assert strip.sizeHint().height() == 44


def test_the_edge_under_the_pointer_is_highlighted_until_the_pointer_leaves(qt_app) -> None:
    from PySide6.QtCore import QEvent

    session, strip = _strip(qt_app)
    strip.show()
    # Until the offscreen window is exposed, Qt routes a move by the screen
    # under the global point; the edge (global x about 804) lies outside the
    # 800 px offscreen screen, so an early move would be dropped.
    assert QTest.qWaitForWindowExposed(strip)
    first = session.words()[0]
    x_end = strip._viewport.x_for(first.end, strip.width())
    QTest.mouseMove(strip, QPoint(int(x_end), strip.height() // 2))
    assert strip.hovered_edge == ("end", first.ref)
    QTest.mouseMove(strip, QPoint(int(x_end) - 40, strip.height() // 2))
    assert strip.hovered_edge is None
    QTest.mouseMove(strip, QPoint(int(x_end), strip.height() // 2))
    qt_app.sendEvent(strip, QEvent(QEvent.Type.Leave))
    assert strip.hovered_edge is None


def test_the_edge_handle_shows_on_the_selected_word(qt_app) -> None:
    from PySide6.QtGui import QPalette

    session, strip = _strip(qt_app)
    strip.show()
    # Until the offscreen window is exposed, Qt routes a move by the screen
    # under the global point; the edge (global x about 804) lies outside the
    # 800 px offscreen screen, so an early move would be dropped.
    assert QTest.qWaitForWindowExposed(strip)
    first = session.words()[0]
    strip.select(first.ref)
    x_end = strip._viewport.x_for(first.end, strip.width())
    QTest.mouseMove(strip, QPoint(int(x_end), strip.height() // 2))
    assert strip.hovered_edge == ("end", first.ref)
    image = strip.grab().toImage()
    highlight = strip.palette().color(QPalette.ColorRole.Highlight)
    for x in (int(x_end) - 1, int(x_end)):
        assert image.pixelColor(x, strip.height() // 2) != highlight


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
    assert table.playhead_row() == 1


def test_an_edge_dragged_past_its_neighbour_and_back_leaves_the_neighbour(qt_app) -> None:
    session, strip = _strip(qt_app)
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, pos=QPoint(800, 17))
    QTest.mouseMove(strip, QPoint(700, 17))
    assert session.words()[0].end > 2.5, "the press grabbed the a/b edge and dragged it later"
    for x in (650, 800):
        QTest.mouseMove(strip, QPoint(x, 17))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, pos=QPoint(800, 17))
    words = session.words()
    assert (words[0].end, words[1].start, words[1].end) == (2.0, 2.0, 3.0)


def test_a_ripple_dragged_past_the_clamp_and_back_ends_where_it_began(qt_app) -> None:
    session, strip = _strip(qt_app)
    shift = Qt.KeyboardModifier.ShiftModifier
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, shift, QPoint(650, 17))
    QTest.mouseMove(strip, QPoint(900, 17))
    assert session.words()[2].start < 3.0, "the press started a ripple and it moved c earlier"
    for x in (1000, 650):
        QTest.mouseMove(strip, QPoint(x, 17))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, shift, QPoint(650, 17))
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


def test_the_selection_bar_shows_the_span_as_one_value(qt_app) -> None:
    from qurantext.gui.review.player import RATES
    from qurantext.gui.review.selection_bar import SelectionBar
    from qurantext.gui.review.session import CARD, TimelineWord, WordRef
    from qurantext.gui.review.transport import Transport

    bar = SelectionBar(Transport(RATES))
    bar.show_word(
        TimelineWord(ref=WordRef(CARD, 0, 0), text="ٱلۡحَمۡدُ", start=1.5, end=2.25, edited=False)
    )
    # The Quran word is isolated even in English: leading the line unisolated,
    # it would lay the line out right to left and draw "00:02.25 → 00:01.50".
    assert bar.label.text() == "\u2068ٱلۡحَمۡدُ\u2069  00:01.50 → 00:02.25"


def test_the_segment_list_shows_a_row_s_times_as_one_span(qt_app) -> None:
    from qurantext.gui.review.segment_list import SegmentList

    session, _ = _strip(qt_app)
    table = SegmentList(session)
    assert table.item(0, 1).text() == "00:00.00–00:10.00"


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


def test_preview_follows_undo_of_a_look_change(qt_app) -> None:
    from qurantext.config.paths import DEFAULT_FONT_PATH
    from qurantext.core.looks import PRESETS
    from qurantext.gui.review.frame_view import FrameView

    if not DEFAULT_FONT_PATH.exists():
        pytest.skip("needs the bundled font")
    session, _ = _strip(qt_app)
    view = FrameView(session)
    view.show_at(0.0, force=True)
    before = view.pixmap().toImage()
    session.set_look(PRESETS["ink_on_paper"])
    view.show_at(0.0, force=True)
    assert view.pixmap().toImage() != before
    session.undo()
    view.show_at(0.0, force=True)
    assert view.pixmap().toImage() == before


# -- the Look panel ----------------------------------------------------------------


@pytest.fixture()
def session(tmp_path):
    """A saved project's session: the panel copies a chosen image beside its file."""
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import Project, load_project, save_project

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
    path = save_project(Project(audio=tmp_path / "a.mp3", cards=cards), tmp_path / "a.qalun.json")
    return ReviewSession(load_project(path))


def _panel(session, prefs):
    from qurantext.gui.review.look_panel import LookPanel

    return LookPanel(session, prefs=prefs, frame_size=(270, 480), reserve_caption_band=False)


def _recorded(signal) -> list:
    seen: list = []
    signal.connect(lambda *args: seen.append(args))
    return seen


def _answer_colours(monkeypatch, *colours, accept: bool = True) -> list:
    """The colour dialog: each of *colours* is tried in turn, then OK (or Cancel).

    Returns what the session's look was after each try, as the preview drew it.
    """
    from PySide6.QtWidgets import QColorDialog

    seen: list = []

    def exec_(dialog) -> int:
        for colour in colours:
            dialog.setCurrentColor(colour)
            seen.append(dialog.parent()._session.look)
        return 1 if accept else 0

    monkeypatch.setattr(QColorDialog, "exec", exec_)
    return seen


def test_choosing_a_palette_sets_the_session_look(qt_app, session, prefs) -> None:
    from qurantext.core.looks import PRESETS

    panel = _panel(session, prefs)
    changed = _recorded(panel.look_changed)
    panel.palette_buttons["emerald"].click()
    assert changed
    assert session.look == PRESETS["emerald"]
    assert panel.status_label.text() == "Emerald"


def test_customise_is_folded_away_until_opened(qt_app, session, prefs) -> None:
    panel = _panel(session, prefs)
    panel.show()
    assert not panel.colour_buttons["body_text"].isVisible()
    panel.customise_toggle.click()
    assert panel.colour_buttons["body_text"].isVisible()


def test_one_customised_colour_reads_as_custom(qt_app, session, prefs, monkeypatch) -> None:
    from PySide6.QtGui import QColor

    _answer_colours(monkeypatch, QColor(10, 200, 30, 255))
    panel = _panel(session, prefs)
    changed = _recorded(panel.look_changed)
    panel.colour_buttons["highlight_word"].click()
    assert changed
    assert session.look.highlight_word == (10, 200, 30, 255)
    assert "Night gold" in panel.status_label.text() and session.look.base_preset == "night_gold"
    assert panel.status_label.text() == "Custom (from Night gold)"


def test_a_cancelled_colour_dialog_changes_nothing(qt_app, session, prefs, monkeypatch) -> None:
    _answer_colours(monkeypatch, accept=False)
    panel = _panel(session, prefs)
    changed = _recorded(panel.look_changed)
    panel.colour_buttons["card"].click()
    assert not changed and not session.can_undo


def test_the_colour_dialog_previews_live_and_is_one_undo_step(
    qt_app, session, prefs, monkeypatch
) -> None:
    from PySide6.QtGui import QColor

    from qurantext.core.looks import NIGHT_GOLD

    tried = _answer_colours(monkeypatch, QColor(200, 0, 0), QColor(0, 0, 200))
    panel = _panel(session, prefs)
    changed = _recorded(panel.look_changed)
    panel.colour_buttons["body_text"].click()
    assert [look.body_text for look in tried] == [(200, 0, 0, 255), (0, 0, 200, 255)]
    assert len(changed) >= 2, "each colour tried is shown in the preview"
    assert session.look.body_text == (0, 0, 200, 255)
    assert session.undo() and session.look == NIGHT_GOLD
    assert not session.can_undo


def test_a_cancelled_colour_dialog_takes_back_what_it_previewed(
    qt_app, session, prefs, monkeypatch
) -> None:
    from PySide6.QtGui import QColor

    from qurantext.core.looks import NIGHT_GOLD

    tried = _answer_colours(monkeypatch, QColor(200, 0, 0), accept=False)
    panel = _panel(session, prefs)
    changed = _recorded(panel.look_changed)
    panel.colour_buttons["header_text"].click()
    assert tried[0].header_text == (200, 0, 0, 255)
    assert session.look == NIGHT_GOLD and not session.can_undo and not session.dirty
    assert changed, "the preview is drawn again without the colour"


def test_every_colour_the_contrast_warning_names_has_a_picker(qt_app, session, prefs) -> None:
    from qurantext.core.looks import _CAPTION_TEXT, _CARD_TEXT

    panel = _panel(session, prefs)
    assert set(_CARD_TEXT) | set(_CAPTION_TEXT) <= set(panel.colour_buttons)
    assert panel.colour_buttons["placeholder_text"].text() == "Opening text"


def test_the_opening_text_picker_clears_its_warning(qt_app, session, prefs, monkeypatch) -> None:
    from dataclasses import replace

    from PySide6.QtGui import QColor

    from qurantext.core.looks import NIGHT_GOLD

    dark = (20, 20, 20, 255)
    # A light card with dark text, except the opening text left light grey.
    session.set_look(
        replace(
            NIGHT_GOLD,
            card=(240, 240, 235, 255),
            body_text=dark,
            header_text=dark,
            highlight_word=dark,
        )
    )
    panel = _panel(session, prefs)
    panel.show()
    assert panel.contrast_label.isVisible()
    assert panel.contrast_label.text() == "Hard to read: Opening text"
    _answer_colours(monkeypatch, QColor(*dark))
    panel.colour_buttons["placeholder_text"].click()
    assert session.look.placeholder_text == dark
    assert not panel.contrast_label.isVisible()


def test_the_contrast_warning_takes_the_new_amber_on_a_theme_switch(qt_app, session, prefs) -> None:
    from dataclasses import replace

    from qurantext.core.looks import NIGHT_GOLD
    from qurantext.gui import theme
    from qurantext.gui.colors import warning_color

    dark = (20, 20, 20, 255)
    session.set_look(replace(NIGHT_GOLD, card=(240, 240, 235, 255), body_text=dark))
    theme.apply_theme(qt_app, "light")
    panel = _panel(session, prefs)
    panel.show()
    assert panel.contrast_label.isVisible()
    light_amber = warning_color(theme.palette(theme.LIGHT)).name()
    assert light_amber in panel.contrast_label.styleSheet()
    theme.apply_theme(qt_app, "dark")
    assert warning_color(theme.palette(theme.DARK)).name() in panel.contrast_label.styleSheet()
    panel.close()


def test_the_background_colour_sets_a_solid_background_and_the_frame(
    qt_app, session, prefs, monkeypatch
) -> None:
    from PySide6.QtGui import QColor

    from qurantext.core.looks import NIGHT_GOLD

    _answer_colours(monkeypatch, QColor(90, 20, 40, 128))
    panel = _panel(session, prefs)
    assert panel.background_colour_button.text() == "Background colour"
    panel.background_colour_button.click()
    bg = session.look.background
    red = (90, 20, 40, 255)  # a background is opaque
    assert (bg.kind, bg.colour, bg.colour2) == ("solid", red, red)
    assert session.look.frame_bg == red
    assert panel.status_label.text() == "Custom (from Night gold)"
    assert session.undo() and session.look == NIGHT_GOLD


@pytest.mark.parametrize("kind", ["gradient", "pattern_lattice"])
def test_the_background_colour_of_a_gradient_or_pattern_keeps_a_second_colour(
    qt_app, session, prefs, monkeypatch, kind
) -> None:
    from PySide6.QtGui import QColor

    from qurantext.core.looks import NIGHT_GOLD

    panel = _panel(session, prefs)
    panel.background_tiles[kind].click()
    _answer_colours(monkeypatch, QColor(10, 60, 30))
    panel.background_colour_button.click()
    bg = session.look.background
    assert bg.kind == kind and bg.colour == (10, 60, 30, 255)
    assert bg.colour2 == (32, 82, 52, 255), "a lighter shade of a dark colour"
    assert session.look.frame_bg == NIGHT_GOLD.frame_bg


def test_an_image_background_has_no_colour_to_pick(
    qt_app, session, prefs, tmp_path, monkeypatch
) -> None:
    from PIL import Image
    from PySide6.QtWidgets import QFileDialog

    src = tmp_path / "photo.png"
    Image.new("RGB", (20, 20), (200, 10, 10)).save(src)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(src), ""))
    panel = _panel(session, prefs)
    panel.show()
    panel.customise_toggle.click()
    assert panel.background_colour_button.isVisible()
    panel.image_button.click()
    assert not panel.background_colour_button.isVisible()
    assert panel.background_tiles["image"].isChecked()


def test_low_contrast_shows_a_warning_that_names_the_part(
    qt_app, session, prefs, monkeypatch
) -> None:
    from PySide6.QtGui import QColor

    _answer_colours(monkeypatch, QColor(40, 40, 46, 255))
    panel = _panel(session, prefs)
    panel.show()
    assert not panel.contrast_label.isVisible()
    panel.colour_buttons["body_text"].click()
    assert panel.contrast_label.isVisible() and "Ayah text" in panel.contrast_label.text()


def test_a_dim_drag_is_one_undo_step(qt_app, session, prefs) -> None:
    from qurantext.core.looks import NIGHT_GOLD

    panel = _panel(session, prefs)
    panel.dim_slider.sliderPressed.emit()
    for v in (10, 20, 30):
        panel.dim_slider.setValue(v)
    panel.dim_slider.sliderReleased.emit()
    assert session.look.background.dim == 0.3
    assert session.undo() and session.look == NIGHT_GOLD
    assert not session.can_undo


def test_an_opacity_drag_sets_the_card_alpha_as_one_undo_step(qt_app, session, prefs) -> None:
    from qurantext.core.looks import NIGHT_GOLD

    panel = _panel(session, prefs)
    panel.opacity_slider.sliderPressed.emit()
    for v in (80, 60, 50):
        panel.opacity_slider.setValue(v)
    panel.opacity_slider.sliderReleased.emit()
    assert session.look.card == (*NIGHT_GOLD.card[:3], 128)
    assert session.undo() and session.look == NIGHT_GOLD


def test_a_built_in_background_keeps_the_colours_and_clears_dim(qt_app, session, prefs) -> None:
    from qurantext.core.looks import PRESETS

    panel = _panel(session, prefs)
    panel.palette_buttons["ocean"].click()
    panel.dim_slider.setValue(40)
    panel.background_tiles["solid"].click()
    bg = session.look.background
    frame_bg = PRESETS["ocean"].frame_bg
    assert (bg.kind, bg.colour, bg.colour2, bg.dim) == ("solid", frame_bg, frame_bg, 0.0)
    assert session.look.frame_bg == bg.colour
    panel.background_tiles["pattern_stars"].click()
    bg = session.look.background
    assert bg.kind == "pattern_stars" and bg.colour == frame_bg and bg.colour2 != bg.colour


def test_choosing_an_image_copies_it_beside_the_project(
    qt_app, session, prefs, tmp_path, monkeypatch
) -> None:
    from PIL import Image
    from PySide6.QtWidgets import QFileDialog

    src = tmp_path / "photo.png"
    Image.new("RGB", (20, 20), (200, 10, 10)).save(src)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(src), ""))
    panel = _panel(session, prefs)
    panel.image_button.click()
    bg = session.look.background
    assert bg.kind == "image" and bg.dim == 0.35
    assert bg.image.parent.name.endswith(".look") and bg.image.is_file()
    assert panel.background_tiles["image"].isChecked()
    assert panel.dim_slider.value() == 35


def test_cancelling_the_image_tile_leaves_the_kind(
    qt_app, session, prefs, tmp_path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    panel = _panel(session, prefs)
    panel.background_tiles["image"].click()
    assert not session.can_undo, "a cancelled choice is no edit"
    assert panel.background_tiles["solid"].isChecked(), "the tiles go back to what the look has"
    assert not panel.background_tiles["image"].isChecked()


def test_an_image_that_cannot_be_used_says_so(
    qt_app, session, prefs, tmp_path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QFileDialog

    gone = tmp_path / "gone.png"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(gone), ""))
    panel = _panel(session, prefs)
    notices = _recorded(panel.notice)
    panel.image_button.click()
    assert notices == [("\u2068gone.png\u2069 could not be used as a background.",)]
    assert not session.can_undo


def test_a_missing_image_is_reported(qt_app, session, prefs, tmp_path, monkeypatch) -> None:
    from PIL import Image
    from PySide6.QtWidgets import QFileDialog

    src = tmp_path / "photo.png"
    Image.new("RGB", (20, 20), (200, 10, 10)).save(src)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(src), ""))
    panel = _panel(session, prefs)
    panel.image_button.click()
    session.look.background.image.unlink()
    notices = _recorded(panel.look_notices)
    panel.blur_slider.setValue(5)
    missing = "The background image is missing; the palette's background is shown instead."
    assert notices[-1] == ([missing],)
    panel.reset_button.click()
    assert notices[-1] == ([],), "a look without the problem takes the line back"


def test_a_project_without_a_file_cannot_take_an_image(qt_app, prefs) -> None:
    from pathlib import Path

    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import Project

    panel = _panel(ReviewSession(Project(audio=Path("a.mp3"))), prefs)
    assert not panel.image_button.isEnabled()
    assert panel.image_button.toolTip() == "This project has no file to write back to."
    assert not panel.background_tiles["image"].isEnabled()
    assert panel.background_tiles["image"].toolTip() == panel.image_button.toolTip()


def test_use_for_new_videos_saves_the_default(qt_app, session, prefs) -> None:
    from qurantext.core.looks import PRESETS

    panel = _panel(session, prefs)
    messages = _recorded(panel.message)
    panel.palette_buttons["rose"].click()
    panel.default_button.click()
    assert prefs.default_look == PRESETS["rose"]
    assert messages == [("New videos will start with this look.",)]


def test_a_default_that_cannot_be_saved_says_why(qt_app, session, prefs, monkeypatch) -> None:
    from qurantext.gui.prefs import Prefs

    def refuse(self, look):
        raise OSError("read-only")

    monkeypatch.setattr(Prefs, "save_default_look", refuse)
    panel = _panel(session, prefs)
    notices = _recorded(panel.notice)
    panel.default_button.click()
    assert notices and "could not be used" in notices[0][0]


def test_reset_returns_to_night_gold(qt_app, session, prefs) -> None:
    from qurantext.core.looks import NIGHT_GOLD

    panel = _panel(session, prefs)
    panel.palette_buttons["sand"].click()
    panel.reset_button.click()
    assert session.look == NIGHT_GOLD


def test_refresh_follows_undo_without_emitting(qt_app, session, prefs) -> None:
    panel = _panel(session, prefs)
    panel.palette_buttons["ocean"].click()
    session.undo()
    changed = _recorded(panel.look_changed)
    panel.refresh()
    assert not changed
    assert panel.status_label.text() == "Night gold"
    assert panel.palette_buttons["night_gold"].isChecked()
    assert not panel.palette_buttons["ocean"].isChecked()


def test_the_swatches_keep_their_order_in_arabic(qt_app, session, prefs) -> None:
    from qurantext.gui import i18n

    i18n.set_language("ar")
    panel = _panel(session, prefs)
    panel.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    panel.resize(260, 900)
    panel.show()
    _spin_briefly(qt_app)
    xs = [panel.palette_buttons[name].x() for name in ("night_gold", "emerald", "sand")]
    assert xs == sorted(xs)


def test_palette_tiles_are_56_by_36_and_the_chosen_one_wears_a_gold_ring(
    qt_app, session, prefs
) -> None:
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QIcon

    from qurantext.core.looks import NIGHT_GOLD
    from qurantext.gui import theme

    panel = _panel(session, prefs)
    tile = panel.palette_buttons["night_gold"]
    assert tile.iconSize() == QSize(56, 36)
    on = tile.icon().pixmap(QSize(56, 36), QIcon.Mode.Normal, QIcon.State.On).toImage()
    off = tile.icon().pixmap(QSize(56, 36), QIcon.Mode.Normal, QIcon.State.Off).toImage()
    assert on.pixelColor(0, 18) == QColor(theme.current_tokens().gold)
    assert off.pixelColor(0, 18) == QColor(*NIGHT_GOLD.frame_bg[:3])
    assert tile.isChecked()


def test_colour_rows_show_the_hex_and_follow_a_pick(qt_app, session, prefs, monkeypatch) -> None:
    from PySide6.QtGui import QColor

    from qurantext.core.looks import NIGHT_GOLD

    panel = _panel(session, prefs)
    row = panel.colour_buttons["highlight_word"]
    assert row.property("row") is True and row.text() == "Highlighted word"
    assert row.hex_label.text() == "#{:02X}{:02X}{:02X}".format(*NIGHT_GOLD.highlight_word[:3])
    _answer_colours(monkeypatch, QColor(1, 2, 3))
    row.click()
    assert row.hex_label.text() == "#010203"


def test_every_slider_has_a_readout_that_follows_it(qt_app, session, prefs) -> None:
    panel = _panel(session, prefs)
    panel.opacity_slider.setValue(70)
    panel.dim_slider.setValue(35)
    panel.blur_slider.setValue(8)
    assert panel.opacity_readout.text() == "70%"
    assert panel.dim_readout.text() == "35%"
    assert panel.blur_readout.text() == "8"
    assert panel.dim_readout.width() == 44 or panel.dim_readout.minimumWidth() == 44


def test_reset_and_choose_image_are_quiet_and_use_for_new_is_not(qt_app, session, prefs) -> None:
    panel = _panel(session, prefs)
    assert panel.reset_button.property("quiet") is True
    assert panel.image_button.property("quiet") is True
    assert panel.default_button.property("quiet") is None


def test_readouts_and_hex_read_left_to_right_in_arabic(qt_app, session, prefs) -> None:
    from qurantext.gui import i18n

    i18n.set_language("ar")
    panel = _panel(session, prefs)
    panel.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    assert panel.dim_readout.layoutDirection() == Qt.LayoutDirection.LeftToRight
    row = panel.colour_buttons["card"]
    assert row.hex_label.layoutDirection() == Qt.LayoutDirection.LeftToRight


def test_an_arabic_colour_row_starts_at_the_right_clear_of_its_hex(qt_app, session, prefs) -> None:
    """The sheet's ``text-align: left`` is the line's start: Qt mirrors it for Arabic.

    A rule aligning Arabic rows "right" was mirrored as well, which drew the chip
    and the name at the left, over the hex.
    """
    from PySide6.QtGui import QColor

    from qurantext.gui import i18n, theme

    i18n.set_language("ar")
    panel = _panel(session, prefs)
    panel.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    row = panel.colour_buttons["card"]
    row.setStyleSheet(theme.stylesheet(theme.current_tokens()))
    row.hex_label.hide()  # only the chip and the name are left to draw
    row.setFixedWidth(280)
    row.adjustSize()
    image = row.grab().toImage()
    ground = QColor(image.pixel(2, image.height() // 2))
    inked = [
        x
        for x in range(image.width())
        for y in range(image.height())
        if QColor(image.pixel(x, y)) != ground
    ]
    assert inked and min(inked) > image.width() // 2, (min(inked), image.width())


def test_there_is_a_tile_per_background_kind_and_the_looks_kind_is_checked(
    qt_app, session, prefs
) -> None:
    from PySide6.QtCore import QSize

    from qurantext.core.looks import BACKGROUND_KINDS
    from qurantext.gui.i18n import t

    panel = _panel(session, prefs)
    assert tuple(panel.background_tiles) == BACKGROUND_KINDS
    assert [k for k, b in panel.background_tiles.items() if b.isChecked()] == ["solid"]
    for kind, tile in panel.background_tiles.items():
        assert tile.iconSize() == QSize(56, 36) and tile.property("swatch") is True, kind
        assert tile.text() == t(f"look.bg.{kind}")
    panel.background_tiles["gradient"].click()
    assert [k for k, b in panel.background_tiles.items() if b.isChecked()] == ["gradient"]
    assert session.look.background.kind == "gradient"


def test_a_tile_is_painted_in_the_looks_colours(qt_app, session, prefs) -> None:
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QIcon

    from qurantext.core.looks import PRESETS

    panel = _panel(session, prefs)
    panel.palette_buttons["ocean"].click()
    image = (
        panel.background_tiles["solid"]
        .icon()
        .pixmap(QSize(56, 36), QIcon.Mode.Normal, QIcon.State.Off)
        .toImage()
    )
    assert image.pixelColor(28, 18) == QColor(*PRESETS["ocean"].frame_bg[:3])


def test_clicking_the_current_tile_again_changes_nothing(qt_app, session, prefs) -> None:
    from dataclasses import replace

    from qurantext.core.looks import PRESETS

    panel = _panel(session, prefs)
    panel.background_tiles["solid"].click()
    assert not session.can_undo and panel.background_tiles["solid"].isChecked()
    # A dimmed, blurred gradient keeps its dim and blur, and no undo step is recorded.
    ocean = PRESETS["ocean"]
    look = replace(ocean, background=replace(ocean.background, dim=0.4, blur=6.0))
    session.set_look(look)
    panel.refresh()
    revision = session.revision
    assert panel.background_tiles["gradient"].isChecked()
    panel.background_tiles["gradient"].click()
    assert session.look == look and session.revision == revision
    assert panel.background_tiles["gradient"].isChecked()
    assert (panel.dim_slider.value(), panel.blur_slider.value()) == (40, 6)


def test_a_gone_image_gives_the_image_tile_its_icon(
    qt_app, session, prefs, tmp_path, monkeypatch
) -> None:
    from PIL import Image
    from PySide6.QtWidgets import QFileDialog

    src = tmp_path / "photo.png"
    Image.new("RGB", (20, 20), (200, 10, 10)).save(src)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(src), ""))
    panel = _panel(session, prefs)
    panel.image_button.click()
    assert panel.background_tiles["image"].isChecked()
    session.look.background.image.unlink()
    panel.dim_slider.setValue(10)  # a change: the tiles rebuild with the image gone
    # No exception above is the point: the tile fell back to its icon and stays chosen.
    assert panel.background_tiles["image"].isChecked()
    assert session.look.background.kind == "image"


def test_the_tiles_do_not_widen_the_panel(qt_app, session, prefs) -> None:
    panel = _panel(session, prefs)
    assert panel.minimumSizeHint().width() <= 286


def test_the_background_tiles_keep_their_order_in_arabic(qt_app, session, prefs) -> None:
    from qurantext.gui import i18n

    i18n.set_language("ar")
    panel = _panel(session, prefs)
    panel.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    panel.resize(294, 900)
    panel.show()
    _spin_briefly(qt_app)
    xs = [panel.background_tiles[k].x() for k in ("solid", "gradient", "pattern_stars")]
    assert xs == sorted(xs)
    panel.close()


# -- the panel's sliders in a scroll area: wheel and lost grabs -------------------


def _wheel(widget, ticks: int, *, up: bool) -> list[bool]:
    """*ticks* notches of the mouse wheel over *widget*; whether each was taken.

    Up raises a slider, down lowers it. A real wheel event
    that a widget ignores goes on to its parents, the scroll area among them;
    Qt does not pass on one sent by hand, so the tests check it was ignored.
    """
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    pos = QPointF(widget.rect().center())
    taken = []
    for _ in range(ticks):
        event = QWheelEvent(
            pos,
            QPointF(widget.mapToGlobal(pos)),
            QPoint(0, 0),
            QPoint(0, 120 if up else -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(widget, event)
        taken.append(event.isAccepted())
    return taken


def _handle_centre(slider) -> QPoint:
    from PySide6.QtWidgets import QStyle, QStyleOptionSlider

    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    return (
        slider.style()
        .subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider
        )
        .center()
    )


def test_the_wheel_scrolls_past_the_sliders(qt_app, session, prefs, monkeypatch) -> None:
    """Scrolling the panel must not edit each control passing under the pointer."""
    from PySide6.QtWidgets import QFileDialog, QScrollArea

    from qurantext.core.looks import NIGHT_GOLD

    asked: list = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: asked.append(a) or ("", ""))
    panel = _panel(session, prefs)
    scroll = QScrollArea()
    scroll.setWidget(panel)
    scroll.setWidgetResizable(True)
    scroll.resize(260, 240)
    panel.customise_toggle.click()
    scroll.show()
    _spin_briefly(qt_app)

    taken = []
    for control in (panel.opacity_slider, panel.dim_slider, panel.blur_slider):
        taken += _wheel(control, 3, up=True)

    assert not any(taken), "every notch is left to the scroll area"
    assert session.look == NIGHT_GOLD and not session.can_undo
    assert not asked, "no file dialog nobody asked for"
    scroll.close()


def test_a_control_with_focus_still_takes_the_wheel(qt_app, session, prefs) -> None:
    panel = _panel(session, prefs)
    panel.show()
    _spin_briefly(qt_app)
    panel.dim_slider.setFocus(Qt.FocusReason.MouseFocusReason)
    qt_app.processEvents()
    assert panel.dim_slider.hasFocus()
    assert _wheel(panel.dim_slider, 1, up=True) == [True]
    assert session.look.background.dim > 0
    panel.close()


def _panel_beside_a_field(qt_app, session, prefs):
    from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

    container = QWidget()
    column = QVBoxLayout(container)
    panel = _panel(session, prefs)
    column.addWidget(panel)
    other = QLineEdit()
    column.addWidget(other)
    container.resize(260, 700)
    container.show()
    _spin_briefly(qt_app)
    return container, panel, other


def _press_and_drag(qt_app, slider, value: int) -> None:
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=_handle_centre(slider))
    assert slider.hasFocus() and slider.isSliderDown()
    slider.setValue(value)  # where the drag has taken it


def _assert_a_later_edit_is_its_own_undo_step(session) -> None:
    from qurantext.gui.review.session import CARD, WordRef

    session.retime(WordRef(CARD, 0, 1), end=4.5)
    assert session.undo()
    assert session.words()[1].end == pytest.approx(3.0), "the retime undoes alone"
    assert session.look.background.dim == pytest.approx(0.3), "the drag is still there"
    assert session.undo() and session.look.background.dim == 0.0
    assert not session.can_undo


def test_losing_focus_mid_slider_drag_closes_the_gesture(qt_app, session, prefs) -> None:
    """Like the word strip: a lost grab (focus moved, a modal box opened) ends the drag."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    container, panel, other = _panel_beside_a_field(qt_app, session, prefs)
    slider = panel.dim_slider
    _press_and_drag(qt_app, slider, 30)
    assert session.look.background.dim == pytest.approx(0.3)

    other.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
    qt_app.processEvents()
    assert not slider.hasFocus()
    assert not slider.isSliderDown()

    # The rest of that drag, should it still arrive, moves nothing.
    end = QPointF(slider.width() - 2, slider.height() / 2)
    move = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        end,
        QPointF(slider.mapToGlobal(end)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(slider, move)
    assert slider.value() == 30

    _assert_a_later_edit_is_its_own_undo_step(session)
    panel.refresh()  # as the window does after an undo
    assert slider.value() == 0, "the slider follows undo again"
    container.close()


def test_hiding_the_panel_mid_slider_drag_closes_the_gesture(qt_app, session, prefs) -> None:
    container, panel, _ = _panel_beside_a_field(qt_app, session, prefs)
    _press_and_drag(qt_app, panel.dim_slider, 30)
    panel.hide()
    assert not panel.dim_slider.isSliderDown()
    _assert_a_later_edit_is_its_own_undo_step(session)
    container.close()


def test_disabling_the_panel_mid_slider_drag_closes_the_gesture(qt_app, session, prefs) -> None:
    container, panel, _ = _panel_beside_a_field(qt_app, session, prefs)
    _press_and_drag(qt_app, panel.dim_slider, 30)
    panel.setEnabled(False)
    assert not panel.dim_slider.isSliderDown()
    _assert_a_later_edit_is_its_own_undo_step(session)
    container.close()


# -- the ayah picker -------------------------------------------------------------


@pytest.fixture
def db(store):
    """The word-level store the suite builds once per module (``conftest.store``)."""
    return store


def _card_text(db, surah, first, last) -> str:
    from contextlib import closing

    from qurantext.data.quran_db import ayah_range_card, connect

    with closing(connect(db)) as conn:
        return ayah_range_card(conn, surah, first, last)["full_text"]


def test_picker_defaults_and_preview(qt_app, db) -> None:
    from qurantext.gui.review.ayah_picker import AyahPicker

    picker = AyahPicker(surah=25, from_ayah=7, db_path=db)
    assert picker.choice() == (25, 7, 7)
    assert picker.preview.text() == _card_text(db, 25, 7, 7), "the preview is the card's text"
    assert picker.preview.text().strip().endswith("٧")
    assert picker.ok_button.isEnabled()


def test_to_follows_from_until_edited(qt_app, db) -> None:
    from qurantext.gui.review.ayah_picker import AyahPicker

    picker = AyahPicker(surah=25, from_ayah=7, db_path=db)
    picker.from_spin.setValue(9)
    assert picker.to_spin.value() == 9
    picker.to_spin.setValue(11)
    picker.from_spin.setValue(10)
    assert picker.choice() == (25, 10, 11)
    picker.from_spin.setValue(12)
    assert picker.to_spin.value() == 12  # never below from


def test_a_given_range_is_kept_when_from_moves(qt_app, db) -> None:
    """Opened on a card's 7–9, moving the first ayah must not collapse the range."""
    from qurantext.gui.review.ayah_picker import AyahPicker

    picker = AyahPicker(surah=25, from_ayah=7, to_ayah=9, db_path=db)
    picker.from_spin.setValue(8)
    assert picker.choice() == (25, 8, 9)


def test_changing_surah_clamps_the_ayah_spins(qt_app, db) -> None:
    from qurantext.gui.review.ayah_picker import AyahPicker

    picker = AyahPicker(surah=2, from_ayah=200, db_path=db)
    index = picker.surah_box.findData(103)  # Al-ʿAṣr: 3 ayat
    picker.surah_box.setCurrentIndex(index)
    assert picker.from_spin.maximum() == 3 and picker.choice()[1:] == (3, 3)
    assert picker.to_spin.maximum() == 3


def test_the_surah_box_lists_every_surah_by_name(qt_app, db) -> None:
    from qurantext.gui.review.ayah_picker import AyahPicker

    picker = AyahPicker(surah=25, db_path=db)
    assert picker.surah_box.count() == 114
    assert picker.surah_box.currentData() == 25
    assert "الفُرقَانِ" in picker.surah_box.currentText(), "named from the store"


def test_a_long_range_preview_is_shortened(qt_app, db) -> None:
    from qurantext.gui.i18n import tn
    from qurantext.gui.review.ayah_picker import AyahPicker

    picker = AyahPicker(surah=25, from_ayah=1, to_ayah=20, db_path=db)
    assert picker.preview.text().count("\n") <= 6
    assert picker.preview.text().endswith(tn("ayah_picker.more", 15))
    assert picker.preview.text().endswith("…and 15 more")


def test_the_preview_follows_the_spins(qt_app, db) -> None:
    from qurantext.gui.review.ayah_picker import AyahPicker

    picker = AyahPicker(surah=25, from_ayah=7, db_path=db)
    picker.from_spin.setValue(8)
    assert picker.preview.text() == _card_text(db, 25, 8, 8)
    picker.to_spin.setValue(10)
    assert picker.preview.text() == _card_text(db, 25, 8, 10)
    assert picker.preview.text().count("\n") == 2


def test_no_store_disables_ok(qt_app, tmp_path) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.ayah_picker import AyahPicker

    picker = AyahPicker(surah=25, db_path=tmp_path / "missing.sqlite")
    assert not picker.ok_button.isEnabled()
    assert picker.preview.text() == t("ayah_picker.no_store")


def test_a_damaged_store_disables_ok(qt_app, tmp_path) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.ayah_picker import AyahPicker

    broken = tmp_path / "quran.sqlite"
    broken.write_bytes(b"not a database at all")
    picker = AyahPicker(surah=25, db_path=broken)
    assert not picker.ok_button.isEnabled()
    assert picker.preview.text() == t("ayah_picker.no_store")


def test_a_hand_made_card_is_marked_in_the_segment_list(qt_app) -> None:
    from pathlib import Path

    from qurantext.gui.i18n import t
    from qurantext.gui.review.segment_list import MANUAL_MARK, SegmentList
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import Project

    detected = {
        "surah_num": 25,
        "from_ayah": 7,
        "to_ayah": 7,
        "full_text": "x",
        "start_time": 1.0,
        "end_time": 2.0,
    }
    manual = dict(detected, from_ayah=8, to_ayah=9, start_time=3.0, end_time=4.0, manual=True)
    project = Project(audio=Path("d.mp3"), mode="lecture", cards=[detected, manual])
    table = SegmentList(ReviewSession(project))
    assert table.item(0, 0).text() == "25:7" and not table.item(0, 0).toolTip()
    assert table.item(1, 0).text() == f"{MANUAL_MARK} 25:8-9"
    assert table.item(1, 0).toolTip() == t("segments.manual")


def test_only_a_lecture_cards_ayah_cell_asks_to_change_it(qt_app) -> None:
    from pathlib import Path

    from qurantext.gui.review.segment_list import SegmentList
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import CaptionCue, Project

    card = {"surah_num": 25, "from_ayah": 7, "to_ayah": 7, "start_time": 1.0, "end_time": 2.0}
    project = Project(
        audio=Path("d.mp3"),
        mode="lecture",
        cards=[card],
        captions=[CaptionCue(3.0, 4.0, "spoken", words=[])],
    )
    table = SegmentList(ReviewSession(project))
    asked = _recorded(table.card_ayah_requested)
    table.cellDoubleClicked.emit(0, 0)
    table.cellDoubleClicked.emit(0, 2)  # the card's text
    table.cellDoubleClicked.emit(1, 0)  # a caption
    assert asked == [(0,)]
    caption_cell = table.visualItemRect(table.item(1, 0)).center()
    assert table.context_menu_at(caption_cell) is None


def test_a_store_missing_a_surah_leaves_ok_off(qt_app, db, tmp_path) -> None:
    """Readable but incomplete: the preview could be drawn, yet no card is chosen from it."""
    import shutil
    import sqlite3

    from qurantext.gui.i18n import t
    from qurantext.gui.review.ayah_picker import AyahPicker

    partial = tmp_path / "partial.sqlite"
    shutil.copyfile(db, partial)
    conn = sqlite3.connect(partial)
    with conn:
        conn.execute("DELETE FROM surahs WHERE surah_num = 114")
    conn.close()
    picker = AyahPicker(surah=25, from_ayah=7, db_path=partial)
    assert not picker.ok_button.isEnabled()
    assert picker.preview.text() == t("ayah_picker.no_store")


def test_a_hand_made_card_leads_with_its_mark_in_arabic(qt_app) -> None:
    from pathlib import Path

    from qurantext.gui.i18n import set_language
    from qurantext.gui.review.segment_list import MANUAL_MARK, SegmentList
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import Project

    card = {"surah_num": 25, "from_ayah": 8, "to_ayah": 9, "start_time": 1.0, "end_time": 2.0}
    project = Project(audio=Path("d.mp3"), mode="lecture", cards=[dict(card, manual=True)])
    set_language("ar")
    table = SegmentList(ReviewSession(project))
    assert table.item(0, 0).text() == f"\u200f{MANUAL_MARK} 25:8-9"


# -- the Episode dialog ---------------------------------------------------------


@pytest.fixture
def episode_lecture(tmp_path, monkeypatch):
    """A saved lecture's session, 100 s long, with the app's data under tmp_path."""
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import CaptionCue, Project, load_project, save_project

    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("QURANTEXT_CACHE_DIR", str(tmp_path / "cache"))
    project = Project(
        audio=tmp_path / "dars.mp3",
        mode="lecture",
        captions=[CaptionCue(1.0, 2.0, "line")],
    )
    save_project(project, tmp_path / "dars.qalun.json")
    return ReviewSession(load_project(tmp_path / "dars.qalun.json"), duration=100.0)


def _fake_probe(monkeypatch, lengths: dict[str, float]) -> list:
    """``probe_part`` knows the clips named in *lengths*; any other is not a video."""
    from qurantext.gui.review import episode_dialog
    from qurantext.jobs.episode import EpisodeError, PartInfo

    probed: list = []

    def probe(path):
        probed.append(path.name)
        if path.name not in lengths:
            raise EpisodeError("episode.error.not_video", name=path.name)
        return PartInfo(path=path, duration=lengths[path.name], has_video=True, has_audio=True)

    monkeypatch.setattr(episode_dialog, "probe_part", probe)
    return probed


def _no_audio_length(monkeypatch) -> None:
    """ffprobe cannot read any recording: a part without a render has no known length."""
    from qurantext.gui.review import episode_dialog

    def unreadable(path):
        raise RuntimeError("no ffprobe here")

    monkeypatch.setattr(episode_dialog, "get_audio_duration", unreadable)


def _recitation_jobs(monkeypatch, tmp_path, lecture_path) -> dict:
    """Three recitation jobs (rendered, not rendered, damaged) and two lectures, listed."""
    from qurantext.gui.review import episode_dialog
    from qurantext.jobs.catalog import DAMAGED, NEEDS_REVIEW, RENDERED, JobEntry
    from qurantext.jobs.project import Project, save_project

    rendered = Project(audio=tmp_path / "fatiha.mp3", mode="recitation")
    rendered.record_render(tmp_path / "fatiha.mp4", preset="social", basmala_offset_s=0.0)
    (tmp_path / "fatiha.mp4").write_bytes(b"video")  # its render is there to reuse
    save_project(rendered, tmp_path / "fatiha.qalun.json")
    fresh = Project(audio=tmp_path / "furqan.mp3", mode="recitation")
    save_project(fresh, tmp_path / "furqan.qalun.json")
    paths = {
        "rendered": rendered.path,
        "fresh": fresh.path,
        "damaged": tmp_path / "broken.qalun.json",
    }
    entries = [
        JobEntry(paths["rendered"], "fatiha", "recitation", RENDERED, 3.0, 7, "1:1-7"),
        JobEntry(lecture_path, "dars", "lecture", RENDERED, 2.5),
        JobEntry(paths["fresh"], "furqan", "recitation", NEEDS_REVIEW, 2.0, 5, "25:7-11"),
        JobEntry(tmp_path / "other.qalun.json", "other", "lecture", NEEDS_REVIEW, 1.5),
        JobEntry(paths["damaged"], "broken", "recitation", DAMAGED, 1.0, error="bad json"),
    ]
    asked: list = []

    def list_jobs(dirs=None, **kwargs):
        asked.append(dirs)
        return entries

    monkeypatch.setattr(episode_dialog, "list_jobs", list_jobs)
    paths["asked"] = asked
    return paths


def _choose_file(monkeypatch, path) -> None:
    from qurantext.gui.review import episode_dialog

    monkeypatch.setattr(
        episode_dialog.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(path), "")),
    )


def _items(box) -> list[tuple[str, object, bool]]:
    model = box.model()
    return [
        (box.itemText(i), box.itemData(i), model.item(i).isEnabled()) for i in range(box.count())
    ]


def test_the_episode_dialog_starts_from_the_sessions_choice(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import EpisodeChoice

    jobs = _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"intro.mp4": 65.0, "fatiha.mp4": 30.0})
    intro = tmp_path / "dars.qalun.episode" / "intro.mp4"
    choice = EpisodeChoice(intro, jobs["rendered"], None, intro_name="Channel intro.mp4")
    episode_lecture.set_episode(choice)
    episode_lecture.save()

    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    assert jobs["asked"] == [[tmp_path]]
    assert dialog.ok_button.property("primary") is True and dialog.ok_button.isDefault()
    # By its original name: the copy beside the project is named by its content.
    assert dialog.intro_label.text() == t("episode.clip", name="Channel intro.mp4", length="01:05")
    assert dialog.intro_remove.isEnabled()
    assert dialog.outro_label.text() == t("episode.none")
    assert not dialog.outro_remove.isEnabled()
    assert dialog.recitation_box.currentData() == jobs["rendered"].resolve()
    assert dialog.choice() == EpisodeChoice(
        intro.resolve(), jobs["rendered"].resolve(), None, intro_name="Channel intro.mp4"
    )


def test_the_recitation_list_shows_each_jobs_state_and_hides_the_lecture(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import ltr, t
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    jobs = _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    entry = "episode.recitation_entry"
    assert _items(dialog.recitation_box) == [
        (t("episode.none"), None, True),
        (
            t(entry, name="fatiha", range=ltr("1:1-7"), status=t("episode.rendered")),
            jobs["rendered"],
            True,
        ),
        (
            t(entry, name="furqan", range=ltr("25:7-11"), status=t("episode.render_first")),
            jobs["fresh"],
            True,
        ),
        (
            t("episode.recitation_entry_no_range", name="broken", status=t("episode.damaged")),
            jobs["damaged"],
            False,
        ),
    ]
    assert dialog.recitation_box.currentIndex() == 0


def test_choosing_a_file_that_is_not_a_video_keeps_the_old_clip(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"intro.mp4": 4.0})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    _choose_file(monkeypatch, tmp_path / "intro.mp4")
    dialog.intro_choose.click()
    assert dialog.choice().intro == tmp_path / "intro.mp4"
    _choose_file(monkeypatch, tmp_path / "song.mp4")
    dialog.intro_choose.click()
    assert dialog.choice().intro == tmp_path / "intro.mp4", "the old clip is kept"
    assert dialog.intro_label.text() == t("episode.clip", name="intro.mp4", length="00:04")
    assert dialog.message_label.text() == t("episode.error.not_video", name="song.mp4")
    assert not dialog.message_label.isHidden()


def test_cancelling_the_file_picker_changes_nothing(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    probed = _fake_probe(monkeypatch, {})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    _choose_file(monkeypatch, "")
    dialog.outro_choose.click()
    assert dialog.choice().outro is None and probed == []


def test_remove_clears_the_clip(qt_app, episode_lecture, prefs, tmp_path, monkeypatch) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"end.mov": 3.0})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    _choose_file(monkeypatch, tmp_path / "end.mov")
    dialog.outro_choose.click()
    assert dialog.choice().outro == tmp_path / "end.mov" and dialog.outro_remove.isEnabled()
    dialog.outro_remove.click()
    assert dialog.choice().outro is None
    assert dialog.outro_label.text() == t("episode.none")
    assert not dialog.outro_remove.isEnabled()


def test_the_total_adds_the_known_lengths_and_marks_an_unknown_one(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    jobs = _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"intro.mp4": 20.0, "fatiha.mp4": 40.5})
    _no_audio_length(monkeypatch)
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    # The lecture alone: its recording's 100 s.
    assert dialog.total_label.text() == t("episode.total", length="01:40")
    _choose_file(monkeypatch, tmp_path / "intro.mp4")
    dialog.intro_choose.click()
    box = dialog.recitation_box
    box.setCurrentIndex(box.findData(jobs["rendered"]))
    # 20 + 40.5 (the recitation's rendered video) + 100.
    assert dialog.total_label.text() == t("episode.total", length="02:41")
    box.setCurrentIndex(box.findData(jobs["fresh"]))
    # Not rendered, and its recording cannot be read: its length is unknown.
    unknown = t("episode.unknown")
    assert dialog.total_label.text() == t("episode.total", length=f"02:00 + {unknown}")


def test_ok_copies_the_clip_sets_the_episode_and_keeps_it_as_the_default(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import episode_dir_for

    jobs = _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    source = tmp_path / "intro.mp4"
    source.write_bytes(b"an intro")
    _fake_probe(monkeypatch, {"intro.mp4": 5.0})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    _choose_file(monkeypatch, source)
    dialog.intro_choose.click()
    box = dialog.recitation_box
    box.setCurrentIndex(box.findData(jobs["fresh"]))
    dialog.ok_button.click()

    assert dialog.result() == dialog.DialogCode.Accepted
    choice = episode_lecture.episode
    assert choice.intro.parent == episode_dir_for(episode_lecture.project.path).resolve()
    assert choice.intro.read_bytes() == b"an intro"
    assert choice.recitation == jobs["fresh"].resolve() and choice.outro is None
    assert choice.intro_name == "intro.mp4", "the original name is kept beside the copy"
    assert dialog.choice() == choice, "after OK the dialog names what was stored"
    assert prefs.default_episode_names == ("intro.mp4", None)
    assert episode_lecture.dirty and episode_lecture.undo(), "one undo step"
    assert episode_lecture.episode.is_empty and not episode_lecture.can_undo
    intro, outro = prefs.default_episode
    assert intro.read_bytes() == b"an intro" and outro is None
    assert intro.parent == (tmp_path / "data" / "episode").resolve()


def test_a_clip_that_cannot_be_copied_keeps_the_dialog_open(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review import episode_dialog
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"intro.mp4": 5.0})

    def full_disk(project_path, source):
        raise OSError("No space left on device")

    monkeypatch.setattr(episode_dialog, "import_episode_clip", full_disk)
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    _choose_file(monkeypatch, tmp_path / "intro.mp4")
    dialog.intro_choose.click()
    dialog.ok_button.click()
    assert dialog.result() != dialog.DialogCode.Accepted
    assert dialog.message_label.text() == t("episode.copy_failed", reason="No space left on device")
    assert episode_lecture.episode.is_empty and not episode_lecture.can_undo
    assert prefs.default_episode == (None, None)


def test_a_default_that_cannot_be_kept_still_sets_the_episode(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    source = tmp_path / "intro.mp4"
    source.write_bytes(b"an intro")
    _fake_probe(monkeypatch, {"intro.mp4": 5.0})

    def refused(intro, outro, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(prefs, "save_default_episode", refused)
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    _choose_file(monkeypatch, source)
    dialog.intro_choose.click()
    dialog.ok_button.click()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert episode_lecture.episode.intro_name == "intro.mp4"
    assert dialog.default_error == t("episode.default_failed", reason="read-only")


def test_cancel_changes_nothing(qt_app, episode_lecture, prefs, tmp_path, monkeypatch) -> None:
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    jobs = _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    source = tmp_path / "intro.mp4"
    source.write_bytes(b"an intro")
    _fake_probe(monkeypatch, {"intro.mp4": 5.0})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    _choose_file(monkeypatch, source)
    dialog.intro_choose.click()
    box = dialog.recitation_box
    box.setCurrentIndex(box.findData(jobs["rendered"]))
    dialog.reject()
    assert episode_lecture.episode.is_empty and not episode_lecture.can_undo
    assert not (tmp_path / "dars.qalun.episode").exists(), "nothing was copied"
    assert prefs.default_episode == (None, None)


def test_the_episode_dialog_reads_in_arabic(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import set_language, t
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    set_language("ar")
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    assert dialog.intro_choose.text() == "اختر…"
    assert dialog.total_label.text() == t("episode.total", length="\u206601:40\u2069")


def test_a_chosen_recitation_no_longer_listed_is_kept(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import EpisodeChoice
    from qurantext.jobs.project import Project, save_project

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    hidden = Project(audio=elsewhere / "ikhlas.mp3", mode="recitation")
    save_project(hidden, elsewhere / "ikhlas.qalun.json")
    episode_lecture.set_episode(EpisodeChoice(None, hidden.path, None))
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    box = dialog.recitation_box
    assert box.currentData() == hidden.path.resolve()
    assert box.currentText() == t(
        "episode.recitation_entry_no_range", name="ikhlas", status=t("episode.render_first")
    )
    dialog.ok_button.click()
    assert episode_lecture.episode.recitation == hidden.path.resolve()


def test_a_seeded_clip_without_its_name_is_called_by_its_part(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    """Never by the content hash its copy beside the project is named by."""
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import EpisodeChoice

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"5e16d067e52c.mp4": 12.0, "outro.mov": 3.0})
    copy = tmp_path / "dars.qalun.episode" / "5e16d067e52c.mp4"
    elsewhere = tmp_path / "outro.mov"
    episode_lecture.set_episode(EpisodeChoice(copy, None, elsewhere))
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    part = t("episode.part.intro")
    assert dialog.intro_label.text() == t("episode.clip", name=part, length="00:12")
    assert dialog.outro_label.text() == t("episode.clip", name="outro.mov", length="00:03")


def test_a_seeded_lecture_shows_the_default_s_own_name(
    qt_app, prefs, tmp_path, monkeypatch
) -> None:
    """Default chosen from "Channel intro 2024.mp4"; a new lecture seeded from it says so."""
    from qurantext.gui.i18n import t
    from qurantext.gui.jobs import JobSpec, run_matching
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import CaptionCue, Project

    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("QURANTEXT_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "Channel intro 2024.mp4"
    source.write_bytes(b"an intro")
    prefs.save_default_episode(source, None)
    assert prefs.default_episode_names == ("Channel intro 2024.mp4", None)

    from qurantext.gui import jobs as jobs_module

    def matched(**kwargs):
        kwargs["output"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output"].write_text('{"matches": [], "meta": {"mode": "lecture"}}')

    monkeypatch.setattr(jobs_module, "run_detection", matched)
    monkeypatch.setattr(
        jobs_module.Project,
        "from_match_file",
        classmethod(
            lambda cls, path, audio, mode: Project(
                audio=audio, mode=mode, matches=path, captions=[CaptionCue(1.0, 2.0, "x")]
            )
        ),
    )
    audio = tmp_path / "dars.mp3"
    audio.write_bytes(b"")
    quran = tmp_path / "q.txt"
    quran.write_text("x")
    intro, outro = prefs.default_episode
    spec = JobSpec(
        audio=audio,
        quran=quran,
        mode="lecture",
        output_dir=tmp_path / "jobs",
        episode_defaults=(str(intro), None),
        episode_default_names=prefs.default_episode_names,
    )
    project = run_matching(spec)
    _recitation_jobs(monkeypatch, tmp_path, project.path)
    _fake_probe(monkeypatch, {intro.name: 7.0})
    dialog = EpisodeDialog(ReviewSession(project, duration=60.0), prefs=prefs, job_dirs=[])
    assert dialog.intro_label.text() == t(
        "episode.clip", name="Channel intro 2024.mp4", length="00:07"
    )


def test_ok_changes_only_the_default_of_a_part_changed_here(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    """An old lecture without an intro: setting its recitation keeps the channel's intro."""
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    jobs = _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    channel = tmp_path / "channel.mp4"
    channel.write_bytes(b"the channel's intro")
    prefs.save_default_episode(channel, None)
    before = (prefs.default_episode, prefs.default_episode_names)

    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    box = dialog.recitation_box
    box.setCurrentIndex(box.findData(jobs["fresh"]))
    dialog.ok_button.click()
    assert episode_lecture.episode.recitation == jobs["fresh"].resolve()
    assert (prefs.default_episode, prefs.default_episode_names) == before


def test_removing_a_clip_clears_its_default_and_keeps_the_other(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import EpisodeChoice, import_episode_clip

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    intro, outro = tmp_path / "in.mp4", tmp_path / "out.mp4"
    intro.write_bytes(b"intro")
    outro.write_bytes(b"outro")
    prefs.save_default_episode(intro, outro)
    kept_outro = prefs.default_episode[1]
    copy = import_episode_clip(episode_lecture.project.path, intro)
    episode_lecture.set_episode(EpisodeChoice(copy, None, None, intro_name="in.mp4"))
    _fake_probe(monkeypatch, {copy.name: 2.0})

    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    dialog.intro_remove.click()
    dialog.ok_button.click()
    assert episode_lecture.episode.is_empty
    assert prefs.default_episode == (None, kept_outro)
    assert prefs.default_episode_names == (None, "out.mp4")


def test_a_clip_that_is_gone_is_said_on_opening(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import EpisodeChoice

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"end.mov": 3.0})
    gone = tmp_path / "dars.qalun.episode" / "abc.mp4"
    episode_lecture.set_episode(EpisodeChoice(gone, None, None, intro_name="Intro.mp4"))
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    said = t("episode.clip_missing", part=t("episode.part.intro"))
    assert dialog.message_label.text() == said and not dialog.message_label.isHidden()
    end = tmp_path / "end.mov"
    _choose_file(monkeypatch, end)
    dialog.intro_choose.click()  # another intro: the line goes
    assert dialog.message_label.isHidden()


def test_a_recitation_whose_video_is_gone_will_be_rendered_first(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    """The job list calls it rendered; the episode would render it first all the same."""
    from qurantext.gui.i18n import ltr, t
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    jobs = _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    (tmp_path / "fatiha.mp4").unlink()
    _fake_probe(monkeypatch, {})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    box = dialog.recitation_box
    assert box.itemText(box.findData(jobs["rendered"])) == t(
        "episode.recitation_entry",
        name="fatiha",
        range=ltr("1:1-7"),
        status=t("episode.render_first"),
    )


def test_an_unreadable_recitation_job_is_listed_as_damaged(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    """Read by the real ``list_jobs``: a broken file has no mode, only its name says it."""
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    _fake_probe(monkeypatch, {})
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "fatiha_recitation.qalun.json").write_text("{not json")
    (jobs / "notes_lecture.qalun.json").write_text("{not json")
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[jobs])
    assert _items(dialog.recitation_box)[1:] == [
        (
            t(
                "episode.recitation_entry_no_range",
                name="fatiha_recitation",
                status=t("episode.damaged"),
            ),
            jobs / "fatiha_recitation.qalun.json",
            False,
        )
    ]


def test_an_arabic_job_name_keeps_its_ayat_in_order(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    """«الفرقان44-49 · 25:44-49 · …»: the name is isolated, the range runs left to right."""
    from qurantext.gui.review import episode_dialog
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.catalog import NEEDS_REVIEW, JobEntry

    _fake_probe(monkeypatch, {})
    entry = JobEntry(
        tmp_path / "x.qalun.json", "دروس الفرقان", "recitation", NEEDS_REVIEW, 1.0, 5, "25:7-11"
    )
    monkeypatch.setattr(episode_dialog, "list_jobs", lambda *a, **k: [entry])
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    text = dialog.recitation_box.itemText(1)
    assert text.startswith("\u2068دروس الفرقان\u2069 · ")
    assert "\u206625:7-11\u2069" not in text, "English: the range is not wrapped"
    assert "25:7-11" in text
    from qurantext.gui.i18n import set_language

    set_language("ar")
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    text = dialog.recitation_box.itemText(1)
    assert "\u2068دروس الفرقان\u2069" in text and "\u206625:7-11\u2069" in text


def test_choosing_a_clip_for_a_generated_part_makes_it_my_clip(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    """A clip chosen for a generated intro replaces it; the outro left alone stays generated."""
    from qurantext.gui.prefs import KEEP_DEFAULT
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import EpisodeChoice, GeneratedIntro, GeneratedOutro

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"intro.mp4": 4.0})
    (tmp_path / "intro.mp4").write_bytes(b"intro")
    intro, outro = GeneratedIntro(name="دروس"), GeneratedOutro(link="example.org")
    episode_lecture.set_episode(EpisodeChoice(intro_generated=intro, outro_generated=outro))
    prefs.save_default_episode(
        KEEP_DEFAULT, KEEP_DEFAULT, intro_generated=intro, outro_generated=outro
    )

    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    assert dialog.intro_kind.currentData() == "generated"
    _choose_file(monkeypatch, tmp_path / "intro.mp4")
    dialog.intro_choose.click()
    assert dialog.intro_kind.currentData() == "clip"
    dialog.ok_button.click()

    episode = episode_lecture.episode
    assert episode.intro is not None and episode.intro_generated is None
    assert episode.outro_generated == outro, "the outro was not touched"
    # The defaults the same: the intro's is now the clip, the outro's still generated.
    assert prefs.default_episode_kinds == ("clip", "generated")
    assert prefs.default_outro_generated == outro and prefs.default_intro_generated is None


# -- the Episode dialog: generated parts ----------------------------------------


def _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch, *, intro=None, outro=None):
    """The dialog over a lecture whose intro and outro are generated (*intro*, *outro*)."""
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import EpisodeChoice, GeneratedIntro, GeneratedOutro

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"intro.mp4": 4.0})
    intro = intro or GeneratedIntro(name="دروس الشيخ")
    outro = outro or GeneratedOutro(link="example.org/dars", platform="youtube")
    episode_lecture.set_episode(EpisodeChoice(intro_generated=intro, outro_generated=outro))
    episode_lecture.save()
    return EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])


def _shown(widget) -> bool:
    return not widget.isHidden()


def test_each_kind_shows_only_its_own_fields(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    for part in ("intro", "outro"):
        kind = getattr(dialog, f"{part}_kind")
        assert [kind.itemText(i) for i in range(kind.count())] == [
            t("episode.kind.none"),
            t("episode.kind.clip"),
            t("episode.kind.generated"),
        ]
        assert kind.currentData() == "none"
        clip, fields = getattr(dialog, f"{part}_choose"), getattr(dialog, f"{part}_fields")
        assert not _shown(clip) and not _shown(fields)
        kind.setCurrentIndex(kind.findData("clip"))
        assert _shown(clip) and _shown(getattr(dialog, f"{part}_label")) and not _shown(fields)
        kind.setCurrentIndex(kind.findData("generated"))
        assert not _shown(clip) and _shown(fields)
        kind.setCurrentIndex(kind.findData("none"))
        assert not _shown(clip) and not _shown(fields)
    dialog.outro_kind.setCurrentIndex(dialog.outro_kind.findData("generated"))
    # The custom phrase shows only for "Custom…".
    assert not _shown(dialog.outro_phrase_custom)
    dialog.outro_phrase.setCurrentIndex(dialog.outro_phrase.count() - 1)
    assert dialog.outro_phrase.currentText() == t("episode.gen.custom")
    assert _shown(dialog.outro_phrase_custom)
    assert (dialog.intro_seconds.minimum(), dialog.intro_seconds.maximum()) == (3, 10)
    assert (dialog.intro_seconds.value(), dialog.outro_seconds.value()) == (5, 6)


def test_the_strip_has_four_cards_in_render_order_and_the_lecture_is_fixed(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    assert list(dialog.cards) == ["intro", "recitation", "lecture", "outro"]
    assert dialog.cards["lecture"].title_label.text() == t("episode.lecture")
    lecture_controls = dialog.cards["lecture"].controls
    # No control on the Lecture card: only room that keeps its picture level with the others.
    assert all(
        lecture_controls.itemAt(i).spacerItem() is not None for i in range(lecture_controls.count())
    )
    assert dialog.cards["lecture"].focusPolicy() == Qt.FocusPolicy.NoFocus
    assert dialog.cards["intro"].controls.count() >= 1  # the kind box
    assert dialog.intro_kind.parent() is dialog.cards["intro"]
    assert dialog.recitation_box.parent() is dialog.cards["recitation"]
    dialog.show()
    _spin_briefly(qt_app)
    xs = [dialog.cards[p].x() for p in ("intro", "recitation", "lecture", "outro")]
    assert xs == sorted(xs)
    dialog.close()


def test_the_strip_mirrors_in_arabic(qt_app, episode_lecture, prefs, tmp_path, monkeypatch) -> None:
    from qurantext.gui import i18n
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    i18n.set_language("ar")
    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    dialog.show()
    _spin_briefly(qt_app)
    xs = [dialog.cards[p].x() for p in ("intro", "recitation", "lecture", "outro")]
    assert xs == sorted(xs, reverse=True)
    dialog.close()


def test_selection_starts_on_the_first_generated_part_else_intro(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import EpisodeChoice, GeneratedOutro

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    assert dialog.selected_part() == "intro" and dialog.cards["intro"].selected
    assert dialog.detail_pane.isHidden(), "nothing generated: no fields to show"
    episode_lecture.set_episode(EpisodeChoice(outro_generated=GeneratedOutro(link="example.org")))
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    assert dialog.selected_part() == "outro"
    assert not dialog.detail_pane.isHidden() and _shown(dialog.outro_fields)
    assert dialog.intro_fields.isHidden()


def test_switching_a_part_to_generated_selects_it_and_shows_its_fields(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
    assert dialog.selected_part() == "intro" and _shown(dialog.intro_fields)
    assert dialog.outro_fields.isHidden(), "one part's fields at a time"
    dialog.outro_kind.setCurrentIndex(dialog.outro_kind.findData("none"))
    dialog.outro_kind.setCurrentIndex(dialog.outro_kind.findData("generated"))
    assert dialog.selected_part() == "outro"
    assert _shown(dialog.outro_fields) and dialog.intro_fields.isHidden()
    dialog.select_part("intro")
    assert _shown(dialog.intro_fields) and dialog.outro_fields.isHidden()
    assert dialog.cards["intro"].selected and not dialog.cards["outro"].selected
    dialog.intro_kind.setCurrentIndex(dialog.intro_kind.findData("none"))
    assert dialog.detail_pane.isHidden() and dialog.selected_part() == "intro"
    dialog.cards["outro"].click()
    assert dialog.selected_part() == "outro" and _shown(dialog.outro_fields)
    dialog.select_part("lecture")
    assert dialog.selected_part() == "outro", "the lecture is never selected"


def test_the_tracked_link_follows_the_link_and_the_platform_live(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from urllib.parse import parse_qs, urlsplit

    dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
    tracked = dialog.outro_tracked
    assert tracked.isReadOnly()
    query = parse_qs(urlsplit(tracked.text()).query)
    assert tracked.text().startswith("https://example.org/dars?")
    assert query["utm_source"] == ["youtube"] and query["utm_campaign"] == ["qalun-lecture"]
    assert query["utm_medium"] == ["video"] and query["utm_content"] == ["outro-qr"]
    dialog.outro_platform.setCurrentIndex(dialog.outro_platform.findData("telegram"))
    assert parse_qs(urlsplit(tracked.text()).query)["utm_source"] == ["telegram"]
    dialog.outro_link.setText("example.org/other?ref=desc&utm_campaign=ramadan#top")
    url = urlsplit(tracked.text())
    assert url.path == "/other" and url.fragment == "top"
    assert parse_qs(url.query)["utm_campaign"] == ["ramadan"]
    assert parse_qs(url.query)["ref"] == ["desc"]
    assert "example.org/other" in dialog.outro_readable.text()
    assert "utm_" not in dialog.outro_readable.text(), "the readable text has no tracking"


def test_the_tracked_link_names_the_lectures_surah_and_ayat(
    qt_app, tmp_path, prefs, monkeypatch
) -> None:
    """The same campaign the render puts in the QR code (outro_spec_for)."""
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.episode_assets import EpisodeChoice, GeneratedOutro
    from qurantext.jobs.generated_parts import outro_spec_for
    from qurantext.jobs.project import CaptionCue, Project, save_project

    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    card = {
        "surah_num": 25,
        "surah_name": "الفرقان",
        "full_text": "وَقَالُواْ",
        "confidence": 0.9,
    }
    project = Project(
        audio=tmp_path / "dars.mp3",
        mode="lecture",
        captions=[CaptionCue(1.0, 2.0, "line")],
        cards=[
            dict(card, from_ayah=44, to_ayah=44, start_time=1.0, end_time=4.0),
            dict(card, from_ayah=49, to_ayah=49, start_time=10.0, end_time=14.0),
        ],
    )
    save_project(project, tmp_path / "dars.qalun.json")
    session = ReviewSession(project, duration=60.0)
    outro = GeneratedOutro(link="example.org/dars", platform="instagram")
    session.set_episode(EpisodeChoice(outro_generated=outro))
    _recitation_jobs(monkeypatch, tmp_path, project.path)
    _fake_probe(monkeypatch, {})
    dialog = EpisodeDialog(session, prefs=prefs, job_dirs=[tmp_path])
    assert "utm_campaign=qalun-025-044-049" in dialog.outro_tracked.text()
    assert dialog.outro_tracked.text() == outro_spec_for(project, outro, {}).qr_url


@pytest.mark.parametrize(
    ("link", "key"),
    [
        ("ftp://example.org/x", "episode.link_invalid"),
        ("example.org/a b", "episode.link_invalid.spaces"),
        ("https:/example.org", "episode.link_invalid.slashes"),
        ("https://me:secret@example.org", "episode.link_invalid.userinfo"),
        ("https://exa_mple", "episode.link_invalid.host"),
        ("https://example.org:99999", "episode.link_invalid.port"),
    ],
)
def test_an_invalid_link_says_why_and_disables_ok(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch, link, key
) -> None:
    from qurantext.gui.i18n import t

    dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
    assert dialog.ok_button.isEnabled()
    dialog.outro_link.setText(link)
    assert not dialog.ok_button.isEnabled()
    assert dialog.outro_warning.text() == t(key) and _shown(dialog.outro_warning)
    assert dialog.outro_tracked.text() == "" and not dialog.outro_copy.isEnabled()
    dialog.flush_previews()  # the preview shows the phrase alone meanwhile
    assert not dialog.outro_preview.pixmap().isNull()
    # Not used while the outro is not generated.
    dialog.outro_kind.setCurrentIndex(dialog.outro_kind.findData("none"))
    assert dialog.ok_button.isEnabled()
    dialog.outro_kind.setCurrentIndex(dialog.outro_kind.findData("generated"))
    assert not dialog.ok_button.isEnabled()
    # An empty link is valid: no QR code.
    dialog.outro_link.setText("")
    assert dialog.ok_button.isEnabled() and not _shown(dialog.outro_warning)
    assert dialog.outro_tracked.text() == "" and not dialog.outro_copy.isEnabled()


def test_copy_gives_the_qr_link_counted_as_the_descriptions(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    """Description clicks and QR scans are measured apart: only utm_content differs."""
    from urllib.parse import parse_qsl, urlsplit

    from PySide6.QtGui import QGuiApplication

    dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
    QGuiApplication.clipboard().setText("")
    dialog.outro_copy.click()
    text = QGuiApplication.clipboard().text()
    qr = dialog.outro_tracked.text()
    copied, shown = urlsplit(text), urlsplit(qr)
    copied_query, qr_query = dict(parse_qsl(copied.query)), dict(parse_qsl(shown.query))
    assert qr_query["utm_content"] == "outro-qr", "the field shows what the QR code opens"
    assert copied_query.pop("utm_content") == "description"
    qr_query.pop("utm_content")
    assert copied_query == qr_query and copied_query["utm_source"] == "youtube"
    assert copied._replace(query="") == shown._replace(query="")
    assert "\u2066" not in text and "\u2069" not in text
    # The same link the render would put in a description, from the same builder.
    from qurantext.jobs.generated_parts import tracked_link_for

    settings = episode_lecture.episode.outro_generated
    assert text == tracked_link_for(episode_lecture.project, settings, {}, content="description")


def test_previews_render_and_wait_for_typing_to_rest(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.review import episode_dialog

    dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
    intro, outro = dialog.intro_preview.pixmap(), dialog.outro_preview.pixmap()
    assert not intro.isNull() and not outro.isNull()
    # The lecture renders at its preset's size (portrait social): an upright preview.
    assert intro.height() > intro.width()
    assert max(intro.width(), intro.height()) <= max(episode_dialog.PREVIEW_BOX)
    before = intro.toImage()
    drawn = []
    real = episode_dialog.render_title_frame

    def counted(*args, **kwargs):
        drawn.append(args[0])
        return real(*args, **kwargs)

    monkeypatch.setattr(episode_dialog, "render_title_frame", counted)
    dialog.intro_style.setCurrentIndex(dialog.intro_style.findData("reveal"))
    dialog.intro_name_edit.setText("دروس الشيخ أحمد")
    assert drawn == [] and dialog._preview_timer.isActive(), "drawn once typing rests"
    assert dialog._preview_timer.interval() == 300
    dialog.flush_previews()
    assert [type(spec).__name__ for spec in drawn] == ["IntroSpec", "OutroSpec"]
    assert drawn[0].style == "reveal" and drawn[0].name == "دروس الشيخ أحمد"
    assert dialog.intro_preview.pixmap().toImage() != before


def test_a_link_too_long_for_a_qr_code_and_letters_the_font_lacks_are_warned(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.jobs.project import JobSettings, set_job_settings

    # Never rendered: the job's preset says the size (fast, 960×540).
    set_job_settings(episode_lecture.project, JobSettings(preset="fast"))
    dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
    assert not _shown(dialog.outro_warning) and not _shown(dialog.intro_warning)
    dialog.outro_link.setText("example.org/" + "a" * 400)
    dialog.flush_previews()
    assert dialog.ok_button.isEnabled(), "a warning: the lecture's size may change first"
    assert dialog.outro_warning.text() == t("episode.gen.qr_too_big", size="960×540")
    # Rendered at 1920×1080 before: the next render is the preset's size still,
    # and the episode's parts are made at the size just rendered (probe S4).
    episode_lecture.project.record_render(
        tmp_path / "dars.mp4", preset="high", basmala_offset_s=0.0, width=1920, height=1080
    )
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    assert dialog._size == (960, 540)
    dialog.outro_link.setText("example.org/" + "a" * 400)
    dialog.flush_previews()
    assert dialog.outro_warning.text() == t("episode.gen.qr_too_big", size="960×540")
    # Re-run with "high": 1920×1080, where the link fits.
    set_job_settings(episode_lecture.project, JobSettings(preset="high"))
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    dialog.outro_link.setText("example.org/" + "a" * 400)
    dialog.flush_previews()
    assert not _shown(dialog.outro_warning)
    assert dialog.outro_preview.pixmap().width() > dialog.outro_preview.pixmap().height()
    dialog.intro_name_edit.setText("Привет")
    assert dialog.intro_warning.text() == t("episode.gen.missing_glyphs", chars="Привет")
    dialog.outro_phrase.setCurrentIndex(dialog.outro_phrase.count() - 1)
    dialog.outro_phrase_custom.setText("Спасибо")
    assert t("episode.gen.missing_glyphs", chars="Спасибо") in dialog.outro_warning.text()


def test_ok_keeps_the_generated_settings_as_one_undo_step(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.review.episode_dialog import PHRASES, EpisodeDialog
    from qurantext.jobs.episode_assets import GeneratedIntro, GeneratedOutro

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    dialog.intro_kind.setCurrentIndex(dialog.intro_kind.findData("generated"))
    dialog.intro_name_edit.setText("  دروس الشيخ ")
    dialog.intro_style.setCurrentIndex(dialog.intro_style.findData("rise"))
    dialog.intro_seconds.setValue(7)
    dialog.outro_kind.setCurrentIndex(dialog.outro_kind.findData("generated"))
    dialog.outro_phrase.setCurrentIndex(dialog.outro_phrase.findData(PHRASES[1]))
    dialog.outro_link.setText("example.org/dars")
    dialog.outro_platform.setCurrentIndex(dialog.outro_platform.findData("tiktok"))
    dialog.outro_style.setCurrentIndex(dialog.outro_style.findData("reveal"))
    dialog.outro_seconds.setValue(8)
    intro = GeneratedIntro(name="دروس الشيخ", style="rise", seconds=7.0)
    outro = GeneratedOutro(
        phrase=PHRASES[1], link="example.org/dars", platform="tiktok", style="reveal", seconds=8.0
    )
    assert dialog.choice().intro_generated == intro
    assert dialog.choice().outro_generated == outro
    dialog.ok_button.click()

    assert dialog.result() == dialog.DialogCode.Accepted
    episode = episode_lecture.episode
    assert (episode.intro_generated, episode.outro_generated) == (intro, outro)
    assert episode.intro is None and episode.outro is None
    assert dialog.choice() == episode
    assert prefs.default_episode_kinds == ("generated", "generated")
    assert (prefs.default_intro_generated, prefs.default_outro_generated) == (intro, outro)
    assert episode_lecture.undo(), "one undo step"
    assert episode_lecture.episode.is_empty and not episode_lecture.can_undo


def test_changing_only_the_outros_platform_keeps_only_that_field_as_default(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    """Field by field: this lecture's link does not replace the default's (review I1)."""
    from qurantext.gui.prefs import KEEP_DEFAULT
    from qurantext.jobs.episode_assets import GeneratedIntro, GeneratedOutro

    channel = tmp_path / "channel.mp4"
    channel.write_bytes(b"the channel's intro")
    prefs.save_default_episode(
        channel, KEEP_DEFAULT, outro_generated=GeneratedOutro(link="example.org")
    )
    before_intro = (prefs.default_episode[0], prefs.default_episode_names[0])
    dialog = _generated_dialog(
        episode_lecture,
        prefs,
        tmp_path,
        monkeypatch,
        intro=GeneratedIntro(name="درس"),
        outro=GeneratedOutro(link="example.org/dars", platform="youtube"),
    )
    dialog.outro_platform.setCurrentIndex(dialog.outro_platform.findData("whatsapp"))
    dialog.ok_button.click()
    assert episode_lecture.episode.outro_generated == GeneratedOutro(
        link="example.org/dars", platform="whatsapp"
    ), "the lecture keeps its own link"
    assert episode_lecture.episode.intro_generated == GeneratedIntro(name="درس")
    assert prefs.default_episode_kinds == ("clip", "generated")
    assert (prefs.default_episode[0], prefs.default_episode_names[0]) == before_intro
    assert prefs.default_outro_generated == GeneratedOutro(
        link="example.org", platform="whatsapp"
    ), "the default keeps its link and takes only the platform"


def test_an_old_lecture_re_exported_keeps_the_channels_new_defaults(
    qt_app, tmp_path, monkeypatch
) -> None:
    """Probe S1: the site moved; re-exporting an old lecture for Instagram keeps the new one."""
    from PySide6.QtCore import QSettings

    from qurantext.gui.prefs import KEEP_DEFAULT, Prefs
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import EpisodeChoice, GeneratedIntro, GeneratedOutro

    session, folder = _probe_lecture(tmp_path, monkeypatch)
    prefs = Prefs(QSettings(str(folder / "prefs.ini"), QSettings.Format.IniFormat))
    prefs.save_default_episode(
        KEEP_DEFAULT,
        KEEP_DEFAULT,
        outro_generated=GeneratedOutro(phrase="بارك الله فيكم", link="example.org/new-site"),
        intro_generated=GeneratedIntro(name="القناة الجديدة"),
    )
    session.set_episode(
        EpisodeChoice(
            intro_generated=GeneratedIntro(name="الاسم القديم"),
            outro_generated=GeneratedOutro(link="example.org/old-site"),
        )
    )
    dialog = EpisodeDialog(session, prefs=prefs, job_dirs=[folder])
    dialog.outro_platform.setCurrentIndex(dialog.outro_platform.findData("instagram"))
    dialog.intro_style.setCurrentIndex(dialog.intro_style.findData("rise"))
    dialog.ok_button.click()
    assert prefs.default_outro_generated == GeneratedOutro(
        phrase="بارك الله فيكم", link="example.org/new-site", platform="instagram"
    )
    assert prefs.default_intro_generated == GeneratedIntro(name="القناة الجديدة", style="rise")
    assert session.episode.outro_generated.link == "example.org/old-site"
    assert session.episode.intro_generated == GeneratedIntro(name="الاسم القديم", style="rise")


def _probe_lecture(tmp_path, monkeypatch, cards=None):
    """A saved lecture's session in its own folder, the job list empty (the review's probes)."""
    from qurantext.gui.review import episode_dialog
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import CaptionCue, Project, load_project, save_project

    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(episode_dialog, "list_jobs", lambda *a, **k: [])
    folder = tmp_path / "probe"
    folder.mkdir(exist_ok=True)
    project = Project(
        audio=folder / "dars.mp3",
        mode="lecture",
        captions=[CaptionCue(1.0, 2.0, "line")],
        cards=cards or [],
    )
    save_project(project, folder / "dars.qalun.json")
    return ReviewSession(load_project(folder / "dars.qalun.json"), duration=100.0), folder


def test_a_part_set_to_none_keeps_its_remembered_settings(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    """Probe S2 (review M2): None changes the default's kind, not its name, phrase or link."""
    from qurantext.gui.prefs import KEEP_DEFAULT
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import GeneratedOutro

    remembered = GeneratedOutro(link="example.org/dars", platform="telegram")
    prefs.save_default_episode(KEEP_DEFAULT, KEEP_DEFAULT, outro_generated=remembered)
    dialog = _generated_dialog(
        episode_lecture, prefs, tmp_path, monkeypatch, outro=GeneratedOutro(link="example.org/dars")
    )
    dialog.outro_kind.setCurrentIndex(dialog.outro_kind.findData("none"))
    dialog.ok_button.click()
    # M9: OK after Generated → None: none in the session, none as the default's kind.
    assert episode_lecture.episode.outro_generated is None
    assert episode_lecture.episode.outro is None
    assert prefs.default_episode_kinds[1] == "none" and prefs.default_outro_generated is None
    assert prefs.remembered_outro_generated == remembered
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    dialog.outro_kind.setCurrentIndex(dialog.outro_kind.findData("generated"))
    assert dialog.outro_link.text() == "example.org/dars"
    assert dialog.outro_platform.currentData() == "telegram"
    # Generated again without touching a field: the remembered settings, as the default.
    dialog.ok_button.click()
    assert prefs.default_episode_kinds[1] == "generated"
    assert prefs.default_outro_generated == remembered


def test_a_generated_part_with_nothing_to_show_is_refused(
    qt_app, tmp_path, prefs, monkeypatch
) -> None:
    """Probe S3 (review M3): no words and no link would fail after the lecture's render."""
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    session, folder = _probe_lecture(tmp_path, monkeypatch)
    dialog = EpisodeDialog(session, prefs=prefs, job_dirs=[folder])
    dialog.outro_kind.setCurrentIndex(dialog.outro_kind.findData("generated"))
    dialog.outro_phrase.setCurrentIndex(dialog.outro_phrase.count() - 1)  # Custom…, empty
    assert not dialog.ok_button.isEnabled()
    assert dialog.outro_warning.text() == t("episode.gen.empty_outro")
    dialog.outro_link.setText("example.org")
    assert dialog.ok_button.isEnabled() and not _shown(dialog.outro_warning)
    dialog.intro_kind.setCurrentIndex(dialog.intro_kind.findData("generated"))
    assert dialog.intro_title.text() == "—", "no card names a surah"
    assert not dialog.ok_button.isEnabled()
    assert dialog.intro_warning.text() == t("episode.gen.empty_intro")
    dialog._keep()  # a key press past the disabled button
    assert dialog.result() != dialog.DialogCode.Accepted and session.episode.is_empty
    dialog.intro_name_edit.setText("دروس")
    assert dialog.ok_button.isEnabled() and not _shown(dialog.intro_warning)


def test_ok_without_a_change_keeps_a_length_the_fields_would_round(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.jobs.episode_assets import GeneratedIntro

    dialog = _generated_dialog(
        episode_lecture, prefs, tmp_path, monkeypatch, intro=GeneratedIntro(name="x", seconds=5.5)
    )
    dialog.ok_button.click()
    assert episode_lecture.episode.intro_generated.seconds == 5.5
    assert not episode_lecture.dirty
    assert episode_lecture.undo() and not episode_lecture.can_undo, "only the setup's step"
    assert prefs.default_episode_kinds == ("none", "none"), "nothing changed, no default"


def test_a_generated_part_starts_from_its_default(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.prefs import KEEP_DEFAULT
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import GeneratedIntro, GeneratedOutro

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    phrase = "شكرًا للمتابعة"
    prefs.save_default_episode(
        KEEP_DEFAULT,
        KEEP_DEFAULT,
        intro_generated=GeneratedIntro(name="قناتي", style="reveal"),
        outro_generated=GeneratedOutro(phrase=phrase, link="example.org", platform="facebook"),
    )
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    assert dialog.intro_kind.currentData() == "none", "this lecture has no intro"
    dialog.intro_kind.setCurrentIndex(dialog.intro_kind.findData("generated"))
    dialog.outro_kind.setCurrentIndex(dialog.outro_kind.findData("generated"))
    assert dialog.intro_name_edit.text() == "قناتي"
    assert dialog.intro_style.currentData() == "reveal"
    assert dialog.outro_phrase.currentData() is None, "a phrase of their own: Custom…"
    assert dialog.outro_phrase_custom.text() == phrase and _shown(dialog.outro_phrase_custom)
    assert dialog.outro_platform.currentData() == "facebook"


def test_cancel_changes_nothing_for_generated_parts(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
    before = episode_lecture.episode
    dialog.intro_kind.setCurrentIndex(dialog.intro_kind.findData("none"))
    dialog.outro_link.setText("example.org/new")
    dialog.outro_platform.setCurrentIndex(dialog.outro_platform.findData("facebook"))
    dialog.reject()
    assert episode_lecture.episode == before and not episode_lecture.dirty
    assert episode_lecture.undo() and not episode_lecture.can_undo, "only the setup's step"
    assert prefs.default_episode_kinds == ("none", "none")


def test_an_address_that_could_pass_for_another_or_cannot_be_drawn_is_warned(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    """Probe S6 (review M4): the written address is checked like the name and the phrase."""
    from qurantext.core.title_cards import missing_glyphs
    from qurantext.gui.i18n import t

    dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
    dialog.outro_link.setText("пример.рф/уроки")
    assert dialog.ok_button.isEnabled(), "a real site may be named so: a warning, not a refusal"
    chars = missing_glyphs("جزاكم الله خيرًا" + "пример.рф/уроки")
    assert chars and dialog.outro_warning.text() == t("episode.gen.missing_glyphs", chars=chars)
    dialog.outro_link.setText("pаypal.com")  # a Cyrillic «а»
    assert t("episode.link_warning.mixed") in dialog.outro_warning.text()
    dialog.outro_link.setText("рау.com")  # all Cyrillic, all Latin-looking
    assert t("episode.link_warning.confusable") in dialog.outro_warning.text()
    dialog.outro_link.setText("example.org/dars")
    assert not _shown(dialog.outro_warning)


def test_a_refused_link_cannot_be_kept_by_any_way_round_the_button(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    """Review M9 and probe S5: _keep itself refuses, and Return does not accept."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
    before = episode_lecture.episode
    dialog.show()
    dialog.outro_link.setFocus()
    dialog.outro_link.setText("ftp://example.org")
    QTest.keyClick(dialog.outro_link, Qt.Key.Key_Return)
    assert dialog.isVisible() and dialog.result() != dialog.DialogCode.Accepted
    dialog._keep()
    assert dialog.result() != dialog.DialogCode.Accepted
    assert episode_lecture.episode == before
    assert prefs.default_episode_kinds == ("none", "none")
    dialog.reject()


def test_closing_the_dialog_stops_a_preview_waiting_for_typing(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    """Review M9: no preview is drawn for a dialog already closed."""
    dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
    dialog.intro_name_edit.setText("اسم آخر")
    assert dialog._preview_timer.isActive()
    dialog.reject()
    assert not dialog._preview_timer.isActive()


def test_the_dialog_fits_a_laptop_screen_with_warnings(qt_app, tmp_path, prefs, monkeypatch):
    """Probe S7 (review M10): Arabic, portrait, both parts Generated, a warning under each."""
    from qurantext.gui.language import apply_language
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import EpisodeChoice, GeneratedIntro, GeneratedOutro

    apply_language(qt_app, "ar")
    session, folder = _probe_lecture(tmp_path, monkeypatch)
    session.set_episode(
        EpisodeChoice(
            intro_generated=GeneratedIntro(name="Привет"),
            outro_generated=GeneratedOutro(phrase="Спасибо", link="example.org/" + "a" * 500),
        )
    )
    dialog = EpisodeDialog(session, prefs=prefs, job_dirs=[folder])
    dialog.flush_previews()
    assert _shown(dialog.intro_warning) and _shown(dialog.outro_warning)
    hint = dialog.sizeHint()
    assert hint.height() <= 700, hint
    assert hint.width() <= 1000, "a long address does not widen the dialog"
    dialog.reject()


def test_the_dialog_says_its_changes_become_the_default(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import set_language, t

    texts = {}
    for language in ("en", "ar"):
        set_language(language)
        dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
        assert _shown(dialog.defaults_hint) and dialog.defaults_hint.wordWrap()
        texts[language] = dialog.defaults_hint.text()
        assert texts[language] == t("episode.defaults_hint")
        dialog.reject()
    assert texts["en"] == "Changes you make here also become the default for new lectures."
    assert texts["ar"] == "ما تغيّره هنا يصبح أيضًا الافتراضي للدروس الجديدة."


def test_a_dialog_opened_after_a_card_change_shows_the_new_campaign(
    qt_app, tmp_path, prefs, monkeypatch
) -> None:
    """Review M6: the shown and copied links are read from the cards as they are on opening."""
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import EpisodeChoice, GeneratedOutro

    card = {"surah_num": 25, "surah_name": "الفرقان", "full_text": "وَقَالُواْ", "confidence": 0.9}
    cards = [dict(card, from_ayah=44, to_ayah=44, start_time=1.0, end_time=4.0)]
    session, folder = _probe_lecture(tmp_path, monkeypatch, cards=cards)
    session.set_episode(EpisodeChoice(outro_generated=GeneratedOutro(link="example.org")))
    dialog = EpisodeDialog(session, prefs=prefs, job_dirs=[folder])
    assert "utm_campaign=qalun-025-044-044" in dialog.outro_tracked.text()
    dialog.reject()
    session.project.cards.append(dict(card, from_ayah=49, to_ayah=49, start_time=6.0, end_time=9.0))
    dialog = EpisodeDialog(session, prefs=prefs, job_dirs=[folder])
    assert "utm_campaign=qalun-025-044-049" in dialog.outro_tracked.text()
    assert "utm_campaign=qalun-025-044-049" in dialog._description_link


def test_the_generated_fields_mirror_in_arabic_and_links_stay_left_to_right(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from PySide6.QtCore import Qt

    from qurantext.gui.i18n import ltr, t
    from qurantext.gui.language import apply_language

    apply_language(qt_app, "ar")
    dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
    rtl, ltr_ = Qt.LayoutDirection.RightToLeft, Qt.LayoutDirection.LeftToRight
    assert dialog.layoutDirection() == rtl
    assert dialog.intro_name_edit.layoutDirection() == rtl
    assert dialog.outro_platform.layoutDirection() == rtl
    assert dialog.outro_link.layoutDirection() == ltr_
    assert dialog.outro_tracked.layoutDirection() == ltr_
    assert dialog.outro_copy.text() == "انسخ"
    assert dialog.outro_platform.currentText() == "يوتيوب"
    assert dialog.intro_kind.currentText() == "مُولَّد"
    # The readable text is one left-to-right run inside the Arabic sentence.
    assert dialog.outro_readable.text() == t("episode.gen.readable", link=ltr("example.org/dars"))
    assert "\u2066example.org/dars\u2069" in dialog.outro_readable.text()
    assert dialog.outro_tracked.text().startswith("https://example.org/dars?"), "no marks"


def test_no_label_in_the_episode_dialog_is_clipped(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QLabel

    from qurantext.gui.language import apply_language

    for language in ("en", "ar"):
        apply_language(qt_app, language)
        dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
        dialog.flush_previews()
        dialog.show()
        qt_app.processEvents()
        clipped = [
            (label.text(), label.width(), label.sizeHint().width())
            for label in dialog.findChildren(QLabel)
            if label.isVisible()
            and not label.wordWrap()
            and label.pixmap().isNull()
            and label.text()
            and label.width() < label.sizeHint().width()
        ]
        assert not clipped, (language, clipped)
        dialog.reject()


def _no_frames(monkeypatch) -> list:
    """``clip_frame`` makes nothing; what it was asked for."""
    from qurantext.gui.review import episode_dialog

    asked: list = []
    monkeypatch.setattr(
        episode_dialog, "clip_frame", lambda path, cache, **kw: asked.append(path.name) or None
    )
    return asked


def test_the_cards_show_each_parts_length_and_picture(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from PIL import Image

    from qurantext.gui.i18n import t
    from qurantext.gui.review import episode_dialog
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"intro.mp4": 4.0})
    (tmp_path / "intro.mp4").write_bytes(b"intro")
    frame = tmp_path / "frame.png"
    Image.new("RGB", (176, 99), (0, 200, 0)).save(frame)
    monkeypatch.setattr(episode_dialog, "clip_frame", lambda path, cache, **kw: frame)
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    cards = dialog.cards
    assert cards["lecture"].length_label.text() == "01:40"
    assert cards["lecture"].thumb_label.property("placeholder") is True, "no card: empty tile"
    assert cards["intro"].length_label.text() == "—"
    _choose_file(monkeypatch, tmp_path / "intro.mp4")
    dialog.intro_choose.click()
    assert cards["intro"].length_label.text() == "00:04"
    assert cards["intro"].thumb_label.pixmap().size().toTuple() == (176, 99)
    dialog.outro_kind.setCurrentIndex(dialog.outro_kind.findData("generated"))
    dialog.outro_link.setText("")
    dialog.flush_previews()
    assert cards["outro"].length_label.text() == "00:06"
    assert cards["outro"].thumb_label.pixmap() is not None
    assert not cards["outro"].thumb_label.pixmap().isNull()
    assert cards["outro"].chip.isHidden()
    assert t("episode.unknown") not in cards["recitation"].length_label.text()


def test_a_clip_without_a_frame_shows_the_film_icon(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"intro.mp4": 4.0})
    (tmp_path / "intro.mp4").write_bytes(b"intro")
    asked = _no_frames(monkeypatch)
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    _choose_file(monkeypatch, tmp_path / "intro.mp4")
    dialog.intro_choose.click()
    assert asked == ["intro.mp4"]
    card = dialog.cards["intro"]
    assert card.thumb_label.property("placeholder") is False
    assert card.thumb_label.pixmap().width() < 100, "the film icon, not a frame"
    dialog.ok_button.click()
    assert dialog.result() == dialog.DialogCode.Accepted


def test_a_gone_clip_and_a_refused_link_are_said_on_the_cards(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import EpisodeChoice

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    _no_frames(monkeypatch)
    episode_lecture.set_episode(EpisodeChoice(intro=tmp_path / "gone.mp4", intro_name="gone.mp4"))
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    chip = dialog.cards["intro"].chip
    assert not chip.isHidden() and chip.text_label.text() == t("episode.chip.missing")
    assert chip.property("kind") == "attention"
    dialog.intro_remove.click()
    assert chip.isHidden()


def test_a_refused_link_marks_the_outro_card_without_selecting_it(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t

    _no_frames(monkeypatch)
    dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
    dialog.select_part("intro")
    dialog.outro_link.setText("http://bad host")
    assert dialog.selected_part() == "intro"
    chip = dialog.cards["outro"].chip
    assert not chip.isHidden() and chip.text_label.text() == t("episode.chip.attention")
    dialog.outro_link.setText("example.org")
    assert chip.isHidden()


def test_the_recitation_card_repeats_the_chosen_jobs_standing(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    paths = _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"fatiha.mp4": 7.0})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    card = dialog.cards["recitation"]
    assert card.chip.isHidden() and card.length_label.text() == "—"
    box = dialog.recitation_box
    box.setCurrentIndex(box.findData(paths["rendered"]))
    assert card.chip.text_label.text() == t("episode.rendered")
    assert card.chip.property("kind") == "accent"
    assert card.length_label.text() == "00:07"
    box.setCurrentIndex(box.findData(paths["fresh"]))
    assert card.chip.text_label.text() == t("episode.render_first")
    assert card.chip.property("kind") == "neutral"


def test_the_strip_fills_the_selected_word_with_the_accent(qt_app) -> None:
    from qurantext.gui import theme

    theme.apply_theme(qt_app, "light")
    session, strip = _strip(qt_app)
    strip.resize(600, 44)
    words = session.words()
    strip.select(words[0].ref)
    image = strip.grab().toImage()
    x = int(
        (strip._viewport.x_for(words[0].start, 600) + strip._viewport.x_for(words[0].end, 600)) / 2
    )
    # Above the centred label, so the sample lands on the fill rather than a glyph.
    assert image.pixelColor(x, 8).name().upper() == theme.LIGHT.accent.upper()
    assert strip.minimumSizeHint().height() >= 40 and strip.HANDLE_PX == 6
    assert strip.EDGE_PX == 8


def test_the_waveform_draws_the_current_word_stronger(qt_app) -> None:
    from qurantext.gui import theme
    from qurantext.gui.review.waveform_view import WaveformView

    theme.apply_theme(qt_app, "light")
    viewport = Viewport()
    viewport.set_duration(10.0)
    viewport.set_window(0.0, 10.0)
    view = WaveformView(viewport)
    view.resize(100, 50)
    view.set_peaks(Peaks(mins=np.full(100, -0.9), maxs=np.full(100, 0.9), rate=10.0, duration=10.0))
    view.set_current_word(2.0, 3.0)
    image = view.grab().toImage()
    inside = image.pixelColor(int(viewport.x_for(2.5, 100)), 25)
    outside = image.pixelColor(int(viewport.x_for(7.5, 100)), 25)
    assert inside.alpha() == 255 and inside != outside
    assert inside.name().upper() == theme.LIGHT.accent.upper()
    assert outside.name().upper() != theme.LIGHT.panel.upper()  # bars are drawn there too, fainter
    view.set_current_word(None, None)
    image = view.grab().toImage()
    assert image.pixelColor(int(viewport.x_for(2.5, 100)), 25) == outside


def test_the_table_marks_the_playhead_row_with_a_rule_and_shows_icons(qt_app) -> None:
    from qurantext.gui.review.segment_list import SegmentList

    table = SegmentList(_three_cue_session())
    assert table.ROW_HEIGHT == 32 and table.alternatingRowColors()
    assert table.verticalHeader().defaultSectionSize() == 32
    assert not table.item(0, 0).icon().isNull()
    assert not table.item(table.rowCount() - 1, 0).icon().isNull()
    table.highlight_at(2.5)
    assert table.playhead_row() == 1
    assert table.item(1, 2).background().style() == Qt.BrushStyle.NoBrush  # a rule, not a tint
    retimed = [table.item(r, 3).text() for r in range(table.rowCount())]
    assert "0" not in retimed


def test_a_cards_row_shows_the_book_and_a_captions_the_microphone(qt_app) -> None:
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
    table = SegmentList(ReviewSession(project))
    card_icon = table.item(0, 0).icon().pixmap(16, 16).toImage()
    caption_icon = table.item(1, 0).icon().pixmap(16, 16).toImage()
    assert not card_icon.isNull() and not caption_icon.isNull()
    assert card_icon != caption_icon


def test_the_playhead_rule_is_painted_on_the_rows_leading_edge(qt_app) -> None:
    from qurantext.gui import theme
    from qurantext.gui.review.segment_list import SegmentList

    theme.apply_theme(qt_app, "light")
    table = SegmentList(_three_cue_session())
    table.resize(500, 200)
    table.highlight_at(2.5)
    rect = table.visualRect(table.model().index(1, 0))
    image = table.viewport().grab().toImage()
    accent = theme.LIGHT.accent.upper()
    assert image.pixelColor(rect.left() + 1, rect.center().y()).name().upper() == accent
    other = table.visualRect(table.model().index(0, 0))
    assert image.pixelColor(other.left() + 1, other.center().y()).name().upper() != accent


def test_the_playhead_rule_leads_from_the_right_under_arabic(qt_app) -> None:
    from qurantext.gui import theme
    from qurantext.gui.review.segment_list import SegmentList

    theme.apply_theme(qt_app, "light")
    table = SegmentList(_three_cue_session())
    table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    table.resize(500, 200)
    # Shown, so the header lays its sections out mirrored before a cell's rect is asked for.
    table.show()
    qt_app.processEvents()
    table.highlight_at(2.5)
    rect = table.visualRect(table.model().index(1, 0))
    image = table.viewport().grab().toImage()
    accent = theme.LIGHT.accent.upper()
    assert image.pixelColor(rect.right() - 1, rect.center().y()).name().upper() == accent
    assert image.pixelColor(rect.left() + 1, rect.center().y()).name().upper() != accent
    table.close()


def test_the_playhead_rule_shows_on_a_selected_row(qt_app) -> None:
    """The selection fill is the accent too, so there the rule is drawn in the text-on-accent colour."""
    from qurantext.gui import theme
    from qurantext.gui.review.segment_list import SegmentList

    theme.apply_theme(qt_app, "light")
    table = SegmentList(_three_cue_session())
    table.resize(500, 200)
    table.show()
    table.activateWindow()
    qt_app.processEvents()
    table.highlight_at(2.5)
    table.selectRow(1)
    rect = table.visualRect(table.model().index(1, 0))
    image = table.viewport().grab().toImage()
    rule = image.pixelColor(rect.left() + 1, rect.center().y())
    fill = image.pixelColor(rect.left() + 8, rect.top() + 2)
    assert rule.name().upper() == theme.LIGHT.on_accent.upper()
    assert rule != fill
    table.close()


def test_the_retimed_count_is_drawn_in_the_secondary_colour_and_follows_the_theme(qt_app) -> None:
    from qurantext.gui import theme
    from qurantext.gui.review.segment_list import SegmentList

    theme.apply_theme(qt_app, "light")
    try:
        table = SegmentList(_three_cue_session())
        item = table.item(0, 3)
        assert item.foreground().color().name().upper() == theme.LIGHT.secondary.upper()
        icon_before = table.item(0, 0).icon().pixmap(16, 16).toImage()
        theme.apply_theme(qt_app, "dark")
        qt_app.processEvents()
        item = table.item(0, 3)
        assert item.foreground().color().name().upper() == theme.DARK.secondary.upper()
        assert table.item(0, 0).icon().pixmap(16, 16).toImage() != icon_before
    finally:
        theme.apply_theme(qt_app, "light")


def test_the_four_pictures_line_up_when_no_part_is_chosen(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui import theme
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    theme.apply_theme(qt_app, "light")
    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    assert (dialog._kind("intro"), dialog._kind("outro")) == ("none", "none")
    dialog.show()
    _spin_briefly(qt_app)
    ys = {
        part: card.thumb_label.mapTo(dialog, QPoint(0, 0)).y()
        for part, card in dialog.cards.items()
    }
    assert len(set(ys.values())) == 1, ys
    dialog.reject()


def test_focus_starts_on_the_selected_parts_kind_and_tab_runs_along_the_strip(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import EpisodeChoice, GeneratedOutro

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    dialog.show()
    _spin_briefly(qt_app)
    assert dialog.focusWidget() is dialog.intro_kind
    # Along the strip: the intro's controls, then the recitation, and only then the outro.
    seen = []
    widget = dialog.intro_kind.nextInFocusChain()
    while widget is not dialog.intro_kind and len(seen) < 200:
        seen.append(widget)
        widget = widget.nextInFocusChain()
    recitation = min(
        seen.index(w) for w in (dialog.cards["recitation"], dialog.recitation_box) if w in seen
    )
    outro = min(seen.index(w) for w in (dialog.cards["outro"], dialog.outro_kind))
    for control in (dialog.intro_choose, dialog.intro_remove):
        assert seen.index(control) < recitation
    assert recitation < outro
    assert seen.index(dialog.cards["outro"]) < seen.index(dialog.outro_kind)
    # Enter on the kind box is the dialog's, not the card's: it presses OK.
    QTest.keyClick(dialog.intro_kind, Qt.Key.Key_Return)
    assert dialog.result() == dialog.DialogCode.Accepted

    episode_lecture.set_episode(
        EpisodeChoice(outro_generated=GeneratedOutro(link="example.org/dars", platform="youtube"))
    )
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    dialog.show()
    _spin_briefly(qt_app)
    assert dialog.selected_part() == "outro"
    assert dialog.focusWidget() is dialog.outro_kind
    dialog.reject()

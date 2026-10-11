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
    background = view.palette().color(QPalette.ColorRole.Window)
    near_top = 10  # only a loud column reaches this high
    assert image.pixelColor(150, near_top) != background, "the first 5 s are drawn on the right"
    assert image.pixelColor(50, near_top) == background, "the silent last 5 s on the left"


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
    # The selected word's fill covers its own box and not the earlier word's.
    from PySide6.QtGui import QPalette

    strip.select(b.ref)
    image = strip.grab().toImage()
    highlight = strip.palette().color(QPalette.ColorRole.Highlight)
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
    assert table.item(1, 2).background().style() != Qt.BrushStyle.NoBrush
    assert table.item(0, 2).background().style() == Qt.BrushStyle.NoBrush


def test_an_edge_dragged_past_its_neighbour_and_back_leaves_the_neighbour(qt_app) -> None:
    session, strip = _strip(qt_app)
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, pos=QPoint(800, 17))
    for x in (700, 650, 800):
        QTest.mouseMove(strip, QPoint(x, 17))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, pos=QPoint(800, 17))
    words = session.words()
    assert (words[0].end, words[1].start, words[1].end) == (2.0, 2.0, 3.0)


def test_a_ripple_dragged_past_the_clamp_and_back_ends_where_it_began(qt_app) -> None:
    session, strip = _strip(qt_app)
    shift = Qt.KeyboardModifier.ShiftModifier
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, shift, QPoint(650, 17))
    for x in (900, 1000, 650):
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


def test_the_warnings_strip_lists_five_gaps_then_counts_the_rest(qt_app) -> None:
    from qurantext.core.coverage import UncoveredSpeech
    from qurantext.gui.review.warnings_strip import WarningsStrip

    strip = WarningsStrip()
    strip.set_gaps([UncoveredSpeech(float(i), i + 0.5, -20.0) for i in range(8)])
    assert strip.text().count("Jump") == 5
    assert "8 stretches of speech have no word:" in strip.text()
    assert "…and 3 more" in strip.text()
    assert "0.5 s at 00:00.0–00:00.5" in strip.text()


def test_the_warnings_strip_counts_a_single_gap_in_the_singular(qt_app) -> None:
    from qurantext.core.coverage import UncoveredSpeech
    from qurantext.gui.review.warnings_strip import WarningsStrip

    strip = WarningsStrip()
    strip.set_gaps([UncoveredSpeech(4.0, 6.0, -20.0)])
    assert "1 stretch of speech has no word:" in strip.text()
    assert "2.0 s at 00:04.0–00:06.0" in strip.text()


def test_the_selection_bar_shows_the_span_as_one_value(qt_app) -> None:
    from qurantext.gui.review.selection_bar import SelectionBar
    from qurantext.gui.review.session import CARD, TimelineWord, WordRef

    bar = SelectionBar()
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
    combo = panel.background_combo
    combo.setCurrentIndex(combo.findData(kind))
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
    combo = panel.background_combo
    combo.setCurrentIndex(combo.findData("solid"))
    bg = session.look.background
    frame_bg = PRESETS["ocean"].frame_bg
    assert (bg.kind, bg.colour, bg.colour2, bg.dim) == ("solid", frame_bg, frame_bg, 0.0)
    assert session.look.frame_bg == bg.colour
    combo.setCurrentIndex(combo.findData("pattern_stars"))
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
    assert panel.background_combo.currentData() == "image"
    assert panel.dim_slider.value() == 35


def test_choosing_image_in_the_list_runs_the_same_flow(
    qt_app, session, prefs, tmp_path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    panel = _panel(session, prefs)
    combo = panel.background_combo
    combo.setCurrentIndex(combo.findData("image"))
    assert not session.can_undo, "a cancelled choice is no edit"
    assert combo.currentData() == "solid", "the list goes back to what the look has"


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


# -- the panel's sliders and list in a scroll area: wheel and lost grabs -------------


def _wheel(widget, ticks: int, *, up: bool) -> list[bool]:
    """*ticks* notches of the mouse wheel over *widget*; whether each was taken.

    Up raises a slider; down moves a list to its next entry. A real wheel event
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


def test_the_wheel_scrolls_past_the_sliders_and_the_list(
    qt_app, session, prefs, monkeypatch
) -> None:
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
    taken += _wheel(panel.background_combo, 6, up=False)  # far enough to reach "My image"

    assert not any(taken), "every notch is left to the scroll area"
    assert session.look == NIGHT_GOLD and not session.can_undo
    assert panel.background_combo.currentData() == "solid"
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
    panel.background_combo.setFocus(Qt.FocusReason.MouseFocusReason)
    qt_app.processEvents()
    assert _wheel(panel.background_combo, 1, up=False) == [True]
    assert session.look.background.kind == "gradient"
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

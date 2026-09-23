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
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent
    from PySide6.QtWidgets import QApplication

    from qurantext.gui.review.session import CARD, WordRef

    session, strip = _strip(qt_app)
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, pos=QPoint(200, 17))
    QTest.mouseMove(strip, QPoint(210, 17))
    assert session.can_undo  # the edge drag already opened a gesture

    QApplication.sendEvent(strip, QFocusEvent(QEvent.Type.FocusOut))

    # A retime from outside the strip, after the gesture was force-closed,
    # must open an undo entry of its own rather than merging into the drag.
    session.retime(WordRef(CARD, 0, 2), end=4.5)
    assert session.words()[2].end == pytest.approx(4.5)

    assert session.undo()
    assert session.words()[2].end == pytest.approx(4.0)
    assert session.undo()
    assert session.words()[1].start == pytest.approx(2.0)
    assert not session.can_undo


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

"""The review window's widgets, driven offscreen."""

from __future__ import annotations

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

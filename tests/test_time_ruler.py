"""The ruler over the waveform: ticks and times that never overlap, right to left."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402

from qurantext.gui.review import time_ruler  # noqa: E402
from qurantext.gui.review.time_ruler import TimeRuler, tick_step  # noqa: E402
from qurantext.gui.review.viewport import Viewport  # noqa: E402


@pytest.mark.parametrize(
    ("span", "width", "expected"),
    [
        (10.0, 1200.0, 1.0),
        (120.0, 600.0, 10.0),
        (3600.0, 600.0, 300.0),  # Review Focus 1: an hour on a narrow ruler labels every 5 min
        (20.0, 600.0, 2.0),
    ],
)
def test_the_major_step_keeps_labels_apart(span, width, expected) -> None:
    major, minor = tick_step(span, width, label_px=48.0)
    assert major == expected
    assert minor < major and major % minor == 0


def test_a_degenerate_span_or_width_returns_the_largest_step() -> None:
    assert tick_step(0.0, 600.0, 48.0)[0] == time_ruler.STEPS[-1]
    assert tick_step(10.0, 0.0, 48.0)[0] == time_ruler.STEPS[-1]


def _ruler(qt_app, span=10.0, duration=60.0, width=600):
    viewport = Viewport()
    viewport.set_duration(duration)
    viewport.set_window(0.0, span)
    ruler = TimeRuler(viewport)
    ruler.resize(width, TimeRuler.HEIGHT)
    return ruler, viewport


def test_labels_run_right_to_left_with_the_first_at_the_right(qt_app) -> None:
    ruler, _ = _ruler(qt_app)
    labels = ruler.labels()  # [(x, text), ...] as they would be painted
    assert labels[0][1] == "00:00" and labels[0][0] > labels[-1][0]
    assert all(b[0] + 48 <= a[0] for a, b in zip(labels, labels[1:], strict=False))


def test_a_click_seeks_and_a_hover_names_the_time(qt_app) -> None:
    ruler, viewport = _ruler(qt_app)
    sought = []
    ruler.seek_requested.connect(sought.append)
    x = viewport.x_for(2.5, ruler.width())
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPoint(int(x), 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    ruler.mousePressEvent(press)
    assert sought and abs(sought[0] - 2.5) < 0.05
    assert ruler.time_at(x).startswith("00:02")


def test_the_playhead_mark_sits_at_its_time(qt_app) -> None:
    ruler, viewport = _ruler(qt_app)
    ruler.set_playhead(5.0)
    assert abs(ruler.playhead_x() - viewport.x_for(5.0, ruler.width())) < 1.0

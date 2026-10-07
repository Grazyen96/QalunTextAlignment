"""The few colours the windows do not take from the palette, in a shade that reads on it.

Amber says "needs attention" (a job row, an edited word) and red marks the
playhead; neither has a palette role. One fixed amber was 2.2:1 on a white
list and unreadable there, so each colour comes in a shade for a light
palette and one for a dark palette, and a widget asks for it with the
palette it paints on — so a theme switched while the app runs gets the right
shade on the next paint. The light shades were measured against Qt's light
window (239) and base (255), the dark ones against Fusion's dark window (53)
and base (35): every amber ≥ 4.5:1 as text, every red ≥ 3:1 as a mark.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

__all__ = ["is_light", "playhead_color", "warning_color"]

_WARNING_ON_LIGHT = QColor(158, 86, 0)
_WARNING_ON_DARK = QColor(239, 159, 39)
_PLAYHEAD_ON_LIGHT = QColor(200, 48, 48)
_PLAYHEAD_ON_DARK = QColor(226, 75, 74)


def is_light(palette: QPalette) -> bool:
    """Whether *palette* is a light theme: its window colour is nearer white than black."""
    return palette.color(QPalette.ColorRole.Window).lightness() >= 128


def warning_color(palette: QPalette) -> QColor:
    """The "needs attention" amber for *palette*, readable as text on its base and window."""
    return QColor(_WARNING_ON_LIGHT if is_light(palette) else _WARNING_ON_DARK)


def playhead_color(palette: QPalette) -> QColor:
    """The playhead red for *palette*, readable as a mark on its window."""
    return QColor(_PLAYHEAD_ON_LIGHT if is_light(palette) else _PLAYHEAD_ON_DARK)

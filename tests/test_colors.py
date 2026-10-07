"""The two fixed colours must read on whichever palette the system gives."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QPalette  # noqa: E402

from qurantext.gui.colors import is_light, playhead_color, warning_color  # noqa: E402


def _luminance(color: QColor) -> float:
    def channel(value: int) -> float:
        v = value / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def contrast(a: QColor, b: QColor) -> float:
    """WCAG contrast ratio between two colours."""
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _palette(window: QColor, base: QColor) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.Base, base)
    return palette


LIGHT = _palette(QColor(239, 239, 239), QColor(255, 255, 255))
DARK = _palette(QColor(53, 53, 53), QColor(35, 35, 35))


def test_lightness_is_read_from_the_window_colour() -> None:
    assert is_light(LIGHT) and not is_light(DARK)


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_the_amber_reads_as_text_on_the_list_and_the_window(palette) -> None:
    amber = warning_color(palette)
    for role in (QPalette.ColorRole.Base, QPalette.ColorRole.Window):
        assert contrast(amber, palette.color(role)) >= 4.5


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_the_playhead_red_reads_as_a_mark_on_the_window(palette) -> None:
    assert contrast(playhead_color(palette), palette.color(QPalette.ColorRole.Window)) >= 3.0


def test_the_light_palette_gets_a_darker_amber_than_the_dark_one() -> None:
    assert warning_color(LIGHT).lightness() < warning_color(DARK).lightness()

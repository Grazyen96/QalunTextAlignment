"""The app's own light and dark theme: every colour reads, the sheet stays off Fusion's widgets."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtGui import QColor, QFont, QPalette  # noqa: E402

from qurantext.gui import theme  # noqa: E402
from qurantext.gui.colors import playhead_color, warning_color  # noqa: E402
from tests.test_colors import contrast  # noqa: E402

THEMES = [theme.LIGHT, theme.DARK]
IDS = ["light", "dark"]


def _c(hex_value: str) -> QColor:
    return QColor(hex_value)


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_text_reads_on_every_surface(tokens) -> None:
    for surface in (tokens.window, tokens.panel, tokens.raised):
        assert contrast(_c(tokens.text), _c(surface)) >= 4.5, surface
        assert contrast(_c(tokens.secondary), _c(surface)) >= 4.5, surface


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_the_accent_reads_as_a_control_and_carries_its_text(tokens) -> None:
    assert contrast(_c(tokens.on_accent), _c(tokens.accent)) >= 4.5
    for surface in (tokens.window, tokens.panel):
        assert contrast(_c(tokens.accent), _c(surface)) >= 3.0, surface


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_the_border_is_visible(tokens) -> None:
    assert contrast(_c(tokens.border), _c(tokens.window)) >= 1.5


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_the_fixed_colours_still_read_on_the_new_surfaces(tokens) -> None:
    palette = theme.palette(tokens)
    amber = warning_color(palette)
    for role in (QPalette.ColorRole.Base, QPalette.ColorRole.Window):
        assert contrast(amber, palette.color(role)) >= 4.5
    assert contrast(playhead_color(palette), palette.color(QPalette.ColorRole.Window)) >= 3.0


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_the_palette_maps_every_role_the_sheet_relies_on(tokens) -> None:
    palette = theme.palette(tokens)
    assert palette.color(QPalette.ColorRole.Window).name().upper() == tokens.window.upper()
    assert palette.color(QPalette.ColorRole.Base).name().upper() == tokens.panel.upper()
    assert palette.color(QPalette.ColorRole.Highlight).name().upper() == tokens.accent.upper()
    assert (
        palette.color(QPalette.ColorRole.HighlightedText).name().upper() == tokens.on_accent.upper()
    )
    assert palette.color(QPalette.ColorRole.Link).name().upper() == tokens.accent.upper()
    assert (
        palette.color(QPalette.ColorRole.PlaceholderText).name().upper() == tokens.secondary.upper()
    )
    disabled = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
    assert disabled.name().upper() == tokens.secondary.upper()


def test_light_is_light_and_dark_is_dark() -> None:
    from qurantext.gui.colors import is_light

    assert is_light(theme.palette(theme.LIGHT))
    assert not is_light(theme.palette(theme.DARK))


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_the_sheet_leaves_fusions_widgets_alone(tokens) -> None:
    sheet = theme.stylesheet(tokens)
    for widget in ("QComboBox", "QSpinBox", "QSlider", "QScrollBar", "QCheckBox", "QRadioButton"):
        assert widget not in sheet, widget


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_the_sheet_styles_what_fusion_cannot(tokens) -> None:
    sheet = theme.stylesheet(tokens)
    assert 'QPushButton[primary="true"]' in sheet
    assert 'QPushButton[primary="true"]:disabled' in sheet
    assert "QFrame#dropZone" in sheet
    assert 'QFrame#dropZone[dragOver="true"]' in sheet
    assert 'QFrame[card="true"]' in sheet
    assert "QHeaderView::section" in sheet
    assert "QProgressBar::chunk" in sheet
    assert tokens.accent in sheet and tokens.on_accent in sheet


def test_tokens_are_found_by_name() -> None:
    assert theme.tokens_for("light") is theme.LIGHT
    assert theme.tokens_for("dark") is theme.DARK
    with pytest.raises(KeyError):
        theme.tokens_for("sepia")


def test_fonts_follow_the_scale(qt_app) -> None:
    body = theme.font("body")
    assert theme.font("title").pointSizeF() > theme.font("section").pointSizeF() > body.pointSizeF()
    assert theme.font("secondary").pointSizeF() < body.pointSizeF()
    assert theme.font("section").weight() == QFont.Weight.DemiBold
    assert theme.font("clock").pointSizeF() == body.pointSizeF()
    with pytest.raises(KeyError):
        theme.font("huge")


def test_spacing_is_an_eight_point_scale() -> None:
    assert (theme.SP_4, theme.SP_8, theme.SP_12, theme.SP_16, theme.SP_24, theme.SP_32) == (
        4,
        8,
        12,
        16,
        24,
        32,
    )

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
    assert 'QFrame[card="true"][empty="true"]' in sheet
    assert "QHeaderView::section" in sheet
    assert tokens.accent in sheet and tokens.on_accent in sheet


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_the_progress_bar_is_left_to_fusion(tokens) -> None:
    """A sheet rule on the bar draws its label in one colour, unreadable over the chunk."""
    assert "QProgressBar" not in theme.stylesheet(tokens)


def _rule(sheet: str, selector: str) -> dict[str, str]:
    """The declarations of the rule whose selector list is exactly *selector*."""
    head = selector + " {"
    assert head in sheet, selector
    body = sheet.split(head, 1)[1].split("}", 1)[0]
    declarations = {}
    for part in body.split(";"):
        if ":" in part:
            name, value = part.split(":", 1)
            declarations[name.strip()] = value.strip()
    return declarations


def _measured(declarations: dict[str, str]) -> float:
    return contrast(_c(declarations["color"]), _c(declarations["background"]))


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_a_disabled_primary_keeps_its_text_readable(tokens) -> None:
    rule = _rule(theme.stylesheet(tokens), 'QPushButton[primary="true"]:disabled')
    assert _measured(rule) >= 4.5


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_a_checked_button_that_is_disabled_keeps_its_text_readable(tokens) -> None:
    """While a job runs the chosen mode is checked and disabled: its word must still read."""
    sheet = theme.stylesheet(tokens)
    rule = _rule(
        sheet,
        'QPushButton[segment="true"]:checked:disabled, QToolButton[swatch="true"]:checked:disabled',
    )
    assert _measured(rule) >= 4.5
    # Still marked as the chosen one: an accent outline, visible on its fill.
    assert tokens.accent in rule["border"]
    assert contrast(_c(tokens.accent), _c(rule["background"])) >= 3.0


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_only_segments_are_filled_when_checked(tokens) -> None:
    """A disclosure says open by its chevron; a checked swatch says chosen by its ring and name."""
    sheet = theme.stylesheet(tokens)
    rule = _rule(sheet, 'QPushButton[segment="true"]:checked')
    assert rule["background"] == tokens.accent and rule["color"] == tokens.on_accent
    assert _measured(rule) >= 4.5
    swatch = _rule(sheet, 'QToolButton[swatch="true"]:checked')
    assert swatch["background"] == "transparent" and swatch["color"] == tokens.accent
    for loose in ("QPushButton:checked", "QToolButton:checked"):
        assert loose not in sheet, loose


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_a_disabled_tile_draws_no_frame_its_neighbours_lack(tokens) -> None:
    """The image tile without a project file: greyed name, no box around it."""
    rule = _rule(theme.stylesheet(tokens), 'QToolButton[swatch="true"]:disabled')
    assert rule["border-color"] == "transparent"


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_rows_quiet_buttons_placeholders_and_selected_cards_have_rules(tokens) -> None:
    sheet = theme.stylesheet(tokens)
    row = _rule(sheet, 'QPushButton[row="true"]')
    assert row["background"] == "transparent" and row["text-align"] == "left"
    # Qt mirrors "left" in a right-to-left window; a "right" for Arabic would land on the left.
    assert "[rtl=" not in sheet
    quiet = _rule(sheet, 'QPushButton[quiet="true"]')
    assert quiet["background"] == "transparent" and quiet["color"] == tokens.accent
    assert contrast(_c(tokens.accent), _c(tokens.window)) >= 4.5
    assert tokens.border in _rule(sheet, 'QLabel[placeholder="true"]')["border"]
    assert tokens.accent in _rule(sheet, 'QFrame[card="true"][selected="true"]')["border"]


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
    if hasattr(QFont, "setFeature") and hasattr(QFont, "Tag"):
        # Tabular digits, so a running clock does not jitter (spec §6).
        assert theme.font("clock").featureValue(QFont.Tag("tnum")) == 1
        assert not theme.font("body").isFeatureSet(QFont.Tag("tnum"))
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


from PySide6.QtCore import Qt  # noqa: E402


class _Hints:
    """Stands in for QStyleHints: a scheme the test chooses, and the signal Qt would emit."""

    def __init__(self, scheme) -> None:
        self._scheme = scheme
        self._slots = []

    def colorScheme(self):  # noqa: N802 - Qt's name
        return self._scheme

    class _Signal:
        def __init__(self, hints) -> None:
            self._hints = hints

        def connect(self, slot) -> None:
            self._hints._slots.append(slot)

    @property
    def colorSchemeChanged(self):  # noqa: N802 - Qt's name
        return self._Signal(self)

    def change(self, scheme) -> None:
        self._scheme = scheme
        for slot in list(self._slots):
            slot(scheme)


@pytest.fixture()
def hints(qt_app, monkeypatch):
    stand_in = _Hints(Qt.ColorScheme.Light)
    monkeypatch.setattr(theme, "_style_hints", lambda app: stand_in)
    # An earlier apply may have connected the real hints; let this test connect the stand-in.
    qt_app.setProperty(theme._CONNECTED_PROPERTY, False)
    # conftest's fixture restores the theme and this property once the stand-in is gone.
    return stand_in


def test_light_and_dark_apply_their_palette_and_sheet(qt_app, hints) -> None:
    tokens = theme.apply_theme(qt_app, "dark")
    assert tokens is theme.DARK
    assert qt_app.palette().color(QPalette.ColorRole.Window).name().upper() == theme.DARK.window
    assert theme.DARK.accent in qt_app.styleSheet()
    assert theme.current_tokens(qt_app) is theme.DARK
    assert theme.apply_theme(qt_app, "light") is theme.LIGHT
    qt_app.setStyleSheet("")  # with a sheet set, style() is Qt's sheet proxy, not Fusion
    assert qt_app.style().objectName().lower() == "fusion"


def test_system_follows_the_desktop_live(qt_app, hints) -> None:
    hints.change(Qt.ColorScheme.Dark)
    assert theme.apply_theme(qt_app, "system") is theme.DARK
    hints.change(Qt.ColorScheme.Light)
    assert theme.current_tokens(qt_app) is theme.LIGHT
    hints.change(Qt.ColorScheme.Dark)
    assert theme.current_tokens(qt_app) is theme.DARK


def test_a_fixed_theme_ignores_the_desktop(qt_app, hints) -> None:
    theme.apply_theme(qt_app, "light")
    hints.change(Qt.ColorScheme.Dark)
    assert theme.current_tokens(qt_app) is theme.LIGHT


def test_an_unknown_scheme_counts_as_light(qt_app, hints) -> None:
    hints.change(Qt.ColorScheme.Unknown)
    assert theme.apply_theme(qt_app, "system") is theme.LIGHT


def test_an_unknown_mode_is_refused(qt_app, hints) -> None:
    with pytest.raises(ValueError):
        theme.apply_theme(qt_app, "sepia")


def test_current_tokens_before_any_apply_is_light() -> None:
    assert theme.current_tokens(None) is theme.LIGHT


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_a_toolbar_separator_is_drawn_in_the_border_colour(tokens) -> None:
    rule = _rule(theme.stylesheet(tokens), 'QFrame[separator="true"]')
    assert rule["color"] == tokens.border

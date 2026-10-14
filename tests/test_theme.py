"""The app's own light and dark theme: every colour reads, the sheet stays off Fusion's widgets."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtGui import QColor, QFont, QPalette  # noqa: E402

from qurantext.core.looks import PRESETS  # noqa: E402
from qurantext.gui import theme  # noqa: E402
from qurantext.gui.colors import playhead_color, warning_color  # noqa: E402
from qurantext.gui.review.look_panel import _PALE_RING  # noqa: E402
from qurantext.gui.style import QalunStyle  # noqa: E402
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
    # A part card keeps a 2 px border always, so selecting it (the accent) moves nothing.
    assert _rule(sheet, 'QFrame[card="true"][part="true"]')["border"] == "2px solid transparent"
    assert sheet.index('QFrame[card="true"][part="true"]') < sheet.index(
        'QFrame[card="true"][selected="true"]'
    )


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
    style = qt_app.style()  # Qalun's proxy, which draws through Fusion
    assert isinstance(style, QalunStyle)
    assert style.baseStyle().objectName().lower() == "fusion"


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


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_quiet_buttons_and_the_chosen_tile_keep_focus_disabled_and_pressed_looks(tokens) -> None:
    """The quiet rule and the checked tile come late in the sheet: their states must follow."""
    sheet = theme.stylesheet(tokens)
    focus = _rule(sheet, 'QPushButton[quiet="true"][kbdfocus="true"]')
    assert focus["border"] == f"2px solid {tokens.accent}" and focus["padding"] == "4px 9px"
    assert _rule(sheet, 'QPushButton[quiet="true"]:disabled')["color"] == tokens.secondary
    assert _rule(sheet, 'QPushButton[quiet="true"]:pressed')["background"] == tokens.border
    for state in ('[kbdfocus="true"]', ":disabled", ":pressed"):
        assert sheet.index(f'QPushButton[quiet="true"]{state}') > sheet.index(
            'QPushButton[quiet="true"] {'
        ), state
    tile = _rule(sheet, 'QToolButton[swatch="true"]:checked[kbdfocus="true"]')
    assert tile["border-color"] == tokens.accent
    assert _rule(sheet, 'QToolButton[swatch="true"]:checked')["border-color"] == "transparent"


def _near(colour: QColor, target: QColor, slack: int = 24) -> bool:
    return all(
        abs(a - b) <= slack for a, b in zip(colour.getRgb()[:3], target.getRgb()[:3], strict=True)
    )


def _edge_has(widget, target: QColor) -> bool:
    """Whether *target* is drawn on the middle of each of the widget's four edges."""
    image = widget.grab().toImage()
    w, h = image.width(), image.height()
    sides = (
        [(x, h // 2) for x in range(3)],
        [(w - 1 - x, h // 2) for x in range(3)],
        [(w // 2, y) for y in range(3)],
        [(w // 2, h - 1 - y) for y in range(3)],
    )
    return all(any(_near(image.pixelColor(x, y), target) for x, y in side) for side in sides)


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_a_focused_quiet_button_and_a_focused_chosen_tile_show_the_accent_ring(
    qt_app, mode
) -> None:
    from PySide6.QtWidgets import (
        QApplication,
        QHBoxLayout,
        QLineEdit,
        QPushButton,
        QToolButton,
        QWidget,
    )

    tokens = theme.apply_theme(qt_app, mode)
    accent = QColor(theme.current_tokens().accent)
    assert accent == QColor(tokens.accent)
    window = QWidget()
    row = QHBoxLayout(window)
    elsewhere = QLineEdit()
    row.addWidget(elsewhere)
    quiet = QPushButton("Reset")
    quiet.setProperty("quiet", True)
    tile = QToolButton()
    tile.setText("Solid")
    tile.setAutoRaise(True)
    tile.setProperty("swatch", True)
    tile.setCheckable(True)
    tile.setChecked(True)
    tile.setFixedSize(56, 36)
    disabled = QPushButton("Choose image")
    disabled.setProperty("quiet", True)
    disabled.setEnabled(False)
    for widget in (quiet, tile, disabled):
        row.addWidget(widget)
    window.show()
    window.activateWindow()
    elsewhere.setFocus()
    QApplication.processEvents()
    assert not _edge_has(quiet, accent) and not _edge_has(tile, accent)
    for widget in (quiet, tile):
        widget.setFocus(Qt.FocusReason.TabFocusReason)
        QApplication.processEvents()
        assert widget.hasFocus()
        assert _edge_has(widget, accent), widget.text()
    # A disabled quiet button reads as off: no accent anywhere in it.
    image = disabled.grab().toImage()
    assert not any(
        _near(image.pixelColor(x, y), accent, slack=12)
        for x in range(image.width())
        for y in range(image.height())
    )
    # A click focuses without the ring: only the keyboard paints it.
    quiet.setFocus(Qt.FocusReason.MouseFocusReason)
    QApplication.processEvents()
    assert quiet.hasFocus()
    assert not _edge_has(quiet, accent)
    window.close()
    window.deleteLater()


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_focus_is_a_property_not_a_pseudo_class(tokens) -> None:
    """A click or a dialog's first focus paints no ring; Tab does (gui.focus marks it)."""
    sheet = theme.stylesheet(tokens)
    assert ":focus" not in sheet
    ring = _rule(sheet, 'QPushButton[kbdfocus="true"], QToolButton[kbdfocus="true"]')
    assert ring["border"] == f"2px solid {tokens.accent}"
    assert _rule(sheet, 'QPushButton[primary="true"][kbdfocus="true"]')["border"] == (
        f"2px solid {tokens.text}"
    )


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_cards_hover_and_focus_like_buttons(tokens) -> None:
    sheet = theme.stylesheet(tokens)
    part_hover = 'QFrame[card="true"][part="true"][clickable="true"]:hover'
    part_focus = 'QFrame[card="true"][part="true"][kbdfocus="true"]'
    selected_part = 'QFrame[card="true"][part="true"][selected="true"]:hover'
    assert _rule(sheet, 'QFrame[card="true"][clickable="true"]:hover')["border-color"] == (
        tokens.accent
    )
    assert _rule(sheet, part_hover)["border-color"] == tokens.border
    assert _rule(sheet, 'QFrame[card="true"][kbdfocus="true"]')["border"] == (
        f"2px solid {tokens.accent}"
    )
    # A focused part card is the text colour, hovered or not, like the primary button.
    assert _rule(sheet, f"{part_focus}, {part_focus}:hover")["border"] == (
        f"2px solid {tokens.text}"
    )
    # The selected Episode card's border wins over hover: its rule comes later.
    for hover in ('QFrame[card="true"][clickable="true"]:hover', part_hover):
        assert sheet.index('QFrame[card="true"][selected="true"]') > sheet.index(hover), hover
    # The hover rules outrank [selected] by one term, so selection repeats itself with :hover.
    assert _rule(sheet, 'QFrame[card="true"][selected="true"]:hover')["border-color"] == (
        tokens.accent
    )
    # The part hover and focus rules outrank that too, so a selected part card repeats
    # itself with [part], hovered and focused, after them.
    focused = 'QFrame[card="true"][part="true"][selected="true"][kbdfocus="true"]'
    selected_rule = _rule(sheet, f"{selected_part}, {focused}, {focused}:hover")
    assert selected_rule["border"] == f"2px solid {tokens.accent}"
    assert sheet.index(selected_part) > sheet.index(part_hover)
    assert sheet.index(selected_part) > sheet.index(part_focus)


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_only_clickable_cards_hover(tokens) -> None:
    """The Banner, the job cards and the Settings cards are not clickable: no hover border."""
    assert 'QFrame[card="true"]:hover' not in theme.stylesheet(tokens)


def test_apply_theme_installs_the_focus_marker(qt_app) -> None:
    from qurantext.gui import focus

    theme.apply_theme(qt_app, "light")
    assert isinstance(qt_app.property("qalun.focus_marker"), focus.KeyboardFocusMarker)


def test_a_selected_card_keeps_its_border_when_hovered(qt_app) -> None:
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent

    from qurantext.gui.review.episode_cards import PartCard

    tokens = theme.apply_theme(qt_app, "light")
    card = PartCard("Intro")
    card.set_selected(True)
    card.show()
    qt_app.processEvents()
    assert card.testAttribute(Qt.WidgetAttribute.WA_Hover)
    centre = QPointF(card.rect().center())
    qt_app.sendEvent(card, QEnterEvent(centre, centre, card.mapToGlobal(centre.toPoint())))
    qt_app.processEvents()
    image = card.grab().toImage()
    accent = QColor(tokens.accent)
    # Two accent pixels deep on the left edge: the 2 px selection border, not a 1 px hover one.
    y = image.height() // 2
    assert _near(image.pixelColor(0, y), accent) and _near(image.pixelColor(1, y), accent)
    card.close()
    # An unselected card hovered shows the border token, so hover never reads as selection.
    other = PartCard("Outro")
    other.show()
    qt_app.processEvents()
    centre = QPointF(other.rect().center())
    qt_app.sendEvent(other, QEnterEvent(centre, centre, other.mapToGlobal(centre.toPoint())))
    qt_app.processEvents()
    assert other.underMouse() or other.testAttribute(Qt.WidgetAttribute.WA_UnderMouse)
    image = other.grab().toImage()
    y = image.height() // 2
    border = QColor(tokens.border)
    assert _near(image.pixelColor(0, y), border, slack=8)
    assert not _near(image.pixelColor(0, y), accent)
    other.close()


def _hover(qt_app, widget) -> None:
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent

    centre = QPointF(widget.rect().center())
    qt_app.sendEvent(widget, QEnterEvent(centre, centre, widget.mapToGlobal(centre.toPoint())))
    qt_app.processEvents()


def _left_edge(widget) -> QColor:
    image = widget.grab().toImage()
    return image.pixelColor(0, image.height() // 2)


@pytest.mark.parametrize("mode", IDS)
def test_a_keyboard_focused_part_card_is_marked_apart_from_the_selected_one(qt_app, mode) -> None:
    """Focus on an Episode card is the text colour, hovered or not; selection stays the accent.

    Tabbing onto a card does not select it, so its mark must not read as selection,
    and the pointer over it must not take the mark away.
    """
    from PySide6.QtWidgets import QHBoxLayout, QWidget

    from qurantext.gui.review.episode_cards import PartCard

    tokens = theme.apply_theme(qt_app, mode)
    text, accent = QColor(tokens.text), QColor(tokens.accent)
    window = QWidget()
    row = QHBoxLayout(window)
    chosen, focused = PartCard("Intro"), PartCard("Outro")
    row.addWidget(chosen)
    row.addWidget(focused)
    chosen.set_selected(True)
    window.show()
    window.activateWindow()  # an inactive window gets no FocusIn events
    qt_app.processEvents()
    focused.setFocus(Qt.FocusReason.TabFocusReason)
    qt_app.processEvents()
    assert focused.property("kbdfocus") is True and not focused.selected
    assert _near(_left_edge(focused), text, slack=8), mode
    assert _near(_left_edge(chosen), accent, slack=8), mode
    _hover(qt_app, focused)
    assert _near(_left_edge(focused), text, slack=8), (mode, "hovered")
    # A selected card that has keyboard focus keeps the accent, hovered or not.
    chosen.setFocus(Qt.FocusReason.TabFocusReason)
    qt_app.processEvents()
    assert chosen.property("kbdfocus") is True
    assert _near(_left_edge(chosen), accent, slack=8), (mode, "selected and focused")
    _hover(qt_app, chosen)
    assert _near(_left_edge(chosen), accent, slack=8), (mode, "selected, focused, hovered")
    window.close()


def test_a_card_that_cannot_be_selected_does_not_hover(qt_app) -> None:
    """The Lecture and Recitation cards do nothing on a click, so the pointer changes nothing."""
    import re

    from qurantext.gui.review.episode_cards import PartCard

    tokens = theme.apply_theme(qt_app, "light")
    card = PartCard("Lecture")
    card.set_selectable(False)
    assert card.property("clickable") is False
    # Every card hover rule asks for a clickable, a selected or a focused card, and an
    # unselectable card is none of these (it takes no focus).
    asks = ('[clickable="true"]', '[selected="true"]', '[kbdfocus="true"]')
    for selector in re.findall(r"^([^{]*:hover[^{]*)\{", theme.stylesheet(tokens), re.MULTILINE):
        for part in selector.split(","):
            if 'QFrame[card="true"]' in part and ":hover" in part:
                assert any(ask in part for ask in asks), part
    assert card.focusPolicy() == Qt.FocusPolicy.NoFocus
    card.show()
    qt_app.processEvents()
    before = _left_edge(card)
    _hover(qt_app, card)
    assert _left_edge(card) == before
    assert not _near(_left_edge(card), QColor(tokens.border), slack=8)
    card.close()


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_every_colour_added_since_phase_a_reads_on_its_surfaces(tokens) -> None:
    """One table for the ring, the amber, the playhead, the quiet accent and the hex labels."""
    pal = theme.palette(tokens)
    surfaces = {"window": tokens.window, "panel": tokens.panel, "raised": tokens.raised}
    # The ring sits on a preset tile's frame: a pale frame (lightness 128 or more) wears
    # the pale-tile gold, a dark one the dark theme's gold, in either theme.
    frames = {name: QColor(*preset.frame_bg[:3]) for name, preset in PRESETS.items()}
    pale = {name: c.name() for name, c in frames.items() if c.lightness() >= 128}
    dark = {name: c.name() for name, c in frames.items() if c.lightness() < 128}
    assert pale and dark
    checks = [
        ("gold", tokens.gold, surfaces, 3.0),
        ("pale ring", _PALE_RING, {**surfaces, **pale}, 3.0),
        ("dark ring", theme.DARK.gold, dark, 3.0),
        ("amber", warning_color(pal).name(), surfaces, 4.5),
        (
            "playhead",
            playhead_color(pal).name(),
            {"window": tokens.window, "panel": tokens.panel},
            3.0,
        ),
        ("accent", tokens.accent, {"raised": tokens.raised, "window": tokens.window}, 4.5),
        ("secondary", tokens.secondary, {"raised": tokens.raised, "window": tokens.window}, 4.5),
        ("on_accent", tokens.on_accent, {"accent": tokens.accent}, 4.5),
    ]
    for name, colour, on, floor in checks:
        for surface, value in on.items():
            assert contrast(_c(colour), _c(value)) >= floor, (tokens.name, name, surface)

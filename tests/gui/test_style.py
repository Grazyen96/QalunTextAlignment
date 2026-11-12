"""The proxy over Fusion: indicators and fields keep a visible outline in both themes."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QCheckBox,
    QComboBox,
    QLineEdit,
    QProxyStyle,
    QRadioButton,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from qurantext.gui import theme  # noqa: E402
from qurantext.gui.style import QalunStyle  # noqa: E402


def _near(colour: QColor, target: QColor, slack: int = 28) -> bool:
    return all(
        abs(a - b) <= slack for a, b in zip(colour.getRgb()[:3], target.getRgb()[:3], strict=True)
    )


def _indicator_left(box) -> tuple[int, int]:
    option = QStyleOptionButton()
    box.initStyleOption(option)
    element = (
        QStyle.SubElement.SE_RadioButtonIndicator
        if isinstance(box, QRadioButton)
        else QStyle.SubElement.SE_CheckBoxIndicator
    )
    rect = box.style().subElementRect(element, option, box)
    return rect.left(), rect.center().y()


def _column_has(widget, x: int, y: int, target: QColor, slack: int = 28) -> bool:
    image = widget.grab().toImage()
    return any(_near(image.pixelColor(x + dx, y), target, slack) for dx in range(3))


def _application_style(app) -> QStyle:
    """The style set on *app*, under the sheet proxy Qt wraps it in once a sheet is set."""
    style = app.style()
    if style.metaObject().className() == "QStyleSheetStyle":
        (style,) = style.findChildren(QStyle, options=Qt.FindChildOption.FindDirectChildrenOnly)
    return style


def test_the_application_style_is_the_proxy_over_fusion(qt_app) -> None:
    theme.apply_theme(qt_app, "light")
    style = _application_style(qt_app)
    assert isinstance(style, QalunStyle) and isinstance(style, QProxyStyle)
    assert style.baseStyle().objectName().lower() == "fusion"
    theme.apply_theme(qt_app, "dark")
    assert _application_style(qt_app) is style, "set once, as Fusion was"


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_checkbox_and_radio_indicators_are_outlined_in_the_secondary_colour(qt_app, mode) -> None:
    tokens = theme.apply_theme(qt_app, mode)
    window = QWidget()
    column = QVBoxLayout(window)
    box, radio = QCheckBox("x"), QRadioButton("y")
    column.addWidget(box)
    column.addWidget(radio)
    window.show()
    qt_app.processEvents()
    outline = QColor(tokens.secondary)
    for widget in (box, radio):
        x, y = _indicator_left(widget)
        assert _column_has(widget, x, y, outline), (mode, type(widget).__name__)
    window.close()


def test_a_disabled_checkbox_keeps_its_outline(qt_app) -> None:
    tokens = theme.apply_theme(qt_app, "dark")
    box = QCheckBox("x")
    box.setEnabled(False)
    box.show()
    qt_app.processEvents()
    x, y = _indicator_left(box)
    assert _column_has(box, x, y, QColor(tokens.secondary))
    box.close()


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_an_unfocused_field_has_the_border_frame_and_a_focused_one_the_accent(qt_app, mode) -> None:
    tokens = theme.apply_theme(qt_app, mode)
    window = QWidget()
    column = QVBoxLayout(window)
    field, other = QLineEdit(), QLineEdit()
    column.addWidget(field)
    column.addWidget(other)
    window.show()
    other.setFocus(Qt.FocusReason.TabFocusReason)
    qt_app.processEvents()
    y = field.height() // 2
    assert _column_has(field, 0, y, QColor(tokens.border)), mode
    field.setFocus(Qt.FocusReason.TabFocusReason)
    qt_app.processEvents()
    assert _column_has(field, 0, y, QColor(tokens.accent)), mode
    window.close()


def test_the_sheet_still_names_none_of_fusions_widgets(qt_app) -> None:
    sheet = theme.stylesheet(theme.DARK)
    for name in ("QCheckBox", "QRadioButton", "QComboBox", "QSpinBox"):
        assert name not in sheet


def test_a_keyboard_focused_checkbox_keeps_fusions_highlight_on_its_indicator(qt_app) -> None:
    """The proxy's grey stroke stays off a box that has keyboard focus.

    Fusion strokes the box in the highlight when the focus came from the
    keyboard; drawing the secondary outline on top would hide the one cue a
    keyboard user has on a checkbox. Qt marks keyboard focus on the window
    when a real Tab key goes through the application, so the test presses one.
    """
    tokens = theme.apply_theme(qt_app, "dark")
    window = QWidget()
    column = QVBoxLayout(window)
    other, box = QLineEdit(), QCheckBox("x")
    column.addWidget(other)
    column.addWidget(box)
    window.show()
    window.activateWindow()
    other.setFocus(Qt.FocusReason.MouseFocusReason)
    qt_app.processEvents()
    x, y = _indicator_left(box)
    assert _column_has(box, x, y, QColor(tokens.secondary)), "unfocused: the outline"
    QTest.keyClick(other, Qt.Key.Key_Tab)
    qt_app.processEvents()
    assert box.hasFocus()
    assert _column_has(box, x, y, QColor(tokens.accent), slack=40), "focused: the highlight"
    assert not _column_has(box, x, y, QColor(tokens.secondary), slack=12)
    window.close()


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_a_combo_focused_by_a_click_keeps_the_border_frame(qt_app, mode) -> None:
    """Fusion frames a combo in its highlight only for keyboard focus, so the proxy frames a clicked one."""
    tokens = theme.apply_theme(qt_app, mode)
    window = QWidget()
    column = QVBoxLayout(window)
    combo = QComboBox()
    combo.addItems(["one", "two"])
    column.addWidget(combo)
    column.addWidget(QLineEdit())
    window.show()
    window.activateWindow()
    combo.setFocus(Qt.FocusReason.MouseFocusReason)
    qt_app.processEvents()
    assert combo.hasFocus()
    edge = combo.grab().toImage().pixelColor(0, combo.height() // 2)
    assert _near(edge, QColor(tokens.border), slack=8), (mode, edge.name())
    window.close()

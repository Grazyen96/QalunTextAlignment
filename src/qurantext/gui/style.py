"""A thin style over Fusion that keeps outlines visible in the dark theme.

Fusion draws a checkbox's box, a radio's circle and a field's frame in a
shade it derives from the window colour: about 1.1:1 in the dark theme,
which no palette role moves. The sheet cannot help without naming those
widgets, which breaks Fusion's sub-controls. So a proxy draws after Fusion:
a 1 px outline in the palette's placeholder-text colour (the secondary
token) around each indicator that does not have keyboard focus, and a 1 px
frame in the Mid colour (the border token) around a field that Fusion does
not frame in its highlight. Fusion highlights an indicator and a combo
only for keyboard focus, and a line edit or spin box for any focus; the
proxy stays off exactly what Fusion highlights. Both colours come from the
palette at draw time, so a theme switch needs nothing here.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPalette, QPen
from PySide6.QtWidgets import QProxyStyle, QStyle

__all__ = ["QalunStyle"]

_INDICATORS = (
    QStyle.PrimitiveElement.PE_IndicatorCheckBox,
    QStyle.PrimitiveElement.PE_IndicatorRadioButton,
)
_COMBO = QStyle.ComplexControl.CC_ComboBox
_FIELDS = (_COMBO, QStyle.ComplexControl.CC_SpinBox)
#: Fusion's corner radius on its boxes and frames.
_RADIUS = 2.0


class QalunStyle(QProxyStyle):
    """Fusion, with outlines the dark theme can show."""

    def drawPrimitive(self, element, option, painter, widget=None) -> None:  # noqa: N802, ANN001 - Qt override
        super().drawPrimitive(element, option, painter, widget)
        if element in _INDICATORS and not _keyboard_focused(option):
            colour = option.palette.color(QPalette.ColorRole.PlaceholderText)
            rect = QRectF(option.rect).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(colour, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if element == QStyle.PrimitiveElement.PE_IndicatorCheckBox:
                painter.drawRoundedRect(rect, _RADIUS, _RADIUS)
            else:
                painter.drawEllipse(rect)
            painter.restore()
        elif element == QStyle.PrimitiveElement.PE_FrameLineEdit and not _focused(option):
            _frame(painter, option)

    def drawComplexControl(self, control, option, painter, widget=None) -> None:  # noqa: N802, ANN001 - Qt override
        super().drawComplexControl(control, option, painter, widget)
        if control not in _FIELDS:
            return
        focused = _keyboard_focused if control == _COMBO else _focused
        if not focused(option):
            _frame(painter, option)


def _focused(option) -> bool:  # noqa: ANN001 - a QStyleOption
    return bool(option.state & QStyle.StateFlag.State_HasFocus)


def _keyboard_focused(option) -> bool:  # noqa: ANN001 - a QStyleOption
    """Focus that came from the keyboard: when Fusion draws its highlight on a box or combo."""
    return _focused(option) and bool(option.state & QStyle.StateFlag.State_KeyboardFocusChange)


def _frame(painter: QPainter, option) -> None:  # noqa: ANN001 - a QStyleOption
    """A 1 px frame in the border colour along the control's rounded edge."""
    colour = option.palette.color(QPalette.ColorRole.Mid)
    rect = QRectF(option.rect).adjusted(0.5, 0.5, -0.5, -0.5)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(colour, 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, _RADIUS, _RADIUS)
    painter.restore()

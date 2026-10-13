"""The few composite controls the windows share, so each looks the same everywhere.

``make_primary`` marks a plain ``QPushButton`` rather than replacing it:
every test reaches Start and Render by attribute, and they stay what they
were. The rest are small containers the stylesheet knows by a property.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qurantext.gui import theme
from qurantext.gui.colors import warning_color
from qurantext.gui.icons import icon

__all__ = ["CHIP_KINDS", "Card", "SectionHeader", "StatusChip", "make_primary"]

CHIP_KINDS = ("attention", "accent", "neutral")


def _repolish(widget: QWidget) -> None:
    """Make the stylesheet read a property set after the widget was styled."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def make_primary(button: QPushButton) -> QPushButton:
    """Fill *button* with the accent: the one action its screen is for. In a dialog, Enter presses it."""
    button.setProperty("primary", True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if isinstance(button.window(), QDialog):
        button.setDefault(True)
    _repolish(button)
    return button


class SectionHeader(QWidget):
    """A section's title in the section font, with room for one control at its far end."""

    def __init__(
        self, text: str, trailing: QWidget | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SP_8)
        self.label = QLabel(text)
        self.label.setFont(theme.font("section"))
        row.addWidget(self.label)
        row.addStretch(1)
        if trailing is not None:
            trailing.setParent(self)
            row.addWidget(trailing)

    def set_text(self, text: str) -> None:
        self.label.setText(text)


class Card(QFrame):
    """A raised surface with a border and 16 px of room inside; put content in ``body``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(theme.SP_16, theme.SP_16, theme.SP_16, theme.SP_16)
        self.body.setSpacing(theme.SP_8)


class StatusChip(QFrame):
    """An icon and a word in a pill: ``attention`` (amber), ``accent`` or ``neutral``."""

    def __init__(
        self,
        text: str,
        icon_name: str | None = None,
        kind: str = "neutral",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("chip", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(22)
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SP_8, 0, theme.SP_8, 0)
        row.setSpacing(theme.SP_4)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(QSize(16, 16))
        self.icon_label.setScaledContents(True)
        self.text_label = QLabel(text)
        self.text_label.setFont(theme.font("secondary"))
        row.addWidget(self.icon_label)
        row.addWidget(self.text_label)
        self._icon_name = icon_name
        self._kind = kind
        self.set_kind(kind)

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)

    def set_kind(self, kind: str) -> None:
        if kind not in CHIP_KINDS:
            raise KeyError(kind)
        self._kind = kind
        self.setProperty("kind", kind)
        palette = QPalette(self.text_label.palette())
        palette.setColor(self.text_label.foregroundRole(), self._colour())
        self.text_label.setPalette(palette)
        self._draw_icon()
        _repolish(self)

    def _colour(self) -> QColor:
        tokens = theme.current_tokens()
        if self._kind == "attention":
            return warning_color(self.palette())
        return QColor(tokens.accent if self._kind == "accent" else tokens.secondary)

    def _draw_icon(self) -> None:
        if self._icon_name is None:
            self.icon_label.hide()
            return
        role = {"attention": "text", "accent": "accent", "neutral": "secondary"}[self._kind]
        pixmap = icon(self._icon_name, role).pixmap(QSize(16, 16))
        if self._kind == "attention":
            # The amber has no token role; tint the pixmap through a mask.
            pixmap = pixmap.copy()
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), self._colour())
            painter.end()
        self.icon_label.setPixmap(pixmap)
        self.icon_label.show()

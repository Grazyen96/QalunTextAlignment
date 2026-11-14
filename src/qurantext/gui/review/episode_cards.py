from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLayout, QVBoxLayout, QWidget

from qurantext.gui import theme
from qurantext.gui.icons import icon
from qurantext.gui.widgets import Card, StatusChip, repolish

__all__ = ["CARD_WIDTH", "THUMB_BOX", "PartCard", "fitted_size"]

THUMB_BOX = (176, 99)
CARD_WIDTH = 204
_GLYPH = 28


def fitted_size(frame: tuple[int, int], box: tuple[int, int] = THUMB_BOX) -> tuple[int, int]:
    width, height = frame
    scale = min(box[0] / width, box[1] / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


class PartCard(Card):
    select_requested = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("part", True)
        self.setFixedWidth(CARD_WIDTH)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setProperty("clickable", True)
        self.setAccessibleName(title)
        self.body.setContentsMargins(theme.SP_12, theme.SP_12, theme.SP_12, theme.SP_12)
        self._selectable = True
        self._selected = False
        self.title_label = QLabel(title)
        bold = self.title_label.font()
        bold.setBold(True)
        self.title_label.setFont(bold)
        self.body.addWidget(self.title_label)
        self.controls = QVBoxLayout()
        self.controls.setSpacing(theme.SP_4)
        self.body.addLayout(self.controls)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(QSize(*THUMB_BOX))
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.thumb_label, 0, Qt.AlignmentFlag.AlignHCenter)
        foot = QHBoxLayout()
        self.length_label = QLabel("—")
        self.length_label.setFont(theme.font("secondary"))
        self.chip = StatusChip("", None, "neutral")
        self.chip.hide()
        foot.addWidget(self.length_label)
        foot.addStretch(1)
        foot.addWidget(self.chip)
        self.body.addLayout(foot)
        self.set_placeholder()

    def add_control(self, widget: QWidget) -> None:
        self.controls.addWidget(widget)
        widget.installEventFilter(self)

    def add_control_layout(self, layout: QLayout) -> None:
        self.controls.addLayout(layout)
        self._watch(layout)

    def _watch(self, layout: QLayout) -> None:
        """Watch every widget in *layout* and the layouts nested in it.

        A nested layout already belongs to *layout*: it is walked, never added
        again (Qt would warn that it already has a parent).
        """
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.installEventFilter(self)
            elif item is not None and item.layout() is not None:
                self._watch(item.layout())

    def set_thumbnail(self, pixmap: QPixmap | None) -> None:
        if pixmap is None:
            self.set_placeholder()
            return
        self._mark_placeholder(False)
        self.thumb_label.setPixmap(
            pixmap.scaled(
                QSize(*THUMB_BOX),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def set_placeholder(self) -> None:
        self.thumb_label.clear()
        self._mark_placeholder(True)

    def set_icon_tile(self, name: str) -> None:
        self._mark_placeholder(False)
        self.thumb_label.setPixmap(icon(name, "secondary").pixmap(QSize(_GLYPH, _GLYPH)))

    def _mark_placeholder(self, on: bool) -> None:
        self.thumb_label.setProperty("placeholder", on)
        repolish(self.thumb_label)

    def set_length(self, text: str) -> None:
        self.length_label.setText(text)

    def set_chip(
        self, text: str | None, kind: str = "neutral", icon_name: str | None = None
    ) -> None:
        if text is None:
            self.chip.hide()
            return
        self.chip.set_text(text)
        self.chip.set_icon(icon_name)
        self.chip.set_kind(kind)
        self.chip.show()

    def set_selectable(self, selectable: bool) -> None:
        self._selectable = selectable
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if selectable else Qt.FocusPolicy.NoFocus)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if selectable else Qt.CursorShape.ArrowCursor
        )
        self.setProperty("clickable", selectable)
        repolish(self)

    @property
    def selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.setProperty("selected", selected)
        repolish(self)

    def click(self) -> None:
        if self._selectable:
            self.select_requested.emit()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.click()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.hasFocus() and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Space,
        ):
            self.click()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.FocusIn:
            self.click()
        return False

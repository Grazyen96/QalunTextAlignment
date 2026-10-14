"""One card of the Episode dialog's strip: a part's title, controls, picture, length and standing.

The dialog owns four of these in render order (Intro · Recitation · Lecture ·
Outro) and fills each card's ``controls`` with the widgets it already has
(the kind box, the clip line, the recitation list). The card only shows:
a thumbnail fitted into :data:`THUMB_BOX`, a length line, a
:class:`StatusChip` when there is something to say, and whether it is the
selected one (a 2 px accent border, from the sheet's ``selected`` rule; the
``part`` rule keeps the same 2 px transparent otherwise).
A click, Enter or Space on the card, or focus landing on one of its
controls, asks the dialog to select it (``select_requested``); the dialog
decides, as the Lecture card is never selectable.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLayout, QVBoxLayout, QWidget

from qurantext.gui import theme
from qurantext.gui.icons import icon
from qurantext.gui.widgets import Card, StatusChip, repolish

__all__ = ["CARD_WIDTH", "THUMB_BOX", "PartCard", "fitted_size"]

#: The box a part's picture is fitted into, in pixels.
THUMB_BOX = (176, 99)
#: Each card's width: the box, the card's own margins and its 2 px border (transparent
#: until the card is selected, so selecting one moves nothing).
CARD_WIDTH = 204
#: An icon tile's glyph.
_GLYPH = 28


def fitted_size(frame: tuple[int, int], box: tuple[int, int] = THUMB_BOX) -> tuple[int, int]:
    """*frame*'s shape scaled to fit *box*, never larger than it."""
    width, height = frame
    scale = min(box[0] / width, box[1] / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


class PartCard(Card):
    """A part of the episode as a card; the dialog fills ``controls`` and sets the rest."""

    #: The person clicked the card, pressed Enter or Space on it, or focused one of its controls.
    select_requested = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("part", True)
        self.setFixedWidth(CARD_WIDTH)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
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

    # -- filling ---------------------------------------------------------------------

    def add_control(self, widget: QWidget) -> None:
        """Put *widget* under the title; focus landing on it selects the card."""
        self.controls.addWidget(widget)
        widget.installEventFilter(self)

    def add_control_layout(self, layout: QLayout) -> None:
        """Put a layout of controls under the title, watching each widget in it."""
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
        """The dashed empty tile: nothing is chosen for this part."""
        self.thumb_label.clear()
        self._mark_placeholder(True)

    def set_icon_tile(self, name: str) -> None:
        """An icon in place of a picture that could not be made."""
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

    # -- selection -------------------------------------------------------------------

    def set_selectable(self, selectable: bool) -> None:
        self._selectable = selectable
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if selectable else Qt.FocusPolicy.NoFocus)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if selectable else Qt.CursorShape.ArrowCursor
        )

    @property
    def selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.setProperty("selected", selected)
        repolish(self)

    def click(self) -> None:
        """Ask to be selected, as a press or a key would."""
        if self._selectable:
            self.select_requested.emit()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.click()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        # Only the card's own keys: Enter a control lets through is the dialog's (OK).
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

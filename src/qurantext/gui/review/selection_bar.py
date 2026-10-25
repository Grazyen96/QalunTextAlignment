"""The selected word and its times.

The buttons that retime it by small steps live on the transport now; the bar
hands them out as properties so a caller can still reach them from here, and
enables them with the selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRect
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from qurantext.gui import theme
from qurantext.gui.i18n import t, time_span
from qurantext.gui.quran_face import with_quran_face
from qurantext.gui.review.session import CARD, TimelineWord

if TYPE_CHECKING:
    from qurantext.gui.review.transport import Transport

__all__ = ["NUDGE_S", "SelectionBar"]

#: What the −/+ buttons move an edge by, in seconds.
NUDGE_S = 0.05


class SelectionBar(QWidget):
    """The selected word and its times; the nudge buttons live on the transport now."""

    def __init__(self, transport: Transport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._transport = transport
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setFont(theme.font("section"))
        row.addWidget(self.label, 1)
        self.show_word(None)

    @property
    def minus_button(self) -> QPushButton:
        """The transport's −50 ms button."""
        return self._transport.minus_button

    @property
    def plus_button(self) -> QPushButton:
        """The transport's +50 ms button."""
        return self._transport.plus_button

    @property
    def snap_button(self) -> QPushButton:
        """The transport's "Snap to playhead" button."""
        return self._transport.snap_button

    def show_word(self, word: TimelineWord | None) -> None:
        """Describe *word*, or invite a selection when there is none."""
        self._transport.set_selection(word is not None)
        # A card's word is the mushaf's, whose open tanween only the Quran face draws.
        section = theme.font("section")
        quran = with_quran_face(section)
        self.label.setFont(quran if word is not None and word.ref.kind == CARD else section)
        # The Quran face's line is taller; the bar keeps its height so nothing below it jumps.
        self.label.setMinimumHeight(_line_height(quran))
        if word is None:
            self.label.setText(t("review.no_selection"))
            return
        span = time_span(word.start, word.end, sep=" → ")
        self.label.setText(t("review.selected", word=word.text, span=span))


def _line_height(font: QFont) -> int:
    """How tall the label lays out a selected word's line in *font*, fallbacks included."""
    sample = t("review.selected", word="\u0645", span=time_span(0.0, 0.0, sep=" → "))
    return QFontMetrics(font).boundingRect(QRect(0, 0, 10_000, 1_000), 0, sample).height()

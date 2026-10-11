"""The cards and captions laid out as a table, one row per segment.

A recitation project has only ayah cards; a lecture project has cards (the
Quran quotes) followed by the captions, which are what a person actually
corrects — the recognised speech, not the certified ayah text. Each row
carries which segment it is (``("card", i)`` or ``("caption", i)``) as
``Qt.UserRole`` data on its reference cell, so a click can seek there and a
text edit can be routed back to the right cue.

In a lecture, a card's ayat are the person's to correct: detection follows
recitation and misses (or mismatches) the ayah a teacher goes back to. A
double-click on a card's Ayah cell, or "Change ayah…" in its context menu,
asks for that through :attr:`SegmentList.card_ayah_requested`; the window
opens the picker. A card placed or changed by hand is marked ✎ in that cell.

Quran text is read-only here for the same reason it is read-only everywhere
in the review window: a card records which ayah and when, never the
characters, which are always looked up from the store at render time.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from PySide6.QtCore import QPoint, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QContextMenuEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from qurantext.core.subtitles import card_ref
from qurantext.gui.i18n import is_rtl, ltr, t, time_span
from qurantext.gui.review.session import CAPTION, CARD, ReviewSession

__all__ = ["MANUAL_MARK", "SegmentList"]

_COLUMN_REF = 0
_COLUMN_TIME = 1
_COLUMN_TEXT = 2
_COLUMN_RETIMED = 3

#: Marks a card placed or changed by hand, ahead of its reference.
MANUAL_MARK = "✎"
_RLM = "\u200f"


class SegmentList(QTableWidget):
    """Lists ``session.project``'s cards (and, in a lecture, its captions)."""

    seek_requested = Signal(float)
    #: The person asked to change which ayat a lecture card shows; carries the card's index.
    card_ayah_requested = Signal(int)

    def __init__(self, session: ReviewSession, parent: QWidget | None = None) -> None:
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(
            [t("segments.ref"), t("segments.time"), t("segments.text"), t("segments.retimed")]
        )
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        # The text is what a person reads; the reference, time and count fit their contents.
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        for column in (_COLUMN_REF, _COLUMN_TIME, _COLUMN_RETIMED):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COLUMN_TEXT, QHeaderView.ResizeMode.Stretch)
        self._session = session
        self._loading = False
        #: Row order, parallel to the table: (kind, segment index, start time).
        self._rows: list[tuple[str, int, float]] = []
        self._row_by_segment: dict[tuple[str, int], int] = {}
        #: The row :meth:`highlight_at` last marked as under the playhead.
        self._playhead_row: int | None = None
        #: True while a click on a row seeks there: the playhead's row is then tinted but
        #: not scrolled to, so the clicked row stays under the pointer (a double-click's
        #: second press must land on the same cell to count as a double-click).
        self._seeking_from_click = False
        #: Whether a card's ayat may be changed from here; off while a render runs.
        self._cards_editable = True
        self.cellClicked.connect(self._on_cell_clicked)
        self.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.itemChanged.connect(self._on_item_changed)
        self.refresh()

    # -- filling ------------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild every row from the session, without writing anything back.

        Clears the selection rather than trying to keep it: a row's meaning
        is its position in this rebuilt list, and after an edit that shifted
        rows (a removal upstream, an undo) a kept selection would silently
        point at a different segment than the one the person had selected.
        """
        self._loading = True
        try:
            entries = self._entries()
            self.setRowCount(len(entries))
            self._rows = []
            self._row_by_segment = {}
            self._playhead_row = None  # every item is new, and none is marked
            for row, (kind, index) in enumerate(entries):
                self._fill_row(row, kind, index)
        finally:
            self._loading = False
        self.clearSelection()

    def _entries(self) -> list[tuple[str, int]]:
        project = self._session.project
        entries = [(CARD, i) for i in range(len(project.cards))]
        if project.mode == "lecture":
            entries += [(CAPTION, i) for i in range(len(project.captions))]
        return entries

    def _fill_row(self, row: int, kind: str, index: int) -> None:
        project = self._session.project
        if kind == CARD:
            card = project.cards[index]
            ref_text = card_ref(card)
            start = _as_float(card.get("start_time"))
            end = _as_float(card.get("end_time"), default=start)
            text = _card_text(card)
            retimed = (
                str(self._session.retimed_count(CARD, index)) if card.get("word_timings") else ""
            )
            text_editable = False
        else:
            cue = project.captions[index]
            ref_text = t("segments.speech")
            start = float(cue.start)
            end = float(cue.end)
            text = cue.text
            retimed = str(self._session.retimed_count(CAPTION, index)) if cue.words else ""
            text_editable = True

        self._rows.append((kind, index, start))
        self._row_by_segment[(kind, index)] = row

        manual = kind == CARD and self._session.is_manual(index)
        if manual:
            # In a right-to-left window an RLM leads, so the mark leads there too: the
            # reference alone has no letter to set the cell's direction by.
            ref_text = f"{_RLM if is_rtl() else ''}{MANUAL_MARK} {ref_text}"
        ref_item = self._set_item(row, _COLUMN_REF, ref_text, kind, index, editable=False)
        if manual:
            ref_item.setToolTip(t("segments.manual"))
        span = ltr(time_span(start, end))
        self._set_item(row, _COLUMN_TIME, span, kind, index, editable=False)
        text_item = self._set_item(row, _COLUMN_TEXT, text, kind, index, editable=text_editable)
        text_item.setTextAlignment(_text_alignment(text))
        if not text_editable:
            text_item.setToolTip(t("segments.locked"))
        self._set_item(row, _COLUMN_RETIMED, retimed, kind, index, editable=False)

    def _set_item(
        self, row: int, column: int, text: str, kind: str, index: int, *, editable: bool
    ) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, (kind, index))
        if editable:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        else:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setItem(row, column, item)
        return item

    # -- reading --------------------------------------------------------------

    def highlight_at(self, t_seconds: float) -> None:
        """Mark the row under *t_seconds* as the playhead's, and scroll it into view.

        A tinted background, never the selection or the current cell: the
        selection is what the person chose (and what "Remove selected"
        removes), so playback moving across rows must not change it.
        """
        segment = self.segment_at(t_seconds)
        row = self._row_by_segment.get(segment) if segment is not None else None
        if row == self._playhead_row:
            return
        if self._playhead_row is not None:
            self._paint_row(self._playhead_row, QBrush())
        self._playhead_row = row
        if row is None:
            return
        tint = QColor(self.palette().highlight().color())
        tint.setAlpha(60)
        self._paint_row(row, QBrush(tint))
        if not self._seeking_from_click:
            self.scrollToItem(self.item(row, _COLUMN_REF))

    def _paint_row(self, row: int, brush: QBrush) -> None:
        # A background change is an itemChanged too; it is not a text edit.
        blocker = QSignalBlocker(self)
        try:
            for column in range(self.columnCount()):
                item = self.item(row, column)
                if item is not None:
                    item.setBackground(brush)
        finally:
            blocker.unblock()

    def segment_at(self, t_seconds: float) -> tuple[str, int] | None:
        """The ``(kind, index)`` of the row :meth:`highlight_at` would mark at *t_seconds*.

        A lecture's caption wins over the card it quotes from; ``None`` before
        the first segment.
        """
        if self._session.project.mode == "lecture":
            caption_index = self._session.caption_at(t_seconds)
            if caption_index is not None:
                return (CAPTION, caption_index)
        card_index = self._session.card_at(t_seconds)
        if card_index is not None:
            return (CARD, card_index)
        return None

    # -- editing ----------------------------------------------------------------

    def remove_selected(self) -> bool:
        """Remove the selected row(s) through the session; ``False`` if none is selected."""
        rows = sorted({index.row() for index in self.selectedIndexes()}, reverse=True)
        if not rows:
            return False
        for row in rows:
            kind, index, _start = self._rows[row]
            if kind == CARD:
                self._session.remove_card(index)
            else:
                self._session.remove_caption(index)
        self.refresh()
        return True

    def _on_cell_clicked(self, row: int, _column: int) -> None:
        if not 0 <= row < len(self._rows):
            return
        _kind, _index, start = self._rows[row]
        # In a lecture the caption at a card's start is the playhead's row, listed after
        # every card; scrolling to it would move another row under the pointer.
        self._seeking_from_click = True
        try:
            self.seek_requested.emit(start)
        finally:
            self._seeking_from_click = False

    def show_card(self, index: int) -> None:
        """Select card *index*'s row and scroll it into view, as after the person changed it."""
        row = self._row_by_segment.get((CARD, index))
        if row is None:
            return
        self.selectRow(row)
        self.scrollToItem(self.item(row, _COLUMN_REF))

    def set_cards_editable(self, editable: bool) -> None:
        """Offer changing a card's ayat (double-click, context menu) only while *editable*."""
        self._cards_editable = editable

    def _lecture_card(self, row: int) -> int | None:
        """The card index at *row* when its ayat may be changed by hand (a lecture's), else None."""
        if self._session.project.mode != "lecture" or not 0 <= row < len(self._rows):
            return None
        kind, index, _start = self._rows[row]
        return index if kind == CARD else None

    def _on_cell_double_clicked(self, row: int, column: int) -> None:
        index = self._lecture_card(row) if column == _COLUMN_REF else None
        if index is not None and self._cards_editable:
            self.card_ayah_requested.emit(index)

    def context_menu_at(self, pos: QPoint) -> QMenu | None:
        """The menu for the row under *pos* (viewport coordinates), or None when it has none.

        Only a lecture card's row has one, holding "Change ayah…", which is
        off while cards cannot be changed (a render is running).
        """
        return self._menu_for_row(self.rowAt(pos.y()))

    def _menu_for_row(self, row: int) -> QMenu | None:
        index = self._lecture_card(row)
        if index is None:
            return None
        menu = QMenu(self)
        action = menu.addAction(t("segments.change_ayah"))
        action.setEnabled(self._cards_editable)
        action.triggered.connect(lambda: self.card_ayah_requested.emit(index))
        return menu

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802 - Qt override
        if event.reason() == QContextMenuEvent.Reason.Keyboard:
            # The menu key names no point: the menu is for the current row.
            menu = self._menu_for_row(self.currentRow())
        else:
            # A scroll area hands its viewport's event on, so the position is the viewport's.
            menu = self.context_menu_at(event.pos())
        if menu is None:
            event.ignore()
            return
        menu.exec(event.globalPos())
        menu.deleteLater()
        event.accept()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != _COLUMN_TEXT:
            return
        row = item.row()
        if not 0 <= row < len(self._rows):
            return
        kind, index, _start = self._rows[row]
        if kind != CAPTION:
            return
        self._session.set_caption_text(index, item.text())


def _starts_right_to_left(text: str) -> bool:
    """Whether *text*'s first strong letter is a right-to-left one (False when it has none)."""
    for character in text:
        kind = unicodedata.bidirectional(character)
        if kind == "L":
            return False
        if kind in ("R", "AL"):
            return True
    return False


def _text_alignment(text: str) -> Qt.AlignmentFlag:
    """The edge a line of *text* starts from, whatever the window's direction.

    Quran text is Arabic and reads from the right in an English window too; a
    Latin lecture caption reads from the left in an Arabic one. AlignAbsolute
    stops Qt from mirroring the edge with the layout.
    """
    edge = (
        Qt.AlignmentFlag.AlignRight if _starts_right_to_left(text) else Qt.AlignmentFlag.AlignLeft
    )
    return edge | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter


def _card_text(card: dict[str, Any]) -> str:
    text = str(card.get("full_text") or card.get("text") or "")
    return text.splitlines()[0] if text else ""


def _as_float(value: Any, *, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default

from __future__ import annotations

import unicodedata
from typing import Any

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QContextMenuEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from qurantext.core.subtitles import card_ref
from qurantext.gui import theme
from qurantext.gui.i18n import is_rtl, ltr, t, time_span
from qurantext.gui.icons import icon
from qurantext.gui.quran_face import with_quran_face
from qurantext.gui.review.session import CAPTION, CARD, ReviewSession

__all__ = ["MANUAL_MARK", "SegmentList"]

_COLUMN_REF = 0
_COLUMN_TIME = 1
_COLUMN_TEXT = 2
_COLUMN_RETIMED = 3

MANUAL_MARK = "✎"
_RLM = "\u200f"


class SegmentList(QTableWidget):
    ROW_HEIGHT = 32

    seek_requested = Signal(float)
    card_ayah_requested = Signal(int)

    def __init__(self, session: ReviewSession, parent: QWidget | None = None) -> None:
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(
            [t("segments.ref"), t("segments.time"), t("segments.text"), t("segments.retimed")]
        )
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(self.ROW_HEIGHT)
        self.setAlternatingRowColors(True)
        self.setItemDelegateForColumn(_COLUMN_REF, _PlayheadRuleDelegate(self))
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        for column in (_COLUMN_REF, _COLUMN_TIME, _COLUMN_RETIMED):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COLUMN_TEXT, QHeaderView.ResizeMode.Stretch)
        self._session = session
        self._loading = False
        self._rows: list[tuple[str, int, float]] = []
        self._row_by_segment: dict[tuple[str, int], int] = {}
        self._playhead_row: int | None = None
        #: True while a click on a row seeks there: the playhead's row is then marked but
        #: not scrolled to, so the clicked row stays under the pointer (a double-click's
        #: second press must land on the same cell to count as a double-click).
        self._seeking_from_click = False
        self._cards_editable = True
        self.cellClicked.connect(self._on_cell_clicked)
        self.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.itemChanged.connect(self._on_item_changed)
        self.refresh()

    def refresh(self) -> None:
        self._loading = True
        try:
            entries = self._entries()
            self.setRowCount(len(entries))
            self._rows = []
            self._row_by_segment = {}
            self._playhead_row = None
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
            count = self._session.retimed_count(CARD, index) if card.get("word_timings") else 0
            text_editable = False
        else:
            cue = project.captions[index]
            ref_text = t("segments.speech")
            start = float(cue.start)
            end = float(cue.end)
            text = cue.text
            count = self._session.retimed_count(CAPTION, index) if cue.words else 0
            text_editable = True

        self._rows.append((kind, index, start))
        self._row_by_segment[(kind, index)] = row

        manual = kind == CARD and self._session.is_manual(index)
        if manual:
            # In a right-to-left window an RLM leads, so the mark leads there too: the
            # reference alone has no letter to set the cell's direction by.
            ref_text = f"{_RLM if is_rtl() else ''}{MANUAL_MARK} {ref_text}"
        ref_item = self._set_item(row, _COLUMN_REF, ref_text, kind, index, editable=False)
        ref_item.setIcon(_row_icon(kind))
        if manual:
            ref_item.setToolTip(t("segments.manual"))
        span = ltr(time_span(start, end))
        self._set_item(row, _COLUMN_TIME, span, kind, index, editable=False)
        text_item = self._set_item(row, _COLUMN_TEXT, text, kind, index, editable=text_editable)
        text_item.setTextAlignment(_text_alignment(text))
        if kind == CARD:
            # The mushaf's open tanween is drawn as open tanween only by the Quran face.
            text_item.setFont(with_quran_face(self.font()))
        if not text_editable:
            text_item.setToolTip(t("segments.locked"))
        retimed = str(count) if count else ""
        retimed_item = self._set_item(row, _COLUMN_RETIMED, retimed, kind, index, editable=False)
        retimed_item.setForeground(_secondary_brush())

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

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self._recolour()
        super().changeEvent(event)

    def _recolour(self) -> None:
        loading, self._loading = self._loading, True
        try:
            for row, (kind, _index, _start) in enumerate(self._rows):
                ref_item = self.item(row, _COLUMN_REF)
                if ref_item is not None:
                    ref_item.setIcon(_row_icon(kind))
                retimed_item = self.item(row, _COLUMN_RETIMED)
                if retimed_item is not None:
                    retimed_item.setForeground(_secondary_brush())
        finally:
            self._loading = loading

    def highlight_at(self, t_seconds: float) -> None:
        segment = self.segment_at(t_seconds)
        row = self._row_by_segment.get(segment) if segment is not None else None
        if row == self._playhead_row:
            return
        self._playhead_row = row
        self.viewport().update()
        if row is not None and not self._seeking_from_click:
            self.scrollToItem(self.item(row, _COLUMN_REF))

    def playhead_row(self) -> int | None:
        return self._playhead_row

    def segment_at(self, t_seconds: float) -> tuple[str, int] | None:
        if self._session.project.mode == "lecture":
            caption_index = self._session.caption_at(t_seconds)
            if caption_index is not None:
                return (CAPTION, caption_index)
        card_index = self._session.card_at(t_seconds)
        if card_index is not None:
            return (CARD, card_index)
        return None

    def remove_selected(self) -> bool:
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
        self._seeking_from_click = True
        try:
            self.seek_requested.emit(start)
        finally:
            self._seeking_from_click = False

    def show_card(self, index: int) -> None:
        row = self._row_by_segment.get((CARD, index))
        if row is None:
            return
        self.selectRow(row)
        self.scrollToItem(self.item(row, _COLUMN_REF))

    def set_cards_editable(self, editable: bool) -> None:
        self._cards_editable = editable

    def _lecture_card(self, row: int) -> int | None:
        if self._session.project.mode != "lecture" or not 0 <= row < len(self._rows):
            return None
        kind, index, _start = self._rows[row]
        return index if kind == CARD else None

    def _on_cell_double_clicked(self, row: int, column: int) -> None:
        index = self._lecture_card(row) if column == _COLUMN_REF else None
        if index is not None and self._cards_editable:
            self.card_ayah_requested.emit(index)

    def context_menu_at(self, pos: QPoint) -> QMenu | None:
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


class _PlayheadRuleDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:  # noqa: D102 - Qt override
        super().paint(painter, option, index)
        table = self.parent()
        if not isinstance(table, SegmentList) or index.row() != table.playhead_row():
            return
        rect = option.rect
        x = rect.right() - 2 if table.isRightToLeft() else rect.left()
        tokens = theme.current_tokens()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        colour = tokens.on_accent if selected else tokens.accent
        painter.fillRect(x, rect.top(), 3, rect.height(), QColor(colour))


def _row_icon(kind: str):
    return icon("book-open" if kind == CARD else "mic", "secondary")


def _secondary_brush() -> QBrush:
    return QBrush(QColor(theme.current_tokens().secondary))


def _starts_right_to_left(text: str) -> bool:
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

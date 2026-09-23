"""The cards and captions laid out as a table, one row per segment.

A recitation project has only ayah cards; a lecture project has cards (the
Quran quotes) followed by the captions, which are what a person actually
corrects — the recognised speech, not the certified ayah text. Each row
carries which segment it is (``("card", i)`` or ``("caption", i)``) as
``Qt.UserRole`` data on its reference cell, so a click can seek there and a
text edit can be routed back to the right cue.

Quran text is read-only here for the same reason it is read-only everywhere
in the review window: a card records which ayah and when, never the
characters, which are always looked up from the store at render time.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem, QWidget

from qurantext.core.subtitles import card_ref
from qurantext.gui.i18n import t
from qurantext.gui.review.session import CAPTION, CARD, ReviewSession

__all__ = ["SegmentList"]

_COLUMN_REF = 0
_COLUMN_TIME = 1
_COLUMN_TEXT = 2
_COLUMN_RETIMED = 3


class SegmentList(QTableWidget):
    """Lists ``session.project``'s cards (and, in a lecture, its captions)."""

    seek_requested = Signal(float)

    def __init__(self, session: ReviewSession, parent: QWidget | None = None) -> None:
        super().__init__(0, 4, parent)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setHorizontalHeaderLabels(
            [t("segments.ref"), t("segments.time"), t("segments.text"), t("segments.retimed")]
        )
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self._session = session
        self._loading = False
        #: Row order, parallel to the table: (kind, segment index, start time).
        self._rows: list[tuple[str, int, float]] = []
        self._row_by_segment: dict[tuple[str, int], int] = {}
        self.cellClicked.connect(self._on_cell_clicked)
        self.itemChanged.connect(self._on_item_changed)
        self.refresh()

    # -- filling ------------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild every row from the session, without writing anything back."""
        self._loading = True
        try:
            entries = self._entries()
            self.setRowCount(len(entries))
            self._rows = []
            self._row_by_segment = {}
            for row, (kind, index) in enumerate(entries):
                self._fill_row(row, kind, index)
        finally:
            self._loading = False

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
            ref_text = ""
            start = float(cue.start)
            end = float(cue.end)
            text = cue.text
            retimed = str(self._session.retimed_count(CAPTION, index)) if cue.words else ""
            text_editable = True

        self._rows.append((kind, index, start))
        self._row_by_segment[(kind, index)] = row

        self._set_item(row, _COLUMN_REF, ref_text, kind, index, editable=False)
        self._set_item(row, _COLUMN_TIME, f"{start:.2f}–{end:.2f}", kind, index, editable=False)
        text_item = self._set_item(row, _COLUMN_TEXT, text, kind, index, editable=text_editable)
        text_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
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
        """Select the row under *t_seconds*, without asking anyone to seek there."""
        segment = self._segment_at(t_seconds)
        if segment is None:
            return
        row = self._row_by_segment.get(segment)
        if row is None:
            return
        self.setCurrentCell(row, _COLUMN_REF)
        self.scrollToItem(self.item(row, _COLUMN_REF))

    def _segment_at(self, t_seconds: float) -> tuple[str, int] | None:
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
        self.seek_requested.emit(start)

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


def _card_text(card: dict[str, Any]) -> str:
    text = str(card.get("full_text") or card.get("text") or "")
    return text.splitlines()[0] if text else ""


def _as_float(value: Any, *, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default

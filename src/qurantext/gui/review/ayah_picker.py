"""The ayah picker: which surah and which ayat a lecture card shows.

Detection follows recitation, so it misses the ayah a teacher goes back to and
talks about without reciting it, and it can match a teacher's return to an
earlier ayah to the wrong one. The person then says which ayat the card is
about, and this dialog is where they say it: a surah, a first and a last ayah,
and under them the exact text the card will show.

The preview is the point of the dialog. A card names a reference and its text
always comes from the store (``data.quran_db.ayah_range_card``, the same
function the session builds the card with), so what the person reads here is
what the video draws, line for line. Nothing typed ever becomes Quran text.

The store is read once on opening for the surah list and ayah counts. Each
preview opens its own short connection: a dialog left open should not hold
the file. A store that is missing or unreadable is said in the preview, and
OK stays off, since no card can be made without it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from qurantext.config.paths import DEFAULT_FONT_PATH, QURAN_DB_PATH
from qurantext.data.quran_db import ayah_range_card, connect, list_surahs
from qurantext.gui.i18n import plain_title, t, tn
from qurantext.gui.surahs import surah_label
from qurantext.jobs.project import SURAH_COUNT

__all__ = ["PREVIEW_LINES", "AyahPicker"]

#: How many ayat the preview shows before it says how many more there are.
PREVIEW_LINES = 5

#: The preview's text size against the window's: Quran text is read closely here.
_PREVIEW_SCALE = 1.4

#: The bundled Quran face's family once registered with Qt ("" when it could not be).
_quran_family: str | None = None


def _quran_font_family() -> str:
    """The bundled Qaloon face's family, registered on first use; "" when it cannot be.

    The card in the video is drawn in this face, so the preview reads the
    same. It has no Latin letters; Qt draws those (the "…and 3 more" line)
    from the window's own font.
    """
    global _quran_family
    if _quran_family is None:
        font_id = QFontDatabase.addApplicationFont(str(DEFAULT_FONT_PATH))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id != -1 else []
        _quran_family = families[0] if families else ""
    return _quran_family


def _read_store(db_path: Path) -> dict[int, tuple[str, int]] | None:
    """Each surah's name and ayah count from the store, or None when it cannot be read."""
    try:
        conn = connect(db_path)
    except (OSError, sqlite3.Error):
        return None
    try:
        rows = list_surahs(conn)
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    surahs = {int(row["surah_num"]): (str(row["name"]), int(row["ayah_count"])) for row in rows}
    return surahs if len(surahs) == SURAH_COUNT else None


class AyahPicker(QDialog):
    """Choose a surah and an ayah range, and see the card's text before saying OK."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        surah: int,
        from_ayah: int = 1,
        to_ayah: int | None = None,
        db_path: Path = QURAN_DB_PATH,
    ) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._surahs = _read_store(db_path)
        #: Whether the person set the last ayah themselves; until then it follows the first.
        #: A range handed in (a card's 7–9) counts as set: moving its start keeps its end.
        self._to_set = to_ayah is not None and to_ayah != from_ayah
        #: True while the dialog itself moves the spins, so that is not read as the person's.
        self._syncing = False
        self.setWindowTitle(plain_title(t("ayah_picker.title")))
        self._build()
        self._fill(surah, from_ayah, to_ayah)

    # -- layout -----------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.surah_box = QComboBox()
        names = {num: name for num, (name, _count) in (self._surahs or {}).items()}
        for num in range(1, SURAH_COUNT + 1):
            self.surah_box.addItem(surah_label(num, names), num)
        self.from_spin = QSpinBox()
        self.to_spin = QSpinBox()
        form.addRow(t("ayah_picker.surah"), self.surah_box)
        form.addRow(t("ayah_picker.from"), self.from_spin)
        form.addRow(t("ayah_picker.to"), self.to_spin)
        layout.addLayout(form)

        self.preview = QLabel()
        self.preview.setTextFormat(Qt.TextFormat.PlainText)
        self.preview.setWordWrap(True)
        # Quran text reads from the right in an English window too.
        self.preview.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.preview.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignTop
        )
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        font = QFont(self.font())
        family = _quran_font_family()
        if family:
            font.setFamilies([family, *font.families()])
        if font.pointSizeF() > 0:  # -1 for a font sized in pixels
            font.setPointSizeF(font.pointSizeF() * _PREVIEW_SCALE)
        self.preview.setFont(font)
        self.preview.setMargin(8)
        scroll = QScrollArea()
        scroll.setWidget(self.preview)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumSize(480, 200)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.ok_button: QPushButton = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.surah_box.currentIndexChanged.connect(self._on_surah)
        self.from_spin.valueChanged.connect(self._on_from)
        self.to_spin.valueChanged.connect(self._on_to)

    def _fill(self, surah: int, from_ayah: int, to_ayah: int | None) -> None:
        """Show *surah*'s *from_ayah*–*to_ayah*, clamped to what the surah has."""
        if self._surahs is None:
            # No store: nothing to count ayat by or to preview, so nothing to choose.
            for widget in (self.surah_box, self.from_spin, self.to_spin):
                widget.setEnabled(False)
            blocked = self.surah_box.blockSignals(True)
            try:
                self.surah_box.setCurrentIndex(max(0, self.surah_box.findData(surah)))
            finally:
                self.surah_box.blockSignals(blocked)
            self._preview_unavailable()
            return
        blocked = self.surah_box.blockSignals(True)
        try:
            self.surah_box.setCurrentIndex(max(0, self.surah_box.findData(surah)))
        finally:
            self.surah_box.blockSignals(blocked)
        self._set_range(from_ayah, to_ayah if to_ayah is not None else from_ayah)

    # -- reading ------------------------------------------------------------------

    def choice(self) -> tuple[int, int, int]:
        """``(surah, from_ayah, to_ayah)`` as chosen."""
        return int(self.surah_box.currentData()), self.from_spin.value(), self.to_spin.value()

    # -- keeping the spins and the preview in line ---------------------------------

    def _count(self) -> int:
        surahs = self._surahs or {}
        return surahs.get(int(self.surah_box.currentData()), ("", 1))[1]

    def _set_range(self, first: int, last: int) -> None:
        """Bound both spins by the current surah, put *first*–*last* in them, then preview."""
        count = self._count()
        first = min(max(1, first), count)
        last = min(max(first, last), count)
        self._syncing = True
        try:
            self.from_spin.setRange(1, count)
            self.from_spin.setValue(first)
            # The last ayah is never before the first: the spin will not go there.
            self.to_spin.setRange(first, count)
            self.to_spin.setValue(last)
        finally:
            self._syncing = False
        self._show_preview()

    def _on_surah(self, _index: int) -> None:
        self._set_range(self.from_spin.value(), self.to_spin.value())

    def _on_from(self, first: int) -> None:
        if self._syncing:
            return
        last = self.to_spin.value() if self._to_set else first
        self._set_range(first, last)

    def _on_to(self, _last: int) -> None:
        if self._syncing:
            return
        self._to_set = True
        self._show_preview()

    def _show_preview(self) -> None:
        """The card's text for the chosen range, the first few ayat of a long one."""
        if self._surahs is None:
            self._preview_unavailable()  # never a preview, nor OK, from a store not read
            return
        surah, first, last = self.choice()
        try:
            conn = connect(self._db_path)
        except (OSError, sqlite3.Error):
            self._preview_unavailable()
            return
        try:
            text = ayah_range_card(conn, surah, first, last)["full_text"]
        except (ValueError, sqlite3.Error):
            # The store changed or is damaged under the dialog; a card cannot be made from it.
            self._preview_unavailable()
            return
        finally:
            conn.close()
        lines = text.split("\n")
        if len(lines) > PREVIEW_LINES:
            more = len(lines) - PREVIEW_LINES
            lines = [*lines[:PREVIEW_LINES], tn("ayah_picker.more", more)]
        self.preview.setText("\n".join(lines))
        self.ok_button.setEnabled(True)

    def _preview_unavailable(self) -> None:
        self.preview.setText(t("ayah_picker.no_store"))
        self.ok_button.setEnabled(False)

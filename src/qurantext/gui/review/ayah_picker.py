from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
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

from qurantext.config.paths import QURAN_DB_PATH
from qurantext.data.quran_db import ayah_range_card, connect, list_surahs
from qurantext.gui.i18n import plain_title, t, tn
from qurantext.gui.quran_face import with_quran_face
from qurantext.gui.surahs import surah_label
from qurantext.gui.widgets import make_primary
from qurantext.jobs.project import SURAH_COUNT

__all__ = ["PREVIEW_LINES", "AyahPicker"]

PREVIEW_LINES = 5

_PREVIEW_SCALE = 1.4


def _read_store(db_path: Path) -> dict[int, tuple[str, int]] | None:
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
        self._to_set = to_ayah is not None and to_ayah != from_ayah
        self._syncing = False
        self.setWindowTitle(plain_title(t("ayah_picker.title")))
        self._build()
        self._fill(surah, from_ayah, to_ayah)

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
        self.preview.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.preview.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignTop
        )
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        font = QFont(with_quran_face(self.font()))
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
        make_primary(self.ok_button)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.surah_box.currentIndexChanged.connect(self._on_surah)
        self.from_spin.valueChanged.connect(self._on_from)
        self.to_spin.valueChanged.connect(self._on_to)

    def _fill(self, surah: int, from_ayah: int, to_ayah: int | None) -> None:
        if self._surahs is None:
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

    def choice(self) -> tuple[int, int, int]:
        return int(self.surah_box.currentData()), self.from_spin.value(), self.to_spin.value()

    def _count(self) -> int:
        surahs = self._surahs or {}
        return surahs.get(int(self.surah_box.currentData()), ("", 1))[1]

    def _set_range(self, first: int, last: int) -> None:
        count = self._count()
        first = min(max(1, first), count)
        last = min(max(first, last), count)
        self._syncing = True
        try:
            self.from_spin.setRange(1, count)
            self.from_spin.setValue(first)
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
        if self._surahs is None:
            self._preview_unavailable()
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

"""The studied-surah picker: "Detect automatically", then the 114 surahs.

A lecture's ayah cards keep to the surah it studies
(``core.video_common.cards_on_screen``). The new-job screen and the review
window both offer the choice, and both fill their picker here, so the two lists
read the same and hold the same data: None for "detect", else the surah number.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QComboBox

from qurantext.config.paths import QURAN_DB_PATH
from qurantext.data import quran_db
from qurantext.gui.i18n import t
from qurantext.jobs.project import SURAH_COUNT

__all__ = ["fill_studied_surah_box", "select_studied_surah", "stored_surah_names", "surah_label"]


def stored_surah_names(db_path: Path = QURAN_DB_PATH) -> dict[int, str]:
    """Surah names from the built store, or none when it is not there.

    Read-only: the review window has no business building the store, and a
    picker without names still works (each surah is listed by its number).
    The work is :func:`qurantext.data.quran_db.stored_surah_names`, which the
    job layer calls without Qt.
    """
    return quran_db.stored_surah_names(db_path)


def surah_label(num: int, names: dict[int, str]) -> str:
    """``25. الفرقان``, or ``Surah 25`` when the name is not known."""
    name = names.get(num)
    return t("surah.item", num=num, name=name) if name else t("surah.number", num=num)


def fill_studied_surah_box(box: QComboBox, names: dict[int, str]) -> None:
    """Put "Detect automatically" and the 114 surahs in *box*, keeping its selection."""
    current = box.currentData() if box.count() else None
    blocked = box.blockSignals(True)
    try:
        box.clear()
        box.addItem(t("surah.detect"), None)
        for num in range(1, SURAH_COUNT + 1):
            box.addItem(surah_label(num, names), num)
        select_studied_surah(box, current)
    finally:
        box.blockSignals(blocked)


def select_studied_surah(box: QComboBox, surah: int | None) -> None:
    """Show *surah* in *box* (None: "Detect automatically"); an unknown one reads as detect."""
    index = box.findData(surah) if surah is not None else 0
    box.setCurrentIndex(max(0, index))

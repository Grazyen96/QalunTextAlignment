"""Correct the subtitles before rendering.

Two different things are edited here and the difference is the whole point.

**Recognised speech** is editable in full. It is wrong often enough that the
code which builds those cues says so in its own docstring, and the Phase 2
prototype showed the recogniser can drop seconds of audio outright.

**Quran text is not editable.** A card records *which* ayah and *when*; the
canonical text is looked up from the store at render time. Correcting a
detection means changing the reference or the timing, never the characters. The
text column is read-only for that reason, not as an oversight.

The warnings strip lists stretches of speech-level audio that no word covers.
That check reads the waveform and needs no model, which matters because the
alignment prototype found an aligner's own confidence is *higher* where it is
wrong. Confidence cannot point a reviewer at the problem; this can.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from qurantext.core.coverage import find_uncovered_speech
from qurantext.core.subtitles import card_ref
from qurantext.jobs.project import CaptionCue, Project, save_project

__all__ = ["SubtitleEditor"]

_MAX_SECONDS = 24 * 60 * 60


class SubtitleEditor(QWidget):
    """Edit a project's captions and confirm its ayah cards."""

    #: Emitted after the project is written back to disk.
    saved = Signal(object)

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Check the subtitles")
        self._build()
        self._load()

    # -- construction ---------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        self.warnings.setVisible(False)
        self.warnings.setStyleSheet(
            "QLabel { background: palette(alternate-base); border: 1px solid palette(mid);"
            " border-radius: 4px; padding: 8px; }"
        )
        layout.addWidget(self.warnings)

        self.tabs = QTabWidget()

        self.captions_table = _table(["Start", "End", "Text"])
        self.captions_table.itemChanged.connect(self._caption_edited)
        self.tabs.addTab(
            _with_hint(
                self.captions_table,
                "Recognised speech. Edit the text and the timings freely — this is what "
                "gets corrected.",
            ),
            "Subtitles",
        )

        self.cards_table = _table(["Start", "End", "Ayah", "Text (locked)"])
        self.tabs.addTab(
            _with_hint(
                self.cards_table,
                "Quran text is not editable here. Change which ayah or when it shows; the "
                "certified text is read from the store when the video is rendered.",
            ),
            "Ayat",
        )

        layout.addWidget(self.tabs)

        buttons = QHBoxLayout()
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(self._remove_selected)
        self.check_button = QPushButton("Check against the audio")
        self.check_button.clicked.connect(self.check_coverage)
        self.save_button = QPushButton("Save")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.remove_button)
        buttons.addWidget(self.check_button)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

    # -- loading --------------------------------------------------------------

    def _load(self) -> None:
        self._loading = True
        try:
            self._fill_captions()
            self._fill_cards()
        finally:
            self._loading = False
        # Open on whichever pane has something to correct.
        self.tabs.setCurrentIndex(0 if self.project.captions else 1)

    def _fill_captions(self) -> None:
        table = self.captions_table
        table.setRowCount(len(self.project.captions))
        for row, cue in enumerate(self.project.captions):
            table.setCellWidget(row, 0, _seconds_box(cue.start, self._caption_time_edited, row, 0))
            table.setCellWidget(row, 1, _seconds_box(cue.end, self._caption_time_edited, row, 1))
            item = QTableWidgetItem(cue.text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 2, item)
        table.resizeColumnsToContents()

    def _fill_cards(self) -> None:
        table = self.cards_table
        cards = self.project.cards
        table.setRowCount(len(cards))
        for row, card in enumerate(cards):
            table.setCellWidget(
                row,
                0,
                _seconds_box(_number(card.get("start_time")), self._card_time_edited, row, 0),
            )
            table.setCellWidget(
                row, 1, _seconds_box(_number(card.get("end_time")), self._card_time_edited, row, 1)
            )
            ref = QTableWidgetItem(card_ref(card))
            ref.setFlags(ref.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 2, ref)

            text = QTableWidgetItem(_first_line(card))
            # Locked: the canonical text comes from the store, never from here.
            text.setFlags(text.flags() & ~Qt.ItemFlag.ItemIsEditable)
            text.setToolTip("Quran text is read from the store and cannot be edited.")
            table.setItem(row, 3, text)
        table.resizeColumnsToContents()

    # -- editing --------------------------------------------------------------

    def _caption_edited(self, item: QTableWidgetItem) -> None:
        if getattr(self, "_loading", False) or item.column() != 2:
            return
        row = item.row()
        if 0 <= row < len(self.project.captions):
            # Word timings describe the old words, so editing the text drops them
            # rather than leaving a karaoke highlight disagreeing with the line.
            self.project.captions[row] = self.project.captions[row].edited(item.text())

    def _caption_time_edited(self, row: int, column: int, value: float) -> None:
        if getattr(self, "_loading", False) or not 0 <= row < len(self.project.captions):
            return
        cue = self.project.captions[row]
        start, end = (value, cue.end) if column == 0 else (cue.start, value)
        self.project.captions[row] = CaptionCue(
            start=start, end=max(end, start), text=cue.text, words=cue.words
        )

    def _card_time_edited(self, row: int, column: int, value: float) -> None:
        if getattr(self, "_loading", False) or not 0 <= row < len(self.project.cards):
            return
        key = "start_time" if column == 0 else "end_time"
        self.project.cards[row][key] = value

    def _remove_selected(self) -> None:
        """Drop a false positive. Removing a card never edits its text."""
        if self.tabs.currentIndex() == 0:
            table, items = self.captions_table, self.project.captions
        else:
            table, items = self.cards_table, self.project.cards
        rows = sorted({index.row() for index in table.selectedIndexes()}, reverse=True)
        if not rows:
            QMessageBox.information(self, "Nothing selected", "Select a row to remove.")
            return
        for row in rows:
            if 0 <= row < len(items):
                del items[row]
        self._load()

    # -- checking and saving --------------------------------------------------

    def check_coverage(self) -> list[str]:
        """Report recitation the timings do not cover, read off the waveform."""
        audio = Path(self.project.audio)
        if not audio.is_file():
            self._show_warnings([f"Audio file not found: {audio}"])
            return []
        words = [
            timing for card in self.project.cards for timing in (card.get("word_timings") or [])
        ]
        if not words:
            self._show_warnings(
                ["These cards carry no word timings, so there is nothing to check."]
            )
            return []
        try:
            gaps = find_uncovered_speech(audio, words)
        except (RuntimeError, OSError) as error:
            self._show_warnings([f"Could not read the audio: {error}"])
            return []

        if not gaps:
            self._show_warnings(["Every stretch of speech-level audio is covered by a word."])
            return []
        messages = [gap.describe() for gap in gaps]
        self._show_warnings(
            [
                f"{len(gaps)} stretch(es) of recitation carry no word. Confirm them by ear:",
                *messages,
            ]
        )
        return messages

    def _show_warnings(self, lines: list[str]) -> None:
        self.warnings.setText("\n".join(lines))
        self.warnings.setVisible(bool(lines))

    def save(self) -> Path | None:
        """Write the project back, so the corrections survive the next render."""
        destination = self.project.path
        if destination is None:
            QMessageBox.warning(
                self, "Nowhere to save", "This project has no file to write back to."
            )
            return None
        path = save_project(self.project, destination)
        self.saved.emit(self.project)
        return path


# --- small helpers ------------------------------------------------------------


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.horizontalHeader().setStretchLastSection(True)
    table.verticalHeader().setVisible(False)
    return table


def _with_hint(widget: QWidget, hint: str) -> QWidget:
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 6, 0, 0)
    label = QLabel(hint)
    label.setWordWrap(True)
    layout.addWidget(label)
    layout.addWidget(widget)
    return wrapper


def _seconds_box(value: float, slot, row: int, column: int) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(2)
    box.setSingleStep(0.1)
    box.setRange(0.0, _MAX_SECONDS)
    box.setSuffix(" s")
    box.setValue(float(value))
    box.valueChanged.connect(lambda v, r=row, c=column: slot(r, c, v))
    return box


def _number(value) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _first_line(card: dict) -> str:
    text = str(card.get("full_text") or card.get("text") or "")
    return text.splitlines()[0] if text else ""

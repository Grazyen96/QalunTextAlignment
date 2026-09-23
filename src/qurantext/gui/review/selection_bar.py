"""The selected word, its times, and the buttons that retime it by small steps.

The bar only shows and asks: a button press becomes ``nudge_requested`` or
``snap_requested``, and the window applies it through the session like any
other edit.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from qurantext.gui.i18n import t
from qurantext.gui.review.session import TimelineWord

__all__ = ["NUDGE_S", "SelectionBar"]

#: What the −/+ buttons move an edge by, in seconds.
NUDGE_S = 0.05


class SelectionBar(QWidget):
    """Word text and times, with −50 ms, +50 ms and Snap to playhead."""

    #: A nudge button was pressed; carries the step in seconds (negative moves earlier).
    nudge_requested = Signal(float)
    #: "Snap to playhead" was pressed.
    snap_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.minus_button = QPushButton(t("review.minus"))
        self.plus_button = QPushButton(t("review.plus"))
        self.snap_button = QPushButton(t("review.snap"))
        row.addWidget(self.label, 1)
        for button in (self.minus_button, self.plus_button, self.snap_button):
            row.addWidget(button)
        self.minus_button.clicked.connect(lambda: self.nudge_requested.emit(-NUDGE_S))
        self.plus_button.clicked.connect(lambda: self.nudge_requested.emit(NUDGE_S))
        self.snap_button.clicked.connect(self.snap_requested)
        self.show_word(None)

    def show_word(self, word: TimelineWord | None) -> None:
        """Describe *word*, or invite a selection when there is none."""
        for button in (self.minus_button, self.plus_button, self.snap_button):
            button.setEnabled(word is not None)
        if word is None:
            self.label.setText(t("review.no_selection"))
            return
        self.label.setText(
            t("review.selected", word=word.text, start=f"{word.start:.2f}", end=f"{word.end:.2f}")
        )

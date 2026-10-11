"""The selected word, its times, and the buttons that retime it by small steps.

The bar only shows and asks: a button press becomes ``nudge_requested`` or
``snap_requested``, and the window applies it through the session like any
other edit.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from qurantext.gui.i18n import t, time_span
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
        # The buttons move time, and the timeline runs right to left in every
        # language: "earlier" (−50 ms) sits on the right, the side of the past,
        # so the row reads "Snap | +50 ms | −50 ms" from the left. The row is
        # pinned left to right and filled in that order, not pinned right to
        # left: a right-to-left button would lay "−50 ms" out as "ms −50".
        # The label outside mirrors with the language.
        self.nudge_row = QWidget()
        self.nudge_row.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        nudges = QHBoxLayout(self.nudge_row)
        nudges.setContentsMargins(0, 0, 0, 0)
        on_screen = (self.snap_button, self.plus_button, self.minus_button)
        # Tab walks the row the way the interface reads: from the left in
        # English (Snap, +, −), from the right in Arabic (−, +, Snap). Qt
        # chains the buttons in the order they join the row, and
        # QWidget.setTabOrder will not move one that already leads it, so they
        # join in reading order before the layout places them. A review is
        # built in one language and rebuilt to change it, so this is decided once.
        reading = on_screen[::-1] if self.isRightToLeft() else on_screen
        for button in reading:
            button.setParent(self.nudge_row)
        for button in on_screen:
            nudges.addWidget(button)
        row.addWidget(self.nudge_row)
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
        span = time_span(word.start, word.end, sep=" → ")
        self.label.setText(t("review.selected", word=word.text, span=span))

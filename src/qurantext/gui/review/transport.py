"""The row under the timeline: play, step, the clock, the rate, and the nudges.

The buttons only ask; the window turns each signal into a session call. The
nudge chevrons point the way the edge moves on the always-right-to-left
timeline, so they are not mirrored with the language.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QWidget

from qurantext.gui import theme
from qurantext.gui.i18n import clock, t
from qurantext.gui.icons import set_icon
from qurantext.gui.review.selection_bar import NUDGE_S

__all__ = ["Transport"]


class Transport(QWidget):
    """See the module docstring."""

    #: Play or pause was pressed.
    play_toggled = Signal()
    #: Previous (−1) or next (+1) word was pressed.
    step_requested = Signal(int)
    #: A rate was chosen by click (not by :meth:`set_rate`).
    rate_changed = Signal(float)
    #: A nudge button was pressed; carries the step in seconds (negative moves earlier).
    nudge_requested = Signal(float)
    #: "Snap to playhead" was pressed.
    snap_requested = Signal()
    #: "Show ayah… from here" was pressed (lecture reviews only).
    show_ayah_requested = Signal()

    def __init__(self, rates: tuple[float, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SP_8)

        self.prev_word_button = self._button("", "skip-back", t("review.prev_word"))
        self.play_button = self._button(t("review.play"), "play", t("review.play"))
        self.next_word_button = self._button("", "skip-forward", t("review.next_word"))
        self.time_label = QLabel(clock(0.0))
        self.time_label.setFont(theme.font("clock"))
        self.time_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        for widget in (
            self.prev_word_button,
            self.play_button,
            self.next_word_button,
            self.time_label,
        ):
            row.addWidget(widget)

        row.addSpacing(theme.SP_8)
        self._rate_group = QButtonGroup(self)
        self._rate_group.setExclusive(True)
        self.rate_buttons: dict[float, QPushButton] = {}
        for rate in rates:
            button = QPushButton(t("review.rate", rate=rate))
            button.setCheckable(True)
            button.setProperty("segment", True)
            button.setToolTip(t("review.rate_label"))
            self._rate_group.addButton(button)
            self.rate_buttons[rate] = button
            row.addWidget(button)
        self.rate_buttons[rates[0]].setChecked(True)
        self._rate_group.buttonClicked.connect(self._on_rate_clicked)

        row.addSpacing(theme.SP_8)
        # The nudges move time, and the timeline runs right to left in every
        # language, so the row is pinned left to right: a right-to-left button
        # would also lay "−50 ms" out as "ms −50".
        self.nudge_row = QWidget()
        self.nudge_row.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        nudge_row = QHBoxLayout(self.nudge_row)
        nudge_row.setContentsMargins(0, 0, 0, 0)
        nudge_row.setSpacing(theme.SP_4)
        self.plus_button = QPushButton(t("review.plus"))
        set_icon(self.plus_button, "chevron-left", size=16, mirror=False)
        self.snap_button = QPushButton(t("review.snap"))
        set_icon(self.snap_button, "crosshair", size=16)
        self.minus_button = QPushButton(t("review.minus"))
        set_icon(self.minus_button, "chevron-right", size=16, mirror=False)
        # Left to right on screen: +50 (later, moves left) · snap · −50 (earlier, moves right).
        on_screen = (self.plus_button, self.snap_button, self.minus_button)
        # Tab walks the row the way the interface reads: from the left in
        # English, from the right in Arabic. Qt chains the buttons in the order
        # they join the row, so they join in reading order before the layout
        # places them.
        reading = on_screen[::-1] if self.isRightToLeft() else on_screen
        for button in reading:
            button.setParent(self.nudge_row)
        for button in on_screen:
            nudge_row.addWidget(button)
        row.addWidget(self.nudge_row)

        self.show_ayah_button = QPushButton(t("review.show_ayah"))
        self.show_ayah_button.setToolTip(t("review.show_ayah.tip"))
        set_icon(self.show_ayah_button, "book-open", size=16)
        row.addSpacing(theme.SP_8)
        row.addWidget(self.show_ayah_button)
        row.addStretch(1)

        self.prev_word_button.clicked.connect(lambda: self.step_requested.emit(-1))
        self.next_word_button.clicked.connect(lambda: self.step_requested.emit(1))
        self.play_button.clicked.connect(lambda: self.play_toggled.emit())
        self.minus_button.clicked.connect(lambda: self.nudge_requested.emit(-NUDGE_S))
        self.plus_button.clicked.connect(lambda: self.nudge_requested.emit(NUDGE_S))
        self.snap_button.clicked.connect(lambda: self.snap_requested.emit())
        self.show_ayah_button.clicked.connect(lambda: self.show_ayah_requested.emit())
        self.set_playing(False)
        self.set_selection(False)
        self.set_lecture(False)

    @staticmethod
    def _button(text: str, icon_name: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        set_icon(button, icon_name)
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        return button

    def _on_rate_clicked(self, button: QPushButton) -> None:
        for rate, own in self.rate_buttons.items():
            if own is button:
                self.rate_changed.emit(rate)
                return

    def set_playing(self, playing: bool) -> None:
        """Show the button that would pause (*playing*) or play."""
        set_icon(self.play_button, "pause" if playing else "play")
        self.play_button.setText(t("review.pause") if playing else t("review.play"))
        self.play_button.setAccessibleName(self.play_button.text())
        self.play_button.setToolTip(
            t("review.tip", action=self.play_button.text(), keys=t("review.key_space"))
        )

    def set_time(self, seconds: float) -> None:
        """Show the playhead at *seconds*."""
        self.time_label.setText(clock(seconds))

    def set_rate(self, rate: float) -> None:
        """Check *rate*'s button without emitting :attr:`rate_changed`."""
        button = self.rate_buttons.get(rate)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def set_selection(self, has: bool) -> None:
        """Enable the nudges only while a word is selected."""
        for button in (self.minus_button, self.plus_button, self.snap_button):
            button.setEnabled(has)

    def set_lecture(self, lecture: bool) -> None:
        """Offer "Show ayah… from here" on lecture reviews only."""
        self.show_ayah_button.setVisible(lecture)

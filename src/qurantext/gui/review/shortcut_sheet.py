"""Every key the review window answers to, on one sheet, opened with ?."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QGridLayout, QLabel, QVBoxLayout, QWidget

from qurantext.gui import theme
from qurantext.gui.i18n import plain_title, t
from qurantext.gui.widgets import SectionHeader

__all__ = ["BINDINGS", "ShortcutSheet", "hint_html"]

#: ``(group, keys as shown, i18n key of the action)``; the window's bindings are checked against it.
BINDINGS: tuple[tuple[str, str, str], ...] = (
    ("playback", "Space", "review.key.play"),
    ("playback", "←", "review.key.next_word"),
    ("playback", "→", "review.key.prev_word"),
    ("playback", "", "review.key.scrub"),
    ("editing", "[", "review.key.set_start"),
    ("editing", "]", "review.key.set_end"),
    ("editing", ",", "review.key.nudge_later"),
    ("editing", ".", "review.key.nudge_earlier"),
    ("editing", "Shift+, / Shift+.", "review.key.nudge_fine"),
    ("editing", "Shift+drag", "review.key.ripple"),
    ("editing", "Ctrl+drag", "review.key.detach"),
    ("editing", "", "review.key.change_ayah"),
    ("editing", "Ctrl+Z", "review.key.undo"),
    ("editing", "Ctrl+Shift+Z", "review.key.redo"),
    ("file", "Ctrl+S", "review.key.save"),
    ("file", "?", "review.key.sheet"),
)


def hint_html() -> str:
    """The status bar's short line, with a link that opens the sheet."""
    return t("review.hint")


class ShortcutSheet(QDialog):
    """Three groups in a two-column grid: the keys, then what they do."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(plain_title(t("review.shortcuts.title")))
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        column = QVBoxLayout(self)
        column.setSpacing(theme.SP_12)
        self._rows: list[tuple[str, str]] = []
        for group in ("playback", "editing", "file"):
            column.addWidget(SectionHeader(t(f"review.shortcuts.{group}")))
            grid = QGridLayout()
            grid.setHorizontalSpacing(theme.SP_16)
            grid.setVerticalSpacing(theme.SP_4)
            row = 0
            for own_group, keys, key in BINDINGS:
                if own_group != group:
                    continue
                keys_label = QLabel(keys)
                keys_label.setFont(theme.font("clock"))
                keys_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
                action = QLabel(t(key))
                action.setWordWrap(True)
                grid.addWidget(keys_label, row, 0, Qt.AlignmentFlag.AlignTop)
                grid.addWidget(action, row, 1)
                self._rows.append((keys, t(key)))
                row += 1
            grid.setColumnStretch(1, 1)
            column.addLayout(grid)
        column.addStretch(1)

    def rows(self) -> list[tuple[str, str]]:
        return list(self._rows)

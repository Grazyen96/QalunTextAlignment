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
    """Three groups in a two-column grid: the keys, then what they do.

    The action texts wrap, and a grid gives a wrapped label only one line of
    height unless told otherwise, so each row is given the height its text
    takes at the narrowest the sheet can be (:data:`MIN_WIDTH`); a wider sheet
    only leaves those rows some room to spare.
    """

    #: The narrowest the sheet gets: wide enough that most actions fit one line.
    MIN_WIDTH = 440

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(plain_title(t("review.shortcuts.title")))
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setMinimumWidth(self.MIN_WIDTH)
        column = QVBoxLayout(self)
        column.setSpacing(theme.SP_12)
        self._rows: list[tuple[str, str]] = []
        #: Each group's grid with its (keys label, action label) rows, top to bottom.
        self.groups: list[tuple[QGridLayout, list[tuple[QLabel, QLabel]]]] = []
        for group in ("playback", "editing", "file"):
            column.addWidget(SectionHeader(t(f"review.shortcuts.{group}")))
            grid = QGridLayout()
            grid.setHorizontalSpacing(theme.SP_16)
            grid.setVerticalSpacing(theme.SP_4)
            labels: list[tuple[QLabel, QLabel]] = []
            for own_group, keys, key in BINDINGS:
                if own_group != group:
                    continue
                shown = _shown_keys(keys)
                keys_label = QLabel(shown)
                keys_label.setFont(theme.font("clock"))
                keys_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
                action = QLabel(t(key))
                action.setWordWrap(True)
                action.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignTop)
                row = len(labels)
                grid.addWidget(keys_label, row, 0, Qt.AlignmentFlag.AlignTop)
                grid.addWidget(action, row, 1)
                labels.append((keys_label, action))
                self._rows.append((shown, t(key)))
            grid.setColumnStretch(1, 1)
            column.addLayout(grid)
            self.groups.append((grid, labels))
        column.addStretch(1)
        self._fit_rows()

    def _fit_rows(self) -> None:
        """Give every row the height its wrapped action text takes at the narrowest sheet.

        The keys column is as wide in every group, so the actions line up down the sheet.
        """
        layout = self.layout()
        margins = layout.contentsMargins()
        inner = self.MIN_WIDTH - margins.left() - margins.right()
        for _grid, labels in self.groups:
            for keys_label, action in labels:
                keys_label.ensurePolished()
                action.ensurePolished()
        keys_width = max(
            (keys.sizeHint().width() for _grid, labels in self.groups for keys, _ in labels),
            default=0,
        )
        for grid, labels in self.groups:
            grid.setColumnMinimumWidth(0, keys_width)
            width = max(1, inner - keys_width - grid.horizontalSpacing())
            for row, (keys_label, action) in enumerate(labels):
                height = max(action.heightForWidth(width), keys_label.sizeHint().height())
                grid.setRowMinimumHeight(row, height)

    def rows(self) -> list[tuple[str, str]]:
        """``(keys as shown, action)`` for every row, in the sheet's order."""
        return list(self._rows)


def _shown_keys(keys: str) -> str:
    """*keys* as the sheet shows them: the space bar named as the play button's tip names it."""
    return keys.replace("Space", t("review.key_space"))

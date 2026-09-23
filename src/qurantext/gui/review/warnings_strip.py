"""The line above the editor that says what needs a person's attention.

Two kinds of thing end up here: notices (the recording is missing, playback is
off, a background read failed) and the coverage check's result — the
stretches of speech no word covers, each with a Jump link to it (the first
few; the rest are counted), or a line saying the check is still running. The
strip hides itself when there is nothing to say.
"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QWidget

from qurantext.core.coverage import UncoveredSpeech
from qurantext.gui.i18n import t

__all__ = ["WarningsStrip"]

#: Gaps listed one per line before the rest are only counted; a long lecture
#: can have dozens, and the strip must not push the editor off the screen.
_MAX_GAP_LINES = 5


class WarningsStrip(QLabel):
    """Notices and uncovered-speech gaps; a gap's Jump link asks to seek there."""

    #: A Jump link was clicked; carries the gap's start in seconds.
    jump_requested = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setVisible(False)
        self._notices: list[str] = []
        #: ``None`` until a coverage check has reported; then its gaps (maybe none).
        self._gaps: list[UncoveredSpeech] | None = None
        #: Whether the recording's levels are being read for a first coverage check.
        self._checking = False
        self.linkActivated.connect(self._on_link)

    def add_notice(self, text: str) -> None:
        """Add *text* as a line, once: the same notice arriving again adds nothing."""
        if text in self._notices:
            return
        self._notices.append(text)
        self._render()

    def set_gaps(self, gaps: list[UncoveredSpeech]) -> None:
        self._gaps = list(gaps)
        self._checking = False
        self._render()

    def set_checking(self, checking: bool) -> None:
        """Say the recording is being checked, until the first result (or *checking* False)."""
        self._checking = checking
        self._render()

    def _render(self) -> None:
        lines = [html.escape(notice) for notice in self._notices]
        if self._gaps:
            lines.append(html.escape(t("review.gaps", count=len(self._gaps))))
            jump = html.escape(t("review.jump"))
            for gap in self._gaps[:_MAX_GAP_LINES]:
                text = t("review.gap", duration=gap.duration, start=gap.start, end=gap.end)
                lines.append(
                    f'&nbsp;&nbsp;{html.escape(text)} <a href="{gap.start:.3f}">{jump}</a>'
                )
            hidden = len(self._gaps) - _MAX_GAP_LINES
            if hidden > 0:
                lines.append(f"&nbsp;&nbsp;{html.escape(t('review.more_gaps', count=hidden))}")
        elif self._gaps is not None:
            lines.append(html.escape(t("review.covered")))
        elif self._checking:
            lines.append(html.escape(t("review.checking")))
        self.setText("<br>".join(lines))
        self.setVisible(bool(lines))

    def _on_link(self, target: str) -> None:
        try:
            self.jump_requested.emit(float(target))
        except ValueError:
            pass

"""The line above the editor that says what needs a person's attention.

Two kinds of thing end up here: notices (the recording is missing, playback is
off, a background read failed, a lecture's chosen surah has no card) and the
coverage check's result — the
stretches of speech no word covers, each with a Jump link to it (the first
few; the rest are counted), or a line saying the check is still running. The
strip hides itself when there is nothing to say.
"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QWidget

from qurantext.core.coverage import UncoveredSpeech
from qurantext.gui.i18n import t, time_span, tn

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
        #: What is wrong with the video's look now; replaced whenever the look is checked again.
        self._look_notices: list[str] = []
        #: Why the cards are empty for the chosen studied surah, while they are.
        self._surah_notice: str | None = None
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

    def set_look_notices(self, texts: list[str]) -> None:
        """Replace the lines about the look: a problem fixed (another image, Reset) leaves."""
        self._look_notices = list(dict.fromkeys(texts))
        self._render()

    def add_look_notice(self, text: str) -> None:
        """Add a line about the look (a render's), until the look is checked again."""
        if text in self._look_notices:
            return
        self._look_notices.append(text)
        self._render()

    def set_surah_notice(self, text: str | None) -> None:
        """Say the chosen studied surah has no card, or (None) stop saying it."""
        if text == self._surah_notice:
            return
        self._surah_notice = text
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
        notices = self._notices + [n for n in self._look_notices if n not in self._notices]
        if self._surah_notice and self._surah_notice not in notices:
            notices.append(self._surah_notice)
        lines = [html.escape(notice) for notice in notices]
        if self._gaps:
            lines.append(html.escape(tn("review.gaps", len(self._gaps))))
            jump = html.escape(t("review.jump"))
            for gap in self._gaps[:_MAX_GAP_LINES]:
                span = time_span(gap.start, gap.end, digits=1)
                text = t("review.gap", duration=gap.duration, span=span)
                lines.append(
                    f'&nbsp;&nbsp;{html.escape(text)} <a href="{gap.start:.3f}">{jump}</a>'
                )
            hidden = len(self._gaps) - _MAX_GAP_LINES
            if hidden > 0:
                lines.append(f"&nbsp;&nbsp;{html.escape(tn('review.more_gaps', hidden))}")
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

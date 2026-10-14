"""What needs a person's attention, under the toolbar, in a card that never moves the body.

Three kinds of thing: notices (the recording is missing, playback is off, a
read failed, the chosen surah has no card, the episode was not made), the
coverage check's result (stretches of speech no word covers, folded behind
a count), and a finished render, with Play and Show in folder. Empty, the
card collapses to a 4 px rule, so the body under it stays where it is.
Dismiss clears news — the render line and the plain notices — never state:
coverage, look, surah and episode notices come back from their checks.
"""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

from qurantext.core.coverage import UncoveredSpeech
from qurantext.gui import theme
from qurantext.gui.i18n import clock, is_rtl, t, time_span, tn
from qurantext.gui.icons import icon, set_icon
from qurantext.gui.jobs import JobOutcome
from qurantext.gui.widgets import Card, repolish

__all__ = ["Banner"]

_MAX_GAP_LINES = 5
_KIND_ICON = {"info": "info", "attention": "circle-alert", "success": "film"}


class Banner(Card):
    """See the module docstring."""

    EMPTY_HEIGHT = 4
    jump_requested = Signal(float)
    play_requested = Signal(object)
    reveal_requested = Signal(object)
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.body.setContentsMargins(theme.SP_12, theme.SP_8, theme.SP_12, theme.SP_8)
        row = QHBoxLayout()
        row.setSpacing(theme.SP_8)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(QSize(20, 20))
        row.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)
        self.text_label = QLabel()
        self.text_label.setWordWrap(True)
        self.text_label.setTextFormat(Qt.TextFormat.RichText)
        self.text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.text_label.linkActivated.connect(self._on_link)
        row.addWidget(self.text_label, 1)
        self.play_button = QPushButton(t("render.play"))
        set_icon(self.play_button, "play", size=16)
        self.reveal_button = QPushButton(t("home.show_in_folder"))
        set_icon(self.reveal_button, "folder", size=16)
        self.dismiss_button = QToolButton()
        self.dismiss_button.setAutoRaise(True)
        self.dismiss_button.setToolTip(t("banner.dismiss"))
        self.dismiss_button.setAccessibleName(t("banner.dismiss"))
        set_icon(self.dismiss_button, "x", size=16)
        for button in (self.play_button, self.reveal_button, self.dismiss_button):
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(row)
        self.play_button.clicked.connect(self._play)
        self.reveal_button.clicked.connect(self._reveal)
        self.dismiss_button.clicked.connect(self.dismiss)

        self._notices: list[str] = []
        self._look_notices: list[str] = []
        self._surah_notice: str | None = None
        self._episode_notice: str | None = None
        self._gaps: list[UncoveredSpeech] | None = None
        self._checking = False
        self._gaps_expanded = False
        self._render_line: str | None = None
        self._render_video: Path | None = None
        self._render_more: list[str] = []
        self._is_empty = True
        self._render()

    # -- the strip's old API ----------------------------------------------------------

    def add_notice(self, text: str) -> None:
        if text not in self._notices:
            self._notices.append(text)
            self._render()

    def set_look_notices(self, texts: list[str]) -> None:
        self._look_notices = list(dict.fromkeys(texts))
        self._render()

    def add_look_notice(self, text: str) -> None:
        if text not in self._look_notices:
            self._look_notices.append(text)
            self._render()

    def set_surah_notice(self, text: str | None) -> None:
        if text != self._surah_notice:
            self._surah_notice = text
            self._render()

    def set_episode_notice(self, text: str | None) -> None:
        text = text or None
        if text != self._episode_notice:
            self._episode_notice = text
            self._render()

    def set_gaps(self, gaps: list[UncoveredSpeech]) -> None:
        self._gaps = list(gaps)
        self._checking = False
        self._render()

    def set_checking(self, checking: bool) -> None:
        self._checking = checking
        self._render()

    # -- the render ----------------------------------------------------------------

    def set_render_done(self, outcome: JobOutcome, duration_s: float | None) -> None:
        """Say the video is ready, with Play and Show in folder; the episode line joins it."""
        name = outcome.video.name if outcome.video is not None else ""
        if duration_s is not None and duration_s > 0:
            self._render_line = t(
                "render.done_banner_timed",
                name=name,
                duration=clock(duration_s, digits=0).split(".")[0],
            )
        else:
            self._render_line = t("render.done_banner", name=name)
        self._render_video = outcome.video
        self._render_more = []
        if outcome.episode_video is not None:
            self._render_more.append(t("review.episode_written", name=outcome.episode_video.name))
        self._render()

    def clear_render(self) -> None:
        self._render_line, self._render_video, self._render_more = None, None, []
        self._render()

    def dismiss(self) -> None:
        """Clear the news; the state (coverage, look, surah, episode) stays."""
        self._notices = []
        self.clear_render()
        self.dismissed.emit()

    # -- gaps ----------------------------------------------------------------------

    @property
    def gaps_expanded(self) -> bool:
        return self._gaps_expanded

    def toggle_gaps(self) -> None:
        self._gaps_expanded = not self._gaps_expanded
        self._render()

    def jump_to(self, target: str) -> None:
        try:
            self.jump_requested.emit(float(target))
        except ValueError:
            pass

    # -- what it says --------------------------------------------------------------

    def lines(self) -> list[str]:
        """Every line as plain text, in the order shown."""
        lines = list(self._notices) + [n for n in self._look_notices if n not in self._notices]
        for extra in (self._surah_notice, self._episode_notice):
            if extra and extra not in lines:
                lines.append(extra)
        if self._render_line:
            lines.append(self._render_line)
            lines.extend(self._render_more)
        return lines

    def kind(self) -> str:
        if self._render_line:
            return "success"
        if self._gaps or self._surah_notice or self._episode_notice or self._look_notices:
            return "attention"
        if self._notices or self._checking or self._gaps is not None:
            return "info"
        return ""

    def text(self) -> str:
        return self.text_label.text()

    def _html(self) -> str:
        parts = [html.escape(line) for line in self.lines()]
        if self._gaps:
            count = len(self._gaps)
            # Folded, the arrow points where the line reads on to.
            arrow = "▾" if self._gaps_expanded else ("◂" if is_rtl() else "▸")
            parts.append(
                f'<a href="gaps">{html.escape(tn("review.gaps_toggle", count))} {arrow}</a>'
            )
            if self._gaps_expanded:
                jump = html.escape(t("review.jump"))
                for gap in self._gaps[:_MAX_GAP_LINES]:
                    span = time_span(gap.start, gap.end, digits=1)
                    text = t("review.gap", duration=gap.duration, span=span)
                    parts.append(
                        f'&nbsp;&nbsp;{html.escape(text)} <a href="{gap.start:.3f}">{jump}</a>'
                    )
                hidden = count - _MAX_GAP_LINES
                if hidden > 0:
                    parts.append(f"&nbsp;&nbsp;{html.escape(tn('review.more_gaps', hidden))}")
        elif self._gaps is not None:
            parts.append(html.escape(t("review.covered")))
        elif self._checking:
            parts.append(html.escape(t("review.checking")))
        return "<br>".join(parts)

    def _render(self) -> None:
        content = self._html()
        self.text_label.setText(content)
        kind = self.kind()
        empty = not content
        self._is_empty = empty
        self.icon_label.setVisible(not empty)
        if not empty:
            role = "accent" if kind in ("info", "success") else "text"
            pixmap = icon(_KIND_ICON.get(kind, "info"), role).pixmap(QSize(20, 20))
            if kind == "attention":
                from PySide6.QtGui import QPainter

                from qurantext.gui.colors import warning_color

                tinted = pixmap.copy()
                painter = QPainter(tinted)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(tinted.rect(), warning_color(self.palette()))
                painter.end()
                pixmap = tinted
            self.icon_label.setPixmap(pixmap)
        has_render = self._render_line is not None and self._render_video is not None
        self.play_button.setVisible(has_render)
        self.reveal_button.setVisible(has_render)
        self.dismiss_button.setVisible(bool(self._notices) or self._render_line is not None)
        self.text_label.setVisible(not empty)
        if self.property("empty") != empty:
            self.setProperty("empty", empty)
            # The sheet reads a property only when it polishes the widget.
            repolish(self)
        if empty:
            self.setFixedHeight(self.EMPTY_HEIGHT)
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
        self.updateGeometry()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        """Draw the kind icon again in a new theme's colours (a label's pixmap is not redrawn)."""
        palette_changed = event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
        )
        if palette_changed and hasattr(self, "_render_more"):  # not while __init__ builds it
            self._render()
        super().changeEvent(event)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(hint.width(), self.EMPTY_HEIGHT) if self._is_empty else hint

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(hint.width(), self.EMPTY_HEIGHT) if self._is_empty else hint

    def _on_link(self, target: str) -> None:
        if target == "gaps":
            self.toggle_gaps()
        else:
            self.jump_to(target)

    def _play(self) -> None:
        if self._render_video is not None:
            self.play_requested.emit(self._render_video)

    def _reveal(self) -> None:
        if self._render_video is not None:
            self.reveal_requested.emit(self._render_video)

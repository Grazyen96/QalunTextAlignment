"""The time ruler over the waveform: ticks and ``mm:ss`` labels, right to left.

The major step is the smallest of :data:`STEPS` whose labels, at the
measured width of the widest one the window shows, do not touch at the
current span and width; the minor step is a fifth of it (a half for 1 and
2 s). A label sits to the left of its tick; one that would leave the ruler
there moves to the tick's right, or is left out if it would touch its
neighbour. The ruler shares the
:class:`Viewport` with the waveform and the strip, so a tick and the bar
under it mean the same moment.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QMouseEvent, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from qurantext.gui import theme
from qurantext.gui.colors import playhead_color
from qurantext.gui.i18n import clock
from qurantext.gui.review.viewport import Viewport

__all__ = ["STEPS", "TimeRuler", "tick_step"]

STEPS = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1200.0, 1800.0, 3600.0)
_LABEL_GAP_PX = 0.0
#: Between a label and its tick, in pixels.
_LABEL_OFFSET_PX = 3.0


def tick_step(span_s: float, width_px: float, label_px: float) -> tuple[float, float]:
    """``(major, minor)`` seconds so that labels *label_px* wide never touch; the largest step when degenerate."""
    if span_s <= 0 or width_px <= 0:
        return STEPS[-1], STEPS[-1] / 5
    px_per_s = width_px / span_s
    for step in STEPS:
        if step * px_per_s >= label_px + _LABEL_GAP_PX:
            return step, (step / 2 if step <= 2 else step / 5)
    return STEPS[-1], STEPS[-1] / 5


def _label(t: float) -> str:
    return clock(t, digits=0).split(".")[0]  # clock(digits=0) yields "mm:ss.0"


class TimeRuler(QWidget):
    """Ticks, labels, a playhead triangle; a click or drag asks to seek."""

    HEIGHT = 24
    seek_requested = Signal(float)

    def __init__(self, viewport: Viewport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setFont(theme.font("clock"))
        self._viewport = viewport
        self._playhead = 0.0
        self._dragging = False
        viewport.changed.connect(self.update)

    def set_playhead(self, t: float) -> None:
        self._playhead = float(t)
        self.update()

    def playhead_x(self) -> float:
        return self._viewport.x_for(self._playhead, self.width())

    def time_at(self, x: float) -> str:
        return clock(max(0.0, self._viewport.t_for(x, self.width())), digits=1)

    def _steps(self) -> tuple[float, float]:
        # The window's latest time has the most digits ("100:00" after 100 minutes).
        metrics = QFontMetrics(self.font())
        latest = _label(self._viewport.start + self._viewport.span)
        label_px = max(metrics.horizontalAdvance("00:00"), metrics.horizontalAdvance(latest))
        return tick_step(self._viewport.span, self.width(), label_px)

    def labels(self) -> list[tuple[float, str]]:
        """``(x, text)`` for each major tick in the window, in time order (so x descends)."""
        major, _ = self._steps()
        start, span = self._viewport.start, self._viewport.span
        first = (start // major) * major
        out = []
        t = first
        while t <= start + span + 1e-9:
            if t >= start - 1e-9:
                out.append((self._viewport.x_for(t, self.width()), _label(t)))
            t += major
        return out

    def label_rects(self) -> list[tuple[QRectF, str]]:
        """Where each label is drawn: left of its tick, else right of it, else not at all.

        In time order, so right to left. A label is moved to its tick's right
        only when the left would leave the ruler, and it is left out when the
        right would leave it too or touch the label drawn before it.
        """
        metrics = QFontMetrics(self.font())
        width, height = self.width(), self.HEIGHT - 10
        out: list[tuple[QRectF, str]] = []
        for x, text in self.labels():
            w = metrics.horizontalAdvance(text)
            rect = QRectF(x - w - _LABEL_OFFSET_PX, 0, w, height)
            if rect.left() < 0:
                rect = QRectF(x + _LABEL_OFFSET_PX, 0, w, height)
                previous = out[-1][0] if out else None
                if rect.right() > width or (
                    previous is not None and rect.right() >= previous.left()
                ):
                    continue
            out.append((rect, text))
        return out

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.seek_requested.emit(self._viewport.t_for(event.position().x(), self.width()))
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if self._dragging:
            self.seek_requested.emit(self._viewport.t_for(event.position().x(), self.width()))
            self.setToolTip("")
            return
        self.setToolTip(self.time_at(event.position().x()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        try:
            tokens = theme.current_tokens()
            palette = self.palette()
            painter.fillRect(self.rect(), palette.window())
            width, height = self.width(), self.height()
            major, minor = self._steps()
            start, span = self._viewport.start, self._viewport.span
            pen_minor = QPen(QColor(tokens.border), 1)
            pen_major = QPen(QColor(tokens.secondary), 1)
            t = (start // minor) * minor
            while t <= start + span + 1e-9:
                x = int(self._viewport.x_for(t, width))
                is_major = abs(t / major - round(t / major)) < 1e-6
                painter.setPen(pen_major if is_major else pen_minor)
                painter.drawLine(x, height - (10 if is_major else 5), x, height - 1)
                t += minor
            painter.setPen(QColor(tokens.secondary))
            for rect, text in self.label_rects():
                painter.drawText(
                    rect, int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter), text
                )
            px = self.playhead_x()
            if 0 <= px <= width:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(playhead_color(palette))
                painter.drawPolygon(
                    QPolygonF([QPointF(px - 5, 0), QPointF(px + 5, 0), QPointF(px, 7)])
                )
            painter.setPen(QPen(QColor(tokens.border), 1))
            painter.drawLine(0, height - 1, width, height - 1)
        finally:
            painter.end()

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from qurantext.core.waveform import Peaks
from qurantext.gui import theme
from qurantext.gui.colors import playhead_color, warning_color
from qurantext.gui.i18n import t
from qurantext.gui.review.viewport import Viewport

__all__ = ["WaveformView", "column_extremes"]

_FAINT_ALPHA = 140
_GAP_FILL_ALPHA = 64
_EDGE_SLACK_PX = 1e-6


class WaveformView(QWidget):
    seek_requested = Signal(float)

    def __init__(self, viewport: Viewport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._viewport = viewport
        self._peaks: Peaks | None = None
        self._missing = False
        self._gaps: list[tuple[float, float]] = []
        self._playhead = 0.0
        self._current: tuple[float, float] | None = None
        self._dragging = False
        viewport.changed.connect(self.update)

    def sizeHint(self):  # noqa: D102 - Qt override, documented by the class
        from PySide6.QtCore import QSize

        return QSize(600, 90)

    @property
    def peaks(self) -> Peaks | None:
        return self._peaks

    def set_peaks(self, peaks: Peaks | None) -> None:
        self._peaks = peaks
        self.update()

    def set_missing(self) -> None:
        self._missing = True
        self.update()

    def placeholder(self) -> str:
        return t("waveform.missing") if self._missing else t("waveform.reading")

    def set_gaps(self, gaps: list[tuple[float, float]]) -> None:
        self._gaps = list(gaps)
        self.update()

    def set_playhead(self, t: float) -> None:
        self._playhead = float(t)
        self.update()

    def set_current_word(self, start: float | None, end: float | None) -> None:
        if start is not None and end is not None:
            self._current = (float(start), float(end))
        else:
            self._current = None
        self.update()

    def _seek_to(self, x: float) -> None:
        self.seek_requested.emit(self._viewport.t_for(x, self.width()))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._seek_to(event.position().x())
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if self._dragging:
            self._seek_to(event.position().x())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        try:
            palette = self.palette()
            tokens = theme.current_tokens()
            painter.fillRect(self.rect(), palette.base())

            width = self.width()
            height = self.height()
            peaks = self._peaks
            if peaks is None or len(peaks.mins) == 0:
                painter.setPen(QColor(tokens.secondary))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.placeholder())
            else:
                self._paint_bars(painter, peaks, width, height)

            attention = warning_color(palette)
            gap_fill = QColor(attention)
            gap_fill.setAlpha(_GAP_FILL_ALPHA)
            painter.setPen(QPen(attention, 1))
            painter.setBrush(gap_fill)
            for gap_start, gap_end in self._gaps:
                left = self._viewport.x_for(gap_end, width)
                right = self._viewport.x_for(gap_start, width)
                # A rect's outline is drawn one pixel past its width, so one less keeps
                # the band on the pixels it covered when it was only filled.
                band_width = max(1, int(right - left))
                painter.drawRect(int(left), 0, band_width - 1, height - 1)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            playhead_x = self._playhead_column(width)
            if playhead_x is not None:
                # A filled rect, not a 2 px pen: the pen's two columns depend on
                # antialiasing and the line's direction; the rect always ends at x.
                painter.fillRect(playhead_x - 1, 0, 2, height, playhead_color(palette))
        finally:
            painter.end()

    def _playhead_column(self, width: int) -> int | None:
        x = self._viewport.x_for(self._playhead, width)
        if not -_EDGE_SLACK_PX <= x <= width + _EDGE_SLACK_PX:
            return None
        return min(max(math.ceil(x) - 1, 0), width - 1)

    def _paint_bars(self, painter: QPainter, peaks: Peaks, width: int, height: int) -> None:
        if width <= 0 or len(peaks.mins) == 0:
            return
        col_min, col_max = column_extremes(peaks, self._viewport.start, self._viewport.span, width)

        strong = QColor(theme.current_tokens().accent)
        faint = QColor(strong)
        faint.setAlpha(_FAINT_ALPHA)
        current = self._current
        mid = height / 2.0
        half = height / 2.0
        tops = (mid - col_max[:width].astype(np.float64) * half).astype(np.int64).tolist()
        bottoms = (mid - col_min[:width].astype(np.float64) * half).astype(np.int64).tolist()
        xs = list(range(width - 1, -1, -1))
        inside = [False] * width
        if current is not None:
            first = self._viewport.t_for(0.5, width)
            step = self._viewport.t_for(1.5, width) - first
            centres = first + step * np.asarray(xs, dtype=np.float64)
            inside = ((centres >= current[0]) & (centres < current[1])).tolist()
        for pen, wanted in ((faint, False), (strong, True)):
            painter.setPen(pen)
            for i in range(width):
                if inside[i] == wanted:
                    painter.drawLine(xs[i], tops[i], xs[i], bottoms[i])


def column_extremes(
    peaks: Peaks, start: float, span: float, width: int
) -> tuple[np.ndarray, np.ndarray]:
    n_bins = len(peaks.mins)
    edges_t = start + (np.arange(width + 1, dtype=np.float64) / width) * span
    edges_idx = np.clip((edges_t * peaks.rate).astype(np.int64), 0, n_bins)
    column_starts = np.clip(edges_idx[:-1], 0, n_bins - 1)
    stop = int(max(edges_idx[-1], column_starts[-1] + 1))
    col_min = np.minimum.reduceat(peaks.mins[:stop], column_starts)
    col_max = np.maximum.reduceat(peaks.maxs[:stop], column_starts)
    return col_min, col_max

"""The recording drawn as a waveform, with gaps and the playhead on top.

One pixel column is one min/max bar, aggregated from whatever peak bins fall
in that column's slice of time — many bins per column when zoomed out, at
most one when zoomed in past the peak resolution. A click or drag anywhere on
the widget asks to seek there; the widget never seeks itself, it only asks
(the window wires ``seek_requested`` to the player and the viewport).

Time runs right to left (see :mod:`.viewport`): the window's start is at the
right edge. The columns are still reduced in time order and only drawn
mirrored, and a gap band's rectangle is spanned from whichever of its two
pixels is further left.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from qurantext.core.waveform import Peaks
from qurantext.gui.colors import playhead_color
from qurantext.gui.i18n import t
from qurantext.gui.review.viewport import Viewport

__all__ = ["WaveformView", "column_extremes"]

_GAP_COLOR = QColor(239, 159, 39, 70)
#: How far past a window edge, in pixels, float rounding may put a time on it.
_EDGE_SLACK_PX = 1e-6


class WaveformView(QWidget):
    """Paints ``Peaks`` against a shared :class:`Viewport`; asks to seek on click/drag."""

    seek_requested = Signal(float)

    def __init__(self, viewport: Viewport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._viewport = viewport
        self._peaks: Peaks | None = None
        #: The recording cannot be read at all, so "Reading…" would never end.
        self._missing = False
        self._gaps: list[tuple[float, float]] = []
        self._playhead = 0.0
        self._dragging = False
        viewport.changed.connect(self.update)

    def sizeHint(self):  # noqa: D102 - Qt override, documented by the class
        from PySide6.QtCore import QSize

        return QSize(600, 90)

    @property
    def peaks(self) -> Peaks | None:
        """The drawn recording, or ``None`` while it is still being read."""
        return self._peaks

    def set_peaks(self, peaks: Peaks | None) -> None:
        """Replace the drawn recording; ``None`` shows the "reading" placeholder."""
        self._peaks = peaks
        self.update()

    def set_missing(self) -> None:
        """Say the recording is not available, instead of waiting to read it."""
        self._missing = True
        self.update()

    def placeholder(self) -> str:
        """What the widget says while it has no waveform to draw."""
        return t("waveform.missing") if self._missing else t("waveform.reading")

    def set_gaps(self, gaps: list[tuple[float, float]]) -> None:
        """Replace the uncovered-speech bands, as ``(start, end)`` seconds."""
        self._gaps = list(gaps)
        self.update()

    def set_playhead(self, t: float) -> None:
        """Move the drawn playhead to *t* seconds."""
        self._playhead = float(t)
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
            painter.fillRect(self.rect(), palette.window())

            width = self.width()
            height = self.height()
            peaks = self._peaks
            if peaks is None or len(peaks.mins) == 0:
                painter.setPen(palette.windowText().color())
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.placeholder())
            else:
                self._paint_bars(painter, peaks, width, height, palette.windowText().color())

            for gap_start, gap_end in self._gaps:
                # The end is the left pixel: later time lies further left.
                left = self._viewport.x_for(gap_end, width)
                right = self._viewport.x_for(gap_start, width)
                painter.fillRect(int(left), 0, max(1, int(right - left)), height, _GAP_COLOR)

            playhead_x = self._playhead_column(width)
            if playhead_x is not None:
                painter.setPen(playhead_color(palette))
                painter.drawLine(playhead_x, 0, playhead_x, height)
        finally:
            painter.end()

    def _playhead_column(self, width: int) -> int | None:
        """The pixel column the playhead is drawn in, or ``None`` outside the window.

        Right to left, ``ceil(x) - 1`` puts pixel column ``p`` over the times
        in ``[t_for(p + 1), t_for(p))``: the same column as the waveform bar
        for that time, and the window's start (``x == width``, where a review
        opens) lands in the last column instead of one past it. The window's
        end (``x == 0``) is drawn too, in column 0: that is where the playhead
        stops when playback reaches the recording's end, with the window
        scrolled as far as it goes. A playhead truly outside
        ``[start, start + span]`` is not drawn at all, as before: pinning it to
        an edge would mark a time the window does not show. The edges allow
        :data:`_EDGE_SLACK_PX` for float rounding, so a playhead at exactly the
        recording's end (whose x can come out as -4e-14) still counts as on it.
        """
        x = self._viewport.x_for(self._playhead, width)
        if not -_EDGE_SLACK_PX <= x <= width + _EDGE_SLACK_PX:
            return None
        return min(max(math.ceil(x) - 1, 0), width - 1)

    def _paint_bars(
        self, painter: QPainter, peaks: Peaks, width: int, height: int, color: QColor
    ) -> None:
        if width <= 0 or len(peaks.mins) == 0:
            return
        col_min, col_max = column_extremes(peaks, self._viewport.start, self._viewport.span, width)

        mid = height / 2.0
        half = height / 2.0
        painter.setPen(color)
        # Column i of the reduction is the i-th slice of time from the window's
        # start, which right to left is the i-th pixel column from the right.
        for i in range(width):
            x = width - 1 - i
            y_top = mid - float(col_max[i]) * half
            y_bottom = mid - float(col_min[i]) * half
            painter.drawLine(x, int(y_top), x, int(y_bottom))


def column_extremes(
    peaks: Peaks, start: float, span: float, width: int
) -> tuple[np.ndarray, np.ndarray]:
    """Each time slice's min and max over the peak bins in it, earliest slice first.

    The *width* slices split ``[start, start+span]`` evenly, in time order;
    the caller decides which pixel column draws which (right to left, the
    first slice is the rightmost column). ``reduceat`` reduces from each index
    to the next, and the last index to the end of the array — so without
    cutting the arrays at the window's end the last slice would fold in the
    whole rest of the recording, and a loud passage far off-screen would show
    as a spike at the window's later edge.
    """
    n_bins = len(peaks.mins)
    edges_t = start + (np.arange(width + 1, dtype=np.float64) / width) * span
    edges_idx = np.clip((edges_t * peaks.rate).astype(np.int64), 0, n_bins)
    column_starts = np.clip(edges_idx[:-1], 0, n_bins - 1)
    # At least one bin past the last column's start, so its reduction is never empty.
    stop = int(max(edges_idx[-1], column_starts[-1] + 1))
    col_min = np.minimum.reduceat(peaks.mins[:stop], column_starts)
    col_max = np.maximum.reduceat(peaks.maxs[:stop], column_starts)
    return col_min, col_max

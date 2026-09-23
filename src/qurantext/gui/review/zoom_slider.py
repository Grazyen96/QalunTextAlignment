"""How much of the recording the timeline shows, as one slider.

A span of seconds is a poor thing to put on a linear slider: the useful range
runs from the whole of an hour-long lecture down to one second, and nearly all
of the interesting stops sit near the narrow end. The slider is therefore
logarithmic — each step divides the span by the same factor — with the whole
recording at the left and :data:`Viewport.MIN_SPAN_S` at the right. It zooms
around the playhead, so what the person is listening to stays in view.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSlider, QWidget

from qurantext.gui.review.viewport import Viewport

__all__ = ["ZoomSlider"]

_STEPS = 100


class ZoomSlider(QSlider):
    """Sets ``viewport.span`` on a log scale, anchored at ``anchor()`` seconds."""

    def __init__(
        self, viewport: Viewport, anchor: Callable[[], float], parent: QWidget | None = None
    ) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setRange(0, _STEPS)
        self._viewport = viewport
        self._anchor = anchor
        self.valueChanged.connect(self._on_value)
        viewport.changed.connect(self._sync)

    def _bounds(self) -> tuple[float, float]:
        widest = self._viewport.duration
        return widest, min(Viewport.MIN_SPAN_S, widest)

    def _on_value(self, value: int) -> None:
        widest, narrowest = self._bounds()
        span = widest * (narrowest / widest) ** (value / _STEPS)
        self._viewport.zoom(self._viewport.span / span, self._anchor())

    def _sync(self) -> None:
        """Show the viewport's current span, without zooming again."""
        widest, narrowest = self._bounds()
        value = 0
        if widest > narrowest:
            fraction = math.log(self._viewport.span / widest) / math.log(narrowest / widest)
            value = round(fraction * _STEPS)
        self.blockSignals(True)
        self.setValue(value)
        self.blockSignals(False)

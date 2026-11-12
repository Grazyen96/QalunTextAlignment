from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSlider, QWidget

from qurantext.gui.review.viewport import Viewport

__all__ = ["ZoomSlider"]

_STEPS = 100


class ZoomSlider(QSlider):
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
        widest, narrowest = self._bounds()
        value = 0
        if widest > narrowest:
            fraction = math.log(self._viewport.span / widest) / math.log(narrowest / widest)
            value = round(fraction * _STEPS)
        self.blockSignals(True)
        self.setValue(value)
        self.blockSignals(False)

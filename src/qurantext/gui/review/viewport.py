from __future__ import annotations

from PySide6.QtCore import QObject, Signal

__all__ = ["Viewport"]


class Viewport(QObject):
    changed = Signal()

    MIN_SPAN_S = 1.0

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.duration = 0.001
        self.start = 0.0
        self.span = self.MIN_SPAN_S

    def set_duration(self, duration: float) -> None:
        new_duration = max(0.001, float(duration))
        if new_duration == self.duration:
            return
        self.duration = new_duration
        self._apply_window(self.start, self.span)

    def set_window(self, start: float, span: float) -> None:
        self._apply_window(start, span)

    def _apply_window(self, start: float, span: float) -> None:
        span = max(self.MIN_SPAN_S, min(float(span), self.duration))
        if span >= self.duration:
            span = self.duration
            start = 0.0
        else:
            start = max(0.0, min(float(start), self.duration - span))
        if start == self.start and span == self.span:
            return
        self.start = start
        self.span = span
        self.changed.emit()

    def zoom(self, factor: float, anchor_t: float) -> None:
        if factor <= 0:
            return
        fraction = (anchor_t - self.start) / self.span if self.span else 0.0
        new_span = max(self.MIN_SPAN_S, min(self.span / factor, self.duration))
        new_start = anchor_t - fraction * new_span
        self._apply_window(new_start, new_span)

    def follow(self, t: float) -> None:
        if self.start <= t < self.start + self.span:
            return
        self._apply_window(t - 0.1 * self.span, self.span)

    def x_for(self, t: float, width: float) -> float:
        if self.span <= 0:
            return float(width)
        return (1.0 - (t - self.start) / self.span) * width

    def t_for(self, x: float, width: float) -> float:
        if width <= 0:
            return self.start
        return self.start + (1.0 - x / width) * self.span

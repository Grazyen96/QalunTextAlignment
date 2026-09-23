"""The visible time window shared by the waveform and the word strip.

Every timeline widget draws the same stretch of the recording, so the mapping
between seconds and pixels lives in one place: change the window here (by
scrolling, zooming or following the playhead) and every widget connected to
:attr:`Viewport.changed` repaints against the new numbers. No widget owns a
`Viewport`'s state; they only read it and ask it to move.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

__all__ = ["Viewport"]


class Viewport(QObject):
    """The window onto the recording: ``[start, start + span)`` seconds.

    ``duration`` is the recording's length; ``start``/``span`` describe what is
    currently visible, with ``span`` clamped to ``[MIN_SPAN_S, duration]`` and
    ``start`` clamped to ``[0, duration - span]``. When ``span`` would exceed
    ``duration`` (a short recording, or zooming out past it), :meth:`set_window`
    sets ``span`` to ``duration`` and ``start`` to ``0`` — the whole recording,
    nothing to scroll. ``changed`` fires only when the window actually moves,
    so a repaint connected to it never runs on a no-op call.
    """

    changed = Signal()

    #: The narrowest window a person can zoom to, in seconds.
    MIN_SPAN_S = 1.0

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.duration = 0.001
        self.start = 0.0
        self.span = self.MIN_SPAN_S

    def set_duration(self, duration: float) -> None:
        """Set the recording's length and re-clamp the current window to it."""
        new_duration = max(0.001, float(duration))
        if new_duration == self.duration:
            return
        self.duration = new_duration
        self._apply_window(self.start, self.span)

    def set_window(self, start: float, span: float) -> None:
        """Move the visible window, clamping *span* then *start* to the recording."""
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
        """Scale ``span`` by 1/*factor*, keeping *anchor_t* under the same pixel.

        *factor* > 1 zooms in (a narrower span); *factor* < 1 zooms out. The
        anchor's fraction across the old window is preserved in the new one, so
        the point the user is pointing at does not jump.
        """
        if factor <= 0:
            return
        fraction = (anchor_t - self.start) / self.span if self.span else 0.0
        new_span = self.span / factor
        new_start = anchor_t - fraction * new_span
        self._apply_window(new_start, new_span)

    def follow(self, t: float) -> None:
        """Keep the playhead visible: page the window when *t* leaves it.

        While *t* stays inside ``[start, start + span)`` nothing happens. When
        it steps outside, the window pages so *t* sits 10 % of the way in from
        the left — enough runway ahead of the playhead to see what is coming.
        """
        if self.start <= t < self.start + self.span:
            return
        self._apply_window(t - 0.1 * self.span, self.span)

    def x_for(self, t: float, width: float) -> float:
        """The pixel column for time *t* in a widget *width* pixels wide."""
        if self.span <= 0:
            return 0.0
        return (t - self.start) / self.span * width

    def t_for(self, x: float, width: float) -> float:
        """The time at pixel column *x* in a widget *width* pixels wide."""
        if width <= 0:
            return self.start
        return self.start + (x / width) * self.span

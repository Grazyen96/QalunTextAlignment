"""Every timed word laid out on the shared timeline, draggable by its edges.

Each word is drawn as a box from its start to its end. A press near a shared
boundary between two words grabs the earlier word's end (retiming a shared
edge moves both words at once); a press near any other edge grabs that edge
alone; a plain press inside a word selects it and asks to seek there; a
shift-press inside a word starts a ripple drag that pushes every later word
by the same amount the pointer travels. An edge dragged with Alt held moves
alone: a shared edge detaches from its neighbour, so a gap can be opened
between two joined words. Every move of a drag is applied from
the state the drag began in, so dragging back undoes what the way out did.
The strip never writes a timing itself — every drag goes through
:class:`ReviewSession`, which is the one place the rules about what an edit
may do live.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFontMetrics,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

from qurantext.gui.review.session import ReviewSession, TimelineWord, WordRef
from qurantext.gui.review.viewport import Viewport

__all__ = ["WordStrip"]

_PLAYHEAD_OUTLINE = QColor(226, 75, 74)
_EDITED_DOT = QColor(239, 159, 39)

#: Below this box width, skip text layout entirely and draw only the box —
#: at deep zoom-out on a long lecture, thousands of boxes are only a
#: fraction of a pixel wide and the label would not be legible anyway.
_MIN_TEXT_WIDTH_PX = 12.0


@dataclass(slots=True)
class _EdgeDrag:
    """An in-progress drag of one word's start or end edge."""

    ref: WordRef
    edge: str  # "start" | "end"
    revision_before: int
    #: False for an Alt-drag: the edge leaves a neighbour it touched behind.
    keep_joined: bool = True


@dataclass(slots=True)
class _RippleDrag:
    """An in-progress shift-drag: the pointer's travel since *t0* is the ripple delta."""

    ref: WordRef
    t0: float
    revision_before: int


class WordStrip(QWidget):
    """Paints ``session.words()`` against a shared :class:`Viewport`; edits by dragging."""

    #: How close (in pixels) a press or the pointer must be to count as "on an edge".
    EDGE_PX = 5

    selection_changed = Signal(object)
    seek_requested = Signal(float)
    edited = Signal()

    def __init__(
        self, viewport: Viewport, session: ReviewSession, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setMouseTracking(True)
        # A child widget never receives ActivationChange or (with the default
        # NoFocus policy) FocusOut, so without this a lost grab — the window
        # deactivating, a modal opening — would go unnoticed mid-drag. A
        # press giving the strip real focus makes Qt deliver a genuine
        # FocusOut when that happens.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._viewport = viewport
        self._session = session
        self._selected: WordRef | None = None
        self._last_edge = "end"
        self._playhead = 0.0
        self._drag: _EdgeDrag | _RippleDrag | None = None
        viewport.changed.connect(self.update)

    def sizeHint(self) -> QSize:  # noqa: D102 - Qt override, documented by the class
        return QSize(600, 34)

    @property
    def selected(self) -> WordRef | None:
        return self._selected

    @property
    def last_edge(self) -> str:
        """The selected word's edge the person last grabbed: ``"start"`` or ``"end"``.

        Keyboard and button nudges move this edge. It is ``"end"`` until an
        edge of the selected word is grabbed, and again whenever the
        selection changes.
        """
        return self._last_edge

    def select(self, ref: WordRef | None) -> None:
        """Select *ref* (or clear the selection with ``None``) and repaint."""
        if ref == self._selected:
            return
        self._selected = ref
        self._last_edge = "end"
        self.selection_changed.emit(ref)
        self.update()

    def set_playhead(self, t: float) -> None:
        """Move the drawn playhead to *t* seconds; the word under it gets a bold outline."""
        self._playhead = float(t)
        self.update()

    def refresh(self) -> None:
        """Repaint from ``session.words()``; call after the session's revision changes.

        A selection whose ref is no longer among the session's words — its
        card or caption was removed, or the undo/redo it came from was
        reverted — can't stay selected, so this drops it first.
        """
        if self._selected is not None:
            try:
                self._session.word(self._selected)
            except IndexError:
                self._selected = None
                self.selection_changed.emit(None)
        self.update()

    def _visible_words(self) -> list[TimelineWord]:
        start = self._viewport.start
        return self._session.words_in(start, start + self._viewport.span)

    # -- hit testing --------------------------------------------------------------

    def _edges(self) -> list[tuple]:
        width = self.width()
        return [
            (tw, self._viewport.x_for(tw.start, width), self._viewport.x_for(tw.end, width))
            for tw in self._visible_words()
        ]

    def _hit_test(self, x: float) -> tuple[str, WordRef] | None:
        """Where a press (or the pointer) at *x* lands, in priority order.

        (1) within :attr:`EDGE_PX` of a boundary shared by two words — grab the
        earlier word's end; (2) within :attr:`EDGE_PX` of any single edge —
        grab that edge; (3) inside a word's body; (4) nothing.
        """
        edges = self._edges()
        for i in range(len(edges) - 1):
            earlier, _, earlier_end = edges[i]
            _, later_start, _ = edges[i + 1]
            if abs(earlier_end - x) <= self.EDGE_PX and abs(later_start - x) <= self.EDGE_PX:
                return "end", earlier.ref
        for tw, x0, x1 in edges:
            if abs(x0 - x) <= self.EDGE_PX:
                return "start", tw.ref
            if abs(x1 - x) <= self.EDGE_PX:
                return "end", tw.ref
        for tw, x0, x1 in edges:
            if x0 <= x <= x1:
                return "body", tw.ref
        return None

    # -- mouse ----------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        x = event.position().x()
        hit = self._hit_test(x)
        if hit is None:
            self.select(None)
            return
        kind, ref = hit
        if kind in ("start", "end"):
            self.select(ref)
            self._last_edge = kind
            revision_before = self._session.revision
            self._session.begin_gesture()
            detach = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            self._drag = _EdgeDrag(ref, kind, revision_before, keep_joined=not detach)
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            return
        # kind == "body"
        self.select(ref)
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            revision_before = self._session.revision
            self._session.begin_gesture()
            t0 = self._viewport.t_for(x, self.width())
            self._drag = _RippleDrag(ref, t0, revision_before)
            return
        self.seek_requested.emit(self._session.word(ref).start)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        # QTest.mouseMove does not reliably report the button as still down on
        # every platform, so the drag is tracked in self._drag rather than by
        # reading event.buttons().
        x = event.position().x()
        if self._drag is None:
            hit = self._hit_test(x)
            if hit is not None and hit[0] in ("start", "end"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.unsetCursor()
            return
        # Each move is applied from the state the drag began in (the session
        # restores it), so the result depends only on where the pointer is now.
        t = self._viewport.t_for(x, self.width())
        if isinstance(self._drag, _EdgeDrag):
            keep_joined = self._drag.keep_joined
            if self._drag.edge == "start":
                self._session.drag_retime(self._drag.ref, start=t, keep_joined=keep_joined)
            else:
                self._session.drag_retime(self._drag.ref, end=t, keep_joined=keep_joined)
        else:
            self._session.drag_ripple(self._drag.ref, t - self._drag.t0)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() != Qt.MouseButton.LeftButton or self._drag is None:
            super().mouseReleaseEvent(event)
            return
        self._finish_drag()

    def _finish_drag(self) -> None:
        """Close an open gesture, however it ends.

        A mouse grab can be lost mid-drag — the window is deactivated, a
        modal dialog opens, the strip is hidden — with no
        ``mouseReleaseEvent`` ever arriving. Left open, the session's gesture
        stays started forever and every later edit merges into that one undo
        step. Every path that can lose the grab funnels through here instead
        of duplicating the release logic.
        """
        if self._drag is None:
            return
        changed = self._session.revision != self._drag.revision_before
        self._session.end_gesture()
        self._drag = None
        self.unsetCursor()
        if changed:
            self.edited.emit()

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt override
        self._finish_drag()
        super().focusOutEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 - Qt override
        self._finish_drag()
        super().hideEvent(event)

    # Not leaveEvent or a changeEvent/ActivationChange override: during a
    # grab the pointer may legitimately leave the widget and come back, and
    # ActivationChange is only ever delivered to a top-level widget anyway —
    # dead code here. focusOutEvent (above) covers the window losing
    # activation instead, now that a press gives the strip real focus.

    # -- painting ---------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        try:
            palette = self.palette()
            painter.fillRect(self.rect(), palette.window())
            width = self.width()
            height = self.height()
            metrics = QFontMetrics(painter.font())
            playhead_ref = self._session.word_at(self._playhead)
            for tw in self._visible_words():
                x0 = self._viewport.x_for(tw.start, width)
                x1 = self._viewport.x_for(tw.end, width)
                if x1 < 0 or x0 > width:
                    continue
                box_width = max(2.0, x1 - x0)
                rect = QRectF(x0, 2.0, box_width, height - 4.0)
                self._paint_word(painter, metrics, rect, tw, tw.ref == playhead_ref, palette)
        finally:
            painter.end()

    def _paint_word(self, painter, metrics, rect, tw, is_under_playhead, palette) -> None:
        selected = tw.ref == self._selected
        if selected:
            painter.fillRect(rect, palette.highlight())

        border_pen = QPen(_PLAYHEAD_OUTLINE if is_under_playhead else palette.mid().color())
        border_pen.setWidth(2 if is_under_playhead else 1)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        if rect.width() < _MIN_TEXT_WIDTH_PX:
            # Too narrow to read at this zoom (thousands of boxes fit in view
            # at once); the box alone is the useful signal, and skipping the
            # text layout is what keeps painting a fully zoomed-out long
            # lecture cheap.
            return

        text_color = palette.highlightedText().color() if selected else palette.windowText().color()
        painter.setPen(text_color)
        elided = metrics.elidedText(
            tw.text, Qt.TextElideMode.ElideRight, max(0, int(rect.width()) - 4)
        )
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), elided)

        if tw.edited:
            radius = 2.5
            center = QPointF(rect.right() - radius - 2, rect.top() + radius + 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_EDITED_DOT)
            painter.drawEllipse(center, radius, radius)

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFont,
    QFontMetrics,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

from qurantext.gui import theme
from qurantext.gui.colors import warning_color
from qurantext.gui.quran_face import with_quran_face
from qurantext.gui.review.session import CARD, ReviewSession, TimelineWord, WordRef
from qurantext.gui.review.viewport import Viewport

__all__ = ["WordStrip"]

_MIN_TEXT_WIDTH_PX = 12.0

#: Held while grabbing a joined edge: the edge leaves its neighbour behind.
#: Ctrl works on every desktop; Alt is taken for moving windows on some Linux ones.
_DETACH = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier


@dataclass(slots=True)
class _EdgeDrag:
    ref: WordRef
    edge: str
    revision_before: int
    keep_joined: bool = True


@dataclass(slots=True)
class _RippleDrag:
    ref: WordRef
    t0: float
    revision_before: int


class WordStrip(QWidget):
    EDGE_PX = 8
    HANDLE_PX = 6

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
        self._last_edge = "start"
        self._playhead = 0.0
        self._drag: _EdgeDrag | _RippleDrag | None = None
        self._hover: tuple[str, WordRef] | None = None
        viewport.changed.connect(self.update)

    def sizeHint(self) -> QSize:  # noqa: D102 - Qt override, documented by the class
        return QSize(600, 44)

    def minimumSizeHint(self) -> QSize:  # noqa: D102 - Qt override, documented by the class
        return QSize(200, 40)

    @property
    def selected(self) -> WordRef | None:
        return self._selected

    @property
    def last_edge(self) -> str:
        return self._last_edge

    @property
    def hovered_edge(self) -> tuple[str, WordRef] | None:
        return self._hover

    def painted_handle(self) -> tuple[str, WordRef] | None:
        if isinstance(self._drag, _EdgeDrag):
            return self._drag.edge, self._drag.ref
        if self._hover is not None:
            return self._hover
        if self._selected is not None:
            return self._last_edge, self._selected
        return None

    def select(self, ref: WordRef | None) -> None:
        if ref == self._selected:
            return
        self._selected = ref
        self._last_edge = "start"
        self.selection_changed.emit(ref)
        self.update()

    def set_playhead(self, t: float) -> None:
        self._playhead = float(t)
        self.update()

    def refresh(self) -> None:
        if self._selected is not None:
            try:
                self._session.word(self._selected)
            except IndexError:
                self._selected = None
                self.selection_changed.emit(None)
        self.update()

    def font_for(self, word: TimelineWord) -> QFont:
        """The font *word* is drawn in: a card's in the Quran face, a caption's in the strip's.

        A card's words are the mushaf's, whose open tanween only the Quran face
        draws; a caption's are recognised speech.
        """
        if word.ref.kind == CARD:
            return with_quran_face(self.font())
        return self.font()

    def _visible_words(self) -> list[TimelineWord]:
        start = self._viewport.start
        return self._session.words_in(start, start + self._viewport.span)

    def _edges(self) -> list[tuple]:
        width = self.width()
        return [
            (tw, self._viewport.x_for(tw.start, width), self._viewport.x_for(tw.end, width))
            for tw in self._visible_words()
        ]

    def _hit_test(self, x: float) -> tuple[str, WordRef] | None:
        edges = self._edges()
        for i in range(len(edges) - 1):
            earlier, _, earlier_end = edges[i]
            _, later_start, _ = edges[i + 1]
            if abs(earlier_end - x) <= self.EDGE_PX and abs(later_start - x) <= self.EDGE_PX:
                return "end", earlier.ref
        for tw, x_start, x_end in edges:
            if abs(x_start - x) <= self.EDGE_PX:
                return "start", tw.ref
            if abs(x_end - x) <= self.EDGE_PX:
                return "end", tw.ref
        for tw, x_start, x_end in edges:
            if x_end <= x <= x_start:
                return "body", tw.ref
        return None

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
            detach = bool(event.modifiers() & _DETACH)
            self._drag = _EdgeDrag(ref, kind, revision_before, keep_joined=not detach)
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            return
        self.select(ref)
        if self._last_edge != "start":
            self._last_edge = "start"
            self.update()
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
            hover = hit if hit is not None and hit[0] in ("start", "end") else None
            if hover != self._hover:
                self._hover = hover
                self.update()
            return
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

    # Neither leaveEvent nor a changeEvent/ActivationChange override ends a
    # drag: during a grab the pointer may legitimately leave the widget and
    # come back, and ActivationChange is only ever delivered to a top-level
    # widget anyway — dead code here. focusOutEvent (above) covers the window
    # losing activation instead, now that a press gives the strip real focus.

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if self._hover is not None:
            self._hover = None
            self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        try:
            palette = self.palette()
            painter.fillRect(self.rect(), palette.window())
            width = self.width()
            height = self.height()
            playhead_ref = self._session.word_at(self._playhead)
            for tw in self._visible_words():
                left = self._viewport.x_for(tw.end, width)
                right = self._viewport.x_for(tw.start, width)
                if right < 0 or left > width:
                    continue
                box_width = max(2.0, right - left)
                rect = QRectF(left, 2.0, box_width, height - 4.0)
                self._paint_word(painter, rect, tw, tw.ref == playhead_ref, palette)
            handle = self.painted_handle()
            if handle is not None:
                self._paint_handle(painter, handle, width, height, palette)
        finally:
            painter.end()

    def _paint_word(self, painter, rect, tw, is_under_playhead, palette) -> None:
        tokens = theme.current_tokens()
        selected = tw.ref == self._selected
        if is_under_playhead:
            border_pen = QPen(QColor(tokens.accent), 2)
        else:
            border_pen = QPen(QColor(tokens.border), 1)
        painter.setPen(border_pen)
        if selected:
            painter.setBrush(QColor(tokens.accent))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 4, 4)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if rect.width() < _MIN_TEXT_WIDTH_PX:
            return

        text_color = QColor(tokens.on_accent) if selected else palette.windowText().color()
        painter.setPen(text_color)
        font = self.font_for(tw)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        elided = metrics.elidedText(
            tw.text, Qt.TextElideMode.ElideRight, max(0, int(rect.width()) - 4)
        )
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), elided)

        if tw.edited:
            bar = QRectF(rect.left() + 1, rect.top() + 1, max(1.0, rect.width() - 2), 3.0)
            painter.fillRect(bar, warning_color(palette))

    def _paint_handle(self, painter, handle, width, height, palette) -> None:
        edge, ref = handle
        try:
            tw = self._session.word(ref)
        except IndexError:
            return
        x = self._viewport.x_for(tw.start if edge == "start" else tw.end, width)
        half = self.HANDLE_PX / 2.0
        bar = QRectF(x - half, 0.0, float(self.HANDLE_PX), float(height))
        if not self._on_selected_box(x, width):
            painter.fillRect(bar, palette.highlight())
            return
        painter.fillRect(bar, palette.highlightedText())
        painter.setPen(QPen(palette.windowText().color(), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(bar)

    def _on_selected_box(self, x: float, width: int) -> bool:
        if self._selected is None:
            return False
        try:
            selected = self._session.word(self._selected)
        except IndexError:
            return False
        left = self._viewport.x_for(selected.end, width)
        right = self._viewport.x_for(selected.start, width)
        half = self.HANDLE_PX / 2.0
        return left - half <= x <= right + half

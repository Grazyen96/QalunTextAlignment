"""The frame the export would draw at the playhead, rendered live.

The review window polls this at frame rate while the play head moves, so a
full render on every poll — about 60 ms at the widget's size — would fall
behind real time. :meth:`FrameView.show_at` throttles to one render per
:data:`MIN_INTERVAL_S` unless the caller passes ``force=True``, which a seek,
a pause, or an edit does, so the frame the person is looking at is never
stale after a deliberate action, only between polls while playing.

The renderer itself (``core.frame_renderer``) is unaware of the GUI: it takes
plain dicts and returns a BGR numpy array, the same shape a render job would
hand to OpenCV. This widget is the only place that array becomes a
:class:`QPixmap`.

The preset size is what the widget asks for, not what it insists on: in a
small window it gives way down to half that, and renders the frame at the
largest size of the preset's shape that fits, so the frame never spills out of
the widget and the rows under it keep their room. Switched to actual size
(:meth:`FrameView.set_fit`), it holds exactly the preset size, and the window
scrolls it if the column is smaller.

A double-click asks for the frame full size (:attr:`FrameView.full_frame_requested`);
:class:`FullFrameView` is that view: a frameless black window over the screen,
the frame rendered once at the largest size of its shape that fits.
"""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPalette,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from qurantext.config.paths import DEFAULT_FONT_PATH
from qurantext.core.frame_renderer import (
    DEFAULT_PLACEHOLDER_TITLE,
    placeholder_lines,
    render_frame_pillow,
)
from qurantext.gui import i18n
from qurantext.gui.review.session import ReviewSession

__all__ = ["FrameView", "FullFrameView"]

#: Renders at most this often while polled continuously (e.g. during playback).
MIN_INTERVAL_S = 0.2

_PORTRAIT_SIZE = (270, 480)
_LANDSCAPE_SIZE = (480, 270)


def _to_pixmap(frame: np.ndarray) -> QPixmap:
    """The renderer's BGR array as a pixmap that owns its pixels."""
    rgb = np.ascontiguousarray(frame[:, :, ::-1])
    height, width, _channels = rgb.shape
    image = QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(image)


class FrameView(QLabel):
    """Shows the export frame at a given time, throttled while it is polled."""

    #: A double-click on the preview: show the frame full size at this time.
    full_frame_requested = Signal(float)

    def __init__(
        self,
        session: ReviewSession,
        *,
        portrait: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._session = session
        self._width, self._height = _PORTRAIT_SIZE if portrait else _LANDSCAPE_SIZE
        self._last_render_at: float | None = None
        self._placeholder_revision: int | None = None
        self._placeholder: tuple[str, str] = (DEFAULT_PLACEHOLDER_TITLE, "")
        self._fit = True
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setMinimumSize(self._width // 2, self._height // 2)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.setToolTip(i18n.t("review.full_frame"))
        #: The time last asked for, so a resize can redraw the same moment.
        self._last_t = 0.0

    @property
    def preset_size(self) -> QSize:
        """The preset's preview size: what the widget asks for, and holds in actual size."""
        return QSize(self._width, self._height)

    @property
    def fit(self) -> bool:
        """True when the frame scales down to the widget, False at the preset's size exactly."""
        return self._fit

    def set_fit(self, fit: bool) -> None:
        """Fit: scale down to the widget. Actual: the preset's preview size, exactly."""
        self._fit = bool(fit)
        if self._fit:
            self.setMinimumSize(self._width // 2, self._height // 2)
            self.setMaximumSize(16777215, 16777215)
        else:
            self.setMinimumSize(self._width, self._height)
            self.setMaximumSize(self._width, self._height)
        self.updateGeometry()
        self.show_at(self._last_t, force=True)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        """A left double-click asks for the frame full size at the time shown."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.full_frame_requested.emit(self._last_t)
            return
        super().mouseDoubleClickEvent(event)

    def sizeHint(self) -> QSize:  # noqa: D102 - Qt override, documented by the class
        return QSize(self._width, self._height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        """Half the preset size: as far as the frame gives way to a small window."""
        return QSize(self._width // 2, self._height // 2)

    def _render_size(self) -> tuple[int, int]:
        """The largest frame of the preset's shape that fits the widget, never above the preset size."""
        width = min(self._width, max(1, self.width()))
        height = min(self._height, max(1, self.height()))
        scale = min(width / self._width, height / self._height)
        return max(1, int(self._width * scale)), max(1, int(self._height * scale))

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        """Redraw the same moment at the new size, so the frame always fits the widget."""
        super().resizeEvent(event)
        self.show_at(self._last_t, force=True)

    def show_at(self, t: float, *, force: bool = False) -> None:
        """Render the frame at *t*, skipping it if throttled and not *force*."""
        self._last_t = t
        now = time.monotonic()
        if (
            not force
            and self._last_render_at is not None
            and (now - self._last_render_at) < MIN_INTERVAL_S
        ):
            return
        self._last_render_at = now

        card, caption, reserve_band = self._session.frame_inputs(t)
        caption_text = caption["text"] if caption else ""
        caption_word_timings = caption["word_timings"] if caption else None
        title, subtitle = self._placeholder_lines(reserve_band)
        try:
            frame = render_frame_pillow(
                t,
                card,
                *self._render_size(),
                DEFAULT_FONT_PATH,
                caption_text=caption_text,
                caption_word_timings=caption_word_timings,
                title=title,
                placeholder_subtitle=subtitle,
                reserve_caption_band=reserve_band,
                look=self._session.look,
            )
        except Exception as error:  # noqa: BLE001 - shown to the person, not raised
            self.clear()
            self.setText(i18n.t("frame.error", details=str(error)))
            return

        self.setPixmap(_to_pixmap(frame))

    def _placeholder_lines(self, reserve_caption_band: bool) -> tuple[str, str]:
        """The (title, subtitle) for the moment before any ayah has started.

        Delegates to ``core.frame_renderer.placeholder_lines`` — the same
        choice ``write_frame_video`` makes for the exported video — so the
        preview never shows a generic title where the video would show the
        lecture's opening card instead. Cached per session revision, since
        this reruns ``validated_matches`` (via ``session.validated_cards``)
        and the result cannot change between edits.
        """
        if self._placeholder_revision != self._session.revision:
            self._placeholder_revision = self._session.revision
            self._placeholder = placeholder_lines(
                self._session.validated_cards(),
                reserve_caption_band=reserve_caption_band,
                studied_surah=self._session.studied_surah,
            )
        return self._placeholder


class FullFrameView(QWidget):
    """The frame at one moment, as large as the screen allows; Escape, a click or losing focus closes it."""

    close_requested = Signal()

    def __init__(
        self,
        session: ReviewSession,
        t: float,
        *,
        portrait: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
        self.setPalette(palette)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        screen = parent.screen() if parent is not None else QGuiApplication.primaryScreen()
        geometry = screen.availableGeometry()
        self.setGeometry(geometry)
        preset_w, preset_h = _PORTRAIT_SIZE if portrait else _LANDSCAPE_SIZE
        scale = min(geometry.width() / preset_w, geometry.height() / preset_h)
        self._shown = QSize(max(1, int(preset_w * scale)), max(1, int(preset_h * scale)))
        #: True while hiding: hiding drops the focus, which must not close it twice.
        self._leaving = False
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        self._render(session, t)

    def shown_size(self) -> QSize:
        """The size the frame was rendered at: the preset's shape, as large as the screen fits."""
        return self._shown

    def _render(self, session: ReviewSession, t: float) -> None:
        card, caption, reserve_band = session.frame_inputs(t)
        title, subtitle = placeholder_lines(
            session.validated_cards(),
            reserve_caption_band=reserve_band,
            studied_surah=session.studied_surah,
        )
        try:
            frame = render_frame_pillow(
                t,
                card,
                self._shown.width(),
                self._shown.height(),
                DEFAULT_FONT_PATH,
                caption_text=caption["text"] if caption else "",
                caption_word_timings=caption["word_timings"] if caption else None,
                title=title,
                placeholder_subtitle=subtitle,
                reserve_caption_band=reserve_band,
                look=session.look,
            )
        except Exception as error:  # noqa: BLE001 - shown to the person, not raised
            self._label.setStyleSheet("color: white;")
            self._label.setText(i18n.t("frame.error", details=str(error)))
            return
        self._label.setPixmap(_to_pixmap(frame))

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt override
        """Take the focus, so Escape reaches it and losing the focus closes it."""
        super().showEvent(event)
        self._leaving = False
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        """Escape closes the view."""
        if event.key() == Qt.Key.Key_Escape:
            self._leave()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        """Any click closes the view."""
        self._leave()

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt override
        """Losing the focus (another window, Alt+Tab) closes the view."""
        super().focusOutEvent(event)
        self._leave()

    def _leave(self) -> None:
        if self._leaving or not self.isVisible():
            return
        self._leaving = True
        self.hide()
        self.close_requested.emit()

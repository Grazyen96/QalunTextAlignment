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

__all__ = ["PORTRAIT_PREVIEW_WIDTH", "FrameView", "FullFrameView"]

MIN_INTERVAL_S = 0.2

_PORTRAIT_SIZE = (270, 480)
_LANDSCAPE_SIZE = (480, 270)
PORTRAIT_PREVIEW_WIDTH = _PORTRAIT_SIZE[0]


def _to_pixmap(frame: np.ndarray) -> QPixmap:
    rgb = np.ascontiguousarray(frame[:, :, ::-1])
    height, width, _channels = rgb.shape
    image = QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(image)


class FrameView(QLabel):
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
        self._last_t = 0.0

    @property
    def preset_size(self) -> QSize:
        return QSize(self._width, self._height)

    @property
    def fit(self) -> bool:
        return self._fit

    def set_fit(self, fit: bool) -> None:
        self._fit = bool(fit)
        if self._fit:
            self.setMinimumSize(self._width // 2, self._height // 2)
            self.setMaximumSize(16777215, 16777215)
        else:
            self.setMinimumSize(self._width, self._height)
            self.setMaximumSize(self._width, self._height)
        self.updateGeometry()
        self.show_at(self._last_t, force=True)

    def request_full_frame(self) -> None:
        self.full_frame_requested.emit(self._last_t)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.request_full_frame()
            return
        super().mouseDoubleClickEvent(event)

    def sizeHint(self) -> QSize:  # noqa: D102 - Qt override, documented by the class
        return QSize(self._width, self._height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(self._width // 2, self._height // 2)

    def _render_size(self) -> tuple[int, int]:
        width = min(self._width, max(1, self.width()))
        height = min(self._height, max(1, self.height()))
        scale = min(width / self._width, height / self._height)
        return max(1, int(self._width * scale)), max(1, int(self._height * scale))

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self.show_at(self._last_t, force=True)

    def show_at(self, t: float, *, force: bool = False) -> None:
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
        except Exception as error:
            self.clear()
            self.setText(i18n.t("frame.error", details=str(error)))
            return

        self.setPixmap(_to_pixmap(frame))

    def _placeholder_lines(self, reserve_caption_band: bool) -> tuple[str, str]:
        if self._placeholder_revision != self._session.revision:
            self._placeholder_revision = self._session.revision
            self._placeholder = placeholder_lines(
                self._session.validated_cards(),
                reserve_caption_band=reserve_caption_band,
                studied_surah=self._session.studied_surah,
            )
        return self._placeholder


class FullFrameView(QWidget):
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
        except Exception as error:
            self._label.setStyleSheet("color: white;")
            self._label.setText(i18n.t("frame.error", details=str(error)))
            return
        self._label.setPixmap(_to_pixmap(frame))

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._leaving = False
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            self._leave()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        self._leave()

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt override
        super().focusOutEvent(event)
        self._leave()

    def _leave(self) -> None:
        if self._leaving or not self.isVisible():
            return
        self._leaving = True
        self.hide()
        self.close_requested.emit()

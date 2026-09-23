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
"""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

from qurantext.config.paths import DEFAULT_FONT_PATH
from qurantext.core.frame_renderer import DEFAULT_PLACEHOLDER_TITLE, render_frame_pillow
from qurantext.gui import i18n
from qurantext.gui.review.session import ReviewSession

__all__ = ["FrameView"]

#: Renders at most this often while polled continuously (e.g. during playback).
MIN_INTERVAL_S = 0.2

_PORTRAIT_SIZE = (270, 480)
_LANDSCAPE_SIZE = (480, 270)


class FrameView(QLabel):
    """Shows the export frame at a given time, throttled while it is polled."""

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

    def sizeHint(self) -> QSize:  # noqa: D102 - Qt override, documented by the class
        return QSize(self._width, self._height)

    def show_at(self, t: float, *, force: bool = False) -> None:
        """Render the frame at *t*, skipping it if throttled and not *force*."""
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
        try:
            frame = render_frame_pillow(
                t,
                card,
                self._width,
                self._height,
                DEFAULT_FONT_PATH,
                caption_text=caption_text,
                caption_word_timings=caption_word_timings,
                title=DEFAULT_PLACEHOLDER_TITLE,
                reserve_caption_band=reserve_band,
            )
        except Exception as error:  # noqa: BLE001 - shown to the person, not raised
            self.clear()
            self.setText(i18n.t("frame.error", details=str(error)))
            return

        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        height, width, _channels = rgb.shape
        image = QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()
        self.setPixmap(QPixmap.fromImage(image))

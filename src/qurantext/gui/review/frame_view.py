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
the widget and the rows under it keep their room.
"""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPixmap, QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from qurantext.config.paths import DEFAULT_FONT_PATH
from qurantext.core.frame_renderer import (
    DEFAULT_PLACEHOLDER_TITLE,
    placeholder_lines,
    render_frame_pillow,
)
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
        self._placeholder_revision: int | None = None
        self._placeholder: tuple[str, str] = (DEFAULT_PLACEHOLDER_TITLE, "")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setMinimumSize(self._width // 2, self._height // 2)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        #: The time last asked for, so a resize can redraw the same moment.
        self._last_t = 0.0

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

        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        height, width, _channels = rgb.shape
        image = QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()
        self.setPixmap(QPixmap.fromImage(image))

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

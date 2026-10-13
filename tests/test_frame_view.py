"""The preview: fit or actual size, and the frame full size on a double-click."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import QEvent, QPointF, QSize, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402

from qurantext.gui.i18n import t  # noqa: E402
from qurantext.gui.review.frame_view import FrameView, FullFrameView  # noqa: E402
from qurantext.gui.review.session import ReviewSession  # noqa: E402
from qurantext.jobs.project import Project, save_project  # noqa: E402
from tests.qt_helpers import spin  # noqa: E402


def _project(tmp_path) -> Project:
    """The one-card project ``tests/test_review_window.py`` builds."""
    cards = [
        {
            "surah_num": 25,
            "from_ayah": 7,
            "to_ayah": 7,
            "full_text": "a b",
            "confidence": 1.0,
            "start_time": 0.0,
            "end_time": 10.0,
            "word_timings": [
                {"word": "a", "start": 1.0, "end": 2.0},
                {"word": "b", "start": 2.0, "end": 3.0},
            ],
        }
    ]
    matches = tmp_path / "m.json"
    matches.write_text(
        json.dumps({"matches": cards, "meta": {"mode": "recitation"}}), encoding="utf-8"
    )
    project = Project(audio=tmp_path / "missing.mp3", cards=cards, matches=matches)
    save_project(project, tmp_path / "m.qalun.json")
    return project


@pytest.fixture()
def review_session(qt_app, tmp_path) -> ReviewSession:
    """A session over the one-card project."""
    return ReviewSession(_project(tmp_path))


def _mouse(kind: QEvent.Type) -> QMouseEvent:
    return QMouseEvent(
        kind,
        QPointF(10, 10),
        QPointF(10, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_fit_follows_the_widget_and_actual_pins_the_preset_size(qt_app, review_session) -> None:
    view = FrameView(review_session, portrait=True)
    assert view.fit is True and view.preset_size == QSize(270, 480)
    view.set_fit(False)
    assert view.fit is False
    assert view.minimumSize() == QSize(270, 480) and view.maximumSize() == QSize(270, 480)
    view.set_fit(True)
    assert view.minimumSize() == QSize(135, 240)
    view.deleteLater()


def test_the_preview_says_a_double_click_shows_the_frame_full_size(qt_app, review_session) -> None:
    view = FrameView(review_session, portrait=True)
    assert view.toolTip() == t("review.full_frame")
    view.deleteLater()


def test_a_double_click_asks_for_the_full_frame_at_the_shown_time(qt_app, review_session) -> None:
    view = FrameView(review_session, portrait=True)
    view.show_at(3.0, force=True)
    asked = []
    view.full_frame_requested.connect(asked.append)
    view.mouseDoubleClickEvent(_mouse(QEvent.Type.MouseButtonDblClick))
    assert asked == [3.0]
    view.deleteLater()


def test_the_full_frame_view_fits_the_screen_keeps_the_shape_and_closes_on_escape(
    qt_app, review_session
) -> None:
    """Review Focus 4: opened at the clicked time, closed by Escape."""
    full = FullFrameView(review_session, 3.0, portrait=True)
    full.show()
    spin(100)
    shown = full.shown_size()
    screen = qt_app.primaryScreen().availableGeometry()
    assert shown.height() <= screen.height() and shown.width() <= screen.width()
    assert abs(shown.width() / shown.height() - 270 / 480) < 0.02
    closed = []
    full.close_requested.connect(lambda: closed.append(1))
    full.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    assert closed == [1] and not full.isVisible()
    full.deleteLater()


def test_the_full_frame_view_closes_on_a_click_too(qt_app, review_session) -> None:
    full = FullFrameView(review_session, 0.0, portrait=False)
    full.show()
    spin(50)
    full.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress))
    assert not full.isVisible()
    full.deleteLater()


def test_the_full_frame_view_shows_the_frame_it_rendered(qt_app, review_session) -> None:
    full = FullFrameView(review_session, 3.0, portrait=False)
    pixmap = full._label.pixmap()
    assert not pixmap.isNull()
    assert pixmap.size() == full.shown_size()
    full.deleteLater()


def test_the_full_frame_view_closes_once_when_it_loses_the_focus(qt_app, review_session) -> None:
    from PySide6.QtGui import QFocusEvent

    full = FullFrameView(review_session, 0.0, portrait=True)
    full.show()
    spin(50)
    closed = []
    full.close_requested.connect(lambda: closed.append(1))
    full.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.ActiveWindowFocusReason))
    assert closed == [1] and not full.isVisible()
    full.deleteLater()

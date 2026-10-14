"""A panel opens by growing over 150 ms, or at once when animation is off."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtWidgets import QLabel, QStyle, QVBoxLayout, QWidget  # noqa: E402

from qurantext.gui import disclosure  # noqa: E402

# Bound at import, before the suite's autouse fixture replaces the module
# attribute with a function that always says no.
from qurantext.gui.disclosure import animations_enabled as real  # noqa: E402
from tests.qt_helpers import wait_for  # noqa: E402

_NO_LIMIT = 16777215


@pytest.fixture()
def panel(qt_app):
    window = QWidget()
    column = QVBoxLayout(window)
    header = QLabel("header")
    body = QWidget()
    inner = QVBoxLayout(body)
    for i in range(6):
        inner.addWidget(QLabel(f"line {i}"))
    column.addWidget(header)
    column.addWidget(body)
    body.hide()
    window.show()
    qt_app.processEvents()
    yield body
    window.close()


def test_without_animation_it_shows_and_hides_at_once(qt_app, panel) -> None:
    disclosure.reveal(panel, True, animate=False)
    assert panel.isVisible() and panel.maximumHeight() == _NO_LIMIT
    disclosure.reveal(panel, False, animate=False)
    assert not panel.isVisible()


def test_with_animation_it_grows_then_frees_its_height(qt_app, panel) -> None:
    full = panel.sizeHint().height()
    disclosure.reveal(panel, True, animate=True)
    assert panel.isVisible() and panel.maximumHeight() < full
    assert wait_for(lambda: panel.maximumHeight() == _NO_LIMIT, 2000)
    assert wait_for(lambda: panel.height() >= full, 2000)
    disclosure.reveal(panel, False, animate=True)
    assert panel.isVisible(), "still on screen while it shrinks"
    assert wait_for(lambda: not panel.isVisible(), 2000)
    assert panel.maximumHeight() == _NO_LIMIT


def test_a_finished_animation_is_deleted(qt_app, panel) -> None:
    """Each open and close made a QPropertyAnimation that lived as long as the panel."""
    from PySide6.QtCore import QCoreApplication, QEvent, QPropertyAnimation

    def animations() -> list:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        return panel.findChildren(QPropertyAnimation)

    disclosure.reveal(panel, True, animate=True)
    assert len(animations()) == 1
    assert wait_for(lambda: panel.maximumHeight() == _NO_LIMIT, 2000)
    assert animations() == []
    disclosure.reveal(panel, False, animate=True)
    assert wait_for(lambda: not panel.isVisible(), 2000)
    assert animations() == []


def test_closing_a_hidden_panel_is_instant(qt_app, panel) -> None:
    """No 0-height panel shown for the length of an animation, taking its layout spacing."""
    assert not panel.isVisible()
    disclosure.reveal(panel, False, animate=True)
    assert panel.isHidden()
    assert panel.property("qalun.disclosure") is None


def test_a_toggle_mid_animation_reverses_and_frees_the_height(qt_app, panel) -> None:
    disclosure.reveal(panel, True, animate=True)
    qt_app.processEvents()
    disclosure.reveal(panel, False, animate=True)  # before the 150 ms are over
    assert wait_for(lambda: not panel.isVisible(), 2000)
    assert panel.maximumHeight() == _NO_LIMIT
    disclosure.reveal(panel, True, animate=True)
    assert wait_for(lambda: panel.maximumHeight() == _NO_LIMIT, 2000)
    assert panel.isVisible()


def test_a_hidden_window_gets_no_animation(qt_app) -> None:
    window = QWidget()
    body = QWidget(window)
    body.hide()
    disclosure.reveal(body, True, animate=True)
    assert body.maximumHeight() == _NO_LIMIT and not body.isHidden()


def test_animations_follow_the_setting_and_the_style_hint(qt_app, prefs, monkeypatch) -> None:
    assert prefs.animate_panels is True
    hint = qt_app.style().styleHint(QStyle.StyleHint.SH_Widget_Animate)
    assert real(prefs) is bool(hint)
    prefs.animate_panels = False
    assert real(prefs) is False
    prefs.animate_panels = True
    monkeypatch.setattr(type(qt_app.style()), "styleHint", lambda self, *a, **k: 0)
    assert real(prefs) is False

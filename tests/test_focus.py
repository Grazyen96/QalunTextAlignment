# tests/test_focus.py
"""The focus ring paints for keyboard focus only: Tab marks a widget, a click does not."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget  # noqa: E402

from qurantext.gui import focus  # noqa: E402


@pytest.fixture()
def pair(qt_app):
    focus.install(qt_app)
    window = QWidget()
    row = QHBoxLayout(window)
    button, field = QPushButton("b"), QLineEdit()
    row.addWidget(button)
    row.addWidget(field)
    window.show()
    window.activateWindow()  # an inactive window gets no FocusIn events
    qt_app.processEvents()
    # Activation hands the first widget focus; start each test from none, so setFocus sends FocusIn.
    if qt_app.focusWidget() is not None:
        qt_app.focusWidget().clearFocus()
    qt_app.processEvents()
    yield button, field
    window.close()


def test_tab_marks_a_widget_and_a_click_does_not(qt_app, pair) -> None:
    button, field = pair
    button.setFocus(Qt.FocusReason.TabFocusReason)
    qt_app.processEvents()
    assert button.property(focus.KBDFOCUS) is True
    field.setFocus(Qt.FocusReason.MouseFocusReason)
    qt_app.processEvents()
    assert not field.property(focus.KBDFOCUS)
    button.setFocus(Qt.FocusReason.BacktabFocusReason)
    assert button.property(focus.KBDFOCUS) is True
    field.setFocus(Qt.FocusReason.ShortcutFocusReason)
    assert field.property(focus.KBDFOCUS) is True


def test_focus_out_clears_the_mark(qt_app, pair) -> None:
    button, field = pair
    button.setFocus(Qt.FocusReason.TabFocusReason)
    assert button.property(focus.KBDFOCUS) is True
    field.setFocus(Qt.FocusReason.MouseFocusReason)  # a click elsewhere
    qt_app.processEvents()
    assert button.property(focus.KBDFOCUS) is False


def test_other_reasons_do_not_mark(qt_app, pair) -> None:
    button, _field = pair
    for reason in (Qt.FocusReason.OtherFocusReason, Qt.FocusReason.ActiveWindowFocusReason):
        button.clearFocus()
        button.setFocus(reason)
        qt_app.processEvents()
        assert not button.property(focus.KBDFOCUS), reason


def test_install_is_idempotent(qt_app) -> None:
    first = focus.install(qt_app)
    assert focus.install(qt_app) is first
    assert qt_app.property("qalun.focus_marker") is first

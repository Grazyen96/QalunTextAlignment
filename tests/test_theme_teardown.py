"""The teardown that puts the theme back between tests must not leave Qt pointing at a deleted widget."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

ROOT = Path(__file__).resolve().parents[1]

# What crashed tools/screenshots.py inside the suite, in its own process, since a
# failure here is a segfault: a dialog let go with deleteLater() while the theme was
# on, the teardown, the next theme, the dialog deleted at last, one more theme change.
_SCRIPT = textwrap.dedent(
    """
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton

    from qurantext.gui import theme, widgets
    from tests.conftest import _THEME_PROPERTIES, restore_theme

    app = QApplication([])
    saved = dict(
        palette=QPalette(app.palette()),
        sheet=app.styleSheet(),
        style_name=app.style().objectName(),
        properties={name: app.property(name) for name in _THEME_PROPERTIES},
    )
    theme.apply_theme(app, "light")
    dialog = QDialog()
    widgets.make_primary(QPushButton("OK", dialog))
    dialog.deleteLater()
    del dialog
    restore_theme(app, **saved)
    theme.apply_theme(app, "light")
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    theme.apply_theme(app, "dark")
    print("survived")
    """
)


def _run(script: str) -> subprocess.CompletedProcess:
    """*script* offscreen in its own process, freed memory scribbled over so a stale pointer crashes."""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", MALLOC_PERTURB_="165")
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT)])
    return subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_a_widget_let_go_under_one_theme_does_not_crash_the_next_theme_change() -> None:
    done = _run(_SCRIPT)
    assert done.returncode == 0, done.stderr[-2000:]
    assert "survived" in done.stdout


# The same, for a widget freed by Python's garbage collector rather than by
# deleteLater(): dialogs kept alive only by a reference cycle are collected at a
# point of the collector's choosing, here forced after the next theme. Collection
# is turned off so nothing frees them early.
_CYCLE_SCRIPT = textwrap.dedent(
    """
    import gc

    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton

    from qurantext.gui import theme, widgets
    from tests.conftest import _THEME_PROPERTIES, restore_theme

    gc.disable()
    app = QApplication([])
    saved = dict(
        palette=QPalette(app.palette()),
        sheet=app.styleSheet(),
        style_name=app.style().objectName(),
        properties={name: app.property(name) for name in _THEME_PROPERTIES},
    )
    theme.apply_theme(app, "light")
    for _ in range(5):
        dialog = QDialog()
        widgets.make_primary(QPushButton("OK", dialog))
        dialog.cycle = dialog
    del dialog
    restore_theme(app, **saved)
    theme.apply_theme(app, "light")
    gc.collect()
    theme.apply_theme(app, "dark")
    print("survived")
    """
)


def test_a_widget_the_garbage_collector_frees_under_the_next_theme_does_not_crash_it() -> None:
    done = _run(_CYCLE_SCRIPT)
    assert done.returncode == 0, done.stderr[-2000:]
    assert "survived" in done.stdout


def test_a_widget_deleted_while_it_has_keyboard_focus_does_not_crash_the_theme(qt_app) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit, QPushButton, QVBoxLayout, QWidget

    from qurantext.gui import theme
    from qurantext.gui.focus import KBDFOCUS

    theme.apply_theme(qt_app, "light")
    window = QWidget()
    layout = QVBoxLayout(window)
    field = QLineEdit()
    button = QPushButton("OK")
    layout.addWidget(field)
    layout.addWidget(button)
    window.show()
    window.activateWindow()
    QCoreApplication.processEvents()
    field.setFocus(Qt.FocusReason.OtherFocusReason)
    QTest.keyClick(field, Qt.Key.Key_Tab)
    QCoreApplication.processEvents()
    assert qt_app.focusWidget() is button
    assert button.property(KBDFOCUS) is True
    # Its focus-out comes from inside its destructor, through the focus marker.
    button.deleteLater()
    del button
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    theme.apply_theme(qt_app, "dark")
    theme.apply_theme(qt_app, "light")
    window.close()

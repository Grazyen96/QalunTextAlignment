"""Application entry point."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, NoReturn

from qurantext.config.paths import bundled_asset

__all__ = ["APP_ICON_PNG", "main", "set_app_icon"]

#: The window and task-bar icon; one PNG, Qt scales it for the sizes it needs.
APP_ICON_PNG = bundled_asset("icon/qalun-256.png")

#: Qt's own criticals and fatals (``QThread: Destroyed while thread is still
#: running``) come through its message handler, not Python's, so a windowed
#: build would otherwise record nothing of them. Its warnings stay out of the
#: log: platform chatter (``qt.qpa.*`` on each activation) would share the 4 MB
#: with real errors, and one repeated per frame would rotate them away.
_qt_log = logging.getLogger("qurantext.qt")
#: The handler Qt had before ours: None means Qt's default, which prints.
_previous_qt_handler: Any = None

#: How long quitting waits, in total, for background threads a closed window
#: left running (a coverage check, a waveform read) before leaving anyway.
_EXIT_WAIT_MS = 30_000


#: The name settings are filed under; see :func:`_name_the_app`.
_APP_NAME = "Qalun"


def set_app_icon(app) -> None:
    """Give every window the app icon; a build that lost the file keeps Qt's blank one."""
    from PySide6.QtGui import QIcon

    if APP_ICON_PNG.is_file():
        app.setWindowIcon(QIcon(str(APP_ICON_PNG)))


def _name_the_app() -> None:
    """Name the organisation and the app before anything reads a default ``QSettings``.

    ``Prefs()`` opens ``QSettings()``, which files the settings under these two
    names; without an organisation name it lands somewhere that depends on how
    the app was launched, and the window forgets its choices between runs.
    """
    from PySide6.QtCore import QCoreApplication

    QCoreApplication.setOrganizationName(_APP_NAME)
    QCoreApplication.setApplicationName(_APP_NAME)


def _start_the_log() -> None:
    """Keep errors in a file, before anything that could raise one is imported.

    A windowed build has no standard error, so without this a traceback from a
    slot or a background thread is gone. Never in the way: the window opens
    whatever happens here.
    """
    try:
        from qurantext.config.app_log import configure

        configure()
        _route_qt_messages()
    except Exception:
        pass


def _route_qt_messages() -> None:
    """Send Qt's criticals and fatals to the log; everything else prints as before."""
    global _previous_qt_handler
    from PySide6.QtCore import qInstallMessageHandler

    _previous_qt_handler = qInstallMessageHandler(_qt_message)


def _qt_message(mode: Any, context: Any, message: str) -> None:
    """Qt's message handler: never raises, since Qt calls it from any thread, mid-anything."""
    try:
        from PySide6.QtCore import QtMsgType

        levels = {
            QtMsgType.QtCriticalMsg: logging.ERROR,
            QtMsgType.QtFatalMsg: logging.CRITICAL,
        }
        level = levels.get(mode)
        if level is None:
            # Debug, info and warnings: not the log's; printed as Qt would.
            if _previous_qt_handler is not None:
                _previous_qt_handler(mode, context, message)
            elif sys.stderr is not None:
                print(message, file=sys.stderr)
            return
        category = getattr(context, "category", None)
        if category and category != "default":
            message = f"{category}: {message}"
        # The log's stderr handler prints it on a terminal, so Qt's default need not.
        _qt_log.log(level, "%s", message)
    except Exception:
        pass


def _leave_now(code: int) -> NoReturn:
    """Exit at once, without Python's teardown, after flushing what can be flushed.

    A windowed build has no stdout or stderr (both None), and a flush on None
    raised before ``os._exit`` was reached, which then ran the very teardown
    this exists to skip.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            try:
                stream.flush()
            except Exception:
                pass
    os._exit(code)


def main(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ModuleNotFoundError:
        print(
            "The window needs Qt, which is not installed.\n  pip install 'qurantext[gui]'",
            file=sys.stderr,
        )
        return 1

    _start_the_log()

    from qurantext.gui.main_window import MainWindow

    _name_the_app()
    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationDisplayName(_APP_NAME)
    set_app_icon(app)

    from qurantext.gui.language import apply_language, initial_language
    from qurantext.gui.prefs import Prefs

    # Before the window: every widget reads its words and direction as it is built.
    prefs = Prefs()
    apply_language(app, initial_language(prefs))
    from qurantext.gui.theme import apply_theme

    apply_theme(app, prefs.theme)
    window = MainWindow(prefs=prefs)
    window.show()
    code = app.exec()

    from qurantext.gui.review.background import join_lingering

    if not join_lingering(_EXIT_WAIT_MS):
        # Still running after the wait: Python's teardown would destroy those
        # QThreads under them and abort, so leave without running it.
        _leave_now(code)
    return code

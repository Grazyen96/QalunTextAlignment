"""Application entry point."""

from __future__ import annotations

import os
import sys

__all__ = ["main"]

#: How long quitting waits, in total, for background threads a closed window
#: left running (a coverage check, a waveform read) before leaving anyway.
_EXIT_WAIT_MS = 30_000


#: The name settings are filed under; see :func:`_name_the_app`.
_APP_NAME = "Qalun"


def _name_the_app() -> None:
    """Name the organisation and the app before anything reads a default ``QSettings``.

    ``Prefs()`` opens ``QSettings()``, which files the settings under these two
    names; without an organisation name it lands somewhere that depends on how
    the app was launched, and the window forgets its choices between runs.
    """
    from PySide6.QtCore import QCoreApplication

    QCoreApplication.setOrganizationName(_APP_NAME)
    QCoreApplication.setApplicationName(_APP_NAME)


def main(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ModuleNotFoundError:
        print(
            "The window needs Qt, which is not installed.\n  pip install 'qurantext[gui]'",
            file=sys.stderr,
        )
        return 1

    from qurantext.gui.main_window import MainWindow

    _name_the_app()
    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationDisplayName(_APP_NAME)

    from qurantext.gui.language import apply_language, initial_language
    from qurantext.gui.prefs import Prefs

    # Before the window: every widget reads its words and direction as it is built.
    prefs = Prefs()
    apply_language(app, initial_language(prefs))
    window = MainWindow(prefs=prefs)
    window.show()
    code = app.exec()

    from qurantext.gui.review.background import join_lingering

    if not join_lingering(_EXIT_WAIT_MS):
        # Still running after the wait: Python's teardown would destroy those
        # QThreads under them and abort, so leave without running it.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
    return code

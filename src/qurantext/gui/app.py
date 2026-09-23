"""Application entry point."""

from __future__ import annotations

import os
import sys

__all__ = ["main"]

#: How long quitting waits, in total, for background threads a closed window
#: left running (a coverage check, a waveform read) before leaving anyway.
_EXIT_WAIT_MS = 30_000


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

    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("Qalun")
    app.setApplicationDisplayName("Qalun")

    window = MainWindow()
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

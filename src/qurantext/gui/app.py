"""Application entry point."""

from __future__ import annotations

import sys

__all__ = ["main"]


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
    return app.exec()

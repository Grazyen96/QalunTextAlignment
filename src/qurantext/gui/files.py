"""Small filesystem-facing helpers shared by more than one window.

Kept apart from any one window so both the home window and the review window
can reveal a finished file the same way.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

__all__ = ["open_folder", "show_in_folder"]


def show_in_folder(path: Path) -> None:
    """Reveal the file in the platform's file manager, selected where possible."""
    try:
        if sys.platform == "win32":
            subprocess.run(["explorer", "/select,", str(path)], check=False)
            return
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=False)
            return
    except OSError:
        pass
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def open_folder(folder: Path) -> bool:
    """Open *folder* itself in the file manager, making it first; False when that failed.

    Made first because the log folder appears only once the window has started
    with a writable data folder; an empty one is still the right place to look.
    """
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))))

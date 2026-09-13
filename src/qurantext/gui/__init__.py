"""The desktop window.

Qt is an optional dependency: install with ``pip install qurantext[gui]``. The
command line works without it, so importing this package is what fails when Qt
is absent, never importing qurantext itself.
"""

from __future__ import annotations

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Open the window. Imports Qt lazily so the error is a sentence, not a traceback."""
    from qurantext.gui.app import main as _main

    return _main(argv)

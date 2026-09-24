"""The review window: listen, watch, and correct a job before it renders.

``ReviewWindow`` is loaded on first use rather than here, so the Qt-free parts
(``session``, the editing model) import on a machine without Qt, as the
command-line install and its CI run do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["ReviewWindow"]

if TYPE_CHECKING:
    from qurantext.gui.review.window import ReviewWindow


def __getattr__(name: str) -> object:
    if name == "ReviewWindow":
        from qurantext.gui.review.window import ReviewWindow

        return ReviewWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

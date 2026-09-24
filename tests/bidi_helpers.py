"""Where Qt actually draws each part of a line, for tests of right-to-left text.

A line's logical order says nothing about what a reader sees: the bidi
algorithm reorders runs, and one missing direction mark swaps two times or two
folders. These helpers lay a line out with ``QTextLayout`` and read each
character's glyph x, so a test can assert the order a person reads. They need a
``QApplication`` (the ``qt_app`` fixture) and run offscreen in milliseconds.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["left_to_right"]


def left_to_right(text: str, parts: Sequence[str], *, rtl: bool | None = None) -> list[str]:
    """*parts* of *text* in the order they are drawn, from the left edge.

    Each part must occur exactly once in *text*. *rtl* is the paragraph
    direction; None (the default) takes it from the text's first strong letter
    outside its isolates, as a label lays out plain text, so a line that
    loses its leading RLM is caught. A part's place is its leftmost
    glyph, which is its left edge whichever way it runs itself.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QTextLayout, QTextOption

    layout = QTextLayout(text, QFont())
    option = QTextOption()
    if rtl is None:
        option.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)
    else:
        option.setTextDirection(
            Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight
        )
    layout.setTextOption(option)
    layout.beginLayout()
    line = layout.createLine()
    line.setLineWidth(100_000)  # one line, however long the text
    layout.endLayout()

    def left_edge(part: str) -> float:
        assert text.count(part) == 1, f"{part!r} must occur once in {text!r}"
        start = text.index(part)
        xs = [
            position.x()
            for index in range(start, start + len(part))
            for run in layout.glyphRuns(index, 1)
            for position in run.positions()
        ]
        assert xs, f"{part!r} draws no glyph"
        return min(xs)

    return sorted(parts, key=left_edge)

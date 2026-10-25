"""The bundled Quran face, for every widget that shows the mushaf's own words.

The shipped KFGQPC Qaloon text writes open tanween as U+0657, U+065E and
U+0656, and only its own face, ``qaloon.10.ttf``, draws those as open
tanween: the interface font's Arabic fallback draws an inverted damma, a
fatha with two dots and a subscript alef. So Quran text in the window is
drawn in this face, with the window's code points left as they are; the
subtitle files' portable spelling (``core.arabic.portable_tanween``) is for
players that do not have the face, never for the window.

The face has no Latin letters; Qt draws those from the families that follow
it, which are the widget's own.
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase

from qurantext.config.paths import DEFAULT_FONT_PATH

__all__ = ["quran_font_family", "with_quran_face"]

#: The bundled Quran face's family once registered with Qt ("" when it could not be).
_quran_family: str | None = None


def quran_font_family() -> str:
    """The bundled Qaloon face's family, registered on first use; "" when it cannot be.

    The card in the video is drawn in this face, so the window reads the same.
    """
    global _quran_family
    if _quran_family is None:
        font_id = QFontDatabase.addApplicationFont(str(DEFAULT_FONT_PATH))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id != -1 else []
        _quran_family = families[0] if families else ""
    return _quran_family


def with_quran_face(font: QFont) -> QFont:
    """A copy of *font* that draws in the Quran face first; *font* itself when there is none.

    A bundle whose face cannot be registered keeps drawing in the widget's own
    font rather than in nothing.
    """
    family = quran_font_family()
    if not family:
        return font
    quran = QFont(font)
    quran.setFamilies([family, *font.families()])
    return quran

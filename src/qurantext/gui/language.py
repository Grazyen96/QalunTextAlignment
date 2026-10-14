"""Put the window into one of its languages.

A language is more than a table of words: Arabic mirrors the layout, Qt's own
buttons and dialogs need their translation loaded, and numbers must stay
Western digits in both (they are timings a reviewer compares with other tools),
which Qt would otherwise draw in the system locale's digits.
"""

from __future__ import annotations

from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTranslator
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from qurantext.config.paths import NOTO_FONT_PATHS
from qurantext.config.preflight import CannotMeasureFonts, arabic_ui_families
from qurantext.gui import i18n
from qurantext.gui.prefs import Prefs

__all__ = ["apply_language", "ensure_arabic_font", "initial_language", "system_language"]

#: Qt's own translation for the language in use, kept so the next switch can remove it.
_qt_translator: QTranslator | None = None

#: The bundled font once registered as the Arabic fallback: its font id and family.
_fallback: tuple[list[int], str] | None = None


def _ui_language_name(locale: QLocale) -> str:
    """The language *locale*'s user interface is in (``"ar-SA"``), else its name.

    Not ``name()`` alone: on Windows and macOS that is the region format, so an
    English Windows with Saudi regional settings would start in Arabic.
    """
    languages = locale.uiLanguages()
    return languages[0] if languages else locale.name()


def system_language(locale_name: str | None = None) -> str:
    """The language the window starts in when none was chosen: Arabic on an Arabic system.

    *locale_name* is a locale name such as ``"ar_EG"`` or ``"ar-SA"``; the default
    reads the system's UI language. Any language the window has no table for
    falls back to English.
    """
    name = locale_name if locale_name is not None else _ui_language_name(QLocale.system())
    language = name.replace("-", "_").split("_", 1)[0].lower()
    return "ar" if language == "ar" else "en"


def initial_language(prefs: Prefs, locale_name: str | None = None) -> str:
    """The language chosen at the foot of the home window, else the system's."""
    return prefs.language or system_language(locale_name)


def ensure_arabic_font(app: QApplication) -> str | None:
    """Let the window draw Arabic letters on a machine with no Arabic font of its own.

    Such a machine shows every Arabic word as empty boxes. The bundled Noto Sans
    Arabic has Arabic letters only (no Latin ones), so it is a substitute of the
    application font's family: Qt draws the Arabic letters with it and
    everything else with the system font. The Quran face is no longer used for
    the interface. A machine with an Arabic font keeps it, and so does one whose
    fonts cannot be measured (``CannotMeasureFonts``): that says nothing about
    what is installed, and a fallback registered on a guess would take over
    Arabic from the font the system has.

    Returns the family registered as the fallback (also when an earlier call
    registered it), or None when nothing was registered.
    """
    global _fallback
    # Once registered, Noto has the Arabic writing system and is not a private
    # family, so ``arabic_ui_families`` counts it as installed: ask only before.
    if _fallback is None:
        try:
            if arabic_ui_families():
                return None
        except CannotMeasureFonts:
            return None
        ids = [QFontDatabase.addApplicationFont(str(path)) for path in NOTO_FONT_PATHS]
        families = [
            family
            for font_id in ids
            if font_id != -1
            for family in QFontDatabase.applicationFontFamilies(font_id)
        ]
        if not families:
            return None  # the files are missing or unreadable; the doctor reports it
        _fallback = ([font_id for font_id in ids if font_id != -1], families[0])
    # Qt keeps each substitute once, so a second language switch adds nothing.
    QFont.insertSubstitution(app.font().family(), _fallback[1])
    return _fallback[1]


def apply_language(app: QApplication, code: str) -> None:
    """Switch the words, Qt's own translation, the digits and the direction to *code*.

    Widgets built afterwards pick all of it up; ones already built keep their
    words, which is why the home window rebuilds itself after calling this.
    """
    global _qt_translator
    i18n.set_language(code)  # raises on an unknown code before anything changes
    if _qt_translator is not None:
        app.removeTranslator(_qt_translator)
        _qt_translator.deleteLater()
        _qt_translator = None
    if code != "en":
        translator = QTranslator(app)
        folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if translator.load(f"qtbase_{code}", folder):
            app.installTranslator(translator)
            _qt_translator = translator
        else:
            translator.deleteLater()  # Qt's buttons stay English; the window's words do not
    # The C locale draws 0-9 and a decimal point whatever the system is set to.
    QLocale.setDefault(QLocale.c())
    # In every language: an Arabic job name shows in the English window too.
    ensure_arabic_font(app)
    # After the translator: installing one may set a direction of its own.
    app.setLayoutDirection(
        Qt.LayoutDirection.RightToLeft if i18n.is_rtl(code) else Qt.LayoutDirection.LeftToRight
    )

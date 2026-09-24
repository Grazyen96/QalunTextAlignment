"""Put the window into one of its languages.

A language is more than a table of words: Arabic mirrors the layout, Qt's own
buttons and dialogs need their translation loaded, and numbers must stay
Western digits in both (they are timings a reviewer compares with other tools),
which Qt would otherwise draw in the system locale's digits.
"""

from __future__ import annotations

from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTranslator
from PySide6.QtWidgets import QApplication

from qurantext.gui import i18n
from qurantext.gui.prefs import Prefs

__all__ = ["apply_language", "initial_language", "system_language"]

#: Qt's own translation for the language in use, kept so the next switch can remove it.
_qt_translator: QTranslator | None = None


def system_language(locale_name: str | None = None) -> str:
    """The language the window starts in when none was chosen: Arabic on an Arabic system.

    *locale_name* is a Qt locale name such as ``"ar_EG"``; the default reads the
    system's. Any language the window has no table for falls back to English.
    """
    name = locale_name if locale_name is not None else QLocale.system().name()
    return "ar" if name.lower().startswith("ar") else "en"


def initial_language(prefs: Prefs, locale_name: str | None = None) -> str:
    """The language chosen at the foot of the home window, else the system's."""
    return prefs.language or system_language(locale_name)


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
    # After the translator: installing one may set a direction of its own.
    app.setLayoutDirection(
        Qt.LayoutDirection.RightToLeft if i18n.is_rtl(code) else Qt.LayoutDirection.LeftToRight
    )

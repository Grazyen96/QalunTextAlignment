"""Choosing the window's language and putting the app into it."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QSpinBox  # noqa: E402

from qurantext.gui import i18n  # noqa: E402
from qurantext.gui.language import apply_language, initial_language, system_language  # noqa: E402
from qurantext.gui.prefs import Prefs  # noqa: E402


def _prefs(tmp_path):
    return Prefs(QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat))


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("ar_EG", "ar"),
        ("ar", "ar"),
        ("ar-SA", "ar"),  # a UI language, as uiLanguages() spells it
        ("ar_SA", "ar"),
        ("en-US", "en"),
        ("de_DE", "en"),
        ("arn-CL", "en"),  # Mapuche starts with "ar" but is not Arabic
        ("C", "en"),
    ],
)
def test_the_system_locale_picks_the_default(name, code) -> None:
    assert system_language(name) == code


class _Locale:
    """Stands in for ``QLocale.system()``: a region format and a list of UI languages."""

    def __init__(self, name: str, ui_languages: list[str]) -> None:
        self._name, self._ui = name, ui_languages

    def name(self) -> str:
        return self._name

    def uiLanguages(self) -> list[str]:  # noqa: N802 - Qt's name
        return self._ui


def test_the_default_reads_the_ui_language_not_the_region_format() -> None:
    """An English Windows with Saudi regional settings starts in English, and back."""
    from qurantext.gui.language import _ui_language_name

    assert _ui_language_name(_Locale("ar_SA", ["en-US", "ar-SA"])) == "en-US"
    assert system_language(_ui_language_name(_Locale("ar_SA", ["en-US"]))) == "en"
    assert system_language(_ui_language_name(_Locale("en_US", ["ar-SA"]))) == "ar"
    assert _ui_language_name(_Locale("ar_EG", [])) == "ar_EG", "no UI languages: the name"


def test_every_test_starts_under_the_c_locale(qt_app) -> None:
    """Even the first of a run: the autouse reset runs before the test, not only after."""
    assert QLocale().name() == QLocale.c().name()
    assert QApplication.layoutDirection() == Qt.LayoutDirection.LeftToRight


def test_a_chosen_language_wins_over_the_system(tmp_path) -> None:
    prefs = _prefs(tmp_path)
    assert initial_language(prefs, "ar_SA") == "ar"
    prefs.language = "en"
    assert initial_language(prefs, "ar_SA") == "en"


def test_applying_arabic_mirrors_the_app_and_back(qt_app) -> None:
    apply_language(QApplication.instance(), "ar")
    assert i18n.current_language() == "ar"
    assert QApplication.layoutDirection() == Qt.LayoutDirection.RightToLeft
    apply_language(QApplication.instance(), "en")
    assert i18n.current_language() == "en"
    assert QApplication.layoutDirection() == Qt.LayoutDirection.LeftToRight


def test_an_unknown_language_changes_nothing(qt_app) -> None:
    with pytest.raises(ValueError):
        apply_language(QApplication.instance(), "xx")
    assert i18n.current_language() == "en"
    assert QApplication.layoutDirection() == Qt.LayoutDirection.LeftToRight


def test_numbers_stay_western_in_arabic(qt_app) -> None:
    """On an Egyptian-Arabic system Qt would draw "٢٨٦"; the window draws "286"."""

    def spin_box_text() -> str:
        box = QSpinBox()
        box.setRange(0, 300)
        box.setValue(286)
        return box.text()

    before = QLocale()
    QLocale.setDefault(QLocale("ar_EG"))
    try:
        assert spin_box_text() != "286", "the test machine's Qt must draw Arabic digits here"
        apply_language(QApplication.instance(), "ar")
        assert spin_box_text() == "286"
    finally:
        QLocale.setDefault(before)


_QT_TRANSLATIONS = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))


@pytest.mark.skipif(
    not (_QT_TRANSLATIONS / "qtbase_ar.qm").is_file(),
    reason=f"Qt's Arabic translation (qtbase_ar.qm) is not in {_QT_TRANSLATIONS}",
)
def test_qt_own_buttons_follow_the_language(qt_app) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    apply_language(QApplication.instance(), "ar")
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    assert box.button(QDialogButtonBox.StandardButton.Cancel).text() != "Cancel"

    apply_language(QApplication.instance(), "en")
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    assert box.button(QDialogButtonBox.StandardButton.Cancel).text().replace("&", "") == "Cancel"

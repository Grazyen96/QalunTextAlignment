"""Fixtures shared across test modules."""

from __future__ import annotations

import pytest

from qurantext.data.quran_db import build_quran_db
from tests.media_helpers import QURAN_FILE


def _reset_to_english() -> None:
    """English, left to right, Qt's own buttons in English, and Western digits."""
    from qurantext.gui import i18n

    i18n.set_language("en")
    try:
        from PySide6.QtWidgets import QApplication

        from qurantext.gui.language import apply_language
    except ModuleNotFoundError:
        return
    app = QApplication.instance()
    if app is not None:
        # Also removes Qt's own translation, sets the direction back and the C locale.
        apply_language(app, "en")


@pytest.fixture(autouse=True)
def _english_left_to_right():
    """Every test starts, and leaves, in English laid out left to right, with Qt's buttons too.

    Reset before the test as well as after: the first test of a run would
    otherwise run under the system's own locale (a comma for the decimal point
    on some machines) and every later one under the C locale, so a test could
    pass or fail by its place in the order. A test that switches language and
    then fails would otherwise leave every later test reading Arabic. Qt's part
    needs the ``QApplication``, which a Qt test's module-scoped ``qt_app`` has
    already made when this runs (pytest sets up the wider scope first).
    """
    _reset_to_english()
    yield
    _reset_to_english()


#: The application properties ``gui.theme.apply_theme`` sets; restored after every test.
_THEME_PROPERTIES = (
    "qalun.tokens",
    "qalun.theme_mode",
    "qalun.fusion_set",
    "qalun.scheme_connected",
)


@pytest.fixture(autouse=True)
def _theme_does_not_leak():
    """Every test leaves the application's palette, sheet, style and theme as it found them.

    ``apply_theme`` sets all of them on the one ``QApplication`` the suite
    shares; without this, a test that measures a layout passes or fails by
    which theme test ran before it. A test that needs the theme applies it
    itself, as the app does at start-up.
    """
    try:
        from PySide6.QtWidgets import QApplication
    except ModuleNotFoundError:
        yield
        return
    app = QApplication.instance()
    if app is None:
        yield
        return
    from PySide6.QtGui import QPalette

    palette = QPalette(app.palette())
    sheet = app.styleSheet()
    style_name = app.style().objectName()
    properties = {name: app.property(name) for name in _THEME_PROPERTIES}
    yield
    if app.styleSheet() != sheet:
        app.setStyleSheet(sheet)
    if app.style().objectName() != style_name and style_name:
        app.setStyle(style_name)
    if app.palette() != palette:
        app.setPalette(palette)
    for name, value in properties.items():
        app.setProperty(name, value)
    try:
        from qurantext.gui.icons import clear_cache
    except ImportError:
        return
    clear_cache()


@pytest.fixture()
def no_basmala(monkeypatch):
    """Render without the basmala splice.

    input/basmala/basmala.mp3 is the user's own media and is not in the
    repository, so a test that depends on it passes locally and fails on a
    fresh clone. Pinning the setting makes these deterministic either way.
    """
    from qurantext.config.settings import get_settings

    monkeypatch.setenv("QURANTEXT_VIDEO_PREPEND_BASMALA", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def no_default_job_dirs(monkeypatch, tmp_path_factory):
    """Keep the job list away from the checkout's real ``output/`` folders.

    ``JobListPanel`` (and so ``MainWindow``) scans ``catalog.default_job_dirs()``
    on top of ``Prefs.job_dirs``; left live, a test counting rows fails as soon
    as the person running it has a job of their own in ``output/``. Opt in from
    every fixture or test that builds either.

    The list's reads also make each job's thumbnail under the user's cache
    directory; they go to a throwaway folder here, not the person's own cache.
    """
    from qurantext.jobs import catalog

    monkeypatch.setattr(catalog, "default_job_dirs", lambda: [])
    cache = tmp_path_factory.getbasetemp() / "user-cache"
    monkeypatch.setattr("qurantext.gui.home.job_list.user_cache_dir", lambda: cache)


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    """A word-level store built from the shipped Quran text, once per module."""
    path = tmp_path_factory.mktemp("store") / "quran.sqlite"
    build_quran_db(QURAN_FILE, path)
    return path


@pytest.fixture(scope="module")
def qt_app():
    """One QApplication for widget tests; skipped where Qt is not installed."""
    pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def settings(tmp_path):
    """A ``QSettings`` on an INI file under tmp_path: never the person's real settings."""
    pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")
    from PySide6.QtCore import QSettings

    return QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)


@pytest.fixture()
def prefs(settings):
    """``Prefs`` over :func:`settings` (modules that scan job folders define their own)."""
    from qurantext.gui.prefs import Prefs

    return Prefs(settings)

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
def no_default_job_dirs(monkeypatch):
    """Keep the job list away from the checkout's real ``output/`` folders.

    ``JobListPanel`` (and so ``MainWindow``) scans ``catalog.default_job_dirs()``
    on top of ``Prefs.job_dirs``; left live, a test counting rows fails as soon
    as the person running it has a job of their own in ``output/``. Opt in from
    every fixture or test that builds either.
    """
    from qurantext.jobs import catalog

    monkeypatch.setattr(catalog, "default_job_dirs", lambda: [])


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

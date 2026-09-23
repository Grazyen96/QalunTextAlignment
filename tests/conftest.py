"""Fixtures shared across test modules."""

from __future__ import annotations

import pytest

from qurantext.data.quran_db import build_quran_db
from tests.media_helpers import QURAN_FILE


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

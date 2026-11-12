"""Tests for the citation n-gram index (data.citation_index)."""

from __future__ import annotations

import pytest

from qurantext.config.paths import DEFAULT_QURAN_PATH
from qurantext.data.quran_db import build_quran_db, connect

QURAN_FILE = DEFAULT_QURAN_PATH

pytestmark = pytest.mark.skipif(not QURAN_FILE.exists(), reason="shipped Quran file not present")


@pytest.fixture(scope="module")
def db(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = tmp_path_factory.mktemp("data") / "quran.sqlite"
    build_quran_db(QURAN_FILE, path)
    return str(path)


def test_index_is_populated_and_recorded(db: str) -> None:
    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM citation_ngrams").fetchone()[0] > 0
    assert (
        conn.execute("SELECT value FROM meta WHERE key = 'citation_ngram_n'").fetchone()[0] == "3"
    )


def test_madani_numbering_ayat_al_kursi(db: str) -> None:
    # In this file's Madani counting Ayat al-Kursi is 2:253 (not the Kufi 2:255).
    conn = connect(db)
    norm = conn.execute("SELECT text_norm FROM ayat WHERE id = '2:253'").fetchone()["text_norm"]
    assert norm.startswith("الله لا اله الا هو الحي القيوم")

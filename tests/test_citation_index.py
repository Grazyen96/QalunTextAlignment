"""Tests for the citation n-gram index (data.citation_index)."""

from __future__ import annotations

import pytest

from qurantext.config.paths import DEFAULT_QURAN_PATH
from qurantext.data.citation_index import find_candidate_ayat
from qurantext.data.quran_db import build_quran_db, connect

QURAN_FILE = DEFAULT_QURAN_PATH

pytestmark = pytest.mark.skipif(not QURAN_FILE.exists(), reason="shipped Quran file not present")


@pytest.fixture(scope="module")
def db(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = tmp_path_factory.mktemp("data") / "quran.sqlite"
    build_quran_db(QURAN_FILE, path)
    return str(path)


def _ayah_text(conn, ayah_id: str) -> str:
    return conn.execute("SELECT text_raw FROM ayat WHERE id = ?", (ayah_id,)).fetchone()["text_raw"]


def test_index_is_populated_and_recorded(db: str) -> None:
    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM citation_ngrams").fetchone()[0] > 0
    assert (
        conn.execute("SELECT value FROM meta WHERE key = 'citation_ngram_n'").fetchone()[0] == "3"
    )


@pytest.mark.parametrize("ayah_id", ["1:1", "1:4", "2:253", "112:1", "55:11", "36:40"])
def test_exact_ayah_text_pins_its_own_ayah(db: str, ayah_id: str) -> None:
    """Looking up an ayah's own text must rank that ayah top (full n-gram hits)."""
    conn = connect(db)
    surah, ayah = (int(p) for p in ayah_id.split(":"))
    results = find_candidate_ayat(conn, _ayah_text(conn, ayah_id), limit=5)
    assert results, f"no candidates for {ayah_id}"
    assert {"surah_num": surah, "ayah_num": ayah} in [
        {"surah_num": r["surah_num"], "ayah_num": r["ayah_num"]} for r in results
    ]
    # Its own text yields the maximum possible hits → it must tie for the top rank.
    top_hits = results[0]["hits"]
    assert any(
        r["surah_num"] == surah and r["ayah_num"] == ayah and r["hits"] == top_hits for r in results
    )


def test_madani_numbering_ayat_al_kursi(db: str) -> None:
    # In this file's Madani counting Ayat al-Kursi is 2:253 (not the Kufi 2:255).
    conn = connect(db)
    norm = conn.execute("SELECT text_norm FROM ayat WHERE id = '2:253'").fetchone()["text_norm"]
    assert norm.startswith("الله لا اله الا هو الحي القيوم")


def test_recurring_refrain_returns_all_occurrences(db: str) -> None:
    # The Ar-Rahman refrain appears many times; its phrase must hit many ayat.
    conn = connect(db)
    results = find_candidate_ayat(conn, _ayah_text(conn, "55:14"), limit=40)
    refrain = [r for r in results if r["surah_num"] == 55]
    assert len(refrain) >= 25


def test_non_quran_text_returns_nothing(db: str) -> None:
    conn = connect(db)
    assert find_candidate_ayat(conn, "هذا كلام ليس من القران ابدا قطعا") == []


def test_min_hits_filters(db: str) -> None:
    conn = connect(db)
    text = _ayah_text(conn, "2:253")  # long ayah → many n-grams
    loose = find_candidate_ayat(conn, text, min_hits=1, limit=50)
    strict = find_candidate_ayat(conn, text, min_hits=3, limit=50)
    assert len(strict) <= len(loose)
    assert all(r["hits"] >= 3 for r in strict)


def test_short_text_below_n_returns_nothing(db: str) -> None:
    conn = connect(db)
    assert find_candidate_ayat(conn, "الله", n=3) == []

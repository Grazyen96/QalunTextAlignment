"""Tests for the SQLite store builder (data.quran_db)."""

from __future__ import annotations

import sqlite3

import pytest

from qurantext.config.paths import QURAN_INPUT_DIR
from qurantext.data.quran_db import (
    build_quran_db,
    connect,
    db_matches_source,
    ensure_quran_db,
)

QURAN_FILE = QURAN_INPUT_DIR / "UthmanicQaloon1-Ver05.txt"

pytestmark = pytest.mark.skipif(
    not QURAN_FILE.exists(), reason="shipped Quran file not present"
)


@pytest.fixture(scope="module")
def db(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = tmp_path_factory.mktemp("data") / "quran.sqlite"
    build_quran_db(QURAN_FILE, path)
    return str(path)


def test_meta_records_provenance(db: str) -> None:
    conn = connect(db)
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
    assert meta["schema_version"] == "2"
    assert meta["counting"] == "madani"
    assert meta["citation_ngram_n"] == "3"
    assert meta["source_file"] == QURAN_FILE.name
    assert len(meta["source_sha256"]) == 64
    assert meta["data_version"] == meta["source_sha256"][:12]
    # Counts in meta agree with the actual tables.
    assert int(meta["surah_count"]) == conn.execute(
        "SELECT COUNT(*) FROM surahs"
    ).fetchone()[0]
    assert int(meta["word_count"]) == conn.execute(
        "SELECT COUNT(*) FROM words"
    ).fetchone()[0]


def test_table_shapes(db: str) -> None:
    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM surahs").fetchone()[0] == 114
    assert conn.execute("SELECT COUNT(*) FROM ayat").fetchone()[0] == 6214
    # IDs are unique (primary keys) and word numbering is sane.
    n_words = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    n_ids = conn.execute("SELECT COUNT(DISTINCT id) FROM words").fetchone()[0]
    assert n_words == n_ids


def test_referential_integrity(db: str) -> None:
    conn = connect(db)
    # Every word joins to a real ayah; every ayah to a real surah.
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM words w LEFT JOIN ayat a ON w.ayah_id = a.id"
            " WHERE a.id IS NULL"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM ayat a LEFT JOIN surahs s ON a.surah_num = s.surah_num"
            " WHERE s.surah_num IS NULL"
        ).fetchone()[0]
        == 0
    )
    # ayat.word_count matches the actual rows in words.
    mismatches = conn.execute(
        "SELECT a.id FROM ayat a"
        " JOIN (SELECT ayah_id, COUNT(*) n FROM words GROUP BY ayah_id) w"
        "   ON w.ayah_id = a.id"
        " WHERE a.word_count != w.n"
    ).fetchall()
    assert mismatches == []


def test_store_is_read_only(db: str) -> None:
    conn = connect(db)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM words")


def test_db_matches_source_detects_staleness(tmp_path) -> None:
    path = tmp_path / "quran.sqlite"
    assert db_matches_source(path, QURAN_FILE, ngram_n=3) is False  # missing
    build_quran_db(QURAN_FILE, path, ngram_n=3)
    assert db_matches_source(path, QURAN_FILE, ngram_n=3) is True
    # A different n-gram length is stale even though the source matches.
    assert db_matches_source(path, QURAN_FILE, ngram_n=2) is False


def test_ensure_quran_db_builds_then_reuses(tmp_path) -> None:
    path = tmp_path / "quran.sqlite"
    assert not path.exists()
    conn = ensure_quran_db(QURAN_FILE, path)  # builds
    conn.close()
    assert path.exists()
    before = path.stat().st_mtime_ns
    conn = ensure_quran_db(QURAN_FILE, path)  # current → no rebuild
    conn.close()
    assert path.stat().st_mtime_ns == before


def test_build_is_deterministic(tmp_path) -> None:
    a = tmp_path / "a.sqlite"
    b = tmp_path / "b.sqlite"
    sa = build_quran_db(QURAN_FILE, a)
    sb = build_quran_db(QURAN_FILE, b)
    # Same source → same data version and identical row counts.
    assert sa["data_version"] == sb["data_version"]
    assert (sa["surahs"], sa["ayat"], sa["words"]) == (sb["surahs"], sb["ayat"], sb["words"])

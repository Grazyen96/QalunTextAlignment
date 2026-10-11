"""Tests for the SQLite store builder (data.quran_db)."""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from qurantext.config.paths import DEFAULT_QURAN_PATH
from qurantext.core.arabic import ayah_text_with_marker
from qurantext.data.quran_db import (
    ayah_range_card,
    build_quran_db,
    connect,
    db_matches_source,
    ensure_quran_db,
    list_surahs,
    surah_ayah_count,
)

QURAN_FILE = DEFAULT_QURAN_PATH

pytestmark = pytest.mark.skipif(not QURAN_FILE.exists(), reason="shipped Quran file not present")


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
    assert int(meta["surah_count"]) == conn.execute("SELECT COUNT(*) FROM surahs").fetchone()[0]
    assert int(meta["word_count"]) == conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]


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
            "SELECT COUNT(*) FROM words w LEFT JOIN ayat a ON w.ayah_id = a.id WHERE a.id IS NULL"
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


@pytest.mark.parametrize("dirname", ["plain", "has#hash", "has?question", "الفرقان"])
def test_connect_handles_uri_significant_characters_in_path(tmp_path, dirname) -> None:
    """A '#' or '?' in the path must not truncate the SQLite URI.

    These characters are legal in filenames on Windows, macOS and Linux, and an
    installer or a user's own folder can easily contain one. Interpolating the
    raw path into the URI silently opened a different, empty database instead of
    raising, so the failure surfaced much later as missing ayat.
    """
    directory = tmp_path / dirname
    directory.mkdir()
    path = directory / "quran.sqlite"
    build_quran_db(QURAN_FILE, path)

    conn = connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM ayat").fetchone()[0] > 0
    finally:
        conn.close()


def test_list_surahs_gives_a_picker_everything_it_needs(tmp_path) -> None:
    """A range picker needs number, name and ayah count for all 114."""
    path = tmp_path / "quran.sqlite"
    build_quran_db(QURAN_FILE, path)
    conn = connect(path)
    try:
        rows = list_surahs(conn)
        assert len(rows) == 114
        assert [r["surah_num"] for r in rows] == list(range(1, 115))
        assert all(r["name"] and r["ayah_count"] > 0 for r in rows)
        assert surah_ayah_count(conn, 1) == 7
        with pytest.raises(ValueError, match="expected 1-114"):
            surah_ayah_count(conn, 999)
    finally:
        conn.close()


def _range_card(db: str | Path, surah: object, start: object, end: object) -> dict:
    """``ayah_range_card`` on a connection that is closed again, whatever happens."""
    with closing(connect(db)) as conn:
        return ayah_range_card(conn, surah, start, end)


def test_a_single_ayah_card_matches_detection(db: str) -> None:
    with closing(connect(db)) as conn:
        card = ayah_range_card(conn, 25, 7, 7)
        raw = conn.execute(
            "SELECT text_raw FROM ayat WHERE surah_num = 25 AND ayah_num = 7"
        ).fetchone()["text_raw"]
        name = conn.execute("SELECT name FROM surahs WHERE surah_num = 25").fetchone()["name"]
    assert card == {
        "surah_num": 25,
        "surah_name": name,
        "from_ayah": 7,
        "to_ayah": 7,
        "text": ayah_text_with_marker(raw, 7),
        "full_text": ayah_text_with_marker(raw, 7),
    }


def test_a_range_joins_ayat_with_newlines_like_detection(db: str) -> None:
    card = _range_card(db, 25, 7, 9)
    lines = card["full_text"].split("\n")
    assert len(lines) == 3
    assert lines[0].endswith(" ٧") and lines[2].endswith(" ٩")
    assert card["text"] == card["full_text"]


@pytest.mark.parametrize(
    "surah, start, end", [(0, 1, 1), (115, 1, 1), (25, 0, 1), (25, 9, 7), (25, 1, 78)]
)
def test_invalid_ranges_raise(db: str, surah: int, start: int, end: int) -> None:
    with pytest.raises(ValueError):
        _range_card(db, surah, start, end)


@pytest.mark.parametrize("surah, start, end", [(25, 7.5, 8), (25.0, 7, 7), (25, True, 1)])
def test_numbers_that_are_not_whole_raise(
    db: str, surah: object, start: object, end: object
) -> None:
    with pytest.raises(ValueError):
        _range_card(db, surah, start, end)


def test_a_store_missing_an_ayah_raises_rather_than_return_short_text(
    db: str, tmp_path: Path
) -> None:
    broken = tmp_path / "quran.sqlite"
    shutil.copyfile(db, broken)
    with closing(sqlite3.connect(broken)) as conn:
        conn.execute("DELETE FROM ayat WHERE surah_num = 25 AND ayah_num = 8")
        conn.commit()
    assert _range_card(broken, 25, 7, 7)["from_ayah"] == 7
    with pytest.raises(ValueError, match="missing ayat"):
        _range_card(broken, 25, 7, 9)

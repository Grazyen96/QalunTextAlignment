"""Build the versioned, read-only SQLite store from the certified Qalun text.

This is the on-device "static data layer" from the architecture doc (§3, §5):
a single-file, zero-config SQLite database keyed end-to-end by the stable
``surah:ayah:word`` identity. It is the foundation everything else joins onto —
alignment timestamps, pre-shaped assets and the citation index all reference the
same IDs.

Tables
------
``meta``    one-row-per-key build provenance (schema version, source checksum,
            counting system, builder version). The checksum is the data version:
            same source file → byte-identical store, which is what "immutable,
            versioned release" needs.
``surahs``  one row per surah (114), with Madani ayah/word counts and start page.
``ayat``    one row per ayah, id ``surah:ayah``, raw + normalized text, word
            count, and the mushaf page span it covers.
``words``   one row per word, id ``surah:ayah:word``, raw + normalized text, and
            the mushaf page/line it sits on.

Counting is **Madani** throughout — it is inherent to the shipped Qalun file's
own ayah markers, not imposed here.

Columns that need an external metadata pack (revelation type, juz, hizb, sajda)
exist in the schema but are left NULL; the ``metadata_pending`` meta key records
that. Populating them is a later step — better NULL than wrong.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

from qurantext import __version__
from qurantext.core.arabic import normalize_detection_ar
from qurantext.core.quran_parser import parse_ayat
from qurantext.core.quran_structure import parse_words
from qurantext.data.citation_index import DEFAULT_NGRAM_N, build_citation_index

SCHEMA_VERSION = 2
COUNTING = "madani"
# Metadata available in the schema but not yet populated (needs a metadata pack).
METADATA_PENDING = "surahs.revelation_type, ayat.juz, ayat.hizb, ayat.sajda"

_SCHEMA = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE surahs (
    surah_num       INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    name_norm       TEXT NOT NULL,
    ayah_count      INTEGER NOT NULL,
    word_count      INTEGER NOT NULL,
    page_start      INTEGER NOT NULL,
    revelation_type TEXT          -- NULL until a metadata pack is loaded
);

CREATE TABLE ayat (
    id         TEXT PRIMARY KEY,   -- 'surah:ayah'
    surah_num  INTEGER NOT NULL REFERENCES surahs(surah_num),
    ayah_num   INTEGER NOT NULL,
    text_raw   TEXT NOT NULL,
    text_norm  TEXT NOT NULL,
    word_count INTEGER NOT NULL,
    page_start INTEGER NOT NULL,
    page_end   INTEGER NOT NULL,
    juz        INTEGER,            -- NULL until a metadata pack is loaded
    hizb       INTEGER,            -- NULL until a metadata pack is loaded
    sajda      INTEGER             -- NULL until a metadata pack is loaded
);

CREATE TABLE words (
    id         TEXT PRIMARY KEY,   -- 'surah:ayah:word'
    surah_num  INTEGER NOT NULL REFERENCES surahs(surah_num),
    ayah_num   INTEGER NOT NULL,
    word_num   INTEGER NOT NULL,
    ayah_id    TEXT NOT NULL REFERENCES ayat(id),
    text_raw   TEXT NOT NULL,
    text_norm  TEXT NOT NULL,
    page       INTEGER NOT NULL,
    line       INTEGER NOT NULL
);

CREATE INDEX idx_words_ayah  ON words(surah_num, ayah_num, word_num);
CREATE INDEX idx_ayat_surah  ON ayat(surah_num, ayah_num);
"""


class QuranDataError(RuntimeError):
    """Raised when the structural parse fails its consistency check."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _aggregate(words: list[dict]) -> tuple[list[dict], list[dict]]:
    """Roll per-word records up into ordered ayah and surah rows."""
    ayat: dict[str, dict] = {}
    surahs: dict[int, dict] = {}

    for w in words:
        ayah_id = f"{w['surah_num']}:{w['ayah_num']}"
        ayah = ayat.get(ayah_id)
        if ayah is None:
            ayah = {
                "id": ayah_id,
                "surah_num": w["surah_num"],
                "ayah_num": w["ayah_num"],
                "words_raw": [],
                "page_start": w["page"],
                "page_end": w["page"],
            }
            ayat[ayah_id] = ayah
        ayah["words_raw"].append(w["text_raw"])
        ayah["page_start"] = min(ayah["page_start"], w["page"])
        ayah["page_end"] = max(ayah["page_end"], w["page"])

        surah = surahs.get(w["surah_num"])
        if surah is None:
            surahs[w["surah_num"]] = {
                "surah_num": w["surah_num"],
                "name": w["surah_name"],
                "name_norm": normalize_detection_ar(w["surah_name"]),
                "ayah_nums": set(),
                "word_count": 0,
                "page_start": w["page"],
            }
            surah = surahs[w["surah_num"]]
        surah["ayah_nums"].add(w["ayah_num"])
        surah["word_count"] += 1
        surah["page_start"] = min(surah["page_start"], w["page"])

    ayah_rows = []
    for ayah in ayat.values():
        text_raw = " ".join(ayah["words_raw"])
        ayah_rows.append(
            {
                "id": ayah["id"],
                "surah_num": ayah["surah_num"],
                "ayah_num": ayah["ayah_num"],
                "text_raw": text_raw,
                "text_norm": normalize_detection_ar(text_raw),
                "word_count": len(ayah["words_raw"]),
                "page_start": ayah["page_start"],
                "page_end": ayah["page_end"],
            }
        )

    surah_rows = [
        {
            "surah_num": s["surah_num"],
            "name": s["name"],
            "name_norm": s["name_norm"],
            "ayah_count": len(s["ayah_nums"]),
            "word_count": s["word_count"],
            "page_start": s["page_start"],
        }
        for s in surahs.values()
    ]
    return surah_rows, ayah_rows


def _verify_against_parser(quran_path: str | Path, ayah_rows: list[dict]) -> None:
    """Guard: the word-level rollup must reproduce parse_ayat exactly.

    parse_ayat is golden-tested. If the structural parse ever drifts from it
    (different ayah set, or a word added/dropped) this fails the build loudly
    instead of shipping a corrupt store.
    """
    expected = parse_ayat(quran_path)
    expected_by_id = {f"{a['surah_num']}:{a['ayah_num']}": a["text_raw"] for a in expected}
    got_by_id = {a["id"]: a["text_raw"] for a in ayah_rows}

    if expected_by_id.keys() != got_by_id.keys():
        missing = sorted(expected_by_id.keys() - got_by_id.keys())
        extra = sorted(got_by_id.keys() - expected_by_id.keys())
        raise QuranDataError(
            f"ayah set mismatch vs parse_ayat: missing={missing[:5]} extra={extra[:5]}"
        )
    for ayah_id, text in expected_by_id.items():
        if got_by_id[ayah_id] != text:
            raise QuranDataError(
                f"text mismatch vs parse_ayat at {ayah_id}: {got_by_id[ayah_id]!r} != {text!r}"
            )


def _write_db(
    db_file: Path,
    *,
    surah_rows: list[dict],
    ayah_rows: list[dict],
    words: list[dict],
    meta: dict[str, str],
    ngram_n: int,
) -> int:
    """Write all tables and build the citation index. Returns the n-gram count."""
    conn = sqlite3.connect(db_file)
    try:
        conn.executescript(_SCHEMA)
        conn.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            list(meta.items()),
        )
        conn.executemany(
            "INSERT INTO surahs(surah_num, name, name_norm, ayah_count, word_count, page_start)"
            " VALUES (:surah_num, :name, :name_norm, :ayah_count, :word_count, :page_start)",
            surah_rows,
        )
        conn.executemany(
            "INSERT INTO ayat(id, surah_num, ayah_num, text_raw, text_norm, word_count,"
            " page_start, page_end)"
            " VALUES (:id, :surah_num, :ayah_num, :text_raw, :text_norm, :word_count,"
            " :page_start, :page_end)",
            ayah_rows,
        )
        conn.executemany(
            "INSERT INTO words(id, surah_num, ayah_num, word_num, ayah_id, text_raw, text_norm,"
            " page, line)"
            " VALUES (:id, :surah_num, :ayah_num, :word_num, :ayah_id, :text_raw, :text_norm,"
            " :page, :line)",
            [{**w, "ayah_id": f"{w['surah_num']}:{w['ayah_num']}"} for w in words],
        )
        conn.commit()
        # Built after words exist, in the same atomic temp file.
        return build_citation_index(conn, n=ngram_n)
    finally:
        conn.close()


def build_quran_db(
    quran_path: str | Path,
    db_path: str | Path,
    *,
    verify: bool = True,
    ngram_n: int = DEFAULT_NGRAM_N,
) -> dict:
    """Build the SQLite store from *quran_path*, writing it to *db_path*.

    Also builds the citation n-gram index (§3-G) into the same store, so a
    single ``build-db`` produces a complete data layer. The store is built into
    a temp file in the destination directory and then atomically moved into
    place, so a failed build never leaves a half-written database. Returns a
    summary dict (counts + data version).
    """
    quran_path = Path(quran_path).expanduser().resolve()
    db_path = Path(db_path).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    words = parse_words(quran_path)
    if not words:
        raise QuranDataError(f"no words parsed from {quran_path}")
    surah_rows, ayah_rows = _aggregate(words)

    if verify:
        _verify_against_parser(quran_path, ayah_rows)

    source_sha256 = _sha256_file(quran_path)
    meta = {
        "schema_version": str(SCHEMA_VERSION),
        "counting": COUNTING,
        "source_file": quran_path.name,
        "source_sha256": source_sha256,
        "data_version": source_sha256[:12],
        "built_with": __version__,
        "metadata_pending": METADATA_PENDING,
        "citation_ngram_n": str(ngram_n),
        "surah_count": str(len(surah_rows)),
        "ayah_count": str(len(ayah_rows)),
        "word_count": str(len(words)),
    }

    tmp_file = db_path.with_name(f"{db_path.name}.tmp")
    if tmp_file.exists():
        tmp_file.unlink()
    ngram_count = _write_db(
        tmp_file,
        surah_rows=surah_rows,
        ayah_rows=ayah_rows,
        words=words,
        meta=meta,
        ngram_n=ngram_n,
    )
    os.replace(tmp_file, db_path)

    return {
        "db_path": str(db_path),
        "surahs": len(surah_rows),
        "ayat": len(ayah_rows),
        "words": len(words),
        "ngrams": ngram_count,
        "data_version": meta["data_version"],
    }


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open the store read-only with a row factory for convenient querying."""
    db_path = Path(db_path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Quran DB not found at {db_path}; build it first.")
    # Build the URI with Path.as_uri() rather than an f-string: it percent-encodes
    # the characters that are significant in a URI and handles Windows drive
    # letters. Interpolating the raw path let a '#' or '?' anywhere in it (legal in
    # filenames on every target platform) truncate the URI, so SQLite silently
    # opened a different, empty database instead of failing.
    conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def db_matches_source(db_path: str | Path, quran_path: str | Path, *, ngram_n: int) -> bool:
    """True if the store at *db_path* is current for *quran_path* and *ngram_n*.

    Checks the recorded schema version, source checksum and citation n-gram
    length so a stale or differently-built store is rebuilt rather than queried
    with the wrong index. Any read error (missing/corrupt/old store) returns
    False so the caller rebuilds.
    """
    db_path = Path(db_path).expanduser()
    if not db_path.exists():
        return False
    try:
        conn = connect(db_path)
        try:
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        finally:
            conn.close()
    except (sqlite3.DatabaseError, FileNotFoundError):
        return False
    return (
        meta.get("schema_version") == str(SCHEMA_VERSION)
        and meta.get("source_sha256") == _sha256_file(Path(quran_path).expanduser().resolve())
        and meta.get("citation_ngram_n") == str(ngram_n)
    )


def ensure_quran_db(
    quran_path: str | Path,
    db_path: str | Path,
    *,
    ngram_n: int = DEFAULT_NGRAM_N,
) -> sqlite3.Connection:
    """Return a read-only connection to a store current for *quran_path*.

    Builds (or rebuilds) the store at *db_path* when it is missing or no longer
    matches the source text / n-gram length, then connects. Lets the lecture
    pipeline back candidate selection with the persisted citation index without
    requiring the user to run ``build-db`` first.
    """
    if not db_matches_source(db_path, quran_path, ngram_n=ngram_n):
        build_quran_db(quran_path, db_path, ngram_n=ngram_n)
    return connect(db_path)


def list_surahs(conn: sqlite3.Connection) -> list[dict]:
    """Every surah with its ayah count, for a picker to populate from.

    This is what lets a user say which surah and which ayat they recited instead
    of the pipeline guessing. Guessing cost roughly ten minutes of fuzzy scoring
    on a nineteen-minute recitation and had no way to say "I do not know" — the
    range finder returns its best candidate whatever the score.
    """
    rows = conn.execute(
        "SELECT surah_num, name, ayah_count FROM surahs ORDER BY surah_num"
    ).fetchall()
    return [
        {"surah_num": r["surah_num"], "name": r["name"], "ayah_count": r["ayah_count"]}
        for r in rows
    ]


def surah_ayah_count(conn: sqlite3.Connection, surah_num: int) -> int:
    """How many ayat a surah has, in the shipped text's own Madani counting."""
    row = conn.execute("SELECT ayah_count FROM surahs WHERE surah_num = ?", (surah_num,)).fetchone()
    if row is None:
        raise ValueError(f"No surah {surah_num} in the store (expected 1-114).")
    return int(row["ayah_count"])

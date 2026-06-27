"""Citation index: a pre-built normalized n-gram phrase index over all ayat.

This is component G of the data layer (architecture §3-G, used by the tafseer
builder in §7): to detect a quoted ayah in a dars transcript, slide a window
over the (ASR) transcript, normalize it the *same* way the index was normalized,
and look its phrases up here to get candidate ``surah:ayah`` hits.

Today ``lecture_matching`` rebuilds an equivalent word index in memory on every
run. This persists the index into the on-device store so the runtime queries it
instead of recomputing it, and so the same normalized phrase index is shared by
the recitation and tafseer paths.

The index is built over ``words.text_norm`` — which is exactly one normalized
token per word and 1:1 with ``word_num`` — so every n-gram points back to a
concrete ``surah:ayah:word`` start. n-grams never cross ayah boundaries (each
ayah is the retrieval unit; consecutive-ayah quotes are reassembled at detection
time by accumulating adjacent hits).

Normalization is :func:`qurantext.core.arabic.normalize_detection_ar` (no
diacritics, no tatweel, unified alef/ya/waw-hamza), already applied when the
store was built. Callers MUST normalize transcript windows the same way before
looking phrases up — :func:`normalize_phrase` does this.
"""

from __future__ import annotations

import sqlite3

from qurantext.core.arabic import normalize_detection_ar

DEFAULT_NGRAM_N = 3

_SCHEMA = """
CREATE TABLE citation_ngrams (
    gram       TEXT NOT NULL,     -- n normalized words joined by a single space
    surah_num  INTEGER NOT NULL,
    ayah_num   INTEGER NOT NULL,
    word_start INTEGER NOT NULL   -- word_num of the gram's first word (the surah:ayah:word anchor)
);
CREATE INDEX idx_citation_gram ON citation_ngrams(gram);
-- Speeds up the unigram inverted lookup (word -> positions) over the words table.
CREATE INDEX IF NOT EXISTS idx_words_norm ON words(text_norm);
"""


def build_citation_index(conn: sqlite3.Connection, n: int = DEFAULT_NGRAM_N) -> int:
    """Build the n-gram phrase index inside *conn*. Returns the n-gram row count.

    Idempotent: drops and rebuilds the table so a rebuild with a different *n*
    is clean. Must run after the ``words`` table is populated.
    """
    if n < 1:
        raise ValueError(f"n-gram size must be >= 1, got {n}")

    conn.execute("DROP TABLE IF EXISTS citation_ngrams")
    conn.executescript(_SCHEMA)

    rows: list[tuple[str, int, int, int]] = []
    cur = conn.execute(
        "SELECT surah_num, ayah_num, word_num, text_norm FROM words"
        " ORDER BY surah_num, ayah_num, word_num"
    )
    # Group consecutive rows by ayah and slide an n-word window within each ayah.
    ayah_key: tuple[int, int] | None = None
    buf: list[tuple[int, str]] = []  # (word_num, text_norm) for the current ayah

    def flush() -> None:
        for i in range(len(buf) - n + 1):
            window = buf[i : i + n]
            gram = " ".join(tok for _, tok in window)
            rows.append((gram, ayah_key[0], ayah_key[1], window[0][0]))

    for surah_num, ayah_num, word_num, text_norm in cur:
        key = (surah_num, ayah_num)
        if key != ayah_key:
            if ayah_key is not None:
                flush()
            ayah_key = key
            buf = []
        buf.append((word_num, text_norm))
    if ayah_key is not None:
        flush()

    conn.executemany(
        "INSERT INTO citation_ngrams(gram, surah_num, ayah_num, word_start) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def normalize_phrase(text: str) -> list[str]:
    """Normalize *text* into the token list used by the index."""
    norm = normalize_detection_ar(text)
    return norm.split() if norm else []


def find_candidate_ayat(
    conn: sqlite3.Connection,
    text: str,
    *,
    n: int = DEFAULT_NGRAM_N,
    min_hits: int = 1,
    limit: int = 20,
) -> list[dict]:
    """Return candidate ayat for a transcript fragment, ranked by n-gram hits.

    Slides every n-gram of the normalized *text* against the index and counts how
    many distinct n-grams of *text* hit each ayah. This is a fast candidate
    filter — callers still fuzzy-score the survivors (see ``lecture_matching``).

    Each result: ``{surah_num, ayah_num, hits}`` with ``hits >= min_hits``.
    """
    tokens = normalize_phrase(text)
    if len(tokens) < n:
        return []

    grams = {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}
    if not grams:
        return []

    counts: dict[tuple[int, int], int] = {}
    for gram in grams:
        seen_for_gram: set[tuple[int, int]] = set()
        for surah_num, ayah_num in conn.execute(
            "SELECT surah_num, ayah_num FROM citation_ngrams WHERE gram = ?", (gram,)
        ):
            key = (surah_num, ayah_num)
            # Count each distinct gram at most once per ayah.
            if key not in seen_for_gram:
                seen_for_gram.add(key)
                counts[key] = counts.get(key, 0) + 1

    ranked = sorted(
        (
            {"surah_num": s, "ayah_num": a, "hits": h}
            for (s, a), h in counts.items()
            if h >= min_hits
        ),
        key=lambda r: (-r["hits"], r["surah_num"], r["ayah_num"]),
    )
    return ranked[:limit]

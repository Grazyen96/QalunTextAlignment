"""Word-level structural parse of the certified Qalun mushaf file.

`quran_parser.parse_ayat` returns ayah-level records. This module goes one level
finer: it walks the same shipped file and yields one record per *word*, carrying
a stable ``surah:ayah:word`` identity plus the mushaf **page** and **line** the
word physically sits on. That ID is the join key the whole target architecture
hangs off — alignment timestamps, pre-shaped assets and the citation index all
reference ``surah:ayah:word`` (see the architecture doc, §3 and §5).

The ayah-boundary semantics are deliberately identical to ``parse_ayat`` — it
reuses the same header/basmala/taʿawwudh predicates and the same inline
Arabic-Indic digit markers — so the set of ayat and their joined text match the
golden-tested parser exactly. The only thing added is positional metadata:

  * **page** — derived from the file's blank-line page breaks. Each run of
    non-empty lines between blank lines is one mushaf page (the shipped file lays
    the 604-page Madani mushaf out this way), numbered from 1.
  * **line** — the 1-based physical line within that page, counting every
    rendered line including surah headers and the standalone basmala, so it
    matches what a reader sees on the page.

Trailing content with no following ayah marker (the file's footer attribution
block) never flushes and is dropped, exactly as in ``parse_ayat``.
"""

from __future__ import annotations

import re
from pathlib import Path

from qurantext.core.arabic import arabic_indic_to_int, normalize_detection_ar
from qurantext.core.quran_parser import (
    _is_basmala,
    _is_surah_header,
    _is_taawwudh,
    is_ayah_marker,
    read_quran_text,
)

_ARABIC_LETTER_RE = re.compile(r"[ء-ي]")


def parse_words(quran_path: str | Path) -> list[dict]:
    """Parse the Qalun file into an ordered list of per-word records.

    Each record is a dict with::

        id          'surah:ayah:word'   (stable join key)
        surah_num   int                 (1-based, Madani order)
        surah_name  str                 (raw header text)
        ayah_num    int                 (1-based within surah, Madani counting)
        word_num    int                 (1-based within ayah)
        text_raw    str                 (the word as written, with diacritics)
        text_norm   str                 (detection-normalized form)
        page        int                 (1-based mushaf page)
        line        int                 (1-based physical line within the page)

    Words are emitted in mushaf order. A word's ``ayah_num`` is only known once
    its closing marker is reached, so words are buffered per ayah and assigned a
    1-based ``word_num`` when that ayah flushes.
    """
    lines = read_quran_text(quran_path).splitlines()

    records: list[dict] = []
    surah_num = 0
    surah_name = ""
    page = 0
    line_no = 0
    prev_blank = True  # so the first non-empty line opens page 1
    # Buffer of (word_raw, page, line) tuples for the ayah currently being read.
    buf: list[tuple[str, int, int]] = []

    def flush(ayah_num: int) -> None:
        for word_num, (word_raw, word_page, word_line) in enumerate(buf, start=1):
            records.append(
                {
                    "id": f"{surah_num}:{ayah_num}:{word_num}",
                    "surah_num": surah_num,
                    "surah_name": surah_name,
                    "ayah_num": ayah_num,
                    "word_num": word_num,
                    "text_raw": word_raw,
                    "text_norm": normalize_detection_ar(word_raw),
                    "page": word_page,
                    "line": word_line,
                }
            )
        buf.clear()

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            prev_blank = True
            continue

        if prev_blank:
            page += 1
            line_no = 0
            prev_blank = False
        line_no += 1

        stripped = line.strip()

        if _is_surah_header(stripped):
            buf.clear()
            surah_num += 1
            surah_name = stripped
            continue

        if _is_basmala(stripped) or _is_taawwudh(stripped):
            continue

        for token in stripped.split():
            if is_ayah_marker(token):
                flush(arabic_indic_to_int(token))
            elif _ARABIC_LETTER_RE.search(token):
                buf.append((token, page, line_no))

    # Any unflushed buffer (the footer block, which has no trailing marker) is
    # intentionally discarded — mirroring parse_ayat.
    return records

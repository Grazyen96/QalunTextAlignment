"""The bundled Mushaf text is KFGQPC Qaloon v10, laid out as the Ver05 file was.

Ver05 is no longer in the tree. What it parsed to is pinned here as digests,
taken from it once when v10 replaced it: v10 must give the same ayat, the same
text once normalised (apart from two words Ver05 ran together), and put every
word on the same mushaf page and line. See src/qurantext/assets/README.md.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from qurantext.config.paths import DEFAULT_QURAN_PATH
from qurantext.core.arabic import normalize_detection_ar
from qurantext.core.quran_parser import is_ayah_marker, parse_ayat
from qurantext.core.quran_structure import parse_words
from qurantext.data.quran_db import build_quran_db, ensure_quran_db

ROOT = Path(__file__).resolve().parents[1]
CONVERTER = ROOT / "tools" / "convert_mushaf_v10.py"

V10_NAME = "UthmanicQaloon1-v10.txt"
V10_SHA256 = "47b3ef5dd2b5a92bdead9506480051834f7eeeaea03051baf05e12be0d5c65ac"
VER05_SHA256 = "905389c1b9aa4c74233fc9abd118af4d88a8ddc7fae64f21a6eb8565fa406975"
# Taken from parsing UthmanicQaloon1-Ver05.txt (git show 6f2a1fe:src/qurantext/assets/quran/...).
VER05_AYAT = "35a784b66647737e90ea5caca83784ff784f019a2aac7a227b9baf11fb40fd70"
VER05_TEXT_NORM = "ab4b689fd4c5f1a3a503f0a0b0c2927bb44f48d2805b8c9b35d865bf14eaa688"
VER05_PAGE_LINES = "3a11e903e66e1731bd8c2eba193c532373e22f3f98d0c7e04077ad650068d580"
# Ver05 ran these words together; v10 writes them apart. Nothing else differs once normalised.
SPLIT_IN_V10 = {(41, 46): ("ما منا", "مامنا"), (41, 50): ("ونا بجانبه", "ونابجانبه")}
NBSP = chr(0xA0)
PAUSE = chr(0x06D6)  # small high ligature sad with lam with alef maksura
RUB_EL_HIZB = chr(0x06DE)


def _digest(lines) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def ayat() -> list[dict]:
    return parse_ayat(DEFAULT_QURAN_PATH)


@pytest.fixture(scope="module")
def by_id(ayat) -> dict[tuple[int, int], str]:
    return {(a["surah_num"], a["ayah_num"]): a["text_raw"] for a in ayat}


def test_the_bundled_text_is_the_converter_output() -> None:
    assert DEFAULT_QURAN_PATH.name == V10_NAME
    digest = hashlib.sha256(DEFAULT_QURAN_PATH.read_bytes()).hexdigest()
    assert digest == V10_SHA256, "regenerate it with tools/convert_mushaf_v10.py, never by hand"


def test_v10_has_the_same_ayat_as_ver05(ayat) -> None:
    assert len(ayat) == 6214
    assert _digest(f"{a['surah_num']}:{a['ayah_num']}" for a in ayat) == VER05_AYAT


def test_v10_normalises_to_the_ver05_text(ayat) -> None:
    lines = []
    for a in ayat:
        key = (a["surah_num"], a["ayah_num"])
        text = a["text_norm"]
        if key in SPLIT_IN_V10:
            apart, together = SPLIT_IN_V10[key]
            assert apart in text, key
            text = text.replace(apart, together)
        lines.append(f"{key[0]}:{key[1]}\t{text}")
    assert _digest(lines) == VER05_TEXT_NORM


def test_every_word_keeps_its_ver05_page_and_line() -> None:
    """The store's page and line columns come from the file's layout, which is Ver05's."""
    seen: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for word in parse_words(DEFAULT_QURAN_PATH):
        spots = seen.setdefault((word["surah_num"], word["ayah_num"]), [])
        if not spots or spots[-1] != (word["page"], word["line"]):
            spots.append((word["page"], word["line"]))
    lines = (
        f"{s}:{a}\t" + ",".join(f"{page}.{line}" for page, line in spots)
        for (s, a), spots in seen.items()
    )
    assert _digest(lines) == VER05_PAGE_LINES


def test_the_file_keeps_ver05s_encoding_and_conventions() -> None:
    raw = DEFAULT_QURAN_PATH.read_bytes()
    assert raw.startswith(b"\xff\xfe"), "UTF-16 LE with a byte-order mark, as Ver05"
    text = raw[2:].decode("utf-16-le")
    assert "\n" not in text.replace("\r\n", "") and "\r" not in text.replace("\r\n", "")
    assert NBSP not in text, "v10's no-break spaces are written as Ver05 writes them"
    for token in text.split():
        assert any("ء" <= ch <= "ي" for ch in token) or is_ayah_marker(token), token
    last = text.split("\r\n")
    assert last[-1] == "", "CRLF after the last line"
    assert normalize_detection_ar(last[-2]) == "من الجنة والناس" and last[-2].endswith(" ٦"), (
        "ends after An-Nas 114:6; the Ver05 footer is not carried over"
    )


def _word(text: str, norm: str) -> str:
    """The word of *text* that normalises to *norm*."""
    return next(word for word in text.split() if normalize_detection_ar(word) == norm)


def test_v10_carries_its_pause_marks(by_id) -> None:
    assert _word(by_id[(25, 59)], "الرحمن").endswith(PAUSE), "v10 adds a pause mark in 25:59"
    first = by_id[(2, 25)].split()[0]
    assert first[0] == RUB_EL_HIZB and normalize_detection_ar(first) == "ان", "۞ stays attached"
    tail = [normalize_detection_ar(word) for word in by_id[(41, 46)].split()[-4:-2]]
    assert tail == ["ما", "منا"]


def test_a_store_built_from_ver05_is_rebuilt_from_v10(tmp_path) -> None:
    db = tmp_path / "quran.sqlite"
    build_quran_db(DEFAULT_QURAN_PATH, db)
    conn = sqlite3.connect(db)
    try:
        conn.execute("UPDATE meta SET value = ? WHERE key = 'source_sha256'", (VER05_SHA256,))
        conn.execute(
            "UPDATE meta SET value = 'UthmanicQaloon1-Ver05.txt' WHERE key = 'source_file'"
        )
        conn.execute("UPDATE ayat SET text_raw = 'stale' WHERE id = '25:59'")
        conn.commit()
    finally:
        conn.close()

    conn = ensure_quran_db(DEFAULT_QURAN_PATH, db)
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        text = conn.execute("SELECT text_raw FROM ayat WHERE id = '25:59'").fetchone()[0]
        words = conn.execute("SELECT word_count FROM ayat WHERE id = '41:46'").fetchone()[0]
    finally:
        conn.close()
    assert meta["source_sha256"] == V10_SHA256
    assert meta["source_file"] == V10_NAME
    assert _word(text, "الرحمن").endswith(PAUSE)
    assert words == 28


# -- the converter ---------------------------------------------------------------


@pytest.fixture(scope="module")
def converter():
    spec = importlib.util.spec_from_file_location("convert_mushaf_v10", CONVERTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASMALA = "بِسْمِ اِ۬للَّهِ اِ۬لرَّحْمَٰنِ اِ۬لرَّحِيمِ"
VER05_SAMPLE = [
    "سُورَةُ الفَاتِحَةِ",
    BASMALA,
    "اِ۬لْحَمْدُ لِلهِ رَبِّ اِ۬لْعَٰلَمِينَ ١ ",
    "اَ۬لرَّحْمَٰنِ اِ۬لرَّحِيمِ ٢",
    "",
    "سُورَةُ النَّاسِ",
    BASMALA,
    " قُلْ أَعُوذُ عَلَيٰ ١ مَامِنَّا ",
    "مَلِكِ ٢",
    "",
    "78",
    "خط النسخ الحاسوبي ـ قالون ـ النسخة رقم ٠٥",
    "",
]


def _sample_v10() -> list[dict]:
    rows = [
        (1, 1, "اِ۬لْحَمْدُ لِلهِ رَبِّ اِ۬لْعَٰلَمِينَ" + NBSP + "١"),
        (1, 2, "اَ۬لرَّحْمَٰنِ اِ۬لرَّحِيمِۖ" + NBSP + "٢"),
        (2, 1, "۞" + NBSP + "قُلْ أَعُوذُ عَلَىٰ" + NBSP + "١"),
        (2, 2, "مَا مِنَّا مَلِكِۖ" + NBSP + "٢"),
    ]
    return [{"sura_no": s, "aya_no": a, "aya_text": t} for s, a, t in rows]


def _load_sample(converter, tmp_path, monkeypatch):
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(_sample_v10(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(converter, "SOURCE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(converter, "AYAH_COUNT", 4)
    return converter.load_v10(path)


def test_the_converter_refuses_data_that_is_not_the_pinned_file(converter, tmp_path) -> None:
    path = tmp_path / "QaloonData_v10.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(converter.ConversionError, match="sha256"):
        converter.load_v10(path)


def test_the_converter_swaps_the_words_and_keeps_the_ver05_layout(
    converter, tmp_path, monkeypatch
) -> None:
    v10 = _load_sample(converter, tmp_path, monkeypatch)
    assert v10[(2, 1)] == ["۞قُلْ", "أَعُوذُ", "عَلَىٰ"]

    out = converter.convert(v10, VER05_SAMPLE)

    assert out.split("\r\n") == [
        "سُورَةُ الفَاتِحَةِ",
        BASMALA,
        "اِ۬لْحَمْدُ لِلهِ رَبِّ اِ۬لْعَٰلَمِينَ ١ ",
        "اَ۬لرَّحْمَٰنِ اِ۬لرَّحِيمِۖ ٢",
        "",
        "سُورَةُ النَّاسِ",
        BASMALA,
        " ۞قُلْ أَعُوذُ عَلَىٰ ١ مَا مِنَّا ",
        "مَلِكِۖ ٢",
        "",
    ]
    assert converter.convert(v10, VER05_SAMPLE) == out, "same inputs, same output"


def test_the_converter_stops_when_the_letters_differ(converter, tmp_path, monkeypatch) -> None:
    v10 = _load_sample(converter, tmp_path, monkeypatch)
    v10[(2, 2)] = ["مَا", "مِنَّا", "مَلِكُونَ"]
    with pytest.raises(converter.ConversionError, match="letters differ"):
        converter.convert(v10, VER05_SAMPLE)

"""Tests for the word-level structural parse (quran_structure.parse_words)."""

from __future__ import annotations

import pytest

from qurantext.config.paths import DEFAULT_QURAN_PATH
from qurantext.core.quran_parser import parse_ayat
from qurantext.core.quran_structure import parse_words

QURAN_FILE = DEFAULT_QURAN_PATH

pytestmark = pytest.mark.skipif(not QURAN_FILE.exists(), reason="shipped Quran file not present")


@pytest.fixture(scope="module")
def words() -> list[dict]:
    return parse_words(QURAN_FILE)


def test_fatiha_first_ayah_word_records(words: list[dict]) -> None:
    fatiha_1 = [w for w in words if w["surah_num"] == 1 and w["ayah_num"] == 1]
    assert [w["id"] for w in fatiha_1] == ["1:1:1", "1:1:2", "1:1:3", "1:1:4"]
    assert [w["word_num"] for w in fatiha_1] == [1, 2, 3, 4]
    # Every word carries positional metadata.
    assert all(w["page"] >= 1 and w["line"] >= 1 for w in fatiha_1)
    assert all(w["text_raw"] and w["text_norm"] for w in fatiha_1)


def test_ids_are_unique_and_well_formed(words: list[dict]) -> None:
    ids = [w["id"] for w in words]
    assert len(ids) == len(set(ids)), "surah:ayah:word IDs must be unique"
    for w in words:
        assert w["id"] == f"{w['surah_num']}:{w['ayah_num']}:{w['word_num']}"


def test_word_num_is_contiguous_within_each_ayah(words: list[dict]) -> None:
    by_ayah: dict[tuple[int, int], list[int]] = {}
    for w in words:
        by_ayah.setdefault((w["surah_num"], w["ayah_num"]), []).append(w["word_num"])
    for nums in by_ayah.values():
        assert nums == list(range(1, len(nums) + 1))


def test_matches_ayah_parser_exactly(words: list[dict]) -> None:
    """Joining word text per ayah must reproduce parse_ayat's text_raw exactly."""
    joined: dict[str, list[str]] = {}
    for w in words:
        joined.setdefault(f"{w['surah_num']}:{w['ayah_num']}", []).append(w["text_raw"])
    structural = {k: " ".join(v) for k, v in joined.items()}

    expected = {f"{a['surah_num']}:{a['ayah_num']}": a["text_raw"] for a in parse_ayat(QURAN_FILE)}
    assert structural == expected


def test_in_verse_basmala_is_not_skipped(words: list[dict]) -> None:
    # An-Naml 27:30 ends with the in-verse basmala; its words must survive.
    naml_30 = " ".join(
        w["text_norm"] for w in words if w["surah_num"] == 27 and w["ayah_num"] == 30
    )
    assert "بسم الله الرحمن الرحيم" in naml_30
    # 27:31 must exist with its own words (was dropped by the old heuristic).
    assert any(w["surah_num"] == 27 and w["ayah_num"] == 31 for w in words)

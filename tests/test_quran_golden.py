"""Regression tests guarding the Quran parser against silent data corruption.

These lock the two CRITICAL bugs fixed in the audit:
  * An-Nūr 24:1 «سُورَةٌ أَنزَلْنَٰهَا…» was misread as a surah header → phantom
    surah, +1 mis-numbering for every surah from 24 on, and 24:1 dropped.
  * Ayat beginning with «أعوذ» (Maryam 19:18, Al-Muʾminūn 23:97) were dropped by
    the ta'awwudh skip.

The unit tests below are file-independent; the golden test parses the shipped
Qalun file and is skipped if it is absent.
"""

from __future__ import annotations

import pytest

from qurantext.config.paths import QURAN_INPUT_DIR
from qurantext.core.arabic import normalize_detection_ar
from qurantext.core.quran_parser import _is_surah_header, _is_taawwudh, parse_ayat

QURAN_FILE = QURAN_INPUT_DIR / "UthmanicQaloon1-Ver05.txt"


# --- file-independent heuristic unit tests ---------------------------------


def test_surah_header_accepts_real_headers() -> None:
    assert _is_surah_header("سُورَةُ الفَاتِحَةِ")
    assert _is_surah_header("سُورَةُ النُّورِ")
    assert _is_surah_header("سُورَةُ آلِ عِمْرَانَ")


def test_surah_header_rejects_annur_24_1() -> None:
    # An-Nūr 24:1 begins with the indefinite «سُورَةٌ» (tanwīn) and is verse text.
    assert not _is_surah_header("سُورَةٌ أَنزَلْنَٰهَا وَفَرَضْنَٰهَا وَأَنزَلْنَا فِيهَا ءَايَٰتِۭ بَيِّنَٰتٖ")


def test_taawwudh_matches_only_the_real_preamble() -> None:
    assert _is_taawwudh("أَعُوذُ بِاللَّهِ مِنَ الشَّيْطَانِ الرَّجِيمِ")
    # Genuine ayat that start with أعوذ must NOT be skipped.
    assert not _is_taawwudh("أَعُوذُ بِالرَّحْمَٰنِ مِنكَ إِن كُنتَ تَقِيّاٗ")  # Maryam 19:18
    assert not _is_taawwudh("أَعُوذُ بِكَ مِنْ هَمَزَٰتِ اِ۬لشَّيَٰطِينِ")  # Al-Muʾminūn 23:97


# --- golden full-file parse ------------------------------------------------


@pytest.mark.skipif(not QURAN_FILE.exists(), reason="shipped Quran file not present")
def test_golden_parse_of_shipped_qalun_file() -> None:
    ayat = parse_ayat(QURAN_FILE)

    surah_nums = sorted({a["surah_num"] for a in ayat})
    assert surah_nums == list(range(1, 115)), "expected 114 contiguous surahs, no phantom"

    names = {a["surah_num"]: normalize_detection_ar(a["surah_name"]) for a in ayat}
    assert "الفاتحة" in names[1]
    assert "البقرة" in names[2]
    assert "النور" in names[24], "An-Nūr must be surah 24, not shifted by a phantom header"
    assert "الناس" in names[114], "last surah must be An-Nās, not Al-Falaq (+1 shift)"

    def find(surah: int, needle: str) -> bool:
        needle = normalize_detection_ar(needle)
        return any(a["surah_num"] == surah and needle in a["text_norm"] for a in ayat)

    # The three ayat the old heuristics dropped must be present.
    assert find(24, "وفرضنها"), "An-Nūr 24:1 text was dropped"
    assert find(19, "اعوذ بالرحمن منك"), "Maryam ayah starting with أعوذ was dropped"
    assert find(23, "اعوذ بك من همزت"), "Al-Muʾminūn ayah starting with أعوذ was dropped"

    # Lock the recovered ayah count so a regression that re-drops them is caught.
    # 6214 reflects two correctness fixes over the old 6213:
    #   -1  the trailing version string «النسخة رقم ٠٥» is no longer misread as a
    #       marker, so the copyright footer is no longer a phantom An-Nās ayah 5.
    #   +2  An-Naml 27:30 and 27:31 are no longer lost to the in-verse basmala
    #       false-skip (see is_ayah_marker / _is_basmala).
    assert len(ayat) == 6214

    # The footer must NOT appear as a verse, and An-Nās ends at ayah 6.
    annas = sorted(a["ayah_num"] for a in ayat if a["surah_num"] == 114)
    assert annas == [1, 2, 3, 4, 5, 6], "An-Nās must have exactly 6 ayat, no footer phantom"

    # An-Naml's in-verse basmala (27:30) must not eat its own line: 30 keeps the
    # basmala, 31 is recovered, and every surah numbers 1..N with no gap.
    naml = sorted(a["ayah_num"] for a in ayat if a["surah_num"] == 27)
    assert naml == list(range(1, 96)), "An-Naml must be 95 contiguous ayat"
    assert find(27, "وانه بسم الله الرحمن الرحيم"), "27:30 in-verse basmala dropped"
    assert find(27, "الا تعلوا علي واتوني مسلمين"), "27:31 was dropped"
    for surah in surah_nums:
        nums = sorted(a["ayah_num"] for a in ayat if a["surah_num"] == surah)
        assert nums == list(range(1, len(nums) + 1)), f"surah {surah} has an ayah-number gap"


@pytest.mark.skipif(not QURAN_FILE.exists(), reason="shipped Quran file not present")
def test_surah_filter_does_not_match_every_surah() -> None:
    # A bare "سورة" (present in every header) must select nothing, not the whole
    # Quran (the old bidirectional-substring bug).
    assert parse_ayat(QURAN_FILE, surah_filter="سورة") == []
    # A real surah name selects exactly that surah.
    fatiha = parse_ayat(QURAN_FILE, surah_filter="الفاتحة")
    assert fatiha
    assert {a["surah_num"] for a in fatiha} == {1}

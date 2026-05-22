import pytest

from qurantext.core.lecture_matching import detect_quran_mentions_in_lecture
from qurantext.core.range_matching import build_warnings, detect_first_ayah, detect_last_ayah


def _sample_ayat() -> list[dict]:
    return [
        {
            "surah_num": 1,
            "surah_name": "سُورَةُ الفَاتِحَةِ",
            "ayah_num": 1,
            "text_raw": "الْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ",
            "text_norm": "الحمد لله رب العالمين",
            "_index": 0,
        },
        {
            "surah_num": 1,
            "surah_name": "سُورَةُ الفَاتِحَةِ",
            "ayah_num": 2,
            "text_raw": "الرَّحْمَنِ الرَّحِيمِ",
            "text_norm": "الرحمن الرحيم",
            "_index": 1,
        },
    ]


def _sample_words() -> list[dict]:
    return [
        {"word_norm": "الحمد", "word_raw": "الْحَمْدُ", "start": 0.0, "end": 0.3},
        {"word_norm": "لله", "word_raw": "لِلَّهِ", "start": 0.3, "end": 0.6},
        {"word_norm": "رب", "word_raw": "رَبِّ", "start": 0.6, "end": 0.8},
        {"word_norm": "العالمين", "word_raw": "الْعَالَمِينَ", "start": 0.8, "end": 1.2},
        {"word_norm": "الرحمن", "word_raw": "الرَّحْمَنِ", "start": 1.2, "end": 1.5},
        {"word_norm": "الرحيم", "word_raw": "الرَّحِيمِ", "start": 1.5, "end": 1.8},
    ]


def test_detect_first_and_last_ayah_on_synthetic_words() -> None:
    ayat = _sample_ayat()
    words = _sample_words()

    first_ayah, first_conf = detect_first_ayah(ayat, words, head_n=6, search_range=2)
    last_ayah, last_conf = detect_last_ayah(
        ayat, words, tail_n=6, search_range=2, first_ayah=first_ayah
    )

    assert first_ayah["ayah_num"] == 1
    assert last_ayah["ayah_num"] == 2
    assert first_conf > 0.9
    assert last_conf > 0.9


def test_build_warnings_for_sparse_transcript() -> None:
    ayat = _sample_ayat()
    words = _sample_words()
    warnings = build_warnings(ayat[0], 0.2, ayat[1], 0.2, words, low_conf=0.4)
    assert any("Only 6 word(s)" in message for message in warnings)
    assert any("Low confidence for first ayah" in message for message in warnings)


def test_detect_quran_mentions_in_lecture_returns_merged_match() -> None:
    matches = detect_quran_mentions_in_lecture(
        _sample_ayat(),
        _sample_words(),
        max_span=2,
        min_score=0.4,
        min_matched_words=2,
    )
    assert matches
    assert matches[0]["from_ayah"] == 1
    assert matches[0]["to_ayah"] == 2


def test_detect_first_ayah_raises_on_empty_words() -> None:
    with pytest.raises(ValueError, match="Head word window is empty"):
        detect_first_ayah(_sample_ayat(), [], head_n=80, search_range=2)


def test_detect_quran_mentions_short_phrase_filtered_at_high_threshold() -> None:
    # A 1-word match should be rejected when short_phrase_threshold is 1.0.
    matches = detect_quran_mentions_in_lecture(
        _sample_ayat(),
        _sample_words()[:2],
        max_span=1,
        min_score=0.4,
        min_matched_words=1,
        short_phrase_threshold=1.0,
        short_phrase_word_limit=10,  # everything is "short"
    )
    assert matches == []

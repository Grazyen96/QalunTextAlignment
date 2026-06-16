import pytest

from qurantext.core.lecture_matching import detect_quran_mentions_in_lecture, iter_word_windows
from qurantext.core.range_matching import (
    build_warnings,
    detect_first_ayah,
    detect_last_ayah,
    select_recitation_timeline,
    trim_match_to_ayah_range,
)


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


# ---------------------------------------------------------------------------
# iter_word_windows – adaptive step coverage
# ---------------------------------------------------------------------------


def test_iter_word_windows_short_windows_cover_all_start_positions() -> None:
    """With step=3 and short_max_words=7, short windows (≤7 words) must start
    at every word index, not just multiples of 3."""
    words = _sample_words()  # 6 words
    windows = list(iter_word_windows(words, min_words=3, max_words=5, step=3, short_max_words=7))

    start_positions = {w["start_word"] for w in windows}
    # Every start position 0..len-min_words should appear at least once.
    for i in range(len(words) - 3 + 1):
        assert i in start_positions, f"start position {i} missing from short-window pass"


def test_iter_word_windows_empty_returns_nothing() -> None:
    assert list(iter_word_windows([], min_words=3, max_words=5, step=1)) == []


def test_iter_word_windows_long_windows_use_coarse_step() -> None:
    """Windows of size > short_max_words should still be yielded (at coarse step)."""
    words = _sample_words()  # 6 words
    windows = list(iter_word_windows(words, min_words=2, max_words=6, step=1, short_max_words=4))
    # Expect windows of size 5 and 6 from the long-window pass.
    long_windows = [w for w in windows if w["word_count"] >= 5]
    assert long_windows


# ---------------------------------------------------------------------------
# trim_match_to_ayah_range – cross-surah guard
# ---------------------------------------------------------------------------


def _ayat_surah_2() -> list[dict]:
    return [
        {
            "surah_num": 2,
            "surah_name": "البقرة",
            "ayah_num": 1,
            "text_raw": "الم",
            "text_norm": "الم",
            "_index": 0,
        },
        {
            "surah_num": 2,
            "surah_name": "البقرة",
            "ayah_num": 2,
            "text_raw": "ذَٰلِكَ الْكِتَابُ",
            "text_norm": "ذلك الكتاب",
            "_index": 1,
        },
    ]


def test_trim_match_to_ayah_range_rejects_cross_surah_match() -> None:
    """A match from surah 1 should return None against surah 2 recitation ayat."""
    match = {
        "surah_num": 1,
        "from_ayah": 1,
        "to_ayah": 2,
        "start_time": 0.0,
        "end_time": 2.0,
        "confidence": 0.9,
        "full_text": "الفاتحة",
    }
    result = trim_match_to_ayah_range(match, _ayat_surah_2(), from_ayah=1, to_ayah=2)
    assert result is None


def test_trim_match_to_ayah_range_accepts_matching_surah() -> None:
    """A match from surah 2 should be trimmed correctly against surah 2 recitation ayat."""
    match = {
        "surah_num": 2,
        "from_ayah": 1,
        "to_ayah": 2,
        "start_time": 0.0,
        "end_time": 2.0,
        "confidence": 0.9,
        "full_text": "البقرة",
    }
    result = trim_match_to_ayah_range(match, _ayat_surah_2(), from_ayah=1, to_ayah=2)
    assert result is not None
    assert result["from_ayah"] == 1
    assert result["to_ayah"] == 2


def test_select_recitation_timeline_filters_out_cross_surah_matches() -> None:
    """Matches whose surah_num differs from recitation_ayat should be ignored."""
    recitation_ayat = _ayat_surah_2()
    matches = [
        {
            "surah_num": 1,  # wrong surah
            "from_ayah": 1,
            "to_ayah": 1,
            "start_time": 0.0,
            "end_time": 1.0,
            "confidence": 0.95,
            "full_text": "الفاتحة",
        },
        {
            "surah_num": 2,
            "from_ayah": 1,
            "to_ayah": 2,
            "start_time": 0.0,
            "end_time": 2.0,
            "confidence": 0.90,
            "full_text": "البقرة",
        },
    ]
    timeline = select_recitation_timeline(matches, recitation_ayat, max_span=5)
    assert timeline
    assert all(m["surah_num"] == 2 for m in timeline)


def test_select_recitation_timeline_drops_inverted_spans() -> None:
    """Overlap trims must never emit a span with end_time <= start_time."""
    recitation_ayat = _ayat_surah_2()
    matches = [
        {
            "surah_num": 2,
            "from_ayah": 1,
            "to_ayah": 1,
            "start_time": 0.0,
            "end_time": 10.0,
            "confidence": 0.95,
            "full_text": "x",
        },
        # Short later span nested inside the first: the forward-fill would push its
        # start to 10.0 while its end stays 9.9 (inverted). It must be dropped, not
        # emitted as a negative-duration span (which the renderer would silently
        # discard, losing a detected ayah).
        {
            "surah_num": 2,
            "from_ayah": 2,
            "to_ayah": 2,
            "start_time": 9.7,
            "end_time": 9.9,
            "confidence": 0.95,
            "full_text": "y",
        },
    ]
    timeline = select_recitation_timeline(matches, recitation_ayat, max_span=5)
    assert timeline
    for span in timeline:
        assert span["end_time"] > span["start_time"]

from qurantext.core.arabic import (
    arabic_indic_to_int,
    ayah_text_with_marker,
    int_to_arabic_indic,
    normalize_alignment_ar,
    normalize_detection_ar,
    normalize_full_aya_ar,
    partial_ratio,
    similarity,
    word_recall,
)
from qurantext.utils.time_utils import seconds_to_srt_time


def test_alignment_normalization_matches_word_alignment_behavior() -> None:
    assert normalize_alignment_ar("بِسْمِ اللّٰهِ ے") == "بسم الله ي"


def test_full_aya_normalization_preserves_current_bari_yeh_behavior() -> None:
    assert normalize_full_aya_ar("بِسْمِ اللّٰهِ ے") == "بسم الله"


def test_detection_normalization_removes_quranic_marks() -> None:
    assert normalize_detection_ar("۞ إِنَّا أَعْطَيْنَاكَ") == "انا اعطيناك"


def test_similarity_helpers() -> None:
    assert similarity("abc", "abc") == 1.0
    assert partial_ratio("abcdef", "xxabcdefyy") > 0.9
    assert word_recall(["abc", "def"], {"abc", "ghi"}) == 0.5


def test_arabic_indic_helpers() -> None:
    assert int_to_arabic_indic(25) == "٢٥"
    assert arabic_indic_to_int("٢٥") == 25
    assert ayah_text_with_marker("الحمد لله", 7) == "الحمد لله \ufd3e٧\ufd3f"


def test_seconds_to_srt_time() -> None:
    assert seconds_to_srt_time(3723.456) == "01:02:03,456"

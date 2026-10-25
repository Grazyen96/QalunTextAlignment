from qurantext.core.arabic import (
    arabic_indic_to_int,
    ayah_text_with_marker,
    int_to_arabic_indic,
    is_qaloon_face,
    normalize_alignment_ar,
    normalize_detection_ar,
    normalize_full_aya_ar,
    partial_ratio,
    portable_tanween,
    similarity,
    word_recall,
)
from qurantext.utils.time_utils import seconds_to_srt_time


def test_alignment_normalization_matches_word_alignment_behavior() -> None:
    assert normalize_alignment_ar("بِسْمِ اللّٰهِ ے") == "بسم الله ي"


def test_full_aya_normalization_preserves_current_bari_yeh_behavior() -> None:
    assert normalize_full_aya_ar("بِسْمِ اللّٰهِ ے") == "بسم الله"


def test_detection_normalization_removes_quranic_marks() -> None:
    assert normalize_detection_ar("۞ إِنَّا أَعْطَيْنَاكَ") == "انا اعطيناك"


def test_similarity_helpers() -> None:
    assert similarity("abc", "abc") == 1.0
    assert partial_ratio("abcdef", "xxabcdefyy") > 0.9
    assert word_recall(["abc", "def"], {"abc", "ghi"}) == 0.5


def test_arabic_indic_helpers() -> None:
    assert int_to_arabic_indic(25) == "٢٥"
    assert arabic_indic_to_int("٢٥") == 25
    # Ayah number is appended as a bare Arabic-Indic digit (no ornate parentheses).
    assert ayah_text_with_marker("الحمد لله", 7) == "الحمد لله ٧"


def test_seconds_to_srt_time() -> None:
    assert seconds_to_srt_time(3723.456) == "01:02:03,456"


def test_seconds_to_srt_time_rounds_without_millisecond_overflow() -> None:
    # 0.9996s must not produce ",1000"; it rolls over into the next whole second.
    assert seconds_to_srt_time(3.9996) == "00:00:04,000"
    assert seconds_to_srt_time(59.9996) == "00:01:00,000"


def test_normalization_removes_tatweel() -> None:
    # Tatweel (U+0640) is a presentational kashida, not a letter — must be stripped.
    text_with_tatweel = "كتـاب"  # كتاب with a tatweel between ت and ا
    assert normalize_alignment_ar(text_with_tatweel) == normalize_alignment_ar("كتاب")
    assert normalize_detection_ar(text_with_tatweel) == normalize_detection_ar("كتاب")


def test_teh_marbuta_and_heh_kept_distinct() -> None:
    # ة (teh marbuta) and ه (heh) must NOT be normalised together.
    assert normalize_alignment_ar("رحمة") != normalize_alignment_ar("رحمه")
    assert normalize_detection_ar("رحمة") != normalize_detection_ar("رحمه")


def test_partial_ratio_short_needle_uses_fine_step() -> None:
    # For needles shorter than 30 chars step=1, so the best window is never skipped.
    needle = "الحمد لله"  # 9 chars — well under the 30-char threshold
    haystack = "xxx " + needle + " xxx"
    assert partial_ratio(needle, haystack) > 0.95


# The shipped text writes open tanween with code points only its own font draws that way.
RAJULAN = "\u0631\u064e\u062c\u064f\u0644\u0627\u0657"


def test_portable_tanween_writes_the_standard_open_tanween() -> None:
    assert portable_tanween("\u0657\u065e\u0656") == "\u08f0\u08f1\u08f2"


def test_only_the_three_tanween_marks_change() -> None:
    """Other mushaf marks, direction marks and Arabic-Indic digits pass through."""
    others = "\u06de \u06ec\u06e2\u200f\u06d2 \u0661\u0660"
    assert portable_tanween(f"{RAJULAN} {others}") == f"{RAJULAN[:-1]}\u08f0 {others}"


def test_is_qaloon_face() -> None:
    assert is_qaloon_face("KFGQPC QALOON Uthmanic Script")
    assert not is_qaloon_face("Amiri")
    assert not is_qaloon_face("Noto Sans Arabic")

from __future__ import annotations

import re
from difflib import SequenceMatcher

ALIGNMENT_TASHKEEL = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
DETECTION_TASHKEEL = re.compile(r"[\u0600-\u0605\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")

AR_DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
TO_ARABIC_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
ARABIC_INDIC_DIGIT_RE = re.compile(r"^[٠١٢٣٤٥٦٧٨٩]+$")


def _normalize_with_pattern(text: str, pattern: re.Pattern[str], *, map_bari_yeh: bool) -> str:
    text = pattern.sub("", text)
    text = text.replace(
        "\u0640", ""
    )  # Remove Tatweel/Kashida (U+0640) — not covered by tashkeel patterns
    text = re.sub(r"[إأآٱ]", "ا", text)
    # Intentional: ة (teh marbuta) and ه (heh) are kept distinct — normalising them
    # causes false merges between grammatically different word forms.
    text = text.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    if map_bari_yeh:
        text = text.replace("ے", "ي")
    text = re.sub(r"[^\u0621-\u064A\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_alignment_ar(text: str) -> str:
    """Match the word-level alignment normalization used in audioAlignment.py."""
    return _normalize_with_pattern(text, ALIGNMENT_TASHKEEL, map_bari_yeh=True)


def normalize_full_aya_ar(text: str) -> str:
    """Match the full-ayah normalization used in fullAyaAlignment.py."""
    return _normalize_with_pattern(text, ALIGNMENT_TASHKEEL, map_bari_yeh=False)


def normalize_detection_ar(text: str) -> str:
    """Match the detect_range.py normalization used for ayah matching."""
    return _normalize_with_pattern(text, DETECTION_TASHKEEL, map_bari_yeh=True)


def similarity(a: str, b: str) -> float:
    """Return the SequenceMatcher similarity ratio for two strings."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def partial_ratio(needle: str, haystack: str) -> float:
    """Best SequenceMatcher ratio of ``needle`` against a haystack sub-window."""
    n = len(needle)
    h = len(haystack)
    if n == 0 or h == 0:
        return 0.0
    if n >= h:
        return SequenceMatcher(None, needle, haystack, autojunk=False).ratio()

    best = 0.0
    # Use step=1 for short needles (< 30 chars) to avoid skipping the best window;
    # use n//10 for longer needles to keep runtime reasonable.
    step = 1 if n < 30 else max(1, n // 10)
    for start in range(0, h - n + 1, step):
        ratio = SequenceMatcher(
            None,
            needle,
            haystack[start : start + n],
            autojunk=False,
        ).ratio()
        if ratio > best:
            best = ratio
        if best > 0.97:
            break
    return best


def word_recall(ayah_words: list[str] | tuple[str, ...], transcript_words: set[str]) -> float:
    """Return the fraction of ayah words found in the transcript window."""
    if not ayah_words:
        return 0.0
    return sum(1 for word in ayah_words if word in transcript_words) / len(ayah_words)


def arabic_indic_to_int(value: str) -> int:
    """Convert an Arabic-Indic digit string to an integer."""
    return int(value.translate(AR_DIGIT_TRANSLATION))


def int_to_arabic_indic(value: int) -> str:
    """Convert an integer to its Arabic-Indic digit string."""
    return str(value).translate(TO_ARABIC_INDIC)


def ayah_text_with_marker(text_raw: str, ayah_num: int) -> str:
    """Append the ayah number as a bare Arabic-Indic digit (e.g. ``… ٧``)."""
    return f"{text_raw} {int_to_arabic_indic(ayah_num)}"

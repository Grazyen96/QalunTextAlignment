from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

__all__ = [
    "ALIGNMENT_TASHKEEL",
    "ARABIC_INDIC_DIGIT_RE",
    "AR_DIGIT_TRANSLATION",
    "DETECTION_TASHKEEL",
    "TO_ARABIC_INDIC",
    "arabic_indic_to_int",
    "ayah_text_with_marker",
    "int_to_arabic_indic",
    "is_qaloon_face",
    "normalize_alignment_ar",
    "normalize_detection_ar",
    "normalize_full_aya_ar",
    "partial_ratio",
    "plain_surah_name",
    "portable_tanween",
    "similarity",
    "surah_title",
    "word_recall",
]

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


# --- Tanween outside the mushaf font --------------------------------------------------

# Only qaloon.10 draws U+0657, U+065E and U+0656 as open fathatan, dammatan and
# kasratan; every other font draws an inverted damma, a fatha with two dots and a
# subscript alef, so text leaving the app's own font uses the standard open tanween.
_PORTABLE_TANWEEN = str.maketrans("\u0657\u065e\u0656", "\u08f0\u08f1\u08f2")


def portable_tanween(text: str) -> str:
    """*text* with U+0657, U+065E and U+0656 written as U+08F0, U+08F1 and U+08F2.

    Those are the standard open fathatan, dammatan and kasratan that common Arabic
    fonts draw. Nothing else changes.
    """
    return text.translate(_PORTABLE_TANWEEN)


def is_qaloon_face(font_name: str) -> bool:
    """True for the bundled Qaloon face, which draws the mushaf's own code points."""
    return "qaloon" in font_name.casefold()


# --- Surah names as a title reads them ----------------------------------------------

# Marks that are part of a letter, not a vowel: an alef with a madda or a hamza is
# its own letter (آ أ إ), as a waw with a hamza is ؤ. Stripping the mark alone would
# turn «آل عمران» into «ال عمران». Other vowel marks may sit between letter and mark.
_LETTER_MARKS = (
    (re.compile("\u0627([\u064b-\u0652]*)\u0653"), "\u0622\\1"),  # alef + madda: alef madda
    (re.compile("\u0627([\u064b-\u0652]*)\u0654"), "\u0623\\1"),  # alef + hamza above
    (re.compile("\u0627([\u064b-\u0652]*)\u0655"), "\u0625\\1"),  # alef + hamza below
    (re.compile("\u0648([\u064b-\u0652]*)\u0654"), "\u0624\\1"),  # waw + hamza above
)
# A word-final yeh (or alef maksura) carrying a dagger alef is an alef maksura:
# the store's «الشُّورَيٰ» is «الشورى», not «الشوري».
_FINAL_YEH_ALEF = re.compile("[\u064a\u0649]([\u064b-\u0652]*)\u0670(?=[\u064b-\u0652]*(?:\\s|$))")
# A word-final hamza on an alef carrier after a letter is written «أ» in a title: the
# shipped text's Uthmani «سبإ» and «النبإ» (surahs 34 and 78) read as «سبأ» and «النبأ».
# A word-initial «إ» («إبراهيم», «الإسراء») is untouched.
_FINAL_HAMZA_BELOW = re.compile("(?<=[\u0621-\u064a])\u0625(?=\\s|$)")
_SURAH_WORD = "سورة"


def plain_surah_name(name: str) -> str:
    """*name* (the store's «سُورَةُ آلِ عِمْرَانَ») as a title writes it: «سورة آل عمران».

    Marks that form letters are joined into them first and a final «يٰ» becomes
    «ى»; then every other mark and the tatweel go, and a word-final «إ» after a
    letter is written «أ», as most people write «سبأ» and «النبأ». Not a blanket NFC
    composition: that would join the store's yeh and hamza above (U+064A
    U+0654) in surah 21 into «الأنبئاء», where a title writes «الأنبياء».
    Spaces are collapsed.
    """
    text = str(name)
    for pattern, letter in _LETTER_MARKS:
        text = pattern.sub(letter, text)
    text = _FINAL_YEH_ALEF.sub("\u0649\\1", text)
    kept = (c for c in text if unicodedata.category(c) != "Mn" and c != "\u0640")
    plain = " ".join("".join(kept).split())
    return _FINAL_HAMZA_BELOW.sub("\u0623", plain)


def surah_title(name: str) -> str:
    """«سورة <name>» in plain letters, without saying «سورة» twice; "" for no name."""
    plain = plain_surah_name(name)
    if not plain:
        return ""
    return plain if plain.split()[0] == _SURAH_WORD else f"{_SURAH_WORD} {plain}"

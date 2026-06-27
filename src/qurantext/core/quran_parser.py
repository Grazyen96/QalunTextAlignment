from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from qurantext.core.arabic import DETECTION_TASHKEEL, arabic_indic_to_int, normalize_detection_ar

ARABIC_INDIC_DIGIT_RE = re.compile(r"^[٠١٢٣٤٥٦٧٨٩]+$")
_ANY_ARABIC_INDIC_DIGIT_RE = re.compile(r"[٠-٩]")

# Tanwīn marks (fathatan/dammatan/kasratan). A header is the construct «سُورَةُ»;
# verse text that merely starts with the word uses the indefinite «سُورَةٌ» (tanwīn).
_TANWIN_MARKS = ("ً", "ٌ", "ٍ")

# Real surah headers are short standalone lines ("سُورَةُ <name>"); the longest is
# "سُورَةُ آلِ عِمْرَانَ" (3 tokens). Anything longer is verse text.
_MAX_HEADER_TOKENS = 4


def _is_surah_header(raw_line: str) -> bool:
    """True when the line is a sūrah-name header (e.g. 'سُورَةُ البَقَرَةِ').

    Distinguishes a genuine header from verse text that merely *starts* with the
    word "سورة" — notably An-Nūr 24:1, «سُورَةٌ أَنزَلْنَٰهَا…». A header uses the
    construct form «سُورَةُ» (no tanwīn), is a short standalone line, and carries
    no ayah-number marker; the ayah uses the indefinite «سُورَةٌ» (tanwīn) and
    runs on into a long verse.
    """
    tokens = raw_line.strip().split()
    if not tokens:
        return False
    first = tokens[0]
    # An indefinite «سُورَةٌ» (tanwīn) is verse text, never a header.
    if any(mark in first for mark in _TANWIN_MARKS):
        return False
    if DETECTION_TASHKEEL.sub("", first) not in {"سورة", "سوره"}:
        return False
    # Headers are short and never contain an ayah-number marker.
    if len(tokens) > _MAX_HEADER_TOKENS or _ANY_ARABIC_INDIC_DIGIT_RE.search(raw_line):
        return False
    return True


def is_ayah_marker(token: str) -> bool:
    """True when *token* is a standalone ayah-number marker.

    Ayah numbers are Arabic-Indic digits with no leading zero — no ayah is
    numbered 0, and the mushaf never zero-pads a verse number. Rejecting
    leading-zero tokens stops the file's trailing version string
    «النسخة رقم ٠٥» from being misread as a marker, which otherwise flushes the
    copyright footer as a phantom An-Nās ayah 5.
    """
    return bool(ARABIC_INDIC_DIGIT_RE.match(token)) and not token.startswith("٠")


_BASMALA_NORM = "بسم الله الرحمن الرحيم"


def _is_basmala(raw_line: str) -> bool:
    """True only for a standalone opening basmala line — the whole line and
    nothing else.

    The old "first word is بسم" heuristic also matched An-Naml 27:30's *in-verse*
    basmala, where mushaf line-wrapping puts «بسم الله الرحمن الرحيم ٣٠ أَلَّا
    تَعْلُواْ…» on one physical line. Skipping that whole line dropped markers
    ٣٠/٣١, all of 27:31, and the tail of 27:30, then fused the remainder into
    27:32. Every one of the 113 genuine opening basmalas in the file normalizes
    exactly to «بسم الله الرحمن الرحيم» and is never combined with following ayah
    text, so an exact match skips them all and rejects the in-verse case.
    """
    return normalize_detection_ar(raw_line) == _BASMALA_NORM




def _is_taawwudh(raw_line: str) -> bool:
    """True when the line is a ta'awwudh preamble spoken before the recitation.

    The genuine preamble is «أعوذ بالله من الشيطان الرجيم». Real ayat also begin
    with أعوذ (Maryam 19:18 «أَعُوذُ بِالرَّحْمَٰنِ مِنكَ…», Al-Muʾminūn 23:97
    «أَعُوذُ بِكَ مِنْ هَمَزَٰتِ…»), so a bare «اعوذ» prefix is not enough — we also
    require the «بالله» + «الشيطان/الرجيم» signature that only the preamble has.
    """
    norm = normalize_detection_ar(raw_line)
    if not (norm.startswith("اعوذ") or norm.startswith("اعود")):
        return False
    words = set(norm.split())
    return "بالله" in words and bool(words & {"الشيطان", "الشيطن", "الرجيم"})


def _surah_name_key(norm_text: str) -> str:
    """Return just the surah-name part of a normalized header or --surah filter.

    Drops a leading "سورة"/"سوره" word so that "الفرقان", "سورة الفرقان", and the
    full header all reduce to the same key. A bare "سورة" reduces to an empty key
    (matching nothing), avoiding the old bug where "--surah سورة" — a word present
    in every header — silently matched every surah.
    """
    parts = norm_text.split()
    if parts and parts[0] in {"سورة", "سوره"}:
        parts = parts[1:]
    return " ".join(parts)


def read_quran_text(quran_path: str | Path) -> str:
    """Read a Quran text file, honouring its byte-order mark.

    UTF-16 (LE/BE) is detected from the BOM; everything else is read as
    ``utf-8-sig``, which transparently strips a 3-byte UTF-8 BOM when present and
    reads plain UTF-8 otherwise. Plain ``utf-8`` would leave a UTF-8 BOM attached
    to the first token and break the first surah header.
    """
    path = Path(quran_path)
    with path.open("rb") as fh:
        bom = fh.read(2)
    encoding = "utf-16" if bom in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    return path.read_text(encoding=encoding, errors="replace")


@lru_cache(maxsize=16)
def _parse_ayat_cached(quran_path: str, surah_filter: str | None = None) -> tuple[dict, ...]:
    """Parse and cache ayat for one Quran file and optional surah filter."""
    lines = read_quran_text(quran_path).splitlines()

    ayat: list[dict] = []
    surah_num = 0
    surah_name = ""
    buf: list[str] = []
    in_target_surah = surah_filter is None
    surah_filter_key = (
        _surah_name_key(normalize_detection_ar(surah_filter)) if surah_filter is not None else None
    )

    def flush(num: int) -> None:
        if not buf:
            return
        if surah_filter is not None and not in_target_surah:
            buf.clear()
            return
        text_raw = " ".join(buf)
        text_norm = normalize_detection_ar(text_raw)
        if text_norm:
            ayat.append(
                {
                    "surah_num": surah_num,
                    "surah_name": surah_name,
                    "ayah_num": num,
                    "text_raw": text_raw,
                    "text_norm": text_norm,
                    "_index": len(ayat),
                }
            )
        buf.clear()

    for raw_line in lines:
        raw_line = raw_line.rstrip("\r\n")
        stripped = raw_line.strip()
        if not stripped:
            continue

        if _is_surah_header(stripped):
            buf.clear()
            surah_num += 1
            surah_name = stripped
            if surah_filter_key is None:
                in_target_surah = True
            else:
                name_key = _surah_name_key(normalize_detection_ar(surah_name))
                in_target_surah = bool(surah_filter_key) and (
                    surah_filter_key == name_key
                    or surah_filter_key in name_key
                    or name_key in surah_filter_key
                )
            continue

        if _is_basmala(stripped) or _is_taawwudh(stripped):
            continue

        for token in stripped.split():
            if is_ayah_marker(token):
                flush(arabic_indic_to_int(token))
            elif re.search(r"[\u0621-\u064A]", token):
                buf.append(token)

    return tuple(ayat)


def parse_ayat(quran_path: str | Path, surah_filter: str | None = None) -> list[dict]:
    """Parse a Qalun-riwaya Quran file into an ordered ayah list."""
    cached = _parse_ayat_cached(str(Path(quran_path).expanduser().resolve()), surah_filter)
    return [dict(ayah) for ayah in cached]

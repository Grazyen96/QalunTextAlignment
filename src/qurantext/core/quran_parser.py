from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from qurantext.core.arabic import DETECTION_TASHKEEL, arabic_indic_to_int, normalize_detection_ar

ARABIC_INDIC_DIGIT_RE = re.compile(r"^[٠١٢٣٤٥٦٧٨٩]+$")


def _is_surah_header(raw_line: str) -> bool:
    """True when the line is a sūrah-name header (e.g. 'سُورَةُ البَقَرَةِ')."""
    tokens = raw_line.strip().split()
    if not tokens:
        return False
    first = DETECTION_TASHKEEL.sub("", tokens[0])
    return first in {"سورة", "سوره"}


def _is_basmala(raw_line: str) -> bool:
    """True when the line is a standalone basmala."""
    stripped = DETECTION_TASHKEEL.sub("", raw_line.strip())
    first = stripped.split()[0] if stripped.split() else ""
    first_norm = re.sub(r"[^\u0621-\u064A]", "", first)
    tail = re.sub(r"[^\u0621-\u064A\s]", " ", stripped)
    return first_norm == "بسم" and ("لرحمن" in tail or "الرحمن" in tail)


def _is_taawwudh(raw_line: str) -> bool:
    """True when the line is a ta'awwudh preamble spoken before the recitation."""
    norm = normalize_detection_ar(raw_line)
    return norm.startswith("اعوذ") or norm.startswith("اعود")


@lru_cache(maxsize=16)
def _parse_ayat_cached(quran_path: str, surah_filter: str | None = None) -> tuple[dict, ...]:
    """Parse and cache ayat for one Quran file and optional surah filter."""
    path = Path(quran_path)
    with path.open("rb") as fh:
        bom = fh.read(2)
    encoding = "utf-16" if bom in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
    with path.open(encoding=encoding, errors="replace") as fh:
        lines = fh.readlines()

    ayat: list[dict] = []
    surah_num = 0
    surah_name = ""
    buf: list[str] = []
    in_target_surah = surah_filter is None
    surah_filter_norm = normalize_detection_ar(surah_filter) if surah_filter is not None else None

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
            if surah_filter_norm is None:
                in_target_surah = True
            else:
                surah_name_norm = normalize_detection_ar(surah_name)
                in_target_surah = (
                    surah_filter_norm in surah_name_norm or surah_name_norm in surah_filter_norm
                )
            continue

        if _is_basmala(stripped) or _is_taawwudh(stripped):
            continue

        for token in stripped.split():
            if ARABIC_INDIC_DIGIT_RE.match(token):
                flush(arabic_indic_to_int(token))
            elif re.search(r"[\u0621-\u064A]", token):
                buf.append(token)

    return tuple(ayat)


def parse_ayat(quran_path: str | Path, surah_filter: str | None = None) -> list[dict]:
    """Parse a Qalun-riwaya Quran file into an ordered ayah list."""
    cached = _parse_ayat_cached(str(Path(quran_path).expanduser().resolve()), surah_filter)
    return [dict(ayah) for ayah in cached]

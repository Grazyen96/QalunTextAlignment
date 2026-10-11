#!/usr/bin/env python3
"""Convert KFGQPC's Qaloon v10 data into the Mushaf text file Qalun ships.

Developer-only, standard library only. The app never runs this.

Input is KFGQPC's Qaloon text v10 (``QaloonData_v10.json``), pinned by checksum
below, plus the KFGQPC Ver05 text Qalun shipped before it
(``UthmanicQaloon1-Ver05.txt``). Ver05 is the template: every line of it is kept
— surah headers, basmala lines, the blank lines that mark mushaf pages, the
ayah-number markers, line breaks and spacing — and only the words are replaced
by the v10 words. The output therefore keeps the exact layout and encoding the
parser and the store read (UTF-16 LE with BOM, CRLF), and every word keeps the
page and line it had.

The v10 JSON carries no basmala lines and no surah header lines; both come from
Ver05. In the JSON a no-break space joins ``۞`` to the word after it and the
last word to the ayah number. The first is written the way Ver05 writes it,
attached to the word (``۞وَإِذَا``); the second becomes the plain space in front
of Ver05's own marker.

Words are matched ayah by ayah on their letters alone (U+0621 to U+064A, without
tatweel, with alef maksura read as yeh). The letters of each ayah must agree
exactly or the conversion stops. Where v10 splits one Ver05 word in two (41:46
``مَا مِنَّا``, 41:50 ``وَنَـَٔا بِجَانِبِهِۦۖ``), both halves stay on the line the
Ver05 word was on.

KFGQPC's attribution footer at the end of Ver05 names that edition's version
number, so it is not carried over: the output ends after An-Nas 114:6.

Ver05 is no longer in the tree; take it from git history::

    git show 6f2a1fe:src/qurantext/assets/quran/UthmanicQaloon1-Ver05.txt > /tmp/ver05.txt
    python3 tools/convert_mushaf_v10.py --json QaloonData_v10.json --ver05 /tmp/ver05.txt

Running it again on the same inputs gives the same bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SOURCE_URL = (
    "https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/"
    "e35e7b590ba68ff451f32aba92a8f078fd11966f/qaloon/data/QaloonData_v10.json"
)
SOURCE_SHA256 = "18465c40ebeec40a92eb98745c9b89796ac6e31f6e93988883dfb6602faaea95"
DEFAULT_OUT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "qurantext"
    / "assets"
    / "quran"
    / "UthmanicQaloon1-v10.txt"
)

AYAH_COUNT = 6214
SURAH_COUNT = 114
NBSP = " "
RUB_EL_HIZB = "۞"
BOM_UTF16_LE = b"\xff\xfe"
NEWLINE = "\r\n"

_LETTER_RE = re.compile(r"[ء-ي]")
_MARKER_RE = re.compile(r"^[٠-٩]+$")
_TANWIN = ("ً", "ٌ", "ٍ")
_BASMALA_SKELETON = "بسماللهالرحمنالرحيم"
_HEADER_WORD = "سورة"


class ConversionError(RuntimeError):
    """The inputs are not what this converter was written for."""


def skeleton(text: str) -> str:
    """The letters of *text* alone, for matching words across the two editions."""
    text = text.replace("ى", "ي").replace("ـ", "")
    return "".join(ch for ch in text if "ء" <= ch <= "ي")


def _is_marker(token: str) -> bool:
    return bool(_MARKER_RE.match(token)) and not token.startswith("٠")


def _marker_value(token: str) -> int:
    return int("".join(str(ord(ch) - 0x0660) for ch in token))


def _is_header(line: str) -> bool:
    tokens = line.split()
    return (
        bool(tokens)
        and len(tokens) <= 4
        and not any(mark in tokens[0] for mark in _TANWIN)
        and skeleton(tokens[0]) == _HEADER_WORD
        and not any(_is_marker(tok) or re.search(r"[٠-٩]", tok) for tok in tokens)
    )


def _is_basmala(line: str) -> bool:
    return skeleton(line) == _BASMALA_SKELETON and not re.search(r"[٠-٩]", line)


def load_v10(json_path: Path) -> dict[tuple[int, int], list[str]]:
    """The v10 words of every ayah, keyed by (surah, ayah), marker dropped."""
    data = json_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE_SHA256:
        raise ConversionError(
            f"{json_path} has sha256 {digest}, expected {SOURCE_SHA256} ({SOURCE_URL})"
        )
    words: dict[tuple[int, int], list[str]] = {}
    for record in json.loads(data.decode("utf-8")):
        key = (int(record["sura_no"]), int(record["aya_no"]))
        text = record["aya_text"].replace(RUB_EL_HIZB + NBSP, RUB_EL_HIZB).replace(NBSP, " ")
        tokens = text.split()
        if not tokens or not _is_marker(tokens[-1]) or _marker_value(tokens[-1]) != key[1]:
            raise ConversionError(f"{key}: v10 text does not end in its ayah number")
        body = tokens[:-1]
        if any(not _LETTER_RE.search(tok) or _is_marker(tok) for tok in body):
            raise ConversionError(f"{key}: v10 text has a token that is not a word")
        if key in words:
            raise ConversionError(f"{key}: duplicate ayah in the v10 data")
        words[key] = body
    if len(words) != AYAH_COUNT:
        raise ConversionError(f"v10 data has {len(words)} ayat, expected {AYAH_COUNT}")
    return words


def read_ver05(ver05_path: Path) -> list[str]:
    data = ver05_path.read_bytes()
    if not data.startswith(BOM_UTF16_LE):
        raise ConversionError(f"{ver05_path} is not UTF-16 LE with a byte-order mark")
    text = data[len(BOM_UTF16_LE) :].decode("utf-16-le")
    if re.search(r"\r(?!\n)|(?<!\r)\n", text):
        raise ConversionError(f"{ver05_path} mixes line endings")
    return text.split(NEWLINE)


def _place(key, slots, v10_words):
    """Assign each v10 word to the Ver05 word whose letters it starts in."""
    v05_skel = [skeleton(word) for _, _, word in slots]
    v10_skel = [skeleton(word) for word in v10_words]
    if "".join(v05_skel) != "".join(v10_skel):
        raise ConversionError(f"{key}: the letters differ between Ver05 and v10")
    if any(not s for s in v05_skel + v10_skel):
        raise ConversionError(f"{key}: a word without letters")
    starts = []
    offset = 0
    for s in v05_skel:
        starts.append(offset)
        offset += len(s)
    placed: list[list[str]] = [[] for _ in slots]
    offset = 0
    slot = 0
    for word, s in zip(v10_words, v10_skel):
        while slot + 1 < len(starts) and starts[slot + 1] <= offset:
            slot += 1
        placed[slot].append(word)
        offset += len(s)
    if any(not words for words in placed):
        raise ConversionError(f"{key}: v10 joins Ver05 words; no rule for that")
    return placed


def convert(v10: dict[tuple[int, int], list[str]], lines: list[str]) -> str:
    # Per line, the replacement for each whitespace-separated token (None = keep).
    replacements: dict[int, dict[int, str]] = {}
    slots: list[tuple[int, int, str]] = []
    surah = 0
    ayah = 0
    last_line = None
    seen: set[tuple[int, int]] = set()
    final = max(v10)

    for line_no, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if _is_header(stripped):
            if slots:
                raise ConversionError(f"line {line_no + 1}: surah header inside an open ayah")
            surah += 1
            ayah = 0
            continue
        if _is_basmala(stripped):
            continue
        if (surah, ayah) == final:
            break  # the attribution footer
        for tok_no, token in enumerate(stripped.split()):
            if _is_marker(token):
                ayah += 1
                key = (surah, ayah)
                if _marker_value(token) != ayah or key not in v10 or not slots:
                    raise ConversionError(f"line {line_no + 1}: unexpected marker for {key}")
                for (l_no, t_no, _), words in zip(slots, _place(key, slots, v10[key])):
                    replacements.setdefault(l_no, {})[t_no] = " ".join(words)
                seen.add(key)
                slots = []
                last_line = line_no
            elif _LETTER_RE.search(token):
                slots.append((line_no, tok_no, token))
            else:
                raise ConversionError(f"line {line_no + 1}: unrecognised token {token!r}")

    if surah != SURAH_COUNT or seen != set(v10):
        raise ConversionError(f"Ver05 covers {len(seen)} ayat in {surah} surahs")

    out: list[str] = []
    for line_no, line in enumerate(lines[: last_line + 1]):
        table = replacements.get(line_no)
        if table:
            counter = iter(range(len(line.split())))

            def swap(match: re.Match, table=table, counter=counter) -> str:
                return table.get(next(counter), match.group(0))

            line = re.sub(r"\S+", swap, line)
        out.append(line)
    return NEWLINE.join(out) + NEWLINE


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", required=True, type=Path, help="QaloonData_v10.json")
    ap.add_argument("--ver05", required=True, type=Path, help="UthmanicQaloon1-Ver05.txt")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    try:
        text = convert(load_v10(args.json), read_ver05(args.ver05))
    except ConversionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    args.out.write_bytes(BOM_UTF16_LE + text.encode("utf-16-le"))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
detect_range.py — v1

Detects Quran content inside a WhisperX transcription, given a Qalun-riwaya
Quran text file.

Modes
-----
1.  ``range``   → detect the FIRST and LAST ayah present in the transcript.
2.  ``lecture`` → scan the whole transcript for Quran mentions inside Dars or
    explanation-heavy audio.
3.  ``recitation`` → detect the recited surah/range first, then emit timestamped
    Quran spans from only that range.

Design constraints respected
-----------------------------
• WhisperX may not preserve tashkeel -------→ every comparison uses normalize_ar()
• WhisperX word boundaries ≠ Quran words -------→ character-level partial-ratio scoring
• Reciter may not start at ayah 1-------→ configurable search window
• Reciter may not end at the last ayah -------→ configurable search window
• Basmala is NOT assumed to be part of ayah 1 → basmala lines are skipped
• The Quran text is the single source of truth

CLI
---
    python detect_range.py \\
        --quran  "UthmanicQaloon1-Ver05.txt" \\
        --whisperx whisperx.json \
        --output result.json

    python detect_range.py \
        --quran  "UthmanicQaloon1-Ver05.txt" \
        --audio  recitation.mp3 \
        --output result.json

Optional filters / tuning
--------------------------
    --surah "سُورَةُ الفُرقَانِ"   filter to one surah (name as it appears in the file)
    --head-words   N               words from transcript start used for first-ayah scan (default 80)
    --tail-words   N               words from transcript end  used for last-ayah  scan (default 80)
    --search-range N               candidate ayat scanned from each end (default 20)
    --low-conf     F               warn when confidence < F (default 0.40)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

from lecture_mode import detect_quran_mentions_in_lecture
from whisperx_service import WhisperXServiceError, transcribe_audio

# ── Unicode / regex constants ──────────────────────────────────────────────────

# Tashkeel: classical diacritics + Quranic reading marks (incl. U+06EC ۬)
TASHKEEL = re.compile(
    r"[\u0600-\u0605\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]"
)

# Arabic-Indic digits (U+0660–U+0669)
_AR_DIG_TR = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Reverse map: Latin → Arabic-Indic
_TO_ARABIC_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")

AR_DIGIT_RE = re.compile(r"^[٠١٢٣٤٥٦٧٨٩]+$")

# ── Default tuning knobs ───────────────────────────────────────────────────────
HEAD_WORDS   = 80
TAIL_WORDS   = 80
SEARCH_RANGE = 20
LOW_CONF     = 0.40

# ══════════════════════════════════════════════════════════════════════════════
# Arabic normalisation
# ══════════════════════════════════════════════════════════════════════════════

def normalize_ar(text: str) -> str:
    """
    Normalize Arabic text for fuzzy comparison.

    Steps:
    1. Strip tashkeel (vowel marks, shadda, Quranic reading marks).
    2. Unify alef variants (أ إ آ ٱ → ا).
    3. Unify ya/waw variants (ى ؤ ئ ے → ي / و).
    4. Remove every non-Arabic character (Latin letters, digits, punctuation …).
    5. Collapse runs of whitespace.
    """
    text = TASHKEEL.sub("", text)
    text = re.sub(r"[إأآٱ]", "ا", text)
    text = (
        text.replace("ى", "ي")
            .replace("ؤ", "و")
            .replace("ئ", "ي")
            .replace("ے", "ي")
    )
    # Keep only basic Arabic letters (U+0621 - U+064A) and spaces.
    # Everything else (special Quranic marks not caught above, punctuation, …)
    # becomes a space, preventing false letter-boundary merges.
    text = re.sub(r"[^\u0621-\u064A\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _arabic_indic_to_int(s: str) -> int:
    return int(s.translate(_AR_DIG_TR))


def _int_to_arabic_indic(n: int) -> str:
    """Convert an integer to its Arabic-Indic digit string (e.g. 25 → '٢٥')."""
    return str(n).translate(_TO_ARABIC_INDIC)


def _ayah_text_with_marker(text_raw: str, ayah_num: int) -> str:
    """Append the ayah number wrapped in ornamental parentheses ﴿٧﴾."""
    return f"{text_raw} \ufd3e{_int_to_arabic_indic(ayah_num)}\ufd3f"


# ══════════════════════════════════════════════════════════════════════════════
# Quran text parser
# ══════════════════════════════════════════════════════════════════════════════

def _is_surah_header(raw_line: str) -> bool:
    """True when the line is a sūrah-name header (e.g. 'سُورَةُ البَقَرَةِ')."""
    tokens = raw_line.strip().split()
    if not tokens:
        return False
    # Compare first token after stripping tashkeel (keeps ة / ه)
    first = TASHKEEL.sub("", tokens[0])
    return first in {"سورة", "سوره"}


def _is_basmala(raw_line: str) -> bool:
    """
    True when the line is a standalone basmala.

    Detection: after tashkeel strip, the line starts with 'بسم'
    and contains 'الرحمن' or 'لرحمن'.
    Robust against the Uthmani 'اِ۬للَّهِ' ligature form.
    """
    stripped = TASHKEEL.sub("", raw_line.strip())
    first = stripped.split()[0] if stripped.split() else ""
    first_norm = re.sub(r"[^\u0621-\u064A]", "", first)
    tail = re.sub(r"[^\u0621-\u064A\s]", " ", stripped)
    return first_norm == "بسم" and ("لرحمن" in tail or "الرحمن" in tail)


def _is_taawwudh(raw_line: str) -> bool:
    """
    True when the line is a ta'awwudh preamble spoken before the recitation
    (e.g. 'أَعُوذُ بِاللَّهِ مِنَ الشَّيْطَانِ الرَّجِيمِ').
    Only present in some single-surah text files; never in the full Quran file.

    Detection: normalised line starts with 'اعوذ' (أَعُوذُ after stripping
    tashkeel), OR contains 'الشيطن' (الشَّيْطَانِ loses the alef-madda
    encoding under normalize_ar, yielding 'الشيطن').
    """
    norm = normalize_ar(raw_line)
    # Only match the opening word — "اعود"/"اعوذ" at the start of the line.
    # Do NOT match interior occurrences of الشيطان, which appear in Quran verses.
    return norm.startswith("اعوذ") or norm.startswith("اعود")


def parse_ayat(quran_path: str, surah_filter: str | None = None) -> list[dict]:
    """
    Parse a Qalun-riwaya Quran file and return an ordered list of dicts::

        {surah_num, surah_name, ayah_num, text_raw, text_norm, _index}

    Handles
    -------
    - UTF-16 LE (BOM-detected) and UTF-8 files.
    - Verse numbers appearing *before or after* verse text (both conventions
      used by different editions collapse to the same token-stream logic:
      a numeral token flushes the preceding buffer as that verse).
    - Surah headers  (lines starting with سُورَةُ)  → increment surah counter.
    - Basmala lines                                 → skipped entirely.
    - Ta'awwudh lines                               → skipped entirely.
    - Optional surah_filter: if given, only yield ayat for that surah.
    """
    path = Path(quran_path)
    with path.open("rb") as fh:
        bom = fh.read(2)
    encoding = "utf-16" if bom in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
    with path.open(encoding=encoding, errors="replace") as fh:
        lines = fh.readlines()

    ayat: list[dict] = []
    surah_num  = 0
    surah_name = ""
    buf: list[str] = []   # token accumulator for the ayah being assembled
    in_target_surah = (surah_filter is None)
    surah_filter_norm = normalize_ar(surah_filter) if surah_filter is not None else None

    def _flush(num: int) -> None:
        """Flush the accumulator as ayah `num` of the current surah."""
        if not buf:
            return
        if surah_filter is not None and not in_target_surah:
            buf.clear()
            return
        text_raw  = " ".join(buf)
        text_norm = normalize_ar(text_raw)
        if text_norm:
            ayat.append({
                "surah_num":  surah_num,
                "surah_name": surah_name,
                "ayah_num":   num,
                "text_raw":   text_raw,
                "text_norm":  text_norm,
                "_index":     len(ayat),
            })
        buf.clear()

    for raw_line in lines:
        raw_line = raw_line.rstrip("\r\n")
        stripped = raw_line.strip()
        if not stripped:
            continue

        # ── surah header ──────────────────────────────────────────────────────
        if _is_surah_header(stripped):
            # Do NOT flush here — no half-ayah should be lingering at this point.
            buf.clear()
            surah_num  += 1
            surah_name  = stripped
            if surah_filter_norm is None:
                in_target_surah = True
            else:
                surah_name_norm = normalize_ar(surah_name)
                in_target_surah = (
                    surah_filter_norm in surah_name_norm
                    or surah_name_norm in surah_filter_norm
                )
            continue

        # ── preamble lines to skip ────────────────────────────────────────────
        if _is_basmala(stripped) or _is_taawwudh(stripped):
            continue

        # ── tokenise the line and process each token ──────────────────────────
        for token in stripped.split():
            if AR_DIGIT_RE.match(token):
                # Verse number → flush buffer as that verse
                _flush(_arabic_indic_to_int(token))
            else:
                # Only enqueue tokens that contain at least one Arabic letter
                if re.search(r"[\u0621-\u064A]", token):
                    buf.append(token)

    # Trailing buffer (e.g. last line of a file without a trailing numeral):
    # we do NOT flush — incomplete verse text is unreliable for matching.

    return ayat


# ══════════════════════════════════════════════════════════════════════════════
# WhisperX extraction
# ══════════════════════════════════════════════════════════════════════════════

def extract_whisper_words(data: dict | list) -> list[dict]:
    """
    Extract a flat list of ``{word_norm, word_raw, start, end, score}`` dicts
    from a WhisperX JSON output.

    Handles
    -------
    - ``dict`` with ``segments[].words[]``  (word-level alignment output).
    - ``dict`` with ``segments[]`` only     (segment fallback, no word timestamps).
    - Flat ``list`` of word dicts.
    """
    words: list[dict] = []

    def _push(raw: str, start, end, score=None) -> None:
        norm = normalize_ar(raw)
        if norm and start is not None and end is not None:
            words.append({
                "word_norm": norm,
                "word_raw":  raw.strip(),
                "start":     float(start),
                "end":       float(end),
                "score":     score,
            })

    if isinstance(data, dict):
        for seg in data.get("segments", []):
            seg_words = seg.get("words") or []
            if seg_words:
                for w in seg_words:
                    _push(
                        w.get("word") or w.get("text") or "",
                        w.get("start"), w.get("end"), w.get("score"),
                    )
            else:
                # Segment-level fallback: treat entire segment text as one unit
                _push(seg.get("text", ""), seg.get("start"), seg.get("end"))
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            seg_words = item.get("words") or []
            if seg_words:
                # Item is a segment with nested word-level timestamps
                for w in seg_words:
                    _push(
                        w.get("word") or w.get("text") or "",
                        w.get("start"), w.get("end"), w.get("score"),
                    )
            else:
                # Item is already a word-level entry
                _push(
                    item.get("word") or item.get("text") or "",
                    item.get("start"), item.get("end"), item.get("score"),
                )

    return words


def _count_whisperx_segments(data: dict | list) -> int:
    """Count top-level WhisperX segments/items in a loaded JSON response."""
    if isinstance(data, dict):
        return len(data.get("segments", []))
    if isinstance(data, list):
        return len(data)
    return 0


def _default_whisperx_raw_path(output_path: str | Path) -> Path:
    """Place raw WhisperX JSON next to the main result file."""
    output_path = Path(output_path)
    return output_path.with_name(f"{output_path.stem}_whisperx_raw.json")


# ══════════════════════════════════════════════════════════════════════════════
# Fuzzy scoring
# ══════════════════════════════════════════════════════════════════════════════

def _find_quran_start(words: list[dict]) -> int:
    """
    Return the index of the first WhisperX word that is NOT part of an
    opening ta'awwudh or basmala preamble.

    The reciter often begins with:
        أعوذ بالله من الشيطان الرجيم   (≤ 5 words)  ← ta'awwudh
        بسم  الله  الرحمن  الرحيم      (4 words)    ← basmala

    before the actual surah verses start.  Including these words in the
    head window biases global matching towards Al-Fatiha ayah 2
    (الرحمن الرحيم) which appears verbatim in the basmala.

    Key: "بسم" is detected as a *separator* between the two patterns and
    must NOT be in _PREAMBLE_VOCAB, otherwise the ta'awwudh loop would
    consume it and the basmala check would never fire.
    """
    _TAAWWUDH_VOCAB = frozenset({
        "اعوذ", "اعود", "بالله", "بالل", "من",
        "الرجيم", "الشيطان", "الشيطن", "شيطان", "شيطن",
    })
    _BASMALA_REST = frozenset({"الله", "الرحمن", "الرحيم"})

    norms = [w["word_norm"] for w in words[:20]]
    i = 0

    # ── Step 1: skip ta'awwudh ─────────────────────────────────────────────
    # Only enters if the very first word is أعوذ / أعود.
    if i < len(norms) and norms[i] in ("اعوذ", "اعود"):
        end = min(i + 8, len(norms))
        while i < end and norms[i] in _TAAWWUDH_VOCAB:
            i += 1
        # i now points to the first non-ta'awwudh word (typically "بسم")

    # ── Step 2: skip basmala if the next word is بسم ──────────────────────
    if i < len(norms) and norms[i] == "بسم":
        i += 1   # skip "بسم" itself
        # skip the remaining 3 basmala words (الله الرحمن الرحيم), up to 3
        skipped = 0
        while skipped < 3 and i < len(norms) and norms[i] in _BASMALA_REST:
            i += 1
            skipped += 1

    # Safety cap: never skip more than 15 words
    return min(i, 15)


def _global_prefilter(
    ayat: list[dict],
    target_str: str,
    n: int,
) -> list[dict]:
    """
    Fast word-recall prefilter over ALL ayat in the parsed list.

    Returns the top *n* ayat ranked by the fraction of their normalised words
    that appear anywhere in *target_str*.  This O(|ayat| × |ayah_words|)
    first pass dramatically narrows the candidate set before the more
    expensive position-based scoring is applied.

    Used when no ``--surah`` filter is given and the file spans multiple surahs.
    """
    target_words = set(target_str.split())
    if not target_words:
        return ayat[:n]

    ranked = sorted(
        ayat,
        key=lambda a: _word_recall(a["text_norm"].split(), target_words),
        reverse=True,
    )
    return ranked[:n]


def _build_candidate_pool(
    ayat: list[dict],
    search_range: int,
    *,
    global_search: bool,
    window_str: str,
    min_index: int | None = None,
    latest: bool = False,
) -> list[dict]:
    """Return the candidate ayat list for a head/tail window."""
    if global_search:
        prefiltered = _global_prefilter(ayat, window_str, search_range * 4)
        candidates = [
            a for a in prefiltered
            if len(a["text_norm"].split()) >= _MIN_WORDS_GLOBAL
        ]
        if not candidates:
            candidates = prefiltered
        if min_index is not None:
            filtered = [a for a in candidates if a["_index"] >= min_index]
            if filtered:
                candidates = filtered
        return candidates

    return ayat[-search_range:] if latest else ayat[:search_range]


def _score_candidates(
    candidates: list[dict],
    window_str: str,
    pos_thresh: float,
) -> list[tuple[int, float, dict]]:
    """Score each candidate against the given transcript window."""
    scored: list[tuple[int, float, dict]] = []
    for ayah in candidates:
        pos, _ = _find_match_position(ayah["text_norm"], window_str, pos_thresh)
        sc = score_ayah(ayah["text_norm"], window_str)
        scored.append((pos, sc, ayah))
    return scored


def _select_best_candidate(
    scored: list[tuple[int, float, dict]],
    window_len: int,
    *,
    latest: bool,
    global_search: bool,
) -> tuple[dict, float]:
    """Pick the best candidate using the existing position/score rules."""
    if global_search:
        positioned = [
            (pos, sc, ay) for pos, sc, ay in scored
            if pos < window_len and sc >= _HIGH_CONF_POSITION
        ]
    else:
        positioned = [(pos, sc, ay) for pos, sc, ay in scored if pos < window_len]

    if positioned:
        positioned.sort(key=lambda t: ((-t[0]) if latest else t[0], -t[1]))
        _, best_score, best_ayah = positioned[0]
    else:
        scored.sort(key=lambda t: -t[1])
        _, best_score, best_ayah = scored[0]

    return best_ayah, best_score

def _partial_ratio(needle: str, haystack: str) -> float:
    """
    Best ``SequenceMatcher.ratio`` of *needle* against any same-length
    sub-window of *haystack*.

    Analogous to fuzzywuzzy's ``partial_ratio``.  When the haystack is longer
    than the needle (the typical case), this finds the best-aligned fragment
    rather than penalising the score for surrounding context words.

    Complexity: O(|haystack| / step × |needle|) — fast enough for short Arabic
    verses (≤ ~200 chars) against an 80-word window (≤ ~500 chars).
    """
    n = len(needle)
    h = len(haystack)
    if n == 0 or h == 0:
        return 0.0
    if n >= h:
        return SequenceMatcher(None, needle, haystack, autojunk=False).ratio()

    best = 0.0
    step = max(1, n // 5)
    for start in range(0, h - n + 1, step):
        r = SequenceMatcher(
            None, needle, haystack[start: start + n], autojunk=False,
        ).ratio()
        if r > best:
            best = r
        if best > 0.97:   # early exit — practically a perfect match
            break
    return best


def _find_match_position(
    needle: str,
    haystack: str,
    min_score: float = 0.40,
) -> tuple[int, float]:
    """
    Slide a same-length window across *haystack* and return
    ``(earliest_pos, best_score)`` where *earliest_pos* is the leftmost
    start-index that achieves a score ≥ *min_score*.

    If no window reaches *min_score*, returns ``(len(haystack), best_score)``
    so the caller can still rank by score even in the low-confidence case.
    """
    n, h = len(needle), len(haystack)
    if n == 0 or h == 0:
        return h, 0.0
    if n >= h:
        sc = SequenceMatcher(None, needle, haystack, autojunk=False).ratio()
        return (0 if sc >= min_score else h), sc

    best_score   = 0.0
    earliest_pos = h          # sentinel: "not found"
    step = max(1, n // 5)

    for start in range(0, h - n + 1, step):
        r = SequenceMatcher(
            None, needle, haystack[start: start + n], autojunk=False,
        ).ratio()
        if r > best_score:
            best_score = r
        if r >= min_score and start < earliest_pos:
            earliest_pos = start

    return earliest_pos, best_score


def _word_recall(ayah_words: list[str], transcript_words: set[str]) -> float:
    """
    Fraction of *ayah_words* that appear anywhere in *transcript_words*.
    Measures how fully the ayah is covered by the transcript window,
    independent of window length (unlike Jaccard).
    """
    if not ayah_words:
        return 0.0
    return sum(1 for w in ayah_words if w in transcript_words) / len(ayah_words)


def score_ayah(ayah_norm: str, transcript_str: str) -> float:
    """
    Combined confidence score (0–1) for how well *ayah_norm* matches
    *transcript_str*:

    - **partial_ratio** (char-level): finds the best aligning substring of the
      transcript for the ayah, handling length mismatches gracefully.
    - **word recall**: fraction of ayah words found anywhere in the transcript
      window (robust to WhisperX word-boundary and insertion noise, and unlike
      Jaccard does not penalise short ayat for the large transcript denominator).

    Final score is the average of the two signals.
    """
    pr  = _partial_ratio(ayah_norm, transcript_str)
    rec = _word_recall(ayah_norm.split(), set(transcript_str.split()))
    return round((pr + rec) / 2.0, 4)


# ══════════════════════════════════════════════════════════════════════════════
# Core detection
# ══════════════════════════════════════════════════════════════════════════════

# Minimum score required at a position for that position to be considered
# "reliably found" rather than a spurious partial alignment.
_POSITION_THRESHOLD        = 0.55   # used when --surah is given / single-surah file
_POSITION_THRESHOLD_GLOBAL = 0.65   # stricter threshold for full-Quran global search
                                    # prevents short ayat (≤3 words) from spuriously
                                    # matching common character sequences

# In global mode, only use *position* as the tiebreaker for ayat whose
# score meets this bar.  Ayat below this threshold rank by score alone,
# which prevents low-confidence matches from other surahs from winning
# purely by happening to appear late/early in the search window.
_HIGH_CONF_POSITION = 0.75

# Minimum number of words an ayah must have to be used as a first/last candidate
# in global-search mode.  Very short ayat (≤4 words) produce spurious late-position
# hits by matching common endings (e.g. العزيز الرحيم, الرحمن الرحيم).
_MIN_WORDS_GLOBAL = 5


def detect_first_ayah(
    ayat: list[dict],
    words: list[dict],
    head_n: int,
    search_range: int,
    *,
    global_search: bool = False,
) -> tuple[dict, float]:
    """
    Detect the FIRST ayah in the recording.

    Strategy
    --------
    For each candidate (first *search_range* ayat, or global prefilter):

    1.  Find the **earliest position** in the transcript head where the ayah
        achieves a fuzzy score ≥ ``_POSITION_THRESHOLD``.
    2.  Independently compute ``score_ayah`` (partial-ratio + recall) as a
        quality measure.

    Decision:

    - **If any candidates produced a reliable position**: pick the one with the
      smallest (earliest) position.  This correctly identifies which ayah the
      reciter started on even when multiple ayat fit the head window.
    - **Fallback** (no candidate met the threshold): rank purely by
      ``score_ayah`` — avoids returning a completely wrong ayah when the
      head window is noisy.

    Global search mode
    ------------------
    When *global_search* is True (full-Quran file, no ``--surah``):

    - Leading ta'awwudh / basmala words are skipped from the head window so
      that "الرحمن الرحيم" in the preamble cannot spuriously match Al-Fatiha.
    - All ayat are pre-screened by word-recall before position detection,
      keeping the *search_range* × 4 best candidates.
    """
    skip = _find_quran_start(words) if global_search else 0
    head_words = words[skip: skip + head_n] if global_search else words[:head_n]

    head_str = " ".join(w["word_norm"] for w in head_words)
    pos_thresh = _POSITION_THRESHOLD_GLOBAL if global_search else _POSITION_THRESHOLD
    candidates = _build_candidate_pool(
        ayat,
        search_range,
        global_search=global_search,
        window_str=head_str,
    )
    scored = _score_candidates(candidates, head_str, pos_thresh)
    return _select_best_candidate(
        scored,
        len(head_str),
        latest=False,
        global_search=global_search,
    )


def detect_last_ayah(
    ayat: list[dict],
    words: list[dict],
    tail_n: int,
    search_range: int,
    *,
    global_search: bool = False,
    first_ayah: dict | None = None,
) -> tuple[dict, float]:
    """
    Detect the LAST ayah in the recording.

    Mirror of ``detect_first_ayah``: among the last *search_range* ayat
    (or a global prefilter when *global_search* is True), the one whose text
    is found at the **largest (latest)** reliable position in the transcript
    tail wins.

    No preamble-skip is needed for the tail (recordings end with the last
    verse, not with a postamble).
    """
    tail_str = " ".join(w["word_norm"] for w in words[-tail_n:])
    pos_thresh = _POSITION_THRESHOLD_GLOBAL if global_search else _POSITION_THRESHOLD
    min_index = first_ayah.get("_index", 0) if first_ayah is not None else None
    candidates = _build_candidate_pool(
        ayat,
        search_range,
        global_search=global_search,
        window_str=tail_str,
        min_index=min_index,
        latest=True,
    )
    scored = _score_candidates(candidates, tail_str, pos_thresh)
    return _select_best_candidate(
        scored,
        len(tail_str),
        latest=True,
        global_search=global_search,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Sanity checks / warnings
# ══════════════════════════════════════════════════════════════════════════════

def build_warnings(
    first: dict,
    first_conf: float,
    last: dict,
    last_conf: float,
    words: list[dict],
    low_conf: float,
    *,
    global_search: bool = False,
) -> list[str]:
    """Return a list of human-readable warning strings."""
    w: list[str] = []

    # ── global-search notice ───────────────────────────────────────────────
    if global_search:
        w.append(
            "No --surah specified: ran a global search across all surahs in the file. "
            "Specify --surah for faster, more accurate results."
        )

    # ── very sparse transcript ─────────────────────────────────────────────
    if len(words) < 20:
        w.append(
            f"Only {len(words)} word(s) in WhisperX output — "
            "transcript may be empty, too short, or corrupt."
        )

    # ── low confidence ─────────────────────────────────────────────────────
    if first_conf < low_conf:
        w.append(
            f"Low confidence for first ayah ({first_conf:.2f} < {low_conf:.2f}). "
            "Try increasing --head-words or --search-range, "
            "or verify that --quran matches the riwaya recited."
        )
    if last_conf < low_conf:
        w.append(
            f"Low confidence for last ayah ({last_conf:.2f} < {low_conf:.2f}). "
            "Try increasing --tail-words or --search-range."
        )

    # ── order inversion ────────────────────────────────────────────────────
    f_idx = first.get("_index", 0)
    l_idx = last.get("_index", 0)
    if f_idx > l_idx:
        w.append(
            "Detected first ayah falls AFTER the detected last ayah in the "
            "Quran file — alignment is likely wrong. "
            "Consider widening --search-range."
        )

    # ── suspiciously narrow range for a long audio ────────────────────────
    if l_idx - f_idx < 2 and len(words) >= 40:
        duration = (words[-1]["end"] - words[0]["start"]) if words else 0.0
        if duration > 30:
            w.append(
                f"Only {l_idx - f_idx + 1} ayah(s) detected over "
                f"{duration:.0f}s of audio — "
                "this looks suspiciously narrow. "
                "Consider increasing --search-range."
            )

    # ── overall very low average confidence ───────────────────────────────
    if first_conf > 0.0 and last_conf > 0.0:
        avg = (first_conf + last_conf) / 2.0
        if avg < 0.25:
            w.append(
                f"Average confidence is very low ({avg:.2f}). "
                "Ensure the Quran file matches the riwaya actually recited."
            )

    return w


def _ayah_entry(ayah: dict, conf: float) -> dict:
    return {
        "surah_num":  ayah["surah_num"],
        "surah_name": ayah["surah_name"],
        "ayah_num":   ayah["ayah_num"],
        "text":       ayah["text_raw"],
        "confidence": conf,
    }


def _ayat_in_detected_range(
    ayat: list[dict],
    first_ayah: dict,
    last_ayah: dict,
) -> list[dict]:
    """
    Return ayat from the detected recitation range.

    Recitation audio should stay inside one surah.  The first ayah is used as
    the surah anchor; if the global tail search picks another surah, fall back
    to the rest of the anchored surah instead of mixing unrelated surahs.
    """
    target_surah = first_ayah["surah_num"]
    first_index = first_ayah["_index"]

    same_surah_last = last_ayah["surah_num"] == target_surah
    if same_surah_last and last_ayah["_index"] >= first_index:
        last_index = last_ayah["_index"]
    else:
        same_surah = [a for a in ayat if a["surah_num"] == target_surah]
        last_index = same_surah[-1]["_index"] if same_surah else first_index

    return [
        a for a in ayat
        if a["surah_num"] == target_surah
        and first_index <= a["_index"] <= last_index
    ]


def _trim_match_to_ayah_range(
    match: dict,
    recitation_ayat: list[dict],
    from_ayah: int,
    to_ayah: int,
) -> dict | None:
    selected_ayat = [
        a for a in recitation_ayat
        if from_ayah <= a["ayah_num"] <= to_ayah
    ]
    if not selected_ayat:
        return None

    full_text = "\n".join(
        _ayah_text_with_marker(a["text_raw"], a["ayah_num"])
        for a in selected_ayat
    )
    trimmed = dict(match)
    trimmed["from_ayah"] = selected_ayat[0]["ayah_num"]
    trimmed["to_ayah"] = selected_ayat[-1]["ayah_num"]
    trimmed["text"] = full_text
    trimmed["full_text"] = full_text
    return trimmed


def _select_recitation_timeline(
    matches: list[dict],
    recitation_ayat: list[dict],
    *,
    max_span: int,
) -> list[dict]:
    """
    Keep one forward-moving set of recitation display spans.

    The lecture matcher intentionally reports every strong overlapping window.
    For continuous recitation that is too noisy, so this pass keeps the earliest
    high-confidence span that advances the ayah number and trims overlap from
    the already displayed ayat.
    """
    if not matches or not recitation_ayat:
        return []

    first_ayah_num = recitation_ayat[0]["ayah_num"]
    last_ayah_num = recitation_ayat[-1]["ayah_num"]
    selected: list[dict] = []
    last_to_ayah = first_ayah_num - 1
    last_end_time = -1.0

    ordered = sorted(
        matches,
        key=lambda m: (
            m["start_time"],
            -m["confidence"],
            m["to_ayah"] - m["from_ayah"],
        ),
    )

    for match in ordered:
        if match["to_ayah"] <= last_to_ayah:
            continue
        if selected and match["start_time"] < last_end_time - 0.5:
            continue

        from_ayah = max(match["from_ayah"], last_to_ayah + 1)
        to_ayah = min(match["to_ayah"], from_ayah + max_span - 1)
        if from_ayah > to_ayah:
            continue

        trimmed = _trim_match_to_ayah_range(
            match,
            recitation_ayat,
            from_ayah,
            to_ayah,
        )
        if trimmed is None:
            continue

        selected.append(trimmed)
        last_to_ayah = trimmed["to_ayah"]
        last_end_time = trimmed["end_time"]

        if last_to_ayah >= last_ayah_num:
            break

    # ── Clamp boundaries so frames switch exactly at detected transitions ──────
    # Forward pass: ensure start_time >= previous end_time
    for i in range(1, len(selected)):
        prev_end = selected[i - 1]["end_time"]
        if selected[i]["start_time"] < prev_end:
            selected[i] = dict(selected[i])
            selected[i]["start_time"] = round(prev_end, 2)

    # Backward pass: ensure end_time <= next start_time
    for i in range(len(selected) - 1):
        next_start = selected[i + 1]["start_time"]
        if selected[i]["end_time"] > next_start:
            selected[i] = dict(selected[i])
            selected[i]["end_time"] = round(next_start, 2)

    return selected


# ══════════════════════════════════════════════════════════════════════════════
# CLI entry point
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect Quran content in a WhisperX transcription.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--quran", required=True,
        help="Path to Qalun Quran text file (single-surah or full Quran).",
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--whisperx",
        help="Path to an existing WhisperX JSON transcription output.",
    )
    source_group.add_argument(
        "--audio",
        help="Path to an audio file to transcribe with WhisperX via Replicate.",
    )
    parser.add_argument(
        "--output", default="result.json",
        help="Path for the output JSON.",
    )
    parser.add_argument(
        "--surah", default=None,
        help=(
            "Optional: surah name to restrict search to "
            "(as it appears in the file, e.g. 'سُورَةُ الفُرقَانِ'). "
            "Used in range/recitation modes; lecture mode always scans the full Quran."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["range", "lecture", "recitation"],
        default="range",
        help=(
            "range = detect first/last ayah; "
            "lecture = detect Quran mentions in lecture audio; "
            "recitation = detect range, then emit timestamped ayah spans inside it."
        ),
    )
    parser.add_argument(
        "--head-words", type=int, default=HEAD_WORDS,
        help="WhisperX words from the start used for first-ayah detection.",
    )
    parser.add_argument(
        "--tail-words", type=int, default=TAIL_WORDS,
        help="WhisperX words from the end used for last-ayah detection.",
    )
    parser.add_argument(
        "--search-range", type=int, default=SEARCH_RANGE,
        help="Number of candidate ayat scanned from each end of the surah.",
    )
    parser.add_argument(
        "--low-conf", type=float, default=LOW_CONF,
        help="Confidence threshold below which a warning is emitted.",
    )
    parser.add_argument(
        "--max-span", type=int, default=5,
        help="Maximum number of consecutive ayat to match in lecture mode.",
    )
    parser.add_argument(
        "--lecture-threshold", type=float, default=0.78,
        help="Minimum confidence for accepting Quran matches in lecture mode.",
    )
    parser.add_argument(
        "--min-matched-words", type=int, default=4,
        help="Minimum overlapping Quran words required in lecture mode.",
    )
    args = parser.parse_args()

    # ── Step 1: parse Quran ────────────────────────────────────────────────────
    print(f"[1/4] Parsing Quran text: {args.quran}")
    effective_surah = None if args.mode == "lecture" else args.surah
    ayat = parse_ayat(args.quran, surah_filter=effective_surah)
    if not ayat:
        print(
            "ERROR: No ayat parsed. "
            "Check --quran path, encoding, and --surah spelling.",
            file=sys.stderr,
        )
        sys.exit(1)
    n_surahs = len({a["surah_num"] for a in ayat})
    print(f"      {len(ayat)} ayat parsed across {n_surahs} surah(s).")
    if args.mode == "lecture" and args.surah is not None:
        print("      Note: ignoring --surah in lecture mode; scanning the full Quran.")

    # ── Step 2: load or generate WhisperX ──────────────────────────────────────
    out_path = Path(args.output)
    if args.whisperx is not None:
        print(f"[2/4] Loading WhisperX JSON: {args.whisperx}")
        wx_path = Path(args.whisperx)
        if not wx_path.exists():
            print(f"ERROR: WhisperX file not found: {args.whisperx}", file=sys.stderr)
            sys.exit(1)
        try:
            with wx_path.open(encoding="utf-8") as fh:
                wx_data = json.load(fh)
        except json.JSONDecodeError as error:
            print(
                f"ERROR: Failed to parse WhisperX JSON '{args.whisperx}': {error}",
                file=sys.stderr,
            )
            sys.exit(1)

        transcript_source = "whisperx_json"
        transcript_input_path = str(wx_path.resolve())
        whisperx_raw_output_path = str(wx_path.resolve())
        whisperx_model_ref = None
        whisperx_segment_count = _count_whisperx_segments(wx_data)
    else:
        print(f"[2/4] Transcribing audio with WhisperX: {args.audio}")
        raw_output_path = _default_whisperx_raw_path(out_path)
        try:
            service_result = transcribe_audio(args.audio, save_raw_to=raw_output_path)
        except (FileNotFoundError, WhisperXServiceError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            sys.exit(1)

        wx_data = service_result.output
        transcript_source = "audio"
        transcript_input_path = str(Path(args.audio).resolve())
        whisperx_raw_output_path = service_result.raw_output_path
        whisperx_model_ref = service_result.model_ref
        whisperx_segment_count = service_result.segment_count
        print(
            f"      WhisperX raw JSON saved to {service_result.raw_output_path} "
            f"({service_result.segment_count} segments, {service_result.word_count} words)."
        )

    words = extract_whisper_words(wx_data)
    if not words:
        print("ERROR: No word tokens extracted from WhisperX output.", file=sys.stderr)
        sys.exit(1)
    duration = words[-1]["end"] - words[0]["start"]
    print(
        f"      {len(words)} word tokens extracted "
        f"({duration:.1f}s, "
        f"{words[0]['start']:.2f}s – {words[-1]['end']:.2f}s)."
    )

    # Clamp parameters to actual data sizes
    head_n  = min(args.head_words,   len(words))
    tail_n  = min(args.tail_words,   len(words))
    s_range = min(args.search_range, len(ayat))

    # Decide whether to run in global-search mode
    global_search = (n_surahs > 1 and args.surah is None)

    if args.mode == "lecture":
        print("[3/4] Detecting Quran mentions inside lecture...")

        mentions = detect_quran_mentions_in_lecture(
            ayat,
            words,
            max_span=args.max_span,
            min_score=args.lecture_threshold,
            min_matched_words=args.min_matched_words,
        )

        result = {
            "matches": mentions,
            "meta": {
                "input_type": transcript_source,
                "input_path": transcript_input_path,
                "whisperx_raw_output_path": whisperx_raw_output_path,
                "whisperx_model_ref": whisperx_model_ref,
                "whisperx_segments": whisperx_segment_count,
                "total_ayat_in_file": len(ayat),
                "whisperx_words": len(words),
                "audio_start_s": words[0]["start"],
                "audio_end_s": words[-1]["end"],
                "audio_duration_s": round(duration, 2),
                "mode": "lecture",
                "max_span": args.max_span,
                "lecture_threshold": args.lecture_threshold,
                "min_matched_words": args.min_matched_words,
                "surah_filter_ignored": args.surah is not None,
            },
        }

        print(f"[4/4] Writing result → {out_path}")
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)

        print()
        print("=" * 64)

        if not mentions:
            print("No Qur'an ayat detected.")
        else:
            for match in mentions:
                if match["from_ayah"] == match["to_ayah"]:
                    ayah_range = f"#{match['from_ayah']}"
                else:
                    ayah_range = f"#{match['from_ayah']}–{match['to_ayah']}"

                print(
                    f"{match['surah_name']} {ayah_range} "
                    f"({match['start_time']:.2f}s–{match['end_time']:.2f}s, "
                    f"conf {match['confidence']:.2f})"
                )
                print(f"Detected: {match['detected_text']}")
                print("Quran:")
                print(match["full_text"])
                print("-" * 64)

        print(f"\nSaved to: {out_path.resolve()}\n")
        return

    # ── Step 3: detect first & last ayah ──────────────────────────────────────
    mode_label = "global" if global_search else f"search_range={s_range}"
    print(
        f"[3/4] Detecting range  "
        f"(head={head_n} words, tail={tail_n} words, {mode_label}) …"
    )
    first_ayah, first_conf = detect_first_ayah(
        ayat, words, head_n, s_range, global_search=global_search,
    )
    last_ayah, last_conf = detect_last_ayah(
        ayat, words, tail_n, s_range, global_search=global_search,
        first_ayah=first_ayah,
    )

    warnings = build_warnings(
        first_ayah, first_conf,
        last_ayah,  last_conf,
        words,
        args.low_conf,
        global_search=global_search,
    )

    if args.mode == "recitation":
        print("[3/4] Refining recitation matches inside detected range...")
        recitation_ayat = _ayat_in_detected_range(ayat, first_ayah, last_ayah)
        raw_mentions = detect_quran_mentions_in_lecture(
            recitation_ayat,
            words,
            max_span=args.max_span,
            min_score=args.lecture_threshold,
            min_matched_words=args.min_matched_words,
            max_merged_ayat=args.max_span,
        )
        mentions = _select_recitation_timeline(
            raw_mentions,
            recitation_ayat,
            max_span=args.max_span,
        )

        result = {
            "first_ayah": _ayah_entry(first_ayah, first_conf),
            "last_ayah":  _ayah_entry(last_ayah,  last_conf),
            "matches": mentions,
            "warnings": warnings,
            "meta": {
                "input_type": transcript_source,
                "input_path": transcript_input_path,
                "whisperx_raw_output_path": whisperx_raw_output_path,
                "whisperx_model_ref": whisperx_model_ref,
                "whisperx_segments": whisperx_segment_count,
                "total_ayat_in_file": len(ayat),
                "recitation_ayat_scanned": len(recitation_ayat),
                "whisperx_words": len(words),
                "audio_start_s": words[0]["start"],
                "audio_end_s": words[-1]["end"],
                "audio_duration_s": round(duration, 2),
                "mode": "recitation",
                "max_span": args.max_span,
                "lecture_threshold": args.lecture_threshold,
                "min_matched_words": args.min_matched_words,
                "head_words_used": head_n,
                "tail_words_used": tail_n,
                "search_range_used": s_range,
                "global_search": global_search,
                "detected_surah_num": first_ayah["surah_num"],
                "detected_surah_name": first_ayah["surah_name"],
            },
        }

        print(f"[4/4] Writing result → {out_path}")
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)

        print()
        print("=" * 64)
        print(
            f"Detected range: {first_ayah['surah_name']} "
            f"#{first_ayah['ayah_num']}–#{last_ayah['ayah_num']} "
            f"(matches: {len(mentions)})"
        )
        if warnings:
            print("Warnings:")
            for msg in warnings:
                print(f"- {msg}")
        for match in mentions:
            if match["from_ayah"] == match["to_ayah"]:
                ayah_range = f"#{match['from_ayah']}"
            else:
                ayah_range = f"#{match['from_ayah']}–{match['to_ayah']}"
            print(
                f"{match['surah_name']} {ayah_range} "
                f"({match['start_time']:.2f}s–{match['end_time']:.2f}s, "
                f"conf {match['confidence']:.2f})"
            )
        print(f"\nSaved to: {out_path.resolve()}\n")
        return

    # ── Step 4: assemble and write result ──────────────────────────────────────
    result = {
        "first_ayah": _ayah_entry(first_ayah, first_conf),
        "last_ayah":  _ayah_entry(last_ayah,  last_conf),
        "warnings":   warnings,
        "meta": {
            "input_type":         transcript_source,
            "input_path":         transcript_input_path,
            "whisperx_raw_output_path": whisperx_raw_output_path,
            "whisperx_model_ref": whisperx_model_ref,
            "whisperx_segments":  whisperx_segment_count,
            "total_ayat_in_file": len(ayat),
            "whisperx_words":     len(words),
            "audio_start_s":      words[0]["start"],
            "audio_end_s":        words[-1]["end"],
            "audio_duration_s":   round(duration, 2),
            "head_words_used":    head_n,
            "tail_words_used":    tail_n,
            "search_range_used":  s_range,
            "global_search":      global_search,
        },
    }

    print(f"[4/4] Writing result → {out_path}")
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    # ── Console summary ────────────────────────────────────────────────────────
    SEP = "═" * 64
    fa  = result["first_ayah"]
    la  = result["last_ayah"]
    print(f"\n{SEP}")
    print(
        f"  First ayah │ {fa['surah_name']} — #{fa['ayah_num']}"
        f"  (conf {fa['confidence']:.2f})"
    )
    print(f"             │ {fa['text'][:70]}")
    print()
    print(
        f"  Last ayah  │ {la['surah_name']} — #{la['ayah_num']}"
        f"  (conf {la['confidence']:.2f})"
    )
    print(f"             │ {la['text'][:70]}")
    if warnings:
        print()
        print("  ⚠  Warnings:")
        for msg in warnings:
            print(f"     • {msg}")
    print(SEP)
    print(f"\nSaved to: {out_path.resolve()}\n")


if __name__ == "__main__":
    main()

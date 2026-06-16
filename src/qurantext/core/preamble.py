"""Detection and rendering of the spoken preamble (istiʿādha / basmala).

Many recitations open with the istiʿādha («أعوذ بالله من الشيطان الرجيم») and/or
the basmala («بسم الله الرحمن الرحيم») before the first ayah. These lines are
stripped from the canonical Quran file during parsing (see
``quran_parser._is_basmala`` / ``_is_taawwudh``), so the matcher never has an
ayah to anchor them to. As a result the leading preamble audio is silently
absorbed into the first ayah's match — pulling its ``start_time`` back to the top
of the recording and shifting every word-highlight index — which makes the video
timing look permanently off.

This module detects the leading preamble in the WhisperX word stream and turns it
into its own timed display segment(s), so the preamble shows with its own timing
and the following ayah is trimmed back to where it actually begins.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Any

# Normalised vocabulary (matches ``normalize_detection_ar`` output) used to
# recognise the spoken preamble at the very start of a recitation.
TAAWWUDH_VOCAB = frozenset(
    {
        "اعوذ",
        "اعود",
        "بالله",
        "بالل",
        "من",
        "الرجيم",
        "الشيطان",
        "الشيطن",
        "شيطان",
        "شيطن",
    }
)
BASMALA_REST = frozenset({"الله", "الرحمن", "الرحيم"})

# Canonical, fully-pointed display text + header label for each preamble kind.
ISTIAADHA_DISPLAY = "أَعُوذُ بِاللَّهِ مِنَ الشَّيْطَانِ الرَّجِيمِ"
BASMALA_DISPLAY = "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ"
ISTIAADHA_LABEL = "الاستعاذة"
BASMALA_LABEL = "البسملة"

_PRESENTATION: dict[str, tuple[str, str]] = {
    "istiaadha": (ISTIAADHA_DISPLAY, ISTIAADHA_LABEL),
    "basmala": (BASMALA_DISPLAY, BASMALA_LABEL),
}

# How many WhisperX words from the start we inspect for a preamble.
_SCAN_WINDOW = 20


@dataclass(slots=True)
class PreambleSpan:
    """A contiguous run of WhisperX words forming one preamble line."""

    kind: str  # "istiaadha" | "basmala"
    start_index: int  # inclusive index into the word list
    end_index: int  # exclusive index into the word list


def detect_leading_preamble(words: list[dict]) -> tuple[list[PreambleSpan], int]:
    """Return the leading preamble spans and the index of the first ayah word.

    Mirrors the skip logic used for global range search: an optional istiʿādha
    run followed by an optional basmala run. The returned index is where genuine
    Quran recitation begins (equal to ``0`` when no preamble is present).
    """
    norms = [str(word.get("word_norm", "")) for word in words[:_SCAN_WINDOW]]
    spans: list[PreambleSpan] = []
    index = 0

    if index < len(norms) and norms[index] in ("اعوذ", "اعود"):
        start = index
        end = min(index + 8, len(norms))
        while index < end and norms[index] in TAAWWUDH_VOCAB:
            index += 1
        spans.append(PreambleSpan("istiaadha", start, index))

    if index < len(norms) and norms[index] == "بسم":
        start = index
        index += 1
        skipped = 0
        while skipped < 3 and index < len(norms) and norms[index] in BASMALA_REST:
            index += 1
            skipped += 1
        spans.append(PreambleSpan("basmala", start, index))

    return spans, index


def _build_span_match(words: list[dict], span: PreambleSpan) -> dict[str, Any] | None:
    """Build a render-ready match dict for one preamble span, or ``None``."""
    seg_words = words[span.start_index : span.end_index]
    if not seg_words:
        return None

    start_time = round(float(seg_words[0]["start"]), 2)
    # End at the next token's start so the card stays up until the following
    # preamble line or the first ayah begins (no dark gap). Fall back to the
    # span's own last word when it is the final token in the stream.
    if span.end_index < len(words):
        end_time = round(float(words[span.end_index]["start"]), 2)
    else:
        end_time = round(float(seg_words[-1]["end"]), 2)
    if end_time <= start_time:
        end_time = round(float(seg_words[-1]["end"]), 2)
    if end_time <= start_time:
        return None

    display, label = _PRESENTATION[span.kind]
    return {
        "kind": "preamble",
        "preamble_kind": span.kind,
        "surah_name": label,
        "from_ayah": None,
        "to_ayah": None,
        "confidence": 1.0,
        "start_time": start_time,
        "end_time": end_time,
        "text": display,
        "full_text": display,
        "detected_text": " ".join(str(w.get("word_raw", "")) for w in seg_words).strip(),
        "word_timings": [
            {"word": str(w.get("word_raw", "")), "start": w["start"], "end": w["end"]}
            for w in seg_words
        ],
    }


def extract_preamble(words: list[dict]) -> tuple[list[dict[str, Any]], float | None]:
    """Return ``(preamble_matches, boundary_time)`` for the leading preamble.

    ``boundary_time`` is the start time of the first genuine ayah word — the
    point any following match should be trimmed back to. Both are empty/``None``
    when no preamble is detected.
    """
    spans, first_index = detect_leading_preamble(words)
    if not spans:
        return [], None

    matches = [match for span in spans if (match := _build_span_match(words, span))]
    boundary_time = (
        float(words[first_index]["start"]) if first_index < len(words) else None
    )
    return matches, boundary_time


def trim_leading_preamble(
    matches: list[dict[str, Any]], boundary_time: float, *, eps: float = 0.1
) -> None:
    """Trim the earliest match so it no longer covers the preamble audio.

    The first ayah match typically absorbs the preamble words (its ``start_time``
    sits at the top of the recording and its ``word_timings`` lead with the
    preamble). Push its start to *boundary_time* and drop the preamble words so
    its word-highlight indices line up with its (preamble-free) display text.
    Mutates the chosen match in place.
    """
    if not matches:
        return

    target = min(matches, key=lambda m: float(m.get("start_time", inf)))
    if float(target.get("start_time", inf)) >= boundary_time:
        return

    target["start_time"] = round(boundary_time, 2)
    word_timings = target.get("word_timings")
    if word_timings:
        target["word_timings"] = [
            wt for wt in word_timings if float(wt.get("start", 0.0)) >= boundary_time - eps
        ]

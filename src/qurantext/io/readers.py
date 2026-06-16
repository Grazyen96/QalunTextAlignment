from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from os import PathLike
from pathlib import Path
from typing import Any

from qurantext.core.arabic import (
    normalize_alignment_ar,
    normalize_detection_ar,
    normalize_full_aya_ar,
)

logger = logging.getLogger(__name__)

TextNormalizer = Callable[[str], str]


def load_json(path: str | PathLike[str]) -> Any:
    """Load JSON data from disk."""
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh)


def _iter_whisperx_segments(data: dict | list) -> Iterator[dict[str, Any]]:
    """Yield normalized WhisperX segment-like dictionaries."""
    raw_segments: Any
    if isinstance(data, dict):
        raw_segments = data.get("segments", [])
    elif isinstance(data, list):
        raw_segments = data
    else:
        raw_segments = []

    for item in raw_segments:
        if isinstance(item, dict):
            yield item


def _iter_segment_words(segment: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield word dictionaries from one WhisperX segment-like item."""
    for item in segment.get("words") or []:
        if isinstance(item, dict):
            yield item


def extract_alignment_words(
    output: dict | list,
    *,
    normalizer: TextNormalizer = normalize_alignment_ar,
) -> list[dict]:
    """Return audioAlignment-style word entries from WhisperX output."""
    words: list[dict] = []

    skipped = 0
    for segment in _iter_whisperx_segments(output):
        segment_words = list(_iter_segment_words(segment))
        if not segment_words:
            segment_words = [segment]
        for word_data in segment_words:
            raw_word = str(word_data.get("word") or word_data.get("text") or "")
            start = word_data.get("start")
            end = word_data.get("end")
            norm = normalizer(raw_word)
            if norm and start is not None and end is not None:
                words.append(
                    {
                        "word_raw": raw_word.strip(),
                        "word_norm": norm,
                        "start": start,
                        "end": end,
                    }
                )
            else:
                skipped += 1
    if skipped:
        logger.warning(
            "extract_alignment_words: skipped %d word(s) with missing timestamps or empty norm",
            skipped,
        )
    return words


def extract_matching_words(
    data: dict | list,
    *,
    normalizer: TextNormalizer = normalize_detection_ar,
) -> list[dict]:
    """Return detect_range-style word entries from WhisperX output."""
    words: list[dict] = []
    skipped = 0

    def push(raw: Any, start: Any, end: Any, score: Any = None) -> None:
        nonlocal skipped
        raw = str(raw) if raw is not None else ""
        norm = normalizer(raw)
        if not norm or start is None or end is None:
            skipped += 1
            return
        # Tolerate messy WhisperX/hand-edited JSON: a single non-numeric
        # timestamp skips that word instead of crashing the whole load.
        try:
            start_f, end_f = float(start), float(end)
        except (TypeError, ValueError):
            skipped += 1
            return
        words.append(
            {
                "word_norm": norm,
                "word_raw": raw.strip(),
                "start": start_f,
                "end": end_f,
                "score": score,
            }
        )

    for segment in _iter_whisperx_segments(data):
        segment_words = list(_iter_segment_words(segment))
        if segment_words:
            for word_data in segment_words:
                push(
                    word_data.get("word") or word_data.get("text") or "",
                    word_data.get("start"),
                    word_data.get("end"),
                    word_data.get("score"),
                )
        else:
            push(
                segment.get("word") or segment.get("text") or "",
                segment.get("start"),
                segment.get("end"),
                segment.get("score"),
            )

    if skipped:
        logger.warning(
            "extract_matching_words: skipped %d word(s) with missing timestamps or empty norm",
            skipped,
        )
    return words


def extract_segments(
    output: dict | list,
    *,
    normalizer: TextNormalizer = normalize_full_aya_ar,
) -> list[dict]:
    """Return fullAyaAlignment-style segment entries from WhisperX output."""
    segments: list[dict] = []

    for segment in _iter_whisperx_segments(output):
        raw_text = segment.get("text") or segment.get("segment") or ""
        start = segment.get("start")
        end = segment.get("end")
        norm = normalizer(raw_text)
        if norm and start is not None and end is not None:
            segments.append(
                {
                    "text_raw": raw_text.strip(),
                    "text_norm": norm,
                    "start": start,
                    "end": end,
                }
            )

    return segments

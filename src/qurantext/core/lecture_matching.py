from __future__ import annotations

from collections import defaultdict

from qurantext.config.settings import (
    DEFAULT_LECTURE_CANDIDATE_LIMIT,
    DEFAULT_LECTURE_MAX_SPAN,
    DEFAULT_LECTURE_MAX_WINDOW_WORDS,
    DEFAULT_LECTURE_MIN_MATCHED_WORDS,
    DEFAULT_LECTURE_MIN_WINDOW_WORDS,
    DEFAULT_LECTURE_SHORT_PHRASE_THRESHOLD,
    DEFAULT_LECTURE_SHORT_PHRASE_WORD_LIMIT,
    DEFAULT_LECTURE_THRESHOLD,
    DEFAULT_LECTURE_WINDOW_STEP,
)
from qurantext.core.arabic import ayah_text_with_marker, partial_ratio, word_recall


def build_ayah_spans(
    ayat: list[dict],
    max_span: int = DEFAULT_LECTURE_MAX_SPAN + 1,
) -> list[dict]:
    """Build searchable ayah spans within the same surah."""
    spans: list[dict] = []

    for index, start_ayah in enumerate(ayat):
        parts_raw: list[str] = []
        parts_norm: list[str] = []

        for offset in range(index, min(index + max_span, len(ayat))):
            current = ayat[offset]
            if current["surah_num"] != start_ayah["surah_num"]:
                break

            parts_raw.append(current["text_raw"])
            parts_norm.append(current["text_norm"])

            text_norm = " ".join(parts_norm)
            norm_words = tuple(text_norm.split())

            spans.append(
                {
                    "surah_num": start_ayah["surah_num"],
                    "surah_name": start_ayah["surah_name"],
                    "from_ayah": start_ayah["ayah_num"],
                    "to_ayah": current["ayah_num"],
                    "from_index": start_ayah["_index"],
                    "to_index": current["_index"],
                    "text_raw": "\n".join(parts_raw),
                    "text_norm": text_norm,
                    "num_ayat": current["ayah_num"] - start_ayah["ayah_num"] + 1,
                    "num_words": len(norm_words),
                    "_norm_words": norm_words,
                    "_word_set": frozenset(norm_words),
                }
            )

    return spans


def build_span_word_index(spans: list[dict]) -> dict[str, list[int]]:
    """Map each normalized word to the span indices that contain it."""
    index: dict[str, list[int]] = defaultdict(list)

    for span_idx, span in enumerate(spans):
        for word in span["_word_set"]:
            index[word].append(span_idx)

    return dict(index)


def iter_word_windows(
    words: list[dict],
    min_words: int = DEFAULT_LECTURE_MIN_WINDOW_WORDS,
    max_words: int = DEFAULT_LECTURE_MAX_WINDOW_WORDS,
    step: int = DEFAULT_LECTURE_WINDOW_STEP,
):
    """Yield overlapping transcript windows from the WhisperX word list."""
    if not words:
        return

    for start in range(0, len(words), step):
        for size in range(min_words, max_words + 1):
            end = start + size
            if end > len(words):
                break

            window_words = words[start:end]
            text_norm = " ".join(word["word_norm"] for word in window_words).strip()
            if not text_norm:
                continue

            text_raw = " ".join(word["word_raw"] for word in window_words).strip()

            yield {
                "start_word": start,
                "end_word": end - 1,
                "start_time": window_words[0]["start"],
                "end_time": window_words[-1]["end"],
                "text_norm": text_norm,
                "text_raw": text_raw,
                "word_count": size,
            }


def score_span_for_lecture(span_norm: str, window_norm: str) -> float:
    """Score a Qur'an span against a transcript window."""
    span_words = span_norm.split()
    window_words = window_norm.split()

    if not span_words or not window_words:
        return 0.0

    span_word_set = set(span_words)
    window_word_set = set(window_words)

    recall = word_recall(span_words, window_word_set)
    matched_window_words = sum(1 for word in window_words if word in span_word_set)
    precision = matched_window_words / len(window_words)
    partial = max(partial_ratio(span_norm, window_norm), partial_ratio(window_norm, span_norm))

    score = (0.45 * partial) + (0.40 * recall) + (0.15 * precision)
    return round(score, 4)


def candidate_spans_by_word_overlap(
    spans: list[dict],
    window_norm: str,
    top_n: int = DEFAULT_LECTURE_CANDIDATE_LIMIT,
    min_overlap_words: int = DEFAULT_LECTURE_MIN_MATCHED_WORDS - 1,
    *,
    word_index: dict[str, list[int]] | None = None,
) -> list[dict]:
    """Fast candidate selection before fuzzy scoring."""
    window_words = set(window_norm.split())
    if not window_words:
        return []

    overlap_counts: dict[int, int] = defaultdict(int)

    if word_index is None:
        for span_idx, span in enumerate(spans):
            overlap = sum(1 for word in span["_norm_words"] if word in window_words)
            if overlap >= min_overlap_words:
                overlap_counts[span_idx] = overlap
    else:
        for word in window_words:
            for span_idx in word_index.get(word, []):
                overlap_counts[span_idx] += 1

    ranked: list[tuple[int, float, int, dict]] = []
    for span_idx, overlap in overlap_counts.items():
        if overlap < min_overlap_words:
            continue
        span = spans[span_idx]
        recall = overlap / max(1, len(span["_norm_words"]))
        ranked.append((overlap, recall, span["num_words"], span))

    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [span for _, _, _, span in ranked[:top_n]]


def merge_quran_matches(
    matches: list[dict],
    *,
    max_time_gap: float = 4.0,
    max_merged_ayat: int | None = None,
    min_score: float = DEFAULT_LECTURE_THRESHOLD,
) -> list[dict]:
    """Merge duplicate and overlapping ayah detections."""
    if not matches:
        return []

    ordered = sorted(
        matches,
        key=lambda match: (
            match["start_time"],
            match["surah_num"],
            match["from_index"],
            match["to_index"],
            -match["confidence"],
        ),
    )

    merged: list[dict] = []
    for match in ordered:
        if not merged:
            merged.append(dict(match))
            continue

        last = merged[-1]
        same_surah = match["surah_num"] == last["surah_num"]
        overlapping_ayat = (
            match["from_index"] <= last["to_index"] + 1
            and match["to_index"] >= last["from_index"] - 1
        )
        nearby_time = (match["start_time"] - last["end_time"]) <= max_time_gap

        if same_surah and overlapping_ayat and nearby_time:
            merged_from = min(last["from_index"], match["from_index"])
            merged_to = max(last["to_index"], match["to_index"])
            if max_merged_ayat is not None and merged_to - merged_from + 1 > max_merged_ayat:
                merged.append(dict(match))
                continue

            if match["from_index"] < last["from_index"]:
                last["from_index"] = match["from_index"]
                last["from_ayah"] = match["from_ayah"]

            if match["to_index"] > last["to_index"]:
                last["to_index"] = match["to_index"]
                last["to_ayah"] = match["to_ayah"]

            last["start_time"] = min(last["start_time"], match["start_time"])
            # Only extend end_time for merging matches that meet the confidence bar;
            # low-confidence detections should not silently stretch the displayed span.
            if match["confidence"] >= min_score:
                last["end_time"] = max(last["end_time"], match["end_time"])
            last["start_word"] = min(last["start_word"], match["start_word"])
            last["end_word"] = max(last["end_word"], match["end_word"])
            last["confidence"] = max(last["confidence"], match["confidence"])

            if len(match["detected_text"]) > len(last["detected_text"]):
                last["detected_text"] = match["detected_text"]
        else:
            merged.append(dict(match))

    merged.sort(key=lambda match: match["start_time"])
    return merged


def hydrate_merged_matches(
    merged: list[dict],
    ayat: list[dict],
    words: list[dict],
) -> list[dict]:
    """Rebuild final Quran text and transcript fragment after merging."""
    final: list[dict] = []
    ayat_by_index = {ayah["_index"]: ayah for ayah in ayat}

    for match in merged:
        selected_ayat = [
            ayat_by_index[index]
            for index in range(match["from_index"], match["to_index"] + 1)
            if index in ayat_by_index
        ]
        if not selected_ayat:
            continue

        detected_words = words[match["start_word"] : match["end_word"] + 1]
        detected_text = " ".join(word["word_raw"] for word in detected_words).strip()
        full_text = "\n".join(
            ayah_text_with_marker(ayah["text_raw"], ayah["ayah_num"]) for ayah in selected_ayat
        )

        final.append(
            {
                "surah_num": match["surah_num"],
                "surah_name": match["surah_name"],
                "from_ayah": selected_ayat[0]["ayah_num"],
                "to_ayah": selected_ayat[-1]["ayah_num"],
                "detected_text": detected_text,
                "text": full_text,
                "full_text": full_text,
                "confidence": round(match["confidence"], 4),
                "start_time": round(match["start_time"], 2),
                "end_time": round(match["end_time"], 2),
            }
        )

    return final


def detect_quran_mentions_in_lecture(
    ayat: list[dict],
    words: list[dict],
    *,
    max_span: int = DEFAULT_LECTURE_MAX_SPAN,
    min_window_words: int = DEFAULT_LECTURE_MIN_WINDOW_WORDS,
    max_window_words: int = DEFAULT_LECTURE_MAX_WINDOW_WORDS,
    window_step: int = DEFAULT_LECTURE_WINDOW_STEP,
    min_score: float = DEFAULT_LECTURE_THRESHOLD,
    min_matched_words: int = DEFAULT_LECTURE_MIN_MATCHED_WORDS,
    candidate_limit: int = DEFAULT_LECTURE_CANDIDATE_LIMIT,
    max_merged_ayat: int | None = None,
    short_phrase_threshold: float = DEFAULT_LECTURE_SHORT_PHRASE_THRESHOLD,
    short_phrase_word_limit: int = DEFAULT_LECTURE_SHORT_PHRASE_WORD_LIMIT,
) -> list[dict]:
    """Detect Qur'an ayat mentioned inside lecture-style audio."""
    if not ayat or not words:
        return []

    spans = build_ayah_spans(ayat, max_span=max_span)
    word_index = build_span_word_index(spans)
    matches: list[dict] = []

    for window in iter_word_windows(
        words,
        min_words=min_window_words,
        max_words=max_window_words,
        step=window_step,
    ):
        window_text_norm = str(window["text_norm"])
        candidates = candidate_spans_by_word_overlap(
            spans,
            window_text_norm,
            top_n=candidate_limit,
            min_overlap_words=min_matched_words,
            word_index=word_index,
        )

        if not candidates:
            continue

        window_words = window_text_norm.split()

        for span in candidates:
            span_text_norm = str(span["text_norm"])
            score = score_span_for_lecture(span_text_norm, window_text_norm)
            if score < min_score:
                continue

            # Short-phrase guard: require higher confidence for spans with few words
            # to avoid false positives from common short phrases.
            if span["num_words"] < short_phrase_word_limit and score < short_phrase_threshold:
                continue

            span_words = span["_word_set"]
            matched_words = sum(1 for word in window_words if word in span_words)
            if matched_words < min_matched_words:
                continue

            matches.append(
                {
                    "surah_num": span["surah_num"],
                    "surah_name": span["surah_name"],
                    "from_ayah": span["from_ayah"],
                    "to_ayah": span["to_ayah"],
                    "from_index": span["from_index"],
                    "to_index": span["to_index"],
                    "detected_text": window["text_raw"],
                    "confidence": score,
                    "start_time": window["start_time"],
                    "end_time": window["end_time"],
                    "start_word": window["start_word"],
                    "end_word": window["end_word"],
                }
            )

    merged = merge_quran_matches(matches, max_merged_ayat=max_merged_ayat, min_score=min_score)
    return hydrate_merged_matches(merged, ayat, words)

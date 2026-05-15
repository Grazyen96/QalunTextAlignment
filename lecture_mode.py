from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher

# Arabic-Indic digit map (U+0660–U+0669)
_TO_ARABIC_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def _int_to_arabic_indic(n: int) -> str:
    """Convert an integer to its Arabic-Indic digit string (e.g. 25 → '٢٥')."""
    return str(n).translate(_TO_ARABIC_INDIC)


def _ayah_text_with_marker(text_raw: str, ayah_num: int) -> str:
    """Append the ayah number wrapped in ornamental parentheses ﴿٧﴾."""
    return f"{text_raw} \ufd3e{_int_to_arabic_indic(ayah_num)}\ufd3f"


def build_ayah_spans(
    ayat: list[dict],
    max_span: int = 6,
) -> list[dict]:
    """
    Build searchable ayah spans within the same surah.

    Each span may cover one or more consecutive ayat up to ``max_span``.
    """
    spans: list[dict] = []

    for i, start_ayah in enumerate(ayat):
        parts_raw: list[str] = []
        parts_norm: list[str] = []

        for j in range(i, min(i + max_span, len(ayat))):
            current = ayat[j]
            if current["surah_num"] != start_ayah["surah_num"]:
                break

            parts_raw.append(current["text_raw"])
            parts_norm.append(current["text_norm"])

            text_norm = " ".join(parts_norm)
            norm_words = tuple(text_norm.split())

            spans.append({
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
            })

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
    min_words: int = 5,
    max_words: int = 35,
    step: int = 3,
):
    """Yield overlapping transcript windows from the WhisperX word list."""
    n = len(words)
    if n == 0:
        return

    for start in range(0, n, step):
        for size in range(min_words, max_words + 1):
            end = start + size
            if end > n:
                break

            window_words = words[start:end]
            text_norm = " ".join(w["word_norm"] for w in window_words).strip()
            if not text_norm:
                continue

            text_raw = " ".join(w["word_raw"] for w in window_words).strip()

            yield {
                "start_word": start,
                "end_word": end - 1,
                "start_time": window_words[0]["start"],
                "end_time": window_words[-1]["end"],
                "text_norm": text_norm,
                "text_raw": text_raw,
                "word_count": size,
            }


def _partial_ratio(needle: str, haystack: str) -> float:
    """Best SequenceMatcher ratio of ``needle`` against a haystack sub-window."""
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
        if best > 0.97:
            break
    return best


def _word_recall(ayah_words: list[str] | tuple[str, ...], transcript_words: set[str]) -> float:
    """Fraction of ayah words found anywhere in the transcript window."""
    if not ayah_words:
        return 0.0
    return sum(1 for w in ayah_words if w in transcript_words) / len(ayah_words)


def score_span_for_lecture(span_norm: str, window_norm: str) -> float:
    """
    Score a Qur'an span against a transcript window.

    Uses a mix of partial matching, ayah-word recall, and transcript precision.
    The partial-ratio term is computed symmetrically so partial-ayah quotations
    can still match the full ayah/span.
    """
    span_words = span_norm.split()
    window_words = window_norm.split()

    if not span_words or not window_words:
        return 0.0

    span_word_set = set(span_words)
    window_word_set = set(window_words)

    recall = _word_recall(span_words, window_word_set)
    matched_window_words = sum(1 for w in window_words if w in span_word_set)
    precision = matched_window_words / len(window_words)
    partial = max(
        _partial_ratio(span_norm, window_norm),
        _partial_ratio(window_norm, span_norm),
    )

    score = (0.45 * partial) + (0.40 * recall) + (0.15 * precision)
    return round(score, 4)


def candidate_spans_by_word_overlap(
    spans: list[dict],
    window_norm: str,
    top_n: int = 25,
    min_overlap_words: int = 3,
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
            overlap = sum(1 for w in span["_norm_words"] if w in window_words)
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
) -> list[dict]:
    """Merge duplicate and overlapping ayah detections."""
    if not matches:
        return []

    ordered = sorted(
        matches,
        key=lambda m: (
            m["start_time"],
            m["surah_num"],
            m["from_index"],
            m["to_index"],
            -m["confidence"],
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
            if (
                max_merged_ayat is not None
                and merged_to - merged_from + 1 > max_merged_ayat
            ):
                merged.append(dict(match))
                continue

            if match["from_index"] < last["from_index"]:
                last["from_index"] = match["from_index"]
                last["from_ayah"] = match["from_ayah"]

            if match["to_index"] > last["to_index"]:
                last["to_index"] = match["to_index"]
                last["to_ayah"] = match["to_ayah"]

            last["start_time"] = min(last["start_time"], match["start_time"])
            last["end_time"] = max(last["end_time"], match["end_time"])
            last["start_word"] = min(last["start_word"], match["start_word"])
            last["end_word"] = max(last["end_word"], match["end_word"])
            last["confidence"] = max(last["confidence"], match["confidence"])

            if len(match["detected_text"]) > len(last["detected_text"]):
                last["detected_text"] = match["detected_text"]
        else:
            merged.append(dict(match))

    merged.sort(key=lambda m: m["start_time"])
    return merged


def hydrate_merged_matches(
    merged: list[dict],
    ayat: list[dict],
    words: list[dict],
) -> list[dict]:
    """Rebuild final Quran text and transcript fragment after merging."""
    final: list[dict] = []
    ayat_by_index = {a["_index"]: a for a in ayat}

    for match in merged:
        selected_ayat = [
            ayat_by_index[i]
            for i in range(match["from_index"], match["to_index"] + 1)
            if i in ayat_by_index
        ]
        if not selected_ayat:
            continue

        detected_words = words[match["start_word"]:match["end_word"] + 1]
        detected_text = " ".join(w["word_raw"] for w in detected_words).strip()
        full_text = "\n".join(
            _ayah_text_with_marker(a["text_raw"], a["ayah_num"])
            for a in selected_ayat
        )

        final.append({
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
        })

    return final


def detect_quran_mentions_in_lecture(
    ayat: list[dict],
    words: list[dict],
    *,
    max_span: int = 5,
    min_window_words: int = 5,
    max_window_words: int = 35,
    window_step: int = 3,
    min_score: float = 0.78,
    min_matched_words: int = 4,
    candidate_limit: int = 25,
    max_merged_ayat: int | None = None,
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

            span_words = span["_word_set"]
            matched_words = sum(1 for w in window_words if w in span_words)
            if matched_words < min_matched_words:
                continue

            matches.append({
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
            })

    merged = merge_quran_matches(matches, max_merged_ayat=max_merged_ayat)
    return hydrate_merged_matches(merged, ayat, words)

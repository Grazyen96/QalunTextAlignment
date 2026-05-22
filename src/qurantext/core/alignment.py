from __future__ import annotations

from qurantext.core.arabic import similarity


def _find_best_match(
    needle_norm: str,
    canon_original: list[str],
    canon_norm: list[str],
    min_score: float,
) -> tuple[str | None, float]:
    """Search canonical normalized strings for the best fuzzy match."""
    best_word = None
    best_score = 0.0

    for original, normalized in zip(canon_original, canon_norm, strict=False):
        score = similarity(needle_norm, normalized)
        if score > best_score:
            best_score = score
            best_word = original

    if best_score >= min_score:
        return best_word, best_score
    return None, best_score


def _align_entries(
    entries: list[dict],
    canon_original: list[str],
    canon_norm: list[str],
    min_score: float,
    *,
    needle_key: str,
    raw_key: str,
    display_key: str,
    manual_index_key: str,
    manual_raw_key: str,
) -> tuple[list[dict], list[dict]]:
    """Align timestamped transcript entries against canonical normalized strings."""
    result: list[dict] = []
    manual_check: list[dict] = []

    for index, entry in enumerate(entries):
        canonical, score = _find_best_match(
            entry[needle_key],
            canon_original,
            canon_norm,
            min_score,
        )

        if canonical is not None:
            display_text = canonical
        else:
            display_text = entry[raw_key]
            manual_check.append(
                {
                    manual_index_key: index,
                    manual_raw_key: entry[raw_key],
                    "start": entry["start"],
                    "end": entry["end"],
                    "best_score": round(score, 4),
                }
            )

        result.append(
            {
                display_key: display_text,
                "start": entry["start"],
                "end": entry["end"],
            }
        )

    return result, manual_check


def find_best_canonical_word(
    word_norm: str,
    canon_original: list[str],
    canon_norm: list[str],
    min_score: float,
) -> tuple[str | None, float]:
    """Search canonical words for the best fuzzy match."""
    return _find_best_match(word_norm, canon_original, canon_norm, min_score)


def align_words(
    words: list[dict],
    canon_original: list[str],
    canon_norm: list[str],
    min_score: float,
) -> tuple[list[dict], list[dict]]:
    """Align WhisperX word entries against canonical Quran words."""
    return _align_entries(
        words,
        canon_original,
        canon_norm,
        min_score,
        needle_key="word_norm",
        raw_key="word_raw",
        display_key="word",
        manual_index_key="word_index",
        manual_raw_key="whisperx_word",
    )


def find_best_canonical_line(
    segment_norm: str,
    lines_original: list[str],
    lines_norm: list[str],
    min_score: float,
) -> tuple[str | None, float]:
    """Search canonical lines for the best fuzzy match."""
    return _find_best_match(segment_norm, lines_original, lines_norm, min_score)


def align_segments(
    segments: list[dict],
    lines_original: list[str],
    lines_norm: list[str],
    min_score: float,
) -> tuple[list[dict], list[dict]]:
    """Align WhisperX segment entries against canonical Quran lines."""
    return _align_entries(
        segments,
        lines_original,
        lines_norm,
        min_score,
        needle_key="text_norm",
        raw_key="text_raw",
        display_key="text",
        manual_index_key="segment_index",
        manual_raw_key="whisperx_text",
    )


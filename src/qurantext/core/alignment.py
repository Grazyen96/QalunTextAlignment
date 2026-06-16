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


def _interpolate_missing_timings(
    timings: list[dict], transcript_words: list[dict]
) -> None:
    """Fill ``None`` timings in place by interpolating across timed neighbours.

    A canonical word with no aligned transcript word (a deletion in the
    transcript) gets an evenly-spaced slice of the silent gap between the
    surrounding timed words, so the highlight never stalls or jumps.
    """
    n = len(timings)
    first_start = float(transcript_words[0]["start"])
    last_end = float(transcript_words[-1]["end"])

    i = 0
    while i < n:
        if timings[i]["start"] is not None:
            i += 1
            continue
        # Locate the contiguous run [i, k) of unfilled canonical words.
        k = i
        while k < n and timings[k]["start"] is None:
            k += 1
        prev_end = float(timings[i - 1]["end"]) if i > 0 else first_start
        next_start = float(timings[k]["start"]) if k < n else last_end
        span = max(next_start - prev_end, 0.0)
        count = k - i
        step = span / (count + 1)
        for off in range(count):
            timings[i + off] = {
                "start": prev_end + step * off,
                "end": prev_end + step * (off + 1),
            }
        i = k


def align_canonical_word_timings(
    transcript_words: list[dict],
    canonical_norms: list[str],
    *,
    gap_penalty: float = 0.4,
) -> list[dict]:
    """Map timed transcript words onto canonical words, one timing per canonical word.

    Returns a list the same length as *canonical_norms* where the Nth entry is the
    ``{"start", "end"}`` span recited for the Nth canonical word. A monotonic
    Needleman–Wunsch alignment over fuzzy word similarity keeps the mapping
    order-preserving even when the reciter repeats a word, the transcriber splits
    or merges tokens, or a leading preamble pads the transcript — the cases that
    make a naive positional (Nth transcript ≈ Nth canonical) mapping drift ahead
    and behind. Canonical words with no aligned transcript word are interpolated.

    *transcript_words* must be time-ordered dicts carrying ``word_norm``,
    ``start`` and ``end``. When empty, every timing is ``None`` (no highlight).
    """
    m = len(transcript_words)
    n = len(canonical_norms)
    if n == 0:
        return []
    if m == 0:
        return [{"start": None, "end": None} for _ in range(n)]

    t_norms = [str(w.get("word_norm") or "") for w in transcript_words]

    # H[i][j]: best alignment score over the first i transcript and j canonical
    # words. A diagonal step aligns a pair (scored by similarity); a vertical or
    # horizontal step leaves a transcript or canonical word unaligned (penalised).
    H = [[0.0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        H[i][0] = -gap_penalty * i
    for j in range(1, n + 1):
        H[0][j] = -gap_penalty * j
    for i in range(1, m + 1):
        row, prev_row = H[i], H[i - 1]
        ti = t_norms[i - 1]
        for j in range(1, n + 1):
            diag = prev_row[j - 1] + similarity(ti, canonical_norms[j - 1])
            up = prev_row[j] - gap_penalty
            left = row[j - 1] - gap_penalty
            row[j] = max(diag, up, left)

    # Backtrack, collecting the transcript words aligned to each canonical word.
    aligned: list[list[int]] = [[] for _ in range(n)]
    i, j = m, n
    while i > 0 and j > 0:
        diag = H[i - 1][j - 1] + similarity(t_norms[i - 1], canonical_norms[j - 1])
        if H[i][j] == diag:
            aligned[j - 1].append(i - 1)
            i -= 1
            j -= 1
        elif H[i][j] == H[i - 1][j] - gap_penalty:
            i -= 1
        else:
            j -= 1

    # Fold unaligned transcript words into the canonical word they duplicate, so a
    # repeated utterance keeps the highlight on that word instead of stalling on
    # the previous one. Words dissimilar to their neighbours (a leading preamble,
    # filler) stay unattached and become insertions.
    fold_threshold = max(gap_penalty, 0.5)
    pairs = sorted((min(ks), c) for c, ks in enumerate(aligned) if ks)
    for u in range(m):
        if any(u in ks for ks in aligned):
            continue
        prev_c = next((c for ti, c in reversed(pairs) if ti < u), None)
        next_c = next((c for ti, c in pairs if ti > u), None)
        best_c, best_score = None, fold_threshold
        for cand in (prev_c, next_c):
            if cand is None:
                continue
            score = similarity(t_norms[u], canonical_norms[cand])
            if score >= best_score:
                best_c, best_score = cand, score
        if best_c is not None:
            aligned[best_c].append(u)

    timings: list[dict] = [{"start": None, "end": None} for _ in range(n)]
    for c_idx, t_indices in enumerate(aligned):
        if t_indices:
            timings[c_idx] = {
                "start": min(float(transcript_words[k]["start"]) for k in t_indices),
                "end": max(float(transcript_words[k]["end"]) for k in t_indices),
            }

    _interpolate_missing_timings(timings, transcript_words)
    return timings

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

# When two ayat compete for the same time slice and the top one would switch
# surah, keep the current surah if its best candidate is within this confidence
# margin — disambiguates near-identical ayat across surahs (e.g. Furqan 9 ≈ Isra
# 48) toward the surah the lecture is actually on.
SURAH_CONTINUITY_MARGIN = 0.1


def spans_starting_at(ayat: list[dict], index: int, max_span: int) -> list[dict]:
    """Build the same-surah spans that start at ``ayat[index]``.

    A span is ``ayat[index]`` concatenated with up to ``max_span - 1`` following
    ayat, stopping at a surah boundary. This is the single source of truth for a
    span's shape — both the in-memory precompute (:func:`build_ayah_spans`) and
    the on-demand DB candidate path build spans through here, so they score
    identically.
    """
    start_ayah = ayat[index]
    spans: list[dict] = []
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


def build_ayah_spans(
    ayat: list[dict],
    max_span: int = DEFAULT_LECTURE_MAX_SPAN + 1,
) -> list[dict]:
    """Build searchable ayah spans within the same surah."""
    spans: list[dict] = []
    for index in range(len(ayat)):
        spans.extend(spans_starting_at(ayat, index, max_span))
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
    short_max_words: int = 7,
):
    """Yield overlapping transcript windows from the WhisperX word list.

    Windows up to *short_max_words* in size always use step=1 so that short
    Quranic phrases starting at any word position are found.  Larger windows
    use the configured *step* for speed.  The two size ranges are
    non-overlapping, so no window is yielded twice.
    """
    if not words:
        return

    # Build (start_step, size_min, size_max) for each non-overlapping pass.
    passes: list[tuple[int, int, int]] = []
    short_cap = min(max_words, short_max_words)
    long_min = max(min_words, short_max_words + 1)
    if min_words <= short_cap:
        passes.append((1, min_words, short_cap))
    if long_min <= max_words:
        passes.append((step, long_min, max_words))

    for pass_step, size_min, size_max in passes:
        for start in range(0, len(words), pass_step):
            for size in range(size_min, size_max + 1):
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


def db_candidate_spans(
    conn,
    ayat: list[dict],
    ayat_index: dict[tuple[int, int], int],
    window_norm: str,
    *,
    max_span: int,
    min_overlap_words: int,
    candidate_limit: int,
) -> list[dict]:
    """Select candidate spans for a window using the persisted store.

    Replaces the in-memory ``build_span_word_index`` rebuild: the inverted
    word→ayah lookup is the persisted ``words(text_norm)`` index queried here.
    Candidate ayat are ranked by how many distinct window words they contain,
    then expanded into spans on demand via :func:`spans_starting_at` — so no
    full span list or word index is precomputed per run.

    *ayat_index* maps ``(surah_num, ayah_num)`` to the position in *ayat*; only
    candidates present there are kept, which naturally scopes results to a
    recitation subset or ``--surah`` filter even though the index is full-Quran.
    """
    window_words = list({w for w in window_norm.split() if w})
    if not window_words:
        return []

    placeholders = ",".join("?" * len(window_words))
    rows = conn.execute(
        f"SELECT surah_num, ayah_num, COUNT(DISTINCT text_norm) AS overlap"  # noqa: S608
        f" FROM words WHERE text_norm IN ({placeholders})"
        f" GROUP BY surah_num, ayah_num HAVING overlap >= ?"
        f" ORDER BY overlap DESC, surah_num, ayah_num LIMIT ?",
        (*window_words, min_overlap_words, candidate_limit),
    ).fetchall()

    # Cap to the same candidate budget the in-memory path uses (candidate_limit
    # spans), taking spans from the highest-overlap ayat first so scoring cost
    # per window stays comparable rather than candidate_limit * max_span.
    spans: list[dict] = []
    for surah_num, ayah_num, _overlap in rows:
        index = ayat_index.get((surah_num, ayah_num))
        if index is not None:
            spans.extend(spans_starting_at(ayat, index, max_span))
            if len(spans) >= candidate_limit:
                break
    return spans[:candidate_limit]


def db_ngram_n(conn) -> int:
    """The n-gram length the store's citation index was built with (default 3)."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'citation_ngram_n'").fetchone()
    return int(row[0]) if row else 3


def db_candidate_spans_ngram(
    conn,
    ayat: list[dict],
    ayat_index: dict[tuple[int, int], int],
    window_norm: str,
    *,
    n: int,
    max_span: int,
    candidate_limit: int,
    min_gram_hits: int = 1,
) -> list[dict]:
    """Phrase-precise candidate selection via the persisted citation n-gram index.

    This is the speed lever: detection is fuzzy-scoring-bound, so the win is
    scoring far fewer (window, candidate) pairs. A window's n-grams are looked up
    in ``citation_ngrams``; only ayat that share an exact n-word phrase become
    candidates. Crucially, a window with **no** n-gram hit returns ``[]`` and is
    skipped entirely — in a tafseer most windows are the teacher speaking, not a
    quote, so this prunes the bulk of the work before any ``partial_ratio`` call.

    Candidates are ranked by distinct n-gram hits and expanded into spans on
    demand, scoped to *ayat_index* exactly as :func:`db_candidate_spans`.
    """
    tokens = window_norm.split()
    if len(tokens) < n:
        return []
    grams = list({" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)})
    if not grams:
        return []

    placeholders = ",".join("?" * len(grams))
    rows = conn.execute(
        f"SELECT surah_num, ayah_num, COUNT(DISTINCT gram) AS hits"  # noqa: S608
        f" FROM citation_ngrams WHERE gram IN ({placeholders})"
        f" GROUP BY surah_num, ayah_num HAVING hits >= ?"
        f" ORDER BY hits DESC, surah_num, ayah_num LIMIT ?",
        (*grams, min_gram_hits, candidate_limit),
    ).fetchall()

    spans: list[dict] = []
    for surah_num, ayah_num, _hits in rows:
        index = ayat_index.get((surah_num, ayah_num))
        if index is not None:
            spans.extend(spans_starting_at(ayat, index, max_span))
            if len(spans) >= candidate_limit:
                break
    return spans[:candidate_limit]


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

            # Only let confident detections extend the span FORWARD (more ayat, a
            # later end). A low-confidence overlap still merges for de-duplication
            # but must not stretch the displayed range — guard to_index/to_ayah,
            # end_word and end_time together, since hydrate_merged_matches re-derives
            # the final end_time from end_word (so guarding end_time alone is moot).
            if match["confidence"] >= min_score:
                if match["to_index"] > last["to_index"]:
                    last["to_index"] = match["to_index"]
                    last["to_ayah"] = match["to_ayah"]
                last["end_time"] = max(last["end_time"], match["end_time"])
                last["end_word"] = max(last["end_word"], match["end_word"])

            last["start_time"] = min(last["start_time"], match["start_time"])
            last["start_word"] = min(last["start_word"], match["start_word"])
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

        # Anchor timing to actual word-level timestamps instead of the window
        # boundaries, which may span multiple ayat inside one WhisperX segment.
        if detected_words:
            start_time = round(detected_words[0]["start"], 2)
            end_time = round(detected_words[-1]["end"], 2)
        else:
            start_time = round(match["start_time"], 2)
            end_time = round(match["end_time"], 2)

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
                "start_time": start_time,
                "end_time": end_time,
            }
        )

    return final


def _merge_same_ayah_intervals(matches: list[dict]) -> list[dict]:
    """Union overlapping/touching detections of the *same* ayah into one span.

    Single-ayah lecture detection emits many overlapping fragments for one quote
    (sliding windows, boundary windows). Collapsing them per ayah first gives one
    confidence and one time span per ayah occurrence, so the timeline sweep below
    has a stable winner inside any cross-ayah overlap.
    """
    by_ayah: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for match in matches:
        by_ayah[(match["surah_num"], match["from_ayah"])].append(match)

    consolidated: list[dict] = []
    for group in by_ayah.values():
        group.sort(key=lambda m: m["start_time"])
        current = dict(group[0])
        for match in group[1:]:
            if match["start_time"] <= current["end_time"]:  # overlap or touch
                current["end_time"] = max(current["end_time"], match["end_time"])
                current["confidence"] = max(current["confidence"], match["confidence"])
                if len(str(match.get("detected_text", ""))) > len(
                    str(current.get("detected_text", ""))
                ):
                    current["detected_text"] = match["detected_text"]
            else:
                consolidated.append(current)
                current = dict(match)
        consolidated.append(current)
    return consolidated


def select_lecture_timeline(matches: list[dict], *, min_card_seconds: float = 1.5) -> list[dict]:
    """Collapse overlapping single-ayah detections into a one-ayah-at-a-time timeline.

    Lecture detection (with single-ayah spans) produces many overlapping and
    competing matches — adjacent ayat whose wide transcript windows overlap, and
    near-duplicate ayat across surahs that both match the same words. This builds
    a clean, non-overlapping timeline so the video shows exactly one ayah at a
    time:

    1. Union same-ayah fragments (:func:`_merge_same_ayah_intervals`).
    2. Sweep the time axis between consolidated boundaries; in each slice the
       highest-confidence ayah covering it wins (ties broken by longer span then
       earlier start, for determinism).
    3. Merge adjacent slices of the same ayah, then absorb slivers shorter than
       *min_card_seconds* into the preceding card so a brief confidence cross
       does not flicker the displayed ayah.
    """
    timed = [m for m in matches if m["end_time"] > m["start_time"]]
    if not timed:
        return []

    consolidated = _merge_same_ayah_intervals(timed)
    breakpoints = sorted(
        {m["start_time"] for m in consolidated} | {m["end_time"] for m in consolidated}
    )

    def _same(a: dict, b: dict) -> bool:
        return a["surah_num"] == b["surah_num"] and a["from_ayah"] == b["from_ayah"]

    def _rank(m: dict) -> tuple:
        return (m["confidence"], m["end_time"] - m["start_time"], -m["start_time"])

    slices: list[list] = []  # [start, end, winning_match]
    for start, end in zip(breakpoints, breakpoints[1:], strict=False):
        if end <= start:
            continue
        mid = (start + end) / 2.0
        covering = [m for m in consolidated if m["start_time"] <= mid < m["end_time"]]
        if not covering:
            continue
        winner = max(covering, key=_rank)
        if slices and _same(slices[-1][2], winner) and abs(slices[-1][1] - start) < 1e-6:
            slices[-1][1] = end
        else:
            slices.append([start, end, winner])

    if not slices:
        return []

    absorbed: list[list] = []
    for start, end, winner in slices:
        if absorbed and (end - start) < min_card_seconds:
            absorbed[-1][1] = end  # extend the previous card over the sliver
        else:
            absorbed.append([start, end, winner])

    # Absorption can leave two adjacent cards with the same ayah — re-merge.
    cards: list[list] = []
    for start, end, winner in absorbed:
        if cards and _same(cards[-1][2], winner):
            cards[-1][1] = end
        else:
            cards.append([start, end, winner])

    _apply_surah_continuity(cards, consolidated, _rank)

    timeline: list[dict] = []
    for start, end, winner in cards:
        card = dict(winner)
        card["start_time"] = round(start, 2)
        card["end_time"] = round(end, 2)
        timeline.append(card)
    return timeline


def _apply_surah_continuity(cards: list[list], consolidated: list[dict], rank) -> None:
    """Swap a card to a neighbouring surah's near-duplicate ayah, in place.

    A spoken quote can score marginally higher for a near-identical ayah in
    another surah (e.g. Furqan 9 ≈ Isra 48). When a card's surah differs from
    *both* its neighbours and a candidate in a neighbour's surah covers most of
    the card's time within *SURAH_CONTINUITY_MARGIN*, prefer that candidate — the
    contextually right ayah in a single-surah lecture. Picking winners by pure
    confidence first (then correcting here) avoids letting a short lead-in
    fragment of the wrong surah anchor the choice.
    """
    for i, card in enumerate(cards):
        start, end, winner = card
        neighbour_surahs = {
            cards[j][2]["surah_num"] for j in (i - 1, i + 1) if 0 <= j < len(cards)
        }
        if winner["surah_num"] in neighbour_surahs or not neighbour_surahs:
            continue

        duration = end - start
        if duration <= 0:
            continue
        candidates = [
            m
            for m in consolidated
            if m["surah_num"] in neighbour_surahs
            and winner["confidence"] - m["confidence"] <= SURAH_CONTINUITY_MARGIN
            and (min(end, m["end_time"]) - max(start, m["start_time"])) >= 0.5 * duration
        ]
        if candidates:
            card[2] = max(candidates, key=rank)


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
    conn=None,
    db_strategy: str = "word_overlap",
    db_candidate_min_overlap: int = 2,
) -> list[dict]:
    """Detect Qur'an ayat mentioned inside lecture-style audio.

    When *conn* (a connection to the persisted store) is given, candidate
    selection is served from the store instead of rebuilding the in-memory span
    word index each run; scoring is unchanged.

    *db_strategy* picks how candidates are drawn from the store:

    - ``"word_overlap"`` (default): candidate ayat by shared words via the
      ``words(text_norm)`` index. *db_candidate_min_overlap* is the per-ayah
      distinct-word overlap a candidate must clear (kept below *min_matched_words*
      so multi-ayah quotes, whose words split across ayat, still surface). This
      returns a superset of the in-memory candidates, so recall is preserved.
    - ``"ngram"``: phrase-precise candidates from the citation n-gram index, and
      — the real lever — windows with no n-gram hit are skipped before any fuzzy
      scoring (≈66% of windows in a speech-heavy tafseer, ≈4% in dense
      recitation). On a real 1284-word tafseer this ran ≈10× faster than
      word_overlap (251s vs 2502s) and reproduced its final (from,to) boundaries
      exactly (8/8). The ±1–2-ayah "jitter" seen earlier was a recitation-only
      artifact: continuous recitation chain-merges into long spans whose endpoints
      shift cosmetically (~99% region coverage retained). A post-merge
      recall-threshold boundary trim was tried to remove that and REJECTED — on
      tafseer it over-trimmed genuine ayat (8/8→5/8) because a spoken quote's
      per-ayah word recall is low (paraphrase + ASR error). So ngram is used
      as-is. (n=2 bigram was also tried: ~same coverage but only ≈1.1×, n=3 wins.)
    """
    if not ayat or not words:
        return []

    spans: list[dict] = []
    word_index: dict[str, list[int]] = {}
    ayat_index: dict[tuple[int, int], int] = {}
    ngram_n = 3
    if conn is None:
        spans = build_ayah_spans(ayat, max_span=max_span)
        word_index = build_span_word_index(spans)
    else:
        ayat_index = {(a["surah_num"], a["ayah_num"]): i for i, a in enumerate(ayat)}
        if db_strategy == "ngram":
            ngram_n = db_ngram_n(conn)

    matches: list[dict] = []

    for window in iter_word_windows(
        words,
        min_words=min_window_words,
        max_words=max_window_words,
        step=window_step,
    ):
        window_text_norm = str(window["text_norm"])
        if conn is None:
            candidates = candidate_spans_by_word_overlap(
                spans,
                window_text_norm,
                top_n=candidate_limit,
                min_overlap_words=min_matched_words,
                word_index=word_index,
            )
        elif db_strategy == "ngram":
            candidates = db_candidate_spans_ngram(
                conn,
                ayat,
                ayat_index,
                window_text_norm,
                n=ngram_n,
                max_span=max_span,
                candidate_limit=candidate_limit,
            )
        else:
            candidates = db_candidate_spans(
                conn,
                ayat,
                ayat_index,
                window_text_norm,
                max_span=max_span,
                min_overlap_words=db_candidate_min_overlap,
                candidate_limit=candidate_limit,
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

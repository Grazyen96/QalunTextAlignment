from __future__ import annotations

from difflib import SequenceMatcher

from qurantext.config.settings import (
    DEFAULT_RANGE_HEAD_WORDS,
    DEFAULT_RANGE_HIGH_CONF_POSITION,
    DEFAULT_RANGE_LOW_CONF,
    DEFAULT_RANGE_MIN_WORDS_GLOBAL,
    DEFAULT_RANGE_POSITION_THRESHOLD,
    DEFAULT_RANGE_POSITION_THRESHOLD_GLOBAL,
    DEFAULT_RANGE_SEARCH_RANGE,
    DEFAULT_RANGE_TAIL_WORDS,
)
from qurantext.core.arabic import ayah_text_with_marker, partial_ratio, word_recall

HEAD_WORDS = DEFAULT_RANGE_HEAD_WORDS
TAIL_WORDS = DEFAULT_RANGE_TAIL_WORDS
SEARCH_RANGE = DEFAULT_RANGE_SEARCH_RANGE
LOW_CONF = DEFAULT_RANGE_LOW_CONF

POSITION_THRESHOLD = DEFAULT_RANGE_POSITION_THRESHOLD
POSITION_THRESHOLD_GLOBAL = DEFAULT_RANGE_POSITION_THRESHOLD_GLOBAL
HIGH_CONF_POSITION = DEFAULT_RANGE_HIGH_CONF_POSITION
MIN_WORDS_GLOBAL = DEFAULT_RANGE_MIN_WORDS_GLOBAL


def _find_quran_start(words: list[dict]) -> int:
    """Return the index of the first WhisperX word after ta'awwudh/basmala."""
    taawwudh_vocab = frozenset(
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
    basmala_rest = frozenset({"الله", "الرحمن", "الرحيم"})

    norms = [word["word_norm"] for word in words[:20]]
    index = 0

    if index < len(norms) and norms[index] in ("اعوذ", "اعود"):
        end = min(index + 8, len(norms))
        while index < end and norms[index] in taawwudh_vocab:
            index += 1

    if index < len(norms) and norms[index] == "بسم":
        index += 1
        skipped = 0
        while skipped < 3 and index < len(norms) and norms[index] in basmala_rest:
            index += 1
            skipped += 1

    return min(index, 15)


def _find_match_position(
    needle: str,
    haystack: str,
    min_score: float = 0.40,
) -> tuple[int, float]:
    """Return the earliest qualifying position and best fuzzy score."""
    needle_len = len(needle)
    haystack_len = len(haystack)
    if needle_len == 0 or haystack_len == 0:
        return haystack_len, 0.0
    if needle_len >= haystack_len:
        score = SequenceMatcher(None, needle, haystack, autojunk=False).ratio()
        return (0 if score >= min_score else haystack_len), score

    best_score = 0.0
    earliest_pos = haystack_len
    step = max(1, needle_len // 5)

    for start in range(0, haystack_len - needle_len + 1, step):
        score = SequenceMatcher(
            None,
            needle,
            haystack[start : start + needle_len],
            autojunk=False,
        ).ratio()
        if score > best_score:
            best_score = score
        if score >= min_score and start < earliest_pos:
            earliest_pos = start

    return earliest_pos, best_score


def score_ayah(ayah_norm: str, transcript_str: str) -> float:
    """Return the combined fuzzy score for one ayah against the transcript."""
    partial = partial_ratio(ayah_norm, transcript_str)
    recall = word_recall(ayah_norm.split(), set(transcript_str.split()))
    return round((partial + recall) / 2.0, 4)


def _global_prefilter(
    ayat: list[dict],
    target_str: str,
    limit: int,
) -> list[dict]:
    target_words = set(target_str.split())
    if not target_words:
        return ayat[:limit]

    ranked = sorted(
        ayat,
        key=lambda ayah: word_recall(ayah["text_norm"].split(), target_words),
        reverse=True,
    )
    return ranked[:limit]


def _build_candidate_pool(
    ayat: list[dict],
    search_range: int,
    *,
    global_search: bool,
    window_str: str,
    min_words_global: int = MIN_WORDS_GLOBAL,
    min_index: int | None = None,
    latest: bool = False,
) -> list[dict]:
    if global_search:
        prefiltered = _global_prefilter(ayat, window_str, search_range * 4)
        candidates = [
            ayah for ayah in prefiltered if len(ayah["text_norm"].split()) >= min_words_global
        ]
        if not candidates:
            candidates = prefiltered
        if min_index is not None:
            filtered = [ayah for ayah in candidates if ayah["_index"] >= min_index]
            if filtered:
                candidates = filtered
        return candidates

    return ayat[-search_range:] if latest else ayat[:search_range]


def _score_candidates(
    candidates: list[dict],
    window_str: str,
    pos_thresh: float,
) -> list[tuple[int, float, dict]]:
    scored: list[tuple[int, float, dict]] = []
    for ayah in candidates:
        pos, _ = _find_match_position(ayah["text_norm"], window_str, pos_thresh)
        scored.append((pos, score_ayah(ayah["text_norm"], window_str), ayah))
    return scored


def _select_best_candidate(
    scored: list[tuple[int, float, dict]],
    window_len: int,
    *,
    latest: bool,
    global_search: bool,
    high_conf_position: float = HIGH_CONF_POSITION,
) -> tuple[dict, float]:
    if global_search:
        positioned = [
            (pos, score, ayah)
            for pos, score, ayah in scored
            if pos < window_len and score >= high_conf_position
        ]
    else:
        positioned = [(pos, score, ayah) for pos, score, ayah in scored if pos < window_len]

    if positioned:
        positioned.sort(key=lambda item: ((-item[0]) if latest else item[0], -item[1]))
        _, best_score, best_ayah = positioned[0]
    else:
        scored.sort(key=lambda item: -item[1])
        _, best_score, best_ayah = scored[0]

    return best_ayah, best_score


def detect_first_ayah(
    ayat: list[dict],
    words: list[dict],
    head_n: int,
    search_range: int,
    *,
    global_search: bool = False,
    position_threshold: float = POSITION_THRESHOLD,
    position_threshold_global: float = POSITION_THRESHOLD_GLOBAL,
    high_conf_position: float = HIGH_CONF_POSITION,
    min_words_global: int = MIN_WORDS_GLOBAL,
) -> tuple[dict, float]:
    """Detect the first ayah in the recording."""
    skip = _find_quran_start(words) if global_search else 0
    head_words = words[skip : skip + head_n] if global_search else words[:head_n]
    head_str = " ".join(word["word_norm"] for word in head_words)
    pos_thresh = position_threshold_global if global_search else position_threshold
    candidates = _build_candidate_pool(
        ayat,
        search_range,
        global_search=global_search,
        window_str=head_str,
        min_words_global=min_words_global,
    )
    return _select_best_candidate(
        _score_candidates(candidates, head_str, pos_thresh),
        len(head_str),
        latest=False,
        global_search=global_search,
        high_conf_position=high_conf_position,
    )


def detect_last_ayah(
    ayat: list[dict],
    words: list[dict],
    tail_n: int,
    search_range: int,
    *,
    global_search: bool = False,
    first_ayah: dict | None = None,
    position_threshold: float = POSITION_THRESHOLD,
    position_threshold_global: float = POSITION_THRESHOLD_GLOBAL,
    high_conf_position: float = HIGH_CONF_POSITION,
    min_words_global: int = MIN_WORDS_GLOBAL,
) -> tuple[dict, float]:
    """Detect the last ayah in the recording."""
    tail_str = " ".join(word["word_norm"] for word in words[-tail_n:])
    pos_thresh = position_threshold_global if global_search else position_threshold
    min_index = first_ayah.get("_index", 0) if first_ayah is not None else None
    candidates = _build_candidate_pool(
        ayat,
        search_range,
        global_search=global_search,
        window_str=tail_str,
        min_words_global=min_words_global,
        min_index=min_index,
        latest=True,
    )
    return _select_best_candidate(
        _score_candidates(candidates, tail_str, pos_thresh),
        len(tail_str),
        latest=True,
        global_search=global_search,
        high_conf_position=high_conf_position,
    )


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
    warnings: list[str] = []

    if global_search:
        warnings.append(
            "No --surah specified: ran a global search across all surahs in the file. "
            "Specify --surah for faster, more accurate results."
        )

    if len(words) < 20:
        warnings.append(
            f"Only {len(words)} word(s) in WhisperX output — transcript may be empty, too short, or corrupt."
        )

    if first_conf < low_conf:
        warnings.append(
            f"Low confidence for first ayah ({first_conf:.2f} < {low_conf:.2f}). "
            "Try increasing --head-words or --search-range, or verify that --quran matches the riwaya recited."
        )
    if last_conf < low_conf:
        warnings.append(
            f"Low confidence for last ayah ({last_conf:.2f} < {low_conf:.2f}). "
            "Try increasing --tail-words or --search-range."
        )

    first_index = first.get("_index", 0)
    last_index = last.get("_index", 0)
    if first_index > last_index:
        warnings.append(
            "Detected first ayah falls AFTER the detected last ayah in the Quran file — alignment is likely wrong. Consider widening --search-range."
        )

    if last_index - first_index < 2 and len(words) >= 40:
        duration = (words[-1]["end"] - words[0]["start"]) if words else 0.0
        if duration > 30:
            warnings.append(
                f"Only {last_index - first_index + 1} ayah(s) detected over {duration:.0f}s of audio — this looks suspiciously narrow. Consider increasing --search-range."
            )

    if first_conf > 0.0 and last_conf > 0.0:
        avg = (first_conf + last_conf) / 2.0
        if avg < 0.25:
            warnings.append(
                f"Average confidence is very low ({avg:.2f}). Ensure the Quran file matches the riwaya actually recited."
            )

    return warnings


def ayah_entry(ayah: dict, conf: float) -> dict:
    """Build the exported ayah summary entry."""
    return {
        "surah_num": ayah["surah_num"],
        "surah_name": ayah["surah_name"],
        "ayah_num": ayah["ayah_num"],
        "text": ayah["text_raw"],
        "confidence": conf,
    }


def ayat_in_detected_range(
    ayat: list[dict],
    first_ayah: dict,
    last_ayah: dict,
) -> list[dict]:
    """Return ayat from the detected recitation range."""
    target_surah = first_ayah["surah_num"]
    first_index = first_ayah["_index"]

    same_surah_last = last_ayah["surah_num"] == target_surah
    if same_surah_last and last_ayah["_index"] >= first_index:
        last_index = last_ayah["_index"]
    else:
        same_surah = [ayah for ayah in ayat if ayah["surah_num"] == target_surah]
        last_index = same_surah[-1]["_index"] if same_surah else first_index

    return [
        ayah
        for ayah in ayat
        if ayah["surah_num"] == target_surah and first_index <= ayah["_index"] <= last_index
    ]


def trim_match_to_ayah_range(
    match: dict,
    recitation_ayat: list[dict],
    from_ayah: int,
    to_ayah: int,
) -> dict | None:
    """Trim one lecture-style match to the selected recitation ayah range."""
    selected_ayat = [ayah for ayah in recitation_ayat if from_ayah <= ayah["ayah_num"] <= to_ayah]
    if not selected_ayat:
        return None

    full_text = "\n".join(
        ayah_text_with_marker(ayah["text_raw"], ayah["ayah_num"]) for ayah in selected_ayat
    )
    trimmed = dict(match)
    trimmed["from_ayah"] = selected_ayat[0]["ayah_num"]
    trimmed["to_ayah"] = selected_ayat[-1]["ayah_num"]
    trimmed["text"] = full_text
    trimmed["full_text"] = full_text
    return trimmed


def select_recitation_timeline(
    matches: list[dict],
    recitation_ayat: list[dict],
    *,
    max_span: int,
) -> list[dict]:
    """Keep one forward-moving set of recitation display spans."""
    if not matches or not recitation_ayat:
        return []

    first_ayah_num = recitation_ayat[0]["ayah_num"]
    last_ayah_num = recitation_ayat[-1]["ayah_num"]
    selected: list[dict] = []
    last_to_ayah = first_ayah_num - 1
    last_end_time = -1.0

    ordered = sorted(
        matches,
        key=lambda match: (
            match["start_time"],
            -match["confidence"],
            match["to_ayah"] - match["from_ayah"],
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

        trimmed = trim_match_to_ayah_range(match, recitation_ayat, from_ayah, to_ayah)
        if trimmed is None:
            continue

        selected.append(trimmed)
        last_to_ayah = trimmed["to_ayah"]
        last_end_time = trimmed["end_time"]

        if last_to_ayah >= last_ayah_num:
            break

    for index in range(1, len(selected)):
        prev_end = selected[index - 1]["end_time"]
        if selected[index]["start_time"] < prev_end:
            selected[index] = dict(selected[index])
            selected[index]["start_time"] = round(prev_end, 2)

    for index in range(len(selected) - 1):
        next_start = selected[index + 1]["start_time"]
        if selected[index]["end_time"] > next_start:
            selected[index] = dict(selected[index])
            selected[index]["end_time"] = round(next_start, 2)

    return selected

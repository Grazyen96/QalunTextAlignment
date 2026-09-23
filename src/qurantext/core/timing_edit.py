"""The rules every timing edit obeys.

The review editor lets a person drag word edges, nudge them, and ripple a run
of late words back into place. Those gestures live in widgets; the rules live
here, so they can be tested without a screen and so no widget ever writes a
timing itself.

Three invariants hold after every call: words keep their order, no two words
overlap, and no word is shorter than :data:`MIN_WORD_S`. Changing one word's
edge moves its neighbour's shared edge rather than overlapping it — dragging a
boundary between two words is the common case.

Every function returns new lists and leaves its input alone, which is what
makes undo a matter of keeping the previous list.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = ["MIN_WORD_S", "count_edited", "derive_card_windows", "retime", "ripple"]

#: Shortest a word may be made. Below this a word box cannot be grabbed.
MIN_WORD_S = 0.04


def _copy(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(word) for word in words]


def _set(word: dict[str, Any], key: str, value: float) -> None:
    value = round(float(value), 3)
    if float(word[key]) != value:
        word[key] = value
        word["edited"] = True


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def retime(
    words: list[dict[str, Any]],
    index: int,
    *,
    start: float | None = None,
    end: float | None = None,
) -> list[dict[str, Any]]:
    """Move one word's start and/or end, trimming a neighbour instead of overlapping it."""
    out = _copy(words)
    word = out[index]
    prev = out[index - 1] if index > 0 else None
    nxt = out[index + 1] if index + 1 < len(out) else None

    if start is not None:
        low = float(prev["start"]) + MIN_WORD_S if prev else 0.0
        new_start = _clamp(float(start), low, float(word["end"]) - MIN_WORD_S)
        _set(word, "start", new_start)
        if prev is not None and float(prev["end"]) > new_start:
            _set(prev, "end", new_start)

    if end is not None:
        high = float(nxt["end"]) - MIN_WORD_S if nxt else math.inf
        new_end = _clamp(float(end), float(word["start"]) + MIN_WORD_S, high)
        _set(word, "end", new_end)
        if nxt is not None and float(nxt["start"]) < new_end:
            _set(nxt, "start", new_end)

    return out


def ripple(
    words: list[dict[str, Any]],
    index: int,
    delta: float,
    *,
    duration: float | None = None,
) -> list[dict[str, Any]]:
    """Shift word *index* and every later word by *delta* seconds.

    The tool for a run of words that is uniformly early or late, such as the
    stretch after a dropped phrase.
    """
    out = _copy(words)
    prev = out[index - 1] if index > 0 else None
    first_start = float(out[index]["start"])
    low = (float(prev["start"]) + MIN_WORD_S if prev else 0.0) - first_start
    high = math.inf if duration is None else float(duration) - float(out[-1]["end"])
    delta = _clamp(float(delta), low, max(low, high))
    if delta == 0:
        return out

    for word in out[index:]:
        _set(word, "start", float(word["start"]) + delta)
        _set(word, "end", float(word["end"]) + delta)
    new_start = float(out[index]["start"])
    if prev is not None and float(prev["end"]) > new_start:
        _set(prev, "end", new_start)
    return out


def derive_card_windows(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make each timed card's window agree with its words again.

    A card starts at its first word and holds until the next card's first word,
    the latched tiling recitation alignment produces. The last card keeps its
    end (the audio end, as detection writes it) unless its words now run later.
    Cards with no word timings are returned unchanged. For recitation projects.
    """
    out = [dict(card) for card in cards]
    timed = [i for i, card in enumerate(out) if card.get("word_timings")]
    for position, i in enumerate(timed):
        card = out[i]
        words = card["word_timings"]
        card["start_time"] = round(float(words[0]["start"]), 3)
        if position + 1 < len(timed):
            following = out[timed[position + 1]]["word_timings"][0]
            card["end_time"] = round(float(following["start"]), 3)
        else:
            current = float(card.get("end_time") or 0.0)
            card["end_time"] = round(max(current, float(words[-1]["end"])), 3)
    return out


def count_edited(words: list[dict[str, Any]]) -> int:
    """How many words a person has retimed."""
    return sum(1 for word in words if word.get("edited"))

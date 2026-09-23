"""The rules every timing edit obeys.

The review editor lets a person drag word edges, nudge them, and ripple a run
of late words back into place. Those gestures live in widgets; the rules live
here, so they can be tested without a screen and so no widget ever writes a
timing itself.

Real alignment output is not tidy. It contains collapsed runs: words shorter
than :data:`MIN_WORD_S`, many of them zero-length, where the aligner could not
tell the words apart. The rules are written so they hold there too. For any
input that already satisfies 1 and 2, as alignment delivers it:

1. Every word in the output has ``start <= end``, and starts are non-decreasing
   in list order. This is a hard postcondition; no edit ever inverts a word.
2. No two words overlap: ``words[i]["end"] <= words[i + 1]["start"]``.
3. :data:`MIN_WORD_S` is a target, applied only when feasible. An edit never
   makes a word shorter than the minimum, but a word that already is (as
   alignment delivered it) may stay so, and is never made shorter still.
   Changing one word's edge moves its neighbour's shared edge rather than
   overlapping it, but never past that neighbour's other edge. When a limit
   cannot be met the edit is clamped to what is feasible, which in the middle
   of a collapsed run can mean not moving at all.

   By default an edge only ever *pushes* a neighbour: shortening a word
   leaves a gap. With ``keep_joined=True`` (what the review editor passes)
   an edge that touched its neighbour's shared edge before the edit
   (compared on the millisecond grid) keeps touching it in both directions,
   so a nudge and its opposite put both words back. The neighbour's shared
   edge is still bounded by its other edge and its minimum, exactly as
   above; an edge with a gap never moves its neighbour except to push it.
4. A request that equals the current value changes nothing: no ``edited``
   flag, output identical up to millisecond rounding (every time is snapped
   to the millisecond grid on copy, and that snap is monotonic).

Every function returns new lists and leaves its input alone, which is what
makes undo a matter of keeping the previous list.

Widgets edit a whole job's cards through :func:`retime_in_cards` and
:func:`ripple_in_cards`, so a card boundary constrains an edit like any other
neighbour and the card windows are re-derived in the same call.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = [
    "MIN_WORD_S",
    "count_edited",
    "cue_bounds",
    "derive_card_windows",
    "retime",
    "retime_in_cards",
    "ripple",
    "ripple_in_cards",
]

#: Shortest a word may be made. Below this a word box cannot be grabbed.
MIN_WORD_S = 0.04


def _snap(value: float) -> float:
    return round(float(value), 3)


def _copy(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy *words*, on the millisecond grid every written time is on anyway.

    Rounding is monotonic, so a list with no inverted and no overlapping words
    keeps both properties; without this, rounding one edge after a clamp could
    invert a neighbour that sits off the grid.
    """
    return [{**word, "start": _snap(word["start"]), "end": _snap(word["end"])} for word in words]


def _check(index: int, count: int, what: str) -> None:
    if not 0 <= index < count:
        raise IndexError(f"There is no {what} {index} (there are {count}).")


def _set(word: dict[str, Any], key: str, value: float) -> None:
    if float(word[key]) == value:
        return
    value = round(float(value), 3)
    if float(word[key]) != value:
        word[key] = value
        word["edited"] = True


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _keep(word: dict[str, Any]) -> float:
    """How much of *word* an edit must leave: the minimum, or all of it if it is shorter."""
    return min(MIN_WORD_S, max(0.0, float(word["end"]) - float(word["start"])))


def retime(
    words: list[dict[str, Any]],
    index: int,
    *,
    start: float | None = None,
    end: float | None = None,
    keep_joined: bool = False,
) -> list[dict[str, Any]]:
    """Move one word's start and/or end, trimming a neighbour instead of overlapping it.

    With *keep_joined*, an edge that shared its instant with the neighbour's
    edge before the edit takes that edge along either way (rule 3 in the
    module docstring), so shortening the word no longer opens a gap there.

    Operates on one list. Widgets call :func:`retime_in_cards`, which applies this
    across card boundaries.
    """
    _check(index, len(words), "word")
    out = _copy(words)
    word = out[index]
    prev = out[index - 1] if index > 0 else None
    nxt = out[index + 1] if index + 1 < len(out) else None
    # Judged before anything moves, on the grid ``_copy`` just put every edge on.
    joined_prev = keep_joined and prev is not None and prev["end"] == word["start"]
    joined_next = keep_joined and nxt is not None and word["end"] == nxt["start"]

    if start is not None:
        start = _snap(start)
        current = float(word["start"])
        low = float(prev["start"]) + _keep(prev) if prev else 0.0
        high = float(word["end"]) - _keep(word)
        # The current value is always reachable, so a no-op request stays one
        # even on input that does not meet the rules.
        _set(word, "start", _clamp(float(start), min(low, current), max(high, current)))
        new_start = float(word["start"])
        if prev is not None and (joined_prev or float(prev["end"]) > new_start):
            _set(prev, "end", new_start)

    if end is not None:
        end = _snap(end)
        current = float(word["end"])
        low = float(word["start"]) + _keep(word)
        high = float(nxt["end"]) - _keep(nxt) if nxt else math.inf
        _set(word, "end", _clamp(float(end), min(low, current), max(high, current)))
        new_end = float(word["end"])
        if nxt is not None and (joined_next or float(nxt["start"]) < new_end):
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
    stretch after a dropped phrase. Clamped so the run never passes the start
    of the word before it and, with *duration*, never runs past the audio; a
    clamp never turns the shift around. Widgets call :func:`ripple_in_cards`.
    """
    _check(index, len(words), "word")
    out = _copy(words)
    prev = out[index - 1] if index > 0 else None
    first_start = float(out[index]["start"])
    low = min(0.0, (float(prev["start"]) + _keep(prev) if prev else 0.0) - first_start)
    high = math.inf if duration is None else max(0.0, float(duration) - float(out[-1]["end"]))
    delta = _clamp(_snap(delta), low, high)
    if delta == 0:
        return out

    for word in out[index:]:
        _set(word, "start", float(word["start"]) + delta)
        _set(word, "end", float(word["end"]) + delta)
    new_start = float(out[index]["start"])
    if prev is not None and float(prev["end"]) > new_start:
        _set(prev, "end", new_start)
    return out


def _flatten(
    cards: list[dict[str, Any]], card_index: int, word_index: int
) -> tuple[list[dict[str, Any]], list[tuple[int, int]], int]:
    """All timed cards' words as one list, where each card's run sits, and the global index."""
    _check(card_index, len(cards), "card")
    if not cards[card_index].get("word_timings"):
        raise ValueError(f"Card {card_index} has no word timings to edit.")
    _check(word_index, len(cards[card_index]["word_timings"]), "word")
    flat: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []
    target = -1
    for i, card in enumerate(cards):
        words = card.get("word_timings")
        if not words:
            continue
        if i == card_index:
            target = len(flat) + word_index
        spans.append((i, len(words)))
        flat.extend(words)
    return flat, spans, target


def _split(
    cards: list[dict[str, Any]], flat: list[dict[str, Any]], spans: list[tuple[int, int]]
) -> list[dict[str, Any]]:
    out = [dict(card) for card in cards]
    offset = 0
    for i, length in spans:
        out[i]["word_timings"] = flat[offset : offset + length]
        offset += length
    return derive_card_windows(out)


def retime_in_cards(
    cards: list[dict[str, Any]],
    card_index: int,
    word_index: int,
    *,
    start: float | None = None,
    end: float | None = None,
    keep_joined: bool = False,
) -> list[dict[str, Any]]:
    """:func:`retime` one word of a job's cards, and re-derive the card windows.

    This is what widgets call. The timed cards' words are edited as one list, so
    the first word of the next card constrains and is trimmed like any other
    neighbour, instead of being overrun by a card's lengthened last word. Cards
    without word timings pass through untouched; the input is never mutated.
    """
    flat, spans, target = _flatten(cards, card_index, word_index)
    edited = retime(flat, target, start=start, end=end, keep_joined=keep_joined)
    return _split(cards, edited, spans)


def ripple_in_cards(
    cards: list[dict[str, Any]],
    card_index: int,
    word_index: int,
    delta: float,
    *,
    duration: float | None = None,
) -> list[dict[str, Any]]:
    """:func:`ripple` from one word of a job's cards through every later card.

    This is what widgets call. A late run rarely stops at a card boundary, so
    the shift carries on into the following cards and their windows move with
    it. Cards without word timings pass through untouched; the input is never
    mutated.
    """
    flat, spans, target = _flatten(cards, card_index, word_index)
    return _split(cards, ripple(flat, target, delta, duration=duration), spans)


def cue_bounds(start: float, end: float, words: list[dict[str, Any]]) -> tuple[float, float]:
    """A caption line's window, grown to cover its words after they are retimed."""
    if not words:
        return start, end
    return (
        _snap(min(float(start), float(words[0]["start"]))),
        _snap(max(float(end), float(words[-1]["end"]))),
    )


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

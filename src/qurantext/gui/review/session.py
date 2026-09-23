"""What the review window edits, kept apart from the widgets.

Every gesture in the window — a drag, a nudge, a ripple, a corrected caption —
ends up here, and every rule about what an edit may do lives in
``core.timing_edit``. The widgets only draw this object and forward what the
person did. That keeps the rules testable without a screen, and it means undo
is one mechanism for every kind of edit: a snapshot of the cards, captions and
review state before each change.

A drag is many small edits and must undo as one, so a gesture brackets them:
one snapshot at the start, none while it runs, and none at all if the gesture
changed nothing.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from qurantext.core.timing_edit import (
    count_edited,
    cue_bounds,
    retime,
    retime_in_cards,
    ripple,
    ripple_in_cards,
)
from qurantext.core.video_common import validated_matches
from qurantext.jobs.project import Project, save_project

__all__ = ["CAPTION", "CARD", "ReviewSession", "TimelineWord", "WordRef"]

CARD = "card"
CAPTION = "caption"


@dataclass(frozen=True, slots=True)
class WordRef:
    """Which word: an ayah card's or a caption line's, by position."""

    kind: str
    segment: int
    word: int


@dataclass(frozen=True, slots=True)
class TimelineWord:
    """A word as the timeline draws it."""

    ref: WordRef
    text: str
    start: float
    end: float
    edited: bool


class ReviewSession:
    """The project being reviewed, with undo and a record of unsaved changes."""

    def __init__(self, project: Project, *, duration: float | None = None) -> None:
        self.project = project
        self.duration = duration
        self._undo: list[tuple] = []
        self._redo: list[tuple] = []
        self._in_gesture = False
        self._gesture_start: tuple | None = None
        self._revision = 0
        self._saved_key = self._key()
        self._validated: tuple[int, list[dict[str, Any]]] | None = None

    # -- state ------------------------------------------------------------------

    @property
    def primary_kind(self) -> str:
        return CARD if self.project.mode == "recitation" else CAPTION

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def dirty(self) -> bool:
        return self._key() != self._saved_key

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def _key(self) -> str:
        return json.dumps(
            {
                "cards": self.project.cards,
                "captions": [cue.to_dict() for cue in self.project.captions],
                "review": self.project.review,
            },
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )

    def _snapshot(self) -> tuple:
        return (
            copy.deepcopy(self.project.cards),
            copy.deepcopy(self.project.captions),
            copy.deepcopy(self.project.review),
        )

    def _restore(self, snapshot: tuple) -> None:
        cards, captions, review = snapshot
        self.project.cards = copy.deepcopy(cards)
        self.project.captions = copy.deepcopy(captions)
        self.project.review = copy.deepcopy(review)

    def _before_change(self) -> None:
        if not self._in_gesture:
            self._undo.append(self._snapshot())
            self._redo.clear()

    def _changed(self) -> None:
        self._revision += 1

    # -- reading ----------------------------------------------------------------

    def words(self, kind: str | None = None) -> list[TimelineWord]:
        kinds = (kind or self.primary_kind,)
        out: list[TimelineWord] = []
        if CARD in kinds:
            for s, card in enumerate(self.project.cards):
                for w, word in enumerate(card.get("word_timings") or []):
                    out.append(self._timeline_word(CARD, s, w, word))
        if CAPTION in kinds:
            for s, cue in enumerate(self.project.captions):
                for w, word in enumerate(cue.words):
                    out.append(self._timeline_word(CAPTION, s, w, word))
        out.sort(key=lambda tw: (tw.start, tw.ref.kind, tw.ref.segment, tw.ref.word))
        return out

    @staticmethod
    def _timeline_word(kind: str, segment: int, index: int, word: dict[str, Any]) -> TimelineWord:
        return TimelineWord(
            ref=WordRef(kind, segment, index),
            text=str(word.get("word") or ""),
            start=float(word["start"]),
            end=float(word["end"]),
            edited=bool(word.get("edited")),
        )

    def _raw_words(self, ref: WordRef) -> list[dict[str, Any]]:
        if ref.kind == CARD:
            return self.project.cards[ref.segment].get("word_timings") or []
        return self.project.captions[ref.segment].words

    def word(self, ref: WordRef) -> TimelineWord:
        return self._timeline_word(ref.kind, ref.segment, ref.word, self._raw_words(ref)[ref.word])

    def step(self, ref: WordRef | None, direction: int) -> WordRef | None:
        ordered = [tw.ref for tw in self.words(ref.kind if ref else None)]
        if not ordered:
            return None
        if ref is None:
            return ordered[0] if direction > 0 else ordered[-1]
        i = ordered.index(ref) + (1 if direction > 0 else -1)
        return ordered[i] if 0 <= i < len(ordered) else None

    def word_at(self, t: float) -> WordRef | None:
        found = None
        for tw in self.words():
            if tw.start <= t:
                found = tw.ref
            else:
                break
        return found

    def card_at(self, t: float) -> int | None:
        found = None
        for i, card in enumerate(self.project.cards):
            if float(card.get("start_time") or 0.0) <= t:
                found = i
        return found

    def caption_at(self, t: float) -> int | None:
        for i, cue in enumerate(self.project.captions):
            if cue.start <= t <= cue.end:
                return i
        return None

    def retimed_count(self, kind: str, segment: int) -> int:
        return count_edited(self._raw_words(WordRef(kind, segment, 0)))

    def coverage_words(self) -> list[dict[str, float]]:
        return [{"start": tw.start, "end": tw.end} for tw in self.words()]

    def frame_inputs(self, t: float) -> tuple[dict | None, dict | None, bool]:
        if self._validated is None or self._validated[0] != self._revision:
            cards = validated_matches(copy.deepcopy(self.project.cards), bridge_gaps=False)
            cards.sort(key=lambda card: float(card["_start_time"]))
            self._validated = (self._revision, cards)
        active = [card for card in self._validated[1] if float(card["_start_time"]) <= t]
        index = self.caption_at(t)
        caption = self.project.caption_segments()[index] if index is not None else None
        return (active[-1] if active else None), caption, bool(self.project.captions)

    # -- editing ----------------------------------------------------------------

    def retime(self, ref: WordRef, *, start: float | None = None, end: float | None = None) -> None:
        self._before_change()
        if ref.kind == CARD:
            self.project.cards = retime_in_cards(
                self.project.cards, ref.segment, ref.word, start=start, end=end
            )
        else:
            cue = self.project.captions[ref.segment]
            words = retime(cue.words, ref.word, start=start, end=end)
            self._set_cue_words(ref.segment, words)
        self._changed()

    def ripple(self, ref: WordRef, delta: float) -> None:
        self._before_change()
        if ref.kind == CARD:
            self.project.cards = ripple_in_cards(
                self.project.cards, ref.segment, ref.word, delta, duration=self.duration
            )
        else:
            cue = self.project.captions[ref.segment]
            words = ripple(cue.words, ref.word, delta, duration=self.duration)
            self._set_cue_words(ref.segment, words)
        self._changed()

    def _set_cue_words(self, index: int, words: list[dict[str, Any]]) -> None:
        cue = self.project.captions[index]
        start, end = cue_bounds(cue.start, cue.end, words)
        self.project.captions[index] = replace(cue, start=start, end=end, words=words)

    def set_caption_text(self, index: int, text: str) -> None:
        if text == self.project.captions[index].text:
            return
        self._before_change()
        self.project.captions[index] = self.project.captions[index].edited(text)
        self._changed()

    def set_card_times(
        self, index: int, *, start: float | None = None, end: float | None = None
    ) -> None:
        card = self.project.cards[index]
        if card.get("word_timings"):
            raise ValueError("This card's times follow its words; retime the words instead.")
        self._before_change()
        new = dict(card)
        if start is not None:
            new["start_time"] = round(float(start), 3)
        if end is not None:
            new["end_time"] = round(float(end), 3)
        new["end_time"] = max(float(new["end_time"]), float(new["start_time"]))
        self.project.cards[index] = new
        self._changed()

    def remove_card(self, index: int) -> None:
        self._before_change()
        del self.project.cards[index]
        self._changed()

    def remove_caption(self, index: int) -> None:
        self._before_change()
        del self.project.captions[index]
        self._changed()

    def mark_reviewed(self) -> None:
        self._before_change()
        self.project.mark_reviewed()
        self._changed()

    # -- gestures and undo -----------------------------------------------------

    def begin_gesture(self) -> None:
        if self._in_gesture:
            return
        self._gesture_start = self._snapshot()
        self._undo.append(self._gesture_start)
        self._redo.clear()
        self._in_gesture = True

    def end_gesture(self) -> None:
        if not self._in_gesture:
            return
        self._in_gesture = False
        if self._undo and self._undo[-1] is self._gesture_start:
            cards, captions, review = self._gesture_start
            if (
                cards == self.project.cards
                and [c.to_dict() for c in captions] == [c.to_dict() for c in self.project.captions]
                and review == self.project.review
            ):
                self._undo.pop()
        self._gesture_start = None

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        self._changed()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        self._changed()
        return True

    # -- saving -----------------------------------------------------------------

    def save(self) -> Path:
        if self.project.path is None:
            raise ValueError("This project has no file to write back to.")
        path = save_project(self.project, self.project.path)
        self._saved_key = self._key()
        return path

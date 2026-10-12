"""What the review window edits, kept apart from the widgets.

Every gesture in the window — a drag, a nudge, a ripple, a corrected caption —
ends up here, and every rule about what an edit may do lives in
``core.timing_edit``. The widgets only draw this object and forward what the
person did. That keeps the rules testable without a screen, and it means undo
is one mechanism for every kind of edit: a snapshot of the cards, captions,
review state, style (which holds the video's look), the lecture's chosen
studied surah and its episode (intro, recitation, outro) before each change.

A drag is many small edits and must undo as one, so a gesture brackets them:
one snapshot at the start, none while it runs, and none at all if the gesture
changed nothing.
"""

from __future__ import annotations

import bisect
import copy
import json
import math
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from qurantext.config.paths import QURAN_DB_PATH
from qurantext.core.frame_renderer import CaptionTrack
from qurantext.core.looks import Look
from qurantext.core.timing_edit import (
    count_edited,
    cue_bounds,
    derive_card_windows,
    retime,
    retime_in_cards,
    ripple,
    ripple_in_cards,
)
from qurantext.core.video_common import (
    cards_on_screen,
    guessed_studied_surah,
    has_surah_cards,
    is_manual_card,
    validated_matches,
)
from qurantext.data.quran_db import ayah_range_card, connect, surah_ayah_count
from qurantext.gui.i18n import t
from qurantext.jobs.episode_assets import EpisodeChoice, project_episode, set_project_episode
from qurantext.jobs.look_assets import project_look, set_project_look
from qurantext.jobs.project import (
    CaptionCue,
    Project,
    job_settings,
    save_project,
    studied_surah_choice,
)

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


def _normalized_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """*words* with every start/end rounded to the grid, for the dirty check only."""
    return [
        {**word, "start": round(float(word["start"]), 3), "end": round(float(word["end"]), 3)}
        for word in words
    ]


def _normalized_card(card: dict[str, Any]) -> dict[str, Any]:
    timings = card.get("word_timings")
    if not timings:
        return card
    return {**card, "word_timings": _normalized_words(timings)}


def _normalized_caption(cue: CaptionCue) -> dict[str, Any]:
    data = cue.to_dict()
    if data.get("words"):
        data["words"] = _normalized_words(data["words"])
    return data


def _unflagged(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """*words* on the grid and without ``edited``: what an edit could have changed."""
    return [
        {key: value for key, value in word.items() if key != "edited"}
        for word in _normalized_words(words)
    ]


def _studied_surah(project: Project) -> int | None:
    """The project's chosen studied surah, None when it guesses (``JobSettings``)."""
    return studied_surah_choice(project.export.get("studied_surah"))


def _set_studied_surah(project: Project, surah: int | None) -> None:
    """Write only the studied surah into ``project.export``.

    Not through ``set_job_settings``: that writes every output choice, and an
    undo of the surah must not add a preset the project never stored.
    """
    export = dict(project.export)
    if surah is None:
        export.pop("studied_surah", None)
    else:
        export["studied_surah"] = surah
    project.export = export


def _settled(
    cards: list,
    captions: list[CaptionCue],
    review: dict,
    style: dict,
    studied: int | None,
    episode: dict,
) -> tuple:
    """A state as a timing edit would leave it, for telling "no edit" from an edit.

    Every timing edit re-derives the card windows from their words (and snaps
    to the millisecond grid), and a loaded project's windows are often a hair
    off: detection rounds a card's window on its own, so a card can open at
    0.11 over a first word at 0.109. Comparing raw states would then read a
    drag that ended where it began as a change. Settling both sides first —
    windows derived, times on the grid, ``edited`` flags dropped — compares
    what the person could see. The flags go because a word whose times are
    where they were was not retimed, whatever an edit on the way marked it.
    Cards without word timings pass through ``derive_card_windows`` untouched,
    and only a timing edit re-derives a timed card's window
    (``set_card_times`` refuses them), so this holds in either mode. The style,
    the studied surah and the episode are compared as they are.
    """
    settled_cards = []
    for card in derive_card_windows(cards):
        if card.get("word_timings"):
            card = {**card, "word_timings": _unflagged(card["word_timings"])}
        settled_cards.append(card)
    settled_captions = []
    for cue in captions:
        data = cue.to_dict()
        if data.get("words"):
            data["words"] = _unflagged(data["words"])
        settled_captions.append(data)
    return settled_cards, settled_captions, review, style, studied, episode


#: The shortest time a card the person places stays on screen, in milliseconds.
_MIN_CARD_MS = 500
#: How near a card's start an insert lands "on" it, in milliseconds.
_SAME_START_MS = 50


def _range_card(surah_num: int, from_ayah: int, to_ayah: int, db_path: Path) -> dict[str, Any]:
    """The reference and text of an ayah range, read from the store at *db_path*.

    Every failure is a ``ValueError`` with a message in the window's language,
    so the window has one exception to catch and a message to show: a range
    the surah does not have, and a store that is missing, unreadable or of an
    older build.
    """
    try:
        conn = connect(db_path)
    except (OSError, sqlite3.Error) as exc:
        raise ValueError(t("session.manual_store_unavailable", details=exc)) from exc
    try:
        return ayah_range_card(conn, surah_num, from_ayah, to_ayah)
    except sqlite3.Error as exc:
        raise ValueError(t("session.manual_store_unavailable", details=exc)) from exc
    except ValueError as exc:
        if _in_surah(conn, surah_num, from_ayah, to_ayah):
            # A sound reference the store has no text for: the store is damaged.
            raise ValueError(t("session.manual_store_unavailable", details=exc)) from exc
        raise ValueError(
            t("session.manual_bad_reference", surah=surah_num, first=from_ayah, last=to_ayah)
        ) from exc
    finally:
        conn.close()


def _in_surah(conn: sqlite3.Connection, surah_num: Any, from_ayah: Any, to_ayah: Any) -> bool:
    """Whether *from_ayah*–*to_ayah* are whole ayat numbers within the store's count for the surah."""
    numbers = (surah_num, from_ayah, to_ayah)
    if any(isinstance(n, bool) or not isinstance(n, int) for n in numbers):
        return False
    try:
        count = surah_ayah_count(conn, surah_num)
    except (ValueError, sqlite3.Error):
        return False
    return 1 <= from_ayah <= to_ayah <= count


def _ms(value: Any) -> int | None:
    """A card time in whole milliseconds, or None when it is not a usable time.

    Insert rules compare on the millisecond grid the cards are stored on, so
    "within 0.05 s" holds at exactly 0.05 s, which float subtraction misses.
    """
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return round(seconds * 1000) if math.isfinite(seconds) else None


def _changed_card(card: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    """*card* at its own times, showing *reference*, without what detection said about it."""
    new = {
        key: value
        for key, value in card.items()
        if key != "word_timings" and not key.startswith(("_matched", "matched"))
    }
    new.update(reference)
    new.update(detected_text="", confidence=1.0, manual=True)
    return new


class ReviewSession:
    """The project being reviewed, with undo and a record of unsaved changes."""

    def __init__(self, project: Project, *, duration: float | None = None) -> None:
        self.project = project
        self.duration = duration
        self._undo: list[tuple] = []
        self._redo: list[tuple] = []
        self._in_gesture = False
        self._gesture_start: tuple | None = None
        #: The redo history, set aside while a gesture runs: given back if the
        #: gesture changes nothing (a click on a word), dropped if it edits.
        self._gesture_redo: list[tuple] = []
        self._revision = 0
        self._look_cache: tuple[int, Look] | None = None
        self._saved_key = self._key()
        #: What :meth:`revert` puts back: the state as loaded, or as last saved.
        self._saved_snapshot = self._snapshot()
        self._validated: tuple[int, list[dict[str, Any]]] | None = None
        self._caption_track: tuple[int, CaptionTrack] | None = None
        self._words_revision: int | None = None
        self._words_by_kind: dict[str, list[TimelineWord]] = {}
        self._starts_by_kind: dict[str, list[float]] = {}
        self._position_by_kind: dict[str, dict[WordRef, int]] = {}
        self._max_len_by_kind: dict[str, float] = {}

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

    @property
    def look(self) -> Look:
        """The look the preview draws with: the project's style, cached per revision."""
        if self._look_cache is None or self._look_cache[0] != self._revision:
            self._look_cache = (self._revision, project_look(self.project))
        return self._look_cache[1]

    def _key(self) -> str:
        """A snapshot for the dirty check, with every word edge on the millisecond grid.

        ``timing_edit`` re-snaps a whole list's edges to 3 decimals on every
        edit as a side effect (see its module docstring), even for words the
        edit did not target. Comparing raw floats would then read that
        snap-only cleanup as a change; rounding here first makes a
        value-preserving snap invisible to ``dirty``.
        """
        return json.dumps(
            {
                "cards": [_normalized_card(card) for card in self.project.cards],
                "captions": [_normalized_caption(cue) for cue in self.project.captions],
                "review": self.project.review,
                "style": self.project.style,
                "studied_surah": _studied_surah(self.project),
                "episode": self.project.episode,
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
            copy.deepcopy(self.project.style),
            _studied_surah(self.project),
            copy.deepcopy(self.project.episode),
        )

    def _restore(self, snapshot: tuple) -> None:
        cards, captions, review, style, studied, episode = snapshot
        self.project.cards = copy.deepcopy(cards)
        self.project.captions = copy.deepcopy(captions)
        self.project.review = copy.deepcopy(review)
        self.project.style = copy.deepcopy(style)
        if _studied_surah(self.project) != studied:
            _set_studied_surah(self.project, studied)
        self.project.episode = copy.deepcopy(episode)

    def _before_change(self) -> None:
        if not self._in_gesture:
            self._undo.append(self._snapshot())
            self._redo.clear()

    def _changed(self) -> None:
        self._revision += 1

    # -- reading ----------------------------------------------------------------

    def words(self, kind: str | None = None) -> list[TimelineWord]:
        """Timed words of *kind* (default: the primary kind), oldest start first.

        The window polls this at frame rate, so the sorted list is cached per
        kind and kept until the next change (``revision`` moving invalidates
        every kind's cache, like ``_validated``). The returned list is the
        cached object itself, not a copy — its entries are frozen dataclasses,
        but callers must still treat the *list* as read-only and never mutate
        or reorder it in place; make a copy first if a caller needs to.
        """
        resolved = kind or self.primary_kind
        self._refresh_words_cache()
        cached = self._words_by_kind.get(resolved)
        if cached is None:
            cached = self._build_words(resolved)
            self._words_by_kind[resolved] = cached
            self._starts_by_kind[resolved] = [tw.start for tw in cached]
            self._position_by_kind[resolved] = {tw.ref: i for i, tw in enumerate(cached)}
        return cached

    def _refresh_words_cache(self) -> None:
        if self._words_revision != self._revision:
            self._words_revision = self._revision
            self._words_by_kind = {}
            self._starts_by_kind = {}
            self._position_by_kind = {}
            self._max_len_by_kind = {}

    def words_in(self, t0: float, t1: float, kind: str | None = None) -> list[TimelineWord]:
        """Words of *kind* overlapping ``[t0, t1]``: ``end >= t0`` and ``start <= t1``.

        A widget painting or hit-testing a visible window need not walk every
        word to find the handful in view. This bisects the cached,
        start-sorted list to the range that could possibly overlap — backing
        the lower bound up by the kind's longest word (also cached, so a
        single outlier doesn't cost anything after the first call) to catch a
        word that starts before *t0* but still ends inside the window — then
        filters only that slice.
        """
        resolved = kind or self.primary_kind
        words = self.words(resolved)
        if not words:
            return []
        starts = self._starts_by_kind[resolved]
        lo = bisect.bisect_left(starts, t0 - self._max_len(resolved))
        hi = bisect.bisect_right(starts, t1)
        return [tw for tw in words[lo:hi] if tw.end >= t0]

    def _max_len(self, kind: str) -> float:
        self._refresh_words_cache()
        cached = self._max_len_by_kind.get(kind)
        if cached is None:
            cached = max((tw.end - tw.start for tw in self.words(kind)), default=0.0)
            self._max_len_by_kind[kind] = cached
        return cached

    def _build_words(self, kind: str) -> list[TimelineWord]:
        out: list[TimelineWord] = []
        if kind == CARD:
            for s, card in enumerate(self.project.cards):
                for w, word in enumerate(card.get("word_timings") or []):
                    out.append(self._timeline_word(CARD, s, w, word))
        else:
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
        resolved = ref.kind if ref else self.primary_kind
        ordered = self.words(resolved)
        if not ordered:
            return None
        if ref is None:
            return (ordered[0] if direction > 0 else ordered[-1]).ref
        i = self._position_by_kind[resolved][ref] + (1 if direction > 0 else -1)
        return ordered[i].ref if 0 <= i < len(ordered) else None

    def word_at(self, t: float) -> WordRef | None:
        """The primary-kind word that most recently started at or before *t*.

        Bisects the cached, start-sorted list instead of scanning it, so this
        stays cheap when the window polls it at frame rate against a long
        lecture's thousands of caption words.
        """
        words = self.words()
        starts = self._starts_by_kind[self.primary_kind]
        i = bisect.bisect_right(starts, t)
        return words[i - 1].ref if i > 0 else None

    def card_at(self, t: float) -> int | None:
        found = None
        for i, card in enumerate(self.project.cards):
            if float(card.get("start_time") or 0.0) <= t:
                found = i
        return found

    def caption_at(self, t: float) -> int | None:
        """The caption the rendered video shows at *t*, by the renderer's own rule.

        Where cues overlap that is the latest-started one, not the first in
        list order; see ``core.frame_renderer.CaptionTrack``. Cached per
        revision, since the window asks at frame rate.
        """
        if self._caption_track is None or self._caption_track[0] != self._revision:
            spans = [(cue.start, cue.end) for cue in self.project.captions]
            self._caption_track = (self._revision, CaptionTrack(spans))
        return self._caption_track[1].index_at(t)

    def retimed_count(self, kind: str, segment: int) -> int:
        return count_edited(self._raw_words(WordRef(kind, segment, 0)))

    def coverage_words(self) -> list[dict[str, float]]:
        return [{"start": tw.start, "end": tw.end} for tw in self.words()]

    def validated_cards(self) -> list[dict[str, Any]]:
        """The cards as the frame renderer draws them: enriched, sorted by start time.

        A lecture's quotes from other surahs are left out, as the export leaves
        them out (``core.video_common.cards_on_screen``), keeping to the
        project's chosen studied surah when it has one.

        Cached per revision — ``frame_inputs`` is built from this, and a
        caller that also needs to mirror the renderer's own logic exactly
        (``core.frame_renderer.placeholder_lines``, for the live-frame
        preview's opening placeholder) can share the same cache instead of
        re-running ``validated_matches`` itself.
        """
        if self._validated is None or self._validated[0] != self._revision:
            cards = cards_on_screen(
                validated_matches(copy.deepcopy(self.project.cards), bridge_gaps=False),
                self.project.mode,
                self.studied_surah,
            )
            cards.sort(key=lambda card: float(card["_start_time"]))
            self._validated = (self._revision, cards)
        return self._validated[1]

    def frame_inputs(self, t: float) -> tuple[dict | None, dict | None, bool]:
        """The active card, the active caption, and whether the frame keeps a caption band.

        The band is kept only when the job burns its captions in: a
        sidecar-only render drops it (``jobs.export``), and the preview should
        look like the video the job will make.
        """
        active = [card for card in self.validated_cards() if float(card["_start_time"]) <= t]
        index = self.caption_at(t)
        caption = self._caption_segment(index) if index is not None else None
        band = bool(self.project.captions) and job_settings(self.project).subtitles != "sidecar"
        return (active[-1] if active else None), caption, band

    def _caption_segment(self, index: int) -> dict[str, Any]:
        """One cue in the shape ``Project.caption_segments()`` produces, built for this cue alone.

        The frame renderer only ever needs the one active cue; rebuilding the
        whole track's segments (``Project.caption_segments()``) every frame
        does needless work on a long lecture.
        """
        cue = self.project.captions[index]
        return {
            "text": cue.text,
            "start": float(cue.start),
            "end": float(cue.end),
            "word_timings": list(cue.words),
        }

    # -- editing ----------------------------------------------------------------

    def retime(
        self,
        ref: WordRef,
        *,
        start: float | None = None,
        end: float | None = None,
        keep_joined: bool = True,
    ) -> None:
        """Move *ref*'s edge; one it shared with the neighbour takes the neighbour's along.

        ``keep_joined`` is what makes a nudge reversible: ``,`` (later) pushes
        the next word's start, and ``.`` (earlier) brings it back instead of
        leaving a gap. Pass False to move the edge alone (a neighbour is then
        only ever pushed), which is how a gap is opened between two joined
        words. An edit that puts everything back where it was last saved is
        settled back to exactly that state (see :meth:`_settle`), so it does
        not read as unsaved.
        """
        self._before_change()
        if ref.kind == CARD:
            self.project.cards = retime_in_cards(
                self.project.cards,
                ref.segment,
                ref.word,
                start=start,
                end=end,
                keep_joined=keep_joined,
            )
        else:
            cue = self.project.captions[ref.segment]
            words = retime(cue.words, ref.word, start=start, end=end, keep_joined=keep_joined)
            self._set_cue_words(ref.segment, words)
        self._settle(ref)
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
        self._settle(ref)
        self._changed()

    def drag_retime(
        self,
        ref: WordRef,
        *,
        start: float | None = None,
        end: float | None = None,
        keep_joined: bool = True,
    ) -> None:
        """Inside a gesture: *ref*'s edge where the pointer is now, applied to the gesture's start.

        Retiming the current state on every move would keep whatever a move
        on the way did to a neighbour: drag an end past the next word and
        back, and the next word stays trimmed. Starting each move from the
        state the drag began in makes the result depend only on where the
        pointer is, so dragging back puts everything back. Like a nudge, it
        goes through :meth:`retime`, so an edge the neighbour shared stays
        shared while it is dragged, unless *keep_joined* is False (a Ctrl or
        Alt drag in the word strip), which detaches it.
        """
        self._restore_gesture_start()
        self.retime(ref, start=start, end=end, keep_joined=keep_joined)

    def drag_ripple(self, ref: WordRef, total_delta: float) -> None:
        """Inside a gesture: ripple from *ref* by the pointer's whole travel since the press.

        A ripple clamps (it never passes the previous word's start), so
        adding up the per-move deltas would count travel the clamp refused
        and leave the run displaced once the pointer comes back. One ripple
        of the total, from the gesture's start, cannot drift.
        """
        self._restore_gesture_start()
        self.ripple(ref, total_delta)

    def _restore_gesture_start(self) -> None:
        if not self._in_gesture or self._gesture_start is None:
            raise RuntimeError("A drag edit is only valid between begin_gesture and end_gesture.")
        self._restore(self._gesture_start)

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
            raise ValueError(t("session.card_follows_words"))
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
        """Remove card *index*; in a recitation the card before it then holds until the next.

        Recitation cards tile the recording (each holds until the next one's
        first word), so a removed card must not leave a hole where no ayah
        shows. Lecture cards are quotes with their own windows and stay as
        they are.
        """
        self._before_change()
        del self.project.cards[index]
        if self.project.mode == "recitation":
            self.project.cards = derive_card_windows(self.project.cards)
        self._changed()

    def is_manual(self, index: int) -> bool:
        """Whether card *index* was placed or changed by hand rather than detected.

        The same test the video uses to keep the card on screen
        (``core.video_common.is_manual_card``), so the window's mark and the
        video never disagree about a card.
        """
        return is_manual_card(self.project.cards[index])

    def insert_manual_card(
        self,
        at: float,
        surah_num: int,
        from_ayah: int,
        to_ayah: int,
        *,
        db_path: Path = QURAN_DB_PATH,
    ) -> int:
        """Show ayat *from_ayah*–*to_ayah* of *surah_num* from *at*; one undo step.

        Detection follows recitation, so it misses the ayah a teacher goes back
        to and talks about without reciting it, and the person places that
        card by hand at the playhead. The card holds until the next card
        starts, or the recording ends; a card that is on screen at *at* now
        ends there, so the new one is what shows.

        No card the person places, or trims, lasts under half a second: one
        would flash its ayah for a frame or two. So *at* changes an existing
        card instead of adding one beside it when it falls within 0.05 s of
        that card's start, in the first half second of a card on screen, or
        less than half a second before the next card starts. The nearest such
        start wins, and of two equally near, one that lasts half a second or
        more. The changed card keeps its times (see :meth:`change_card_ayah`).

        Returns the card's index once the cards are back in start order.
        Raises ``ValueError`` outside a lecture, for a reference the store does
        not have, or when the store cannot be read; then nothing changed and
        there is nothing to undo.
        """
        self._require_lecture()
        at = max(0.0, float(at))
        if self.duration is not None:
            at = max(0.0, min(at, float(self.duration) - _MIN_CARD_MS / 1000))
        # Before anything changes: a reference the store refuses is no edit.
        reference = _range_card(surah_num, from_ayah, to_ayah, db_path)
        cards = self.project.cards
        at_ms = round(at * 1000)

        # (distance, shorter than half a second, index) of each card *at* lands on: at
        # equal distance a card that lasts is changed rather than one that would flash.
        nearby: list[tuple[int, bool, int]] = []
        for i, card in enumerate(cards):
            start = _ms(card.get("start_time"))
            if start is None:
                continue
            after = at_ms - start  # how far into the card *at* falls
            end = _ms(card.get("end_time"))
            inside = end is not None and 0 < after < _MIN_CARD_MS and at_ms < end
            if abs(after) <= _SAME_START_MS or inside or -_MIN_CARD_MS < after < 0:
                short = end is None or end - start < _MIN_CARD_MS
                nearby.append((abs(after), short, i))
        if nearby:
            index = min(nearby)[2]
            self._replace_card(index, _changed_card(cards[index], reference))
            return index

        following = [
            start
            for start in (_ms(card.get("start_time")) for card in cards)
            if start is not None and start > at_ms
        ]
        if following:
            end_ms = min(following)  # at least half a second away (see above)
        elif self.duration is not None:
            end_ms = max(round(float(self.duration) * 1000), at_ms + _MIN_CARD_MS)
        else:
            end_ms = at_ms + 10_000
        new = {
            **reference,
            "start_time": at_ms / 1000,
            "end_time": end_ms / 1000,
            "confidence": 1.0,
            "detected_text": "",
            "manual": True,
        }
        updated = []
        for card in cards:
            start, end = _ms(card.get("start_time")), _ms(card.get("end_time"))
            if start is not None and end is not None and start < at_ms < end:
                card = {**card, "end_time": at_ms / 1000}  # half a second or more (see above)
            updated.append(card)
        updated.append(new)
        updated.sort(key=lambda card: _ms(card.get("start_time")) or 0)

        self._before_change()
        self.project.cards = updated
        self._changed()
        return next(i for i, card in enumerate(updated) if card is new)

    def change_card_ayah(
        self,
        index: int,
        surah_num: int,
        from_ayah: int,
        to_ayah: int,
        *,
        db_path: Path = QURAN_DB_PATH,
    ) -> None:
        """Make card *index* show ayat *from_ayah*–*to_ayah* of *surah_num*; one undo step.

        The card stays where it is on the timeline: the person is correcting
        which ayat the teacher meant (detection follows recitation, and a
        teacher who goes back to an earlier ayah is easily matched to the
        wrong one), not when it shows. What detection said about the old
        reference — the heard text, its word timings, its match scores — no
        longer describes the card and goes; the card is then the person's.

        Raises ``IndexError`` for an index that is not a card (a negative one
        included: it would silently change a card from the end), and
        ``ValueError`` as :meth:`insert_manual_card` does; then nothing changed
        and there is nothing to undo.
        """
        self._require_lecture()
        if not 0 <= index < len(self.project.cards):
            raise IndexError(f"No card {index}; the project has {len(self.project.cards)}.")
        card = self.project.cards[index]
        reference = _range_card(surah_num, from_ayah, to_ayah, db_path)
        self._replace_card(index, _changed_card(card, reference))

    def _require_lecture(self) -> None:
        """Refuse a hand-made card outside a lecture: a recitation's cards tile its words."""
        if str(self.project.mode).lower() != "lecture":
            raise ValueError(t("session.manual_lecture_only"))

    def _replace_card(self, index: int, new: dict[str, Any]) -> None:
        """Put *new* in place of card *index* as one undo step; no step when nothing differs."""
        if new == self.project.cards[index]:
            return
        self._before_change()
        self.project.cards[index] = new
        self._changed()

    def remove_caption(self, index: int) -> None:
        self._before_change()
        del self.project.captions[index]
        self._changed()

    def mark_reviewed(self) -> None:
        self._before_change()
        self.project.mark_reviewed()
        self._changed()

    def set_look(self, look: Look) -> None:
        """Choose *look*; one undo step, or one per gesture while a slider is dragged."""
        if look == self.look:
            return
        self._before_change()
        set_project_look(self.project, look)
        self._changed()

    @property
    def studied_surah(self) -> int | None:
        """The surah a lecture's cards keep to; None while it is guessed."""
        return _studied_surah(self.project)

    @property
    def guessed_studied_surah(self) -> int | None:
        """The surah a lecture's cards keep to while none is chosen, by number; else None.

        The same guess the frame and the export make (``cards_on_screen``); None
        outside a lecture and when no detected card names a surah by number.
        """
        if str(self.project.mode).lower() != "lecture":
            return None
        guess = guessed_studied_surah(self.project.cards)
        return guess if isinstance(guess, int) and not isinstance(guess, bool) else None

    def set_studied_surah(self, surah: int | None) -> None:
        """Choose the surah a lecture's cards keep to (None: guess it); one undo step."""
        surah = studied_surah_choice(surah)
        if surah == self.studied_surah:
            return
        self._before_change()
        _set_studied_surah(self.project, surah)
        self._changed()

    @property
    def episode(self) -> EpisodeChoice:
        """What plays around the lecture: its intro, recitation and outro, resolved."""
        return project_episode(self.project)

    def set_episode(self, choice: EpisodeChoice) -> None:
        """Choose the lecture's intro, recitation and outro; one undo step.

        Nothing happens when *choice* is what the project already holds. The
        clips are expected beside the project already (``import_episode_clip``):
        this only records the paths. Refused (``ValueError``) outside a
        lecture: a recitation is rendered alone.
        """
        if str(self.project.mode).lower() != "lecture":
            raise ValueError(t("session.episode_lecture_only"))

        def resolved_path(part: Path | None) -> Path | None:
            return None if part is None else Path(part).expanduser().resolve()

        resolved = replace(
            choice,
            intro=resolved_path(choice.intro),
            recitation=resolved_path(choice.recitation),
            outro=resolved_path(choice.outro),
            # A name belongs to its clip: none for a part not chosen.
            intro_name=choice.intro_name if choice.intro is not None else None,
            outro_name=choice.outro_name if choice.outro is not None else None,
        )
        if resolved == self.episode:
            return
        self._before_change()
        set_project_episode(self.project, resolved)
        self._changed()

    @property
    def missing_studied_surah(self) -> int | None:
        """The chosen studied surah when no card the frame draws is one of its ayat.

        The video then shows only its opening title card, which the window
        says rather than leave the person looking for the ayat. Judged on the
        cards the frame draws (``validated_cards``), so a card validation drops
        does not hide the warning.
        """
        surah = self.studied_surah
        if surah is None or str(self.project.mode).lower() != "lecture":
            return None
        return None if has_surah_cards(self.validated_cards(), surah) else surah

    # -- gestures and undo -----------------------------------------------------

    def begin_gesture(self) -> None:
        if self._in_gesture:
            return
        self._gesture_start = self._snapshot()
        self._undo.append(self._gesture_start)
        # Set aside, not cleared: a press that never moves is no edit and must
        # leave redo as it was (see end_gesture). Nothing can redo mid-gesture.
        self._gesture_redo, self._redo = self._redo, []
        self._in_gesture = True

    def end_gesture(self) -> None:
        """Close the gesture; one that ends where it began is no edit at all.

        "Where it began" is judged on the settled states (see ``_settled``),
        and then the gesture-start snapshot is put back exactly — windows,
        flags and all — and its undo entry dropped, so the project is not
        dirty and there is nothing to undo; the redo history set aside when it
        began comes back. A gesture that did edit starts a new branch, and the
        redo history goes.
        """
        if not self._in_gesture:
            return
        self._in_gesture = False
        start, self._gesture_start = self._gesture_start, None
        redo, self._gesture_redo = self._gesture_redo, []
        if start is None:
            return
        if not self._settles_to(start):
            # A real edit; but one that undid the edits before it is the saved state.
            if self._settle():
                self._changed()
            return
        if self._undo and self._undo[-1] is start:
            self._undo.pop()
        self._redo = redo
        if not self._is_exactly(start):
            self._restore(start)
            self._changed()

    def _settle(self, ref: WordRef | None = None) -> bool:
        """Outside a gesture, an edit that lands back on the saved state *is* the saved state.

        A nudge and its opposite (or a ripple and its opposite) put every
        time back, but each marked the words it moved as ``edited`` and
        re-derived the card windows, so the project would read as unsaved
        with nothing to save. When the settled states match (see
        ``_settled``), the saved snapshot is put back exactly. Undo keeps its
        entries: stepping back through the nudges is still possible. Returns
        whether anything was put back.

        *ref*, the word just edited, makes the usual case cheap: while that
        word is away from its saved times the states cannot match, and the
        whole-project comparison (a few milliseconds per thousand words) is
        skipped.
        """
        if self._in_gesture:
            return False
        if ref is not None and not self._at_saved_times(ref):
            return False
        if not self._settles_to(self._saved_snapshot):
            return False
        if self._is_exactly(self._saved_snapshot):
            return False
        self._restore(self._saved_snapshot)
        return True

    def _settles_to(self, snapshot: tuple) -> bool:
        """Whether the current state is *snapshot* once both are settled."""
        current = (
            self.project.cards,
            self.project.captions,
            self.project.review,
            self.project.style,
            _studied_surah(self.project),
            self.project.episode,
        )
        return _settled(*current) == _settled(*snapshot)

    def _at_saved_times(self, ref: WordRef) -> bool:
        """Whether *ref* sits where the saved state has the word at its position.

        False also when the saved state has no word there: then the two states
        differ in shape and cannot settle to each other anyway.
        """
        cards, captions, _review, _style, _studied, _episode = self._saved_snapshot
        if ref.kind == CARD:
            segments = [card.get("word_timings") or [] for card in cards]
        else:
            segments = [cue.words for cue in captions]
        if ref.segment >= len(segments) or ref.word >= len(segments[ref.segment]):
            return False
        saved = segments[ref.segment][ref.word]
        now = self._raw_words(ref)[ref.word]
        return all(round(float(saved[k]), 3) == round(float(now[k]), 3) for k in ("start", "end"))

    def _is_exactly(self, snapshot: tuple) -> bool:
        cards, captions, review, style, studied, episode = snapshot
        return (
            cards == self.project.cards
            and captions == self.project.captions
            and review == self.project.review
            and style == self.project.style
            and studied == _studied_surah(self.project)
            and episode == self.project.episode
        )

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
            raise ValueError(t("session.no_file"))
        path = save_project(self.project, self.project.path)
        self._saved_key = self._key()
        self._saved_snapshot = self._snapshot()
        return path

    def revert(self) -> None:
        """Put back the state as loaded or last saved: what "discard" means.

        The undo and redo history goes too. Every step in it leads back into
        the changes the person just chose to throw away, so keeping it would
        let one Ctrl+Z quietly resurrect them.
        """
        self._in_gesture = False
        self._gesture_start = None
        self._gesture_redo = []
        self._undo.clear()
        self._redo.clear()
        self._restore(self._saved_snapshot)
        self._changed()

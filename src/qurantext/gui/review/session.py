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
    kind: str
    segment: int
    word: int


@dataclass(frozen=True, slots=True)
class TimelineWord:
    ref: WordRef
    text: str
    start: float
    end: float
    edited: bool


def _normalized_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    return [
        {key: value for key, value in word.items() if key != "edited"}
        for word in _normalized_words(words)
    ]


def _studied_surah(project: Project) -> int | None:
    return studied_surah_choice(project.export.get("studied_surah"))


def _set_studied_surah(project: Project, surah: int | None) -> None:
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


_MIN_CARD_MS = 500
_SAME_START_MS = 50


def _range_card(surah_num: int, from_ayah: int, to_ayah: int, db_path: Path) -> dict[str, Any]:
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
            raise ValueError(t("session.manual_store_unavailable", details=exc)) from exc
        raise ValueError(
            t("session.manual_bad_reference", surah=surah_num, first=from_ayah, last=to_ayah)
        ) from exc
    finally:
        conn.close()


def _in_surah(conn: sqlite3.Connection, surah_num: Any, from_ayah: Any, to_ayah: Any) -> bool:
    numbers = (surah_num, from_ayah, to_ayah)
    if any(isinstance(n, bool) or not isinstance(n, int) for n in numbers):
        return False
    try:
        count = surah_ayah_count(conn, surah_num)
    except (ValueError, sqlite3.Error):
        return False
    return 1 <= from_ayah <= to_ayah <= count


def _ms(value: Any) -> int | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return round(seconds * 1000) if math.isfinite(seconds) else None


def _changed_card(card: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    new = {
        key: value
        for key, value in card.items()
        if key != "word_timings" and not key.startswith(("_matched", "matched"))
    }
    new.update(reference)
    new.update(detected_text="", confidence=1.0, manual=True)
    return new


class ReviewSession:
    def __init__(self, project: Project, *, duration: float | None = None) -> None:
        self.project = project
        self.duration = duration
        self._undo: list[tuple] = []
        self._redo: list[tuple] = []
        self._in_gesture = False
        self._gesture_start: tuple | None = None
        self._gesture_redo: list[tuple] = []
        self._revision = 0
        self._look_cache: tuple[int, Look] | None = None
        self._saved_key = self._key()
        self._saved_snapshot = self._snapshot()
        self._validated: tuple[int, list[dict[str, Any]]] | None = None
        self._caption_track: tuple[int, CaptionTrack] | None = None
        self._words_revision: int | None = None
        self._words_by_kind: dict[str, list[TimelineWord]] = {}
        self._starts_by_kind: dict[str, list[float]] = {}
        self._position_by_kind: dict[str, dict[WordRef, int]] = {}
        self._max_len_by_kind: dict[str, float] = {}

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
        if self._look_cache is None or self._look_cache[0] != self._revision:
            self._look_cache = (self._revision, project_look(self.project))
        return self._look_cache[1]

    def _key(self) -> str:
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

    def words(self, kind: str | None = None) -> list[TimelineWord]:
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
        if self._caption_track is None or self._caption_track[0] != self._revision:
            spans = [(cue.start, cue.end) for cue in self.project.captions]
            self._caption_track = (self._revision, CaptionTrack(spans))
        return self._caption_track[1].index_at(t)

    def retimed_count(self, kind: str, segment: int) -> int:
        return count_edited(self._raw_words(WordRef(kind, segment, 0)))

    def coverage_words(self) -> list[dict[str, float]]:
        return [{"start": tw.start, "end": tw.end} for tw in self.words()]

    def validated_cards(self) -> list[dict[str, Any]]:
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
        active = [card for card in self.validated_cards() if float(card["_start_time"]) <= t]
        index = self.caption_at(t)
        caption = self._caption_segment(index) if index is not None else None
        band = bool(self.project.captions) and job_settings(self.project).subtitles != "sidecar"
        return (active[-1] if active else None), caption, band

    def _caption_segment(self, index: int) -> dict[str, Any]:
        cue = self.project.captions[index]
        return {
            "text": cue.text,
            "start": float(cue.start),
            "end": float(cue.end),
            "word_timings": list(cue.words),
        }

    def retime(
        self,
        ref: WordRef,
        *,
        start: float | None = None,
        end: float | None = None,
        keep_joined: bool = True,
    ) -> None:
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
        self._restore_gesture_start()
        self.retime(ref, start=start, end=end, keep_joined=keep_joined)

    def drag_ripple(self, ref: WordRef, total_delta: float) -> None:
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
        self._before_change()
        del self.project.cards[index]
        if self.project.mode == "recitation":
            self.project.cards = derive_card_windows(self.project.cards)
        self._changed()

    def is_manual(self, index: int) -> bool:
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
        self._require_lecture()
        at = max(0.0, float(at))
        if self.duration is not None:
            at = max(0.0, min(at, float(self.duration) - _MIN_CARD_MS / 1000))
        reference = _range_card(surah_num, from_ayah, to_ayah, db_path)
        cards = self.project.cards
        at_ms = round(at * 1000)

        nearby: list[tuple[int, bool, int]] = []
        for i, card in enumerate(cards):
            start = _ms(card.get("start_time"))
            if start is None:
                continue
            after = at_ms - start
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
            end_ms = min(following)
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
                card = {**card, "end_time": at_ms / 1000}
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
        self._require_lecture()
        if not 0 <= index < len(self.project.cards):
            raise IndexError(f"No card {index}; the project has {len(self.project.cards)}.")
        card = self.project.cards[index]
        reference = _range_card(surah_num, from_ayah, to_ayah, db_path)
        self._replace_card(index, _changed_card(card, reference))

    def _require_lecture(self) -> None:
        if str(self.project.mode).lower() != "lecture":
            raise ValueError(t("session.manual_lecture_only"))

    def _replace_card(self, index: int, new: dict[str, Any]) -> None:
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
        if look == self.look:
            return
        self._before_change()
        set_project_look(self.project, look)
        self._changed()

    @property
    def studied_surah(self) -> int | None:
        return _studied_surah(self.project)

    @property
    def guessed_studied_surah(self) -> int | None:
        if str(self.project.mode).lower() != "lecture":
            return None
        guess = guessed_studied_surah(self.project.cards)
        return guess if isinstance(guess, int) and not isinstance(guess, bool) else None

    def set_studied_surah(self, surah: int | None) -> None:
        surah = studied_surah_choice(surah)
        if surah == self.studied_surah:
            return
        self._before_change()
        _set_studied_surah(self.project, surah)
        self._changed()

    @property
    def episode(self) -> EpisodeChoice:
        return project_episode(self.project)

    def set_episode(self, choice: EpisodeChoice) -> None:
        if str(self.project.mode).lower() != "lecture":
            raise ValueError(t("session.episode_lecture_only"))

        def resolved_path(part: Path | None) -> Path | None:
            return None if part is None else Path(part).expanduser().resolve()

        resolved = replace(
            choice,
            intro=resolved_path(choice.intro),
            recitation=resolved_path(choice.recitation),
            outro=resolved_path(choice.outro),
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
        surah = self.studied_surah
        if surah is None or str(self.project.mode).lower() != "lecture":
            return None
        return None if has_surah_cards(self.validated_cards(), surah) else surah

    def begin_gesture(self) -> None:
        if self._in_gesture:
            return
        self._gesture_start = self._snapshot()
        self._undo.append(self._gesture_start)
        self._gesture_redo, self._redo = self._redo, []
        self._in_gesture = True

    def end_gesture(self) -> None:
        if not self._in_gesture:
            return
        self._in_gesture = False
        start, self._gesture_start = self._gesture_start, None
        redo, self._gesture_redo = self._gesture_redo, []
        if start is None:
            return
        if not self._settles_to(start):
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

    def save(self) -> Path:
        if self.project.path is None:
            raise ValueError(t("session.no_file"))
        path = save_project(self.project, self.project.path)
        self._saved_key = self._key()
        self._saved_snapshot = self._snapshot()
        return path

    def revert(self) -> None:
        self._in_gesture = False
        self._gesture_start = None
        self._gesture_redo = []
        self._undo.clear()
        self._redo.clear()
        self._restore(self._saved_snapshot)
        self._changed()

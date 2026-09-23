# Review editor — Phase 1: foundations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the project file the thing that is rendered and exported (cards and captions), add the pure timing-edit model, split matching from rendering, list jobs, and compute waveform peaks — everything the review editor (Phase 2) stands on, with no UI.

**Architecture:** `jobs/project.py` grows to v2 (matches path, review state, render record, unknown-key preservation). A pure `core/timing_edit.py` owns every timing rule. `RenderRequest`/`ExportRequest`/`build_cues` accept a `cards` override, and a new `jobs/project_render.py` is the single route from a project to a video and subtitle files, used by the GUI job layer and the CLI. `jobs/catalog.py` lists projects; `core/waveform.py` streams min/max peaks from FFmpeg.

**Tech Stack:** Python 3.10+, numpy, FFmpeg (subprocess), pytest. No Qt in this phase.

**Spec:** `docs/superpowers/specs/2026-09-23-review-editor-design.md` (sections 1.1–1.6, and 6 for tests).

## Global Constraints

- Python 3.10+; code must pass `ruff check` and `ruff format --check` with the pinned `ruff==0.15.13`.
- `core/` must not import from `jobs/` or `gui/`.
- Quran text is never edited: cards change reference/timing only.
- Times are seconds as floats, rounded to 3 decimals when written.
- Match the house style: module docstrings that say *why*, `from __future__ import annotations`, `__all__`, frozen `slots=True` dataclasses for requests/results.
- Run tests with: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q`
- Every commit message ends with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Commit subjects follow the repo's style: a plain sentence saying what changed and why, e.g. "Render the project's cards, not the match file's".

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `src/qurantext/jobs/project.py` | modify | v2 fields, content hash, render record, review state, unknown keys, caption edits keep timings |
| `src/qurantext/core/timing_edit.py` | create | `retime`, `ripple`, `derive_card_windows`, `count_edited` |
| `src/qurantext/jobs/render.py` | modify | `RenderRequest.cards` override |
| `src/qurantext/jobs/export.py` | modify | `ExportRequest.cards`, `build_cues(cards=)` |
| `src/qurantext/jobs/project_render.py` | create | `render_project`, `export_project_subtitles` |
| `src/qurantext/cli/main.py` | modify | `generate-video --project` goes through `render_project` |
| `src/qurantext/gui/jobs.py` | modify | `run_matching`, `run_render`, `run_job` kept as wrapper |
| `src/qurantext/jobs/catalog.py` | create | `list_jobs`, `JobEntry`, `job_status` |
| `src/qurantext/services/transcript_cache.py` | modify | `_audio_digest` → public `audio_digest` |
| `src/qurantext/core/waveform.py` | create | `Peaks`, `compute_peaks`, `load_or_compute_peaks` |
| tests | create/modify | `test_project.py`, `test_timing_edit.py`, `test_export.py`, `test_project_render.py`, `test_gui.py`, `test_catalog.py`, `test_waveform.py` |

---

### Task 1: Project file v2

**Files:**
- Modify: `src/qurantext/jobs/project.py`
- Test: `tests/test_project.py`

**Interfaces:**
- Produces:
  - `PROJECT_VERSION = "2"`; `SUPPORTED_VERSIONS = ("1", "2")`
  - `REVIEW_STATES = ("needs_review", "reviewed")`
  - `Project` new fields: `matches: Path | None = None`, `review: dict[str, Any]` (default `{"state": "needs_review", "reviewed_at": None}`), `render: dict[str, Any] | None = None`, `extra: dict[str, Any]` (unknown top-level keys)
  - `Project.content_hash() -> str`
  - `Project.record_render(video: Path, *, preset: str | None, basmala_offset_s: float, when: datetime | None = None) -> None`
  - `Project.render_is_stale -> bool` (property)
  - `Project.mark_reviewed(when: datetime | None = None) -> None`
  - `CaptionCue.edited(text)` keeps word timings (relabelled) when the word count is unchanged
  - `Project.from_match_file` sets `matches`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_project.py`, and replace `test_editing_text_drops_word_timings_that_no_longer_match` (its "original"→"rewritten" edit keeps the word count, so under the new rule the timing survives):

```python
def test_editing_text_keeps_word_timings_when_the_word_count_is_unchanged() -> None:
    cue = CaptionCue(
        0.0,
        2.0,
        "one two",
        words=[{"word": "one", "start": 0.0, "end": 1.0}, {"word": "two", "start": 1.0, "end": 2.0}],
    )
    assert cue.edited("one two") is cue

    fixed = cue.edited("one too")
    assert fixed.text == "one too"
    assert [w["word"] for w in fixed.words] == ["one", "too"]
    assert [w["start"] for w in fixed.words] == [0.0, 1.0]
    assert cue.words[1]["word"] == "two", "the original cue must not be mutated"


def test_editing_text_drops_word_timings_when_the_word_count_changes() -> None:
    cue = CaptionCue(0.0, 1.0, "original", words=[{"word": "original", "start": 0.0, "end": 1.0}])
    changed = cue.edited("two words")
    assert changed.words == []
    assert cue.words


def test_version_one_files_load_and_are_written_back_as_version_two(tmp_path) -> None:
    path = tmp_path / "job.qalun.json"
    path.write_text(
        json.dumps({"project_version": "1", "audio": "a.mp3", "mode": "lecture", "cards": []}),
        encoding="utf-8",
    )
    project = load_project(path)
    assert project.matches is None
    assert project.review["state"] == "needs_review"
    assert project.render is None
    save_project(project, path)
    assert json.loads(path.read_text(encoding="utf-8"))["project_version"] == "2"


def test_unknown_top_level_keys_survive_a_round_trip(tmp_path) -> None:
    path = tmp_path / "job.qalun.json"
    save_project(_project(tmp_path), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["written_by_a_newer_build"] = {"keep": True}
    path.write_text(json.dumps(data), encoding="utf-8")

    save_project(load_project(path), path)
    assert json.loads(path.read_text(encoding="utf-8"))["written_by_a_newer_build"] == {"keep": True}


def test_from_match_file_remembers_the_match_file(tmp_path) -> None:
    matches = tmp_path / "m.json"
    matches.write_text(json.dumps(_match_payload(), ensure_ascii=False), encoding="utf-8")
    project = Project.from_match_file(matches, tmp_path / "dars.mp3")
    assert project.matches == matches.resolve()

    path = save_project(project, tmp_path / "job.qalun.json")
    assert json.loads(path.read_text(encoding="utf-8"))["matches"] == "m.json"
    assert load_project(path).matches == matches.resolve()


def test_a_render_is_stale_only_after_the_content_changes(tmp_path) -> None:
    project = _project(tmp_path)
    assert project.render_is_stale is False

    project.record_render(tmp_path / "v.mp4", preset="social", basmala_offset_s=3.25)
    assert project.render["basmala_offset_s"] == 3.25
    assert project.render_is_stale is False

    path = save_project(project, tmp_path / "job.qalun.json")
    reloaded = load_project(path)
    assert reloaded.render_is_stale is False, "saving right after a render is not a change"
    assert reloaded.render["video"] == (tmp_path / "v.mp4").resolve()

    reloaded.cards[0]["start_time"] = 0.5
    assert reloaded.render_is_stale is True


def test_mark_reviewed_records_state_and_time(tmp_path) -> None:
    from datetime import datetime

    project = _project(tmp_path)
    project.mark_reviewed(datetime(2026, 9, 23, 10, 0, 0))
    assert project.review == {"state": "reviewed", "reviewed_at": "2026-09-23T10:00:00"}
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python -m pytest tests/test_project.py -q`
Expected: FAIL (e.g. `AttributeError: 'Project' object has no attribute 'record_render'`, version "1" written).

- [ ] **Step 3: Implement** in `src/qurantext/jobs/project.py`:

Add imports `hashlib` and `from datetime import datetime`. Update `__all__` with `"REVIEW_STATES"`, `"SUPPORTED_VERSIONS"`.

```python
#: Bumped when the on-disk shape changes incompatibly.
PROJECT_VERSION = "2"
#: Versions this build reads. Version 1 is upgraded on the next save.
SUPPORTED_VERSIONS = ("1", "2")
REVIEW_STATES = ("needs_review", "reviewed")

_KNOWN_KEYS = frozenset(
    {"project_version", "audio", "mode", "matches", "cards", "captions",
     "style", "export", "review", "render"}
)


def _default_review() -> dict[str, Any]:
    return {"state": "needs_review", "reviewed_at": None}
```

Replace `CaptionCue.edited`:

```python
    def edited(self, text: str) -> CaptionCue:
        """Return this cue with corrected *text*.

        Fixing a misheard word keeps the word count, so the timings still
        describe the words and are kept, relabelled in order. A rewrite that
        changes the count drops them rather than leave a karaoke highlight
        disagreeing with the line.
        """
        if text == self.text:
            return self
        tokens = text.split()
        if self.words and len(tokens) == len(self.words):
            words = [{**word, "word": token} for word, token in zip(self.words, tokens)]
        else:
            words = []
        return replace(self, text=text, words=words)
```

Add fields to `Project` (before `path`):

```python
    #: The match file this project was derived from. The basmala splice reads
    #: its metadata at render time.
    matches: Path | None = None
    #: ``{"state": "needs_review" | "reviewed", "reviewed_at": iso | None}``.
    review: dict[str, Any] = field(default_factory=_default_review)
    #: The last successful render, or None. See :meth:`record_render`.
    render: dict[str, Any] | None = None
    #: Top-level keys this build does not know, written back untouched.
    extra: dict[str, Any] = field(default_factory=dict)
```

In `from_match_file`, pass `matches=matches_path` to `cls(...)`.

Add methods:

```python
    def content_hash(self) -> str:
        """A digest of what a render depends on: the cards and the captions."""
        payload = json.dumps(
            {"cards": self.cards, "captions": [cue.to_dict() for cue in self.captions]},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def record_render(
        self,
        video: Path,
        *,
        preset: str | None,
        basmala_offset_s: float,
        when: datetime | None = None,
    ) -> None:
        """Remember a successful render and the content it was made from."""
        self.render = {
            "video": Path(video).expanduser().resolve(),
            "preset": preset,
            "basmala_offset_s": round(float(basmala_offset_s), 3),
            "rendered_at": (when or datetime.now()).isoformat(timespec="seconds"),
            "content_hash": self.content_hash(),
        }

    @property
    def render_is_stale(self) -> bool:
        """True when the cards or captions changed after the last render."""
        return self.render is not None and self.render.get("content_hash") != self.content_hash()

    def mark_reviewed(self, when: datetime | None = None) -> None:
        self.review = {
            "state": "reviewed",
            "reviewed_at": (when or datetime.now()).isoformat(timespec="seconds"),
        }
```

Replace `to_dict`:

```python
    def to_dict(self, *, relative_to: Path | None = None) -> dict[str, Any]:
        data: dict[str, Any] = dict(self.extra)
        render = None
        if self.render is not None:
            render = dict(self.render)
            if render.get("video"):
                render["video"] = _store_path(Path(render["video"]), relative_to)
        data.update(
            {
                "project_version": PROJECT_VERSION,
                "audio": _store_path(self.audio, relative_to),
                "matches": _store_path(self.matches, relative_to) if self.matches else None,
                "mode": self.mode,
                "cards": self.cards,
                "captions": [cue.to_dict() for cue in self.captions],
                "style": self.style,
                "export": self.export,
                "review": self.review,
                "render": render,
            }
        )
        return data
```

Replace `from_dict`:

```python
    @classmethod
    def from_dict(cls, data: dict[str, Any], *, base_dir: Path | None = None) -> Project:
        version = str(data.get("project_version") or "")
        if version and version not in SUPPORTED_VERSIONS:
            raise ValueError(
                f"Project file version {version!r} is not supported by this build "
                f"(expected one of {', '.join(SUPPORTED_VERSIONS)})."
            )
        render = data.get("render")
        if isinstance(render, dict):
            render = dict(render)
            if render.get("video"):
                render["video"] = _resolve_path(str(render["video"]), base_dir)
        else:
            render = None
        review = data.get("review")
        return cls(
            audio=_resolve_path(str(data["audio"]), base_dir),
            mode=str(data.get("mode") or "recitation"),
            cards=list(data.get("cards") or []),
            captions=[CaptionCue.from_dict(cue) for cue in (data.get("captions") or [])],
            style=dict(data.get("style") or {}),
            export=dict(data.get("export") or {}),
            matches=_resolve_path(str(data["matches"]), base_dir) if data.get("matches") else None,
            review=dict(review) if isinstance(review, dict) else _default_review(),
            render=render,
            extra={k: v for k, v in data.items() if k not in _KNOWN_KEYS},
        )
```

Note: `content_hash` must hash cards exactly as they will be after a JSON round-trip, which is why `record_render` is called with in-memory data that is already JSON-shaped (dicts, lists, floats). The staleness test above guards this.

- [ ] **Step 4: Run to verify they pass**

Run: `venv/bin/python -m pytest tests/test_project.py tests/test_editor.py -q`
Expected: PASS. If `test_editor.py` asserted the old "text edit drops words" behaviour for a same-count edit, update that assertion to the new rule (same count keeps relabelled timings) — nothing else in it should change.

- [ ] **Step 5: Commit**

```bash
git add src/qurantext/jobs/project.py tests/test_project.py tests/test_editor.py
git commit -m "Give the project its match file, review state and last render

A caption fix that keeps the word count now keeps its word timings, and keys
a newer build wrote are carried through instead of dropped.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The timing-edit model

**Files:**
- Create: `src/qurantext/core/timing_edit.py`
- Test: `tests/test_timing_edit.py`

**Interfaces:**
- Produces (all pure, all return new lists, inputs never mutated):
  - `MIN_WORD_S = 0.04`
  - `retime(words: list[dict], index: int, *, start: float | None = None, end: float | None = None) -> list[dict]`
  - `ripple(words: list[dict], index: int, delta: float, *, duration: float | None = None) -> list[dict]`
  - `derive_card_windows(cards: list[dict]) -> list[dict]`
  - `count_edited(words: list[dict]) -> int`
- Word dicts are `{"word": str, "start": float, "end": float}` plus optional `"edited": True`, which these functions set on every word whose times they change.

Rules (from spec 1.2, made exact):
- **retime, start:** new start is clamped to `[prev.start + MIN_WORD_S (or 0.0 with no prev), word.end - MIN_WORD_S]`. If the previous word's end is later than the new start, the previous word's end becomes the new start (it is trimmed, never reordered).
- **retime, end:** applied after start. New end is clamped to `[word.start + MIN_WORD_S, next.end - MIN_WORD_S (or +inf with no next)]`. If the next word's start is earlier than the new end, the next word's start becomes the new end.
- **ripple:** shifts word *index* and every later word by *delta*. *delta* is clamped so the moved word's start stays `>= prev.start + MIN_WORD_S` (or `>= 0.0`), and, if *duration* is given, so the last word's end stays `<= duration`. If the previous word's end is later than the moved word's new start, it is trimmed to it.
- **derive_card_windows:** for cards with non-empty `word_timings`, in list order: `start_time` = first word's start; `end_time` = the next timed card's first word start; the last timed card keeps its `end_time` unless its last word ends later, then it becomes that word's end. Cards without word timings are returned unchanged (copied). Meant for recitation projects.
- All written times are rounded to 3 decimals.

- [ ] **Step 1: Write the failing tests** — `tests/test_timing_edit.py`:

```python
"""The rules every timing edit obeys, kept out of the widgets.

A reviewer drags, nudges and ripples; these are what stop an edit from making
two words overlap, swap order, or leave a card window disagreeing with its words.
"""

from __future__ import annotations

import pytest

from qurantext.core.timing_edit import (
    MIN_WORD_S,
    count_edited,
    derive_card_windows,
    retime,
    ripple,
)


def _words(*spans):
    return [{"word": f"w{i}", "start": s, "end": e} for i, (s, e) in enumerate(spans)]


def test_retime_moves_one_word_and_marks_it_edited() -> None:
    words = _words((0.0, 1.0), (1.0, 2.0), (2.0, 3.0))
    out = retime(words, 1, start=1.2, end=1.8)
    assert (out[1]["start"], out[1]["end"]) == (1.2, 1.8)
    assert out[1]["edited"] is True
    assert "edited" not in out[0] and "edited" not in out[2]
    assert words[1]["start"] == 1.0, "input must not be mutated"


def test_retime_start_earlier_trims_the_previous_word_instead_of_overlapping() -> None:
    out = retime(_words((0.0, 1.0), (1.0, 2.0)), 1, start=0.6)
    assert out[1]["start"] == 0.6
    assert out[0]["end"] == 0.6
    assert out[0]["edited"] is True


def test_retime_start_cannot_pass_the_previous_word_start() -> None:
    out = retime(_words((0.5, 1.0), (1.0, 2.0)), 1, start=0.1)
    assert out[1]["start"] == pytest.approx(0.5 + MIN_WORD_S)
    assert out[0]["end"] == pytest.approx(0.5 + MIN_WORD_S)


def test_retime_end_later_pushes_the_next_word_start() -> None:
    out = retime(_words((0.0, 1.0), (1.0, 2.0)), 0, end=1.4)
    assert out[0]["end"] == 1.4
    assert out[1]["start"] == 1.4


def test_retime_end_cannot_pass_the_next_word_end() -> None:
    out = retime(_words((0.0, 1.0), (1.0, 2.0)), 0, end=9.0)
    assert out[0]["end"] == pytest.approx(2.0 - MIN_WORD_S)


def test_retime_keeps_a_minimum_length() -> None:
    out = retime(_words((0.0, 1.0)), 0, start=5.0)
    assert out[0]["start"] == pytest.approx(1.0 - MIN_WORD_S)
    out = retime(_words((0.0, 1.0)), 0, end=-3.0)
    assert out[0]["end"] == pytest.approx(MIN_WORD_S)


def test_the_first_word_cannot_start_before_zero() -> None:
    out = retime(_words((0.5, 1.0)), 0, start=-2.0)
    assert out[0]["start"] == 0.0


def test_ripple_shifts_the_word_and_everything_after_it() -> None:
    words = _words((0.0, 1.0), (1.0, 2.0), (6.0, 7.0), (7.0, 8.0))
    out = ripple(words, 2, -3.5)
    assert [(w["start"], w["end"]) for w in out] == [
        (0.0, 1.0),
        (1.0, 2.0),
        (2.5, 3.5),
        (3.5, 4.5),
    ]
    assert [bool(w.get("edited")) for w in out] == [False, False, True, True]


def test_ripple_is_clamped_by_the_previous_word_and_trims_it() -> None:
    out = ripple(_words((0.0, 2.0), (3.0, 4.0)), 1, -10.0)
    assert out[1]["start"] == pytest.approx(MIN_WORD_S)
    assert out[0]["end"] == pytest.approx(MIN_WORD_S)


def test_ripple_does_not_run_past_the_audio() -> None:
    out = ripple(_words((0.0, 1.0), (1.0, 2.0)), 0, 5.0, duration=3.0)
    assert out[-1]["end"] == 3.0
    assert out[0]["start"] == 1.0


def test_card_windows_follow_their_first_words() -> None:
    cards = [
        {"from_ayah": 7, "start_time": 0.0, "end_time": 10.0,
         "word_timings": _words((0.4, 1.0), (1.0, 2.0))},
        {"from_ayah": 8, "start_time": 10.0, "end_time": 20.0,
         "word_timings": _words((12.0, 13.0), (13.0, 25.0))},
    ]
    out = derive_card_windows(cards)
    assert (out[0]["start_time"], out[0]["end_time"]) == (0.4, 12.0)
    assert (out[1]["start_time"], out[1]["end_time"]) == (12.0, 25.0)
    assert cards[0]["start_time"] == 0.0, "input must not be mutated"


def test_the_last_card_keeps_its_end_when_its_words_end_earlier() -> None:
    cards = [{"start_time": 0.0, "end_time": 96.57, "word_timings": _words((0.1, 1.0))}]
    assert derive_card_windows(cards)[0]["end_time"] == 96.57


def test_cards_without_word_timings_are_left_alone() -> None:
    cards = [{"start_time": 3.0, "end_time": 5.0}]
    out = derive_card_windows(cards)
    assert out == cards and out[0] is not cards[0]


def test_count_edited() -> None:
    words = retime(_words((0.0, 1.0), (1.0, 2.0), (2.0, 3.0)), 1, start=1.1)
    assert count_edited(words) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python -m pytest tests/test_timing_edit.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'qurantext.core.timing_edit'`.

- [ ] **Step 3: Implement** `src/qurantext/core/timing_edit.py`:

```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `venv/bin/python -m pytest tests/test_timing_edit.py -q`
Expected: PASS (15 tests).

- [ ] **Step 5: Add the real-recording check** (skips when the local media is absent; it is not in git). Append to `tests/test_timing_edit.py`:

```python
def test_the_25_7_gap_can_be_closed_by_retiming(tmp_path) -> None:
    """The measured 7.5 s hole after نذيرا is something an edit can close.

    This does not claim which timing is right — the prototype could not settle
    that without a listener. It proves the tool can express the fix.
    """
    import shutil
    from pathlib import Path

    from qurantext.core.coverage import find_uncovered_speech
    from qurantext.jobs.project import Project

    audio = Path("input/recitations/furquanTra7-11.mp3")
    matches = Path("output/recitation_matching/furquanTra7-11_recitation.json")
    if not (audio.is_file() and matches.is_file() and shutil.which("ffmpeg")):
        pytest.skip("needs the local furquanTra7-11 recording and its match file")

    project = Project.from_match_file(matches, audio)
    words = project.cards[0]["word_timings"]
    before = find_uncovered_speech(audio, words)
    assert any(g.start < 20.0 < g.end for g in before), "expected the known gap near 16.7–24.2 s"

    last_of_25_7 = next(i for i, w in enumerate(words) if w["end"] >= 16.6)
    following_start = float(words[last_of_25_7 + 1]["start"])
    fixed = retime(words, last_of_25_7, end=following_start)
    after = find_uncovered_speech(audio, fixed)
    assert not any(g.start < 20.0 < g.end for g in after)
```

Run: `venv/bin/python -m pytest tests/test_timing_edit.py -q`
Expected: PASS, or this one test SKIPPED on a machine without the media.

- [ ] **Step 6: Commit**

```bash
git add src/qurantext/core/timing_edit.py tests/test_timing_edit.py
git commit -m "Keep the timing rules in one place the editor can call

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Render and export the cards they are given

**Files:**
- Modify: `src/qurantext/jobs/render.py` (`RenderRequest`, `render_video` where it calls `load_matches(matches_path)`)
- Modify: `src/qurantext/jobs/export.py` (`ExportRequest`, `build_cues`, `export_job`)
- Test: `tests/test_export.py`

**Interfaces:**
- Produces:
  - `RenderRequest.cards: tuple[dict, ...] | None = None` — when not None, `render_video` uses `[dict(c) for c in cards]` instead of `load_matches(matches_path)`; `matches` must still exist on disk (basmala splice reads its meta).
  - `ExportRequest.cards: tuple[dict, ...] | None = None`, forwarded to `RenderRequest.cards` and to `build_cues`.
  - `build_cues(matches_path, duration, *, mode, db_path=QURAN_DB_PATH, captions=None, cards=None) -> list[Cue]`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_export.py`:

```python
def test_build_cues_uses_the_cards_it_is_given(tmp_path, store) -> None:
    _, matches = _job(tmp_path)
    card = json.loads(matches.read_text(encoding="utf-8"))["matches"][0]
    moved = dict(card, start_time=1.5)

    from_file = build_cues(matches, 20.0, mode="recitation", db_path=store)
    from_project = build_cues(matches, 20.0, mode="recitation", db_path=store, cards=(moved,))
    assert from_file[0].start == pytest.approx(0.0)
    assert from_project[0].start == pytest.approx(1.5)


def test_render_uses_the_cards_it_is_given(tmp_path, store, no_basmala, monkeypatch) -> None:
    from qurantext.jobs import render as render_module
    from qurantext.jobs.render import RenderRequest, render_video

    audio, matches = _job(tmp_path)
    seen = {}

    def capture(audio_path, matches_list, output_path, *args, **kwargs):
        seen["cards"] = matches_list
        output_path.write_bytes(b"")
        return 1.0

    monkeypatch.setattr(render_module, "render_frame_video", capture)
    replacement = {"surah_num": 25, "from_ayah": 9, "to_ayah": 9, "start_time": 2.0,
                   "end_time": 3.0, "full_text": "x", "confidence": 1.0}
    render_video(
        RenderRequest(
            audio=audio, matches=matches, output=tmp_path / "v.mp4",
            width=160, height=120, fps=8, font_file=DEFAULT_FONT_PATH,
            cards=(replacement,),
        )
    )
    assert [c["from_ayah"] for c in seen["cards"]] == [9]
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python -m pytest tests/test_export.py -q -k "given"`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'cards'`.

- [ ] **Step 3: Implement.**

In `src/qurantext/jobs/render.py`, add to `RenderRequest` after `captions`:

```python
    #: Ayah cards supplied by the caller, usually from a project file. When
    #: given, they are rendered instead of the match file's, which is what lets
    #: a timing correction reach the video. The match file is still read for
    #: its metadata (the basmala splice needs it).
    cards: tuple[dict, ...] | None = None
```

and replace `matches = load_matches(matches_path)` in `render_video` with:

```python
    matches = (
        [dict(card) for card in request.cards]
        if request.cards is not None
        else load_matches(matches_path)
    )
```

In `src/qurantext/jobs/export.py`: add `cards: tuple[dict, ...] | None = None` to `ExportRequest` after `captions` (same comment, one line: "Ayah cards from a project file, used instead of the match file's."). In `export_job`, pass `cards=request.cards` to `RenderRequest(...)` and `cards=request.cards` to `build_cues(...)`. In `build_cues`, add the keyword parameter `cards: tuple[dict, ...] | None = None` and replace `load_matches(matches_path)` inside `validated_matches(...)` with:

```python
            [dict(card) for card in cards] if cards is not None else load_matches(matches_path),
```

Update the `build_cues` docstring with one sentence: "*cards*, when given, replace the match file's cards, so a project's corrected timings are what the subtitles follow."

- [ ] **Step 4: Run to verify they pass**

Run: `venv/bin/python -m pytest tests/test_export.py tests/test_jobs.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/qurantext/jobs/render.py src/qurantext/jobs/export.py tests/test_export.py
git commit -m "Render and subtitle the cards the caller gives, not only the match file's

Card timing edits in a project had no effect: the renderer always re-read the
match file. This is the hook that lets them reach the video.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: One route from a project to a video and subtitle files

**Files:**
- Create: `src/qurantext/jobs/project_render.py`
- Modify: `src/qurantext/cli/main.py` (`_run_generate_video`)
- Test: `tests/test_project_render.py`

**Interfaces:**
- Consumes: `Project` (Task 1: `matches`, `record_render`, `caption_segments`, `path`), `ExportRequest.cards` and `build_cues(cards=)` (Task 3), `save_project`.
- Produces:
  - `SUBTITLE_TIMELINES = ("video", "audio")`
  - `render_project(project: Project, output: Path, *, preset: str | None = None, subtitles: str = "burn", formats: tuple[str, ...] = ("srt",), width=None, height=None, fps=None, font_file: Path | None = None, title: str | None = None, db_path: Path = QURAN_DB_PATH, progress=None, cancel=None) -> ExportResult` — renders from `project.cards` and `project.captions`, then `project.record_render(...)` and, if `project.path` is set, saves.
  - `export_project_subtitles(project: Project, stem: Path, formats: tuple[str, ...], *, timeline: str = "audio", db_path: Path = QURAN_DB_PATH) -> list[Path]` — no render. `"video"` shifts cues by `project.render["basmala_offset_s"]`, and raises `ValueError` when `project.render` is None. ASS size comes from `project.render["preset"]` via `VIDEO_PRESETS` when known, else 1080×1920. Raises `ValueError` when no cue can be built.

- [ ] **Step 1: Write the failing tests** — `tests/test_project_render.py`. Reuse the helpers from `tests/test_export.py` by importing them (they are module-level):

```python
"""A project is what gets rendered and exported, so corrections reach the output."""

from __future__ import annotations

import pytest

from qurantext.config.paths import DEFAULT_FONT_PATH
from qurantext.jobs.project import Project, load_project, save_project
from qurantext.jobs.project_render import export_project_subtitles, render_project
from tests.test_export import _job, no_basmala, pytestmark, store  # noqa: F401


def _project(tmp_path):
    audio, matches = _job(tmp_path)
    project = Project.from_match_file(matches, audio)
    save_project(project, tmp_path / "job.qalun.json")
    return project


def test_render_project_records_the_render_and_saves(tmp_path, store, no_basmala) -> None:
    project = _project(tmp_path)
    result = render_project(
        project, tmp_path / "v.mp4", width=160, height=120, fps=8,
        font_file=DEFAULT_FONT_PATH, db_path=store,
    )
    assert result.video.exists()
    reloaded = load_project(project.path)
    assert reloaded.render["video"] == result.video
    assert reloaded.render_is_stale is False


def test_render_project_follows_the_projects_cards(tmp_path, store, no_basmala) -> None:
    project = _project(tmp_path)
    project.cards[0]["start_time"] = 1.0
    result = render_project(
        project, tmp_path / "v.mp4", subtitles="sidecar", formats=("srt",),
        width=160, height=120, fps=8, font_file=DEFAULT_FONT_PATH, db_path=store,
    )
    srt = result.subtitles[0].read_text(encoding="utf-8-sig")
    assert "00:00:01,000 -->" in srt


def test_export_writes_the_chosen_formats_without_rendering(tmp_path, store) -> None:
    project = _project(tmp_path)
    written = export_project_subtitles(
        project, tmp_path / "out" / "clip", ("srt", "vtt", "ass"), db_path=store
    )
    assert sorted(p.suffix for p in written) == [".ass", ".srt", ".vtt"]
    assert not list(tmp_path.glob("**/*.mp4"))


def test_export_on_the_video_timeline_applies_the_basmala_offset(tmp_path, store) -> None:
    project = _project(tmp_path)
    with pytest.raises(ValueError, match="rendered"):
        export_project_subtitles(project, tmp_path / "a", ("srt",), timeline="video", db_path=store)

    project.record_render(tmp_path / "v.mp4", preset="social", basmala_offset_s=2.0)
    (path,) = export_project_subtitles(
        project, tmp_path / "b", ("srt",), timeline="video", db_path=store
    )
    assert "00:00:02,000 -->" in path.read_text(encoding="utf-8-sig")
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python -m pytest tests/test_project_render.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'qurantext.jobs.project_render'`.

- [ ] **Step 3: Implement** `src/qurantext/jobs/project_render.py`:

```python
"""From a project to the deliverables, by one route.

The window and the command line both render through here, so a correction made
in the editor — a retimed word, a moved card, a fixed caption — is what reaches
the video and the subtitle files, whichever surface started the job.

Exporting subtitles does not render. It needs to know which timeline to use:
the original recording's, or the rendered video's, which starts later when a
basmala was spliced in front. The offset is taken from the project's record of
its last render rather than recomputed, so the files match the video that
actually exists.
"""

from __future__ import annotations

from pathlib import Path

from qurantext.config.paths import QURAN_DB_PATH
from qurantext.config.settings import VIDEO_PRESETS
from qurantext.core.subtitles import Cue, write_subtitles
from qurantext.core.video_common import get_audio_duration
from qurantext.jobs.export import ExportRequest, ExportResult, build_cues, export_job
from qurantext.jobs.project import Project, save_project
from qurantext.utils.progress import CancelToken, ProgressCallback

__all__ = ["SUBTITLE_TIMELINES", "export_project_subtitles", "render_project"]

#: Which clock exported subtitles follow.
SUBTITLE_TIMELINES = ("video", "audio")

_DEFAULT_SIZE = (1080, 1920)


def render_project(
    project: Project,
    output: Path,
    *,
    preset: str | None = None,
    subtitles: str = "burn",
    formats: tuple[str, ...] = ("srt",),
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
    font_file: Path | None = None,
    title: str | None = None,
    db_path: Path = QURAN_DB_PATH,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> ExportResult:
    """Render *project*, remember the render, and save the project if it has a file."""
    if project.matches is None:
        raise ValueError(
            "This project does not record its match file, so it cannot be rendered. "
            "Open it from the job it was made for, or re-run matching."
        )
    result = export_job(
        ExportRequest(
            audio=Path(project.audio),
            matches=Path(project.matches),
            output=Path(output),
            subtitles=subtitles,
            formats=tuple(formats),
            preset=preset,
            width=width,
            height=height,
            fps=fps,
            font_file=font_file,
            title=title,
            db_path=Path(db_path),
            captions=tuple(project.caption_segments()),
            cards=tuple(project.cards),
        ),
        progress=progress,
        cancel=cancel,
    )
    offset = result.render.basmala_offset_seconds if result.render is not None else 0.0
    project.record_render(result.video, preset=preset, basmala_offset_s=offset)
    if project.path is not None:
        save_project(project, project.path)
    return result


def export_project_subtitles(
    project: Project,
    stem: Path,
    formats: tuple[str, ...],
    *,
    timeline: str = "audio",
    db_path: Path = QURAN_DB_PATH,
) -> list[Path]:
    """Write subtitle files for *project* without rendering anything."""
    if timeline not in SUBTITLE_TIMELINES:
        raise ValueError(f"timeline must be one of {', '.join(SUBTITLE_TIMELINES)}.")
    offset = 0.0
    if timeline == "video":
        if project.render is None:
            raise ValueError(
                "There is no rendered video to line the subtitles up with. "
                "Render first, or export on the original recording's timeline."
            )
        offset = float(project.render.get("basmala_offset_s") or 0.0)

    duration = get_audio_duration(Path(project.audio))
    cues = build_cues(
        Path(project.matches) if project.matches else Path(),
        duration,
        mode=project.mode,
        db_path=Path(db_path),
        captions=tuple(project.caption_segments()),
        cards=tuple(project.cards),
    )
    if not cues:
        raise ValueError("No subtitle lines could be built from this project.")
    if offset:
        cues = [Cue(start=c.start + offset, end=c.end + offset, text=c.text, ref=c.ref) for c in cues]

    preset = (project.render or {}).get("preset")
    width, height = VIDEO_PRESETS[preset][:2] if preset in VIDEO_PRESETS else _DEFAULT_SIZE
    stem = Path(stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    return write_subtitles(cues, stem, tuple(formats), width=width, height=height)
```

- [ ] **Step 4: Route the CLI through it.** In `src/qurantext/cli/main.py`, `_run_generate_video`:

  1. After loading the project, let it supply the match file: replace `args.mode = project.mode` block so it also sets `args.matches = args.matches or (str(project.matches) if project.matches else None)`.
  2. In the `else:` branch (the `export_job` call), when `project is not None` call `render_project` instead:

```python
    else:
        if project is not None:
            if args.matches and project.matches is None:
                project.matches = Path(args.matches)
            result = render_project(
                project,
                Path(output_path),
                preset=getattr(args, "preset", None),
                subtitles=subtitles,
                formats=tuple(args.subtitle_format),
                width=args.width,
                height=args.height,
                fps=args.fps,
                font_file=Path(args.font_file) if args.font_file else None,
                title=getattr(args, "title", None),
                progress=ConsoleProgress(),
            )
        else:
            result = export_job(
                ExportRequest(...unchanged, but drop the now-always-None captions= line...),
                progress=ConsoleProgress(),
            )
        for path in result.subtitles:
            print(f"Subtitles saved to: {path}")
```

Keep the existing `ExportRequest(...)` arguments exactly as they are except `captions=` (which is always None on that branch now). Add `from qurantext.jobs.project_render import render_project` to the imports.

- [ ] **Step 5: Run to verify**

Run: `venv/bin/python -m pytest tests/test_project_render.py tests/test_export.py tests/test_project.py -q && venv/bin/python -m qurantext generate-video --help >/dev/null`
Expected: PASS, and `--help` exits 0.

- [ ] **Step 6: Commit**

```bash
git add src/qurantext/jobs/project_render.py src/qurantext/cli/main.py tests/test_project_render.py
git commit -m "Render and export a project by one route, from the window or the command line

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Split matching from rendering in the window's job layer

**Files:**
- Modify: `src/qurantext/gui/jobs.py`
- Test: `tests/test_gui.py`

**Interfaces:**
- Consumes: `Project.from_match_file`, `save_project` (Task 1), `render_project` (Task 4).
- Produces:
  - `project_path_for(match_path: Path) -> Path` → `match_path.with_suffix(".qalun.json")`
  - `run_matching(spec: JobSpec, *, progress=None, cancel=None) -> Project` — runs detection as `run_job` does today, then derives and saves the project. If a project file already exists there, it is first renamed to `<stem>.<YYYYmmddTHHMMSS>.qalun-backup.json` so earlier corrections are never silently lost.
  - `run_render(project: Project, *, preset: str = "social", subtitles: str = "burn", formats: tuple[str, ...] = ("srt",), output_dir: Path | None = None, progress=None, cancel=None) -> JobOutcome`
  - `JobOutcome` gains `project: Path | None = None` and `subtitles: tuple[Path, ...] = ()`
  - `JobSpec` gains `render_right_away: bool = False` (Phase 3 uses it); `run_job` stays, now `run_matching` then, when `spec.render`, `run_render` — so the current window keeps working unchanged.

- [ ] **Step 1: Write the failing tests** — in `tests/test_gui.py`, extend `test_run_job_matches_then_renders` with, after its existing assertions:

```python
    assert outcome.project is not None and outcome.project.exists()
    from qurantext.jobs.project import load_project

    saved = load_project(outcome.project)
    assert saved.render is not None and saved.render["video"] == outcome.video
```

(If the test names its result something other than `outcome`, use that name.) And add:

```python
def test_rematching_keeps_the_earlier_project_as_a_backup(tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.jobs.project import Project

    match_path = tmp_path / "clip_recitation.json"
    match_path.write_text(
        json.dumps({"matches": [], "meta": {"mode": "recitation"}}), encoding="utf-8"
    )
    old = jobs_module.project_path_for(match_path)
    old.write_text('{"project_version": "2", "audio": "a.mp3"}', encoding="utf-8")

    def fake_range(**kwargs):
        return {"matches": []}

    monkeypatch.setattr(jobs_module, "run_recitation_range", fake_range)
    audio = tmp_path / "clip.m4a"
    audio.write_bytes(b"")
    spec = JobSpec(audio=audio, quran=QURAN_FILE, surah_num=1, from_ayah=1, to_ayah=7,
                   output_dir=tmp_path)
    project = jobs_module.run_matching(spec)

    assert isinstance(project, Project) and project.path == old
    backups = list(tmp_path.glob("clip_recitation.*.qalun-backup.json"))
    assert len(backups) == 1
    assert '"audio": "a.mp3"' in backups[0].read_text(encoding="utf-8")
```

- [ ] **Step 2: Run to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_gui.py -q`
Expected: FAIL (`AttributeError: ... 'project_path_for'`, `JobOutcome` has no `project`).

- [ ] **Step 3: Implement** in `src/qurantext/gui/jobs.py`. Update the module docstring's last sentence to say matching and rendering are separate calls so the window can put review between them. Imports: `from datetime import datetime`, `from qurantext.jobs.project import Project, save_project`, `from qurantext.jobs.project_render import render_project`; drop the now-unused `RenderRequest, render_video` import. Update `__all__` to add `"project_path_for", "run_matching", "run_render"`.

```python
@dataclass(frozen=True, slots=True)
class JobOutcome:
    """What a finished job produced, for the window to offer."""

    matches: Path
    video: Path | None
    cards: int
    mode: str
    project: Path | None = None
    subtitles: tuple[Path, ...] = ()


def project_path_for(match_path: Path) -> Path:
    """Where a job's project lives: beside its match file."""
    return Path(match_path).with_suffix(".qalun.json")


def _set_aside(path: Path) -> None:
    """Keep an earlier project instead of overwriting its corrections."""
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        path.rename(path.with_name(f"{path.name.removesuffix('.qalun.json')}.{stamp}.qalun-backup.json"))


def run_matching(
    spec: JobSpec,
    *,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> Project:
    """Find or align the ayat, then write the project the review opens."""
    audio = Path(spec.audio)
    match_dir = Path(
        spec.output_dir
        or (RECITATION_MATCHING_OUTPUT_DIR if spec.mode == "recitation" else LECTURE_MATCHING_OUTPUT_DIR)
    )
    match_path = match_dir / f"{audio.stem}_{spec.mode}.json"

    # (move the existing `if spec.has_stated_range: ... else: ...` detection
    #  block here unchanged; it assigns `result`, which is no longer needed)

    project = Project.from_match_file(match_path, audio, mode=spec.mode)
    destination = project_path_for(match_path)
    _set_aside(destination)
    save_project(project, destination)
    return project


def run_render(
    project: Project,
    *,
    preset: str = "social",
    subtitles: str = "burn",
    formats: tuple[str, ...] = ("srt",),
    output_dir: Path | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> JobOutcome:
    """Render the project — with whatever corrections it now holds."""
    video_dir = Path(output_dir or VIDEOS_OUTPUT_DIR)
    result = render_project(
        project,
        video_dir / f"{Path(project.audio).stem}.mp4",
        preset=preset,
        subtitles=subtitles,
        formats=formats,
        progress=progress,
        cancel=cancel,
    )
    return JobOutcome(
        matches=Path(project.matches),
        video=result.video,
        cards=len(project.cards),
        mode=project.mode,
        project=project.path,
        subtitles=tuple(result.subtitles),
    )


def run_job(
    spec: JobSpec,
    *,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> JobOutcome:
    """Match, then render. Both stages report progress and honour Cancel."""
    project = run_matching(spec, progress=progress, cancel=cancel)
    if not spec.render:
        return JobOutcome(
            matches=Path(project.matches),
            video=None,
            cards=len(project.cards),
            mode=spec.mode,
            project=project.path,
        )
    if cancel is not None:
        cancel.raise_if_cancelled("render")
    return run_render(
        project, preset=spec.preset, output_dir=spec.output_dir, progress=progress, cancel=cancel
    )
```

Add `render_right_away: bool = False` to `JobSpec` after `render`, with the comment `#: Render as soon as matching finishes, skipping review. For jobs you trust.`

- [ ] **Step 4: Run to verify**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_gui.py tests/test_editor.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/qurantext/gui/jobs.py tests/test_gui.py
git commit -m "Write the project when matching ends, and render from it

The window rendered from the match file, so corrections saved in the editor
never reached a video made from the window. Matching and rendering are now
separate calls, which is where the review will go.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: List the jobs

**Files:**
- Create: `src/qurantext/jobs/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `load_project`, `Project.render`, `Project.render_is_stale`, `Project.review` (Task 1).
- Produces:
  - Status constants: `NEEDS_REVIEW = "needs_review"`, `REVIEWED = "reviewed"`, `RENDERED = "rendered"`, `CHANGED_SINCE_RENDER = "changed_since_render"`, `DAMAGED = "damaged"`
  - `@dataclass(frozen=True, slots=True) class JobEntry: project: Path; name: str; mode: str; status: str; modified: float; card_count: int = 0; ayah_range: str | None = None; error: str | None = None`
  - `job_status(project: Project) -> str`
  - `ayah_range(cards: list[dict]) -> str | None` — e.g. `"25:7–11"` (en dash), `"25:77–26:3"` across surahs, `None` when no non-preamble card has a surah.
  - `default_job_dirs() -> list[Path]` → `[RECITATION_MATCHING_OUTPUT_DIR, LECTURE_MATCHING_OUTPUT_DIR]`
  - `list_jobs(dirs: Iterable[Path] | None = None) -> list[JobEntry]`, newest first; `*.qalun.json` only (backups end `.qalun-backup.json` and are excluded by the glob).

- [ ] **Step 1: Write the failing tests** — `tests/test_catalog.py`:

```python
"""The job list: every project the app has made, and what state it is in."""

from __future__ import annotations

import os

from qurantext.jobs.catalog import (
    CHANGED_SINCE_RENDER,
    DAMAGED,
    NEEDS_REVIEW,
    RENDERED,
    REVIEWED,
    ayah_range,
    list_jobs,
)
from qurantext.jobs.project import Project, save_project


def _card(surah, a, b, kind=None):
    card = {"surah_num": surah, "from_ayah": a, "to_ayah": b, "start_time": 0.0, "end_time": 1.0}
    if kind:
        card["kind"] = kind
    return card


def _save(tmp_path, name, **changes):
    project = Project(audio=tmp_path / f"{name}.mp3", mode="recitation", cards=[_card(25, 7, 11)])
    for key, value in changes.items():
        setattr(project, key, value)
    return save_project(project, tmp_path / f"{name}_recitation.qalun.json")


def test_statuses(tmp_path) -> None:
    _save(tmp_path, "fresh")
    reviewed = Project(audio=tmp_path / "r.mp3", cards=[_card(1, 1, 7)])
    reviewed.mark_reviewed()
    save_project(reviewed, tmp_path / "r_recitation.qalun.json")
    rendered = Project(audio=tmp_path / "v.mp3", cards=[_card(1, 1, 7)])
    rendered.record_render(tmp_path / "v.mp4", preset="social", basmala_offset_s=0.0)
    save_project(rendered, tmp_path / "v_recitation.qalun.json")
    changed = Project(audio=tmp_path / "c.mp3", cards=[_card(1, 1, 7)])
    changed.record_render(tmp_path / "c.mp4", preset="social", basmala_offset_s=0.0)
    changed.cards[0]["start_time"] = 0.5
    save_project(changed, tmp_path / "c_recitation.qalun.json")

    by_name = {entry.name: entry.status for entry in list_jobs([tmp_path])}
    assert by_name == {
        "fresh": NEEDS_REVIEW,
        "r": REVIEWED,
        "v": RENDERED,
        "c": CHANGED_SINCE_RENDER,
    }


def test_newest_first_and_backups_are_not_jobs(tmp_path) -> None:
    older = _save(tmp_path, "older")
    newer = _save(tmp_path, "newer")
    os.utime(older, (1_000_000, 1_000_000))
    (tmp_path / "newer_recitation.20260923T101200.qalun-backup.json").write_text("{}")
    assert [entry.name for entry in list_jobs([tmp_path])] == ["newer", "older"]
    assert newer.exists()


def test_a_damaged_file_is_listed_not_skipped(tmp_path) -> None:
    (tmp_path / "broken.qalun.json").write_text("{not json", encoding="utf-8")
    (entry,) = list_jobs([tmp_path])
    assert entry.status == DAMAGED and entry.error


def test_missing_folders_are_fine(tmp_path) -> None:
    assert list_jobs([tmp_path / "nope"]) == []


def test_ayah_range() -> None:
    assert ayah_range([_card(25, 7, 8), _card(25, 9, 11)]) == "25:7–11"
    assert ayah_range([_card(25, 77, 77), _card(26, 1, 3)]) == "25:77–26:3"
    assert ayah_range([_card(None, None, None, kind="preamble"), _card(1, 1, 7)]) == "1:1–7"
    assert ayah_range([]) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python -m pytest tests/test_catalog.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement** `src/qurantext/jobs/catalog.py`:

```python
"""Every job the app has made, and what state each is in.

The home window lists these so a job can be reopened without hunting for files.
The project files are the record; nothing else is kept. A file that cannot be
read is listed as damaged rather than skipped, so a job never silently vanishes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qurantext.config.paths import LECTURE_MATCHING_OUTPUT_DIR, RECITATION_MATCHING_OUTPUT_DIR
from qurantext.jobs.project import Project, load_project

__all__ = [
    "CHANGED_SINCE_RENDER",
    "DAMAGED",
    "NEEDS_REVIEW",
    "RENDERED",
    "REVIEWED",
    "JobEntry",
    "ayah_range",
    "default_job_dirs",
    "job_status",
    "list_jobs",
]

NEEDS_REVIEW = "needs_review"
REVIEWED = "reviewed"
RENDERED = "rendered"
CHANGED_SINCE_RENDER = "changed_since_render"
DAMAGED = "damaged"


@dataclass(frozen=True, slots=True)
class JobEntry:
    """One row of the job list."""

    project: Path
    name: str
    mode: str
    status: str
    modified: float
    card_count: int = 0
    ayah_range: str | None = None
    error: str | None = None


def job_status(project: Project) -> str:
    if project.render is not None:
        return CHANGED_SINCE_RENDER if project.render_is_stale else RENDERED
    return REVIEWED if project.review.get("state") == "reviewed" else NEEDS_REVIEW


def ayah_range(cards: list[dict[str, Any]]) -> str | None:
    """``25:7–11`` for the span the cards cover, or None when none names a surah."""
    ayat = [c for c in cards if c.get("kind") != "preamble" and c.get("surah_num") is not None]
    if not ayat:
        return None
    first, last = ayat[0], ayat[-1]
    s1, a1 = int(first["surah_num"]), int(first["from_ayah"])
    s2, a2 = int(last["surah_num"]), int(last["to_ayah"])
    return f"{s1}:{a1}–{a2}" if s1 == s2 else f"{s1}:{a1}–{s2}:{a2}"


def default_job_dirs() -> list[Path]:
    return [RECITATION_MATCHING_OUTPUT_DIR, LECTURE_MATCHING_OUTPUT_DIR]


def list_jobs(dirs: Iterable[Path] | None = None) -> list[JobEntry]:
    """Projects under *dirs*, newest first."""
    entries: list[JobEntry] = []
    for folder in dirs if dirs is not None else default_job_dirs():
        folder = Path(folder)
        if not folder.is_dir():
            continue
        for path in folder.glob("*.qalun.json"):
            modified = path.stat().st_mtime
            try:
                project = load_project(path)
            except (OSError, ValueError, KeyError, TypeError) as error:
                entries.append(
                    JobEntry(
                        project=path,
                        name=path.name.removesuffix(".qalun.json"),
                        mode="",
                        status=DAMAGED,
                        modified=modified,
                        error=str(error),
                    )
                )
                continue
            entries.append(
                JobEntry(
                    project=path,
                    name=Path(project.audio).stem,
                    mode=project.mode,
                    status=job_status(project),
                    modified=modified,
                    card_count=len(project.cards),
                    ayah_range=ayah_range(project.cards),
                )
            )
    entries.sort(key=lambda entry: entry.modified, reverse=True)
    return entries
```

- [ ] **Step 4: Run to verify they pass**

Run: `venv/bin/python -m pytest tests/test_catalog.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/qurantext/jobs/catalog.py tests/test_catalog.py
git commit -m "List every job and the state it is in

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Waveform peaks

**Files:**
- Modify: `src/qurantext/services/transcript_cache.py` (`_audio_digest` → `audio_digest`)
- Create: `src/qurantext/core/waveform.py`
- Test: `tests/test_waveform.py`

**Interfaces:**
- Produces:
  - `transcript_cache.audio_digest(audio_path: Path) -> str` (public; `cache_key` calls it; add to `__all__`)
  - `@dataclass(frozen=True, slots=True) class Peaks: mins: np.ndarray; maxs: np.ndarray; rate: float; duration: float` — `mins`/`maxs` are float32, one value per bin, `rate` bins per second.
  - `compute_peaks(audio: Path, *, per_second: int = 100, sample_rate: int = 16000, chunk_seconds: float = 10.0) -> Peaks`
  - `load_or_compute_peaks(audio: Path, cache_file: Path, *, per_second: int = 100) -> Peaks` — `.npz` with `mins`, `maxs`, `rate`, `duration`, `digest`; recomputes when the audio's digest differs or the cache is unreadable; a failed cache write is ignored.
- Note: `core/waveform.py` importing `services/transcript_cache` is allowed (`core` must not import `jobs`/`gui`; `services` is fine — but to keep `core` free of network-y modules, move nothing else).

- [ ] **Step 1: Write the failing tests** — `tests/test_waveform.py`:

```python
"""Waveform peaks: enough to draw an hour of audio without holding it in memory."""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from qurantext.core import waveform
from qurantext.core.waveform import compute_peaks, load_or_compute_peaks

_FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(not _FFMPEG, reason="needs ffmpeg")


def _tone(path, seconds=3.0, source="sine=frequency=440:sample_rate=16000"):
    subprocess.run(
        [_FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", source, "-t", str(seconds), str(path)],
        check=True,
    )
    return path


def test_a_tone_gives_one_bin_per_hundredth_with_its_amplitude(tmp_path) -> None:
    peaks = compute_peaks(_tone(tmp_path / "t.wav"))
    assert peaks.rate == 100
    assert len(peaks.maxs) == len(peaks.mins) == 300
    assert peaks.duration == pytest.approx(3.0, abs=0.02)
    assert float(np.median(peaks.maxs)) == pytest.approx(0.125, abs=0.01)
    assert float(np.median(peaks.mins)) == pytest.approx(-0.125, abs=0.01)


def test_silence_is_flat(tmp_path) -> None:
    peaks = compute_peaks(_tone(tmp_path / "s.wav", source="anullsrc=r=16000:cl=mono"))
    assert float(np.abs(peaks.maxs).max()) == 0.0


def test_chunk_size_does_not_change_the_result(tmp_path) -> None:
    audio = _tone(tmp_path / "t.wav", seconds=1.0)
    whole = compute_peaks(audio)
    ragged = compute_peaks(audio, chunk_seconds=0.013)
    np.testing.assert_array_equal(whole.maxs, ragged.maxs)
    np.testing.assert_array_equal(whole.mins, ragged.mins)


def test_the_cache_is_reused_until_the_audio_changes(tmp_path, monkeypatch) -> None:
    audio = _tone(tmp_path / "t.wav", seconds=1.0)
    cache = tmp_path / "t.peaks.npz"
    first = load_or_compute_peaks(audio, cache)
    assert cache.exists()

    calls = []
    real = waveform.compute_peaks
    monkeypatch.setattr(waveform, "compute_peaks", lambda *a, **k: calls.append(1) or real(*a, **k))
    again = load_or_compute_peaks(audio, cache)
    assert calls == []
    np.testing.assert_array_equal(first.maxs, again.maxs)

    _tone(audio, seconds=2.0)
    changed = load_or_compute_peaks(audio, cache)
    assert calls == [1] and len(changed.maxs) == 200


def test_unreadable_audio_says_so(tmp_path) -> None:
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not audio")
    with pytest.raises(RuntimeError, match="FFmpeg"):
        compute_peaks(bad)
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python -m pytest tests/test_waveform.py -q`
Expected: FAIL with `ImportError: cannot import name 'waveform'`.

- [ ] **Step 3: Make the digest public.** In `src/qurantext/services/transcript_cache.py` rename `_audio_digest` to `audio_digest`, give it a one-line docstring ("SHA-256 of the audio file's bytes, read in chunks."), update its call in `cache_key`, and add `"audio_digest"` to `__all__` if the module has one. Run `venv/bin/python -m pytest tests/test_transcript_cache.py -q` → PASS.

- [ ] **Step 4: Implement** `src/qurantext/core/waveform.py`:

```python
"""Waveform peaks for the review editor.

The editor draws the recording so a reviewer can see where speech is and where
a word's timing sits against it. Drawing needs only the loudest and quietest
sample in each hundredth of a second, so the audio is streamed through FFmpeg
and reduced as it arrives: an hour of lecture is about 2.9 MB of peaks, where
decoding it whole would hold about 230 MB.

Peaks are cached beside the project, keyed by the audio's bytes, so reopening a
job does not decode the recording again.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from qurantext.core.video_common import require_binary
from qurantext.services.transcript_cache import audio_digest

__all__ = ["Peaks", "compute_peaks", "load_or_compute_peaks"]


@dataclass(frozen=True, slots=True)
class Peaks:
    """Per-bin minimum and maximum sample, ``rate`` bins per second."""

    mins: np.ndarray
    maxs: np.ndarray
    rate: float
    duration: float


def compute_peaks(
    audio: Path,
    *,
    per_second: int = 100,
    sample_rate: int = 16000,
    chunk_seconds: float = 10.0,
) -> Peaks:
    """Stream *audio* through FFmpeg and keep only min/max per bin."""
    ffmpeg = require_binary("ffmpeg", "Install FFmpeg and try again.")
    hop = sample_rate // per_second
    chunk_bytes = max(4, int(sample_rate * chunk_seconds) * 4)
    process = subprocess.Popen(
        [ffmpeg, "-v", "error", "-i", str(audio), "-ac", "1", "-ar", str(sample_rate),
         "-f", "f32le", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    mins: list[np.ndarray] = []
    maxs: list[np.ndarray] = []
    pending = b""
    carry = np.empty(0, dtype=np.float32)
    total = 0
    assert process.stdout is not None and process.stderr is not None
    while True:
        block = process.stdout.read(chunk_bytes)
        if not block:
            break
        block = pending + block
        usable = len(block) - len(block) % 4
        pending = block[usable:]
        samples = np.concatenate([carry, np.frombuffer(block[:usable], dtype=np.float32)])
        total += usable // 4
        whole = (len(samples) // hop) * hop
        if whole:
            frames = samples[:whole].reshape(-1, hop)
            mins.append(frames.min(axis=1))
            maxs.append(frames.max(axis=1))
        carry = samples[whole:]
    errors = process.stderr.read()
    if process.wait() != 0:
        details = errors.decode("utf-8", "replace").strip()
        raise RuntimeError(f"FFmpeg could not read the audio for the waveform: {details}")
    if len(carry):
        mins.append(np.array([carry.min()], dtype=np.float32))
        maxs.append(np.array([carry.max()], dtype=np.float32))

    empty = np.empty(0, dtype=np.float32)
    return Peaks(
        mins=np.concatenate(mins).astype(np.float32) if mins else empty,
        maxs=np.concatenate(maxs).astype(np.float32) if maxs else empty,
        rate=float(per_second),
        duration=total / sample_rate,
    )


def load_or_compute_peaks(audio: Path, cache_file: Path, *, per_second: int = 100) -> Peaks:
    """Peaks for *audio*, from *cache_file* when it was made from the same bytes."""
    digest = audio_digest(Path(audio))
    try:
        with np.load(cache_file) as cached:
            if str(cached["digest"]) == digest and float(cached["rate"]) == per_second:
                return Peaks(
                    mins=cached["mins"],
                    maxs=cached["maxs"],
                    rate=float(cached["rate"]),
                    duration=float(cached["duration"]),
                )
    except (OSError, KeyError, ValueError):
        pass

    peaks = compute_peaks(Path(audio), per_second=per_second)
    try:
        Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
        with Path(cache_file).open("wb") as handle:
            np.savez(handle, mins=peaks.mins, maxs=peaks.maxs, rate=peaks.rate,
                     duration=peaks.duration, digest=digest)
    except OSError:
        pass  # a cache that cannot be written costs a re-decode next time, nothing more
    return peaks
```

Note for the implementer: the cache-reuse test monkeypatches `waveform.compute_peaks`, so `load_or_compute_peaks` must call it through the module global name (as written above), not through a local alias.

- [ ] **Step 5: Run to verify they pass**

Run: `venv/bin/python -m pytest tests/test_waveform.py tests/test_transcript_cache.py -q`
Expected: PASS.

- [ ] **Step 6: Full suite, lint and format, then commit**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q && venv/bin/ruff check src tests && venv/bin/ruff format --check src tests`
Expected: all pass (307 + the new tests), no lint or format findings. If `ruff format --check` fails, run `venv/bin/ruff format src tests` and re-run.

```bash
git add src/qurantext/core/waveform.py src/qurantext/services/transcript_cache.py tests/test_waveform.py
git commit -m "Reduce the recording to waveform peaks as it streams, and cache them

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After Phase 1

Phase 2 (review editor), 3 (home window), 4 (two languages) and 5 (packaging) each get their own plan, written against the code as it stands when the previous phase lands, in `docs/superpowers/plans/`.

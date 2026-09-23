# Review editor — Phase 2: the editor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the table-of-spin-boxes subtitle editor with a review window where a person listens to the recording, sees the waveform with uncovered-speech bands, watches the word highlight and the live frame, retimes words by drag or keyboard, undoes, saves, exports subtitle files, and renders with corrections.

**Architecture:** All editing state and rules live in a Qt-free `ReviewSession` (`gui/review/session.py`) that calls `core/timing_edit.py`; widgets only draw the session and forward gestures to it. Playback sits behind a small `Player` interface with a real Qt Multimedia implementation (imported lazily, so the app still opens without `PySide6-Addons`) and a fake for tests; a pure `PlaybackClock` smooths Qt's coarse position reports. A shared `Viewport` object gives the waveform and the word strip one time↔pixel mapping. Every user-visible string goes through `gui/i18n.t()` from the start, so Phase 4 only adds the Arabic table and right-to-left layout.

**Tech Stack:** Python 3.10+, PySide6 (QtCore/QtGui/QtWidgets; QtMultimedia optional at runtime), numpy, pytest with offscreen Qt (`QT_QPA_PLATFORM=offscreen`) and `PySide6.QtTest`.

**Spec:** `docs/superpowers/specs/2026-09-23-review-editor-design.md` — §2 (review editor) and §6 (testing). Phase 1 plan and its ledger (`.superpowers/sdd/2026-09-23-review-editor-phase1-foundations/progress.md`) record decisions this phase inherits.

## Global Constraints

- Python 3.10+; `venv/bin/ruff check src tests` and `venv/bin/ruff format --check src tests` clean (pinned `ruff==0.15.13`, line length 100).
- `core/` never imports `jobs/` or `gui/`. `gui/review/session.py` imports no Qt at all.
- Quran text is never editable: cards change reference/timing only; lecture caption text is editable.
- Times are float seconds rounded to 3 decimals when written.
- Time runs left to right in every timeline widget, in both languages; those widgets set `Qt.LayoutDirection.LeftToRight` explicitly.
- Every user-visible string in `gui/review/` goes through `qurantext.gui.i18n.t(key, **fmt)`; English only in this phase.
- Widgets never write timings themselves: every edit goes through `ReviewSession`, which goes through `timing_edit` (`retime_in_cards`/`ripple_in_cards` for cards, `retime`/`ripple` for caption words).
- Playback must be optional: if Qt Multimedia cannot load, the review window still opens, playback controls are disabled with a one-line reason, and everything else works.
- Do not `pip install` anything. Tests use `FakePlayer`; `QtPlayer` is exercised only where `PySide6.QtMultimedia` imports (skip otherwise).
- House style: why-docstrings, `from __future__ import annotations`, `__all__`, frozen `slots=True` dataclasses for value types.
- Run tests with `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q`.
- Commit messages: a plain-sentence subject saying what changed and why, then a blank line, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `src/qurantext/core/timing_edit.py` | modify | reject bad indices; snap to ms grid; `cue_bounds` |
| `src/qurantext/gui/jobs.py` | modify | identical re-match leaves the project file untouched |
| `src/qurantext/gui/i18n.py` | create | `STRINGS`, `t()`, language state |
| `src/qurantext/gui/review/__init__.py` | create | exports `ReviewWindow` |
| `src/qurantext/gui/review/session.py` | create | Qt-free editing model: words, lookups, edits, gestures, undo/redo, dirty, save, frame inputs |
| `src/qurantext/gui/review/player.py` | create | `PlaybackClock`, `Player` base, `FakePlayer`, `QtPlayer`, `create_player` |
| `src/qurantext/gui/review/viewport.py` | create | `Viewport`: visible window, zoom, time↔x |
| `src/qurantext/gui/review/waveform_view.py` | create | paints peaks, gap bands, playhead; click/drag seeks |
| `src/qurantext/gui/review/word_strip.py` | create | word boxes; select; drag edges (retime) / Shift-drag (ripple) |
| `src/qurantext/gui/review/frame_view.py` | create | live frame at the playhead, throttled |
| `src/qurantext/gui/review/segment_list.py` | create | ayah/caption rows, click to seek, editable caption text |
| `src/qurantext/gui/review/window.py` | create | `ReviewWindow`: layout, transport, selected-word bar, shortcuts, background peaks/coverage, save/close |
| `src/qurantext/gui/review/export_dialog.py` | create | Export subtitles dialog |
| `src/qurantext/gui/files.py` | create | `show_in_folder` (moved from `main_window.py`) |
| `src/qurantext/gui/main_window.py` | modify | open `ReviewWindow`; use `gui/files.show_in_folder` |
| `src/qurantext/gui/editor.py`, `tests/test_editor.py` | delete | replaced |
| `pyproject.toml` | modify | `gui` extra gains `PySide6-Addons` |
| `tests/conftest.py` | modify | shared `qt_app` fixture |
| tests | create | `test_i18n.py`, `test_review_session.py`, `test_player.py`, `test_review_widgets.py`, `test_review_window.py` |

---

### Task 1: Close the two edges carried over from Phase 1

**Files:**
- Modify: `src/qurantext/core/timing_edit.py`
- Modify: `src/qurantext/gui/jobs.py` (`_match`, `_keep_earlier`)
- Test: `tests/test_timing_edit.py`, `tests/test_gui.py`

**Interfaces:**
- Produces:
  - `retime`, `ripple`, `retime_in_cards`, `ripple_in_cards` raise `IndexError` for any negative or out-of-range index (`index`, `card_index`, `word_index`). No modulo, no Python negative indexing.
  - Every time these functions read is snapped to the millisecond grid on copy (`round(x, 3)`), and requested `start`/`end`/`delta` are rounded to 3 decimals before clamping. Rounding is monotonic, so invariants 1–2 hold on the snapped copy; invariant 4 becomes "identical up to millisecond rounding". Update the module docstring's invariant 4 to say exactly that.
  - `cue_bounds(start: float, end: float, words: list[dict]) -> tuple[float, float]` — `(min(start, words[0].start), max(end, words[-1].end))` rounded to 3 decimals, or `(start, end)` unchanged when *words* is empty. Add to `__all__`.
  - `gui/jobs._match`: when `_keep_earlier` finds the existing project's `content_hash()` equal to the freshly derived one, it does **not** save — the existing file (with its review state, render record, style and export) is left byte-for-byte untouched and `load_project(destination)` is returned as the project. `_keep_earlier` returns a small result so `_match` can tell "unchanged" from "backed up" from "nothing there".

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_timing_edit.py`:

```python
@pytest.mark.parametrize("index", [-1, 3, 99])
def test_retime_and_ripple_refuse_an_index_that_is_not_there(index) -> None:
    words = _words((0.0, 1.0), (1.0, 2.0), (2.0, 3.0))
    with pytest.raises(IndexError):
        retime(words, index, start=0.5)
    with pytest.raises(IndexError):
        ripple(words, index, 0.5)


@pytest.mark.parametrize(("card_index", "word_index"), [(-1, 0), (5, 0), (0, -1), (0, 9)])
def test_card_edits_refuse_an_index_that_is_not_there(card_index, word_index) -> None:
    from qurantext.core.timing_edit import retime_in_cards, ripple_in_cards

    cards = [
        {"start_time": 0.0, "end_time": 2.0, "word_timings": _words((0.0, 1.0), (1.0, 2.0))},
        {"start_time": 2.0, "end_time": 4.0, "word_timings": _words((2.0, 3.0), (3.0, 4.0))},
    ]
    with pytest.raises(IndexError):
        retime_in_cards(cards, card_index, word_index, start=0.5)
    with pytest.raises(IndexError):
        ripple_in_cards(cards, card_index, word_index, 0.5)


def test_off_grid_times_never_invert_a_neighbour() -> None:
    words = [{"word": "a", "start": 0.4, "end": 0.5}, {"word": "b", "start": 0.5006, "end": 0.5009}]
    out = retime(words, 0, end=1.0)
    for word in out:
        assert word["start"] <= word["end"]
    assert out[0]["end"] <= out[1]["start"]


def test_a_sub_millisecond_ripple_does_not_shorten_a_word() -> None:
    words = _words((76.5, 76.563), (76.563, 76.603), (76.603, 77.0))
    out = ripple(words, 1, -0.0025)
    assert round(out[1]["end"] - out[1]["start"], 3) == 0.04


def test_cue_bounds_grow_to_cover_the_words() -> None:
    from qurantext.core.timing_edit import cue_bounds

    assert cue_bounds(1.0, 2.0, _words((0.8, 1.2), (1.2, 2.5))) == (0.8, 2.5)
    assert cue_bounds(1.0, 2.0, _words((1.1, 1.2))) == (1.0, 2.0)
    assert cue_bounds(1.0, 2.0, []) == (1.0, 2.0)
```

Append to `tests/test_gui.py`:

```python
def test_an_identical_rematch_leaves_the_project_file_untouched(tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.jobs.project import Project, load_project, project_path_for, save_project

    match_path = tmp_path / "clip_recitation.json"
    match_path.write_text(json.dumps({"matches": [], "meta": {"mode": "recitation"}}), encoding="utf-8")
    audio = tmp_path / "clip.m4a"
    audio.write_bytes(b"")
    existing = Project.from_match_file(match_path, audio, mode="recitation")
    existing.mark_reviewed()
    existing.style = {"theme": "night"}
    destination = save_project(existing, project_path_for(match_path))
    before = destination.read_bytes()

    monkeypatch.setattr(jobs_module, "run_recitation_range", lambda **kwargs: {"matches": []})
    spec = JobSpec(audio=audio, quran=QURAN_FILE, surah_num=1, from_ayah=1, to_ayah=7,
                   output_dir=tmp_path)
    project = jobs_module.run_matching(spec)

    assert destination.read_bytes() == before
    assert project.review["state"] == "reviewed" and project.style == {"theme": "night"}
    assert not list(tmp_path.glob("*.qalun-backup.json"))
    assert load_project(destination).review["state"] == "reviewed"
```

- [ ] **Step 2: Run to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_timing_edit.py tests/test_gui.py -q`
Expected: the new tests FAIL (no `IndexError`; `cue_bounds` missing; project file rewritten).

- [ ] **Step 3: Implement.**

In `core/timing_edit.py`:

```python
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
```

Call `_check(index, len(words), "word")` at the top of `retime` and `ripple`; round `start`/`end` (when not None) and `delta` with `_snap` before any clamping. In `_flatten`, replace the existing checks with `_check(card_index, len(cards), "card")` first, then the existing "has no word timings" `ValueError`, then `_check(word_index, len(words), "word")` for the target card, and compute `target = len(flat) + word_index` (no modulo). Add:

```python
def cue_bounds(start: float, end: float, words: list[dict[str, Any]]) -> tuple[float, float]:
    """A caption line's window, grown to cover its words after they are retimed."""
    if not words:
        return start, end
    return (
        _snap(min(float(start), float(words[0]["start"]))),
        _snap(max(float(end), float(words[-1]["end"]))),
    )
```

In `gui/jobs.py`, make `_keep_earlier` return one of three outcomes and have `_match` act on it:

```python
_UNCHANGED = "unchanged"


def _keep_earlier(destination: Path, derived: Project) -> Path | str | None:
    """Back up the project at *destination* unless re-matching reproduced it exactly.

    Returns the backup path, ``"unchanged"`` when the existing project already
    holds exactly what re-matching derived (it is then left alone, review state,
    render record and all), or None when there was nothing there.
    """
    ...  # same comparison as today; return _UNCHANGED instead of None when equal
```

and in `_match`:

```python
    kept = _keep_earlier(destination, project)
    if kept == _UNCHANGED:
        return load_project(destination), None
    backup = kept if isinstance(kept, Path) else None
    if backup is not None:
        report(progress, "detect", f"Kept your earlier corrections in {backup.name}")
    save_project(project, destination)
    return project, backup
```

(`load_project` is already imported in `gui/jobs.py`; add it if not.)

- [ ] **Step 4: Run to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_timing_edit.py tests/test_gui.py -q`
Expected: PASS, including every pre-existing test. If a pre-existing test relied on negative `word_index` wrapping, change it to the explicit positive index and note it in the report.

- [ ] **Step 5: Full suite, ruff, commit**

```bash
git add src/qurantext/core/timing_edit.py src/qurantext/gui/jobs.py tests/test_timing_edit.py tests/test_gui.py
git commit -m "Refuse indices that are not there, and leave an unchanged project alone

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: One place for the window's words

**Files:**
- Create: `src/qurantext/gui/i18n.py`
- Modify: `tests/conftest.py` (add `qt_app`)
- Test: `tests/test_i18n.py`

**Interfaces:**
- Produces:
  - `STRINGS: dict[str, dict[str, str]]` with an `"en"` table. Keys are dotted, e.g. `"review.title"`.
  - `LANGUAGES = ("en",)` (Phase 4 adds `"ar"`).
  - `t(key: str, **fmt) -> str` — the current language's string, `.format(**fmt)`-ed; falls back to English, then to the key itself (never raises for a missing key; a test catches missing keys instead).
  - `current_language() -> str`, `set_language(code: str) -> None` (raises `ValueError` for an unknown code).
  - `tests/conftest.py` gains a module-scoped `qt_app` fixture that `pytest.importorskip("PySide6")` inside it and returns `QApplication.instance() or QApplication([])`.

- [ ] **Step 1: Write the failing tests** — `tests/test_i18n.py`:

```python
"""Every word the window shows comes from one table, so a second language is one more table."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from qurantext.gui import i18n

GUI_SOURCE = Path(__file__).resolve().parents[1] / "src" / "qurantext" / "gui"
_CALL = re.compile(r"""\bt\(\s*["']([a-z0-9_.]+)["']""")


def test_t_formats_and_falls_back() -> None:
    i18n.STRINGS["en"]["test.greeting"] = "Hello {name}"
    try:
        assert i18n.t("test.greeting", name="Khalil") == "Hello Khalil"
        assert i18n.t("test.not_there") == "test.not_there"
    finally:
        del i18n.STRINGS["en"]["test.greeting"]


def test_an_unknown_language_is_refused() -> None:
    with pytest.raises(ValueError):
        i18n.set_language("xx")
    assert i18n.current_language() == "en"


def test_every_key_the_code_uses_exists_in_every_language() -> None:
    used = set()
    for path in GUI_SOURCE.rglob("*.py"):
        used |= set(_CALL.findall(path.read_text(encoding="utf-8")))
    for language in i18n.LANGUAGES:
        missing = sorted(used - set(i18n.STRINGS[language]))
        assert not missing, f"{language} is missing: {missing}"


def test_every_language_has_the_same_keys_and_placeholders() -> None:
    fields = re.compile(r"{(\w+)}")
    english = i18n.STRINGS["en"]
    for language in i18n.LANGUAGES:
        table = i18n.STRINGS[language]
        assert set(table) == set(english)
        for key, text in english.items():
            assert set(fields.findall(table[key])) == set(fields.findall(text)), key
```

- [ ] **Step 2: Run to verify they fail** — `venv/bin/python -m pytest tests/test_i18n.py -q` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** `src/qurantext/gui/i18n.py`:

```python
"""The window's words, in one table per language.

Every string a person reads in the window comes from here, so adding a
language means adding a table, not editing widgets. English is the fallback for
a key a newer build added before its translation; the key itself is the last
resort, and a test fails the build long before that shows.
"""

from __future__ import annotations

__all__ = ["LANGUAGES", "STRINGS", "current_language", "set_language", "t"]

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # Tasks 3–9 add their keys here, grouped by widget.
    },
}
LANGUAGES = tuple(STRINGS)

_current = "en"


def current_language() -> str:
    return _current


def set_language(code: str) -> None:
    global _current
    if code not in STRINGS:
        raise ValueError(f"Unknown language {code!r}; choose from {', '.join(LANGUAGES)}.")
    _current = code


def t(key: str, **fmt: object) -> str:
    text = STRINGS.get(_current, {}).get(key) or STRINGS["en"].get(key) or key
    return text.format(**fmt) if fmt else text
```

Add to `tests/conftest.py`:

```python
@pytest.fixture(scope="module")
def qt_app():
    """One QApplication for widget tests; skipped where Qt is not installed."""
    pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
```

Existing test modules that define their own `qt_app` keep working (a module-level fixture overrides conftest's); leave them.

- [ ] **Step 4: Verify** — `venv/bin/python -m pytest tests/test_i18n.py -q` → PASS.

- [ ] **Step 5: Commit** — subject "Keep the window's words in one table, ready for a second language".

**Rule for Tasks 3–9:** every task that adds a `t("…")` call adds the English string to `STRINGS["en"]` in the same commit; `test_every_key_the_code_uses_exists_in_every_language` enforces it.

---

### Task 3: The review session (Qt-free editing model)

**Files:**
- Create: `src/qurantext/gui/review/__init__.py` (empty docstring module for now; Task 8 exports `ReviewWindow`)
- Create: `src/qurantext/gui/review/session.py`
- Test: `tests/test_review_session.py`

**Interfaces:**
- Consumes: `Project`, `CaptionCue`, `save_project` (`jobs/project.py`); `retime`, `ripple`, `retime_in_cards`, `ripple_in_cards`, `cue_bounds`, `count_edited` (`core/timing_edit.py`); `validated_matches` (`core/video_common.py`).
- Produces (all in `gui/review/session.py`, `__all__` = `CARD`, `CAPTION`, `WordRef`, `TimelineWord`, `ReviewSession`):
  - `CARD = "card"`, `CAPTION = "caption"`
  - `@dataclass(frozen=True, slots=True) class WordRef: kind: str; segment: int; word: int`
  - `@dataclass(frozen=True, slots=True) class TimelineWord: ref: WordRef; text: str; start: float; end: float; edited: bool`
  - `class ReviewSession`:
    - `__init__(self, project: Project, *, duration: float | None = None)`
    - `project: Project`, `duration: float | None` (settable; the window sets it once the player knows it)
    - `primary_kind -> str` — `CARD` for `mode == "recitation"`, else `CAPTION`
    - `words(kind: str | None = None) -> list[TimelineWord]` — timed card words and/or caption words, sorted by `(start, kind, segment, word)`; `kind=None` → the primary kind only
    - `word(ref: WordRef) -> TimelineWord`
    - `step(ref: WordRef | None, direction: int) -> WordRef | None` — previous/next word of the same kind in time order; from None → first (direction>0) or last
    - `word_at(t: float) -> WordRef | None` — the primary-kind word that most recently *started* at or before *t* (the renderer highlights on starts)
    - `card_at(t: float) -> int | None` — the last card whose `start_time <= t` (latched, like the renderer)
    - `caption_at(t: float) -> int | None` — the caption with `start <= t <= end`
    - `retime(ref, *, start=None, end=None) -> None`, `ripple(ref, delta: float) -> None`
    - `set_caption_text(index: int, text: str) -> None` (via `CaptionCue.edited`)
    - `set_card_times(index: int, *, start=None, end=None) -> None` — only for cards **without** word timings; raises `ValueError` otherwise; clamps `end >= start`
    - `remove_card(index)`, `remove_caption(index)`
    - `mark_reviewed() -> None`
    - `begin_gesture() -> None`, `end_gesture() -> None`
    - `undo() -> bool`, `redo() -> bool`, `can_undo`, `can_redo` (properties)
    - `dirty -> bool` (property) — the cards, captions or review state differ from the last save (or from load)
    - `revision -> int` (property) — increments on every change, undo and redo; widgets repaint when it changes
    - `save() -> Path` — `save_project(project, project.path)`; `ValueError` when `project.path` is None
    - `frame_inputs(t: float) -> tuple[dict | None, dict | None, bool]` — `(active validated card, active caption segment, reserve_caption_band)` for `render_frame_pillow`; `reserve_caption_band = bool(project.captions)`
    - `coverage_words() -> list[dict]` — every timed card word (recitation) or every caption word (lecture), as `{"start", "end"}` dicts, for `find_uncovered_speech`
    - `retimed_count(kind: str, segment: int) -> int`

Undo model: an undo entry is a deep copy of `(cards, captions, review)`. Any edit outside a gesture pushes one entry and clears redo. `begin_gesture()` pushes one entry and suppresses pushes until `end_gesture()`; if the gesture changed nothing, its entry is dropped. `undo()` swaps current state onto the redo stack; `redo()` the reverse. The cached validated cards (for `frame_inputs`) are invalidated whenever `revision` changes.

- [ ] **Step 1: Write the failing tests** — `tests/test_review_session.py`:

```python
"""The editing model behind the review window, tested without a screen."""

from __future__ import annotations

import pytest

from qurantext.gui.review.session import CAPTION, CARD, ReviewSession, WordRef
from qurantext.jobs.project import CaptionCue, Project, load_project, save_project


def _w(text, start, end):
    return {"word": text, "start": start, "end": end}


def _recitation(tmp_path=None):
    cards = [
        {"surah_num": 25, "from_ayah": 7, "to_ayah": 7, "full_text": "a b", "confidence": 1.0,
         "start_time": 0.0, "end_time": 2.0, "word_timings": [_w("a", 0.0, 1.0), _w("b", 1.0, 2.0)]},
        {"surah_num": 25, "from_ayah": 8, "to_ayah": 8, "full_text": "c d", "confidence": 1.0,
         "start_time": 2.0, "end_time": 10.0, "word_timings": [_w("c", 2.0, 3.0), _w("d", 3.0, 4.0)]},
    ]
    project = Project(audio=(tmp_path or __import__("pathlib").Path(".")) / "a.mp3",
                      mode="recitation", cards=cards)
    if tmp_path is not None:
        save_project(project, tmp_path / "job.qalun.json")
    return project


def _lecture():
    return Project(
        audio=__import__("pathlib").Path("dars.mp3"),
        mode="lecture",
        cards=[{"surah_num": 1, "from_ayah": 1, "to_ayah": 1, "full_text": "x", "confidence": 1.0,
                "start_time": 5.0, "end_time": 8.0}],
        captions=[CaptionCue(0.0, 2.0, "one two", words=[_w("one", 0.0, 1.0), _w("two", 1.0, 2.0)]),
                  CaptionCue(2.5, 4.0, "three", words=[_w("three", 2.5, 4.0)])],
    )


def test_words_are_the_primary_kind_in_time_order() -> None:
    session = ReviewSession(_recitation())
    assert session.primary_kind == CARD
    assert [w.text for w in session.words()] == ["a", "b", "c", "d"]
    assert session.words()[2].ref == WordRef(CARD, 1, 0)
    lecture = ReviewSession(_lecture())
    assert lecture.primary_kind == CAPTION
    assert [w.text for w in lecture.words()] == ["one", "two", "three"]


def test_lookups_follow_the_renderer() -> None:
    session = ReviewSession(_recitation())
    assert session.word_at(1.5) == WordRef(CARD, 0, 1)
    assert session.word_at(-1.0) is None
    assert session.card_at(9.0) == 1
    assert session.card_at(-0.1) is None
    lecture = ReviewSession(_lecture())
    assert lecture.caption_at(2.2) is None
    assert lecture.caption_at(3.0) == 1


def test_step_moves_between_words_across_cards() -> None:
    session = ReviewSession(_recitation())
    assert session.step(None, +1) == WordRef(CARD, 0, 0)
    assert session.step(WordRef(CARD, 0, 1), +1) == WordRef(CARD, 1, 0)
    assert session.step(WordRef(CARD, 0, 0), -1) is None


def test_retime_goes_through_the_card_rules_and_rederives_windows() -> None:
    session = ReviewSession(_recitation())
    session.retime(WordRef(CARD, 1, 0), start=2.5)
    card = session.project.cards[1]
    assert card["word_timings"][0]["start"] == 2.5 and card["word_timings"][0]["edited"]
    assert card["start_time"] == 2.5
    assert session.project.cards[0]["end_time"] == 2.5
    assert session.dirty and session.can_undo
    assert session.retimed_count(CARD, 1) == 1


def test_ripple_carries_into_later_cards() -> None:
    session = ReviewSession(_recitation())
    session.ripple(WordRef(CARD, 0, 1), 0.5)
    assert [w.start for w in session.words()] == [0.0, 1.5, 2.5, 3.5]


def test_caption_retime_grows_the_line_to_cover_its_words() -> None:
    session = ReviewSession(_lecture())
    session.retime(WordRef(CAPTION, 1, 0), end=4.6)
    cue = session.project.captions[1]
    assert cue.words[0]["end"] == 4.6 and cue.end == 4.6


def test_caption_text_edits_keep_timings_when_the_count_holds() -> None:
    session = ReviewSession(_lecture())
    session.set_caption_text(0, "one too")
    assert [w["word"] for w in session.project.captions[0].words] == ["one", "too"]


def test_card_times_are_editable_only_without_word_timings() -> None:
    lecture = ReviewSession(_lecture())
    lecture.set_card_times(0, start=6.0, end=5.0)
    assert (lecture.project.cards[0]["start_time"], lecture.project.cards[0]["end_time"]) == (6.0, 6.0)
    with pytest.raises(ValueError):
        ReviewSession(_recitation()).set_card_times(0, start=1.0)


def test_a_gesture_is_one_undo_step_and_an_empty_one_is_none() -> None:
    session = ReviewSession(_recitation())
    session.begin_gesture()
    for value in (0.2, 0.3, 0.4):
        session.retime(WordRef(CARD, 0, 1), start=1.0 + value)
    session.end_gesture()
    assert session.words()[1].start == 1.4
    assert session.undo() is True
    assert session.words()[1].start == 1.0
    assert session.undo() is False
    assert session.redo() is True and session.words()[1].start == 1.4

    session.begin_gesture()
    session.end_gesture()
    session.undo()
    assert session.words()[1].start == 1.0, "the empty gesture left no entry of its own"


def test_undo_back_to_the_saved_state_is_clean(tmp_path) -> None:
    session = ReviewSession(load_project(_recitation(tmp_path).path))
    assert not session.dirty
    session.retime(WordRef(CARD, 0, 0), end=0.8)
    assert session.dirty
    session.undo()
    assert not session.dirty


def test_save_writes_back_and_clears_dirty(tmp_path) -> None:
    session = ReviewSession(load_project(_recitation(tmp_path).path))
    session.retime(WordRef(CARD, 0, 0), end=0.8)
    session.mark_reviewed()
    path = session.save()
    assert not session.dirty
    reloaded = load_project(path)
    assert reloaded.cards[0]["word_timings"][0]["end"] == 0.8
    assert reloaded.review["state"] == "reviewed"


def test_save_without_a_file_says_so() -> None:
    with pytest.raises(ValueError):
        ReviewSession(_recitation()).save()


def test_removing_a_card_never_touches_quran_text() -> None:
    session = ReviewSession(_recitation())
    text = session.project.cards[1]["full_text"]
    session.remove_card(0)
    assert len(session.project.cards) == 1 and session.project.cards[0]["full_text"] == text
    session.undo()
    assert len(session.project.cards) == 2


def test_frame_inputs_give_the_active_card_and_caption() -> None:
    card, caption, band = ReviewSession(_recitation()).frame_inputs(2.5)
    assert card["from_ayah"] == 8 and "_start_time" in card
    assert caption is None and band is False
    card, caption, band = ReviewSession(_lecture()).frame_inputs(1.0)
    assert card is None and caption["text"] == "one two" and band is True


def test_coverage_words_are_the_primary_kind() -> None:
    assert len(ReviewSession(_recitation()).coverage_words()) == 4
    assert len(ReviewSession(_lecture()).coverage_words()) == 3


def test_revision_moves_on_every_change() -> None:
    session = ReviewSession(_recitation())
    start = session.revision
    session.retime(WordRef(CARD, 0, 0), end=0.9)
    session.undo()
    session.redo()
    assert session.revision == start + 3
```

- [ ] **Step 2: Run to verify they fail** — `venv/bin/python -m pytest tests/test_review_session.py -q` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** `src/qurantext/gui/review/session.py`:

```python
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

    def set_card_times(self, index: int, *, start: float | None = None, end: float | None = None) -> None:
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
```

Note for the implementer: `CaptionCue` is a dataclass whose `words` list is shared by `dataclasses.replace`; `retime`/`ripple` already return new lists, so no aliasing reaches the undo snapshots (they are deep copies). `project.cards` is reassigned, never mutated in place, except in `set_card_times`/`remove_card`, which snapshot first.

- [ ] **Step 4: Verify** — `venv/bin/python -m pytest tests/test_review_session.py -q` → PASS (17 tests).

- [ ] **Step 5: Commit** — subject "Hold the review's edits, undo and unsaved state in one model the widgets draw".

---

### Task 4: Playback behind a small interface

**Files:**
- Create: `src/qurantext/gui/review/player.py`
- Test: `tests/test_player.py`

**Interfaces:**
- Produces (`__all__` = `PlaybackClock`, `Player`, `FakePlayer`, `QtPlayer`, `create_player`, `RATES`):
  - `RATES = (1.0, 0.75, 0.5)`
  - `class PlaybackClock` (pure Python, no Qt): `__init__(self, now: Callable[[], float] = time.monotonic)`; `report(position_s: float) -> None` (re-anchor on Qt's report); `seek(position_s) -> None`; `set_playing(playing: bool) -> None`; `set_rate(rate: float) -> None`; `position() -> float` = anchor + (now − anchor_time) × rate while playing, else anchor; never returns less than the last value it returned while playing (monotonic), except after `seek` or a `report` that moves backwards by more than 0.25 s (a real jump), which resets it.
  - `class Player(QObject)` — the interface the window uses. Signals: `playing_changed = Signal(bool)`, `duration_changed = Signal(float)`, `error = Signal(str)`. Constructor `Player(parent=None, *, reason: str = "")`. Methods: `available -> bool`, `reason -> str` (why not, when unavailable), `load(path: Path) -> None`, `play()`, `pause()`, `toggle()`, `seek(seconds: float)`, `position() -> float`, `duration() -> float`, `is_playing() -> bool`, `set_rate(rate: float)`, `rate() -> float`. The base class implements everything as an unavailable player (no-ops; `position()` returns the last seek) with `reason` given at construction.
  - `class FakePlayer(Player)` — `FakePlayer(duration: float = 60.0, *, now: Callable[[], float] = time.monotonic, parent=None)`; available; `load` sets duration from a constructor argument (default 60.0); `play/pause/seek/set_rate` update state and emit signals; position driven by a `PlaybackClock` with an injectable `now`, so tests advance time explicitly.
  - `class QtPlayer(Player)` — `QMediaPlayer` + `QAudioOutput`; connects `positionChanged` (ms) → `clock.report`, `playbackStateChanged` → `playing_changed`, `durationChanged` → `duration_changed`, `errorOccurred` → `error`; `position()` returns the clock's smoothed value clamped to `[0, duration]`.
  - `create_player(parent=None) -> Player` — imports `PySide6.QtMultimedia` inside a `try`; on `ImportError` (or any failure constructing it) returns `Player(reason=t("player.unavailable", details=str(error)))`.

- [ ] **Step 1: Write the failing tests** — `tests/test_player.py`:

```python
"""Playback: a smoothed clock, a fake for tests, and a graceful absence."""

from __future__ import annotations

import builtins

import pytest

from qurantext.gui.review.player import RATES, PlaybackClock


class _Now:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def test_the_clock_runs_between_reports_at_the_rate() -> None:
    now = _Now()
    clock = PlaybackClock(now)
    clock.report(10.0)
    clock.set_playing(True)
    now.t += 0.5
    assert clock.position() == pytest.approx(10.5)
    clock.set_rate(0.5)
    now.t += 1.0
    assert clock.position() == pytest.approx(11.0)


def test_the_clock_holds_when_paused() -> None:
    now = _Now()
    clock = PlaybackClock(now)
    clock.report(3.0)
    now.t += 5.0
    assert clock.position() == 3.0


def test_a_slightly_late_report_does_not_run_the_clock_backwards() -> None:
    now = _Now()
    clock = PlaybackClock(now)
    clock.report(10.0)
    clock.set_playing(True)
    now.t += 0.3
    seen = clock.position()
    clock.report(10.2)
    assert clock.position() >= seen


def test_a_seek_or_a_real_jump_resets_it() -> None:
    now = _Now()
    clock = PlaybackClock(now)
    clock.report(50.0)
    clock.set_playing(True)
    now.t += 1.0
    clock.seek(5.0)
    assert clock.position() == pytest.approx(5.0)
    clock.report(1.0)
    assert clock.position() == pytest.approx(1.0)


def test_rates_offered() -> None:
    assert RATES == (1.0, 0.75, 0.5)


def test_fake_player_plays_seeks_and_signals(qt_app) -> None:
    from qurantext.gui.review.player import FakePlayer

    now = _Now()
    player = FakePlayer(duration=30.0, now=now)
    states, durations = [], []
    player.playing_changed.connect(states.append)
    player.duration_changed.connect(durations.append)
    player.load(__import__("pathlib").Path("x.mp3"))
    assert durations == [30.0] and player.available
    player.seek(4.0)
    player.play()
    now.t += 2.0
    assert player.position() == pytest.approx(6.0)
    player.toggle()
    assert states == [True, False] and not player.is_playing()


def test_without_qt_multimedia_the_player_explains_itself(qt_app, monkeypatch) -> None:
    from qurantext.gui.review import player as player_module

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith("PySide6.QtMultimedia"):
            raise ImportError("No module named 'PySide6.QtMultimedia'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    player = player_module.create_player()
    assert not player.available
    assert "QtMultimedia" in player.reason
    player.play()
    assert not player.is_playing()


def test_qt_player_loads_when_multimedia_is_installed(qt_app, tmp_path) -> None:
    pytest.importorskip("PySide6.QtMultimedia")
    from qurantext.gui.review.player import QtPlayer, create_player

    assert isinstance(create_player(), QtPlayer)
```

- [ ] **Step 2: Run to verify they fail** — `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_player.py -q` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** `src/qurantext/gui/review/player.py`. The clock (complete):

```python
class PlaybackClock:
    """Where playback is now, between the player's coarse position reports.

    Qt reports the position every few tens of milliseconds, which makes a
    running highlight stutter. Between reports this extrapolates on a monotonic
    clock at the playback rate, re-anchors on every report, and never steps
    backwards on a report that is merely a little late — only a seek or a real
    jump (more than :data:`JUMP_S`) moves it back.
    """

    JUMP_S = 0.25

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._anchor = 0.0
        self._anchor_at = now()
        self._playing = False
        self._rate = 1.0
        self._last = 0.0

    def _extrapolated(self) -> float:
        if not self._playing:
            return self._anchor
        return self._anchor + (self._now() - self._anchor_at) * self._rate

    def _anchor_to(self, position: float) -> None:
        self._anchor = float(position)
        self._anchor_at = self._now()

    def report(self, position_s: float) -> None:
        current = self._extrapolated()
        if position_s < current - self.JUMP_S:
            self._last = float(position_s)
        self._anchor_to(position_s)

    def seek(self, position_s: float) -> None:
        self._anchor_to(position_s)
        self._last = float(position_s)

    def set_playing(self, playing: bool) -> None:
        self._anchor_to(self._extrapolated())
        self._playing = bool(playing)

    def set_rate(self, rate: float) -> None:
        self._anchor_to(self._extrapolated())
        self._rate = float(rate)

    def position(self) -> float:
        value = self._extrapolated()
        if self._playing:
            value = max(value, self._last)
        self._last = value
        return value
```

`Player` base (unavailable), `FakePlayer`, `QtPlayer`, `create_player` as described in Interfaces. `QtPlayer` specifics: `QMediaPlayer.setAudioOutput(QAudioOutput(self))`; `setSource(QUrl.fromLocalFile(str(path)))`; `setPlaybackRate(rate)`; `setPosition(int(seconds * 1000))` and `clock.seek(seconds)` on seek; on `playbackStateChanged` call `clock.set_playing(state == QMediaPlayer.PlaybackState.PlayingState)` then emit `playing_changed`; `durationChanged(ms)` → emit seconds; `errorOccurred(error, message)` → emit `error(message)`. Keep PySide6.QtMultimedia imports inside `QtPlayer.__init__`/`create_player` only, so importing this module never needs Addons. Add the string `"player.unavailable": "Playback is off on this machine: {details}"` to `STRINGS["en"]`.

- [ ] **Step 4: Verify** — `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_player.py tests/test_i18n.py -q` → PASS (the QtPlayer test SKIPS here: Addons is not installed).

- [ ] **Step 5: Commit** — subject "Play the recording behind a small interface, smoothed between Qt's reports".

---

### Task 5: The viewport and the waveform

**Files:**
- Create: `src/qurantext/gui/review/viewport.py`, `src/qurantext/gui/review/waveform_view.py`
- Test: `tests/test_review_widgets.py`

**Interfaces:**
- Consumes: `Peaks` (`core/waveform.py`).
- Produces:
  - `class Viewport(QObject)`: signal `changed = Signal()`; attributes `duration: float` (≥ 0.001), `start: float`, `span: float` (visible seconds, clamped to `[MIN_SPAN_S=1.0, duration]`); `set_duration(d)`, `set_window(start, span)` (clamps so `0 <= start <= duration - span`), `zoom(factor, anchor_t)` (keeps *anchor_t* at the same pixel), `follow(t)` (if *t* leaves the window, page so *t* sits at 10 % from the left), `x_for(t, width) -> float`, `t_for(x, width) -> float`. Emits `changed` only on an actual change.
  - `class WaveformView(QWidget)`: `__init__(viewport, parent=None)`; `set_peaks(peaks: Peaks | None)`, `set_gaps(gaps: list[tuple[float, float]])`, `set_playhead(t: float)`; signal `seek_requested = Signal(float)` emitted on left-press and while dragging with the left button; `sizeHint` 600×90; `setLayoutDirection(Qt.LeftToRight)`; paints: background, min/max bars per pixel column (aggregate bins in the column's time range), translucent amber gap bands, red playhead line; with no peaks, centred text `t("waveform.reading")`.
- Strings to add: `"waveform.reading": "Reading the recording…"`.

- [ ] **Step 1: Write the failing tests** — `tests/test_review_widgets.py` (this file grows in Tasks 6–7):

```python
"""The review window's widgets, driven offscreen."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from qurantext.core.waveform import Peaks  # noqa: E402
from qurantext.gui.review.viewport import Viewport  # noqa: E402


def test_viewport_maps_time_and_pixels(qt_app) -> None:
    vp = Viewport()
    vp.set_duration(100.0)
    vp.set_window(10.0, 20.0)
    assert vp.x_for(20.0, 400) == pytest.approx(200.0)
    assert vp.t_for(100.0, 400) == pytest.approx(15.0)


def test_viewport_clamps_and_zooms_around_an_anchor(qt_app) -> None:
    vp = Viewport()
    vp.set_duration(100.0)
    vp.set_window(95.0, 20.0)
    assert (vp.start, vp.span) == (80.0, 20.0)
    before = vp.x_for(90.0, 500)
    vp.zoom(2.0, 90.0)
    assert vp.span == pytest.approx(10.0)
    assert vp.x_for(90.0, 500) == pytest.approx(before)
    vp.zoom(1000.0, 90.0)
    assert vp.span == Viewport.MIN_SPAN_S


def test_viewport_follows_the_playhead(qt_app) -> None:
    vp = Viewport()
    vp.set_duration(100.0)
    vp.set_window(0.0, 10.0)
    seen = []
    vp.changed.connect(lambda: seen.append(vp.start))
    vp.follow(5.0)
    assert seen == []
    vp.follow(12.0)
    assert vp.start == pytest.approx(11.0)


def test_waveform_click_asks_to_seek(qt_app) -> None:
    from qurantext.gui.review.waveform_view import WaveformView

    vp = Viewport()
    vp.set_duration(10.0)
    vp.set_window(0.0, 10.0)
    view = WaveformView(vp)
    view.resize(500, 90)
    view.set_peaks(Peaks(mins=-np.ones(1000, np.float32) / 2, maxs=np.ones(1000, np.float32) / 2,
                         rate=100.0, duration=10.0))
    asked = []
    view.seek_requested.connect(asked.append)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(250, 45))
    assert asked and asked[0] == pytest.approx(5.0, abs=0.05)


def test_waveform_paints_without_peaks_and_with_gaps(qt_app) -> None:
    from qurantext.gui.review.waveform_view import WaveformView

    vp = Viewport()
    vp.set_duration(10.0)
    view = WaveformView(vp)
    view.resize(300, 90)
    view.set_gaps([(2.0, 4.0)])
    view.set_playhead(3.0)
    assert not view.grab().isNull()
```

- [ ] **Step 2: Run to verify they fail**, then **Step 3: Implement** both files per Interfaces (the painting code is ordinary `QPainter`; aggregate `peaks.mins/maxs` per pixel column with numpy slicing on `int(t*rate)` bounds; colours from `palette()` for background/foreground so dark mode works, `QColor(239, 159, 39, 70)` for gap bands, `QColor(226, 75, 74)` for the playhead).

- [ ] **Step 4: Verify** — `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py tests/test_i18n.py -q` → PASS.

- [ ] **Step 5: Commit** — subject "Draw the recording, its uncovered stretches and the playhead on one shared timeline".

---

### Task 6: The word strip

**Files:**
- Create: `src/qurantext/gui/review/word_strip.py`
- Test: `tests/test_review_widgets.py` (append)

**Interfaces:**
- Consumes: `Viewport` (Task 5); `ReviewSession`, `WordRef` (Task 3).
- Produces: `class WordStrip(QWidget)`:
  - `__init__(viewport, session, parent=None)`; `setLayoutDirection(Qt.LeftToRight)`; `sizeHint` 600×34.
  - `selected -> WordRef | None`; `select(ref: WordRef | None)`; signal `selection_changed = Signal(object)`; signal `seek_requested = Signal(float)`; signal `edited = Signal()` (after any edit through the strip).
  - `refresh()` — repaint from `session.words()` (call after the session's revision changes).
  - Shared boundaries: when a press is within `EDGE_PX` of both a word's end and the next word's start, grab the earlier word's **end** — `retime(end=)` moves the shared edge for both words, which is what dragging a boundary means.
  - Mouse: press on a word's body → select it and emit `seek_requested(word.start)`. Press within `EDGE_PX = 5` of a word's left/right edge → start an edge drag: `session.begin_gesture()`, then on each move `session.retime(ref, start=t)` / `session.retime(ref, end=t)`, and on release `session.end_gesture()` + `edited`. Shift-press on a word's body → ripple drag: remember the press time `t0` and the word's start; on each move compute the total delta from `t0` and apply it as `session.ripple(ref, delta - applied)`, tracking `applied` so the ripple equals the pointer's travel; release ends the gesture. The cursor shows `SizeHorCursor` over edges.
  - Paint: a box per visible word from `x_for(start)` to `x_for(end)` (min 2 px wide), text elided to fit, drawn with the app font (Arabic shapes correctly inside the box); edited words get a small dot; the selected word uses the palette highlight; the word under the playhead (`session.word_at(playhead)`) gets a bold outline. `set_playhead(t)`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_review_widgets.py`:

```python
def _strip(qt_app):
    from qurantext.gui.review.session import ReviewSession
    from qurantext.gui.review.word_strip import WordStrip
    from qurantext.jobs.project import Project

    cards = [{"surah_num": 25, "from_ayah": 7, "to_ayah": 7, "full_text": "a b c", "confidence": 1.0,
              "start_time": 0.0, "end_time": 10.0,
              "word_timings": [{"word": "a", "start": 1.0, "end": 2.0},
                               {"word": "b", "start": 2.0, "end": 3.0},
                               {"word": "c", "start": 3.0, "end": 4.0}]}]
    session = ReviewSession(Project(audio=__import__("pathlib").Path("a.mp3"), cards=cards))
    vp = Viewport()
    vp.set_duration(10.0)
    vp.set_window(0.0, 10.0)
    strip = WordStrip(vp, session)
    strip.resize(1000, 34)
    return session, strip


def test_clicking_a_word_selects_it_and_seeks(qt_app) -> None:
    session, strip = _strip(qt_app)
    seeks = []
    strip.seek_requested.connect(seeks.append)
    QTest.mouseClick(strip, Qt.MouseButton.LeftButton, pos=QPoint(250, 17))
    assert strip.selected.word == 1 and seeks == [pytest.approx(2.0)]


def test_dragging_an_edge_retimes_through_the_session_as_one_undo(qt_app) -> None:
    session, strip = _strip(qt_app)
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, pos=QPoint(200, 17))
    for x in (210, 230, 250):
        QTest.mouseMove(strip, QPoint(x, 17))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, pos=QPoint(250, 17))
    words = session.words()
    assert words[1].start == pytest.approx(2.5, abs=0.02)
    assert words[0].end == pytest.approx(2.5, abs=0.02)
    session.undo()
    assert session.words()[1].start == 2.0
    assert not session.can_undo


def test_shift_dragging_ripples_the_rest(qt_app) -> None:
    session, strip = _strip(qt_app)
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier,
                     QPoint(250, 17))
    QTest.mouseMove(strip, QPoint(300, 17))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier,
                       QPoint(300, 17))
    assert [w.start for w in session.words()] == pytest.approx([1.0, 2.5, 3.5], abs=0.02)
```

Note: `QTest.mouseMove` does not carry button state on every platform. If moves arrive without `LeftButton` in `event.buttons()`, track the drag from press to release in the widget's own state rather than testing `event.buttons()` — the test must pass offscreen.

- [ ] **Step 2–4:** fail → implement → pass (`QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py -q`).

- [ ] **Step 5: Commit** — subject "Show each word at its time, and let a drag retime it or ripple the rest".

---

### Task 7: The live frame and the segment list

**Files:**
- Create: `src/qurantext/gui/review/frame_view.py`, `src/qurantext/gui/review/segment_list.py`
- Test: `tests/test_review_widgets.py` (append)

**Interfaces:**
- Consumes: `ReviewSession.frame_inputs`, `card_at`, `caption_at`, `retimed_count`, `set_caption_text`, `remove_card`, `remove_caption` (Task 3); `render_frame_pillow`, `DEFAULT_PLACEHOLDER_TITLE`, `_frame_dependencies` (`core/frame_renderer.py`); `DEFAULT_FONT_PATH` (`config/paths.py`); `card_ref` (`core/subtitles.py`).
- Produces:
  - `class FrameView(QLabel)`: `__init__(session, *, portrait: bool = True, parent=None)`; `show_at(t: float, *, force: bool = False)` — renders at most every `MIN_INTERVAL_S = 0.2` unless *force* (call the renderer as the module-global `render_frame_pillow`, so the test's monkeypatch takes effect) (seek/pause/edit call it with `force=True`); size 270×480 portrait / 480×270 landscape; converts the BGR array to a `QImage` (copy, `Format_RGB888` after `[:, :, ::-1]`). A render error shows `t("frame.error", details=…)` as text instead of raising.
  - `class SegmentList(QTableWidget)`: `__init__(session, parent=None)`; columns `t("segments.ref")`, `t("segments.time")`, `t("segments.text")`, `t("segments.retimed")`; one row per card (recitation) or per card then per caption (lecture), each row's `Qt.UserRole` data = `("card", i)` or `("caption", i)`; Quran text cells read-only with tooltip `t("segments.locked")`; caption text cells editable → `session.set_caption_text`; `refresh()`; `highlight_at(t)` selects-without-signal the row under *t*; signal `seek_requested = Signal(float)` on row click (row's start); `remove_selected() -> bool` removes the selected row through the session. Text cells use right-to-left alignment for Arabic (`Qt.AlignRight | Qt.AlignVCenter`) even in the English UI.
- Strings to add: `frame.error`, `segments.ref`, `segments.time`, `segments.text`, `segments.retimed`, `segments.locked` (English: "Could not draw the frame: {details}", "Ayah", "Time", "Text", "Retimed", "Quran text is read from the store and cannot be edited here.").

- [ ] **Step 1: Write the failing tests** — append:

```python
def test_frame_view_draws_the_active_card(qt_app) -> None:
    from qurantext.config.paths import DEFAULT_FONT_PATH
    from qurantext.gui.review.frame_view import FrameView

    if not DEFAULT_FONT_PATH.exists():
        pytest.skip("needs the bundled font")
    session, _ = _strip(qt_app)
    view = FrameView(session)
    view.show_at(2.5, force=True)
    assert view.pixmap() is not None and not view.pixmap().isNull()
    assert (view.pixmap().width(), view.pixmap().height()) == (270, 480)


def test_frame_view_throttles_while_playing(qt_app, monkeypatch) -> None:
    from qurantext.gui.review import frame_view as module

    session, _ = _strip(qt_app)
    calls = []
    monkeypatch.setattr(module, "render_frame_pillow", lambda *a, **k: calls.append(a[0]) or
                        np.zeros((480, 270, 3), np.uint8))
    view = module.FrameView(session)
    for t in (1.0, 1.05, 1.1):
        view.show_at(t)
    view.show_at(1.15, force=True)
    assert calls == [1.0, 1.15]


def test_segment_list_locks_quran_text_and_seeks(qt_app) -> None:
    from qurantext.gui.review.segment_list import SegmentList

    session, _ = _strip(qt_app)
    table = SegmentList(session)
    assert table.rowCount() == 1
    text_item = table.item(0, 2)
    assert not (text_item.flags() & Qt.ItemFlag.ItemIsEditable)
    seeks = []
    table.seek_requested.connect(seeks.append)
    table.cellClicked.emit(0, 0)
    assert seeks == [pytest.approx(0.0)]


def test_segment_list_edits_caption_text_through_the_session(qt_app) -> None:
    from qurantext.gui.review.segment_list import SegmentList
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import CaptionCue, Project

    project = Project(audio=__import__("pathlib").Path("d.mp3"), mode="lecture",
                      captions=[CaptionCue(0.0, 1.0, "misheard", words=[])])
    session = ReviewSession(project)
    table = SegmentList(session)
    row = next(r for r in range(table.rowCount())
               if table.item(r, 0).data(Qt.ItemDataRole.UserRole) == ("caption", 0))
    table.item(row, 2).setText("corrected")
    assert session.project.captions[0].text == "corrected" and session.can_undo
```

- [ ] **Step 2–4:** fail → implement → pass. The throttle uses `time.monotonic()`; the test relies on three calls within 0.2 s of the first, which holds on any machine.

- [ ] **Step 5: Commit** — subject "Show the frame the video will have at the playhead, and list the ayat and captions".

---

### Task 8: The review window

**Files:**
- Create: `src/qurantext/gui/review/window.py`; modify `src/qurantext/gui/review/__init__.py` to export `ReviewWindow`
- Test: `tests/test_review_window.py`

**Interfaces:**
- Consumes: everything from Tasks 3–7; `load_or_compute_peaks`, `peaks_path_for` (`core/waveform.py`); `find_uncovered_speech` (`core/coverage.py`); `run_in_thread` (`gui/worker.py`); `CancelToken`.
- Produces: `class ReviewWindow(QMainWindow)`:
  - `__init__(project: Project, *, player: Player | None = None, parent=None)` — `player` defaults to `create_player(self)`; builds a `ReviewSession`; title `t("review.title", name=Path(project.audio).stem)`.
  - Layout: toolbar row (`Save`, `Undo`, `Redo`, `Mark as reviewed`, stretch, `Export subtitles…`, `Render with corrections` — the last two are wired in Task 9; here they exist and emit `export_requested`/`render_requested` signals); warnings strip (`QLabel`, hidden when empty) listing gaps with a "Jump" link per gap (`linkActivated` → seek); body: `FrameView` left, right column = zoom slider row, `WaveformView`, `WordStrip`, transport row (play/pause button, time label `mm:ss.cc`, rate combo from `RATES`), selected-word bar (word text, times, `−50 ms`, `+50 ms`, `Snap to playhead`); bottom: `SegmentList`.
  - Player unavailable → play button disabled with tooltip = `player.reason`, and a line in the warnings strip; everything else enabled.
  - A 60 Hz `QTimer` while playing reads `player.position()`, updates waveform/strip playhead, `viewport.follow`, the time label, `segment_list.highlight_at`, and `frame_view.show_at(t)`. On pause/seek/edit: `frame_view.show_at(t, force=True)`.
  - Background work via `run_in_thread` (keep references): peaks (`load_or_compute_peaks(project.audio, peaks_path_for(project.path or …))`) → `waveform.set_peaks` and `viewport.set_duration` if the player has none yet; coverage (`find_uncovered_speech(project.audio, session.coverage_words())`) on open and again 1 s after the last edit (single-shot `QTimer` restarted on each edit) → `waveform.set_gaps` + warnings strip. Missing audio → warnings strip says `t("review.audio_missing", path=…)`; no crash. Both workers are cancelled on close.
  - Keyboard (`QShortcut`s on the window): Space play/pause; Left/Right previous/next word (`session.step`, select + seek); `[` / `]` set selected word start / end at the playhead; `,` / `.` nudge the selected word's end by −/+0.05 s (Shift: 0.01 s) — the "selected edge" is the end unless the last edge the user grabbed was a start; Ctrl+Z undo; Ctrl+Shift+Z redo; Ctrl+S save.
  - After any edit or undo/redo: refresh strip, list, toolbar enabled states, title marker (`*` when `session.dirty`).
  - `closeEvent`: if `session.dirty`, ask via `self._confirm_discard()` → returns `"save" | "discard" | "cancel"` (a `QMessageBox` with Save/Discard/Cancel; tests monkeypatch this method); "save" saves then closes, "discard" closes, "cancel" ignores the event. Stop the timer, pause the player, cancel workers.
  - Signals: `saved = Signal(object)` (the path), `export_requested = Signal()`, `render_requested = Signal()`.
- Strings to add (English): `review.title` "Review — {name}", `review.save` "Save", `review.undo` "Undo", `review.redo` "Redo", `review.mark_reviewed` "Mark as reviewed", `review.export` "Export subtitles…", `review.render` "Render with corrections", `review.play` "Play", `review.pause` "Pause", `review.zoom` "Zoom", `review.snap` "Snap to playhead", `review.minus` "−50 ms", `review.plus` "+50 ms", `review.no_selection` "Select a word to retime it", `review.selected` "{word}  {start} → {end} s", `review.gaps` "{count} stretch(es) of speech have no word:", `review.gap` "{duration:.1f} s at {start:.1f}–{end:.1f} s", `review.jump` "Jump", `review.covered` "Every stretch of speech is covered by a word.", `review.audio_missing` "The recording is not where the project says: {path}", `review.discard_title` "Save your corrections?", `review.discard_text` "This review has changes that are not saved.", `review.shortcuts` "Space plays · ←/→ step words · [ and ] set start/end at the playhead · , and . nudge · Ctrl+Z undoes".

- [ ] **Step 1: Write the failing tests** — `tests/test_review_window.py`:

```python
"""The review window, assembled, with a fake player."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from qurantext.gui.review.player import FakePlayer  # noqa: E402
from qurantext.jobs.project import Project, load_project, save_project  # noqa: E402


class _Now:
    t = 0.0

    def __call__(self):
        return self.t


def _project(tmp_path):
    cards = [{"surah_num": 25, "from_ayah": 7, "to_ayah": 7, "full_text": "a b", "confidence": 1.0,
              "start_time": 0.0, "end_time": 10.0,
              "word_timings": [{"word": "a", "start": 1.0, "end": 2.0},
                               {"word": "b", "start": 2.0, "end": 3.0}]}]
    matches = tmp_path / "m.json"
    matches.write_text(json.dumps({"matches": cards, "meta": {"mode": "recitation"}}), encoding="utf-8")
    project = Project(audio=tmp_path / "missing.mp3", cards=cards, matches=matches)
    save_project(project, tmp_path / "m.qalun.json")
    return project


def _window(qt_app, tmp_path):
    from qurantext.gui.review.window import ReviewWindow

    now = _Now()
    player = FakePlayer(duration=10.0, now=now)
    window = ReviewWindow(_project(tmp_path), player=player)
    window.resize(1100, 800)
    return window, player, now


def test_it_opens_on_a_missing_recording_and_says_so(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    QTest.qWait(50)
    assert "missing.mp3" in window.warnings.text()


def test_keyboard_steps_and_sets_edges_at_the_playhead(qt_app, tmp_path) -> None:
    window, player, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Right)
    assert window.strip.selected.word == 1
    player.seek(2.4)
    QTest.keyClick(window, Qt.Key.Key_BracketLeft)
    assert window.session.words()[1].start == pytest.approx(2.4)
    QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert window.session.words()[1].start == 2.0


def test_nudge_moves_the_end_by_fifty_milliseconds(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
    assert window.session.words()[0].end == pytest.approx(2.05)


def test_ctrl_s_saves_and_the_title_loses_its_marker(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
    assert window.windowTitle().endswith("*")
    QTest.keyClick(window, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert not window.windowTitle().endswith("*")
    assert load_project(window.session.project.path).cards[0]["word_timings"][0]["end"] == 2.05


@pytest.mark.parametrize(("answer", "closes", "saved"), [("cancel", False, False),
                                                          ("discard", True, False),
                                                          ("save", True, True)])
def test_closing_with_changes_asks(qt_app, tmp_path, monkeypatch, answer, closes, saved) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
    monkeypatch.setattr(window, "_confirm_discard", lambda: answer)
    window.close()
    assert window.isVisible() is (not closes)
    stored = load_project(window.session.project.path).cards[0]["word_timings"][0]["end"]
    assert (stored == 2.05) is saved


def test_without_playback_the_window_still_edits(qt_app, tmp_path) -> None:
    from qurantext.gui.review.player import Player
    from qurantext.gui.review.window import ReviewWindow

    window = ReviewWindow(_project(tmp_path), player=Player(reason="no audio backend"))
    window.show()
    assert not window.play_button.isEnabled()
    assert "no audio backend" in window.play_button.toolTip()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
    assert window.session.dirty
```

(Expose `window.session`, `window.strip`, `window.warnings`, `window.play_button` as public attributes.)

- [ ] **Step 2–4:** fail → implement → pass (`QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_window.py tests/test_review_widgets.py tests/test_i18n.py -q`). Offscreen, `QShortcut` needs the window shown and active; call `window.activateWindow()` in `_window` if key clicks are not delivered, or bind the keys in `keyPressEvent` instead of `QShortcut` — whichever passes offscreen; note the choice in the report.

- [ ] **Step 5: Commit** — subject "Assemble the review window: listen, see, retime by hand or by key, undo, save".

---

### Task 9: Export subtitles and render with corrections

**Files:**
- Create: `src/qurantext/gui/review/export_dialog.py`, `src/qurantext/gui/files.py`
- Modify: `src/qurantext/gui/review/window.py` (wire `export_requested` / `render_requested`)
- Modify: `src/qurantext/gui/main_window.py` (use `files.show_in_folder`; delete its `_show_in_folder`)
- Test: `tests/test_review_window.py` (append)

**Interfaces:**
- Consumes: `export_project_subtitles`, `SUBTITLE_TIMELINES` (`jobs/project_render.py`); `SUBTITLE_FORMATS` (`core/subtitles.py`); `run_render` (`gui/jobs.py`); `run_in_thread`.
- Produces:
  - `gui/files.show_in_folder(path: Path) -> None` — moved verbatim from `main_window._show_in_folder`.
  - `class ExportDialog(QDialog)`: `__init__(session: ReviewSession, parent=None)`; checkboxes per format in `SUBTITLE_FORMATS` (SRT checked); folder field + "Choose…" button (default: the rendered video's folder if `project.render`, else `VIDEOS_OUTPUT_DIR`); filename stem field (default: the audio's stem); timeline radios `t("export.match_video")` (enabled only when `project.render` exists, and then the default) / `t("export.match_audio")`; `Export` button → if `session.dirty`, `session.save()` first; then `export_project_subtitles(session.project, folder / stem, formats, timeline=…)`; shows the written files and a "Show in folder" button; errors (`ValueError`, `OSError`) shown inline in the dialog, not raised. Public `export() -> list[Path]` does the work (tests call it directly).
  - `ReviewWindow` wiring: `export_requested` → `ExportDialog(self.session, self).exec()`. `render_requested` → save if dirty, then `run_in_thread(lambda progress, cancel: run_render(session.project, preset=…, subtitles=…, progress=progress, cancel=cancel), …)` with a progress bar + Cancel in the toolbar row; preset = `project.render["preset"]` if present, else `"social"`; subtitles = `project.export.get("subtitles", "burn")`; on finish, `QMessageBox.information(t("render.done", path=video))` with "Show the video" (`show_in_folder`); on failure/cancel, a message; the Render button is disabled while running.
- Strings to add: `export.title` "Export subtitles", `export.formats` "Formats", `export.folder` "Folder", `export.choose` "Choose…", `export.name` "File name", `export.match_video` "Match the rendered video (includes the basmala at the start)", `export.match_audio` "Match the original recording", `export.go` "Export", `export.done` "Wrote {count} file(s):", `export.show` "Show in folder", `export.none_chosen` "Choose at least one format.", `render.running` "Rendering — {percent}%", `render.done` "The video is ready: {path}", `render.show` "Show the video", `render.failed` "The render did not finish: {details}", `render.cancelled` "Rendering stopped.", `render.cancel` "Cancel".

- [ ] **Step 1: Write the failing tests** — append to `tests/test_review_window.py`:

```python
from tests.media_helpers import MEDIA_AVAILABLE, MEDIA_REASON, build_job  # noqa: E402


@pytest.mark.skipif(not MEDIA_AVAILABLE, reason=MEDIA_REASON)
def test_export_writes_the_chosen_formats_and_saves_first(qt_app, tmp_path, store) -> None:
    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.session import CARD, ReviewSession, WordRef

    audio, matches = build_job(tmp_path)
    project = Project.from_match_file(matches, audio)
    save_project(project, tmp_path / "job.qalun.json")
    session = ReviewSession(project)
    session.retime(WordRef(CARD, 0, 1), start=0.45)
    dialog = ExportDialog(session, db_path=store)
    dialog.set_formats(("srt", "vtt"))
    dialog.set_destination(tmp_path / "out", "clip")
    written = dialog.export()
    assert sorted(p.suffix for p in written) == [".srt", ".vtt"]
    assert not session.dirty, "unsaved edits are saved before exporting"


def test_export_on_the_video_timeline_is_offered_only_after_a_render(qt_app, tmp_path) -> None:
    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.session import ReviewSession

    project = _project(tmp_path)
    assert not ExportDialog(ReviewSession(project)).video_timeline_available()
    project.record_render(tmp_path / "v.mp4", preset="social", basmala_offset_s=1.0)
    dialog = ExportDialog(ReviewSession(project))
    assert dialog.video_timeline_available() and dialog.timeline() == "video"


def test_render_with_corrections_saves_then_renders_the_project(qt_app, tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.gui.jobs import JobOutcome

    window, _, _ = _window(qt_app, tmp_path)
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Period)
    seen = {}

    def fake_render(project, **kwargs):
        seen["end"] = project.cards[0]["word_timings"][0]["end"]
        seen["saved"] = load_project(project.path).cards[0]["word_timings"][0]["end"]
        return JobOutcome(matches=project.matches, video=tmp_path / "v.mp4", cards=1, mode="recitation")

    monkeypatch.setattr(jobs_module, "run_render", fake_render)
    monkeypatch.setattr(window, "_announce_render", lambda outcome: seen.setdefault("done", outcome))
    window.render_requested.emit()
    QTest.qWaitFor(lambda: "done" in seen, 5000)
    assert seen["end"] == 2.05 and seen["saved"] == 2.05
```

Implementation notes the tests fix: `ExportDialog.__init__(session, parent=None, *, db_path=QURAN_DB_PATH)`; public helpers `set_formats(formats)`, `set_destination(folder, stem)`, `timeline() -> str`, `video_timeline_available() -> bool`, `export() -> list[Path]`; `tests/media_helpers.py` already exposes `MEDIA_AVAILABLE`, `MEDIA_REASON` and `build_job(tmp_path, seconds=6.0) -> (audio, matches)`. `ReviewWindow._announce_render(outcome)` is the method that shows the finished-render message (tests monkeypatch it). The window calls `jobs_module.run_render` through the module attribute, and connects the worker's finished signal as `lambda outcome: self._announce_render(outcome)`, so both monkeypatches take effect.

- [ ] **Step 2–4:** fail → implement → pass.

- [ ] **Step 5: Commit** — subject "Export the corrected subtitles, and render the corrections from the review".

---

### Task 10: Open the review from the window, and retire the old editor

**Files:**
- Modify: `src/qurantext/gui/main_window.py` (`_open_editor`, imports, `check_button` label)
- Delete: `src/qurantext/gui/editor.py`, `tests/test_editor.py`
- Modify: `pyproject.toml` (`gui` extra)
- Test: `tests/test_gui.py` (append)

**Interfaces:**
- Consumes: `ReviewWindow` (Task 8), `project_path_for`, `load_project` (`jobs/project.py`), `JobOutcome.project` (Phase 1).
- Produces: `MainWindow._open_editor()` opens `ReviewWindow(load_project(outcome.project or project_path_for(outcome.matches)))`, keeps a reference, connects `saved` to the status line (`t("main.saved", path=…)`), and shows it. The "Check the subtitles" button becomes `t("main.review")` = "Review and correct". `pyproject.toml`: `gui = ["PySide6-Essentials>=6.6,<7", "PySide6-Addons>=6.6,<7"]` with a comment that Addons carries Qt Multimedia for playback and the app runs without it.

Before deleting `tests/test_editor.py`, check that every behaviour it covered has a new home: Quran text locked (Task 7), caption editing (Tasks 3/7), time editing (Task 3), end-before-start clamp (Task 3 `set_card_times`), removing a false positive (Tasks 3/7), saving (Task 3/8), coverage reports for "nothing to check" and "missing audio" (Task 8). If any is missing, add the test to the matching new file in this task.

- [ ] **Step 1: Write the failing test** — append to `tests/test_gui.py`:

```python
def test_review_opens_the_jobs_project(qt_app, tmp_path, monkeypatch) -> None:
    from qurantext.gui import main_window as module
    from qurantext.gui.jobs import JobOutcome
    from qurantext.jobs.project import Project, save_project

    matches = tmp_path / "clip_recitation.json"
    matches.write_text(json.dumps({"matches": [], "meta": {"mode": "recitation"}}), encoding="utf-8")
    project_path = save_project(Project(audio=tmp_path / "clip.mp3", matches=matches),
                                tmp_path / "clip_recitation.qalun.json")
    opened = []
    monkeypatch.setattr(module, "ReviewWindow", lambda project, **kw: opened.append(project) or
                        type("W", (), {"show": lambda self: None,
                                       "saved": type("S", (), {"connect": lambda self, f: None})()})())
    window = module.MainWindow()
    window._outcome = JobOutcome(matches=matches, video=None, cards=0, mode="recitation",
                                 project=project_path)
    window._open_editor()
    assert opened and opened[0].path == project_path
```

- [ ] **Step 2–4:** fail → implement → pass; then `git rm src/qurantext/gui/editor.py tests/test_editor.py`.

- [ ] **Step 5: Full suite + ruff + a manual smoke run**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q && venv/bin/ruff check src tests && venv/bin/ruff format --check src tests`
Then a manual smoke run that opens a real project offscreen and grabs a screenshot:

```bash
QT_QPA_PLATFORM=offscreen venv/bin/python - <<'EOF'
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
app = QApplication([])
from qurantext.gui.review.window import ReviewWindow
from qurantext.jobs.project import Project
m = Path("output/recitation_matching/furquanTra7-11_recitation.json")
if m.exists():
    w = ReviewWindow(Project.from_match_file(m, Path("input/recitations/furquanTra7-11.mp3")))
    w.resize(1280, 860); w.show(); QTest.qWait(4000)
    w.grab().save("/tmp/claude-review-window.png"); print("saved")
EOF
```

Attach the screenshot path to the report (the controller reviews it).

- [ ] **Step 6: Commit** — subject "Open the review from the main window, and retire the old subtitle editor".

---

## After Phase 2

Phase 3 (home window: job list, Recitation|Lecture toggle, More options, Start → review, the output-folder scanning decision), Phase 4 (Arabic table + RTL), Phase 5 (packaging: Qt Multimedia in the PyInstaller spec, playback preflight check, size budget) each get their own plan.

# Review editor Phase 4 — Arabic and right-to-left — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Qalun's window speaks English and Arabic, switchable, with Arabic laid out right to left while every timeline keeps time running left to right; plus the four residuals Phase 3 carried.

**Architecture:** `gui/i18n.py` stays Qt-free and gains plurals (`tn`), bidi isolation of formatted values in right-to-left languages, and one-value time spans. A new `gui/language.py` applies a language to the running app (i18n table, layout direction, Qt's own translations, Western digits). Language changes from the home window only, when no review is open and no job runs; the home window then rebuilds its panels in place. Every review window is built in the language current when it opens.

**Tech Stack:** Python 3.10+, PySide6 6.11 (Essentials + Addons), pytest offscreen.

**Spec:** `docs/superpowers/specs/2026-09-23-review-editor-design.md` §4 (and §2/§3 for the widgets it touches). §4's "switching rebuilds the open windows in place" is narrowed by ruling (see Task 4) — the spec is amended in the same commit as this plan.

## Global Constraints

- Python 3.10+; `venv/bin/ruff check src tests` and `venv/bin/ruff format --check src tests` clean (pinned ruff==0.15.13, line length 100).
- `core/` never imports `jobs/` or `gui/`. `gui/review/session.py` and `gui/i18n.py` import no Qt at all.
- Quran text is never editable: cards change reference/timing only; lecture caption text is editable.
- Every user-visible string in `gui/` goes through `qurantext.gui.i18n.t(key, **fmt)` (or `tn` for counts). Both tables have the same keys and the same placeholders (a test enforces it).
- Spec §4, verbatim: "The waveform, word strip and time fields are pinned `LeftToRight` so time keeps its direction; everything else mirrors."
- Spec §4, verbatim: "Numbers and times stay Western digits in both languages (they are timing values a reviewer compares with other tools)."
- Spec §4, verbatim: "The Arabic strings are drafted by the implementer and **must be reviewed by a native speaker before release**; the spec does not claim they are final."
- Tests never touch real user settings: build `Prefs` on a `QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)`.
- Tests that build a `JobListPanel` or `MainWindow` use the `no_default_job_dirs` fixture.
- Callbacks passed to `run_in_thread`/`BackgroundJobs` must be bound methods of UI-thread QObjects (a bare lambda runs on the worker thread).
- No telemetry: the app sends nothing (spec "Out of scope").
- Do not `pip install` anything.
- House style: why-docstrings, `from __future__ import annotations`, `__all__`, frozen `slots=True` dataclasses for value types.

## Files

| File | Responsibility | Task |
|---|---|---|
| `pyproject.toml` | `faulthandler_timeout` | 1 |
| `src/qurantext/gui/review/word_strip.py` | Ctrl (or Alt) detaches | 1 |
| `src/qurantext/gui/main_window.py` | after-close state; refuse review while re-matching; language footer + rebuild | 1, 4 |
| `src/qurantext/gui/i18n.py` | `tn`, plural rules, RTL isolation, `time_span`, `ltr`, `is_rtl`, `LANGUAGE_NAMES`, Arabic table | 2, 3 |
| `src/qurantext/gui/review/{selection_bar,warnings_strip,segment_list,window,export_dialog,session}.py`, `gui/home/job_list.py` | call sites for spans/plurals/framed errors | 2 |
| `src/qurantext/gui/language.py` (new) | `system_language`, `initial_language`, `apply_language` | 4 |
| `src/qurantext/gui/prefs.py` | `Prefs.language` | 4 |
| `src/qurantext/gui/app.py` | apply the language before the first window | 4 |
| `src/qurantext/gui/home/new_job.py` | `audio_path` property; mirrored More-options arrow | 4, 5 |
| `src/qurantext/gui/home/job_list.py`, `gui/review/{segment_list,window,selection_bar}.py` | RTL pins and alignment | 5 |
| `tests/conftest.py` | autouse language reset | 2 |
| `tests/test_i18n.py`, `tests/test_language.py` (new), `tests/test_rtl.py` (new), `tests/test_gui.py`, `tests/test_review_*.py`, `tests/test_home_panels.py` | tests | 1–5 |
| `README.md` | language paragraph | 4 |

---

### Task 1: The residuals Phase 3 carried

**Files:**
- Modify: `pyproject.toml` (`[tool.pytest.ini_options]`)
- Modify: `src/qurantext/gui/review/word_strip.py:197` (detach modifier), `src/qurantext/gui/i18n.py` (`review.shortcuts` text)
- Modify: `src/qurantext/gui/main_window.py` (`_on_finished`, `_on_failed`, `_on_cancelled`, `_open_review`)
- Test: `tests/test_review_widgets.py` (or wherever the Alt-drag test from Phase 3 lives — `grep -rn "AltModifier" tests`), `tests/test_gui.py`

**Interfaces:**
- Consumes: `project_path_for` (`jobs/project.py`), `match_path_for(spec)` (`gui/jobs.py`), `Prefs.unhide_job`, `Prefs.job_dirs`, `MainWindow._running_spec`, `MainWindow._closing`.
- Produces: i18n key `home.busy_matching` = "This job is being matched again; its review opens when that finishes." Nothing else later tasks rely on.

- [ ] **Step 1: Hang dumps.** Add `faulthandler_timeout = 120` to `[tool.pytest.ini_options]` in `pyproject.toml` (pytest's built-in option: a test running longer than 120 s dumps every thread's stack to stderr). The slowest test today takes a few seconds; check with `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q --durations=5`.

- [ ] **Step 2: Hunt the hang.** One of five full runs on the Phase 3 tip hung for >15 min with little CPU. Run the suite 8 times in a row, each under `timeout 600`, capturing output:

```bash
for i in 1 2 3 4 5 6 7 8; do QT_QPA_PLATFORM=offscreen timeout 600 venv/bin/python -m pytest -q -p no:randomly > /tmp/claude-1000/-home-khalil-PycharmProjects-QuranText/8df4d836-dab4-4c89-91cc-fa89e369f0e4/scratchpad/phase4/run_$i.log 2>&1; echo "run $i rc=$?"; done
```

(Drop `-p no:randomly` if the plugin is not installed.) If a run hangs, the faulthandler dump names the test and the stuck frame: fix the cause (typically a `QThread` wait, a `QEventLoop` without a timeout, or a `_wait_for` without a deadline) with a regression test where one is possible. If no run hangs, say so in the report with the eight run times; the faulthandler setting stays so the next hang explains itself. Timebox the hunt to this one loop plus the fix.

- [ ] **Step 3: Write the failing tests for the other three residuals.**

In the file that holds the Phase 3 Alt-drag test (it drags a joined edge with `Qt.KeyboardModifier.AltModifier` and asserts a gap opens), parametrize it over both modifiers:

```python
@pytest.mark.parametrize(
    "modifier", [Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.AltModifier]
)
def test_dragging_a_joined_edge_with_ctrl_or_alt_leaves_the_neighbour(qt_app, ..., modifier):
    ...  # the existing body, with `modifier` in place of AltModifier
```

In `tests/test_gui.py`, next to the Phase 3 "closing mid-job" tests (they use a blocked fake job and monkeypatch `QApplication.quit`; reuse their helpers):

```python
def test_a_job_finishing_after_close_still_lists_its_folder_and_unhides_it(
    qt_app, tmp_path, no_default_job_dirs, monkeypatch
) -> None:
    # A job with output_dir=tmp_path/"out" whose project was hidden earlier;
    # close the window while it runs, then let it finish.
    ...
    assert tmp_path / "out" in prefs.job_dirs
    assert project_path not in prefs.hidden_jobs
    assert window._reviews == {}  # still no review under a closed window


def test_opening_the_review_of_a_job_being_matched_again_is_refused(
    qt_app, tmp_path, no_default_job_dirs, monkeypatch
) -> None:
    # A project on disk; Start a blocked re-match of the same audio/range,
    # then double-click that project's row (or call window._open_review(path)).
    ...
    assert window._reviews == {}
    assert window.new_job.status_label.text() == t("home.busy_matching")
    # release the job: when it finishes its review opens as usual
    ...
    assert window._review_of(project_path) is not None
```

Use the real attribute names of the status line and of the blocked-job helper in `test_gui.py` (read the Phase 3 tests first; do not invent new helpers where one exists).

- [ ] **Step 4: Run them; see them fail.**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q tests/test_gui.py -k "after_close or matched_again" <alt-drag test file> -k "ctrl_or_alt"`
Expected: the Ctrl case FAILS (no gap), the after-close test FAILS on `job_dirs`, the re-match test FAILS (a review opens).

- [ ] **Step 5: Implement.**

`word_strip.py` — accept either modifier (Alt is taken for window moves on XFCE and Plasma 5, so Ctrl is the one that works everywhere; Alt keeps working where it can):

```python
#: Held while grabbing a joined edge: the edge leaves its neighbour behind.
#: Ctrl works on every desktop; Alt is taken for moving windows on some Linux ones.
_DETACH = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
...
            detach = bool(event.modifiers() & _DETACH)
```

Update the module docstring's "with Alt held" and the `_EdgeDrag.keep_joined` comment to say "Ctrl (or Alt)". In `i18n.py`, change the `review.shortcuts` wording from Alt-drag to "Ctrl-drag" (keep the rest of the sentence).

`main_window.py` — the state a finished job leaves behind is recorded even after close; only the UI is skipped:

```python
    def _on_finished(self, finished: _Finished) -> None:
        project = finished.project
        project_path = project.path or project_path_for(project.matches)
        # State, not UI: the list must show this job next launch, closed window or not.
        self._remember_output_dir()
        # Running a job again is asking for it: one removed from the list comes back.
        self._prefs.unhide_job(project_path)
        if self._closing:
            return  # no review, and no list, under a window that is going away
        ...  # unchanged from here
```

`_on_failed` / `_on_cancelled`: before their `if self._closing: return`, call `self._remember_matched_output()` — split the state half out of `_list_a_half_done_job` (the `_remember_output_dir()` for a render-right-away job whose matching saved a project) so it runs when closing, and keep the list refresh behind the `_closing` guard.

`_open_review` refuses the job being matched (the check lives here, not in `_show_review`, because `_on_finished` opens that same project through `_show_review` before `_on_done` clears `_running_spec`):

```python
    def _open_review(self, project_path: Path) -> None:
        """Open *project_path* for review, or say on the status line why it cannot be."""
        if self._is_being_matched(project_path):
            # Its file is about to be replaced; a review opened now would show the old
            # match, and saving it would overwrite the new one.
            self.new_job.show_status(t("home.busy_matching"))
            return
        problem = self._show_review(project_path)
        if problem is not None:
            self.new_job.show_status(problem)

    def _is_being_matched(self, project_path: Path) -> bool:
        spec = self._running_spec
        if spec is None:
            return False
        target = project_path_for(match_path_for(spec))
        return Path(target).resolve() == Path(project_path).resolve()
```

Add `"home.busy_matching": "This job is being matched again; its review opens when that finishes."` to `STRINGS["en"]` (the review opens when matching finishes only when "Render right away" is off — word it exactly as given; it is the common case and the status line says what happened when the job ends).

- [ ] **Step 6: Run them; see them pass.** Same command as Step 4. Expected: PASS.

- [ ] **Step 7: Full suite + ruff, then commit** (one commit per residual is fine):

```bash
QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q
venv/bin/ruff check src tests && venv/bin/ruff format --check src tests
git commit -m "Dump every thread's stack when a test runs past two minutes" ...
git commit -m "Let Ctrl detach a joined edge, since Alt moves windows on some desktops" ...
git commit -m "Record a job's folder and unhide it even when it finishes after the window closed" ...
git commit -m "Refuse to open the review of a job that is being matched again" ...
```

(each with the blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`).

---

### Task 2: i18n engine — plurals, isolation, one-value time spans, framed errors (English only)

**Files:**
- Modify: `src/qurantext/gui/i18n.py`
- Modify: `src/qurantext/gui/review/selection_bar.py:52-55`, `src/qurantext/gui/review/warnings_strip.py:60-75`, `src/qurantext/gui/review/segment_list.py:126`, `src/qurantext/gui/home/job_list.py:284`, `src/qurantext/gui/review/export_dialog.py:195-215`, `src/qurantext/gui/review/window.py:693-695`, `src/qurantext/gui/review/session.py:493,646`
- Modify: `tests/conftest.py` (autouse reset), `tests/test_i18n.py`
- Test: `tests/test_i18n.py`, the existing widget tests that read these strings

**Interfaces:**
- Consumes: nothing new.
- Produces (Tasks 3–5 rely on these exact names, all exported in `i18n.__all__`):
  - `RTL_LANGUAGES: frozenset[str]` = `frozenset({"ar"})`
  - `LANGUAGE_NAMES: dict[str, str]` = `{"en": "English", "ar": "العربية"}` (each language in its own name; never translated)
  - `is_rtl(code: str | None = None) -> bool` (default: the current language)
  - `t(key: str, **fmt) -> str` (unchanged signature; isolates formatted values when RTL)
  - `tn(key: str, count: int, **fmt) -> str` (plural-aware; passes `count` into the format)
  - `plural_category(language: str, n: int) -> str` — one of `zero one two few many other`
  - `time_span(start: float, end: float, *, digits: int = 2, sep: str = "–") -> str`
  - `ltr(text: str) -> str` — `text` wrapped in LRI…PDI when the current language is RTL, else unchanged
  - Table type: `STRINGS: dict[str, dict[str, str | dict[str, str]]]` — a plural key maps to `{category: text}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_i18n.py` (keep the existing four; rewrite the placeholder-parity test as below):

```python
import string

from qurantext.gui.i18n import (
    LANGUAGE_NAMES, RTL_LANGUAGES, is_rtl, ltr, plural_category, set_language, t, time_span, tn,
)

_FSI, _PDI, _LRI = "⁨", "⁩", "⁦"
_CALL = re.compile(r"""\btn?\(\s*["']([a-z0-9_.]+)["']""")


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _variants(value):
    return value.values() if isinstance(value, dict) else [value]


@pytest.mark.parametrize(
    ("n", "category"),
    [(0, "zero"), (1, "one"), (2, "two"), (3, "few"), (10, "few"), (11, "many"),
     (99, "many"), (100, "other"), (102, "other"), (103, "few"), (111, "many")],
)
def test_arabic_plural_categories(n, category) -> None:
    assert plural_category("ar", n) == category


def test_english_plural_categories() -> None:
    assert [plural_category("en", n) for n in (0, 1, 2)] == ["other", "one", "other"]


def test_tn_picks_the_variant_and_formats_count() -> None:
    i18n.STRINGS["en"]["test.files"] = {"one": "{count} file", "other": "{count} files"}
    try:
        assert tn("test.files", 1) == "1 file"
        assert tn("test.files", 3) == "3 files"
    finally:
        del i18n.STRINGS["en"]["test.files"]


def test_t_refuses_a_plural_key() -> None:
    i18n.STRINGS["en"]["test.files"] = {"one": "{count} file", "other": "{count} files"}
    try:
        with pytest.raises(TypeError):
            t("test.files", count=2)
    finally:
        del i18n.STRINGS["en"]["test.files"]


def test_values_are_isolated_only_in_a_right_to_left_language(monkeypatch) -> None:
    monkeypatch.setitem(i18n.STRINGS, "rtl_test", {"test.gap": "gap {span} s"})
    monkeypatch.setattr(i18n, "RTL_LANGUAGES", frozenset({"rtl_test"}))
    monkeypatch.setattr(i18n, "LANGUAGES", (*i18n.LANGUAGES, "rtl_test"))
    i18n.STRINGS["en"]["test.gap"] = "gap {span} s"
    try:
        assert t("test.gap", span=time_span(1.5, 2.25)) == "gap 1.50–2.25 s"
        set_language("rtl_test")
        assert t("test.gap", span=time_span(1.5, 2.25)) == f"gap {_FSI}1.50–2.25{_PDI} s"
        assert ltr("1.50") == f"{_LRI}1.50{_PDI}"
        assert is_rtl()
    finally:
        set_language("en")
        del i18n.STRINGS["en"]["test.gap"]
    assert ltr("1.50") == "1.50"
    assert not is_rtl()


def test_format_specs_still_apply_inside_isolation(monkeypatch) -> None:
    ...  # same set-up as above with "{duration:.1f} s": RTL result is f"{_FSI}3.2{_PDI} s"


def test_time_span_formats_one_value() -> None:
    assert time_span(12.3, 15.2) == "12.30–15.20"
    assert time_span(1.0, 2.0, digits=1, sep=" → ") == "1.0 → 2.0"


def test_language_names_cover_every_language() -> None:
    assert set(i18n.LANGUAGES) <= set(LANGUAGE_NAMES)
    assert RTL_LANGUAGES <= set(LANGUAGE_NAMES)


def test_every_language_has_the_same_keys_and_placeholders() -> None:
    english = i18n.STRINGS["en"]
    for language in i18n.LANGUAGES:
        table = i18n.STRINGS[language]
        assert set(table) == set(english), language
        for key, text in english.items():
            value = table[key]
            assert isinstance(value, dict) == isinstance(text, dict), key
            if isinstance(text, dict):
                assert {"one", "other"} <= set(text), key
                needed = set(_PLURAL_CATEGORIES[language])
                assert needed <= set(value), (language, key)
                # "other" carries every field; a variant may drop {count} ("one file")
                assert _fields(value["other"]) == _fields(text["other"]), (language, key)
                for variant in value.values():
                    assert _fields(variant) <= _fields(text["other"]), (language, key)
            else:
                assert _fields(value) == _fields(text), (language, key)
```

with `_PLURAL_CATEGORIES = {"en": ("one", "other"), "ar": ("zero", "one", "two", "few", "many", "other")}` in the test file (the test only enforces what each language needs). Fix `test_every_key_the_code_uses_exists_in_every_language` to use the new `_CALL` so `tn(` calls count.

Add the call-site tests — update the existing widget tests that assert the English text of these strings to the new wording (below), and add:

```python
def test_the_selection_bar_shows_the_span_as_one_value(qt_app) -> None:
    bar = SelectionBar()
    bar.show_word(TimelineWord(... text="ٱلۡحَمۡدُ", start=1.5, end=2.25 ...))
    assert bar.label.text() == "ٱلۡحَمۡدُ  1.50 → 2.25 s"
```

(construct `TimelineWord` the way the existing selection-bar test does.)

- [ ] **Step 2: Run; see them fail.**
Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q tests/test_i18n.py`
Expected: ImportError on `tn` / `time_span` etc.

- [ ] **Step 3: Implement `i18n.py`.** Keep the module Qt-free. Core of it:

```python
import string

#: Languages written right to left: their layout mirrors, and every value
#: formatted into their sentences is isolated so it keeps its own direction.
RTL_LANGUAGES = frozenset({"ar"})

#: Each language by its own name, for the language menu; never translated.
LANGUAGE_NAMES = {"en": "English", "ar": "العربية"}

_FSI, _LRI, _PDI = "⁨", "⁦", "⁩"


class _Isolating(string.Formatter):
    """Wraps every formatted value in FSI…PDI.

    Without it a time range inside an Arabic sentence ("12.3–15.2") is laid out
    as "15.2–12.3", and a Latin file name drags the words around it out of order.
    FSI gives each value the direction of its own first strong letter, and a
    value with none (a number, a range of times) runs left to right.
    """

    def format_field(self, value: object, format_spec: str) -> str:
        return _FSI + super().format_field(value, format_spec) + _PDI


_ISOLATING = _Isolating()


def is_rtl(code: str | None = None) -> bool:
    return (code or _current) in RTL_LANGUAGES


def plural_category(language: str, n: int) -> str:
    """CLDR's cardinal category of *n* in *language* (only the two we ship)."""
    n = abs(int(n))
    if language == "ar":
        if n == 0:
            return "zero"
        if n == 1:
            return "one"
        if n == 2:
            return "two"
        if 3 <= n % 100 <= 10:
            return "few"
        if 11 <= n % 100 <= 99:
            return "many"
        return "other"
    return "one" if n == 1 else "other"


def _lookup(key: str) -> tuple[str, str | dict[str, str]] | None:
    for language in (_current, "en"):
        value = STRINGS.get(language, {}).get(key)
        if value:
            return language, value
    return None


def _format(text: str, fmt: dict[str, object]) -> str:
    if not fmt:
        return text
    return _ISOLATING.format(text, **fmt) if is_rtl() else text.format(**fmt)


def t(key: str, **fmt: object) -> str:
    found = _lookup(key)
    if found is None:
        return key
    _, value = found
    if isinstance(value, dict):
        raise TypeError(f"{key!r} depends on a count; use tn({key!r}, count).")
    return _format(value, fmt)


def tn(key: str, count: int, **fmt: object) -> str:
    """*key*'s text for *count* things, in the current language's plural form."""
    found = _lookup(key)
    if found is None:
        return key
    language, value = found
    if isinstance(value, str):
        return _format(value, {"count": count, **fmt})
    text = value.get(plural_category(language, count)) or value["other"]
    return _format(text, {"count": count, **fmt})


def time_span(start: float, end: float, *, digits: int = 2, sep: str = "–") -> str:
    """Two times as one value, so a sentence in any language keeps them in order."""
    return f"{start:.{digits}f}{sep}{end:.{digits}f}"


def ltr(text: str) -> str:
    """*text* forced left to right inside right-to-left surroundings (a table cell of times)."""
    return f"{_LRI}{text}{_PDI}" if is_rtl() else text
```

Note `set_language` checks `STRINGS`; `LANGUAGES = tuple(STRINGS)` stays.

- [ ] **Step 4: Change the English templates and call sites.**

| Key | New English value | Call site |
|---|---|---|
| `review.selected` | `"{word}  {span} s"` | `selection_bar.py`: `t("review.selected", word=word.text, span=time_span(word.start, word.end, sep=" → "))` |
| `review.gap` | `"{duration:.1f} s at {span} s"` | `warnings_strip.py`: `t("review.gap", duration=gap.duration, span=time_span(gap.start, gap.end, digits=1))` |
| `review.gaps` | `{"one": "{count} stretch of speech has no word:", "other": "{count} stretches of speech have no word:"}` | `tn("review.gaps", len(self._gaps))` |
| `review.more_gaps` | `{"one": "…and {count} more", "other": "…and {count} more"}` | `tn("review.more_gaps", hidden)` |
| `home.cards` | `{"one": "{count} card", "other": "{count} cards"}` | `job_list.py`: `tn("home.cards", entry.card_count)` |
| `export.done` | `{"one": "Wrote {count} file:", "other": "Wrote {count} files:"}` | `export_dialog.py`: `tn("export.done", len(written))` |
| `home.finished.matched` and any other `{count}` key with "(s)" | split into `one`/`other` the same way | `tn(...)` |

Find every other `{count}`/"(s)" string with `grep -n "(s)\|{count" src/qurantext/gui/i18n.py` and convert it the same way.

Segment list time cell: `self._set_item(row, _COLUMN_TIME, ltr(time_span(start, end)), kind, index, editable=False)`.

Concatenations (two sentences glued with an f-string) become templates:
- `export_dialog.py:130` → `t("export.match_video_stale")` = "Match the video's timeline (rendered before your latest changes)" — then delete `export.stale` if nothing else uses it; keep `export.match_video` for the fresh case.
- `export_dialog.py:211` → `tn("export.done", len(written), names=names)` with the English values `"Wrote {count} file: {names}"` / `"Wrote {count} files: {names}"`.

Framed errors — the sentence is translated; the details (from the OS or core) stay as they are:
- `window.py:694`: `QMessageBox.warning(self, t("review.save"), t("review.save_failed", details=str(error)))`, `"review.save_failed": "The corrections were not saved: {details}"`.
- `export_dialog.py:195`: show `t("export.failed", details=str(error))` = "The subtitles were not written: {details}" (if the dialog already frames it, keep that key).
- `session.py:493`: `raise ValueError(t("session.card_follows_words"))` = "This card's times follow its words; retime the words instead."; `session.py:646`: `t("session.no_file")` = "This project has no file to write back to." (`session.py` may import `gui.i18n` — it is Qt-free.)

- [ ] **Step 5: Autouse reset** in `tests/conftest.py` so a failing test cannot leave the next one in Arabic:

```python
@pytest.fixture(autouse=True)
def _english_left_to_right():
    """Every test starts, and leaves, in English laid out left to right."""
    from qurantext.gui import i18n

    yield
    i18n.set_language("en")
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
    except ModuleNotFoundError:
        return
    app = QApplication.instance()
    if app is not None:
        app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
```

(Task 4 extends it to remove Qt translators; leave a one-line comment saying so.)

- [ ] **Step 6: Run; see them pass.** `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q tests/test_i18n.py tests/test_review_*.py tests/test_home_panels.py` → PASS; then the full suite.

- [ ] **Step 7: Commit.**
`Give counts their plural forms and times one value, so another language can order them` (and, separately if you like, `Frame the errors a person sees in a translated sentence`).

---

### Task 3: The Arabic table

**Files:**
- Modify: `src/qurantext/gui/i18n.py` (add `STRINGS["ar"]`)
- Test: `tests/test_i18n.py` (parity tests from Task 2 now cover `ar`)

**Interfaces:**
- Consumes: the table format from Task 2 (plural keys are dicts; `ar` plural keys carry all six categories).
- Produces: `STRINGS["ar"]` with every `STRINGS["en"]` key; `"ar" in LANGUAGES`.

- [ ] **Step 1: Write the failing test.**

```python
def test_arabic_is_a_language() -> None:
    assert "ar" in i18n.LANGUAGES
    assert i18n.is_rtl("ar")


def test_arabic_plural_keys_have_every_category() -> None:
    for key, value in i18n.STRINGS["en"].items():
        if isinstance(value, dict):
            assert set(i18n.STRINGS["ar"][key]) >= {"zero", "one", "two", "few", "many", "other"}, key


def test_arabic_differs_from_english_where_it_should() -> None:
    """A copied English string is a missed translation; only codes and symbols may match."""
    same_ok = {"format.srt", "format.vtt", "format.ass", "review.rate", "review.minus", "review.plus"}
    for key, text in i18n.STRINGS["en"].items():
        if key in same_ok or isinstance(text, dict):
            continue
        assert i18n.STRINGS["ar"][key] != text, key
```

Adjust `same_ok` to the keys that genuinely have no words (format names, `{rate:g}×`, "−50 ms" if you keep "ms" — Arabic may write "−50 م.ث"; decide per key and list only those you leave identical).

- [ ] **Step 2: Run; see it fail.** `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q tests/test_i18n.py` → FAIL (`ar` missing).

- [ ] **Step 3: Write `STRINGS["ar"]`**, in the same order and grouping as `STRINGS["en"]`, directly below it, headed by:

```python
    # Drafted for the first release; a native speaker must review every line
    # before it ships (spec §4). Keep the order and grouping of "en".
    "ar": {
```

Guidance for the drafting:
- Modern Standard Arabic, plain and short, the register of a well-made desktop app; address the person with the imperative ("اختر", "احفظ"), not the polite third person.
- Terms, used consistently: job مهمة, review مراجعة, render «إخراج الفيديو», recitation تلاوة, lecture محاضرة, card بطاقة, caption/subtitle ترجمة/تعليق → use «ترجمة نصية» for subtitles and «تعليق» for a lecture caption line, word كلمة, ayah آية (plural آيات), surah سورة, waveform الموجة الصوتية, playhead مؤشر التشغيل, undo تراجع, redo إعادة.
- Keep every `{placeholder}` and its format spec exactly (`{rate:g}`, `{duration:.1f}`); keep "SRT", "VTT", "ASS", "PySide6-Addons", "Qalun" in Latin letters.
- Seconds: «ث»; milliseconds: «م.ث» or keep "ms" — choose one and use it everywhere.
- Plural keys: all six categories, e.g. `home.cards`:
  `{"zero": "لا بطاقات", "one": "بطاقة واحدة", "two": "بطاقتان", "few": "{count} بطاقات", "many": "{count} بطاقة", "other": "{count} بطاقة"}`.
- Western digits only: never write ٠–٩ in the table.
- The ellipsis stays "…"; the arrow in `review.selected` comes from code (`time_span(..., sep=" → ")`), not the table.

- [ ] **Step 4: Run; see it pass.** `tests/test_i18n.py` → PASS; full suite.

- [ ] **Step 5: Commit.** `Add the Arabic table, drafted for a native speaker's review`.

---

### Task 4: Choosing and applying a language

**Files:**
- Create: `src/qurantext/gui/language.py`
- Modify: `src/qurantext/gui/prefs.py` (`language` property), `src/qurantext/gui/app.py`, `src/qurantext/gui/main_window.py` (footer + switch + rebuild), `src/qurantext/gui/home/new_job.py` (`audio_path` property), `src/qurantext/gui/i18n.py` (new keys), `tests/conftest.py` (translator cleanup), `README.md`, `docs/superpowers/specs/2026-09-23-review-editor-design.md` (already amended by the controller — do not edit)
- Test: `tests/test_language.py` (new), `tests/test_prefs.py`, `tests/test_gui.py`

**Interfaces:**
- Consumes: `i18n.set_language`, `i18n.is_rtl`, `i18n.LANGUAGES`, `i18n.LANGUAGE_NAMES` (Task 2), `STRINGS["ar"]` (Task 3).
- Produces:
  - `Prefs.language: str | None` (None = follow the system; setter accepts a code in `LANGUAGES` or None; an unknown stored value reads as None).
  - `language.system_language(locale_name: str | None = None) -> str` — `"ar"` when the locale name starts with `ar`, else `"en"`; default reads `QLocale.system().name()`.
  - `language.initial_language(prefs: Prefs, locale_name: str | None = None) -> str`.
  - `language.apply_language(app: QApplication, code: str) -> None`.
  - `MainWindow.language_combo: QComboBox` (itemData = code), `MainWindow.set_language(code: str) -> bool` (True when applied).
  - `NewJobPanel.audio_path: Path | None` (read-only property).

- [ ] **Step 1: Write the failing tests** — `tests/test_language.py`:

```python
from PySide6.QtCore import QLocale, QSettings, Qt
from PySide6.QtWidgets import QApplication, QSpinBox

from qurantext.gui import i18n
from qurantext.gui.language import apply_language, initial_language, system_language
from qurantext.gui.prefs import Prefs


def _prefs(tmp_path):
    return Prefs(QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat))


@pytest.mark.parametrize(("name", "code"), [("ar_EG", "ar"), ("ar", "ar"), ("de_DE", "en"), ("C", "en")])
def test_the_system_locale_picks_the_default(name, code) -> None:
    assert system_language(name) == code


def test_a_chosen_language_wins_over_the_system(tmp_path) -> None:
    prefs = _prefs(tmp_path)
    assert initial_language(prefs, "ar_SA") == "ar"
    prefs.language = "en"
    assert initial_language(prefs, "ar_SA") == "en"


def test_applying_arabic_mirrors_the_app_and_back(qt_app) -> None:
    apply_language(QApplication.instance(), "ar")
    assert i18n.current_language() == "ar"
    assert QApplication.layoutDirection() == Qt.LayoutDirection.RightToLeft
    apply_language(QApplication.instance(), "en")
    assert i18n.current_language() == "en"
    assert QApplication.layoutDirection() == Qt.LayoutDirection.LeftToRight


def test_numbers_stay_western_in_arabic(qt_app) -> None:
    apply_language(QApplication.instance(), "ar")
    box = QSpinBox()
    box.setRange(0, 300)
    box.setValue(286)
    assert box.text() == "286"


def test_qt_own_buttons_follow_the_language(qt_app) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    apply_language(QApplication.instance(), "ar")
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    assert box.button(QDialogButtonBox.StandardButton.Cancel).text() != "Cancel"
```

(Skip the last test with a clear reason if `qtbase_ar.qm` is not in `QLibraryInfo.path(TranslationsPath)`.)

`tests/test_prefs.py`: `language` round-trips `"ar"`, `None`, and an unknown stored value reads as `None`.

`tests/test_gui.py`:

```python
def test_switching_to_arabic_rebuilds_the_home_window(qt_app, tmp_path, no_default_job_dirs) -> None:
    prefs = _prefs(tmp_path)  # the file's existing helper
    window = MainWindow(prefs=prefs)
    window.new_job.set_audio(AUDIO)  # any existing file
    assert window.set_language("ar")
    assert prefs.language == "ar"
    assert window.windowTitle() == i18n.STRINGS["ar"]["app.title"]
    assert window.job_list.findChild(QLabel).text() != i18n.STRINGS["en"]["home.jobs"]  # rebuilt
    assert window.new_job.audio_path == AUDIO  # the half-filled form survives
    assert window.language_combo.currentData() == "ar"


def test_the_language_does_not_change_while_a_review_is_open(qt_app, tmp_path, no_default_job_dirs) -> None:
    ...  # open a review (window._open_review(project_path) on a saved project)
    assert not window.set_language("ar")
    assert i18n.current_language() == "en"
    assert window.new_job.status_label.text() == t("home.language_busy")
    assert window.language_combo.currentData() == "en"  # the combo snaps back


def test_the_language_does_not_change_while_a_job_runs(...) -> None:
    ...  # the blocked fake job from Phase 3's tests; same three asserts
```

- [ ] **Step 2: Run; see them fail.** `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q tests/test_language.py tests/test_prefs.py tests/test_gui.py -k "language"` → ImportError / AttributeError.

- [ ] **Step 3: Implement `gui/language.py`:**

```python
"""Put the window into one of its languages.

A language is more than a table of words: Arabic mirrors the layout, Qt's own
buttons and dialogs need their translation loaded, and numbers must stay
Western digits in both (they are timings a reviewer compares with other tools),
which Qt would otherwise draw in the system locale's digits.
"""

from __future__ import annotations

from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTranslator
from PySide6.QtWidgets import QApplication

from qurantext.gui import i18n
from qurantext.gui.prefs import Prefs

__all__ = ["apply_language", "initial_language", "system_language"]

#: Qt's own translation for the language in use, kept so the next switch can remove it.
_qt_translator: QTranslator | None = None


def system_language(locale_name: str | None = None) -> str:
    name = locale_name if locale_name is not None else QLocale.system().name()
    return "ar" if name.lower().startswith("ar") else "en"


def initial_language(prefs: Prefs, locale_name: str | None = None) -> str:
    return prefs.language or system_language(locale_name)


def apply_language(app: QApplication, code: str) -> None:
    global _qt_translator
    i18n.set_language(code)  # raises on an unknown code before anything changes
    if _qt_translator is not None:
        app.removeTranslator(_qt_translator)
        _qt_translator = None
    if code != "en":
        translator = QTranslator(app)
        folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if translator.load(f"qtbase_{code}", folder):
            app.installTranslator(translator)
            _qt_translator = translator
    # After the translator: installing one may set a direction of its own.
    QLocale.setDefault(QLocale.c())
    app.setLayoutDirection(
        Qt.LayoutDirection.RightToLeft if i18n.is_rtl(code) else Qt.LayoutDirection.LeftToRight
    )
```

Expose a `reset_for_tests()`? No — extend the conftest autouse fixture instead: after the test, `apply_language(app, "en")` when a `QApplication` exists (this removes the translator and restores direction), else `i18n.set_language("en")`.

`Prefs.language` follows the existing optional-value properties in `prefs.py` (key `"language"`; stored as the code or removed for None).

`app.py`, after `QApplication(...)` and before `MainWindow()`:

```python
    from qurantext.gui.language import apply_language, initial_language
    from qurantext.gui.prefs import Prefs

    prefs = Prefs()
    apply_language(app, initial_language(prefs))
    window = MainWindow(prefs=prefs)
```

`main_window.py`:
- `_build()` adds a footer row under the splitter: stretch, `QLabel(t("home.language"))`, `self.language_combo` with one item per `i18n.LANGUAGES`, text `LANGUAGE_NAMES[code]`, data `code`; current = `i18n.current_language()`; `activated` → `self._language_chosen`. Build the combo inside `_build()` so a rebuild makes a fresh one.
- `set_language(code) -> bool`:

```python
    def set_language(self, code: str) -> bool:
        """Switch the window's language; refuse while anything could lose its place.

        A review window holds unsaved corrections and a job its progress rows;
        rebuilding under them is where things would go missing, and switching a
        language is rare enough to ask for a quiet moment.
        """
        if code == i18n.current_language():
            return True
        if self._reviews or self._cancel is not None:
            self._select_language_in_combo(i18n.current_language())
            self.new_job.show_status(t("home.language_busy"))
            return False
        audio = self.new_job.audio_path
        apply_language(QApplication.instance(), code)
        self._prefs.language = code
        self.setWindowTitle(t("app.title"))
        old = self.centralWidget()
        self._build()  # fresh panels in the new language, from prefs
        old.deleteLater()
        if audio is not None:
            self.new_job.set_audio(audio)
        return True
```

(`_build()` currently also calls `self.resize(1024, 680)`; move the resize to `__init__` so a rebuild keeps the person's window size, and keep the splitter sizes proportional.)
- New keys: `"home.language": "Language"`, `"home.language_busy": "Close the open reviews and wait for the job to finish before changing the language."` — with their Arabic in `STRINGS["ar"]`.

`new_job.py`: `audio_path` property returning `self._audio`.

`README.md` "The window" section: one paragraph — the window is in English or Arabic, following the system language until one is chosen at the bottom of the home window; Arabic lays the window out right to left, while waveforms and timelines keep time running left to right; the Arabic text is a draft awaiting review by a native speaker.

- [ ] **Step 4: Run; see them pass;** then the full suite (the autouse fixture must keep every other test in English).

- [ ] **Step 5: Commit.**
`Start in the system's language, remember a chosen one, and switch the home window in place`.

---

### Task 5: Right to left, everywhere it should be and nowhere it should not

**Files:**
- Modify: `src/qurantext/gui/home/job_list.py:106` (remove the LTR pin), `src/qurantext/gui/home/new_job.py:216,533` (arrow), `src/qurantext/gui/review/segment_list.py:48,128` (unpin; alignment), `src/qurantext/gui/review/window.py` (`time_label` and `rate_combo` pins), `src/qurantext/gui/review/selection_bar.py` (nudge buttons pinned)
- Test: `tests/test_rtl.py` (new)

**Interfaces:**
- Consumes: `apply_language` (Task 4), `ltr`/`time_span` (Task 2), the Arabic table (Task 3).
- Produces: `SelectionBar.nudge_row: QWidget` (the pinned container of −/+/Snap). Nothing else.

- [ ] **Step 1: Write the failing tests** — `tests/test_rtl.py`, all in Arabic via `apply_language(QApplication.instance(), "ar")` at the start of each test (the autouse fixture restores English):

```python
LTR = Qt.LayoutDirection.LeftToRight
RTL = Qt.LayoutDirection.RightToLeft


def test_time_widgets_keep_left_to_right_and_the_rest_mirrors(qt_app, review_window) -> None:
    w = review_window  # a ReviewWindow on a small recitation project, built AFTER apply_language("ar")
    for widget in (w.waveform, w.strip, w.zoom_slider, w.frame_view, w.time_label, w.selection_bar.nudge_row):
        assert widget.layoutDirection() == LTR, widget
    for widget in (w, w.segment_list, w.warnings, w.save_button):
        assert widget.layoutDirection() == RTL, widget


def test_arrow_keys_step_time_the_same_way_in_arabic(qt_app, review_window) -> None:
    w = review_window
    w.seek(5.0)
    QTest.keyClick(w, Qt.Key.Key_Left)
    assert w.player.position() < 5.0  # Left is earlier on a left-to-right time axis


def test_the_minus_button_sits_left_of_plus(qt_app, review_window) -> None:
    bar = review_window.selection_bar
    bar.show(); qt_app.processEvents()
    assert bar.minus_button.x() < bar.plus_button.x()


def test_segment_times_are_isolated_and_text_aligns_to_its_script(qt_app, review_window) -> None:
    table = review_window.segment_list
    time_text = table.item(0, 1).text()
    assert time_text.startswith("⁦") and time_text.endswith("⁩")
    alignment = table.item(0, 2).textAlignment()
    assert alignment & Qt.AlignmentFlag.AlignAbsolute
    assert alignment & Qt.AlignmentFlag.AlignRight  # Quran text is Arabic: its right edge


def test_a_latin_caption_aligns_left(qt_app, lecture_review_window) -> None:
    ...  # a caption row whose text is "Hello" → AlignLeft | AlignAbsolute


def test_the_job_list_mirrors(qt_app, tmp_path, no_default_job_dirs) -> None:
    panel = JobListPanel(_prefs(tmp_path))
    assert panel.list.layoutDirection() == RTL


def test_more_options_points_the_way_arabic_reads(qt_app, tmp_path, store, no_default_job_dirs) -> None:
    panel = NewJobPanel(_prefs(tmp_path), quran_default=QURAN_FILE)
    panel.more_button.setChecked(False)
    assert panel.more_button.arrowType() == Qt.ArrowType.LeftArrow
    panel.more_button.setChecked(True)
    assert panel.more_button.arrowType() == Qt.ArrowType.DownArrow


def test_no_english_is_left_in_the_arabic_windows(qt_app, tmp_path, no_default_job_dirs, review_window) -> None:
    """Every word a person reads comes from the Arabic table (or is a name, a code, a number)."""
    english = {
        text for key, text in i18n.STRINGS["en"].items()
        if isinstance(text, str) and "{" not in text and text != i18n.STRINGS["ar"][key]
    }
    main = MainWindow(prefs=_prefs(tmp_path))
    for root in (main, review_window, review_window._make_export_dialog()):
        shown = set(_texts(root))
        assert not (shown & english), (root, sorted(shown & english))
```

with a `_texts(root)` helper that yields `windowTitle()`, and for every descendant: `QLabel.text()`, `QAbstractButton.text()`, `QGroupBox.title()`, `toolTip()`, `QLineEdit.placeholderText()`, every `QComboBox.itemText(i)`, every `QTableWidget.horizontalHeaderItem(i).text()`. Build `review_window` / `lecture_review_window` fixtures in `tests/test_rtl.py` the way `tests/test_review_window.py` builds its windows (FakePlayer, a small project in `tmp_path`), **after** `apply_language(..., "ar")`.

- [ ] **Step 2: Run; see them fail.** `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q tests/test_rtl.py` → FAIL (job list pinned, time label mirrored, arrow RightArrow, alignment not absolute, …). If the "no English left" test lists strings, those are the bugs to fix — a hard-coded string moves into the tables; a Qt string (standard buttons) comes from Task 4's translator.

- [ ] **Step 3: Implement.**
- `job_list.py:106`: remove `self.list.setLayoutDirection(LeftToRight)` (it was a Phase 3 stopgap). Row labels take the layout's direction; a job name keeps its own letters' direction (QLabel detects it).
- `segment_list.py`: remove the pin at `:48`. Time cells already use `ltr(time_span(...))` (Task 2). Text cells align to their own script, absolutely:

```python
def _text_alignment(text: str) -> Qt.AlignmentFlag:
    """The edge a line of *text* starts from, whatever the window's direction.

    Quran text is Arabic and reads from the right in an English window too; a
    Latin lecture caption reads from the left in an Arabic one. AlignAbsolute
    stops Qt from mirroring the edge with the layout.
    """
    edge = Qt.AlignmentFlag.AlignRight if _starts_right_to_left(text) else Qt.AlignmentFlag.AlignLeft
    return edge | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
```

where `_starts_right_to_left(text)` returns True when the first character whose `unicodedata.bidirectional()` is `L`, `R` or `AL` is `R`/`AL` (False for none). Use it at `:128` in place of the fixed `AlignRight`.
- `window.py`: `self.time_label.setLayoutDirection(LeftToRight)`; the transport row itself mirrors (Play may move to the right in Arabic).
- `selection_bar.py`: put `minus_button`, `plus_button`, `snap_button` in `self.nudge_row = QWidget()` with its own `QHBoxLayout` (zero margins), `self.nudge_row.setLayoutDirection(Qt.LayoutDirection.LeftToRight)` — they move time, so earlier stays on the left; the label stays outside it and mirrors.
- `new_job.py:216,533`: the collapsed arrow is `LeftArrow` when `self.layoutDirection() == RightToLeft` (or `QApplication.isRightToLeft()`), else `RightArrow`; expanded stays `DownArrow`. Put the choice in one helper used at both places.

- [ ] **Step 4: Run; see them pass;** full suite; ruff.

- [ ] **Step 5: Screenshots for the controller.** Write a short script in the scratchpad (`…/scratchpad/phase4/shots.py`) that, offscreen, applies Arabic, builds the home window at 1280×800 and a review window on the real `furquanTra7-11` project (if present under `output/`; else the test project) at 1280×800, and saves `…/scratchpad/phase4/home_ar.png`, `…/scratchpad/phase4/review_ar.png`, plus `home_en.png` for comparison. Look at them: time ranges read earlier→later left to right, the job list and form mirror, no clipped Arabic, no English left. Fix what you see, then re-take.

- [ ] **Step 6: Commit.**
`Lay the window out right to left in Arabic, keeping time left to right`.

---

## Self-review notes (controller)

- Spec §4 coverage: table + `t` (existing) ✓; language in QSettings, default from system locale → Task 4 ✓; RTL direction → Tasks 4–5 ✓; waveform/strip/time fields pinned LTR → Task 5 test ✓; Western digits → Task 4 (`QLocale.c()`) + Task 3 rule ✓; parity test → Task 2 ✓; native-speaker caveat → Task 3 header + README ✓; "switching rebuilds the open windows in place" → narrowed by ruling to the home window while no review is open and no job runs (spec amended).
- Phase 2/3 deferred RTL items: segment list pin + hard-coded alignment (T5), mirrored time ranges (T2 `time_span` + isolation), `review.selected` mixing Arabic and times (T2), `time_label` (T5), core/session errors (T2 framing; `timing_edit`'s own messages stay English — core is language-free and they are programming errors, not a person's), job list pin (T5), More-options arrow (T5), concatenations (T2), plurals (T2), switching rebuild + `Prefs.language` (T4).
- Phase 5 notes (not this plan): the `qtbase_ar.qm` file must be collected by PyInstaller; an Arabic-capable UI font must exist on each platform (Windows/macOS ship one; Linux usually Noto).

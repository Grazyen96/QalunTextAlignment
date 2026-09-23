# Review editor — Phase 3: the home window — Implementation Plan

> **For agentic workers:** execute task by task. Per Khalil's instruction (2026-09-23) there is **no per-task review in this phase** — each task is implemented, tested and committed, and one whole-branch review with one fix wave runs at the end. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the single-form main window with a home window: a list of every job with its state on the left, a "New job" panel on the right (drop zone, Recitation | Lecture toggle, surah/ayat, readable video sizes, collapsible More options), where Start runs matching and opens the review — plus the three items Phase 2 handed over.

**Architecture:** The job's choices (video size, subtitles mode, formats, output folder) are written into `project.export` when matching finishes and read back through one helper, so the review renders what was chosen. The window's remembered settings live in a small injectable `Prefs` wrapper around `QSettings`, so tests never touch the user's real settings. The home window is two focused panels (`gui/home/job_list.py`, `gui/home/new_job.py`) that `MainWindow` wires together; neither panel runs jobs.

**Tech Stack:** Python 3.10+, PySide6 (QtMultimedia now installed), pytest offscreen.

**Spec:** `docs/superpowers/specs/2026-09-23-review-editor-design.md` §3 (home window), with §1.4 (job flow). Phase 2 ledger: `.superpowers/sdd/2026-09-23-review-editor-phase2-editor/progress.md` (carried rulings F5 and the two residuals).

## Global Constraints

- Python 3.10+; `venv/bin/ruff check src tests` and `venv/bin/ruff format --check src tests` clean (ruff==0.15.13, line length 100).
- `core/` never imports `jobs/` or `gui/`; `gui/review/session.py` and `gui/prefs.py`'s pure parts stay Qt-light (`prefs.py` may import `QSettings` only).
- Every user-visible string in `gui/` goes through `qurantext.gui.i18n.t(key, **fmt)` — including all of `main_window.py`, which today still has English literals. English table only in this phase.
- Tests never read or write the real user settings: every `Prefs` in tests is built on a `QSettings` INI file in `tmp_path`.
- Quran text is never editable. Times rounded to 3 decimals when written.
- Bare lambdas passed as `run_in_thread`/`BackgroundJobs` callbacks run on the worker thread — callbacks must be bound methods of UI-thread QObjects.
- Commit messages: plain-sentence subject, blank line, `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Tests: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q`.

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `src/qurantext/jobs/project.py` | modify | `JobSettings`, `job_settings(project)`, `set_job_settings(project, settings)` |
| `src/qurantext/gui/jobs.py` | modify | `run_matching` records the spec's choices; `run_render` reads them; drop `JobSpec.render` |
| `src/qurantext/gui/review/window.py` | modify | render / frame aspect / caption band from `job_settings` |
| `src/qurantext/core/timing_edit.py` | modify | `retime(..., keep_joined=False)` |
| `src/qurantext/gui/review/session.py` | modify | nudges keep joined edges; a drag that ends where it began is not an edit |
| `src/qurantext/gui/prefs.py` | create | `Prefs` over an injectable `QSettings` |
| `src/qurantext/jobs/catalog.py` | modify | dedupe folders; `hidden` filter |
| `src/qurantext/gui/home/__init__.py`, `job_list.py`, `new_job.py` | create | the two panels |
| `src/qurantext/gui/main_window.py` | rewrite | compose panels; Start → matching → review; render right away; close |
| `src/qurantext/gui/i18n.py` | modify | all new strings |
| `README.md` | modify | "The window" section |
| tests | create/modify | `test_job_settings.py`, `test_prefs.py`, `test_home_panels.py`, `test_gui.py`, `test_timing_edit.py`, `test_review_session.py` |

---

### Task 1: The three items Phase 2 handed over

**Files:** `jobs/project.py`, `gui/jobs.py`, `gui/review/window.py`, `core/timing_edit.py`, `gui/review/session.py`; tests `tests/test_job_settings.py` (new), `tests/test_gui.py`, `tests/test_timing_edit.py`, `tests/test_review_session.py`, `tests/test_review_window.py`.

**1a. One source for the job's choices (Phase 2 F5).**

In `jobs/project.py`:

```python
SUBTITLE_CHOICES = ("burn", "sidecar", "both")


@dataclass(frozen=True, slots=True)
class JobSettings:
    """What the person chose for this job's output, kept with the job."""

    preset: str = "social"
    subtitles: str = "burn"
    formats: tuple[str, ...] = ("srt",)
    output_dir: Path | None = None


def job_settings(project: Project) -> JobSettings:
    """The job's choices from ``project.export``, with defaults for anything unset."""


def set_job_settings(project: Project, settings: JobSettings) -> None:
    """Write *settings* into ``project.export``, keeping any other keys it holds."""
```

Stored keys in `project.export`: `preset` (str), `subtitles` (one of `SUBTITLE_CHOICES`), `formats` (list of str), `output_dir` (str, stored relative to the project file like other paths — reuse `_store_path`/`_resolve_path` in `to_dict`/`from_dict`, or store absolute POSIX; pick one and test the round-trip). Unknown or invalid values fall back to defaults (an unknown preset → `"social"`; an unknown subtitles value → `"burn"`).

`gui/jobs.py`:
- `JobSpec` gains `subtitles: str = "burn"` and `formats: tuple[str, ...] = ("srt",)`; **remove `render: bool`** (keep `render_right_away`). `run_job` keeps working: it matches, then renders only when `spec.render_right_away` is True (update `tests/test_gui.py` callers that passed `render=False`/relied on `render=True` accordingly — `test_run_job_matches_then_renders` passes `render_right_away=True`).
- `_match` calls `set_job_settings(project, JobSettings(spec.preset, spec.subtitles, spec.formats, spec.output_dir))` before saving — and the "unchanged re-match leaves the file untouched" path must still hold: compare content first; if unchanged but the settings differ, update just the settings (load, set, save) — a re-run with a new video size must take effect.
- `run_render(project, *, progress=None, cancel=None, **overrides)` reads `job_settings(project)` for preset/subtitles/formats/output_dir; keyword overrides still win (keep the existing parameters, defaulting to `None` meaning "use the job's setting"). Output folder: `settings.output_dir or VIDEOS_OUTPUT_DIR`.

`gui/review/window.py`: the render uses `run_render(snapshot, progress=…, cancel=…)` without hard-coded preset/subtitles; the frame's aspect uses `job_settings(project).preset` when there is no render record; `FrameView` gets `reserve_caption_band = bool(captions) and settings.subtitles != "sidecar"` (sidecar-only renders drop the band, `jobs/export.py`), so the preview matches. Keep `FrameView`'s API change minimal (e.g. a `set_caption_band(bool)` or a constructor argument).

Tests: `test_job_settings.py` — defaults, round-trip through `save_project`/`load_project`, invalid values fall back, other `export` keys preserved. `test_gui.py` — `run_matching` records the spec's choices; re-matching unchanged content with a different preset updates only the settings; `run_render` uses the recorded preset and output folder (monkeypatch `render_project` to capture its arguments). `test_review_window.py` — Render with corrections passes no hard-coded preset (captured `run_render` kwargs), and a sidecar job's frame has no caption band (capture `render_frame_pillow` kwargs).

**1b. A drag that ends where it began is not an edit (Phase 2 residual).**

`ReviewSession.end_gesture`: compare the gesture-start snapshot and the current state **after running both card lists through `derive_card_windows`** (recitation) and ignoring `edited` flags that were not set at gesture start; when they match, restore the gesture-start snapshot exactly and drop the undo entry. Test: begin a gesture on a real-shaped recitation project whose loaded card windows are not exactly derived (e.g. `start_time` 0.11 with first word 0.109), drag out and back → `not session.dirty`, `not session.can_undo`, cards identical to before.

**1c. Nudging back puts the neighbour back (Phase 2 residual).**

`core/timing_edit.retime(words, index, *, start=None, end=None, keep_joined=False)`: when `keep_joined` is True and the edited edge was **joined** to the neighbour's shared edge before the edit (`word.end == next.start` for an end edit, `prev.end == word.start` for a start edit, compared after ms snapping), the neighbour's shared edge moves with it in both directions, still bounded by the neighbour's other edge and its minimum length (invariants 1–3 unchanged). `retime_in_cards` forwards `keep_joined`. `ReviewSession.retime` passes `keep_joined=True` (nudges, `[`/`]`, snap); drags use `drag_retime`, which also passes `keep_joined=True`. Tests (timing_edit): joined end nudged +0.05 then −0.05 → both words exactly as before; an un-joined edge (a gap) → the neighbour never moves; collapsed-run fuzz from Phase 1 still holds with `keep_joined=True` (extend the property loop to use both values). Session test: `.` then `,` on a word whose end touches the next start → session state equals the start state (not dirty).

- [ ] Write failing tests for 1a–1c; implement; full suite + ruff; commit as three commits:
  "Keep the job's choices with the job, and render what was chosen" /
  "Treat a drag that ends where it began as no edit" /
  "Let a nudge move a shared boundary both ways".

---

### Task 2: Remembered settings, and a job list that finds every job

**Files:** create `src/qurantext/gui/prefs.py`; modify `src/qurantext/jobs/catalog.py`; tests `tests/test_prefs.py`, `tests/test_catalog.py`.

`gui/prefs.py`:

```python
class Prefs:
    """The home window's remembered choices, over an injectable QSettings.

    Tests pass a QSettings on an INI file in a temporary folder, so they never
    read or write the person's real settings.
    """

    def __init__(self, settings: QSettings | None = None) -> None: ...

    # typed accessors, each with a default and validation on read:
    mode: str                      # "recitation" | "lecture"            (default "recitation")
    preset: str                    # a VIDEO_PRESETS key                 (default "social")
    subtitles: str                 # SUBTITLE_CHOICES                    (default "burn")
    formats: tuple[str, ...]       # subset of SUBTITLE_FORMATS          (default ("srt",))
    render_right_away: bool        #                                     (default False)
    output_dir: Path | None        #                                     (default None)
    quran_override: Path | None    # a Quran text other than the shipped one (default None)
    more_options_open: bool        #                                     (default False)
    hidden_jobs: set[Path]         # project files removed from the list (default empty)
    job_dirs: list[Path]           # extra folders the list scans; output_dir is added
                                   # automatically whenever it is set    (default empty)
```

Implement as properties with setters (setters write through and `sync()`); an invalid stored value reads back as the default. `hide_job(path)`, `unhide_job(path)`.

`jobs/catalog.list_jobs(dirs=None, *, hidden=frozenset())`: dedupe folders by resolved path (the same folder listed twice lists its jobs once), skip projects whose resolved path is in `hidden`. Add `job_dirs_for(extra: Iterable[Path]) -> list[Path]` = `default_job_dirs()` + extra, deduped, order kept.

Decision (records the Phase 1 open question): **the job list scans the default matching folders plus every output folder the person has chosen** (remembered in `Prefs.job_dirs`).

Tests: `test_prefs.py` — defaults on an empty INI; round-trip of every key; invalid stored values read back as defaults; setting `output_dir` adds it to `job_dirs` once; hide/unhide. `test_catalog.py` — duplicate folders listed once; hidden projects skipped.

- [ ] Tests first; implement; full suite + ruff; commit "Remember the window's choices, and find jobs in every folder they were saved to".

---

### Task 3: The job list panel

**Files:** create `src/qurantext/gui/home/__init__.py`, `src/qurantext/gui/home/job_list.py`; tests `tests/test_home_panels.py`.

`class JobListPanel(QWidget)`:
- `__init__(prefs: Prefs, parent=None)`; header `t("home.jobs")` = "Your jobs" with a refresh button (`t("home.refresh")`).
- `refresh()` — `list_jobs(job_dirs_for(prefs.job_dirs), hidden=prefs.hidden_jobs)` into a `QListWidget`; each row shows the job name (bold) and a second line: mode (`t("home.mode.recitation")` / `t("home.mode.lecture")`), the ayah range or `t("home.cards", count=…)`, and the status (`t("home.status.needs_review")`, `…reviewed`, `…rendered`, `…changed_since_render`, `…damaged`); needs review and changed since render are drawn with the palette's warning-ish colour (use `QPalette.ColorRole.Link` or a fixed amber that reads in both themes — pick one and note it). Each row's `Qt.UserRole` = the `JobEntry`.
- `set_running(name: str, text: str | None)` — shows (or clears, with None) a transient top row for the job being matched, e.g. "recitation.m4a — Aligning… 40%".
- Signals: `open_requested = Signal(object)` (project `Path`) on double-click or Enter; `reveal_requested = Signal(object)` from the context menu "Show in folder" (`t("home.show_in_folder")`); context menu "Remove from list" (`t("home.remove_from_list")`) calls `prefs.hide_job(path)` then `refresh()`. Damaged rows: double-click shows their error in the status tip instead of opening.
- Empty state: a centred label `t("home.empty")` = "Your jobs appear here once you start one."

Tests (`test_home_panels.py`, with a `prefs` fixture on a tmp INI and `job_dirs` pointing at tmp folders holding projects saved with `save_project`): rows appear newest first with the right status text; double-click emits `open_requested` with the project path; "Remove from list" hides the row and persists (a fresh panel on the same INI does not show it); `set_running` adds and removes the transient row; a damaged file is listed and does not emit `open_requested`.

- [ ] Tests first; implement; full suite + ruff; commit "List every job and its state beside the new-job form".

---

### Task 4: The new-job panel

**Files:** create `src/qurantext/gui/home/new_job.py`; tests `tests/test_home_panels.py` (append).

`class NewJobPanel(QWidget)`:
- `__init__(prefs: Prefs, *, quran_default: Path | None, parent=None)`.
- Drop zone (`t("home.drop")` = "Drop an audio file, or choose one" with a "Choose…" link/button `t("home.choose")`); accepts drops of `AUDIO_SUFFIXES` (move that constant and `_first_audio` from `main_window.py` into this module); shows the chosen file's name and folder.
- Recitation | Lecture as two checkable `QPushButton`s in an exclusive `QButtonGroup` (`t("home.mode.recitation")`, `t("home.mode.lecture")`); the choice is remembered in `prefs.mode`.
- Surah picker + from/to spin boxes (recitation only; hidden for lecture), populated from the Quran store as today (`ensure_quran_db` + `list_surahs`; keep the current error handling).
- Video size combo with readable names: `t("preset.social")` = "Portrait 1080×1920 · 30 fps", `t("preset.high")` = "Landscape 1920×1080 · 30 fps", `t("preset.standard")` = "Landscape 1280×720 · 25 fps", `t("preset.fast")` = "Quick draft 960×540 · 24 fps"; remembered in `prefs.preset`.
- "More options" — a checkable tool button with an arrow (`t("home.more")`) that shows/hides a group (state remembered in `prefs.more_options_open`) holding: Quran text override (label + "Choose…" + "Use the shipped text" reset), output folder (label + "Choose…" + "Default" reset), subtitles radio group burn/sidecar/both (`t("home.subtitles.burn")` = "In the picture", `…sidecar` = "As files beside the video", `…both` = "Both") with formats checkboxes shown when files are involved, and a "Render right away" checkbox (`t("home.render_right_away")` = "Render right away (skip the review)").
- `spec() -> JobSpec` — the job the panel would run now (all fields including subtitles, formats, output_dir, render_right_away).
- `problem() -> str | None` — `spec().validate()` translated: `JobSpec.validate` returns i18n keys (`"job.need_audio"`, `"job.need_quran"`, `"job.need_range"`, `"job.bad_range"`) instead of English sentences; the panel shows `t(problem)` as visible helper text under the Start button (not only a tooltip). Update `JobSpec.validate`'s existing tests to the keys.
- Start button (`t("home.start")`) enabled only when `problem()` is None; signal `start_requested = Signal(object)` (the `JobSpec`); `set_running(running: bool)` disables inputs and swaps Start for Cancel (`t("home.cancel")`, signal `cancel_requested`); a progress bar + status line shown while running (`set_progress(fraction: float | None, text: str)`).

Tests: toggling mode hides the range and persists; the preset combo shows readable names and persists; More options open/closed persists; `spec()` reflects every control (subtitles/formats/output_dir/render_right_away); `problem()` gives the right key for each missing input and the helper label shows its English text; dropping a non-audio file is refused; `start_requested` carries the spec; `set_running(True)` disables inputs.

- [ ] Tests first; implement; full suite + ruff; commit "Collect a new job in one panel, with the rarely changed options folded away".

---

### Task 5: The home window

**Files:** rewrite `src/qurantext/gui/main_window.py`; modify `src/qurantext/gui/i18n.py`; tests `tests/test_gui.py`.

`MainWindow(prefs: Prefs | None = None)` — default `Prefs()` (real settings) only when not given; tests always pass one.
- Layout: a `QSplitter` with `JobListPanel` (left, ~300 px) and `NewJobPanel` (right); window title `t("app.title")` = "Qalun"; minimum size fits 1024×680.
- `start_requested(spec)` → `run_in_thread(lambda progress, cancel: run_matching(spec, …) [then run_render(project, …) when spec.render_right_away], …)` with **bound-method** callbacks; progress goes to the new-job panel and `job_list.set_running(name, text)`; Cancel works as today; on finish: add `spec.output_dir` to `prefs.job_dirs` when set, `job_list.refresh()`, and open the review for the project (the existing one-window-per-project `_open_review(project_path)` from Phase 2's `_open_editor`, renamed). On failure/cancel: message in the panel's status line, no modal for cancel.
- `job_list.open_requested(path)` → `_open_review(path)`; `reveal_requested(path)` → `show_in_folder`.
- Review windows: keep Phase 2's map/eviction/close-on-quit behaviour; also `job_list.refresh()` when a review emits `saved` or `closed`.
- Remove the old single-form widgets, the "Preview a frame" button (the review has the live frame) and "Show the video" (the job list's Show in folder and the review's render message cover it). Keep `_default_quran_file` behaviour for the default Quran text; `prefs.quran_override` wins when set and the file exists.
- Every string via `t()`.

Tests (update/replace the existing `MainWindow` tests in `tests/test_gui.py`; keep the Phase 2 tests for review ownership and close-on-quit, adapted): Start runs matching (monkeypatch `run_matching` to write a project and return it) and opens a review for it (monkeypatch `ReviewWindow` as the existing test does); `render_right_away` also calls `run_render`; a custom output folder ends up in `prefs.job_dirs` and the job appears in the list; double-clicking a job opens its review; the running row appears during the job and disappears after; closing with a review that refuses keeps the main window open.

- [ ] Tests first; implement; full suite + ruff; commit "Open on a list of every job, and start a new one beside it".

---

### Task 6: Tidy, document, and look at it

**Files:** `README.md` ("The window" section: the job list, the review, More options, where files go); remove dead code left behind (`jobs.run_job` stays only if something still calls it — grep; `JobOutcome` fields no longer used); smoke screenshot.

- [ ] Update the README; grep for dead code and remove it; full suite + ruff.
- [ ] Smoke run offscreen with `Prefs` on a tmp INI whose `job_dirs` include `output/recitation_matching` and `output/lecture_matching`, window 1280×800, save `…/scratchpad/phase3/home.png`; then open the first job's review and save `…/scratchpad/phase3/home_review.png`. Report both paths.
- [ ] Commit "Describe the new window, and remove what it no longer uses".

---

## After Phase 3

Whole-branch review (one pass, most capable model) → one fix wave → one scoped re-review → merge decision. Phase 4 (Arabic table + RTL, and the Phase 2 RTL deferrals) and Phase 5 (packaging with Qt Multimedia, playback preflight, size budget) follow.

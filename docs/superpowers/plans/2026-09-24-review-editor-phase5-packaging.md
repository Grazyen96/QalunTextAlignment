# Review editor Phase 5 — packaging and the release check — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The packaged Qalun app plays audio, speaks Arabic and says so in its own `--doctor`; the size cost is measured; everything a person must check by hand before release is written down; and the residuals Phases 3–4 carried are closed.

**Architecture:** Packaging stays one PyInstaller spec plus ordinary scripts in `packaging/ci/` (the workflow file is not edited — it needs a token scope ordinary pushes lack). New preflight checks run inside the frozen app; a `--release` flag makes the CI gate strict about what a shipped app must have (playback, Qt's Arabic translation, an Arabic-capable interface font) while a developer's `--doctor` only notes them. Two UI fixes that only show on real desktops (Arabic keyboard layouts, native title bars) are made testable offscreen.

**Tech Stack:** Python 3.10+, PySide6 6.11 (Essentials + Addons), PyInstaller 6.22 (in the venv), pytest offscreen.

**Spec:** `docs/superpowers/specs/2026-09-23-review-editor-design.md` §5 (packaging) and §6 (the manual check before release); §4 for the Arabic items.

## Global Constraints

- Python 3.10+; `venv/bin/ruff check src tests` and `venv/bin/ruff format --check src tests` clean (pinned ruff==0.15.13, line length 100; `PLE2502` on — write direction marks as `\u` escapes).
- `core/` never imports `jobs/` or `gui/` (`tests/test_layering.py`). `gui/review/session.py` and `gui/i18n.py` import no Qt.
- Every user-visible string in `gui/` goes through `t()`/`tn()`, with English and Arabic in the same commit. Preflight (`config/preflight.py`) stays English: it is a diagnostic report a person sends to whoever helps them.
- Spec §5, verbatim: "`packaging/qalun.spec`: `QtMultimedia` in hiddenimports; confirm the Qt FFmpeg multimedia plugin is collected on all three platforms; keep the existing excludes (none of them is Multimedia)."
- Spec §5, verbatim: "`config/preflight.py` gains a "playback" check; `packaging/ci/check.*` runs it."
- Spec §5, verbatim: "Size budget: record the before/after size of each platform's archive in `packaging/README.md`. Expected +30–40 MB; if it is far larger, stop and review before merging."
- Do not edit `.github/workflows/*` (token scope); platform logic goes in `packaging/ci/`.
- Do not `pip install` or download anything. Build outputs (`dist/`, `build/`, vendor copies, zips) go under the scratchpad `/tmp/claude-1000/-home-khalil-PycharmProjects-QuranText/8df4d836-dab4-4c89-91cc-fa89e369f0e4/scratchpad/phase5/`, never into the repo.
- No telemetry. Any link to a download page or the Releases page added to a document carries UTM parameters (`utm_source`, `utm_medium`, `utm_campaign`) so downloads are measurable (organisation rule); the app itself sends nothing.
- Tests never touch real user settings; tests building a `JobListPanel`/`MainWindow` use `no_default_job_dirs`; never `QTest.qWait` in tests (it holds the GIL and deadlocked worker threads) — use the GIL-releasing helper in the tests.
- House style: why-docstrings, `from __future__ import annotations`, `__all__`, frozen `slots=True` dataclasses for value types.

## Files

| File | Responsibility | Task |
|---|---|---|
| `src/qurantext/gui/home/new_job.py`, `gui/main_window.py`, `gui/home/job_list.py` | residuals | 1 |
| `src/qurantext/config/preflight.py`, `packaging/entry.py`, `packaging/ci/check.sh`, `packaging/ci/check.ps1` | playback / translation / font checks, `--release` | 2 |
| `packaging/qalun.spec`, `packaging/README.md` | Multimedia + translations collected, size budget | 3 |
| `src/qurantext/gui/language.py`, `gui/review/window.py`, `gui/i18n.py`, `gui/main_window.py` | interface-font fallback, layout-independent shortcuts, plain window titles | 4 |
| `src/qurantext/gui/home/job_list.py`, `gui/main_window.py` | job list read off the UI thread | 5 |
| `docs/release-checklist.md` (new), `README.md` | the manual check, settings location | 6 |

---

### Task 1: Residuals Phase 4 carried

**Files:** Modify `src/qurantext/gui/home/new_job.py` (drop zone path line), `src/qurantext/gui/main_window.py` (`_start`, `_on_progress`, the hold), `src/qurantext/gui/home/job_list.py` (running row text). Test: `tests/test_home_panels.py`, `tests/test_gui.py`.

**Interfaces:** Consumes the Phase 4 hold mechanism in `main_window.py` (`_answer`, `_holding`, `_stage`) and `i18n.path_text`. Produces nothing later tasks rely on.

- [ ] **Step 1: Failing tests.**

```python
def test_a_long_audio_path_is_elided_to_one_line_with_the_full_path_as_tooltip(qt_app, prefs, store):
    panel = _panel(prefs, store)
    deep = Path("/tmp") / ("very-long-folder-name-" * 12) / "تلاوة.mp3"
    panel.set_audio(deep)
    label = panel.drop_label            # or the label that shows the chosen file's folder
    panel.resize(700, 600); panel.show(); qt_app.processEvents()
    metrics = label.fontMetrics()
    for line in label.text().split("\n"):
        assert metrics.horizontalAdvance(line) <= label.width()
    assert str(deep.parent) in label.toolTip()
    assert "…" in label.text()


def test_a_refusal_made_before_the_first_progress_event_stays_up(qt_app, tmp_path, no_default_job_dirs, ...):
    # Start a blocked job; before any ProgressEvent arrives, trigger a held answer
    # (double-click the job's own row → home.busy_matching); then deliver the first
    # progress event of stage "detect" with no fraction.
    ...
    assert window.new_job.status_label.text() == t("home.busy_matching")


def test_the_running_row_names_the_stage_before_any_percentage(qt_app, tmp_path, no_default_job_dirs, ...):
    # Start a blocked job; deliver ProgressEvent(stage="detect", message="…", fraction=None).
    ...
    assert t("job.stage.detect") in _running_text(window.job_list)
```

Use the file's existing helpers and real attribute names (read the Phase 3/4 tests first).

- [ ] **Step 2: Run; see them fail.** `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q tests/test_home_panels.py tests/test_gui.py -k "elided or before_the_first or names_the_stage"`.

- [ ] **Step 3: Implement.**
  - Drop zone: the line that shows the chosen file's folder (and the file name line) is elided in the middle to the label's width with `QFontMetrics.elidedText(text, Qt.TextElideMode.ElideMiddle, width)`, recomputed on `resizeEvent`; the full path (through `path_text`) is the tooltip. Keep the fixed drop-zone height.
  - Hold: a stage change clears a held answer only when the hold was set *during* an earlier stage. Record the stage current when `_answer` holds (`None` before the first event) and clear on a change *away from a stage the job had already reported*: the first event after `_start` never clears a hold.
  - Running row: `_on_progress` passes the same stage sentence it shows on the status line to `job_list.set_running(name, text, fraction)` when the event has no fraction; with a fraction, keep today's percentage text.

- [ ] **Step 4: Run; see them pass;** full suite; ruff.

- [ ] **Step 5: Commits.** `Elide a long audio path in the drop zone, and keep the whole path as its tooltip`; `Keep a refusal up through a new job's first progress event`; `Name the stage in the running row before the first percentage arrives`.

---

### Task 2: What the packaged app must be able to do — preflight

**Files:** Modify `src/qurantext/config/preflight.py`, `packaging/entry.py` (`--doctor --release`), `packaging/ci/check.sh`, `packaging/ci/check.ps1`, `packaging/ci/README.md`. Test: `tests/test_preflight.py` (exists? `ls tests | grep preflight`; else create).

**Interfaces:**
- Produces `run_checks(*, release: bool = False) -> list[CheckResult]`. New checks, each a `CheckResult(name, status, detail, remedy)`:
  - `"Playback"` — `_playback(release)`
  - `"Window translation"` — `_qt_translation(release)`
  - `"Arabic interface font"` — `_arabic_ui_font(release)`
- `entry.py`: `qalun --doctor [--release]`; `--release` → `run_checks(release=True)`.
- Consumed by Task 3 (the frozen gate) and Task 4 (the font fallback reuses `arabic_ui_families()`).

- [ ] **Step 1: Failing tests** (`tests/test_preflight.py`):

```python
from qurantext.config import preflight
from qurantext.config.preflight import Status, run_checks


def test_playback_loads_a_short_recording(qt_app) -> None:
    result = preflight._playback(release=True)
    assert result.status == Status.OK, result
    assert "FFmpeg" in result.detail or "backend" in result.detail


def test_playback_missing_is_a_note_for_a_developer_and_a_failure_for_a_release(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "_import_multimedia", lambda: (_ for _ in ()).throw(ImportError("no QtMultimedia")))
    assert preflight._playback(release=False).status == Status.WARN
    assert preflight._playback(release=True).status == Status.FAIL


def test_the_arabic_window_translation_is_found() -> None:
    assert preflight._qt_translation(release=True).status == Status.OK


def test_no_arabic_font_fails_a_release(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "arabic_ui_families", lambda: [])
    assert preflight._arabic_ui_font(release=False).status == Status.WARN
    assert preflight._arabic_ui_font(release=True).status == Status.FAIL


def test_release_checks_include_the_new_ones() -> None:
    names = {r.name for r in run_checks(release=True)}
    assert {"Playback", "Window translation", "Arabic interface font"} <= names
```

`tests/test_packaging_entry.py` (or the existing entry tests — `grep -rn "packaging.entry\|entry.main" tests`): `main(["--doctor", "--release"])` calls `run_checks(release=True)` (monkeypatch it; assert the flag).

- [ ] **Step 2: Run; see them fail.**

- [ ] **Step 3: Implement** in `preflight.py`, each check with a why-docstring:

```python
def _import_multimedia():
    from PySide6 import QtMultimedia  # noqa: PLC0415 - optional part of Qt

    return QtMultimedia


def _playback(release: bool) -> CheckResult:
    """Can this machine play the recording under review?

    Loads a half-second WAV written on the spot through ``QMediaPlayer`` and waits
    (bounded, 5 s) for Qt to report it loaded with a duration. Importing the module
    is not enough: the FFmpeg multimedia plugin is a separate file a frozen build can
    leave behind, and without it the module imports and every file fails to load.
    Needs no sound device — CI machines have none — so audio outputs are only noted.
    """
```

  - Build a `QCoreApplication` only if no application exists (a `QApplication` in the GUI/tests is reused); write the WAV with the standard `wave` module into a `tempfile.TemporaryDirectory`; `QMediaPlayer.setSource(QUrl.fromLocalFile(...))`; run a `QEventLoop` quit by `mediaStatusChanged` (LoadedMedia/InvalidMedia) or a 5 s `QTimer.singleShot`; OK when `LoadedMedia` and `duration() > 0`, detail names the backend if Qt exposes it (`QMediaFormat().supportedFileFormats(QMediaFormat.ConversionMode.Decode)` count, `QMediaDevices.audioOutputs()` count). Failure: WARN (developer) / FAIL (release), remedy: developer "pip install -e '.[gui]' (PySide6-Addons carries Qt Multimedia)", frozen "This is a packaging fault: the Qt multimedia plugin was not bundled. Please report it."
  - `_qt_translation(release)`: `QTranslator().load("qtbase_ar", QLibraryInfo.path(TranslationsPath))`; OK with the folder; else WARN/FAIL ("Qt's own buttons will stay English in the Arabic window").
  - `arabic_ui_families() -> list[str]` (public; Task 4 uses it): `QFontDatabase.families(QFontDatabase.WritingSystem.Arabic)` minus the bundled Quran font's family (it has no Latin letters; see Task 4). Needs a `QGuiApplication`; if only a `QCoreApplication` can exist, return the list the check can measure and say so in the detail. `_arabic_ui_font(release)`: OK naming the first two families; else WARN/FAIL with remedy "Install an Arabic font (for example Noto Sans Arabic); Qalun falls back to its bundled Quran font for Arabic letters, which is legible but not meant for interface text."
  - `run_checks(*, release=False)` appends the three.
  - `entry.py`: `--doctor` reads an optional `--release` after it.
  - `check.sh`: `PATH=/nonexistent "$app" --doctor --release`; `check.ps1`: `-ArgumentList "--doctor","--release"`. Update `packaging/ci/README.md`'s table row.

- [ ] **Step 4: Run; see them pass;** full suite; ruff.

- [ ] **Step 5: Commit.** `Check in the app itself that it can play audio, translate Qt's buttons and draw Arabic, strictly for a release`.

---

### Task 3: The spec, a real Linux build, and the size budget

**Files:** Modify `packaging/qalun.spec`, `packaging/README.md`. Test: a real build (no pytest file), plus `tests/test_packaging_spec.py` for the spec's declarations.

**Interfaces:** Consumes `--doctor --release` (Task 2). Produces the measured Linux sizes in `packaging/README.md`.

- [ ] **Step 1: Failing test** (`tests/test_packaging_spec.py`) — read the spec as text so the rule lives in a test:

```python
SPEC = Path(__file__).resolve().parents[1] / "packaging" / "qalun.spec"


def test_the_spec_names_qt_multimedia_and_excludes_none_of_it() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert '"PySide6.QtMultimedia"' in text
    excludes = text.split("excludes=[", 1)[1].split("]", 1)[0]
    assert "Multimedia" not in excludes
```

- [ ] **Step 2: Implement the spec.** Add `"PySide6.QtMultimedia"` to `hiddenimports` with a comment (the review window's player; the import is inside a function, so analysis cannot see it). Confirm how PyInstaller 6.22's PySide6 hooks collect (a) the multimedia plugins (`plugins/multimedia/libffmpegmediaplugin.*`) and (b) the FFmpeg libraries Qt's plugin links (`libavcodec`, … shipped inside PySide6's `Qt/lib`), and (c) `translations/qtbase_ar.qm` + `qtmultimedia_ar.qm`. Read the hook source in `venv/lib/python3.12/site-packages/PyInstaller/hooks/` (`hook-PySide6.QtMultimedia.py`, `utils/hooks/qt/`). Add explicit `datas`/`binaries` only for what the hooks do not collect, each with a comment saying why.

- [ ] **Step 3: Build twice on Linux, into the scratchpad.**

```bash
P=/tmp/claude-1000/-home-khalil-PycharmProjects-QuranText/8df4d836-dab4-4c89-91cc-fa89e369f0e4/scratchpad/phase5
# after: the spec as it now is
venv/bin/pyinstaller packaging/qalun.spec --noconfirm --distpath $P/dist-after --workpath $P/build-after
# before: the same spec with Multimedia excluded (what the app was before Phase 2)
sed 's/"PySide6.QtMultimedia",//; s/excludes=\[/excludes=["PySide6.QtMultimedia",/' packaging/qalun.spec > $P/qalun-before.spec
venv/bin/pyinstaller $P/qalun-before.spec --noconfirm --distpath $P/dist-before --workpath $P/build-before
```

(`SPECPATH` in a copied spec points at the scratchpad: set `ROOT` by environment variable or copy the spec into `packaging/` under a git-ignored name and delete it after — choose one and say which.) Zip each `qalun` folder the way the release workflow does (`shutil.make_archive(..., "zip", dist, "qalun")`) and record folder size (`du -sm`) and zip size (MB) for both.

- [ ] **Step 4: The gate on the real bundle.** Stage a vendor folder in the scratchpad the way `collect-linux.sh` would, from what is already on this machine (no downloads): `/usr/local/bin/ffmpeg`, `/usr/local/bin/ffprobe` (check they are static: `ldd`), `/usr/lib/x86_64-linux-gnu/libfribidi.so.0`; copy them beside `dist-after/qalun/qalun`; run `PATH=/nonexistent $P/dist-after/qalun/qalun --doctor --release`. Every line must be `ok` except "Transcription" (no token is fine — WARN) and "Quran store" (WARN until built). If Playback, Window translation or Arabic interface font fail, fix the spec (Step 2) and rebuild. Also start the bundled GUI offscreen for 5 s (`QT_QPA_PLATFORM=offscreen timeout 5 $P/dist-after/qalun/qalun`): exit by timeout (124) with nothing on stderr about missing plugins is a pass. The doctor's playback check already exercises the bundled plugin; the GUI start only proves the window launches.

- [ ] **Step 5: Record the budget** in `packaging/README.md`, a new "Size" section:

```markdown
## Size

Playback (Qt Multimedia, from PySide6-Addons) is the one thing the review editor
added to the bundle. Measured on Linux, 24 Sep 2026, PyInstaller 6.22, PySide6 6.11.2,
FFmpeg and FriBiDi not included (they are the same before and after):

| | folder | zip |
|---|---|---|
| before (Multimedia excluded) | … MB | … MB |
| after | … MB | … MB |
| difference | … MB | … MB |

Windows and macOS: record from the first release-workflow run after this change
(the zip sizes on the run's summary page) — see docs/release-checklist.md.
```

If the zip difference exceeds 60 MB (far above the spec's +30–40 MB), stop and report BLOCKED with the breakdown (largest new files: `find dist-after -type f -size +2M | xargs du -m | sort -n | tail`) instead of committing.

Update the README's "About 223 MB" line with today's measured folder size, and add Multimedia/translations to "Two things that are easy to get wrong" only if the hooks needed help.

- [ ] **Step 6: Run the new test; full suite; ruff; commit.** `Bundle Qt Multimedia and measure what playback costs the app`.

---

### Task 4: Arabic on real desktops — interface font, keyboard layouts, title bars

**Files:** Modify `src/qurantext/gui/language.py` (font fallback), `src/qurantext/gui/review/window.py` (`_bind_keys`, `keyPressEvent`), `src/qurantext/gui/i18n.py` (`plain_title`), every `setWindowTitle(t(...))` call site (`grep -rn "setWindowTitle" src/qurantext/gui`). Test: `tests/test_language.py`, `tests/test_review_window.py`, `tests/test_i18n.py`.

**Interfaces:**
- Consumes `preflight.arabic_ui_families()` (Task 2).
- Produces `language.ensure_arabic_font(app) -> str | None` (the family registered as a fallback, or None when the system has one), `i18n.plain_title(text: str) -> str`, `window.SCANCODE_KEYS` (platform → scan code → Qt key).

- [ ] **Step 1: Failing tests.**

```python
def test_without_a_system_arabic_font_the_bundled_one_is_the_fallback(qt_app, monkeypatch) -> None:
    monkeypatch.setattr(language, "arabic_ui_families", lambda: [])
    family = language.ensure_arabic_font(QApplication.instance())
    assert family  # registered from DEFAULT_FONT_PATH
    assert family in QFont.substitutes(QApplication.font().family()) or family in QFontDatabase.families()


def test_with_a_system_arabic_font_nothing_is_registered(qt_app, monkeypatch) -> None:
    monkeypatch.setattr(language, "arabic_ui_families", lambda: ["Noto Sans Arabic"])
    assert language.ensure_arabic_font(QApplication.instance()) is None


@pytest.mark.parametrize(("scancode", "key"), [...])  # the four punctuation keys on this platform
def test_shortcuts_follow_the_physical_key_on_an_arabic_layout(qt_app, review_window, scancode, key) -> None:
    # A press of the "[" key on an Arabic layout: text "ج", key() == Key_unknown or the Arabic
    # letter's code, nativeScanCode() == the physical key's code.
    event = QKeyEvent(QEvent.Type.KeyPress, 0x062C, Qt.KeyboardModifier.NoModifier,
                      scancode, 0, 0, "ج")
    ...  # deliver to the window; assert the same action as "[" ran (start set at playhead)


def test_plain_title_drops_isolates_and_keeps_order_marks() -> None:
    text = "مراجعة — ⁨furquanTra7-11⁩"
    out = plain_title(text)
    assert not any(c in out for c in "⁦⁧⁨⁩")
    assert "furquanTra7-11" in out
```

- [ ] **Step 2: Run; see them fail.**

- [ ] **Step 3: Implement.**
  - `ensure_arabic_font(app)`: when `arabic_ui_families()` is empty, `QFontDatabase.addApplicationFont(str(DEFAULT_FONT_PATH))` and add its family as a substitute of the application font's family (`QFont.insertSubstitution(app.font().family(), family)`), so Qt draws Arabic letters with it and everything else with the system font. Call it from `apply_language` for every language (Arabic job names appear in the English window too). Why-docstring: the bundled Qaloon font is a Quran face with no Latin letters, so it is only ever a fallback.
  - Shortcuts: keep the `QShortcut`s. In `keyPressEvent`, when the event is not already handled and its `text()` is not ASCII, look up `event.nativeScanCode()` in `SCANCODE_KEYS[sys.platform-family]` for the four layout-dependent keys `[ ] , .` (with Shift for `, .`), and run the same action. Table (verify each value against Qt/XKB/Windows/macOS docs and say where it came from in a comment): X11/Wayland evdev+8 — `[`=34, `]`=35, `,`=59, `.`=60; Windows set-1 scan codes — `[`=0x1A, `]`=0x1B, `,`=0x33, `.`=0x34; macOS virtual key codes (Qt reports them as `nativeVirtualKey`, scan code 0) — `[`=33, `]`=30, `,`=43, `.`=47 (read `nativeVirtualKey()` on macOS). Ctrl+Z/Ctrl+Shift+Z/Ctrl+S already work through Qt's Latin fallback for modified keys — note it, do not duplicate.
  - `plain_title(text)`: native title bars on some platforms draw isolate controls as boxes; replace each FSI/LRI/RLI…PDI pair with its content followed by an LRM (U+200E) when the content's first strong character is Latin/none, or an RLM (U+200F) when it is Arabic — marks every title bar has understood for decades. Use it at every `setWindowTitle(t(...))`.

- [ ] **Step 4: Run; see them pass;** full suite; ruff.

- [ ] **Step 5: Commits.** `Fall back to the bundled font for Arabic letters when the system has none`; `Let the review's punctuation shortcuts follow the physical key on any layout`; `Keep isolate controls out of window titles, which some title bars draw as boxes`.

---

### Task 5: Read the job list off the UI thread

**Files:** Modify `src/qurantext/gui/home/job_list.py` (`refresh`), maybe `src/qurantext/gui/main_window.py`. Test: `tests/test_home_panels.py`.

**Interfaces:** Consumes `gui/review/background.BackgroundJobs` (bound-method callbacks), `jobs/catalog.list_jobs(dirs, *, hidden)`. Produces: `JobListPanel.refresh()` returns at once; a new signal `JobListPanel.refreshed = Signal()` emitted after rows are rebuilt; `JobListPanel.wait_until_refreshed(timeout_ms)` for tests only if the existing wait helper cannot do it.

- [ ] **Step 1: Failing test.**

```python
def test_refresh_reads_projects_off_the_ui_thread(qt_app, prefs, monkeypatch) -> None:
    seen = {}
    real = catalog.list_jobs

    def spy(*args, **kwargs):
        seen["thread"] = threading.get_ident()
        return real(*args, **kwargs)

    monkeypatch.setattr(job_list_module, "list_jobs", spy)
    panel = JobListPanel(prefs)
    _wait_for(lambda: "thread" in seen)   # the GIL-releasing helper
    assert seen["thread"] != threading.get_ident()
```

Plus: two refreshes in quick succession show the second's result (a stale first result arriving late never overwrites a newer one — use a generation counter); the running row survives a refresh (existing test keeps passing); closing the window while a read runs does not crash (`BackgroundJobs.stop()` on the panel's close/destroy, as the review window does).

- [ ] **Step 2: Run; see it fail.**

- [ ] **Step 3: Implement.** `refresh()` bumps `self._generation`, starts `list_jobs` in `BackgroundJobs` with a bound method `_on_listed(generation, entries)` (use a small bound-method wrapper or `functools.partial` of a bound method — never a bare lambda; see the rule), which drops results whose generation is not current, rebuilds rows, re-applies the running row, updates the empty state, and emits `refreshed`. Existing tests that call `refresh()` and then read rows must wait for `refreshed` (update them with the existing wait helper).

- [ ] **Step 4: Run; see it pass;** full suite ×2 (threads); ruff.

- [ ] **Step 5: Commit.** `Read the job list on a worker thread, so a big folder cannot freeze the window`.

---

### Task 6: The release checklist and the settings location

**Files:** Create `docs/release-checklist.md`; modify `README.md` ("The window" section: where settings live), `packaging/README.md` (link to the checklist).

**Interfaces:** Consumes the measured sizes (Task 3) and the checks (Task 2). Produces the document the owner follows before tagging a release.

- [ ] **Step 1: Write `docs/release-checklist.md`** — short, imperative, one checkbox per item, grouped:
  - **Build:** run *Build the app* (Actions → Run workflow); every platform's gate step passes (`--doctor --release`); record the Windows and macOS zip sizes in `packaging/README.md`'s Size table (stop if the Multimedia difference is far above +30–40 MB).
  - **By ear, on Windows and Linux (spec §6):** open the packaged app; start a job on `furquanTra7-11.mp3` (surah 25, ayat 7–11); in the review, play, find the late words at the end of 25:7 and fix the rift by ear (ripple the late words); save; render; confirm the MP4 and an exported SRT match what the editor showed.
  - **Arabic, on a real desktop:** switch to العربية; with an Arabic keyboard layout active, `[ ] , .` still set/nudge; window title bars show no boxes; Qt's own buttons (the file dialog, Save/Discard) are Arabic; a machine without an Arabic font (a fresh Linux VM) still draws Arabic letters.
  - **Words:** a native Arabic speaker reviews `STRINGS["ar"]` in the running app (start from the uncertain list: `review.mark_reviewed`, `review.snap`, `segments.retimed`, «م.ث», the Cancel/Close forms, `review.save` as a dialog title, the five `job.stage.*` lines, the video header wording «الآيات 7 - 11» vs «الآيات من 7 إلى 11»), editing the table in place and keeping every `⁦…⁩`/`‏` mark.
  - **Publish:** tag `vX.Y.Z` and push the tag (the workflow attaches the zips to a Release). If the release is announced anywhere (a website, a post, a QR code on printed material), link to the Release page with UTM parameters, e.g. `https://github.com/Grazyen96/QalunTextAlignment/releases/latest?utm_source=<channel>&utm_medium=<post|print|qr>&utm_campaign=qalun-vX.Y.Z`, one `utm_source` per channel, so downloads per channel can be told apart (GitHub's own release download counts give the total).
- [ ] **Step 2: README** — in "The window": settings (language, last choices, hidden jobs, output folders) live in Qt's standard place for an app named Qalun: `~/.config/Qalun/Qalun.conf` on Linux, the registry key `HKEY_CURRENT_USER\Software\Qalun\Qalun` on Windows, `~/Library/Preferences/com.qalun.Qalun.plist` on macOS (verify each against Qt's QSettings documentation for the NativeFormat and the organisation/application names set in `gui/app.py`; write what Qt actually uses). Deleting it resets the window.
- [ ] **Step 3: `packaging/README.md`** — link the checklist from the top section.
- [ ] **Step 4: Commit.** `Write down what to check by hand before a release, and where settings live`.

---

## Self-review notes (controller)

- Spec §5: Addons in the gui extra (done in Phase 2) ✓; QtMultimedia hiddenimport + plugin collected (T3 on Linux; Windows/macOS through the CI gate's strict playback check, T2+T3) ✓; excludes kept (T3 test) ✓; preflight playback + check.* runs it (T2) ✓; size budget recorded (T3 Linux; T6 checklist for Windows/macOS) ✓.
- Spec §6 manual check → T6 checklist (a person's job; cannot be automated here).
- Carried: Phase 4 residuals (T1); Phase 3 deferral list_jobs on the UI thread (T5); settings location (T6); Phase 4 M10 keyboard layouts + title bars (T4, plus the checklist for the real-desktop part); qtbase_ar.qm collection (T2 check + T3 build); Arabic UI font on Linux (T2 check + T4 fallback).
- Organisation rule (measurable links): T6's publish step carries UTM parameters; the app sends nothing.

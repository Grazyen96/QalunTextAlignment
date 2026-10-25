# Release check fixes (v0.3.0 pre-release): implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the two blockers and the nine cheap majors that the 2026-10-25 release check verified, so that v0.3.0 can be tagged as a pre-release.

**Architecture:** Each finding is fixed at its source, one task per fix, each with its own tests. The subtitle writers map three KFGQPC tanween code points to standard Unicode at write time and never touch what the video or the window draws. The frame encoder writes to a partial file and moves it into place. The review widgets that draw Quran words put the bundled Qaloon face first, as the ayah picker already does. The macOS app is signed again after FFmpeg is staged. All doc changes land in the last task.

**Tech Stack:** Python 3.12, PySide6 6.11 (offscreen tests), Pillow, FFmpeg, PyInstaller spec, bash CI scripts, GitHub Actions YAML.

**Spec:** `docs/release-check-2026-10-25.md`, sections 4.1 and 4.2. The finding ids below are the report's.

**Rulings made while planning** (the executor records them in the ledger):

1. JRN-2/REV-1 gets the code fix: selecting a word arms its start edge and the armed edge is painted. The guide then says what a press does.
2. JRN-3/INT-3: the frame encoder writes `.<stem>.<8 hex>.part.mp4` beside the target and replaces the target only on success. `job_status` treats a job whose video is gone as not rendered. Closing a review that is rendering asks first, and the default answer keeps rendering.
3. QRN-1 maps only U+0657, U+065E and U+0656. U+06D2 stays, because verification found it is not a defect. Nothing `qaloon.10.ttf` draws is mapped: not the video frames, not the window's Quran face, and not an ASS file whose font is the Qaloon face.
4. QRN-2 draws with the Quran face, as the ayah picker does, rather than mapping the text.
5. REL-6 is fixed in the docs: glibc 2.38+ on Linux, Apple silicon on macOS, Windows 10 or 11 64-bit. Building Linux on an older base is out of scope.
6. RC-2 (the guide's "about 300 MB free") is fixed in Task 9, because it sits on the same lines as REL-6.
7. REL-1 ships Pillow's metadata and Python's own licence. The LGPL texts for Qt and FriBiDi stay with the owner's licence review (already known).

## Global Constraints

- Work only in the worktree `/home/khalil/PycharmProjects/QuranText/.claude/worktrees/release-fixes` (branch `fix/release-check-2026-10-25`). `$PY` is `/home/khalil/PycharmProjects/QuranText/venv/bin/python` and `$RUFF` its `ruff`.
  - Tests: `QT_QPA_PLATFORM=offscreen $PY -m pytest …` from the worktree root.
  - Before every commit: `$RUFF check src tests tools && $RUFF format src tests tools`.
  - The venv's editable install points at the main checkout. Every ad-hoc script and CLI call therefore needs `PYTHONPATH=src`; pytest is fine through `pythonpath = ["src"]`.
- Commit messages are one sentence in the repository's style (what changed, then "because …"). They end with `Co-Authored-By: <your model> <noreply@anthropic.com>`.
- Every `t()` key exists in both languages with the same placeholders.
  - An Arabic line that starts with a value starts with `‏`, and direction marks are written as `\u` escapes.
  - Each new key is added to `docs/release-checklist.md` → "Words", for the native-speaker review.
- Never `QTest.qWait`; pump with `qt_app.processEvents()` or `tests.qt_helpers.wait_for`.
  - A new Qt test file starts with `pytest.importorskip("PySide6", ...)`.
  - A test that needs FFmpeg skips without it, because CI has neither Qt nor FFmpeg.
- Every widget attribute and public name the tests use keeps its name.
- The tanween mapping is exactly U+0657 → U+08F0, U+065E → U+08F1, U+0656 → U+08F2.
- The laptop is short of memory. Never transcribe, and never run two test suites at once. Run the full suite (about 4 minutes) at most once per task, at its end.

## Review Focus

1. **A re-render on Windows while the old MP4 is open in a player.** Replacing the file fails with `PermissionError`. The old video must stay, the partial file must go, and the message must say the file may be open in another program. → Task 6 test `test_a_locked_target_keeps_the_earlier_video_and_says_why`.
2. **A cue with other mushaf marks next to tanween** (U+06DE, U+06EC, U+06E2, U+200F, Arabic-Indic digits, U+06D2). Only the three tanween code points may change. → Task 1 test `test_only_the_three_tanween_marks_change`.
3. **An ASS file whose font is the Qaloon face**, either as a sidecar or from the CLI's burned-in renderer. The mushaf's own code points must stay, because that face has no U+08F0–08F2. → Task 1 tests `test_an_ass_file_in_the_qaloon_face_keeps_the_mushaf_marks` and `test_build_ass_keeps_the_marks_for_the_qaloon_face`.
4. **A broken bundle where the Quran face cannot be registered.** The review must keep drawing in its own font, not blank or crash. → Task 4 test `test_without_the_quran_face_the_widgets_keep_their_font`.
5. **A screen at 125 % or 150 %.** Qt picks the 2× pixmap, which must hold the whole icon. → Task 3 test `test_a_fractional_screen_scale_gets_the_whole_icon`.

Test strings use escapes for the marks:

- `JANNATUN = "جَنَّةٞ"`
- `RAJULAN = "رَجُلاٗ"`
- `JANNATIN = "جَنَّٰتٖ"`

---

### Task 1: Subtitle files write tanween in standard Unicode (QRN-1, blocker)

**Files:**
- Modify: `src/qurantext/core/arabic.py` (two public functions, added to `__all__`)
- Modify: `src/qurantext/core/subtitles.py` (`write_srt`, `write_vtt`, `write_ass`; the module docstring says ayah cues are written with standard tanween)
- Modify: `src/qurantext/core/ass_renderer.py` (`build_ass`)
- Test: `tests/test_arabic.py`, `tests/test_subtitles.py`, and a new `tests/test_ass_renderer.py`

**Interfaces:**
- Produces: `portable_tanween(text: str) -> str` returns *text* with U+0657, U+065E and U+0656 replaced by U+08F0, U+08F1 and U+08F2, and nothing else changed.
- Produces: `is_qaloon_face(font_name: str) -> bool` is true when the name, case-insensitively, contains `qaloon`.

- [ ] **Step 1: Write the failing tests.**
  - In `tests/test_arabic.py`:
    - `test_portable_tanween_writes_the_standard_open_tanween`: `portable_tanween("ٖٗٞ") == "ࣰࣱࣲ"`.
    - `test_only_the_three_tanween_marks_change`: a string mixing RAJULAN with U+06DE, U+06EC, U+06E2, U+200F, U+06D2 and `"١٠"` maps to the same string with only U+0657 → U+08F0.
    - `test_is_qaloon_face`: true for `"KFGQPC QALOON Uthmanic Script"`, false for `"Amiri"` and `"Noto Sans Arabic"`.
  - In `tests/test_subtitles.py`:
    - `test_written_subtitles_carry_no_kfgqpc_tanween`: `write_subtitles([Cue(0.0, 2.0, f"{JANNATUN} {RAJULAN} {JANNATIN}", "25:8")], tmp_path / "x", ("srt", "vtt", "ass"))`. Each file, read as `utf-8-sig`, contains none of U+0656, U+0657 or U+065E, and contains U+08F0, U+08F1 and U+08F2.
    - `test_an_ass_file_in_the_qaloon_face_keeps_the_mushaf_marks`: `write_ass(..., font_name="KFGQPC QALOON Uthmanic Script")` keeps U+065E and has no U+08F1.
    - `test_store_cues_reach_the_file_mapped`: an ayah cue built by `ayah_caption_cues` from the bundled store for 25:8 (use the test helpers this file already has for the store) is written with U+08F1 and without U+065E.
  - In `tests/test_ass_renderer.py`:
    - `test_build_ass_writes_standard_tanween`: `build_ass([match], "Amiri", 1280, 720)`, where *match* is one valid card whose `full_text` is JANNATUN. Copy the smallest valid card from the existing render tests. The result has U+08F1 and no U+065E.
    - `test_build_ass_keeps_the_marks_for_the_qaloon_face`: the same card with `"KFGQPC QALOON Uthmanic Script"` keeps U+065E.
- [ ] **Step 2: Run them and see them fail** (`ImportError` / assertion).
- [ ] **Step 3: Implement.**
  - Add the two functions in `core/arabic.py`, with a one-line note on why: only `qaloon.10` draws the three code points as open tanween.
  - In `write_srt` and `write_vtt`, write `portable_tanween(cue.text)`.
  - In `write_ass`, map unless `is_qaloon_face(font_name)`.
  - In `build_ass`, map the label and body unless `is_qaloon_face(font_name)`.
  - Do not change cue construction, `video_common`, the frame renderer or any project data: the window and the video keep the mushaf's code points.
- [ ] **Step 4: Run** `tests/test_arabic.py tests/test_subtitles.py tests/test_ass_renderer.py tests/test_export.py tests/test_project_render.py`, then the full suite.
- [ ] **Step 5: Lint, then commit.**

### Task 2: Pillow's and Python's licences ship with the app (REL-1, blocker)

**Files:**
- Modify: `packaging/qalun.spec` (the `datas` block after the certifi/idna lines)
- Modify: `THIRD_PARTY_NOTICES.md` (the Python paragraph at about lines 238–240 and the Pillow paragraph at 250–254: say where each licence file sits in the app)
- Test: `tests/test_packaging_spec.py`

**Interfaces:**
- Produces: the spec ships `copy_metadata("pillow")`, which puts Pillow's `LICENSE` with every vendored library's licence in the bundle.
- Produces: Python's `LICENSE.txt` ships in the bundle's data folder under `python/LICENSE.txt`. A spec function `_python_licence() -> Path` returns the first existing file of `Path(sys.base_prefix) / "LICENSE.txt"` and `Path(sys.base_prefix) / "lib" / f"python{X}.{Y}" / "LICENSE.txt"`, and otherwise raises `SystemExit("qalun.spec: no LICENSE.txt for the Python running the build")`, as the sherpa licence lookup does.

- [ ] **Step 1: Write the failing tests** in `tests/test_packaging_spec.py`:
  - `test_the_spec_ships_pillows_licence_with_its_libraries`: the spec text holds `copy_metadata("pillow")`, and the installed Pillow's metadata `LICENSE` mentions `libjpeg-turbo`, `FreeType` and `HarfBuzz`. Read it with `importlib.metadata.distribution("pillow").files`.
  - `test_the_spec_ships_pythons_licence`: the spec text holds `_python_licence()` and the destination `"python"`. Run the function's two candidate paths for this interpreter and assert one exists.
  - `test_the_notices_point_at_the_shipped_pillow_and_python_licences`: `THIRD_PARTY_NOTICES.md` names `python/LICENSE.txt` and Pillow's `LICENSE` in its `pillow-*.dist-info` folder.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the spec lines and the notices wording. The notice says where a person finds each file in the unzipped app (`_internal/` on Windows and Linux, `Contents/Resources` on macOS), as its other paragraphs do.
- [ ] **Step 4: Run** `tests/test_packaging_spec.py`, then the full suite.
- [ ] **Step 5: Lint, then commit.**

### Task 3: Icons fill their box at every pixel ratio (SHL-1)

**Files:**
- Modify: `src/qurantext/gui/icons.py` (`_pixmap`)
- Test: `tests/test_icons.py`

**Interfaces:**
- Consumes/produces: none new. `_pixmap` renders with `renderer.render(painter, QRectF(0, 0, size, size))`.

- [ ] **Step 1: Write the failing tests.**
  - `test_every_icon_fills_its_box_at_ratio_2`: for every name in `NAMES` at size 20:
    1. Take the alpha mask of the ratio-2 pixmap scaled smoothly to 20×20.
    2. Take the alpha mask of the ratio-1 pixmap, thresholding both at 64.
    3. Assert an intersection-over-union of at least 0.7. Today the mean is 0.13, because the 2× pixmap holds only the top-left quarter.
  - `test_a_fractional_screen_scale_gets_the_whole_icon`: `icon("settings").pixmap(QSize(20, 20), 1.5)`, scaled to 20×20, matches the ratio-1 mask the same way.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the one-line change and import `QRectF`.
- [ ] **Step 4: Run** `tests/test_icons.py tests/test_widgets.py`, then the full suite.
- [ ] **Step 5: Lint, then commit.**

### Task 4: Quran words in the review are drawn in the Quran face (QRN-2)

**Files:**
- Create: `src/qurantext/gui/quran_face.py`
- Modify: `src/qurantext/gui/review/ayah_picker.py` (use the new module; drop its private copy)
- Modify: `src/qurantext/gui/review/word_strip.py` (`paintEvent`, `_paint_word`)
- Modify: `src/qurantext/gui/review/segment_list.py` (the card rows' text cell)
- Modify: `src/qurantext/gui/review/selection_bar.py` (`show_word`)
- Test: create `tests/test_quran_face.py`; keep `tests/test_ayah_picker.py` green

**Interfaces:**
- Produces (in `gui/quran_face.py`):
  - `quran_font_family() -> str`: the bundled `qaloon.10.ttf` family, registered on first use and cached; `""` when it cannot be registered.
  - `with_quran_face(font: QFont) -> QFont`: a copy of *font* whose families are `[quran_font_family(), *font.families()]`, or *font* unchanged when the family is `""`.
- Produces: `WordStrip.font_for(word: TimelineWord) -> QFont`, the font a word is drawn in. It is `with_quran_face(self.font())` when `word.ref.kind == CARD`, else `self.font()`. `_paint_word` draws with it and measures with `QFontMetrics` of it.

- [ ] **Step 1: Write the failing tests** in `tests/test_quran_face.py`:
  - `test_card_text_cells_use_the_quran_face_first`: in a recitation review, the card row's text item `font().families()[0] == quran_font_family()`.
  - `test_caption_cells_keep_the_table_font`: in a lecture review, a caption row's text font does not start with the Quran family.
  - `test_the_strip_draws_card_words_in_the_quran_face`: `strip.font_for(card_word).families()[0] == quran_font_family()`.
  - `test_the_selection_bar_names_a_quran_word_in_the_quran_face`: after selecting a card word, `selection_bar.label.font().families()[0] == quran_font_family()`. After selecting none, the label font is `theme.font("section")`.
  - `test_without_the_quran_face_the_widgets_keep_their_font`: monkeypatch `quran_font_family` to return `""`. All three widgets keep their own font, and painting the strip does not raise.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Move the registration code from `ayah_picker._quran_font_family` as is; `ayah_picker` imports `quran_font_family`.
- [ ] **Step 4: Run and look.** Run `tests/test_quran_face.py tests/test_ayah_picker.py tests/test_review_window.py tests/test_review_widgets.py`, then `PYTHONPATH=src QT_QPA_PLATFORM=offscreen $PY tools/screenshots.py /tmp/claude-shots-task4`.
  - Look at `review-recitation-*` and `review-lecture-*` in both languages.
  - Nothing may be clipped in the strip boxes, the table rows or the selection bar; the Qaloon face is tall.
  - If something is, size the Quran font down to the existing line box, and say so in the report.
  - Then run the full suite.
- [ ] **Step 5: Lint, then commit.**

### Task 5: The basmala card shows the Qaloon mushaf's basmala (QRN-3)

**Files:**
- Modify: `src/qurantext/core/preamble.py:41-43` (`BASMALA_DISPLAY` and its comment)
- Test: `tests/test_basmala.py`

**Interfaces:**
- Produces: `BASMALA_DISPLAY == "بِسْمِ اِ۬للَّهِ اِ۬لرَّحْمَٰنِ اِ۬لرَّحِيمِ"`. This is the form 111 of the shipped text's 113 basmala lines use; the other two add a shadda on the ba.

- [ ] **Step 1: Write the failing test.** `test_the_basmala_card_uses_the_shipped_texts_basmala`:
  1. Read `DEFAULT_QURAN_PATH` (UTF-16).
  2. Collect the stripped lines for which `quran_parser._is_basmala` is true.
  3. Assert that the most common one equals `BASMALA_DISPLAY`.
- [ ] **Step 2: Run it and see it fail.**
- [ ] **Step 3: Implement.** Copy the line from the text file itself, not from this plan. Search `tests/` for the old literal and update any test that pinned it.
- [ ] **Step 4: Run** `tests/test_basmala.py tests/test_subtitles.py tests/test_video_renderer.py`, then the full suite.
- [ ] **Step 5: Lint, then commit.**

### Task 6: A re-render never deletes the earlier video (JRN-3, INT-3)

**Files:**
- Modify: `src/qurantext/core/frame_renderer.py` (`write_frame_video`, about lines 1314–1546)
- Modify: `src/qurantext/jobs/catalog.py` (`job_status`)
- Modify: `src/qurantext/gui/review/window.py` (`closeEvent`, plus a new `_confirm_stop_render`)
- Modify: `src/qurantext/gui/i18n.py` (four keys, both languages); `docs/release-checklist.md` (Words)
- Test: the existing frame-renderer cancel tests (find them with `grep -rn "cancel" tests/test_video_renderer.py tests/test_project_render.py`), `tests/test_catalog.py`, `tests/test_review_window.py`

**Interfaces:**
- Produces: `write_frame_video` encodes into `output_path.with_name(f".{output_path.stem}.{uuid.uuid4().hex[:8]}.part.mp4")`.
  - On success it calls `os.replace(partial, output_path)`.
  - On cancel or failure it unlinks only the partial.
  - When the replace raises `PermissionError`, it unlinks the partial and raises `RuntimeError(f"Could not replace {output_path.name}: it may be open in another program. Close it and render again.")`.
  - Its return value and the recorded video path stay `output_path`.
- Produces: `job_status(project)` returns `REVIEWED` or `NEEDS_REVIEW` (by the review state) when `project.render` names a video that does not exist.
- Produces: the i18n keys `review.stop_render_title`, `review.stop_render_text`, `review.stop_render_stop` and `review.stop_render_keep`.
  - English: "Rendering", "The video is still being rendered. Stop and close? The video you made before stays as it was.", "Stop and close", "Keep rendering".
  - Arabic: written to match the existing `review.render*` lines.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_cancelled_render_keeps_the_earlier_video`: write bytes to the target, render the same project again, and cancel at the first progress event. The target's bytes are unchanged and no `*.part.mp4` is left. Skip without FFmpeg, as its neighbours do.
  - `test_a_finished_render_replaces_the_earlier_video`.
  - `test_a_locked_target_keeps_the_earlier_video_and_says_why`: monkeypatch `os.replace` in `frame_renderer` to raise `PermissionError`. The old bytes stay, no partial is left, and the error says "open in another program".
  - `test_a_render_whose_video_is_gone_is_not_rendered` (catalog).
  - `test_closing_while_rendering_asks_and_keeping_keeps_the_window`.
  - `test_stop_and_close_cancels_the_render` (review window, with `_confirm_stop_render` monkeypatched to `True` or `False`).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
  - In `closeEvent`, the stop question comes first, and only when the window is not already closed and `self._rendering`.
  - The box's default and Escape button is "Keep rendering".
  - Keep the existing unsaved-changes flow after it.
- [ ] **Step 4: Run** the touched test files, then the full suite.
- [ ] **Step 5: Lint, then commit.**

### Task 7: Selecting a word arms its start (JRN-2, REV-1)

**Files:**
- Modify: `src/qurantext/gui/review/word_strip.py` (`__init__`, `select`, the `last_edge` docstring, `paintEvent`)
- Modify: `src/qurantext/gui/review/window.py:954` (the `_nudge` docstring)
- Test: `tests/test_review_window.py` (the tests that pin the end default, such as `test_nudge_moves_the_end_by_fifty_milliseconds`, change to the start); `tests/test_review_widgets.py` or the strip's own tests

**Interfaces:**
- Produces: `WordStrip.last_edge` is `"start"` after construction and after every `select()` of a new word, until an edge is grabbed.
- Produces: `WordStrip.painted_handle() -> tuple[str, WordRef] | None`. It returns the drag's edge while dragging, else the hovered edge, else `(self.last_edge, self.selected)` when a word is selected. `paintEvent` draws that one handle.

- [ ] **Step 1: Write the failing tests.**
  - `test_selecting_a_word_arms_its_start`.
  - `test_a_nudge_after_selecting_a_word_moves_when_it_lights_up`. Click a word's body, press `.`: its start is 0.05 s earlier, and the next word's start is unchanged. Then `,` brings it back.
  - `test_the_armed_edge_is_painted`. After a selection, `painted_handle() == ("start", ref)`. Hovering another word's end returns that hover, and grabbing the selected word's end returns `("end", ref)`.
  - Update the end-pinning tests to the start, with values recomputed from the fixture.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/test_review_window.py` and the strip tests, then the full suite.
- [ ] **Step 5: Lint, then commit.**

### Task 8: The macOS app is signed again after FFmpeg is staged (REL-5)

**Files:**
- Modify: `packaging/ci/stage.sh`. When `dist/Qalun.app` exists, after the copy run `codesign --force --deep --sign - dist/Qalun.app`, with a comment on why: files added under `Contents/MacOS` after PyInstaller signed the bundle break its seal.
- Modify: `packaging/ci/check.sh`. For a `.app` build, run `codesign --verify --deep --strict --verbose=2 dist/Qalun.app` before the doctor. On failure, print `The gate failed: the app's signature does not cover everything in it (codesign --verify; see above).` and exit 1.
- Modify: `packaging/ci/README.md` (one line on each)
- Test: create `tests/test_stage_script.py`; add one test to `tests/test_gate_script.py`

**Interfaces:** none in Python.

- [ ] **Step 1: Write the failing tests.** Each puts a stand-in `codesign` on `PATH` that appends its arguments to a log file.
  - `test_a_mac_build_is_signed_again_after_staging`. With `dist/Qalun.app/Contents/MacOS/qalun` and `vendor/ffmpeg`:
    1. `codesign` is called exactly once, with `--force --deep --sign - dist/Qalun.app`.
    2. When it is called, `dist/Qalun.app/Contents/MacOS/ffmpeg` exists.
  - `test_a_linux_build_is_not_signed`: with `dist/qalun`, `codesign` is not called.
  - `test_an_app_whose_signature_is_broken_fails_the_gate`: a `.app` stand-in, with `codesign` exiting 1. The gate exits non-zero with the sentence above, and the doctor never runs.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/test_stage_script.py tests/test_gate_script.py tests/test_package_script.py`, then the full suite.
- [ ] **Step 5: Lint, then commit.**

### Task 9: The guide, README and release notes say what the app does and needs (JRN-1, JRN-2, JRN-6/REL-4, REL-6, RC-2)

**Files:**
- Modify: `USER_GUIDE.md`, `README.md` (`Just want to use it?`, `System requirements`), `.github/workflows/release.yml` (the release `body`)
- Test: create `tests/test_user_docs.py`

**What the words must say** (in the guide's plain style):

- **Step 3 of "Making your first video"** (JRN-1):
  - A *Recitation* needs its surah and the first and last ayah recited.
  - *Detect automatically* is the *Lecture*'s choice, for the surah being studied.
- **Troubleshooting, "The video has the wrong ayat":**
  - Recitation: check the surah and ayat chosen, and start again.
  - Lecture: use **Surah on the cards**, **Change ayah…** or **Show ayah… from here**.
- **The nudge line** (JRN-2): click the word and press **.** to make it light up earlier or **,** to make it light up later, 50 ms a press. To move its end instead, drag the word's left edge.
- **Step 2, "Unzip and open"** (JRN-6/REL-4):
  - Windows warns about an unknown publisher: **More info → Run anyway**.
  - macOS refuses the first open: open **System Settings → Privacy & Security** and choose **Open Anyway**.
  - Linux: extract with the file manager or `unzip`.
- **"What your computer needs"** (REL-6, RC-2):
  - Windows 10 or 11 (64-bit).
  - A Mac with Apple silicon (M1 or newer).
  - Linux with glibc 2.38 or newer (for example Ubuntu 24.04, Linux Mint 22, Debian 13, Fedora 39 or newer).
  - Memory: keep the existing line.
  - Space: about 1 GB free, plus room for your videos.
- **README:** the same requirements in its "System requirements" list.
- **`release.yml` body:** the macOS line gives the Privacy & Security → Open Anyway route, with "(on macOS 14 or older, right-click → Open also works)", and a "Needs:" line with the three systems.

- [ ] **Step 1: Write the failing tests** in `tests/test_user_docs.py`:
  - `test_the_guide_offers_detect_automatically_for_lectures_only`: every paragraph of `USER_GUIDE.md` that contains "Detect automatically" also contains "Lecture" or "lecture".
  - `test_the_guide_names_what_each_system_needs`: it contains "Apple silicon", "glibc 2.38", "Open Anyway" and "Run anyway".
  - `test_the_release_notes_give_macos_open_anyway_and_the_requirements`: the `release.yml` text contains "Privacy & Security", "Open Anyway", "Apple silicon" and "glibc 2.38".
  - `test_the_guide_does_not_promise_300_mb`: "300 MB" is not in the guide.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Edit the three files.**
- [ ] **Step 4: Run** `tests/test_user_docs.py tests/test_gate_script.py` (it reads `release.yml`), then the full suite.
- [ ] **Step 5: Lint, then commit.**

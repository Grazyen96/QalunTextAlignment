# Review editor, home window and subtitle export — design

**Date:** 23 September 2026
**Status:** approved in conversation, awaiting spec review

## Why

The forced-alignment prototype (`docs/findings/forced-alignment-prototype.md`)
concluded that recitation timing QA has to be a person listening, and that an
aligner's confidence cannot point them at the problem. The app has no way to
listen: the subtitle editor is two tables of spin boxes, with no playback, no
waveform and no word timings. The one error we have measured — a five-second
rift at the end of 25:7 — cannot be seen or fixed in it.

Two defects make any editing pointless today, and are fixed here first:

1. **The window never renders corrections.** `gui/jobs.run_job` renders from the
   match file. Only the CLI's `generate-video --project` reads the project.
2. **Card timing edits are ignored everywhere.** `render_video` reads cards with
   `load_matches(matches_path)`; the project's `cards` are never rendered, only
   its `captions`.

## Decisions (settled)

| Question | Decision |
|---|---|
| Playback | Qt Multimedia `QMediaPlayer` (adds `PySide6-Addons`), position smoothed between Qt's updates |
| Interface language | English and Arabic, switchable; Arabic is right-to-left |
| Word retiming | Both recitation ayah words and lecture caption words |
| Subtitle export | An Export dialog: formats and destination, no re-render |
| Job flow | Start matches, then opens review. Rendering is a separate step. "Render right away" stays as an option |
| Time axis | Always left to right, in both languages. Arabic text inside a word box is shaped RTL as usual |

## Out of scope

- A new render engine, styles or MOGRT-like templates.
- Editing Quran characters. Cards stay reference + timing only.
- Re-running recognition or alignment from inside the editor.
- Usage telemetry. Architecture decision 5 is "fully offline". Should a public
  download page or an in-app link to the Releases page be added later, it gets
  UTM parameters so downloads are measurable; the app itself sends nothing.

## 1. Foundations (no UI)

### 1.1 Project file v2

`jobs/project.py`, `PROJECT_VERSION = "2"`. Version 1 files load and are
upgraded on the next save; unknown top-level keys are preserved (today they are
dropped, which would erase anything a newer build wrote).

New fields:

```json
{
  "matches": "furquanTra7-11_recitation.json",
  "review": {"state": "needs_review", "reviewed_at": null},
  "render": {"video": "../videos/furquanTra7-11.mp4", "preset": "social",
             "basmala_offset_s": 3.42, "rendered_at": "2026-09-23T10:12:00"}
}
```

- `review.state` ∈ `needs_review` | `reviewed`. Any timing or text edit after a
  render keeps `reviewed` but marks the render stale, which the job list shows
  as "changed since render". Staleness is a content hash of `cards` + `captions`
  recorded in `render.content_hash`, not a timestamp: saving the project right
  after a render must not make that render look stale.
- `render` is written by the app after a successful render. Its
  `basmala_offset_s` is what the Export dialog uses to put subtitles on the
  rendered video's timeline.
- Per-word `"edited": true` marks words a person has retimed, so the list can
  show "2 retimed" and a later automatic pass never silently overwrites them.

### 1.2 Timing model — `core/timing_edit.py` (pure Python)

The only place timing rules live; widgets call it and never write timings
themselves. Operates on one list of `{word, start, end}` at a time (a card's
`word_timings` or a caption's `words`).

- `retime(words, i, start=None, end=None) -> words` — clamps so words never
  overlap or reorder: `words[i-1].start < start`, `end <= words[i+1].start`,
  `end > start + MIN_WORD_S` (0.04 s).
- `ripple(words, i, delta) -> words` — shifts word *i* and every later word in
  the list by *delta*, clamped against word *i-1*. This is the tool for the
  25:7 rift, where a run of words is uniformly late.
- `derive_card_windows(cards)` — for cards that carry word timings, a card's
  `start_time` is its first word's start and its `end_time` is the next card's
  first word start. The last card keeps its `end_time` (the audio end, as detection
  writes it) unless its last word now ends later, in which case it extends to that
  word's end. This is the
  latched tiling `assign_recitation_word_timings` already produces, kept true
  after edits. Cards without word timings (lecture) keep directly editable
  start/end.
- `CaptionCue.edited(text)` (stays in `jobs/project.py`, since `core` must not
  import `jobs`) changes behaviour: if the new
  text has the same word count, word timings are kept and relabelled
  positionally; otherwise they are dropped as today. Fixing a misheard word
  therefore no longer throws away its karaoke timing.

Every function returns new lists; undo is a snapshot stack (see 2.6).

### 1.3 Render and export read the project

- `RenderRequest` and `ExportRequest` gain `cards: tuple[dict, ...] | None`.
  When given, it replaces `load_matches(matches_path)`. The match path is still
  required: the basmala splice reads its `meta`.
- `export.build_cues` takes the same `cards` override.
- New `jobs/project_render.py`:
  `render_project(project, output, *, preset, subtitles, formats, progress, cancel)`
  and `export_project_subtitles(project, destination_stem, formats, *, timeline)`,
  the only entry points the GUI uses. `timeline` is `"video"` (apply
  `render.basmala_offset_s`) or `"audio"` (original recording).
- The CLI's `--project` path is switched to `render_project` so both surfaces
  share one route.

### 1.4 Job flow — `gui/jobs.py`

`run_job` becomes two calls:

- `run_matching(spec) -> Project` — detection or stated range as today, then
  derive and save `<matches stem>.qalun.json` beside the match file. Always, not
  only when the editor opens.
- `run_render(project, preset, subtitles) -> RenderOutcome` — via
  `render_project`, then records `project.render` and saves.

`JobSpec.render_right_away` (default False) chains them for jobs you trust.

### 1.5 Job list — `jobs/catalog.py`

`list_jobs(dirs) -> list[JobEntry]` scans the recitation and lecture match
folders for `*.qalun.json`, newest first, with name, mode, range or ayah count,
and status (`needs review`, `reviewed`, `rendered`, `changed since render`). A
file that fails to parse is listed as damaged, not skipped silently.

### 1.6 Waveform peaks — `core/waveform.py`

`compute_peaks(audio, per_second=100) -> Peaks(min, max, rate, duration)`.
Streams 16 kHz mono float32 from FFmpeg in chunks and keeps only min/max per bin,
so an hour-long lecture costs ~2.9 MB instead of the ~230 MB a full decode would.
Cached beside the project as `<project stem>.peaks.npz`, keyed by the audio's
content hash (`services/transcript_cache._audio_digest`, promoted to a public
helper). Runs in a worker
thread; the editor shows a "reading audio" placeholder until it arrives.
`core/coverage.py` is left as it is.

## 2. Review editor — `gui/review/`

Replaces `gui/editor.py`. One package, one widget per file:

| File | Responsibility |
|---|---|
| `window.py` | `ReviewWindow`: layout, toolbar (Export subtitles…, Render with corrections), save/close, unsaved-changes prompt |
| `player.py` | `Player` protocol + `QtPlayer` (QMediaPlayer + QAudioOutput) + `FakePlayer` for tests |
| `waveform_view.py` | Paints peaks, gap bands, playhead; click/drag to seek; zoom slider; follows the playhead |
| `word_strip.py` | Word boxes at their times under the waveform; drag edges to retime, Shift-drag to ripple |
| `frame_view.py` | Live frame at the playhead |
| `segment_list.py` | Ayah cards (lecture: cards and caption lines) with time, locked text, retimed count |
| `commands.py` | Undo stack of timing snapshots |

### 2.1 Playback and sync

`QtPlayer` wraps `QMediaPlayer`. Qt's `positionChanged` arrives in coarse steps,
so `position()` returns the last reported position plus the time elapsed on a
`QElapsedTimer` since it arrived, times the playback rate. It is re-anchored on
every report, seek, pause and rate change, and clamped so it never runs
backwards. A 60 Hz UI timer reads it while playing. Rates: 1×, 0.75×, 0.5×.

If Qt Multimedia cannot load (no backend, missing library), the editor still
opens: playback controls are disabled with a one-line reason, and waveform,
word strip, frame and all editing keep working. `qalun --doctor` reports it.

### 2.2 Waveform and gaps

Time runs left to right in both languages. Gap bands come from
`find_uncovered_speech`, which now runs automatically when the editor opens
(in a worker) and again after each edit settles (debounced 1 s). The warning
strip lists them, each with Jump.

### 2.3 Word strip and retiming

- Click a word: select it and seek to its start.
- Drag its left or right edge: `retime`. Shift-drag the body: `ripple`.
- Keys: space play/pause; ←/→ previous/next word; `[` / `]` set the selected
  word's start / end at the playhead; `,` / `.` nudge the selected edge by
  −/+50 ms (Shift: 10 ms); Ctrl+Z / Ctrl+Shift+Z undo/redo; Ctrl+S save.
- The selected-word bar shows the word, its times, −50 ms, +50 ms and
  "Snap to playhead".
- Recitation: after any retime, `derive_card_windows` updates card start/end.

### 2.4 Live frame

Calls `render_frame_pillow` with the active card and caption at the playhead,
at a fixed small size (270×480 portrait, 480×270 landscape, from the job's
preset aspect). It draws on pause and seek immediately and at most 5 times a
second while playing, dropping frames rather than queueing them. The frame
shows the edited timings, so it previews exactly what "Render with
corrections" will produce.

The basmala splice happens at render time and is not on the editor's timeline;
the editor always shows the original recording.

### 2.5 Segment list

Clicking a row seeks there and scrolls the strip. The row under the playhead is
highlighted while playing. Quran text is read-only with the existing tooltip.
Lecture caption text is editable in place (via `edit_caption_text`). "Remove"
stays, for false-positive cards and captions. "Mark as reviewed" sets
`review.state`.

### 2.6 Undo

Each edit pushes a snapshot of the affected list, so memory is bounded by edit
count × list size. A drag is one undo step, pushed on release. Save does not
clear the stack.

### 2.7 Export subtitles dialog

- Formats: SRT, WebVTT, ASS (checkboxes; SRT preselected).
- Destination: folder + filename stem, defaulting to the video's folder and stem.
- Timeline: "Match the rendered video" (only offered when `project.render`
  exists; applies the basmala offset) or "Match the original recording".
- Writes via `export_project_subtitles`. No re-render. Lists the files written,
  with "Show in folder".
- Content is what the renderer uses today: recitation = canonical ayah text per
  ayah from the store; lecture = the (corrected) captions.
- Unsaved edits are saved first, so the exported files and the project agree.

### 2.8 Render with corrections

Saves, then `run_render` in the existing worker with progress and Cancel, then
updates `project.render`. The Subtitles choice (burn in / separate files / both)
comes from More options on the home window and is stored in `project.export`.

## 3. Home window — `gui/main_window.py`

- **Left: Your jobs** from `list_jobs`, with status. Double-click (or Enter)
  opens the review. Context menu: Show in folder, Remove from list (hides it by
  adding the path to a hidden list in `QSettings`; deleting files stays a
  file-manager action).
- **Right: New job.** Drop zone; Recitation | Lecture as two toggle buttons;
  surah and ayat (recitation); video size with readable names ("Portrait
  1080×1920 · 30 fps").
- **More options** (collapsed, state remembered): Quran text override, output
  folder, subtitles (burn in / separate files / both), render right away.
- **Start** runs matching and opens the review when it finishes. The row appears
  in Your jobs immediately with a progress bar in place of its status.
- Disabled Start gets its reason as visible helper text, not only a tooltip.
- "Preview a frame" moves into the review window, where it is always available
  (the live frame), so the home window no longer needs it.

## 4. Two languages — `gui/i18n.py`

- A plain Python table, `STRINGS = {"en": {...}, "ar": {...}}`, and `t(key, **fmt)`.
  No `.ts`/`.qm` build step, so nothing extra to ship or to break in packaging.
- Language is stored in `QSettings`; default follows the system locale (Arabic
  if the locale is `ar*`, else English). Switching rebuilds the open windows
  in place, with `QApplication.setLayoutDirection(RightToLeft)` for Arabic.
- The waveform, word strip and time fields are pinned `LeftToRight` so time
  keeps its direction; everything else mirrors.
- Numbers and times stay Western digits in both languages (they are timing
  values a reviewer compares with other tools).
- A test asserts both tables have the same keys and the same `{placeholders}`.
- The Arabic strings are drafted by the implementer and **must be reviewed by a
  native speaker before release**; the spec does not claim they are final.

## 5. Packaging

- `pyproject.toml` `gui` extra adds `PySide6-Addons` pinned to the same version
  range as `PySide6-Essentials`.
- `packaging/qalun.spec`: `QtMultimedia` in hiddenimports; confirm the Qt FFmpeg
  multimedia plugin is collected on all three platforms; keep the existing
  excludes (none of them is Multimedia).
- `config/preflight.py` gains a "playback" check; `packaging/ci/check.*` runs it.
- Size budget: record the before/after size of each platform's archive in
  `packaging/README.md`. Expected +30–40 MB; if it is far larger, stop and
  review before merging.

## 6. Testing

- **Pure units:** `timing_edit` (clamp, ripple, card windows, text edit keeps or
  drops words), project v1→v2 upgrade and unknown-key preservation, catalog
  status derivation, peaks (synthetic sine → known min/max; chunk boundaries),
  i18n key parity, render/export honouring `cards` (a moved card changes the
  rendered frame at that time and the exported cue times).
- **The 25:7 case as a fixture:** load the real `furquanTra7-11` project, ripple
  the late words, and assert the uncovered-speech gap at 16.7–24.2 s is gone.
- **Widgets, offscreen, with `FakePlayer`:** drag and keyboard edits go through
  `timing_edit`; undo restores; Export writes the chosen formats with the right
  offset; unsaved-changes prompt; language switch flips direction but not the
  waveform's.
- **Sync:** `QtPlayer`'s smoothing tested with an injected clock (monotonic,
  re-anchors on report, respects rate).
- **Manual, before merge:** play a real recitation in the packaged app on
  Windows and Linux, fix the 25:7 rift by ear, render, and confirm the MP4 and
  the exported SRT match what the editor showed.

## 7. Order of work

1. Foundations: project v2, `timing_edit`, render/export from project,
   job flow split, catalog, peaks. Fixes both defects above on its own.
2. Review editor (player, waveform, word strip, frame, list, undo, export
   dialog, render with corrections).
3. Home window.
4. i18n and RTL.
5. Packaging and the manual check.

Each step keeps the suite green and the app usable; step 1 is worth merging
even if the rest waits.

# Phase B: the home window — design

Date: 2026-10-13 · Status: approved in conversation, awaiting written-spec review

## 1. Purpose

Phase A (`2026-10-13-phase-a-presentation-layer-design.md`, merged) gave the
app a theme, icons, composites and an app icon without moving anything. The
audit (`docs/ux-audit-2026-10-13.md` §2.2, §4.1) left the home window's
structure as it was: a form stretched across the window with machine-level
settings folded into "More options", a job list of bare text rows that only
refreshes on demand, two progress bars for one job, settings scattered over
the footer, the form and two other windows, and an empty first launch that
says one sentence. Phase B restructures the home window and gathers the
settings.

Success means:

- First launch explains the two kinds of job on screen and leads to the drop
  zone.
- The form reads top to bottom as the job's own choices only; every
  machine-level setting is in one Settings dialog reachable from the header.
- A job is recognisable in the list by its thumbnail, name and a status
  chip, and the list follows the folders without a Refresh click.
- While a job runs there is one progress indicator in the form and the
  list's thin bar; the status line carries words, not percentages.
- The window fits 1024×680 in English and in Arabic.
- Every widget attribute the tests reach keeps its name; `JobSpec`,
  `Prefs` keys, project files and the CLI are unchanged.

Decisions taken in the brainstorm (owner's answers):

| Question | Decision |
|---|---|
| Where machine-level settings live | **A Settings dialog** with tabs, opened from a gear in the header |
| Transcription engine | **Moves to Settings**; the form shows a note when the online engine is set |
| Job thumbnail | **A frame rendered from the project's look**, cached as PNG |
| Header contents | **Theme toggle + Settings gear + Help**; language moves into Settings |

Out of scope (later phases): the review window (C), the Look panel and
Episode dialog (D), animation and the Arabic UI font (E), hover-only row
actions (dropped for accessibility), a settings page inside the window.

## 2. What the user sees

### 2.1 The header

A 48 px strip across the top of the home window: the app icon at 24 px, the
word "Qalun" in the title font, a stretch, then three tool buttons with
icons and tooltips: **Theme** (`sun` when the resolved theme is dark, `moon`
when light; a click pins the opposite theme into `Prefs.theme`, so a person
on System who clicks gets Light or Dark explicitly, and System is chosen
again in Settings), **Settings** (`settings`, opens the dialog), **Help**
(`circle-question-mark`, opens the project's README on GitHub in the
browser; phase C points it at the shortcut sheet). The footer is gone:
"Open log folder", Language and the Theme combo now live in Settings.

### 2.2 The form

Under the header the splitter stays: the job list on the left at 300 px,
the form on the right. The form sits in a column with a maximum width of
560 px, aligned to the leading edge (left in English, right in Arabic), so
a surah combo no longer spans the window. Top to bottom:

1. "New job" section header.
2. The drop zone card: an `upload` icon, "Drop an audio file, or choose one",
   the Choose… button. Once a file is chosen: a `file-music` icon, the name
   and the folder, elided as today.
3. The mode toggle (Recitation / Lecture, with icons, as phase A left it)
   and under it one line of secondary text that follows the choice:
   "Times the ayat of a recitation, word by word." / "Finds the ayat quoted
   in a lecture and shows them as cards."
4. Surah and Ayat (recitation) or Surah (lecture), Video size — unchanged.
5. More options, holding only Subtitles, Files and Render right away.
6. An engine note, shown only when `Prefs.engine == "whisperx"`: "Transcribes
   online with WhisperX, which uploads the recording." followed by the
   no-token sentence when the token is missing, and a link "Change in
   Settings" that opens the dialog on its Transcription tab.
7. Start, primary, full width of the column; the reason it is disabled in
   secondary text under it.
8. The status line, for answers, notices and how the last job ended.

While a job runs: Start is hidden and the progress bar takes its slot at the
same height, text visible, reading the stage and percentage ("Transcribing —
42%", with the ETA when known: "Transcribing — 42%, about 1m 20s left"),
Cancel beside it; the status line shows only held answers and, at the end,
the outcome. The 24 px full-width bar and the separate progress sentence
on the status line are gone.

### 2.3 The job list

The section header "Your jobs" with Refresh as its trailing icon button
stays. Each row is a card: a 48×48 thumbnail at the leading edge; beside it
the name in bold, under the name a `StatusChip` and the detail line
"{mode} · {scope}", and at the trailing edge the modified date in the
locale's short format. Chips: Needs review and Changed since render in
`attention` with `circle-alert`; Rendered in `accent` with `film`; Reviewed
`neutral` with `circle-check`; Damaged `attention` with `triangle-alert`
and no detail line. Rows stay `QListWidgetItem`s with a row widget, so
selection, Enter/double-click to open, the context menu and the three
buttons under the list (Open, Show in folder, Remove from list) are
unchanged. The running row keeps its text and 6 px bar.

The list follows its folders: a file appearing, vanishing or being renamed
in any job folder refreshes the list within half a second. Refresh stays
for a folder on a drive the watcher cannot see.

### 2.4 The empty state

With no jobs, the list area shows the app icon at 96 px, "No jobs yet" in
the section font, one line "Drop a recording on the right to start one.",
and two small cards, Recitation and Lecture, each with its icon and the
same one-line description as the form. Clicking a card selects that mode in
the form and moves focus to the drop zone's Choose… button. While the
folders are being read the area says "Reading your jobs…" as today.

### 2.5 The Settings dialog

A modal `QDialog`, title "Settings", with a `QTabWidget` of five tabs and a
Close button. Every control writes to `Prefs` as it changes, as the form
does; there is no OK/Cancel.

| Tab | Controls |
|---|---|
| General | Language (combo, `language_combo`); Theme (combo System / Light / Dark, `theme_combo`). |
| Transcription | On this computer / WhisperX online radios (`engine_buttons`); the no-token sentence naming the `.env` folder when the token is missing. |
| Files | Quran text: current label, Choose…, Use the shipped text. Output folder: current label, Choose…, Default. Job folders: a list of the extra folders the job list scans (`Prefs.job_dirs`), Add folder…, Remove. |
| Videos | Default look: "Based on {preset}" (or the preset name), Reset to Night gold. Episode defaults: Intro: {name or None}, Outro: {name or None}, each with Clear. |
| About | "Qalun {version}", Open log folder (`log_link` stays a link), Third-party notices (opens the bundled `THIRD_PARTY_NOTICES.md` with the system viewer), Qalun on GitHub (link). |

A language change is applied through `MainWindow.set_language`, which keeps
its refusal while a review window or a job is busy; on refusal the combo
snaps back and the reason shows in the dialog. On success the dialog closes
(it was built in the old language) and the window rebuilds as it does today.

## 3. Modules

Four icons join the bundle (`tools/fetch_icons.py` and `icons.NAMES`, Lucide
1.56.0 names): `upload`, `file-music`, `circle-alert`, `triangle-alert`.
The README URL for Help is `https://github.com/Grazyen96/QalunTextAlignment#readme`.

### 3.1 `gui/home/header.py` — `HeaderBar(QWidget)`

Icon label, title label (`theme.font("title")`), stretch, three
`QToolButton`s: `theme_button`, `settings_button`, `help_button`
(auto-raise, 20 px icons via `set_icon`, tooltips). Signals:
`theme_toggle_requested`, `settings_requested`, `help_requested`. A method
`show_theme(tokens_name: str)` sets the toggle's icon (`sun` for dark,
`moon` for light) and tooltip; the window calls it after every
`apply_theme`.

### 3.2 `gui/home/settings_dialog.py` — `SettingsDialog(QDialog)`

`SettingsDialog(prefs, *, parent, quran_default, db_path, tab=None)`;
`tab in ("general", "transcription", "files", "videos", "about")` opens on
that tab. Attributes named above plus `quran_label`, `quran_choose_button`,
`quran_reset_button`, `output_label`, `output_choose_button`,
`output_reset_button`, `job_dirs_list`, `add_dir_button`,
`remove_dir_button`, `look_label`, `look_reset_button`, `intro_label`,
`intro_clear_button`, `outro_label`, `outro_clear_button`,
`version_label`, `notices_link`, `github_link`, `close_button`. Signals:
`language_requested(str)` (the window answers through `set_language` and
calls `dialog.language_refused(reason)` or closes it), `theme_requested(str)`,
`files_changed` (Quran text, output folder or job folders changed; the
window tells the form and the list). The dialog reads and writes `Prefs`
directly for everything else. The Quran, output and engine behaviour moves
here from `NewJobPanel` unchanged in effect (`_usable_override`, the file
filters, `_token_missing`).

### 3.3 `gui/home/new_job.py` — `NewJobPanel`

Loses the Quran, output and engine rows and their buttons. Gains
`description_label` under the mode toggle, `engine_note` (a `QLabel` with a
`settings` link emitting `settings_requested`), and `reload_settings()`
which re-reads `prefs.quran_override`, `prefs.output_dir`, `prefs.engine`,
refills the surahs when the Quran text changed, and refreshes the note.
`spec()` reads engine, Quran text and output folder from prefs. The column:
a `QWidget` with `setMaximumWidth(560)` inside an `QHBoxLayout` with a
trailing stretch (which the layout mirrors in Arabic). Start is
`make_primary` and spans the column; `problem_label` moves under it.
`progress_bar` stays a `QProgressBar` (attribute kept), 36 px tall, text
visible, in Start's slot; `set_progress(fraction, text)` now puts *text* on
the bar's format and leaves the status line alone; `show_status` is
unchanged. `set_running` swaps Start for the bar + Cancel.

### 3.4 `gui/home/job_list.py` — `JobListPanel`, `_JobRow`, `EmptyState`

`_JobRow` gains `thumb_label` (48×48, the cached PNG or the fallback tile),
`chip: StatusChip`, `date_label` (secondary font, `QLocale().toString(date,
QLocale.FormatType.ShortFormat)`); `name_label` and `detail_label` keep
their names and `_detail_text` drops the status part (the chip carries it).
`EmptyState(QWidget)` with `recitation_card`, `lecture_card` (clickable
`Card`s) and signal `mode_chosen(str)`; the panel re-emits it as
`mode_requested(str)` and `MainWindow` forwards it to the form. The watcher:
`QFileSystemWatcher` on `job_dirs_for(prefs.job_dirs)` (existing folders
only), re-armed in `refresh`, `directoryChanged` into a 500 ms single-shot
`QTimer` into `refresh`.

### 3.5 `jobs/thumbnails.py` — `thumbnail_for(project, cache_dir) -> Path | None`

Pure Python, no widgets, runs inside `_read_jobs` on the worker. Key:
`sha1(str(project.path) + mtime + json.dumps(project.style, sort_keys=True))`;
file `cache_dir / "thumbs" / f"{key}.png"`. On a miss: the look from
`look_from_style(project.style, base_dir=project.path.parent)`, the preset's
aspect from `job_settings(project).preset`, long side 96 px, the first
card (by start time) rendered with `render_frame_pillow` at that size and
`reserve_caption_band=False`, converted BGR→RGB and saved as PNG. A project
with no cards, or any exception, returns `None` and logs at debug; the
row then draws a tile in the look's `frame_bg` with the mode icon tinted
`on_accent`-or-text by lightness. Old files are not pruned (a few KB each;
the cache dir is the user's cache). `JobEntry` gains `thumbnail: Path | None`
and `background: tuple[int, int, int] | None`.

### 3.6 `gui/main_window.py`

Builds the `HeaderBar` above the splitter and drops the footer; wires
`settings_requested` to `_open_settings(tab=None)`, which runs the dialog
modally, then calls `new_job.reload_settings()` and `job_list.refresh()`
when `files_changed` fired; `theme_toggle_requested` to a toggle that
writes `Prefs.theme` and calls `apply_theme`; `help_requested` to
`QDesktopServices.openUrl` on the README URL; the form's
`settings_requested` to `_open_settings("transcription")`; the list's
`mode_requested` to `new_job.select_mode(mode)`. `set_language` keeps its
rebuild; `_language_busy` is unchanged. `language_combo`, `theme_combo` and
`log_link` are attributes of the dialog now; the window keeps
`set_theme(code)` from phase A.

### 3.7 Strings

New keys in both languages: `home.header.theme_to_dark`,
`home.header.theme_to_light`, `home.header.settings`, `home.header.help`,
`home.mode.recitation.desc`, `home.mode.lecture.desc`, `home.engine.note`,
`home.engine.change`, `home.empty.title`, `home.empty.hint`,
`home.detail` ("{mode} · {scope}"), `settings.title`, `settings.tab.*` (5),
`settings.job_dirs`, `settings.add_dir`, `settings.remove_dir`,
`settings.look`, `settings.look.based_on`, `settings.look.reset`,
`settings.episode`, `settings.episode.intro`, `settings.episode.outro`,
`settings.episode.none`, `settings.episode.clear`, `settings.version`,
`settings.notices`, `settings.github`, `settings.close`,
`home.progress.*` keep their texts (now shown on the bar). The Arabic
strings await native review with the rest.

## 4. Data flow

```
HeaderBar ─settings_requested─▶ MainWindow._open_settings ─▶ SettingsDialog(prefs)
   SettingsDialog writes Prefs as controls change
   SettingsDialog ─language_requested─▶ MainWindow.set_language (may refuse)
   SettingsDialog ─theme_requested────▶ MainWindow.set_theme ─▶ apply_theme ─▶ header.show_theme
   SettingsDialog ─files_changed──────▶ (on close) new_job.reload_settings(); job_list.refresh()
HeaderBar ─theme_toggle_requested─▶ MainWindow: prefs.theme = opposite; apply_theme
JobListPanel.refresh ─▶ worker: list_jobs + thumbnail_for each ─▶ _on_listed ─▶ rows (chip, thumb, date)
QFileSystemWatcher.directoryChanged ─▶ 500 ms timer ─▶ refresh
EmptyState.mode_chosen ─▶ JobListPanel.mode_requested ─▶ NewJobPanel.select_mode ─▶ choose_button.setFocus
NewJobPanel.spec() reads prefs.engine / quran_override / output_dir
```

## 5. Error handling

- A watcher that cannot watch a folder (missing, unreadable, too many
  watches) is ignored: Refresh still works and the list is read as today.
- A thumbnail that cannot be rendered or written yields the fallback tile;
  a cache directory that cannot be created disables caching for that read
  (render in memory is still attempted once, not persisted).
- A language refusal shows the reason in the dialog and snaps the combo
  back; nothing else changes.
- Removing the folder of a running job from Settings takes effect at the
  next refresh; the running row is unaffected.
- The help URL failing to open (no browser) is reported on the status line.
- The notices file missing from a build disables the link with a tooltip.

## 6. Testing

- `tests/test_settings_dialog.py`: every tab's controls round-trip into
  prefs; opening on a named tab; the Quran override, output folder and
  engine tests moved from `tests/test_home_panels.py` (same assertions,
  against the dialog); language refusal snaps back and shows the reason;
  `files_changed` fires for Quran, output and job-folder changes.
- `tests/test_thumbnails.py`: cache key changes with mtime and style, not
  with time; a hit does not re-render (monkeypatched renderer counts); a
  project with no cards returns None; a renderer exception returns None;
  the PNG has the preset's aspect with long side 96.
- `tests/test_home_panels.py`: rows carry chip kind and text per status,
  the date label, the thumbnail or fallback tile; the empty state's cards
  select the mode and focus Choose…; the watcher's timer fires `refresh`
  once for three quick `directoryChanged` emissions (emit the signal
  directly on the watcher); the form's column is ≤ 560 px wide; the engine
  note shows only for whisperx and its link opens Settings on the
  Transcription tab; `set_progress` puts the text on the bar and leaves the
  status line; the More options form has exactly the three per-job rows.
- `tests/test_gui.py`: the 1024×680 fit in English **and Arabic**; the
  header's theme toggle flips the pref and the palette; `_open_settings`
  reloads the form after a Quran change.
- `tests/test_rtl.py`: the header mirrors; the form column sits at the
  right; the empty-state cards mirror.
- `tools/screenshots.py` gains `settings-<tab>` and `home-empty` images.

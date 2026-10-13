# Phase C: the review window — design

Date: 2026-10-14 · Status: approved in conversation, awaiting written-spec review

## 1. Purpose

Phases A and B (merged) gave the app its presentation layer and a
restructured home window. The review window still has the audit's two
biggest faults (`docs/ux-audit-2026-10-13.md` §2.3): its timeline column
leaves over half its height blank while the segment table, the thing a
lecture reviewer edits, gets a fifth of the window; and the timeline has no
time ruler, so the only time reference is the clock. Its transport is text,
its toolbar is eleven equal buttons, its warnings push the body down when
they appear, a finished render blocks the window with a dialog, and the
shortcuts are one elided line. Phase C relays out the window and fixes each
of these.

Success means:

- In a lecture at 1280×800 the segment table shows at least eight rows.
- The timeline reads: a ruler with ticks and times, a visible span readout,
  a playhead mark, a hover time.
- Every transport action has an icon button; the nudges sit with the
  transport; the rate is one click.
- Render is the one primary action on the toolbar; the groups read apart.
- Notices, coverage gaps and a finished render appear in a banner that
  never moves the body and never blocks the window; failures still get a
  dialog.
- Every shortcut is discoverable from a sheet opened by `?`.
- Every widget attribute the tests reach keeps its name; the session, the
  viewport and `core.timing_edit` are unchanged; keyboard bindings are
  unchanged.

Decisions taken in the brainstorm (owner's answers):

| Question | Decision |
|---|---|
| Layout | **Two columns**: preview + Look on the left, timeline + table on the right |
| Lecture's cards and captions | **One table** on the right, cards then captions, as today |
| A finished render | **Banner for success, dialog only for failure** (and cancel) |
| Preview | **Fit / 100% toggle and a full-size view on double-click**, in this phase |

Out of scope (later phases): the Look panel's re-flow and the Episode
dialog (D), animation and the Arabic UI font (E), splitting the segment
table, hover-only controls.

## 2. What the user sees

### 2.1 Layout

Under the toolbar and the banner, a horizontal `QSplitter` with two
columns.

- **Left column**, width = the preview's width + 2 × 12 px, not
  collapsible: the preview (`FrameView`) on top, under it a row with the
  fit / 100% toggle (two small checkable tool buttons, `zoom-out` /
  `zoom-in` icons, tooltips "Fit" / "Actual size"), then the Look panel in
  its scroll area taking the rest of the height.
- **Right column**, stretch 1: the zoom row (label, slider, span readout,
  `−` / `+` icon buttons), the time ruler, the waveform, the word strip,
  the transport row, the selection bar, then the segment table with
  stretch 1. The old vertical splitter and the old `addStretch` go.

The status bar keeps one line: "Space plays · ← → words · [ ] set
start/end · ? all shortcuts".

### 2.2 The timeline

- **Time ruler** (`TimeRuler`, 24 px): major ticks with `mm:ss` labels in
  the clock font, minor ticks between; the major step is the smallest of
  1, 2, 5, 10, 30, 60, 120, 300 s whose labels (measured) do not overlap
  at the current span and width. Right to left like the strip. A small
  accent triangle marks the playhead. Hover shows the time under the
  pointer as a tooltip; a click or drag seeks.
- **Zoom row**: the slider as today; a readout "20 s shown" (`review.span`,
  seconds rounded, minutes when ≥ 60 s); `zoom_out_button` / `zoom_in_button`
  step the slider by 10 of its 100 steps.
- **Waveform**: bars in the accent colour at 55 % alpha on the panel
  surface, the bars of the word under the playhead at full alpha; gap bands
  drawn as the attention colour at 25 % with a 1 px attention outline;
  playhead 2 px; "reading" / "missing" placeholders in the secondary colour.
- **Word strip**: boxes with 4 px radius, 1 px `border` outline; the
  selected box filled with the accent and its text in `on_accent`; the box
  under the playhead outlined 2 px accent; the edited bar stays 3 px amber
  at the top; the hover handle 6 px wide; `sizeHint` height 44 and
  `minimumHeight` 40.
- **Transport row**, leading to trailing: `prev_word_button` (`skip-back`),
  `play_button` (`play` / `pause`), `next_word_button` (`skip-forward`), the
  clock, the rate as three checkable segment buttons `rate_buttons[1.0 |
  0.75 | 0.5]` (replacing `rate_combo`; the attribute `rate_combo` is
  removed and its tests move to the buttons), then the nudge group moved
  from the selection bar: `minus_button` (`chevron-right`, "−50 ms"),
  `snap_button` (`crosshair`), `plus_button` (`chevron-left`, "+50 ms") —
  the nudge buttons keep their text and get the chevrons that point the
  way the edge moves on the always-right-to-left timeline (so NOT mirrored
  under RTL: they are registered with `mirror=False`), then
  `show_ayah_button` in a lecture. The buttons keep their attribute names
  but live on `self.transport` (a `QWidget`); `selection_bar` keeps
  `label`, `minus_button`, `plus_button`, `snap_button` as properties that
  return the transport's buttons, so existing tests keep working.
- **Selection bar**: the word and its span only, in `theme.font("section")`
  for the Arabic word.
- **Keyboard**: unchanged (`Space`, `←` `→`, `[` `]`, `,` `.`, `Shift+,`
  `Shift+.`, `Ctrl+Z`, `Ctrl+Shift+Z`, `Ctrl+S`), plus `?` (and `Shift+/`)
  opening the shortcut sheet.

### 2.3 Toolbar and banner

- **Toolbar** order: Save, Undo, Redo, separator, Mark as reviewed, Remove
  selected, separator, stretch, Surah on the cards + combo (lecture),
  Episode…, Export subtitles…, Render (primary) [progress bar + Cancel
  while rendering], separator, `help_button` (`keyboard` icon, tooltip
  "Shortcuts (?)"). Separators are 1 px `border`-coloured frames 20 px tall.
- **Banner** (`Banner`, attribute `warnings`): a `Card` with a leading icon
  (by the strongest kind present: `attention` → `circle-alert` amber,
  `success` → `film` accent, `info` → `info` accent), one `QLabel` per
  line (rich text, links as today), an actions area at the trailing end
  and a dismiss `x` tool button. Empty, it collapses to a 4 px rule of
  reserved height, so showing or hiding it never moves the body. Its
  content is what `WarningsStrip` showed, kept by the same methods:
  notices, look notices, the surah notice, the episode notice, the
  coverage result. Gaps: the first line says "N stretches of speech have no
  word ▸"; clicking it toggles the per-gap lines (first five + "…and N
  more"); Jump links seek as today. `set_render_done(outcome)` adds a
  `success` line "Rendered {name} · {duration}" (the recording's measured
  length, `session.duration`, as `mm:ss`; omitted while unmeasured) with **Play** (`QDesktopServices.openUrl` on the file)
  and **Show in folder** actions, plus the episode-written line when there
  is one; a later `set_render_done`, a new render start, or the dismiss
  cross clears it. Dismiss clears only the render line and the plain
  notices; coverage and look/surah/episode notices come back on the next
  check, as they are state, not news.
- **Render outcomes**: success → the banner (no dialog); the window's
  `_announce_render` becomes the banner call, and `render_finished_text`
  stays for the CLI-side messages; failed / cancelled / episode-failed →
  dialogs as today (`_say_render`).

### 2.4 Shortcut sheet

`ShortcutSheet`, a non-modal `QDialog` owned by the window (one instance,
`show()`/`raise_()`), title "Shortcuts", three groups in a two-column grid
(keys in the clock font, action text): Playback (Space, ← →, drag the
waveform), Editing ([ ], `,` `.`, Shift+, Shift+., Shift-drag ripple,
Ctrl-drag detach, Ctrl+Z, Ctrl+Shift+Z, double-click an Ayah cell),
File (Ctrl+S, ?). Opened by `?`, the toolbar's `help_button`, and a
link in the status bar's hint. Key names come from the same `t(...)`
strings as the tooltips.

### 2.5 Segment table

- Rows 32 px; alternating row colours (`setAlternatingRowColors(True)`,
  the palette's `AlternateBase`).
- The Ayah cell gets a decoration icon: `book-open` for a card, `mic` for a
  caption; the ✎ text mark for a hand-placed card stays in the text.
- The playhead row is marked by a 3 px accent rule on the leading edge of
  its first cell (an item delegate paints it) instead of a full tint; the
  selection highlight is unchanged.
- The Retimed-words column shows the number only when it is above zero,
  in the secondary colour; zero is blank.
- Columns, editing, the context menu, `highlight_at`, `segment_at`,
  `remove_selected`, `show_card` are unchanged in behaviour.

### 2.6 Preview

- `fit_button` / `actual_button` under the preview: Fit (default) renders
  at the largest size of the preset's shape that fits the left column's
  width and the available height; Actual size renders at the preset's
  preview size (270×480 / 480×270) inside a scroll area when the column is
  shorter. The choice is remembered in `Prefs.preview_fit` (bool, default
  True).
- Double-click on the preview opens `FullFrameView`: a frameless top-level
  window sized to the screen's available geometry, the frame rendered once
  at the largest size of the preset's shape that fits, black around it;
  Escape, a click, or the window losing focus closes it. The playhead time
  is the one the preview showed.

## 3. Modules

| Module | What |
|---|---|
| `gui/review/time_ruler.py` | `TimeRuler(viewport, parent)`: `set_playhead(t)`, `seek_requested(float)`, `tick_step(span_s, width_px, label_px) -> float` (pure, tested), paints via `viewport.x_for`. |
| `gui/review/banner.py` | `Banner(parent)` with the `WarningsStrip` methods plus `set_render_done(outcome)`, `clear_render()`, `dismissed`, `jump_requested`, `play_requested(Path)`, `reveal_requested(Path)`; `lines() -> list[str]` for tests. `warnings_strip.py` is deleted; its tests move. |
| `gui/review/shortcut_sheet.py` | `ShortcutSheet(parent)`, `BINDINGS` (group, keys, i18n key) as the single source for the sheet and the status bar hint. |
| `gui/review/transport.py` | `Transport(player_rates, parent)`: the row's buttons and the clock; signals `play_toggled`, `step_requested(int)`, `rate_changed(float)`, `nudge_requested(float)`, `snap_requested`, `show_ayah_requested`; `set_playing(bool)`, `set_time(seconds)`, `set_rate(float)`, `set_selection(bool)`. |
| `gui/review/frame_view.py` | `FrameView.set_fit(bool)`, `fit` property, `full_frame_requested` signal on double-click; `FullFrameView(session, t, parent)`. |
| `gui/review/waveform_view.py`, `word_strip.py` | paint changes only; `WordStrip.HANDLE_PX = 6`. |
| `gui/review/segment_list.py` | icons, alternating rows, the rule delegate, blank zero. |
| `gui/review/window.py` | the two-column `_build`, the toolbar groups, wiring the transport and the banner, `_announce_render` → banner, `?` binding, `help_button`, the sheet. `selection_bar` becomes a thin `SelectionBar` (label only) with the three button properties delegating to the transport. |
| `gui/prefs.py` | `preview_fit: bool`. |
| `gui/icons.py` | `set_icon(..., mirror=True)`: `mirror=False` keeps a directional icon as drawn under RTL (the nudge chevrons); new names `zoom-in`, `zoom-out`, `crosshair`, `maximize-2`, `keyboard`, `info` (Lucide 1.56.0; `info` exists there). |
| `tools/screenshots.py` | adds `shortcuts-<lang>-<theme>.png` and `review-full-frame-<lang>-<theme>.png`. |

Strings (both languages): `review.span` ("{seconds} s shown" / minutes
variant), `review.zoom_in`, `review.zoom_out`, `review.fit`,
`review.actual_size`, `review.prev_word`, `review.next_word`,
`review.rate_label`, `review.help`, `review.shortcuts.title`,
`review.shortcuts.playback`, `review.shortcuts.editing`,
`review.shortcuts.file`, one `review.key.*` per binding (12),
`review.hint` (the short status line), `review.gaps_toggle` (plural),
`render.done_banner` ("Rendered {name} · {duration}"), `render.play`,
`banner.dismiss`. `review.shortcuts` (the long line) is removed.

## 4. Data flow

```
Viewport.changed ─▶ TimeRuler.update, WaveformView.update, WordStrip.update, zoom readout
ReviewWindow._show_time(t) ─▶ ruler/waveform/strip.set_playhead, transport.set_time, frame_view.show_at, table.highlight_at
Transport.step_requested ─▶ window._step; nudge_requested ─▶ window._nudge; rate_changed ─▶ player.set_rate
Banner.jump_requested ─▶ window.seek; play_requested ─▶ QDesktopServices.openUrl; reveal_requested ─▶ files.show_in_folder
render finished ─▶ window._announce_render(outcome) ─▶ warnings.set_render_done(outcome) [+ dialogs for episode_error / failed / cancelled as today]
render started ─▶ warnings.clear_render()
`?` / help_button / hint link ─▶ window.show_shortcuts() ─▶ ShortcutSheet.show()
FrameView.full_frame_requested ─▶ window._show_full_frame() ─▶ FullFrameView
fit_button/actual_button ─▶ frame_view.set_fit(bool) ─▶ prefs.preview_fit
```

## 5. Error handling

- A video the banner's Play cannot open (no player registered) is reported
  as a notice line on the banner.
- An unmeasured recording length shows the line without the " · mm:ss".
- The full-frame window on a screen smaller than the preset keeps the
  aspect and fits; a renderer error shows the error text in the window.
- `tick_step` with a zero or negative span or width returns the largest step
  and draws no labels rather than dividing by zero.
- The ruler's hover tooltip is suppressed while a drag seeks.

## 6. Testing

- `tests/test_time_ruler.py`: `tick_step` picks 1 s at 10 s / 1200 px, 10 s at
  120 s / 600 px, 60 s at an hour / 600 px; labels never closer than their
  measured width; the first label sits at the right under RTL (always, since
  the timeline is RTL in both languages); click seeks; hover tooltip text.
- `tests/test_banner.py`: kinds and the icon; lines from each setter;
  `set_render_done` adds the line and two actions and `clear_render` removes
  it; dismiss clears news but not state; the empty height is 4 px; gap lines
  collapse and expand; Jump emits the start.
- `tests/test_shortcut_sheet.py`: every binding in `window._keys` appears in
  `BINDINGS`; the sheet lists them in both languages; `?` shows it once and
  raises it the second time.
- `tests/test_transport.py`: buttons' icons and signals; rate segments
  exclusive; `set_playing` swaps the icon; nudge buttons not mirrored under
  RTL (pixmaps equal across layouts).
- `tests/test_review_window.py`: the two-column layout (`look_scroll` under
  `frame_view` in the left column; the table at the bottom of the right);
  a lecture at 1280×800 shows ≥ 8 table rows; `_announce_render` puts the
  line on the banner and opens no dialog (tests that monkeypatched
  `_announce_render` adapt to read `warnings.lines()`); failure still opens
  the dialog; the fit toggle round-trips through prefs; the full-frame
  window opens on double-click and closes on Escape; the existing 1280 px
  fit tests stay green.
- `tests/test_review_widgets.py`: strip paint (selected fill, playhead
  outline), waveform placeholder colour, table icons and the blank zero,
  the rule delegate marks the playhead row.
- `tests/test_rtl.py`: ruler labels, transport order, banner mirroring.
- `tools/screenshots.py` gains the two images; the phase review attaches them.

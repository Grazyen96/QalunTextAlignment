# Phase A: the presentation layer — design

Date: 2026-10-13 · Status: approved in conversation, awaiting written-spec review

## 1. Purpose

The UX audit of 2026-10-13 (`docs/ux-audit-2026-10-13.md`) found the app's
workflows sound and its appearance unfinished: raw Qt Fusion, one font size,
no icons, no app icon, no spacing scale, no theme, and no visual emphasis on
the action each screen exists for. Phase A adds the missing layer without
moving anything: a theme with its own light and dark palettes, a type and
spacing scale, bundled icons, an app icon, and four small composite widgets,
applied in place to the existing screens.

Success means:

- Every window, dialog and row reads as one product in light and in dark,
  on Linux, Windows and macOS.
- Start, Render and each dialog's confirming button are the one obviously
  primary control on their screen.
- Every toolbar and row button has an icon; every window has the app icon.
- The person can choose System, Light or Dark, and System follows the
  desktop live.
- Nothing moves: no layout change, no new panel, no behaviour change, and
  every widget attribute the tests reach (`win.new_job.start_button`,
  `review.play_button`, …) keeps its name and class.
- Every text colour measures at least 4.5:1 on its surface in both themes
  and every control colour at least 3:1, by test.

Decisions taken in the brainstorm (owner's answers):

| Question | Decision |
|---|---|
| Accent direction | **Ink blue** for primary actions, selection and links; **gold** only as a detail (app icon, swatch ring, section rules). Amber stays "needs attention", red stays the playhead. |
| Theme control | **System / Light / Dark** preference with the app's own palettes; System follows the OS colour scheme live. |
| Icons | **Lucide** SVGs bundled and tinted from the palette at load time. |
| App icon | **Drafted in this phase** as an SVG master with generated PNG, ICO and ICNS. |
| Reach | **Foundation applied in place**: primary buttons and icons on existing buttons, headings on the type scale; no layout moves. |

Out of scope (later phases): the home header bar and Settings dialog (B),
job-row cards and the empty state (B), the review window's two-column
layout, time ruler, iconed transport and `Banner` (C), the Look panel and
Episode dialog re-flow (D), animation and the Arabic UI font (E).

## 2. What the user sees

- The same windows, with a warm off-white or a warm near-black surface
  instead of Fusion's grey, panels on white or dark panel colour, 6 px
  radius on buttons and fields, 8 px on lists and tables.
- **Start**, **Render with corrections**, **Export** (export dialog) and
  **OK** (ayah picker, episode dialog) filled in the accent with white
  text; every other button outlined, with an accent border on hover.
- Icons, 16 px in rows and 20 px in toolbars, on: Refresh, Open, Show in
  folder, Remove from list, Choose, Recitation (mic) and Lecture (book) in
  the mode toggle, Save, Undo, Redo, Mark as reviewed, Remove selected,
  Export subtitles, Episode, Render, Play / Pause, Choose image, Use for new videos, Reset, and the two disclosure toggles
  (More options, Customise).
- "Your jobs", "New job" and "Look" in the section font; the review clock
  in tabular digits.
- A **Theme** combo (System, Light, Dark) in the home footer beside
  Language. Switching repaints every open window at once.
- The app icon in the title bar, the task bar or dock, and the packaged
  executable and bundle.

In Arabic every icon that points along the reading direction (chevrons,
disclosure arrows) is mirrored; Undo and Redo are not, since their arrows
mean time, not reading order. Nothing else changes for RTL: the palette and
the stylesheet carry no direction.

## 3. Modules

### 3.1 `gui/theme.py`

```python
@dataclass(frozen=True, slots=True)
class Tokens:
    name: str                 # "light" | "dark"
    window: str               # surface.window
    panel: str                # surface.panel (Base)
    raised: str               # surface.raised (cards, rows)
    border: str
    text: str                 # text.primary
    secondary: str            # text.secondary, PlaceholderText, disabled
    accent: str
    on_accent: str
    gold: str

LIGHT = Tokens("light", "#F4F3F0", "#FFFFFF", "#FFFFFF", "#DDD9D1",
               "#1C1B1A", "#5F5B55", "#2F5D8A", "#FFFFFF", "#B8891C")
DARK  = Tokens("dark",  "#1C1B1A", "#262523", "#2E2C29", "#3A3835",
               "#ECE9E3", "#A8A49C", "#7FB0E6", "#101418", "#D9B45B")
```

The hex values are the audit's; the tests in §6 are what fix them, and an
implementer who finds one short of its ratio adjusts the value, not the
test.

- `palette(tokens) -> QPalette`: Window, WindowText, Base, AlternateBase,
  Text, Button (panel in light, a step above panel in dark), ButtonText,
  PlaceholderText, Link, Highlight, HighlightedText, ToolTipBase,
  ToolTipText, and Mid / Dark / Light for Fusion's frames; the Disabled
  group's Text, ButtonText and WindowText set to `secondary`.
- `stylesheet(tokens) -> str`: generated from the tokens (§3.2).
- `apply_theme(app, mode)`, `mode in ("system", "light", "dark")`: forces
  the `Fusion` style once, resolves `system` through
  `app.styleHints().colorScheme()` (`Unknown` counts as light), sets the
  palette and the stylesheet, and stores the resolved `Tokens` on the
  application property `"qalun.tokens"` so `current_tokens()` answers
  without a global. In `system` mode it connects (once) to
  `colorSchemeChanged` and re-applies on change; the other modes
  disconnect it.
- `font(role) -> QFont`, `role in ("title", "section", "body", "secondary",
  "clock")`: title 15 pt weight 600, section 12 pt weight 600, body the
  application font, secondary one point smaller, clock = body with
  `QFont.Feature` `tnum` enabled (Qt 6.7+; a guarded no-op below).
- Spacing constants `SP_4, SP_8, SP_12, SP_16, SP_24, SP_32`.
- `is_light(palette)`, `warning_color`, `playhead_color` stay in
  `gui/colors.py`, unchanged in signature; their shades are re-measured
  against the new surfaces by `tests/test_colors.py` and adjusted if a
  ratio drops.

### 3.2 The stylesheet

Palette first. Qt draws `QComboBox`, `QSpinBox`, `QSlider`, `QScrollBar`,
`QCheckBox` and `QRadioButton` from the palette, and a stylesheet rule on
any of them replaces Fusion's sub-control drawing (the broken combo arrows
in the brainstorm renders). The generated sheet therefore names only:

| Selector | Rule |
|---|---|
| `QPushButton`, `QToolButton` | 1 px `border` border, 6 px radius, 5 px 14 px padding, `panel` background; `:hover` border `accent`; `:pressed` background `border`; `:disabled` text `secondary`; `:focus` 2 px `accent` outline. |
| `QPushButton[primary="true"]` | `accent` background, `on_accent` text, no border, weight 600, 7 px 22 px padding; `:hover` 8 % darker (light) or lighter (dark); `:disabled` background `border`, text `secondary`. |
| `QFrame#dropZone` | 2 px dashed `border`, 10 px radius, `panel` background; `[dragOver="true"]` solid `accent` border (keeps today's property). |
| `QListWidget`, `QTableWidget`, `QScrollArea` | 1 px `border` border, 8 px radius, `panel` background. |
| `QHeaderView::section` | `window` background, no border but a 1 px bottom `border`, 6 px padding, weight 600. |
| `QProgressBar` | no border, 3 px radius, `border` background; `::chunk` `accent`, 3 px radius. |
| `QStatusBar`, `QToolTip` | `window` / `panel` background, `text` colour, 1 px `border` border on the tip. |

The sheet is built by string formatting from one `Tokens`, so dark and RTL
need no second sheet. The two stylesheets that exist today
(`new_job._TOGGLE_STYLE`, the drop-zone and "Choose…" rules) are removed
and their effect expressed by the sheet above: the mode toggle becomes two
`QPushButton`s with `checkable` icons whose `:checked` rule is
`accent` / `on_accent`; "Choose…" becomes an outlined button with the
`folder-open` icon.

### 3.3 `gui/icons.py`

- Files: `src/qurantext/assets/icons/<name>.svg`, Lucide's SVGs unchanged
  except that each keeps `stroke="currentColor"`; `LICENSE` (ISC) beside
  them. The set (31, Lucide's names at tag 1.56.0): `play pause skip-back
  skip-forward undo-2 redo-2 save circle-check trash download film sparkles
  palette image sun moon monitor refresh-cw folder-open folder x
  chevron-right chevron-down chevron-left mic book-open pencil link qr-code
  settings circle-question-mark`.
- `icon(name, role="text") -> QIcon`, `role in ("text", "accent",
  "on_accent", "secondary")`: renders through `QSvgRenderer` at 16, 20 and
  24 px, at device pixel ratio 1 and 2, with `currentColor` replaced by the
  role's colour from `current_tokens()`; the Disabled mode gets
  `secondary`. Cached by `(name, role, tokens.name)`. A name not in the set
  raises `KeyError` at call time.
- `mirrored(name)`: the names that flip under RTL (`chevron-right`,
  `chevron-left`, `skip-back`, `skip-forward`); `icon()` swaps them when
  `QGuiApplication.isRightToLeft()`.
- `refresh_icons(window)`: every window that sets icons registers its
  `(widget, name, role)` triples through `set_icon(widget, name, role)`,
  which also stores them on the window; `apply_theme` calls
  `refresh_icons` on every top-level widget, so a switch re-tints.

### 3.4 `gui/widgets.py`

- `make_primary(button)`: sets `primary=true`, unpolishes and polishes, sets
  `setDefault(True)` when the button is in a dialog. Plain `QPushButton`s
  stay plain, so every test that reaches `start_button` or `render_button`
  keeps working.
- `SectionHeader(QLabel)`: the `section` font, `WindowText` role; takes the
  text and an optional trailing widget (Refresh beside "Your jobs").
- `Card(QFrame)`: `raised` background, 1 px `border` border, 10 px radius,
  16 px contents margins; a plain container for phase B's rows and the
  Episode strip. In phase A it is used only by the drop zone.
- `StatusChip(QWidget)`: an icon and a text in a pill, `kind in
  ("attention", "accent", "neutral")`, 22 px tall, 8 px side padding;
  ships for phase B, used nowhere in A.

### 3.5 Prefs and the footer

`Prefs.theme` (`"system"` default; any other string reads as `"system"`).
`MainWindow._build` adds `theme_combo` before `language_combo` in the
footer, with the key `home.theme` and items `home.theme.system`,
`home.theme.light`, `home.theme.dark` in both languages; `activated`
writes the pref and calls `apply_theme`. The combo is never disabled: a
theme switch loses nothing, unlike a language switch.

### 3.6 The app icon

- `src/qurantext/assets/icon/qalun.svg`: a 1024-unit square, ink
  (`#1C1B1A`) with a 22 % corner radius, a gold (`#D9B45B`) ayah-end
  roundel (two concentric rings and a dot) centred at 56 % of the width.
- `tools/make_app_icon.py`: renders 16, 24, 32, 48, 64, 128, 256, 512 and
  1024 px PNGs through `QSvgRenderer` (offscreen), writes `qalun.ico`
  (Pillow, the sizes up to 256) and `qalun.icns` (Pillow). Outputs are
  committed beside the SVG so a build needs no step.
- `app.main` calls `app.setWindowIcon(QIcon(str(bundled_asset("icon/qalun.png"))))`
  after `_name_the_app()`: every window inherits it.
- `packaging/qalun.spec`: `icon=` on `EXE` (the `.ico`) and on `BUNDLE`
  (the `.icns`); the `assets` folder is already in `datas`.

### 3.7 Where it is applied in A

| Place | Change |
|---|---|
| `app.main` | `apply_theme(app, prefs.theme)` after `apply_language`; the window icon. |
| `main_window` | Theme combo; `refresh_icons` wiring. |
| `home/job_list` | `SectionHeader("Your jobs")` with Refresh (icon `refresh-cw`) as its trailing widget; icons on Open (`folder-open`), Show in folder (`folder`), Remove from list (`x`). Row text and `_detail_text` unchanged. |
| `home/new_job` | `SectionHeader("New job")`; the drop zone becomes a `Card` with the dashed rule via its object name; "Choose…" an outlined button with `folder-open`; mode toggle icons `mic` / `book-open`; `make_primary(start_button)`; More options toggle icon `chevron-right` / `chevron-down`. |
| `review/window` | Toolbar icons (`save`, `undo-2`, `redo-2`, `circle-check`, `trash`, `download`, `sparkles`, `film`); `make_primary(render_button)`; `play` / `pause` swapped in `_on_playing_changed`; clock font on `time_label`. |
| `review/selection_bar` | No icons: the nudge buttons' labels already say the direction, and a chevron there would have to follow the always-right-to-left timeline rather than the reading direction. |
| `review/look_panel` | `SectionHeader("Look")`; icons `image`, `circle-check`, `refresh-cw`; Customise toggle chevrons. |
| `review/export_dialog`, `ayah_picker`, `episode_dialog` | `make_primary` on Export and the two OK buttons. |
| `tools/screenshots.py` | The offscreen screenshot script from the audit, made a repo tool: every window and dialog, light and dark, English and Arabic, into a folder given on the command line. |

Left as it is in A, on purpose: every margin and spacing outside the new
composites, the job row's layout, the warnings strip, the segment table's
columns, the status-bar hint, and every message box.

## 4. Data flow

```
Prefs.theme ──▶ apply_theme(app, mode)
                  ├─ resolve system → Tokens
                  ├─ app.setStyle("Fusion") (once)
                  ├─ app.setPalette(palette(tokens))
                  ├─ app.setStyleSheet(stylesheet(tokens))
                  ├─ app.setProperty("qalun.tokens", tokens)
                  └─ for each top-level: refresh_icons(window)
widgets ── PaletteChange ──▶ existing changeEvent repaints (rows, strip, waveform)
icons   ── icon(name, role) ──▶ reads current_tokens(); cached per theme name
```

## 5. Error handling

- A missing or unreadable SVG raises at the first `icon()` call for it; the
  tests cover every name, so a packaged build cannot lack one silently. The
  doctor gains one line, "Interface icons", that counts the files.
- A Qt without `colorSchemeChanged` (older than 6.5) resolves `system` as
  light once and never listens; the combo still offers Light and Dark.
- `QFont.Feature` missing (Qt < 6.7): the clock font is the body font.
- A `Prefs.theme` value from a newer build reads as `system`.
- The PyInstaller `icon=` paths are checked by the packaging test so a
  renamed file fails CI, not the release.

## 6. Testing

- `tests/test_theme.py`: for `LIGHT` and `DARK`, `text` on `window`,
  `panel` and `raised` ≥ 4.5; `secondary` on the same ≥ 4.5; `on_accent`
  on `accent` ≥ 4.5; `accent` on `window` and `panel` ≥ 3.0; `border` on
  `window` ≥ 1.5 (visible, not text); `palette()` maps every role named in
  §3.1; `stylesheet()` names none of the palette-drawn widgets (a literal
  check for `QComboBox`, `QSpinBox`, `QSlider`, `QScrollBar`); `apply_theme`
  with `system` follows a monkeypatched `colorScheme()` and its signal;
  `font("clock")` differs from `font("body")` only when the feature is
  available.
- `tests/test_colors.py`: `LIGHT` / `DARK` fixtures take the new `window`
  and `panel` values; the existing ratio tests keep their thresholds.
- `tests/test_icons.py`: every name in the set renders a non-empty pixmap
  at each size; tinting with `accent` yields pixels of that colour;
  Disabled differs from Normal; an unknown name raises `KeyError`; a
  mirrored name under RTL is the horizontal flip of its LTR pixmap; the
  cache returns the same `QIcon` for the same key and a new one after
  `apply_theme` to the other theme.
- `tests/test_widgets.py`: `make_primary` sets the property and keeps the
  class; `SectionHeader` uses the section font; `Card` margins;
  `StatusChip` text, icon and kind.
- `tests/test_app_icon.py`: the SVG and every generated size exist, the
  ICO holds 256 px, the ICNS opens in Pillow; `app.main`'s window icon is
  not null (offscreen).
- `tests/test_prefs.py`: `theme` round trip and the unknown-value fallback.
- `tests/test_home_panels.py`, `tests/test_review_window.py`,
  `tests/test_review_widgets.py`, `tests/test_rtl.py`: run unchanged; one
  new case each that the primary button carries the property and that
  the mirrored chevrons flip under Arabic.
- `tests/test_packaging_spec.py`: the `icon=` paths exist.
- Phase review: `tools/screenshots.py` run once in light and once in dark,
  the images attached to the branch review.

## 7. Licensing

Lucide is ISC-licensed (compatible with GPL-3.0-only). `THIRD_PARTY_NOTICES.md`
gains a "Lucide icons" section naming the version, the copyright line, the
licence file path inside the bundle (`_internal/qurantext/assets/icons/LICENSE`)
and in the source (`packaging/licenses/Lucide-LICENSE.txt`), in the form the
Amiri section uses. The app icon is the project's own work under the
project licence.

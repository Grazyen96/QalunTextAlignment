# Phase E: polish — design

Date: 2026-10-14 · Status: approved in conversation, awaiting written-spec review

## 1. Purpose

Phases A to D (merged) gave the app its presentation layer and relaid out
every screen. What is left is the audit's last row (`docs/ux-audit-2026-10-13.md`
§5 E): the disclosures flip open with no transition; the focus ring paints on
every focus, clicks and dialog openings included, which phase A noted as loud;
cards have no hover or focus state; in the dark theme Fusion draws checkbox,
radio and field outlines at about 1.1:1 (phase A's I7); the Arabic interface's
last-resort font is the Quran face; and the colours added since phase A were
never checked together for contrast. Phases B to D also left a list of small
code-only minors.

Success means:

- More options and Customise open and close in 150 ms with an ease-out, and
  at once when "Animate panels" is off or Qt's style says not to animate.
- The 2 px accent focus ring paints only after Tab, Backtab or a shortcut
  moved focus; a click or a dialog's initial focus paints none.
- Cards show an accent border on hover and the ring on keyboard focus.
- In both themes a checkbox or radio indicator has a visible outline and an
  unfocused field a visible frame, without the stylesheet naming either.
- A machine with no Arabic font shows the interface in Noto Sans Arabic.
- Every colour added since phase A passes its ratio on every surface it sits
  on, in both themes, under one test.
- The deferred minors from B, C and D are closed.
- Every widget attribute the tests reach keeps its name.

## 2. What the user sees

### 2.1 Motion

A disclosure (`more_group` under More options, `customise_box` under
Customise) opens by growing from 0 to its full height over 150 ms with
`QEasingCurve.Type.OutCubic`, and closes the same way in reverse. While it
animates its maximum height is driven; when it ends the limit is released
(`QWIDGETSIZE_MAX`) so the panel lays out as before. A toggle during an
animation restarts it from the current height. The chevron swaps at the
start, as now.

Animation runs only when both hold: the General setting "Animate panels"
(`Prefs.animate_panels`, default True, a `QCheckBox` under Theme in the
Settings dialog's General tab, key `settings.animate_panels` / Arabic
«حرّك اللوحات») is on, and `app.style().styleHint(QStyle.StyleHint.SH_Widget_Animate)`
is non-zero. Otherwise the panel shows or hides at once, exactly as today.
The setting takes effect on the next toggle; nothing restarts.

### 2.2 Focus

Keyboard focus is marked, not every focus. An application-wide event filter
sets the dynamic property `kbdfocus` to True on a widget whose `FocusIn`
carries the reason `TabFocusReason`, `BacktabFocusReason` or
`ShortcutFocusReason`, and to False on its `FocusOut`; each change
re-polishes the widget. Every `:focus` rule in the stylesheet becomes the
same rule with `[kbdfocus="true"]` in its place (buttons, quiet buttons,
rows, the primary button, the checked swatch). A widget focused by a click,
by `setFocus()` at dialog open, or by the window activating shows no ring.
Fusion's own focus frame on line edits, combos and spin boxes is unchanged.

### 2.3 Hover and focus on cards

`QFrame[card="true"]:hover` draws the border in the accent, as buttons do,
and `QFrame[card="true"][kbdfocus="true"]` draws the 2 px accent ring. The
mode cards (`_ModeCard`) and the Episode cards (`PartCard`) set
`WA_Hover`; the plain job cards and the Settings cards do not hover (they
are not clickable). The selected Episode card keeps its 2 px accent border
whether hovered or not.

### 2.4 Dark outlines

A `QalunStyle(QProxyStyle)` wraps Fusion. `apply_theme` sets it once (in
place of the bare Fusion, same guard property). It overrides
`drawPrimitive` for `PE_IndicatorCheckBox` and `PE_IndicatorRadioButton`:
after Fusion's drawing it strokes a 1 px outline in the palette's
`PlaceholderText` colour (the secondary token) following Fusion's shape (a
2 px-radius rounded rect for the box, a circle for the radio), for enabled
and disabled widgets alike. It overrides `drawPrimitive` for
`PE_FrameLineEdit` and `drawComplexControl` for `CC_ComboBox` and
`CC_SpinBox`: after Fusion's drawing, when the widget does not have focus,
it strokes a 1 px frame in the palette's `Mid` colour (the border token)
along the control's rounded outline; a focused control keeps Fusion's
highlight frame. The style reads the palette on each draw, so a theme switch
needs nothing. The stylesheet still never names those widgets.

### 2.5 Arabic interface font

Noto Sans Arabic Regular and Bold (SIL OFL 1.1) ship under
`src/qurantext/assets/fonts/` with `NotoSansArabic-OFL.txt` beside them,
fetched by `tools/fetch_fonts.py` from a pinned notofonts release (tag and
sha256 of each file recorded in `THIRD_PARTY_NOTICES.md`, the licence also
under `packaging/licenses/`). `language.ensure_arabic_font` registers both
files and substitutes "Noto Sans Arabic" for the application font's family
under the rule it has today: only when `arabic_ui_families()` is empty, and
never when fonts cannot be measured. The Quran face is no longer registered
for the interface; it keeps its place in the video. The doctor gains an
"Interface font" check beside "Bundled font" reporting both files and their
sizes, failing when either is missing.

### 2.6 Contrast pass

One theme test, parametrised over both themes, checks:

| Colour | Surfaces | Ratio |
|---|---|---|
| `gold` (the tile ring) | window, panel, raised, white (`#FFFFFF`, the palest preset tile) | ≥ 3.0 |
| `warning_color(palette)` | window, panel, raised | ≥ 4.5 |
| `playhead_color(palette)` | window, panel | ≥ 3.0 |
| `accent` (quiet buttons, chip accent) | raised, window | ≥ 4.5 |
| `secondary` (hex labels, chip neutral) | raised, window | ≥ 4.5 |
| `on_accent` | accent | ≥ 4.5 |

`LIGHT.gold` moves from `#B8891C` to the nearest deeper gold that clears
3.0 on white (about `#9A700A`; the plan computes it with the test's own
`contrast`). `DARK.gold` stays. The app icon SVG is a static asset and does
not change.

### 2.7 Leftovers closed

- C: `window.py`'s `_TIMELINE_ROOM` branch is made reachable or removed
  with its constant (the plan reads the code and decides); the ruler's
  label width is measured ×1.15 instead of a 0 px gap; the 2 px playhead is
  a filled rect; the overstated test docstring says what the test checks.
- D: the recitation card draws its picture through `thumbnail_image` at
  `fitted_size` so it is as sharp as the lecture's; the Export hint indent
  comes from `style().subElementRect(SE_CheckBoxContents, …)`; each colour
  row's accessible description is its hex; `_update_cards` keeps a
  per-path pixmap cache; the clip-name comment and the `clip_frames`
  docstring say what the code does.
- B/D: `StatusChip` icons and the Look panel's tile pixmaps are drawn at the
  widget's device pixel ratio.
- Tests: an autouse fixture in `tests/conftest.py` sets `QURANTEXT_CACHE_DIR`
  to a per-test temporary folder, so no test writes into the real cache;
  the Episode tests' own settings of it are then redundant and removed.

Out of scope, still the owner's: the Look panel below the fold at
1280×800, a link redirect under the owner's domain, the AZERTY `?` check,
native review of the Arabic strings, the Arabic percent sign.

## 3. Modules

| Module | What |
|---|---|
| `gui/disclosure.py` | `animations_enabled(prefs) -> bool` (setting and style hint); `reveal(widget, open_, *, animate: bool, duration_ms=150)`: animates `maximumHeight` or sets visibility at once; keeps one `QPropertyAnimation` per widget as a property so a second call restarts it. |
| `gui/focus.py` | `KeyboardFocusMarker(QObject)`: the event filter; `install(app)` installs it once (guarded by an app property). `KBDFOCUS = "kbdfocus"`. |
| `gui/style.py` | `QalunStyle(QProxyStyle)` as §2.4. |
| `gui/theme.py` | `apply_theme` sets `QalunStyle(QStyleFactory.create("Fusion"))` under the existing guard and calls `focus.install(app)`; `:focus` → `[kbdfocus="true"]`; the card hover and focus rules; `LIGHT.gold` moved. |
| `gui/prefs.py` | `animate_panels: bool` (default True). |
| `gui/home/settings_dialog.py` | the General tab's checkbox `animate_box`, writing the pref directly. |
| `gui/home/new_job.py`, `gui/review/look_panel.py` | call `disclosure.reveal` from their toggles with `animate=animations_enabled(prefs)`. |
| `gui/home/job_list.py`, `gui/review/episode_cards.py` | `WA_Hover` on the clickable cards. |
| `gui/language.py` | registers the two Noto files; `NOTO_FONT_PATHS` in `config/paths.py`. |
| `config/preflight.py` | `_interface_font()` check. |
| `tools/fetch_fonts.py` | downloads the pinned release files and prints their sha256. |
| `THIRD_PARTY_NOTICES.md`, `packaging/licenses/NotoSansArabic-OFL.txt`, `README.md` (fonts line), `docs/release-checklist.md` (the new Arabic string; the dark-theme images to look at). |
| Leftovers | `gui/review/window.py`, `gui/review/time_ruler.py`, `gui/review/waveform_view.py` or wherever the playhead is drawn, `gui/review/episode_dialog.py`, `gui/review/export_dialog.py`, `gui/review/look_panel.py`, `gui/widgets.py`, `jobs/clip_frames.py`, `tests/conftest.py`. |

Strings (both languages): `settings.animate_panels`; the doctor's
"Interface font" label if the doctor's labels are translated (they are
English-only today; keep them so).

## 4. Data flow

```
toggle (More options / Customise) ─▶ disclosure.reveal(widget, open_, animate=animations_enabled(prefs))
    animate ─▶ QPropertyAnimation(maximumHeight 0↔sizeHint) 150 ms OutCubic ─▶ finished: maximumHeight = QWIDGETSIZE_MAX / hide
    not     ─▶ widget.setVisible(open_)
apply_theme(app, mode) ─▶ QalunStyle set once ─▶ focus.install(app) once ─▶ palette + sheet as today
FocusIn(reason ∈ Tab/Backtab/Shortcut) ─▶ widget.kbdfocus = True ─▶ repolish ─▶ sheet's [kbdfocus] rules
FocusOut ─▶ kbdfocus = False ─▶ repolish
apply_language ─▶ ensure_arabic_font ─▶ (no Arabic UI family) ─▶ addApplicationFont(Noto Regular, Bold) ─▶ insertSubstitution(app family → "Noto Sans Arabic")
QalunStyle.drawPrimitive / drawComplexControl ─▶ Fusion ─▶ outline/frame in palette roles
```

## 5. Error handling

- A disclosure whose widget is destroyed mid-animation: the animation is
  parented to the widget and dies with it.
- A hidden parent while animating: the animation finishes on a hidden
  widget; the next toggle starts from the real state (`isVisible`).
- A Noto file missing or unreadable: `ensure_arabic_font` returns None as
  today for a missing font, registers whichever file loaded, and the doctor
  says which is missing.
- `QStyleFactory.create("Fusion")` returning None (no Fusion built in): the
  proxy wraps the application's current style instead; a test does not
  cover this, it is a comment.
- The focus filter sees a `FocusIn` on a non-widget object (QWindow,
  QQuickItem): ignored.

## 6. Testing

- `tests/test_disclosure.py`: `animate=False` shows and hides at once;
  `animate=True` leaves the widget visible with `maximumHeight` below its
  size hint right after the call and at `QWIDGETSIZE_MAX` after the
  animation finished (drive the animation with `animation.setCurrentTime`
  or spin with `tests.qt_helpers.wait_for`); a second call mid-animation
  reverses; `animations_enabled` is False when the pref is off and when the
  style hint is 0 (monkeypatched).
- `tests/test_focus.py`: a Tab `FocusIn` sets `kbdfocus` True, a mouse
  `FocusIn` does not, `FocusOut` clears it; `install` is idempotent.
- `tests/test_style.py`: `app.style()` is a `QalunStyle` over Fusion after
  `apply_theme`; a dark-theme checkbox grab has the secondary colour on its
  indicator's edge and a light one too; an unfocused line edit grab has the
  border colour on its frame; a focused one has the accent.
- `tests/test_theme.py`: the contrast table of §2.6; the `[kbdfocus="true"]`
  rules exist and no `:focus` rule remains; the card hover/focus rules.
- `tests/test_language.py` (or where `ensure_arabic_font` is tested): with
  `arabic_ui_families` monkeypatched empty, the registered family is "Noto
  Sans Arabic"; with a family present nothing is registered.
- `tests/test_preflight.py`: the Interface font check OK with both files,
  failing with one renamed (monkeypatched paths).
- `tests/test_settings_dialog.py`: the checkbox round-trips the pref.
- `tests/test_home_panels.py` / `tests/test_review_widgets.py`: the toggles
  still show and hide (animation off under offscreen tests through the
  style hint or the pref set False in the fixture).
- One test per leftover: `_TIMELINE_ROOM` (whichever way it goes), the ruler
  step with the ×1.15 width, the playhead rect, the sharp recitation picture
  (size 176 long side), the Export indent equals the style's rect, the
  accessible description, the pixmap cache hit, the conftest fixture (the
  real cache path is never written: assert `QURANTEXT_CACHE_DIR` is set in a
  test).
- `tools/screenshots.py` runs unchanged; the phase review looks at the
  dark-theme Settings and review images for the outlines.

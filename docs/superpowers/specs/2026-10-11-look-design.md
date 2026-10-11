# Look: colour palettes and backgrounds — design

Date: 2026-10-11 · Status: approved in conversation, awaiting written-spec review

## 1. Purpose

Every Qalun video looks the same today: a near-black frame, a translucent grey card, white text, a gold
highlight and a cyan caption word. The user — a lecturer or reciter publishing videos, usually with a
consistent channel look — wants to choose the colours and the background, including their own image,
and to vary one video when needed.

Success means:

- The user can change a video's look in the review window and see it in the live preview immediately.
- The exported video looks exactly like the preview.
- A video with no look chosen renders byte-identical to today.
- Text stays readable: the user is warned before choosing an unreadable combination, and a photo
  background can be dimmed and blurred.
- Exports never fail because of the look.

Decisions taken in the brainstorm (owner's answers):

| Question | Decision |
|---|---|
| What a background covers | The **whole frame**; the card stays a translucent panel on top |
| Where it is chosen, how long it sticks | **Review window**, saved **per video**, plus **"Use for new videos"** as the default |
| Colour control | **~6 presets + Customise** (individual colour pickers) with a contrast warning |
| Built-in backgrounds | **Drawn in code** (solid, gradient, geometric patterns); no bundled photos |

Out of scope: video or animated backgrounds; font family and text sizes; a look per card; intro and
outro (the next feature); styling of the subtitle sidecar files (SRT/ASS, which players style
themselves); the separate ASS render mode, which keeps its own white-text style.

## 2. What the user sees

A **Look** panel in the review window, beside the frame preview. Every change redraws the preview.

- **Palette** shows the presets as swatches: `night_gold` (today's look, the default), `emerald`,
  `sand`, `ink_on_paper` (light card, dark text), `ocean` and `rose`. Picking one sets every colour
  and the suggested background.
- **Customise** is folded away by default. It holds colour pickers for:
  - the ayah text, the highlighted word and the surah title;
  - the card colour, with an opacity slider (0–100 %);
  - the caption text and the caption's active word.

  Once anything is customised, the palette reads "Custom (from <preset>)".
- **Contrast warning**, shown inline and never blocking. It appears when any text colour against the
  card colour has a WCAG contrast ratio below 4.5:1. The card colour used for the check is the card
  composited at its opacity over the background's average colour.
- **Background**:
  - built-ins: `solid`, `gradient` (two stops, vertical), and the patterns `pattern_stars` (eight-point
    star tiling), `pattern_lattice` (diagonal lattice) and `pattern_arches` (arch row). Patterns are
    drawn as faint lines over the solid colour. Each preset names its suggested background.
  - **Choose image…** accepts PNG, JPEG and WebP. The image is cover-fitted: scaled to fill the
    frame and centre-cropped, never stretched.
  - **Dim** (0–80 %, default 35 % for images, 0 for built-ins) lays black at that alpha over the
    background.
  - **Blur** (0–20, default 0) is a Gaussian blur whose radius is `value × frame_height / 1000` pixels,
    so it looks the same at every resolution.
- **Use for new videos** saves the current look as the user's default. **Reset** returns to
  `night_gold`.
- Problems appear in the review window's existing warnings strip: an unreadable image, or an image
  that has gone missing.

## 3. Architecture

### 3.1 `qurantext/core/looks.py` (new, no Qt)

- `Look`: a frozen dataclass with slots.
  - RGBA colours: `frame_bg`, `card`, `card_border`, `header_text`, `body_text`, `highlight_word`,
    `subtle`, `debug_text`, `placeholder_text`, `caption_bg`, `caption_text`, `caption_active`,
    `caption_upcoming`. These map one to one onto today's `COLOUR_*` constants.
  - `background: Background`.
  - `base_preset: str`.
- `Background`: a frozen dataclass.
  - `kind`: one of `solid | gradient | pattern_stars | pattern_lattice | pattern_arches | image`.
  - `colour`, `colour2` (for the gradient), `image: Path | None`, `dim: float`, `blur: float`.
- `PRESETS: dict[str, Look]` and `NIGHT_GOLD = PRESETS["night_gold"]`. `NIGHT_GOLD` equals today's
  constants exactly, with a `solid` background in `frame_bg`.
- `Look.to_dict(relative_to=...)` and `Look.from_dict(data, base_dir=..., fallback=NIGHT_GOLD)`:
  - colours are stored as `#RRGGBBAA` strings;
  - each field is validated on its own, and an invalid one falls back to the base preset's value;
  - unknown keys are preserved on round-trip;
  - an image path is stored relative to the project when possible, following the project's existing
    `_store_path` and `_resolve_path` rule.
- `contrast_ratio(fg, bg)` (WCAG 2.x) and `readability_warnings(look, background_mean) -> list[str]`,
  returning message keys rather than text.
- `look_from_project_style(style: dict, base_dir) -> Look`: an empty dict gives `NIGHT_GOLD`.

### 3.2 `qurantext/core/backgrounds.py` (new)

- `base_layer(look, width, height) -> PIL.Image (RGBA)`: the background (built-in or image, then
  blur, then dim) with the card panel and its border composited on top at the frame layout's card
  box. The card box is passed in from the caller's `_frame_layout` result.
- The cache key is what the layer draws: `(look.background, look.card, look.card_border,
  look.base_preset, width, height, card_box, radius)`. `base_preset` is there because it picks the
  fallback background. Text and caption colours are not in the key, so editing them is a cache hit.
  The image's file size and mtime are added to the key so a replaced file is noticed. The cache
  holds an LRU of 4 entries, which bounds memory at 4 × w × h × 4 bytes. One module lock guards
  every cache lookup and insert; layers are built outside it.
- A decoded photo has its own small cache, keyed by `(path, size and mtime, width, height, blur)`
  and holding it cover-fitted and blurred. A dim or card-colour change therefore does not decode the
  file again. A JPEG decodes at a reduced scale (Pillow's `draft()`) when that still covers the
  frame.
- `background_mean(look, width, height) -> RGB` feeds the contrast check.
- An image that is missing or fails to decode raises nothing. The layer uses the base preset's
  built-in background and reports the problem through a returned `warnings` list, or a sibling
  function, so the renderer can surface it.

### 3.3 Renderer (`core/frame_renderer.py`)

- `render_frame_pillow(..., look: Look = NIGHT_GOLD)`. The frame starts as a copy of
  `base_layer(...)` instead of `new(COLOUR_BG)` plus `draw_rounded_rectangle`.
- Every `COLOUR_*` use reads from `look`. This covers the header, body, highlight, subtle, debug,
  placeholder, caption strip, caption spoken, active and upcoming colours. The module constants stay
  as `NIGHT_GOLD`'s source values, for compatibility.
- The export loop (`render_video` and its helpers) takes `look` and passes it to every frame. Frames
  still go to FFmpeg unchanged.
- Invariant: with `look=NIGHT_GOLD`, output is **byte-identical** to today. The existing golden-frame
  and render tests stay as they are, and a new test pins this.
- Performance: today each frame allocates a full-frame overlay and alpha-composites the card. The
  cached base layer removes that work. The plan measures render time for alFurqanCut at the portrait
  preset before and after, with `night_gold` and with a blurred image. Target: no slower than today.

### 3.4 Project, jobs and CLI

- `project.style` holds `Look.to_dict(...)`. An empty dict means `night_gold`. The project version is
  unchanged, because the slot already exists and unknown keys are already preserved.
- `content_hash()` includes `style` **only when it is non-empty**. Changing the look marks a render
  stale, and every existing project keeps its current hash.
- Importing the user's image copies it into `<project stem>.look/<sha256[:12]>.<ext>` beside the
  project file, and the style stores the relative path. Moving or sharing the project folder keeps
  the image. Re-importing the same file reuses the same copy. Old copies are not garbage-collected:
  they are small, and the user can delete the folder.
- `RenderRequest` gains `look: Look = NIGHT_GOLD`. `jobs/render.py` builds it from the project, and
  the still-frame preview (`jobs/preview.py`) and the review window's `FrameView` pass the same look.
- The CLI's render and preview commands get `--look <preset>`, with choices from `PRESETS`. It is
  applied when the project has no style of its own.

### 3.5 GUI

- `gui/review/look_panel.py` (new) is the panel described in §2. It edits the session's project
  style through the session, so undo, dirty-state and save work like the other edits; the plan
  checks how `session.py` handles edits and follows that. Each change triggers `FrameView.show_at(t,
  force=True)`.
- Colour pickers use `QColorDialog` with the alpha channel.
- `Prefs.default_look` stores JSON in QSettings.
  - "Use for new videos" saves the current look there.
  - If the look includes an image, the image is copied into the app's data directory
    (`looks/<sha12>.<ext>`). When a new job's project is created, its style is seeded from
    `Prefs.default_look`, and the image is copied into that project's `.look/` folder.
- Strings go in `gui/i18n.py` in every language the app ships. Arabic strings are added to the
  existing native-speaker review item.
- Preset names and colours are defined once, in `core/looks.py`; the swatches are drawn from those
  definitions.

## 4. Failure handling

| Situation | Behaviour |
|---|---|
| Project `style` has bad or unknown values | Field-wise fallback to the base preset; unknown keys preserved |
| User image missing or undecodable at preview or export | Base preset's built-in background; a warning in the strip and in the render result; the export completes |
| Image is huge (e.g. 8000×6000) | Decoded once, cover-fitted down to frame size, and cached; never resized per frame |
| Low contrast | Inline warning only; never blocks |
| Preferences hold a default look whose image is gone | New jobs get the look with the base preset's built-in background, and a warning is shown in the review window |

## 5. Testing

- `looks`: each preset round-trips through `to_dict` and `from_dict`; per-field fallback; unknown
  keys kept; relative image path; contrast ratio against known WCAG pairs; every preset has no
  readability warnings on its own suggested background.
- `backgrounds`: each kind renders at two sizes; cover-fit crops rather than stretches; dim and blur
  change the pixels as expected; a missing or corrupt image falls back with a warning; the cache is
  hit across frames and invalidated when the file's mtime changes.
- Renderer: `NIGHT_GOLD` output is byte-identical to the pre-change output, using the existing
  goldens plus one new frame pinned before the change; every preset renders an ayah frame and a
  placeholder frame; the export passes `look` through (spy).
- Project: `content_hash` is unchanged for an empty style and changes when the look changes; the
  image is copied into `.look/` and the copy is deduplicated by hash.
- GUI (pytest-qt):
  - choosing a palette updates the session's style and redraws the preview;
  - Customise changes one colour;
  - the contrast warning appears;
  - "Use for new videos" writes `Prefs.default_look`;
  - a new job is seeded from it;
  - Reset works.
- A manual check before merging: one exported video per preset, plus one with an image, watched on
  this laptop.

## 6. Delivery

One feature branch (`feat/look`), worked in its own worktree while `feat/mushaf-v10` is in flight.
v10 merges first; any overlap (tests that render text) is resolved by rebasing `feat/look` onto it.
Phases:

1. `looks` + `backgrounds` + renderer threading, with the byte-identical guarantee.
2. Project, jobs, CLI and preview plumbing.
3. The GUI panel and preferences.

There is one whole-branch review at the end of each phase, and the branch is merged locally after
the final one.

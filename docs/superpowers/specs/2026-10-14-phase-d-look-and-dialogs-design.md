# Phase D: the Look panel, the Episode dialog and the Export dialog — design

Date: 2026-10-14 · Status: approved in conversation, awaiting written-spec review

## 1. Purpose

Phases A to C (merged) gave the app its presentation layer, a restructured
home window and a relaid review window. Three screens the audit named are
still as they were (`docs/ux-audit-2026-10-13.md` §2.3 R5, §2.4 D1–D2, §4.3,
§4.4):

- The Look panel's swatches are 48×28 icons filled with the accent when
  chosen; Customise is seven stacked buttons with 18 px chips and no values;
  no slider shows its value; the background is a combo with a stray "Choose
  image…" button under it.
- The Episode dialog opens as three combos reading "None" in a 320×210 box.
  The generated intro and outro with their previews, the QR code and the
  recitation list appear only after a choice, so the person cannot see what
  an episode is before making one.
- The Export dialog's three format checkboxes say nothing about when to use
  which, and the disabled "match the video" radio gives its reason only on
  hover.

Phase D reflows the panel and rebuilds the two dialogs around what they
already do. No behaviour of the session, the renderer, the episode join or
the subtitle export changes.

Success means:

- The Look panel reads as tiles: six palette tiles with the chosen one
  ringed in gold, six background tiles painted in the look's own colours, a
  single column of colour rows with their hex values, a readout on every
  slider, and the two bottom actions weighted apart.
- The Episode dialog shows the whole episode at once: four cards in render
  order with a picture, a length and a standing on each, and the chosen
  part's fields under them.
- The Export dialog says what each format is for and why the video timeline
  cannot be chosen.
- Every widget attribute the tests reach keeps its name, except the Look
  panel's `background_combo`, which has no equivalent and whose tests move
  to the tiles.
- The review window still fits 1280 px wide in both languages at every
  preset; the Look panel's height floor does not move.

## 2. What the user sees

### 2.1 Look panel

Top to bottom, inside the same scroll area:

**Header.** The "Look" `SectionHeader` and the "Palette · Night gold" line
(`status_label`) stay as they are.

**Palette tiles.** The six presets are `QToolButton`s with a 56×36 icon
(`_SWATCH = QSize(56, 36)`) and the preset's name under it, three per row in
a left-to-right grid as today. The icon is the preset in miniature as
`_swatch_icon` draws it now, scaled to the new size. The checked state's
pixmap carries a 2 px ring in the theme's gold token
(`theme.current_tokens().gold`), inset 1 px, so the ring sits on the tile
and not around the name; the icons are rebuilt on a palette change so the
ring takes the new theme's gold. The stylesheet rule
`QToolButton[swatch="true"]:checked` loses its accent fill: it becomes a
transparent background with the text in the accent colour, so the chosen
name reads in the accent. `QPushButton[segment="true"]:checked` keeps its
fill through its own rule.

**Customise.** The disclosure button stays, collapsed by default, chevron as
today. Inside it, one column of rows. Each row is a `_ColourRow(QPushButton)`
with the property `row="true"`: a 24 px chip icon (`_CHIP = QSize(24, 24)`,
the checkerboard chip as today), the colour's name as the button's text,
left-aligned, and a child `hex_label` at the trailing end showing `#RRGGBB`
in the secondary font, left-to-right in both languages. A new stylesheet
rule gives `QPushButton[row="true"]` a transparent background, no border,
left text alignment, `4px 6px` padding and the raised colour on hover and
focus. `colour_buttons[name]` and `background_colour_button` are these
rows; the alpha of a see-through colour is not shown in the hex. The Card
opacity label, slider and new readout sit under the Card row as today; the
Background colour row stays last and still hides while the background is an
image.

**Background.** The label "Background" stays. The combo goes. Under the
label, six `QToolButton` tiles in the same 3×2 left-to-right grid as the
palette, the property `swatch="true"` so they ring and colour like the
palette tiles, held in `background_tiles: dict[str, QToolButton]` keyed by
`BACKGROUND_KINDS`. Each tile's icon is that kind painted by the real
background code in the look's current colours, drawn at four times the size
and shrunk with LANCZOS so a pattern reads at 56×36 (`core.backgrounds.
tile_image`, §3). The colours are the ones choosing the kind would use: the
panel derives the `Background` for each kind through one function,
`_background_for_kind(look, kind)`, which is also what a click applies (the
body of today's `_on_background_kind`). The tiles are drawn without dim and
blur: they show the kind, the sliders show the rest. The image tile shows
the look's photo when the look has one that can be read, else the Lucide
`image` icon in the secondary role centred on the frame colour. The tiles
are rebuilt only when the colours or the image stamp changed since the last
build.

Clicking a tile does what choosing the kind in the combo did: the image tile
opens the file dialog and, on cancel or a failed import, the tiles go back
to the look's kind; any other tile applies its `Background` through the
session. The tile of the current kind is checked; clicking it again changes
nothing and stays checked. Without a project file the image tile is disabled
with the "no file" tooltip, as the combo's item was.

The kind names shorten in both languages (`look.bg.*`): Solid, Gradient,
Stars, Lattice, Arches, My image / لون واحد، تدرّج، نجوم، شبكة، أقواس،
صورتي. The file-dialog filter keeps using `look.bg.image`.

`image_button` ("Choose image…", `image` icon) stays under the tiles so a
chosen image can be swapped, now a quiet button (below). It is disabled
without a project file as today.

**Dim and Blur.** The two sliders keep their labels, ranges and gesture
behaviour. Each gains a readout `QLabel` at its trailing end
(`opacity_readout`, `dim_readout`, `blur_readout`), 44 px wide,
left-to-right, right-aligned to the slider's end, in the secondary font:
`t("look.percent", value=n)` ("{value}%" in both languages, the digits
Western as the clock's are) for opacity and dim, the plain number for blur.
The readout follows `valueChanged`, so it moves during a drag.

**Bottom.** `default_button` ("Use for new videos") stays a bordered button
as the default style draws it. `reset_button` ("Reset") and `image_button`
get the property `quiet="true"`: a new stylesheet rule
`QPushButton[quiet="true"]` draws a transparent background, a transparent
1 px border, the accent as text colour, and the raised colour on hover; the
focus rule keeps the 2 px accent border all buttons have. Both keep their
icons.

**Width.** At the left column's 294 px floor three tiles with their names
fit the panel's 286 px inner width (three 93 px columns); "Ink on paper"
and "حبر على ورق" are the longest names and fit a column. Nothing in the
panel asks for more than it does today, so the window's 1280 px fit does
not move.

### 2.2 Episode dialog

**The strip.** Four `PartCard`s in a row in render order, Intro ·
Recitation · Lecture · Outro, in a layout the Arabic window mirrors. Each
card is about 200 px wide and holds, top to bottom: a bold title
(`episode.intro`, `episode.recitation`, the new `episode.lecture`,
`episode.outro`), a control area the dialog fills, a thumbnail fitted into a
176×99 box (`THUMB_BOX`) keeping the lecture's shape, a length line, and a
`StatusChip` shown only when there is something to say.

**Intro and Outro cards.** The control area holds the kind combo
(`intro_kind`, `outro_kind`, unchanged) and, under it, the clip line
(`intro_label`, `outro_label`) with the Choose… and Remove buttons
(`intro_choose`, `intro_remove`, `outro_choose`, `outro_remove`), visible for
My clip only, as the row is today. The thumbnail by kind:

- None: an empty tile, a `QLabel` with the property `placeholder="true"`
  drawn by a new rule as a 2 px dashed border in the border colour, no text.
- My clip: the clip's middle frame grabbed by ffmpeg (`jobs.clip_frames`,
  §3) when the clip is chosen or the dialog opens; when the frame cannot be
  made, the Lucide `film` icon in the secondary role centred in the tile.
- Generated: the same middle frame the detail pane's preview shows, scaled
  into the box, redrawn with it when typing rests (`flush_previews`).

The length line is the clip's `mm:ss` (or `episode.unknown`), the generated
seconds as `mm:ss`, or "—" for None. The chip is amber
(`StatusChip(kind="attention")`, icon `triangle-alert`): "Clip missing"
(`episode.chip.missing`) when the part's clip is gone, else "Needs
attention" (`episode.chip.attention`) when that part's warning label has
text or the outro's link is refused; hidden otherwise.

**Recitation card.** The control area holds `recitation_box`, unchanged in
contents and texts. The thumbnail is the chosen job's home-list thumbnail
(`thumbnails.thumbnail_for(project, user_cache_dir())`, the project read
once per path and kept beside the lengths); an empty tile for None, the
`film` icon when there is no picture. The length is what `_update_total`
computes for it. The chip repeats the chosen job's standing with the texts
the combo already uses: `episode.rendered` as `accent` with `circle-check`,
`episode.render_first` as `neutral` with `info`, `episode.damaged` as
`attention` with `triangle-alert`; hidden for None.

**Lecture card.** No controls. The thumbnail is drawn once at open from the
lecture's first shown card at the session's current look, through the
thumbnail module's drawing function (`thumbnails.thumbnail_image`, §3)
without caching; the empty tile when the lecture shows no card. The length
is `_lecture_seconds` (or `episode.unknown`). No chip. The card is not
selectable and never shows the selected border.

**Selection and the detail pane.** An Intro or Outro card is selected by a
click on it, by Enter or Space while it has focus, or when a control inside
it takes focus (the combo, the clip buttons). The selected card has the
property `selected="true"` and a 2 px accent border from a new rule
`QFrame[card="true"][selected="true"]`. Under the strip, the total line
(`total_label`), then the detail pane (`detail_pane`): a widget holding the
existing `intro_fields` and `outro_fields` widgets, each with its preview
beside its form exactly as today, warnings included. The pane shows the
selected part's fields while that part is Generated and hides otherwise,
with the dialog's `adjustSize()` as `_show_kinds` calls it today. At open
the first Generated part in (intro, outro) is selected, else Intro;
switching a part's combo to Generated selects its card. `selected_part()`
and `select_part(part)` read and set it. The message line
(`message_label`), the defaults hint and OK/Cancel stay under the pane.

**What stays.** The tracked link, its field, Copy, the readable address line,
the QR fit warning and the preview drawing are untouched. OK, the defaults
logic, the clip copying and `choice()` are untouched.

### 2.3 Export dialog

The formats become a vertical list. Each format is its checkbox
(`_format_boxes[name]`, text unchanged) with a one-line description under it
in the secondary font, indented to the checkbox's text:

| Key | English | Arabic |
|---|---|---|
| `export.format.srt` | For players, editors and YouTube; almost everything reads it. | للمشغّلات والمحرّرات ويوتيوب؛ تقرؤها البرامج كلّها تقريبًا. |
| `export.format.vtt` | For web pages and HTML video players. | لصفحات الويب ومشغّلات الفيديو في المتصفّح. |
| `export.format.ass` | Keeps styling and position; for players and editors that support it. | تحفظ التنسيق والموضع؛ للمشغّلات والمحرّرات التي تدعمها. |

The video radio (`_video_radio`) sits in a row with a
`StatusChip(t("export.needs_render"), "info", "neutral")`
(`needs_render_chip`, "Needs a render" / "يحتاج إلى إخراج أولًا") that is
visible only while the radio is disabled; the radio's tooltip stays. The
stale wording on the radio is unchanged. The folder and name fields, the
result line and the buttons are as they are.

### 2.4 Ayah picker

Untouched.

## 3. Modules

| Module | What |
|---|---|
| `core/backgrounds.py` | `tile_image(background: Background, width: int, height: int) -> Image.Image`: the background drawn at `4 × (width, height)` by `_draw_background` with `dim=0, blur=0`, shrunk with LANCZOS to `(width, height)`; raises `ValueError`/`OSError` for an image that cannot be read (the panel then draws the icon tile). The stamp is `_image_stamp(background)`. |
| `gui/review/look_panel.py` | `_ColourRow`, `background_tiles`, `_background_for_kind(look, kind) -> Background` (module function, pure), `_tile_icon(image)`, the three readouts, `_swatch_icon(look, ring: QColor)` with the ringed On state; `background_combo` removed; `_WheelSafeCombo` removed with it. |
| `gui/theme.py` | rules: `QToolButton[swatch="true"]:checked` (transparent, accent text), `QPushButton[row="true"]`, `QPushButton[quiet="true"]`, `QLabel[placeholder="true"]`, `QFrame[card="true"][selected="true"]`. |
| `jobs/thumbnails.py` | `thumbnail_image(project: Project, look: Look, size: tuple[int, int]) -> Image.Image | None`: the uncached drawing `thumbnail_for` does, at *size*, with *look*; `thumbnail_for` calls it. `LONG_SIDE` and the cache are unchanged. |
| `jobs/clip_frames.py` | `clip_frame(path: Path, cache_dir: Path | None, *, seconds: float | None, long_side: int = 176) -> Path | None`: ffmpeg (`require_binary("ffmpeg")`) writes the frame at `seconds / 2` (0 when unknown) scaled to *long_side* with the aspect kept, as a PNG under `cache_dir / "thumbs" / f"clip-{sha1(path|mtime_ns|size)}.png"`, written atomically as the thumbnails are; served from the cache when present; `None` when *cache_dir* is None, ffmpeg is missing, exits non-zero or exceeds 10 s, or the file cannot be written. Never raises. |
| `gui/review/episode_cards.py` | `PartCard(Card)`: `title_label`, `controls: QVBoxLayout`, `thumb_label`, `length_label`, `chip: StatusChip`; `set_thumbnail(pixmap | None)`, `set_placeholder()`, `set_icon_tile(name)`, `set_length(text)`, `set_chip(text | None, kind, icon)`, `set_selectable(bool)`, `set_selected(bool)`, `selected` property; signal `select_requested`; click, Enter/Space and a child's `FocusIn` (event filter on the widgets added to `controls`) emit it. `THUMB_BOX = (176, 99)`. |
| `gui/review/episode_dialog.py` | builds the strip and the pane; `cards: dict[str, PartCard]`, `detail_pane`, `selected_part()`, `select_part(part)`; `_update_cards()` after every change that touched a part (kind, clip, fields, recitation, previews); thumbnails as §2.2. `_ClipRow` keeps its API; its `layout()` is replaced by the card's control area. |
| `gui/review/export_dialog.py` | the format list with descriptions; `needs_render_chip`. |
| `gui/i18n.py` | both languages: `look.percent`, the six shortened `look.bg.*`, `episode.lecture` ("Lecture" / "المحاضرة"), `episode.chip.missing` ("Clip missing" / "المقطع مفقود"), `episode.chip.attention` ("Needs attention" / "يحتاج إلى انتباه"), `export.format.srt/vtt/ass`, `export.needs_render`. |
| `tools/screenshots.py` | adds `review-customise-<lang>-<theme>.png` (the review window with Customise open), and photographs the Episode dialog with its intro set to Generated and selected so the strip and the pane both show; the Export image stays. |

## 4. Data flow

```
LookPanel.refresh ─▶ _show(look) ─▶ palette tiles checked, colour rows' chips + hex,
                                   readouts, background tiles rebuilt if colours/stamp changed,
                                   background_tiles[kind].setChecked(True)
background_tiles[kind].clicked ─▶ _choose_background(kind):
    "image" ─▶ _choose_image() ─▶ import_look_image ─▶ _apply; on cancel/failure ─▶ refresh
    else    ─▶ _apply(replace(look, background=_background_for_kind(look, kind)))
slider.valueChanged ─▶ readout.setText, then the existing _on_* ─▶ _apply

EpisodeDialog.__init__ ─▶ cards built ─▶ _ClipRow / combos / fields reparented ─▶
    _show_kinds ─▶ _update_link ─▶ _update_total ─▶ _update_cards ─▶ flush_previews
combo/kind/clip/field/recitation change ─▶ (today's handlers) ─▶ _update_cards
flush_previews ─▶ pane previews ─▶ cards' generated thumbnails
PartCard.select_requested ─▶ select_part ─▶ detail_pane shows that part's fields if Generated
_ClipRow._choose ─▶ probe_part ─▶ clip_frame(path, user_cache_dir(), seconds=duration) ─▶ card thumbnail
```

## 5. Error handling

- A background image that cannot be read gives the image tile the icon
  tile, and the existing `look_notices` line still says why.
- `tile_image` for a pattern at a size below its cell draws what fits; it
  never raises for a size.
- `clip_frame` never raises: ffmpeg missing, failing, timing out, an
  unwritable cache or a `None` cache dir all give `None` and the film icon.
  The timeout kills the process.
- A recitation project that cannot be loaded shows the empty tile and the
  damaged chip, as its combo entry is disabled today.
- The lecture thumbnail's renderer error is logged and shows the empty
  tile; the dialog opens regardless.
- Reparenting the existing widgets changes no signal wiring; `done()` still
  stops the preview timer.

## 6. Testing

- `tests/test_looks.py` (or a new `tests/test_backgrounds.py`): `tile_image`
  returns the asked size for every kind; a solid tile is its colour; a
  pattern tile differs from a solid one of the same colour; an image tile
  with a missing file raises.
- `tests/test_review_widgets.py` (Look panel): palette tiles are 56×36 and
  the checked tile's On pixmap has gold on its edge while the Off pixmap
  does not; the checked tile changes with `refresh`; colour rows show the
  hex of the look's colour and update after a pick; readouts read "70%" /
  "35%" / "8" for those values and follow a slider drag; `background_tiles`
  has one tile per kind, the look's kind is checked, clicking a tile applies
  that kind with the same colours the old combo did (the existing
  second-colour tests move to the tiles), clicking the image tile opens the
  chooser and a cancel leaves the kind, the image tile is disabled without a
  project file; `image_button` still opens the chooser; the quiet property
  on Reset and Choose image; the tile grid is left-to-right under RTL. The
  two combo wheel-safety tests are removed; the slider wheel tests stay.
- `tests/test_thumbnails.py`: `thumbnail_image` draws at the asked size and
  `thumbnail_for` still caches the same PNG.
- `tests/test_clip_frames.py`: a frame from a clip written by ffmpeg in the
  test (skipped when ffmpeg is absent) has the asked long side and is served
  from the cache the second time; a missing file, a missing ffmpeg
  (monkeypatched `require_binary`) and a None cache give `None`.
- `tests/test_episode.py`, `tests/test_episode_recitation.py`: every
  existing test stays green with its names; new tests: four cards in order
  and mirrored under RTL; the Lecture card shows the lecture's length and no
  controls; the selected card at open is the first Generated part else
  Intro; switching a combo to Generated selects its card and shows the pane;
  None and My clip hide the pane; the chip reads "Clip missing" for a gone
  clip and "Needs attention" for a refused link; the recitation chip follows
  the chosen entry; a clip's thumbnail is set when `clip_frame` returns a
  path (monkeypatched) and the film icon when it returns `None`; the
  generated thumbnail matches the pane's preview after `flush_previews`.
- `tests/test_export.py`: the three descriptions are under their boxes in
  both languages; the chip is visible with no render and hidden with one;
  the stale text is unchanged.
- `tests/test_theme.py`: the new rules name no Fusion-sensitive widget; the
  quiet and row buttons' text colours pass 4.5:1 in both themes.
- `tests/test_review_window.py`: the 1280 px fit tests stay green; the Look
  panel's minimum width is unchanged.
- `tools/screenshots.py` gains the Customise image and the Generated-intro
  Episode image; the phase review attaches them.

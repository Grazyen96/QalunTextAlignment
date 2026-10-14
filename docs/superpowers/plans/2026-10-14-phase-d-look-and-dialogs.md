# Phase D: Look panel, Episode dialog and Export dialog — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reflow the Look panel into tiles, rows and readouts; rebuild the Episode dialog as a strip of four cards with a detail pane; give the Export dialog format descriptions and a visible reason for its disabled radio.

**Architecture:** The Look panel keeps its session-driven model (every change through `ReviewSession.set_look`, `refresh` reads back) and swaps its controls: palette and background `QToolButton` tiles whose icons are painted pixmaps (the background ones by `core.backgrounds.tile_image`), `_ColourRow` buttons, readout labels. The Episode dialog keeps every widget and handler it has and reparents them into `PartCard`s (a new `Card` subclass) and a detail pane; thumbnails come from the existing thumbnail module and a new ffmpeg frame grab. The Export dialog only changes layout. Five stylesheet rules carry the new states.

**Tech Stack:** PySide6 6.11 (Fusion + palette-first stylesheet), Pillow, ffmpeg via `require_binary`, pytest with `QT_QPA_PLATFORM=offscreen`.

**Spec:** `docs/superpowers/specs/2026-10-14-phase-d-look-and-dialogs-design.md`

## Global Constraints

- Interpreter `venv/bin/python`; tests `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest …`; lint `venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools` before every commit.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- The stylesheet never names `QComboBox`, `QSpinBox`, `QSlider`, `QScrollBar`, `QCheckBox`, `QRadioButton`, `QTabWidget`, `QTabBar`, `QProgressBar` (`tests/test_theme.py` enforces it).
- Every `t()` / `tn()` key exists in both `STRINGS["en"]` and `STRINGS["ar"]` with the same placeholders (`tests/test_i18n.py`); Arabic values-only lines start with `‏`; direction marks are written as `\u` escapes (ruff PLE2502).
- Never `QTest.qWait`; use `qt_app.processEvents()` / `tests.qt_helpers`.
- Every widget attribute the tests reach keeps its name. The one exception the spec allows is `LookPanel.background_combo`, removed in Task 5.
- The review window must still satisfy `tests/test_review_window.py`'s 1280 px fit tests (`minimumSizeHint().width() <= 1280`) in both languages.
- Shortened background names (`look.bg.*`): Solid, Gradient, Stars, Lattice, Arches, My image / لون واحد، تدرّج، نجوم، شبكة، أقواس، صورتي.
- Tile size `_SWATCH = QSize(56, 36)`, chip `_CHIP = QSize(24, 24)`, three tiles per row, readouts 44 px wide, `THUMB_BOX = (176, 99)`, card width 200 px, frame-grab timeout 10 s.

## Review Focus

1. A look whose image file was deleted after it was chosen: the background tiles must still build (icon tile), the panel must not raise, and the missing-image notice must still be said. → Task 5 test `test_a_gone_image_gives_the_image_tile_its_icon`.
2. Typing in the outro's link while the Intro card is selected: the Outro card's chip must turn to "Needs attention" without the selection moving. → Task 9 test `test_a_refused_link_marks_the_outro_card_without_selecting_it`.
3. A clip whose frame cannot be grabbed (ffmpeg absent or failing): the card shows the film icon and the dialog opens and accepts as before. → Task 9 test `test_a_clip_without_a_frame_shows_the_film_icon`.
4. Arabic: the strip reads Outro · Lecture · Recitation · Intro from the left, while hex values and readouts stay left-to-right. → Task 4 test `test_readouts_and_hex_read_left_to_right_in_arabic`, Task 8 test `test_the_strip_mirrors_in_arabic`.
5. The panel at its 294 px floor: the tiles must not widen the panel's minimum and the window must still fit 1280 px. → Task 5 test `test_the_tiles_do_not_widen_the_panel`, Task 11 suite run.

---

### Task 1: Stylesheet rules for tiles, rows, quiet buttons, placeholders and selected cards

**Files:**
- Modify: `src/qurantext/gui/theme.py:161-170` (the checked rules) and the card rules
- Test: `tests/test_theme.py`

**Interfaces:**
- Produces: property selectors `QToolButton[swatch="true"]:checked`, `QPushButton[row="true"]`, `QPushButton[row="true"][rtl="true"]`, `QPushButton[quiet="true"]`, `QLabel[placeholder="true"]`, `QFrame[card="true"][selected="true"]`.

- [ ] **Step 1: Update and add the theme tests**

In `tests/test_theme.py`, replace `test_only_segments_and_swatches_are_filled_when_checked` with:

```python
@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_only_segments_are_filled_when_checked(tokens) -> None:
    """A disclosure says open by its chevron; a checked swatch says chosen by its ring and name."""
    sheet = theme.stylesheet(tokens)
    rule = _rule(sheet, 'QPushButton[segment="true"]:checked')
    assert rule["background"] == tokens.accent and rule["color"] == tokens.on_accent
    assert _measured(rule) >= 4.5
    swatch = _rule(sheet, 'QToolButton[swatch="true"]:checked')
    assert swatch["background"] == "transparent" and swatch["color"] == tokens.accent
    for loose in ("QPushButton:checked", "QToolButton:checked"):
        assert loose not in sheet, loose


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_rows_quiet_buttons_placeholders_and_selected_cards_have_rules(tokens) -> None:
    sheet = theme.stylesheet(tokens)
    row = _rule(sheet, 'QPushButton[row="true"]')
    assert row["background"] == "transparent" and row["text-align"] == "left"
    assert _rule(sheet, 'QPushButton[row="true"][rtl="true"]')["text-align"] == "right"
    quiet = _rule(sheet, 'QPushButton[quiet="true"]')
    assert quiet["background"] == "transparent" and quiet["color"] == tokens.accent
    assert contrast(_c(tokens.accent), _c(tokens.window)) >= 4.5
    assert tokens.border in _rule(sheet, 'QLabel[placeholder="true"]')["border"]
    assert tokens.accent in _rule(sheet, 'QFrame[card="true"][selected="true"]')["border"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_theme.py -q`
Expected: the two new tests FAIL (`AssertionError` on the missing selectors); the rest pass.

- [ ] **Step 3: Write the rules**

In `src/qurantext/gui/theme.py`, inside `stylesheet`, replace the combined checked rule

```
QPushButton[segment="true"]:checked, QToolButton[swatch="true"]:checked {{
    background: {t.accent};
    color: {t.on_accent};
    border-color: {t.accent};
}}
```

with

```
QPushButton[segment="true"]:checked {{
    background: {t.accent};
    color: {t.on_accent};
    border-color: {t.accent};
}}
QToolButton[swatch="true"]:checked {{
    background: transparent;
    color: {t.accent};
    border-color: transparent;
}}
```

Leave the `:checked:disabled` combined rule as it is (the tests pin it). After the `QPushButton[primary="true"]:disabled` rule add:

```
QPushButton[row="true"] {{
    text-align: left;
    background: transparent;
    border: 1px solid transparent;
    padding: 4px 6px;
}}
QPushButton[row="true"][rtl="true"] {{ text-align: right; }}
QPushButton[row="true"]:hover {{ background: {t.raised}; border-color: {t.border}; }}
QPushButton[row="true"]:focus {{ background: {t.raised}; border: 2px solid {t.accent}; padding: 3px 5px; }}
QPushButton[quiet="true"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {t.accent};
}}
QPushButton[quiet="true"]:hover {{ background: {t.raised}; border-color: transparent; }}
QLabel[placeholder="true"] {{ border: 2px dashed {t.border}; border-radius: 6px; background: transparent; }}
```

and after `QFrame[card="true"][empty="true"]`:

```
QFrame[card="true"][selected="true"] {{ border: 2px solid {t.accent}; }}
```

- [ ] **Step 4: Run the theme tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_theme.py tests/test_widgets.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/gui/theme.py tests/test_theme.py
git commit -m "Give the sheet rules for ringed swatches, colour rows, quiet buttons, dashed placeholders and selected cards

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `tile_image` in the backgrounds module

**Files:**
- Modify: `src/qurantext/core/backgrounds.py` (`__all__`, a new public function after `background_mean`)
- Test: `tests/test_backgrounds.py`

**Interfaces:**
- Produces: `tile_image(background: Background, width: int, height: int) -> Image.Image` — the kind drawn at `4 × (width, height)` with `dim=0, blur=0`, shrunk with LANCZOS; raises `ValueError(code)` for an image that is missing or unreadable (`code` is `"image_missing"` / `"image_unreadable"`), `OSError` from decoding.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backgrounds.py`:

```python
# -- tiles for the Look panel ------------------------------------------------------


def test_a_tile_has_the_asked_size_for_every_kind(tmp_path) -> None:
    from qurantext.core.backgrounds import tile_image
    from qurantext.core.looks import BACKGROUND_KINDS

    for kind in BACKGROUND_KINDS:
        if kind == "image":
            continue
        bg = Background(kind, (20, 30, 40, 255), (200, 200, 200, 255))
        assert tile_image(bg, 56, 36).size == (56, 36), kind


def test_a_solid_tile_is_its_colour_and_a_pattern_tile_is_not() -> None:
    from qurantext.core.backgrounds import tile_image

    solid = tile_image(Background("solid", (20, 30, 40, 255), (20, 30, 40, 255)), 56, 36)
    assert solid.convert("RGB").getpixel((28, 18)) == (20, 30, 40)
    stars = tile_image(Background("pattern_stars", (20, 30, 40, 255), (230, 200, 90, 255)), 56, 36)
    assert len(set(stars.convert("RGB").getdata())) > 1, "the lines reach the small tile"


def test_a_tile_ignores_dim_and_blur() -> None:
    from qurantext.core.backgrounds import tile_image

    plain = Background("solid", (200, 100, 50, 255), (200, 100, 50, 255))
    dimmed = replace(plain, dim=0.8, blur=20.0)
    assert tile_image(dimmed, 8, 8).tobytes() == tile_image(plain, 8, 8).tobytes()


def test_an_image_tile_shows_the_photo_and_a_gone_one_raises(tmp_path) -> None:
    from qurantext.core.backgrounds import tile_image

    photo = tmp_path / "p.png"
    Image.new("RGB", (40, 40), (250, 10, 10)).save(photo)
    bg = Background("image", (0, 0, 0, 255), (0, 0, 0, 255), image=photo)
    assert tile_image(bg, 16, 16).convert("RGB").getpixel((8, 8)) == (250, 10, 10)
    photo.unlink()
    with pytest.raises(ValueError, match="image_missing"):
        tile_image(bg, 16, 16)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/bin/python -m pytest tests/test_backgrounds.py -q -k tile`
Expected: FAIL with `ImportError: cannot import name 'tile_image'`.

- [ ] **Step 3: Implement**

In `src/qurantext/core/backgrounds.py` add `"tile_image"` to `__all__`, `from dataclasses import replace` to the imports if absent, and after `background_mean`:

```python
#: A tile is drawn this many times larger and shrunk, so a pattern's lines survive 56 px.
TILE_OVERSAMPLE = 4


def tile_image(background: Background, width: int, height: int) -> Image.Image:
    """*background*'s kind in its colours at *width* × *height*, without dim or blur.

    For the Look panel's background tiles: what the kind looks like, not how
    far it is dimmed (the sliders show that). Raises ``ValueError`` with the
    problem's code for an image that is missing or cannot be read.
    """
    flat = replace(background, dim=0.0, blur=0.0)
    big = (width * TILE_OVERSAMPLE, height * TILE_OVERSAMPLE)
    try:
        image = _draw_background(flat, *big, _image_stamp(flat))
    except _ImageProblem as problem:
        raise ValueError(problem.code) from problem
    return image.resize((width, height), Image.Resampling.LANCZOS)
```

Check how `_decode_photo` reports an unreadable file: if it raises `_ImageProblem("image_unreadable")` the `except` above covers it; if it lets an `OSError` through, that is the `OSError` the spec names and needs no handling here.

- [ ] **Step 4: Run the tests**

Run: `venv/bin/python -m pytest tests/test_backgrounds.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/core/backgrounds.py tests/test_backgrounds.py
git commit -m "Draw a background kind as a small tile in its own colours for the Look panel

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: The phase's strings in both languages

**Files:**
- Modify: `src/qurantext/gui/i18n.py` (the `look.*`, `episode.*`, `export.*` blocks of `STRINGS["en"]` and `STRINGS["ar"]`)
- Test: `tests/test_i18n.py` (existing parity tests)

**Interfaces:**
- Produces the keys every later task calls: `look.percent`, `episode.lecture`, `episode.chip.missing`, `episode.chip.attention`, `export.format.srt`, `export.format.vtt`, `export.format.ass`, `export.needs_render`; the six `look.bg.*` values shortened.

- [ ] **Step 1: Edit the English block**

Change the six background names and add the new keys next to their neighbours:

```python
        "look.bg.solid": "Solid",
        "look.bg.gradient": "Gradient",
        "look.bg.pattern_stars": "Stars",
        "look.bg.pattern_lattice": "Lattice",
        "look.bg.pattern_arches": "Arches",
        "look.bg.image": "My image",
        "look.percent": "{value}%",
```

after `"episode.unknown": "?",`:

```python
        "episode.lecture": "Lecture",
        "episode.chip.missing": "Clip missing",
        "episode.chip.attention": "Needs attention",
```

after `"export.formats": "Formats",`:

```python
        "export.format.srt": "For players, editors and YouTube; almost everything reads it.",
        "export.format.vtt": "For web pages and HTML video players.",
        "export.format.ass": "Keeps styling and position; for players and editors that support it.",
        "export.needs_render": "Needs a render",
```

- [ ] **Step 2: Edit the Arabic block**

```python
        "look.bg.solid": "لون واحد",
        "look.bg.gradient": "تدرّج",
        "look.bg.pattern_stars": "نجوم",
        "look.bg.pattern_lattice": "شبكة",
        "look.bg.pattern_arches": "أقواس",
        "look.bg.image": "صورتي",
        "look.percent": "{value}%",
```

```python
        "episode.lecture": "المحاضرة",
        "episode.chip.missing": "المقطع مفقود",
        "episode.chip.attention": "يحتاج إلى انتباه",
```

```python
        "export.format.srt": "للمشغّلات والمحرّرات ويوتيوب؛ تقرؤها البرامج كلّها تقريبًا.",
        "export.format.vtt": "لصفحات الويب ومشغّلات الفيديو في المتصفّح.",
        "export.format.ass": "تحفظ التنسيق والموضع؛ للمشغّلات والمحرّرات التي تدعمها.",
        "export.needs_render": "يحتاج إلى إخراج أولًا",
```

`look.percent` is the same in both languages on purpose: the readout is a left-to-right number, like the clock.

- [ ] **Step 3: Run the string tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_i18n.py -q`
Expected: PASS (the "every key the code uses exists" test only sees keys once later tasks call them; the parity test checks both languages now).

- [ ] **Step 4: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/gui/i18n.py
git commit -m "Add the phase D strings: shorter background names, a percent readout, the Lecture card, two chips, three format descriptions and the render chip

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Look panel — palette tiles, colour rows, readouts, quiet buttons

**Files:**
- Modify: `src/qurantext/gui/review/look_panel.py`
- Test: `tests/test_review_widgets.py` (the Look panel section, after `_panel`)

**Interfaces:**
- Consumes: Task 1 rules, Task 3 `look.percent`.
- Produces: `_SWATCH = QSize(56, 36)`, `_CHIP = QSize(24, 24)`, `_ColourRow(QPushButton)` with `hex_label` and `set_colour(rgba)`, `_two_state_icon(pixmap: QPixmap) -> QIcon` (Off plain, On ringed in gold), `opacity_readout`, `dim_readout`, `blur_readout`; `reset_button` and `image_button` carry `quiet="true"`.

- [ ] **Step 1: Write the failing tests**

After `test_the_swatches_keep_their_order_in_arabic` in `tests/test_review_widgets.py` add:

```python
def test_palette_tiles_are_56_by_36_and_the_chosen_one_wears_a_gold_ring(
    qt_app, session, prefs
) -> None:
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QIcon

    from qurantext.core.looks import NIGHT_GOLD
    from qurantext.gui import theme

    panel = _panel(session, prefs)
    tile = panel.palette_buttons["night_gold"]
    assert tile.iconSize() == QSize(56, 36)
    on = tile.icon().pixmap(QSize(56, 36), QIcon.Mode.Normal, QIcon.State.On).toImage()
    off = tile.icon().pixmap(QSize(56, 36), QIcon.Mode.Normal, QIcon.State.Off).toImage()
    assert on.pixelColor(0, 18) == QColor(theme.current_tokens().gold)
    assert off.pixelColor(0, 18) == QColor(*NIGHT_GOLD.frame_bg[:3])
    assert tile.isChecked()


def test_colour_rows_show_the_hex_and_follow_a_pick(qt_app, session, prefs, monkeypatch) -> None:
    from PySide6.QtGui import QColor

    from qurantext.core.looks import NIGHT_GOLD

    panel = _panel(session, prefs)
    row = panel.colour_buttons["highlight_word"]
    assert row.property("row") is True and row.text() == "Highlighted word"
    assert row.hex_label.text() == "#{:02X}{:02X}{:02X}".format(*NIGHT_GOLD.highlight_word[:3])
    _answer_colours(monkeypatch, QColor(1, 2, 3))
    row.click()
    assert row.hex_label.text() == "#010203"


def test_every_slider_has_a_readout_that_follows_it(qt_app, session, prefs) -> None:
    panel = _panel(session, prefs)
    panel.opacity_slider.setValue(70)
    panel.dim_slider.setValue(35)
    panel.blur_slider.setValue(8)
    assert panel.opacity_readout.text() == "70%"
    assert panel.dim_readout.text() == "35%"
    assert panel.blur_readout.text() == "8"
    assert panel.dim_readout.width() == 44 or panel.dim_readout.minimumWidth() == 44


def test_reset_and_choose_image_are_quiet_and_use_for_new_is_not(qt_app, session, prefs) -> None:
    panel = _panel(session, prefs)
    assert panel.reset_button.property("quiet") is True
    assert panel.image_button.property("quiet") is True
    assert panel.default_button.property("quiet") is None


def test_readouts_and_hex_read_left_to_right_in_arabic(qt_app, session, prefs) -> None:
    from qurantext.gui import i18n

    i18n.set_language("ar")
    panel = _panel(session, prefs)
    panel.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    assert panel.dim_readout.layoutDirection() == Qt.LayoutDirection.LeftToRight
    row = panel.colour_buttons["card"]
    assert row.hex_label.layoutDirection() == Qt.LayoutDirection.LeftToRight
    assert row.property("rtl") is True
```

- [ ] **Step 2: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py -q -k "palette_tiles or colour_rows or readout or quiet or left_to_right_in_arabic"`
Expected: FAIL (`AttributeError: hex_label` / `opacity_readout`, size mismatch).

- [ ] **Step 3: Implement in `look_panel.py`**

Constants and imports:

```python
from PySide6.QtCore import QEvent, QPointF, QRectF, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QFocusEvent, QHideEvent, QIcon, QMouseEvent, QPainter, QPalette, QPen, QPixmap,
    QWheelEvent,
)
...
from qurantext.gui import theme

#: A palette or background tile, in pixels.
_SWATCH = QSize(56, 36)
#: A colour row's chip.
_CHIP = QSize(24, 24)
#: Tiles per row; three fit the panel's width with their names under them.
_SWATCH_COLUMNS = 3
#: The ring a chosen tile wears, in pixels.
_RING = 2
#: A slider's value readout, wide enough for "100%".
_READOUT_WIDTH = 44
```

The ringed two-state icon (replaces the end of `_swatch_icon`):

```python
def _ringed(pixmap: QPixmap) -> QPixmap:
    """*pixmap* with the theme's gold ring on its edge: the chosen tile."""
    ringed = QPixmap(pixmap)
    painter = QPainter(ringed)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(theme.current_tokens().gold), _RING))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    half = _RING / 2
    painter.drawRoundedRect(
        QRectF(half, half, pixmap.width() - _RING, pixmap.height() - _RING), 3, 3
    )
    painter.end()
    return ringed


def _two_state_icon(pixmap: QPixmap) -> QIcon:
    """*pixmap* plain when not chosen, ringed when chosen (``QIcon.State.On``)."""
    result = QIcon()
    result.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
    result.addPixmap(_ringed(pixmap), QIcon.Mode.Normal, QIcon.State.On)
    return result


def _swatch_icon(look: Look) -> QIcon:
    """The preset in miniature: its card on its background, a line of text and a highlight."""
    pixmap = QPixmap(_SWATCH)
    pixmap.fill(_qcolor(look.frame_bg))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_qcolor(look.card))
    painter.drawRoundedRect(QRectF(4, 4, _SWATCH.width() - 8, _SWATCH.height() - 8), 4, 4)
    painter.setBrush(_qcolor(look.body_text))
    painter.drawRoundedRect(QRectF(10, 11, 36, 3), 1.5, 1.5)
    painter.drawRoundedRect(QRectF(10, 20, 14, 3), 1.5, 1.5)
    painter.setBrush(_qcolor(look.highlight_word))
    painter.drawRoundedRect(QRectF(27, 20, 19, 3), 1.5, 1.5)
    painter.end()
    return _two_state_icon(pixmap)
```

The colour row:

```python
class _ColourRow(QPushButton):
    """One editable colour: its chip, its name, and its hex at the trailing end."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(name, parent)
        self.setProperty("row", True)
        self.setProperty("rtl", is_rtl())
        self.setIconSize(_CHIP)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        trailing = QHBoxLayout(self)
        trailing.setContentsMargins(0, 0, theme.SP_8, 0)
        trailing.addStretch(1)
        self.hex_label = QLabel()
        self.hex_label.setFont(theme.font("secondary"))
        self.hex_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self.hex_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.hex_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        trailing.addWidget(self.hex_label)

    def set_colour(self, colour: RGBA) -> None:
        self.setIcon(_chip_icon(colour))
        self.hex_label.setText("#{:02X}{:02X}{:02X}".format(*colour[:3]))
```

In `_build`: every palette button gets `button.setIcon(_swatch_icon(look))`, `button.setIconSize(_SWATCH)` (unchanged lines) — nothing else changes there. Replace the colour buttons' creation with `_ColourRow(_colour_name(name))` and `background_colour_button = _ColourRow(t("look.colour.background"))`; drop their `setIconSize` calls. Build the readouts with a helper used for all three sliders:

```python
    def _readout(self) -> QLabel:
        label = QLabel()
        label.setFixedWidth(_READOUT_WIDTH)
        label.setFont(theme.font("secondary"))
        label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return label
```

Opacity: after `custom.addWidget(self.opacity_label)` put the slider and `self.opacity_readout = self._readout()` in a `QHBoxLayout` (slider stretch 1). Dim/Blur: the `sliders` grid gains a third column: `sliders.addWidget(self.dim_readout, 0, 2)`, `sliders.addWidget(self.blur_readout, 1, 2)`. Wire in `_wire`, before the existing slider loop:

```python
        self.opacity_slider.valueChanged.connect(
            lambda v: self.opacity_readout.setText(t("look.percent", value=v))
        )
        self.dim_slider.valueChanged.connect(
            lambda v: self.dim_readout.setText(t("look.percent", value=v))
        )
        self.blur_slider.valueChanged.connect(lambda v: self.blur_readout.setText(str(v)))
```

and in `_show`, after the three `_set_slider` calls, set the readouts explicitly as well (a blocked `setValue` emits nothing):

```python
        self.opacity_readout.setText(t("look.percent", value=self.opacity_slider.value()))
        self.dim_readout.setText(t("look.percent", value=self.dim_slider.value()))
        self.blur_readout.setText(str(self.blur_slider.value()))
```

In `_show` replace `button.setIcon(_chip_icon(getattr(look, name)))` with `button.set_colour(getattr(look, name))` and `self.background_colour_button.setIcon(_chip_icon(bg.colour))` with `.set_colour(bg.colour)`. Quiet buttons, in `_build` right after creating them:

```python
        self.image_button.setProperty("quiet", True)
        self.reset_button.setProperty("quiet", True)
```

Theme switch: the gold ring was painted with the tokens at build time. In `changeEvent`, on the palette events already handled, also rebuild the palette icons:

```python
            for name, button in self.palette_buttons.items():
                button.setIcon(_swatch_icon(PRESETS[name]))
```

- [ ] **Step 4: Run the panel tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py tests/test_review_window.py -q -x`
Expected: all PASS (the combo tests still pass: the combo is untouched in this task).

- [ ] **Step 5: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/gui/review/look_panel.py tests/test_review_widgets.py
git commit -m "Turn the palette swatches into 56×36 tiles ringed in gold when chosen, the colour buttons into rows with their hex, give every slider a readout, and quieten Reset and Choose image

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Look panel — background tiles replace the combo

**Files:**
- Modify: `src/qurantext/gui/review/look_panel.py`
- Test: `tests/test_review_widgets.py`

**Interfaces:**
- Consumes: Task 2 `tile_image`, Task 4 `_two_state_icon`, `_SWATCH`.
- Produces: `LookPanel.background_tiles: dict[str, QToolButton]`, module functions `_background_for_kind(look: Look, kind: str) -> Background` and `_second_colour(look: Look, colour: RGBA) -> RGBA`; `background_combo` and `_WheelSafeCombo` removed.

- [ ] **Step 1: Rewrite the combo-driven tests and add the tile tests**

In `tests/test_review_widgets.py`:

- `test_the_background_colour_of_a_gradient_or_pattern_keeps_a_second_colour`: replace the two `combo` lines with `panel.background_tiles[kind].click()`.
- `test_a_built_in_background_keeps_the_colours_and_clears_dim`: replace `combo = …; combo.setCurrentIndex(combo.findData("solid"))` with `panel.background_tiles["solid"].click()` and the stars line with `panel.background_tiles["pattern_stars"].click()`.
- `test_choosing_an_image_copies_it_beside_the_project`: replace the `background_combo.currentData() == "image"` assertion with `assert panel.background_tiles["image"].isChecked()`.
- Rename `test_choosing_image_in_the_list_runs_the_same_flow` to `test_cancelling_the_image_tile_leaves_the_kind` and make its body:

```python
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    panel = _panel(session, prefs)
    panel.background_tiles["image"].click()
    assert not session.can_undo, "a cancelled choice is no edit"
    assert panel.background_tiles["solid"].isChecked(), "the tiles go back to what the look has"
    assert not panel.background_tiles["image"].isChecked()
```

- `test_an_image_background_has_no_colour_to_pick` and `test_a_project_without_a_file_cannot_take_an_image`: read them; wherever they reach `background_combo` (its model item or `currentData`) use `panel.background_tiles["image"]` (`isEnabled()`, `toolTip()`, `isChecked()`) instead.
- `test_the_wheel_scrolls_past_the_sliders_and_the_list`: rename to `test_the_wheel_scrolls_past_the_sliders`, delete the `background_combo` wheel line and the `currentData() == "solid"` assertion; keep the `asked` assertion.
- `test_a_control_with_focus_still_takes_the_wheel`: delete the four `background_combo` lines (the slider half stays).

Add:

```python
def test_there_is_a_tile_per_background_kind_and_the_looks_kind_is_checked(
    qt_app, session, prefs
) -> None:
    from PySide6.QtCore import QSize

    from qurantext.core.looks import BACKGROUND_KINDS

    panel = _panel(session, prefs)
    assert tuple(panel.background_tiles) == BACKGROUND_KINDS
    assert [k for k, b in panel.background_tiles.items() if b.isChecked()] == ["solid"]
    for kind, tile in panel.background_tiles.items():
        assert tile.iconSize() == QSize(56, 36) and tile.property("swatch") is True, kind
        assert tile.text() == t(f"look.bg.{kind}")
    panel.background_tiles["gradient"].click()
    assert [k for k, b in panel.background_tiles.items() if b.isChecked()] == ["gradient"]
    assert session.look.background.kind == "gradient"


def test_a_tile_is_painted_in_the_looks_colours(qt_app, session, prefs) -> None:
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QIcon

    from qurantext.core.looks import PRESETS

    panel = _panel(session, prefs)
    panel.palette_buttons["ocean"].click()
    image = (
        panel.background_tiles["solid"]
        .icon()
        .pixmap(QSize(56, 36), QIcon.Mode.Normal, QIcon.State.Off)
        .toImage()
    )
    assert image.pixelColor(28, 18) == QColor(*PRESETS["ocean"].frame_bg[:3])


def test_clicking_the_current_tile_again_changes_nothing(qt_app, session, prefs) -> None:
    panel = _panel(session, prefs)
    panel.background_tiles["solid"].click()
    assert not session.can_undo and panel.background_tiles["solid"].isChecked()


def test_a_gone_image_gives_the_image_tile_its_icon(
    qt_app, session, prefs, tmp_path, monkeypatch
) -> None:
    from PIL import Image
    from PySide6.QtWidgets import QFileDialog

    src = tmp_path / "photo.png"
    Image.new("RGB", (20, 20), (200, 10, 10)).save(src)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(src), ""))
    panel = _panel(session, prefs)
    panel.image_button.click()
    assert panel.background_tiles["image"].isChecked()
    session.look.background.image.unlink()
    panel.dim_slider.setValue(10)  # a change: the tiles rebuild with the image gone
    # No exception above is the point: the tile fell back to its icon and stays chosen.
    assert panel.background_tiles["image"].isChecked()
    assert session.look.background.kind == "image"


def test_the_tiles_do_not_widen_the_panel(qt_app, session, prefs) -> None:
    panel = _panel(session, prefs)
    assert panel.minimumSizeHint().width() <= 286


def test_the_background_tiles_keep_their_order_in_arabic(qt_app, session, prefs) -> None:
    from qurantext.gui import i18n

    i18n.set_language("ar")
    panel = _panel(session, prefs)
    panel.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    panel.resize(294, 900)
    panel.show()
    _spin_briefly(qt_app)
    xs = [panel.background_tiles[k].x() for k in ("solid", "gradient", "pattern_stars")]
    assert xs == sorted(xs)
    panel.close()
```

`t` is imported at the top of the test module already (check; otherwise `from qurantext.gui.i18n import t` inside each test).

- [ ] **Step 2: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py -q -k "tile or background"`
Expected: FAIL with `AttributeError: 'LookPanel' object has no attribute 'background_tiles'`.

- [ ] **Step 3: Implement**

In `look_panel.py`:

Remove `_WheelSafeCombo`, the `QComboBox` and `QStandardItemModel` imports. Add `from qurantext.core.backgrounds import tile_image` and `from PySide6.QtGui import QImage`.

Module functions (replace the `_second_colour` staticmethod):

```python
def _second_colour(look: Look, colour: RGBA) -> RGBA:
    """The preset's own second colour when it has one, else a shade of *colour*."""
    preset = PRESETS.get(look.base_preset, NIGHT_GOLD).background
    if preset.colour == colour and preset.colour2 != colour:
        return preset.colour2
    return _shade(colour)


def _background_for_kind(look: Look, kind: str) -> Background:
    """The background choosing *kind* gives *look*: a solid one is the frame's colour,
    the rest keep the colours and derive a second when there is none; dim and blur start over."""
    if kind == "solid":
        return Background("solid", look.frame_bg, look.frame_bg)
    colour = look.background.colour
    colour2 = look.background.colour2
    if colour2 == colour:
        colour2 = _second_colour(look, colour)
    return Background(kind, colour, colour2)


def _pil_pixmap(image) -> QPixmap:  # noqa: ANN001 — a PIL image
    rgba = image.convert("RGBA")
    width, height = rgba.size
    qimage = QImage(rgba.tobytes(), width, height, 4 * width, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage.copy())


def _icon_tile(colour: RGBA, name: str) -> QPixmap:
    """*name*'s icon centred on *colour*: the image tile while the look has no image."""
    pixmap = QPixmap(_SWATCH)
    pixmap.fill(_qcolor(colour))
    glyph = icon(name, "secondary").pixmap(QSize(20, 20))
    painter = QPainter(pixmap)
    painter.drawPixmap((_SWATCH.width() - 20) // 2, (_SWATCH.height() - 20) // 2, glyph)
    painter.end()
    return pixmap
```

(`icon` comes from `qurantext.gui.icons`; add it to the import beside `set_icon`.)

In `_build`, replace the combo block with the tile grid:

```python
        background_label = QLabel(t("look.background"))
        column.addWidget(background_label)
        tiles = QWidget()
        tiles.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        tile_grid = QGridLayout(tiles)
        tile_grid.setContentsMargins(0, 0, 0, 0)
        tile_grid.setSpacing(2)
        self.background_tiles: dict[str, QToolButton] = {}
        for index, kind in enumerate(BACKGROUND_KINDS):
            tile = QToolButton()
            tile.setCheckable(True)
            tile.setAutoRaise(True)
            tile.setProperty("swatch", True)
            tile.setIconSize(_SWATCH)
            tile.setText(_background_name(kind))
            tile.setToolTip(_background_name(kind))
            tile.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.background_tiles[kind] = tile
            tile_grid.addWidget(tile, index // _SWATCH_COLUMNS, index % _SWATCH_COLUMNS)
        for column_index in range(_SWATCH_COLUMNS):
            tile_grid.setColumnStretch(column_index, 1)
        column.addWidget(tiles)
        #: What the tiles were last painted for; they are rebuilt when it changes.
        self._tiles_key: tuple | None = None
```

The no-file branch disables the image tile instead of the combo's item:

```python
            self.background_tiles["image"].setEnabled(False)
            self.background_tiles["image"].setToolTip(t("session.no_file"))
```

In `_wire`, replace the combo connection with:

```python
        for kind, tile in self.background_tiles.items():
            tile.clicked.connect(lambda _checked=False, k=kind: self._choose_background(k))
```

In `_show`, replace the combo block with:

```python
        self._paint_tiles(look)
        for kind, tile in self.background_tiles.items():
            with QSignalBlocker(tile):
                tile.setChecked(kind == bg.kind)
```

and add:

```python
    def _paint_tiles(self, look: Look) -> None:
        """Each kind in *look*'s colours; only when those colours or the image changed."""
        bg = look.background
        image = bg.image if bg.kind == "image" else None
        try:
            stamp = image.stat().st_mtime_ns if image is not None else None
        except OSError:
            stamp = None
        key = (look.frame_bg, bg.colour, bg.colour2, image, stamp)
        if key == self._tiles_key:
            return
        self._tiles_key = key
        for kind, tile in self.background_tiles.items():
            if kind == "image":
                background = bg if bg.kind == "image" else None
            else:
                background = _background_for_kind(look, kind)
            pixmap = None
            if background is not None:
                try:
                    pixmap = _pil_pixmap(tile_image(background, _SWATCH.width(), _SWATCH.height()))
                except (ValueError, OSError):
                    pixmap = None  # a missing or unreadable image: the icon tile below
            if pixmap is None:
                pixmap = _icon_tile(look.frame_bg, "image")
            tile.setIcon(_two_state_icon(pixmap))
```

Replace `_on_background_kind` with:

```python
    def _choose_background(self, kind: str) -> None:
        if kind == "image":
            if not self._choose_image():
                self._shown = None
                self.refresh()  # the tiles go back to the background the look has
            return
        look = self._session.look
        self._apply(replace(look, background=_background_for_kind(look, kind)))
```

`_pick_background_colour` keeps calling `self._second_colour(start, rgba)` today; change it to the module function `_second_colour(start, rgba)`. In `changeEvent`, after rebuilding the palette icons (Task 4), force the tiles to repaint on the next refresh with `self._tiles_key = None; self._paint_tiles(self._session.look)` so the ring takes the new gold.

Update the module docstring's last paragraph: the panel's sliders take the wheel only with focus; the tiles never take it.

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py tests/test_review_window.py tests/test_rtl.py tests/test_i18n.py -q`
Expected: all PASS, including the 1280 px fit tests.

- [ ] **Step 5: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/gui/review/look_panel.py tests/test_review_widgets.py
git commit -m "Choose a background from six tiles painted in the look's own colours instead of a list, and shorten the kinds' names

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: `thumbnail_image` and the clip frame grab

**Files:**
- Modify: `src/qurantext/jobs/thumbnails.py`
- Create: `src/qurantext/jobs/clip_frames.py`
- Test: `tests/test_thumbnails.py`, create `tests/test_clip_frames.py`

**Interfaces:**
- Produces: `thumbnails.thumbnail_image(project: Project, look: Look, size: tuple[int, int]) -> Image.Image | None`; `clip_frames.clip_frame(path: Path, cache_dir: Path | None, *, seconds: float | None, long_side: int = 176) -> Path | None`, `clip_frames.TIMEOUT_S = 10`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_thumbnails.py`:

```python
def test_thumbnail_image_draws_at_the_asked_size_with_the_given_look(tmp_path) -> None:
    from qurantext.core.looks import PRESETS

    project = _project(tmp_path)
    image = thumbnails.thumbnail_image(project, PRESETS["ocean"], (56, 99))
    assert image is not None and image.size == (56, 99)
    assert image.convert("RGB").getpixel((2, 2)) == PRESETS["ocean"].frame_bg[:3]


def test_thumbnail_image_is_none_for_no_cards_or_a_failing_renderer(tmp_path, monkeypatch) -> None:
    from qurantext.core.looks import NIGHT_GOLD

    assert thumbnails.thumbnail_image(_project(tmp_path, cards=[]), NIGHT_GOLD, (54, 96)) is None

    def boom(*a, **k):
        raise RuntimeError("no renderer")

    monkeypatch.setattr(thumbnails, "render_frame_pillow", boom)
    assert thumbnails.thumbnail_image(_project(tmp_path), NIGHT_GOLD, (54, 96)) is None
```

Create `tests/test_clip_frames.py`:

```python
# tests/test_clip_frames.py
"""A still from a clip for the Episode dialog's cards: grabbed once, then served from the cache."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from qurantext.jobs import clip_frames
from qurantext.jobs.clip_frames import clip_frame

ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _clip(path: Path, size: str = "160x90") -> Path:
    subprocess.run(
        [shutil.which("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
         f"color=c=red:s={size}:d=1", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )  # fmt: skip
    return path


@ffmpeg
def test_a_landscape_clip_gives_a_176_wide_png_served_from_the_cache_next_time(
    tmp_path, monkeypatch
) -> None:
    clip = _clip(tmp_path / "intro.mp4")
    png = clip_frame(clip, tmp_path / "cache", seconds=1.0)
    assert png is not None and png.parent == tmp_path / "cache" / "thumbs"
    with Image.open(png) as image:
        assert image.size == (176, 99)
        assert image.convert("RGB").getpixel((88, 49))[0] > 200
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    assert clip_frame(clip, tmp_path / "cache", seconds=1.0) == png
    assert not calls, "a hit does not run ffmpeg"


@ffmpeg
def test_a_portrait_clip_gives_a_176_tall_png(tmp_path) -> None:
    png = clip_frame(_clip(tmp_path / "up.mp4", "90x160"), tmp_path / "cache", seconds=None)
    with Image.open(png) as image:
        assert image.size == (99, 176)


def test_no_cache_dir_a_missing_file_and_a_missing_ffmpeg_give_none(tmp_path, monkeypatch) -> None:
    assert clip_frame(tmp_path / "x.mp4", None, seconds=1.0) is None
    assert clip_frame(tmp_path / "x.mp4", tmp_path / "cache", seconds=1.0) is None
    (tmp_path / "y.mp4").write_bytes(b"not a video")

    def missing(name, hint=None):
        raise RuntimeError("no ffmpeg")

    monkeypatch.setattr(clip_frames, "require_binary", missing)
    assert clip_frame(tmp_path / "y.mp4", tmp_path / "cache", seconds=1.0) is None


def test_a_failing_or_slow_ffmpeg_gives_none_and_leaves_no_part_file(tmp_path, monkeypatch) -> None:
    (tmp_path / "y.mp4").write_bytes(b"not a video")
    monkeypatch.setattr(clip_frames, "require_binary", lambda name, hint=None: "ffmpeg")

    def fails(*a, **k):
        raise subprocess.CalledProcessError(1, a[0])

    monkeypatch.setattr(subprocess, "run", fails)
    assert clip_frame(tmp_path / "y.mp4", tmp_path / "cache", seconds=1.0) is None

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], clip_frames.TIMEOUT_S)

    monkeypatch.setattr(subprocess, "run", slow)
    assert clip_frame(tmp_path / "y.mp4", tmp_path / "cache", seconds=1.0) is None
    assert not list((tmp_path / "cache" / "thumbs").glob("*.part"))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/bin/python -m pytest tests/test_thumbnails.py tests/test_clip_frames.py -q`
Expected: FAIL (`ModuleNotFoundError: qurantext.jobs.clip_frames`, `AttributeError: thumbnail_image`).

- [ ] **Step 3: Implement `thumbnail_image`**

In `thumbnails.py` add `"thumbnail_image"` to `__all__`, import `Look` from `qurantext.core.looks`, and split `thumbnail_for`:

```python
def thumbnail_image(project: Project, look: Look, size: tuple[int, int]) -> Image.Image | None:
    """The first shown card at *look*, drawn at *size*; None when there is nothing to draw.

    None for a project with no card the video would show, or a renderer that
    raises. Not cached: ``thumbnail_for`` is the cached path.
    """
    if not project.cards:
        return None
    try:
        card = _first_card(project)
        if card is None:
            return None
        width, height = size
        # Halfway in: past the opening, and far enough that a word is lit.
        start, end = float(card["_start_time"]), float(card["_end_time"])
        at = start + max(0.1, (end - start) / 2)
        frame = render_frame_pillow(
            at,
            card,
            width * _OVERSAMPLE,
            height * _OVERSAMPLE,
            DEFAULT_FONT_PATH,
            reserve_caption_band=False,
            look=look,
        )
        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        return Image.fromarray(rgb).resize((width, height), Image.Resampling.LANCZOS)
    except Exception as error:  # noqa: BLE001 - a picture is never worth a damaged row
        _log.debug("No thumbnail for %s: %s", project.path, error)
        return None


def thumbnail_for(project: Project, cache_dir: Path | None) -> Path | None:
    """(docstring as today)"""
    if cache_dir is None or not project.cards:
        return None
    try:
        folder = Path(cache_dir) / "thumbs"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{cache_key(project)}.png"
        if target.is_file():
            return target
        image = thumbnail_image(project, _look(project), _size(project))
        if image is None:
            return None
        _save_atomically(image, target)
        return target
    except Exception as error:  # noqa: BLE001
        _log.debug("No thumbnail for %s: %s", project.path, error)
        return None
```

Run the existing thumbnail tests after this; they must stay green (the renderer monkeypatch in `test_a_renderer_failure_means_no_thumbnail_and_no_exception` now hits `thumbnail_image`).

- [ ] **Step 4: Implement `clip_frames.py`**

```python
"""A still from a video clip, for the Episode dialog's cards.

ffmpeg writes the clip's middle frame as a PNG under the same ``thumbs``
cache the home list's thumbnails use, keyed by the clip's path, time and
size, so a clip is read once however often the dialog opens. Everything that
can go wrong (no ffmpeg, a file that is not a video, a slow decode, a cache
that cannot be written) gives ``None``: the card then shows an icon, and the
dialog opens all the same. Runs where it is called: the dialog already reads
each clip with ffprobe on the UI thread, and a frame costs about as much.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from qurantext.core.video_common import require_binary

__all__ = ["TIMEOUT_S", "clip_frame"]

_log = logging.getLogger(__name__)

#: A frame that takes longer than this is not worth the wait.
TIMEOUT_S = 10


def clip_frame(
    path: Path, cache_dir: Path | None, *, seconds: float | None, long_side: int = 176
) -> Path | None:
    """The PNG of *path*'s frame at ``seconds / 2`` (0 when unknown), *long_side* wide or tall.

    Served from the cache when it is there; ``None`` for anything that fails.
    """
    if cache_dir is None:
        return None
    part: Path | None = None
    try:
        path = Path(path)
        stat = path.stat()
        folder = Path(cache_dir) / "thumbs"
        folder.mkdir(parents=True, exist_ok=True)
        raw = f"clip|{path}|{stat.st_mtime_ns}|{stat.st_size}|{long_side}"
        key = hashlib.sha1(raw.encode("utf-8")).hexdigest()  # noqa: S324 - a cache name
        target = folder / f"clip-{key}.png"
        if target.is_file():
            return target
        ffmpeg = require_binary("ffmpeg")
        at = max(0.0, (seconds or 0.0) / 2)
        scale = (
            f"scale='if(gt(iw,ih),{long_side},-1)':'if(gt(iw,ih),-1,{long_side})'"
        )
        handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed at once, replaced below
            dir=folder, prefix=".", suffix=".png.part", delete=False
        )
        handle.close()
        part = Path(handle.name)
        subprocess.run(
            [
                ffmpeg, "-y", "-nostdin", "-v", "error",
                "-ss", f"{at:.3f}", "-i", str(path),
                "-frames:v", "1", "-vf", scale, "-c:v", "png", "-f", "image2", "-update", "1",
                str(part),
            ],
            check=True,
            timeout=TIMEOUT_S,
            capture_output=True,
        )  # fmt: skip
        os.replace(part, target)
        part = None
        return target
    except Exception as error:  # noqa: BLE001 - a picture is never worth a failed dialog
        _log.debug("No frame for %s: %s", path, error)
        return None
    finally:
        if part is not None:
            part.unlink(missing_ok=True)
```

- [ ] **Step 5: Run the tests**

Run: `venv/bin/python -m pytest tests/test_thumbnails.py tests/test_clip_frames.py tests/test_home_panels.py -q`
Expected: all PASS (the ffmpeg-marked ones skip only on a machine without ffmpeg).

- [ ] **Step 6: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/jobs/thumbnails.py src/qurantext/jobs/clip_frames.py tests/test_thumbnails.py tests/test_clip_frames.py
git commit -m "Split the thumbnail drawing from its cache, and grab a clip's middle frame with ffmpeg into the same cache

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: `PartCard` and `StatusChip.set_icon`

**Files:**
- Create: `src/qurantext/gui/review/episode_cards.py`
- Modify: `src/qurantext/gui/widgets.py` (`StatusChip.set_icon`)
- Test: create `tests/test_episode_cards.py`; `tests/test_widgets.py`

**Interfaces:**
- Consumes: Task 1 rules (`placeholder`, `selected`), `widgets.Card`, `widgets.StatusChip`, `icons.icon`.
- Produces: `THUMB_BOX = (176, 99)`, `CARD_WIDTH = 200`, `fitted_size(frame: tuple[int, int], box: tuple[int, int] = THUMB_BOX) -> tuple[int, int]`, `PartCard(title: str, parent=None)` with `title_label`, `controls: QVBoxLayout`, `thumb_label`, `length_label`, `chip`, `add_control(widget)`, `add_control_layout(layout)`, `set_thumbnail(pixmap: QPixmap | None)`, `set_placeholder()`, `set_icon_tile(name: str)`, `set_length(text: str)`, `set_chip(text: str | None, kind: str = "neutral", icon_name: str | None = None)`, `set_selectable(bool)`, `set_selected(bool)`, `selected` property, signal `select_requested`; `StatusChip.set_icon(name: str | None)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_widgets.py`:

```python
def test_a_chip_can_change_its_icon(qt_app) -> None:
    from qurantext.gui.widgets import StatusChip

    chip = StatusChip("x", "info", "neutral")
    before = chip.icon_label.pixmap().toImage()
    chip.set_icon("triangle-alert")
    assert chip.icon_label.pixmap().toImage() != before
    chip.set_icon(None)
    assert chip.icon_label.isHidden()
```

Create `tests/test_episode_cards.py`:

```python
# tests/test_episode_cards.py
"""One card of the Episode strip: title, controls, thumbnail, length, chip, selection."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QComboBox

from qurantext.gui.review.episode_cards import CARD_WIDTH, THUMB_BOX, PartCard, fitted_size


def test_fitted_size_keeps_the_frames_shape_inside_the_box() -> None:
    assert fitted_size((1920, 1080)) == (176, 99)
    assert fitted_size((1080, 1920)) == (56, 99)
    assert fitted_size((100, 100), (50, 80)) == (50, 50)


def test_a_card_starts_empty_with_a_dash_and_no_chip(qt_app) -> None:
    card = PartCard("Intro")
    assert card.title_label.text() == "Intro" and card.width() == CARD_WIDTH
    assert card.thumb_label.property("placeholder") is True
    assert card.thumb_label.size().toTuple() == THUMB_BOX
    assert card.length_label.text() == "—" and card.chip.isHidden()


def test_a_thumbnail_a_tile_and_a_placeholder_swap_in_and_out(qt_app) -> None:
    card = PartCard("Intro")
    pixmap = QPixmap(352, 198)
    pixmap.fill(QColor(200, 0, 0))
    card.set_thumbnail(pixmap)
    assert card.thumb_label.property("placeholder") is False
    assert card.thumb_label.pixmap().size().toTuple() == THUMB_BOX
    card.set_icon_tile("film")
    assert card.thumb_label.pixmap().width() < 100
    card.set_thumbnail(None)
    assert card.thumb_label.property("placeholder") is True


def test_the_chip_shows_its_text_kind_and_icon_or_hides(qt_app) -> None:
    card = PartCard("Outro")
    card.set_chip("Needs attention", "attention", "triangle-alert")
    assert not card.chip.isHidden() and card.chip.text_label.text() == "Needs attention"
    assert card.chip.property("kind") == "attention"
    card.set_chip(None)
    assert card.chip.isHidden()


def test_a_click_a_key_or_focus_in_a_control_asks_for_selection(qt_app) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent

    card = PartCard("Intro")
    combo = QComboBox()
    card.add_control(combo)
    asked = []
    card.select_requested.connect(lambda: asked.append(True))
    card.click()
    assert asked == [True]
    qt_app.sendEvent(combo, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason))
    assert asked == [True, True]
    card.set_selected(True)
    assert card.selected and card.property("selected") is True
    card.set_selectable(False)
    card.click()
    assert asked == [True, True], "an unselectable card asks for nothing"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_episode_cards.py tests/test_widgets.py -q`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError: set_icon`.

- [ ] **Step 3: Add `StatusChip.set_icon` in `widgets.py`**

```python
    def set_icon(self, name: str | None) -> None:
        """Swap the icon, or drop it with None."""
        self._icon_name = name
        self._draw_icon()
```

- [ ] **Step 4: Write `episode_cards.py`**

```python
"""One card of the Episode dialog's strip: a part's title, controls, picture, length and standing.

The dialog owns four of these in render order (Intro · Recitation · Lecture ·
Outro) and fills each card's ``controls`` with the widgets it already has
(the kind box, the clip line, the recitation list). The card only shows:
a thumbnail fitted into :data:`THUMB_BOX`, a length line, a
:class:`StatusChip` when there is something to say, and whether it is the
selected one (a 2 px accent border, from the sheet's ``selected`` rule).
A click, Enter or Space on the card, or focus landing on one of its
controls, asks the dialog to select it (``select_requested``); the dialog
decides, as the Lecture card is never selectable.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLayout, QVBoxLayout, QWidget

from qurantext.gui import theme
from qurantext.gui.icons import icon
from qurantext.gui.widgets import Card, StatusChip, repolish

__all__ = ["CARD_WIDTH", "THUMB_BOX", "PartCard", "fitted_size"]

#: The box a part's picture is fitted into, in pixels.
THUMB_BOX = (176, 99)
#: Each card's width: the box plus the card's own margins.
CARD_WIDTH = 200
#: An icon tile's glyph.
_GLYPH = 28


def fitted_size(frame: tuple[int, int], box: tuple[int, int] = THUMB_BOX) -> tuple[int, int]:
    """*frame*'s shape scaled to fit *box*, never larger than it."""
    width, height = frame
    scale = min(box[0] / width, box[1] / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


class PartCard(Card):
    """A part of the episode as a card; the dialog fills ``controls`` and sets the rest."""

    #: The person clicked the card, pressed Enter or Space on it, or focused one of its controls.
    select_requested = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(CARD_WIDTH)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(title)
        self.body.setContentsMargins(theme.SP_12, theme.SP_12, theme.SP_12, theme.SP_12)
        self._selectable = True
        self._selected = False
        self.title_label = QLabel(title)
        bold = self.title_label.font()
        bold.setBold(True)
        self.title_label.setFont(bold)
        self.body.addWidget(self.title_label)
        self.controls = QVBoxLayout()
        self.controls.setSpacing(theme.SP_4)
        self.body.addLayout(self.controls)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(QSize(*THUMB_BOX))
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.thumb_label, 0, Qt.AlignmentFlag.AlignHCenter)
        foot = QHBoxLayout()
        self.length_label = QLabel("—")
        self.length_label.setFont(theme.font("secondary"))
        self.chip = StatusChip("", None, "neutral")
        self.chip.hide()
        foot.addWidget(self.length_label)
        foot.addStretch(1)
        foot.addWidget(self.chip)
        self.body.addLayout(foot)
        self.set_placeholder()

    # -- filling ---------------------------------------------------------------------

    def add_control(self, widget: QWidget) -> None:
        """Put *widget* under the title; focus landing on it selects the card."""
        self.controls.addWidget(widget)
        widget.installEventFilter(self)

    def add_control_layout(self, layout: QLayout) -> None:
        """Put a layout of controls under the title, watching each widget in it."""
        self.controls.addLayout(layout)
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.installEventFilter(self)
            elif item is not None and item.layout() is not None:
                self.add_control_layout(item.layout())

    def set_thumbnail(self, pixmap: QPixmap | None) -> None:
        if pixmap is None:
            self.set_placeholder()
            return
        self._mark_placeholder(False)
        self.thumb_label.setPixmap(
            pixmap.scaled(
                QSize(*THUMB_BOX),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def set_placeholder(self) -> None:
        """The dashed empty tile: nothing is chosen for this part."""
        self.thumb_label.clear()
        self._mark_placeholder(True)

    def set_icon_tile(self, name: str) -> None:
        """An icon in place of a picture that could not be made."""
        self._mark_placeholder(False)
        self.thumb_label.setPixmap(icon(name, "secondary").pixmap(QSize(_GLYPH, _GLYPH)))

    def _mark_placeholder(self, on: bool) -> None:
        self.thumb_label.setProperty("placeholder", on)
        repolish(self.thumb_label)

    def set_length(self, text: str) -> None:
        self.length_label.setText(text)

    def set_chip(self, text: str | None, kind: str = "neutral", icon_name: str | None = None) -> None:
        if text is None:
            self.chip.hide()
            return
        self.chip.set_text(text)
        self.chip.set_icon(icon_name)
        self.chip.set_kind(kind)
        self.chip.show()

    # -- selection -------------------------------------------------------------------

    def set_selectable(self, selectable: bool) -> None:
        self._selectable = selectable
        self.setFocusPolicy(
            Qt.FocusPolicy.StrongFocus if selectable else Qt.FocusPolicy.NoFocus
        )
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if selectable else Qt.CursorShape.ArrowCursor
        )

    @property
    def selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.setProperty("selected", selected)
        repolish(self)

    def click(self) -> None:
        """Ask to be selected, as a press or a key would."""
        if self._selectable:
            self.select_requested.emit()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.click()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.click()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.FocusIn:
            self.click()
        return False
```

- [ ] **Step 5: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_episode_cards.py tests/test_widgets.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/gui/review/episode_cards.py src/qurantext/gui/widgets.py tests/test_episode_cards.py tests/test_widgets.py
git commit -m "Add the Episode strip's card: title, controls, a fitted picture or dashed tile, a length, a chip, and selection by click, key or focus

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Episode dialog — the strip, the selection and the detail pane

**Files:**
- Modify: `src/qurantext/gui/review/episode_dialog.py` (`__init__`, `_ClipRow.layout`, `_kind_box`, `_on_kind`, `_show_kinds`, new `select_part`/`selected_part`)
- Test: `tests/test_review_widgets.py` (Episode section)

**Interfaces:**
- Consumes: Task 7 `PartCard`, Task 3 `episode.lecture`.
- Produces: `EpisodeDialog.cards: dict[str, PartCard]` keyed `"intro" | "recitation" | "lecture" | "outro"`, `detail_pane: QWidget`, `selected_part() -> str`, `select_part(part: str) -> None`; `_kind_box(kind, part)`; `_on_kind(part: str | None = None)`.

- [ ] **Step 1: Write the failing tests**

After `test_each_kind_shows_only_its_own_fields` add:

```python
def test_the_strip_has_four_cards_in_render_order_and_the_lecture_is_fixed(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    assert list(dialog.cards) == ["intro", "recitation", "lecture", "outro"]
    assert dialog.cards["lecture"].title_label.text() == t("episode.lecture")
    assert dialog.cards["lecture"].controls.count() == 0
    assert dialog.cards["lecture"].focusPolicy() == Qt.FocusPolicy.NoFocus
    assert dialog.cards["intro"].controls.count() >= 1  # the kind box
    assert dialog.intro_kind.parent() is dialog.cards["intro"]
    assert dialog.recitation_box.parent() is dialog.cards["recitation"]
    dialog.show()
    _spin_briefly(qt_app)
    xs = [dialog.cards[p].x() for p in ("intro", "recitation", "lecture", "outro")]
    assert xs == sorted(xs)
    dialog.close()


def test_the_strip_mirrors_in_arabic(qt_app, episode_lecture, prefs, tmp_path, monkeypatch) -> None:
    from qurantext.gui import i18n
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    i18n.set_language("ar")
    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    dialog.show()
    _spin_briefly(qt_app)
    xs = [dialog.cards[p].x() for p in ("intro", "recitation", "lecture", "outro")]
    assert xs == sorted(xs, reverse=True)
    dialog.close()


def test_selection_starts_on_the_first_generated_part_else_intro(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import EpisodeChoice, GeneratedOutro

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    assert dialog.selected_part() == "intro" and dialog.cards["intro"].selected
    assert dialog.detail_pane.isHidden(), "nothing generated: no fields to show"
    episode_lecture.set_episode(EpisodeChoice(outro_generated=GeneratedOutro(link="example.org")))
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    assert dialog.selected_part() == "outro"
    assert not dialog.detail_pane.isHidden() and _shown(dialog.outro_fields)
    assert dialog.intro_fields.isHidden()


def test_switching_a_part_to_generated_selects_it_and_shows_its_fields(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
    assert dialog.selected_part() == "intro" and _shown(dialog.intro_fields)
    assert dialog.outro_fields.isHidden(), "one part's fields at a time"
    dialog.outro_kind.setCurrentIndex(dialog.outro_kind.findData("none"))
    dialog.outro_kind.setCurrentIndex(dialog.outro_kind.findData("generated"))
    assert dialog.selected_part() == "outro"
    assert _shown(dialog.outro_fields) and dialog.intro_fields.isHidden()
    dialog.select_part("intro")
    assert _shown(dialog.intro_fields) and dialog.outro_fields.isHidden()
    assert dialog.cards["intro"].selected and not dialog.cards["outro"].selected
    dialog.intro_kind.setCurrentIndex(dialog.intro_kind.findData("none"))
    assert dialog.detail_pane.isHidden() and dialog.selected_part() == "intro"
    dialog.cards["outro"].click()
    assert dialog.selected_part() == "outro" and _shown(dialog.outro_fields)
    dialog.select_part("lecture")
    assert dialog.selected_part() == "outro", "the lecture is never selected"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py -q -k "strip or selection or selects_it"`
Expected: FAIL with `AttributeError: 'EpisodeDialog' object has no attribute 'cards'`.

- [ ] **Step 3: Restructure `__init__`**

Imports: add `from PySide6.QtWidgets import QScrollArea` only if needed (not needed); add `from qurantext.gui.review.episode_cards import PartCard` and `from PySide6.QtWidgets import QFrame` (no). Replace the layout part of `__init__` (from `current = session.episode` to `layout.addWidget(self.total_label)`) with:

```python
        current = session.episode
        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SP_12)
        self.total_label = QLabel()

        #: The four parts in render order; the Lecture card is fixed.
        self.cards: dict[str, PartCard] = {
            "intro": PartCard(t("episode.intro")),
            "recitation": PartCard(t("episode.recitation")),
            "lecture": PartCard(t("episode.lecture")),
            "outro": PartCard(t("episode.outro")),
        }
        self.cards["lecture"].set_selectable(False)
        self.cards["recitation"].set_selectable(False)
        strip = QHBoxLayout()
        strip.setSpacing(theme.SP_8)
        for card in self.cards.values():
            strip.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)
        strip.addStretch(1)
        layout.addLayout(strip)
        for part in ("intro", "outro"):
            self.cards[part].select_requested.connect(lambda p=part: self.select_part(p))

        self._intro = _ClipRow(self, "intro", current.intro, current.intro_name)
        self.intro_label, self.intro_choose, self.intro_remove = (
            self._intro.label,
            self._intro.choose,
            self._intro.remove,
        )
        self.intro_kind = self._kind_box(_kind_of(current, "intro"), "intro")
        self.cards["intro"].add_control(self.intro_kind)
        self.cards["intro"].add_control_layout(self._intro.layout())
        self._intro_original = current.intro_generated
        self.intro_fields = self._intro_fields(
            current.intro_generated or prefs.remembered_intro_generated or GeneratedIntro()
        )

        self.recitation_box = QComboBox()
        self.recitation_box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.recitation_box.setMinimumContentsLength(10)
        self._fill_recitations(job_dirs, current.recitation)
        self.recitation_box.currentIndexChanged.connect(self._update_total)
        self.cards["recitation"].add_control(self.recitation_box)

        self._outro = _ClipRow(self, "outro", current.outro, current.outro_name)
        self.outro_label, self.outro_choose, self.outro_remove = (
            self._outro.label,
            self._outro.choose,
            self._outro.remove,
        )
        self.outro_kind = self._kind_box(_kind_of(current, "outro"), "outro")
        self.cards["outro"].add_control(self.outro_kind)
        self.cards["outro"].add_control_layout(self._outro.layout())
        self._outro_original = current.outro_generated
        self.outro_fields = self._outro_fields(
            current.outro_generated or prefs.remembered_outro_generated or GeneratedOutro()
        )

        layout.addWidget(self.total_label)
        #: The selected part's generated fields, under the strip.
        self.detail_pane = QWidget()
        pane = QVBoxLayout(self.detail_pane)
        pane.setContentsMargins(0, 0, 0, 0)
        pane.addWidget(self.intro_fields)
        pane.addWidget(self.outro_fields)
        layout.addWidget(self.detail_pane)
        #: Which of intro/outro the pane shows: the first Generated one, else the intro.
        self._selected = next(
            (part for part in ("intro", "outro") if self._kind(part) == "generated"), "intro"
        )
        self.cards[self._selected].set_selected(True)
```

(`theme` imported as `from qurantext.gui import theme`.) The rest of `__init__` (message label, hint, buttons, `_initial`, `_building = False`, the first `_show_kinds()` …) stays. `_unclipped_labels(form)` on the old outer form is deleted with it.

`_ClipRow.layout()` becomes a column so the clip line and its two buttons fit a 200 px card:

```python
    def layout(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(theme.SP_4)
        self.label.setWordWrap(True)
        column.addWidget(self.label)
        buttons = QHBoxLayout()
        buttons.addWidget(self.choose)
        buttons.addWidget(self.remove)
        column.addLayout(buttons)
        return column
```

Delete `_kind_row`. `_kind_box` takes the part and tells `_on_kind` which changed:

```python
    def _kind_box(self, kind: str, part: str) -> QComboBox:
        box = QComboBox()
        for name in KINDS:
            box.addItem(t(f"episode.kind.{name}"), name)
        box.setCurrentIndex(box.findData(kind))
        box.currentIndexChanged.connect(lambda _index, p=part: self._on_kind(p))
        return box

    def _on_kind(self, part: str | None = None) -> None:
        if self._building:
            return
        if part is not None and self._kind(part) == "generated":
            self.select_part(part)
        self._show_kinds()
        self._update_link()
        self._update_total()
        self._show_missing()
        self.flush_previews()
```

Selection and the pane:

```python
    def selected_part(self) -> str:
        """Which of intro/outro the detail pane belongs to."""
        return self._selected

    def select_part(self, part: str) -> None:
        """Make *part*'s card the selected one; the lecture and the recitation never are."""
        if part not in ("intro", "outro") or part == self._selected:
            return
        self.cards[self._selected].set_selected(False)
        self._selected = part
        self.cards[part].set_selected(True)
        if not self._building:
            self._show_kinds()

    def _show_kinds(self) -> None:
        """Each part's own controls: the clip line for My clip; the selected part's fields for Generated."""
        shown = False
        for part, row, fields in (
            ("intro", self._intro, self.intro_fields),
            ("outro", self._outro, self.outro_fields),
        ):
            kind = self._kind(part)
            row.set_visible(kind == "clip")
            visible = kind == "generated" and part == self._selected
            fields.setVisible(visible)
            shown = shown or visible
        self.detail_pane.setVisible(shown)
        if self.isVisible():
            self.adjustSize()
```

`_clip_chosen(part)` (a clip chosen for a generated part) already calls `_set_kind(part, "clip")`, which fires `_on_kind(part)`; nothing more.

- [ ] **Step 4: Run the Episode tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py tests/test_review_window.py -q -k "episode or Episode or generated or outro or intro or recitation"`
Expected: all PASS. If `test_each_kind_shows_only_its_own_fields` fails on `_shown(fields)` for a part that is Generated but not selected, the selection-on-Generated in `_on_kind` is not firing: check the lambda's `p=part` capture.

- [ ] **Step 5: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/gui/review/episode_dialog.py tests/test_review_widgets.py
git commit -m "Lay the Episode dialog out as a strip of four cards in render order with the selected part's fields in a pane under it

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Episode dialog — thumbnails, lengths and chips on the cards

**Files:**
- Modify: `src/qurantext/gui/review/episode_dialog.py`
- Test: `tests/test_review_widgets.py`

**Interfaces:**
- Consumes: Task 6 `clip_frame`, `thumbnail_for`, `thumbnail_image`; Task 7 card setters and `fitted_size`; Task 3 chip strings.
- Produces: `EpisodeDialog._update_cards()`; `_ClipRow.frame: Path | None`; `_status_code(entry, lecture_video) -> str` (`"rendered" | "render_first" | "damaged"`); module-level names `clip_frame`, `thumbnail_for`, `thumbnail_image`, `user_cache_dir` (tests monkeypatch them on the module).

- [ ] **Step 1: Write the failing tests**

Add `monkeypatch.setenv("QURANTEXT_CACHE_DIR", str(tmp_path / "cache"))` to the `episode_lecture` fixture (so no test writes into the real cache). Then add:

```python
def _no_frames(monkeypatch) -> list:
    """``clip_frame`` makes nothing; what it was asked for."""
    from qurantext.gui.review import episode_dialog

    asked: list = []
    monkeypatch.setattr(
        episode_dialog, "clip_frame", lambda path, cache, **kw: asked.append(path.name) or None
    )
    return asked


def test_the_cards_show_each_parts_length_and_picture(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from PIL import Image

    from qurantext.gui.i18n import t
    from qurantext.gui.review import episode_dialog
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"intro.mp4": 4.0})
    (tmp_path / "intro.mp4").write_bytes(b"intro")
    frame = tmp_path / "frame.png"
    Image.new("RGB", (176, 99), (0, 200, 0)).save(frame)
    monkeypatch.setattr(episode_dialog, "clip_frame", lambda path, cache, **kw: frame)
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    cards = dialog.cards
    assert cards["lecture"].length_label.text() == "01:40"
    assert cards["lecture"].thumb_label.property("placeholder") is True, "no card: empty tile"
    assert cards["intro"].length_label.text() == "—"
    _choose_file(monkeypatch, tmp_path / "intro.mp4")
    dialog.intro_choose.click()
    assert cards["intro"].length_label.text() == "00:04"
    assert cards["intro"].thumb_label.pixmap().size().toTuple() == (176, 99)
    dialog.outro_kind.setCurrentIndex(dialog.outro_kind.findData("generated"))
    dialog.outro_link.setText("")
    dialog.flush_previews()
    assert cards["outro"].length_label.text() == "00:06"
    assert cards["outro"].thumb_label.pixmap() is not None
    assert not cards["outro"].thumb_label.pixmap().isNull()
    assert cards["outro"].chip.isHidden()
    assert t("episode.unknown") not in cards["recitation"].length_label.text()


def test_a_clip_without_a_frame_shows_the_film_icon(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"intro.mp4": 4.0})
    (tmp_path / "intro.mp4").write_bytes(b"intro")
    asked = _no_frames(monkeypatch)
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    _choose_file(monkeypatch, tmp_path / "intro.mp4")
    dialog.intro_choose.click()
    assert asked == ["intro.mp4"]
    card = dialog.cards["intro"]
    assert card.thumb_label.property("placeholder") is False
    assert card.thumb_label.pixmap().width() < 100, "the film icon, not a frame"
    dialog.ok_button.click()
    assert dialog.result() == dialog.DialogCode.Accepted


def test_a_gone_clip_and_a_refused_link_are_said_on_the_cards(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.jobs.episode_assets import EpisodeChoice

    _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {})
    _no_frames(monkeypatch)
    episode_lecture.set_episode(EpisodeChoice(intro=tmp_path / "gone.mp4", intro_name="gone.mp4"))
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    chip = dialog.cards["intro"].chip
    assert not chip.isHidden() and chip.text_label.text() == t("episode.chip.missing")
    assert chip.property("kind") == "attention"
    dialog.intro_remove.click()
    assert chip.isHidden()


def test_a_refused_link_marks_the_outro_card_without_selecting_it(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t

    _no_frames(monkeypatch)
    dialog = _generated_dialog(episode_lecture, prefs, tmp_path, monkeypatch)
    dialog.select_part("intro")
    dialog.outro_link.setText("http://bad host")
    assert dialog.selected_part() == "intro"
    chip = dialog.cards["outro"].chip
    assert not chip.isHidden() and chip.text_label.text() == t("episode.chip.attention")
    dialog.outro_link.setText("example.org")
    assert chip.isHidden()


def test_the_recitation_card_repeats_the_chosen_jobs_standing(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    paths = _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"fatiha.mp4": 7.0})
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    card = dialog.cards["recitation"]
    assert card.chip.isHidden() and card.length_label.text() == "—"
    box = dialog.recitation_box
    box.setCurrentIndex(box.findData(paths["rendered"]))
    assert card.chip.text_label.text() == t("episode.rendered")
    assert card.chip.property("kind") == "accent"
    assert card.length_label.text() == "00:07"
    box.setCurrentIndex(box.findData(paths["fresh"]))
    assert card.chip.text_label.text() == t("episode.render_first")
    assert card.chip.property("kind") == "neutral"
```

Read `_recitation_jobs` to confirm the keys of the dict it returns (`"rendered"`, `"fresh"` or the names it uses) and adjust the two `paths[...]` lookups to them.

- [ ] **Step 2: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py -q -k "cards_show or film_icon or said_on_the_cards or without_selecting or jobs_standing"`
Expected: FAIL (`AttributeError: clip_frame` on the module, lengths "—").

- [ ] **Step 3: Implement**

Imports in `episode_dialog.py`:

```python
from qurantext.config.paths import user_cache_dir
from qurantext.gui.review.episode_cards import PartCard, fitted_size
from qurantext.jobs.clip_frames import clip_frame
from qurantext.jobs.thumbnails import thumbnail_for, thumbnail_image
```

`_ClipRow` gains a frame:

```python
        #: The clip's middle frame as a PNG, when one could be made.
        self.frame: Path | None = None
```

and in `set(...)`, before `self._dialog._update_total()`:

```python
        self.frame = (
            clip_frame(path, user_cache_dir(), seconds=length) if path is not None else None
        )
```

Recitation standing as a code (replace `_status_text`'s body and make `_entry_text` translate it):

```python
def _status_code(entry: JobEntry, lecture_video: Path | None) -> str:
    """``rendered`` only when the episode would use the recorded video as it is (see the rule in ``_status_text``)."""
    if entry.status == DAMAGED:
        return "damaged"
    if entry.status != RENDERED:
        return "render_first"
    try:
        project = load_project(Path(entry.project))
        needs = recitation_needs_render(project, avoid=lecture_video)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        needs = True
    return "render_first" if needs else "rendered"


def _status_text(entry: JobEntry, lecture_video: Path | None) -> str:
    return t(f"episode.{_status_code(entry, lecture_video)}")
```

In `_fill_recitations`, keep each listed entry's code: add `self._recitation_codes: dict[Path, str] = {}` in `__init__` (before `_fill_recitations` runs) and inside the loop `self._recitation_codes[path] = _status_code(entry, lecture_video)`; for the unlisted current one, `self._recitation_codes[_resolved(current)] = _status_code(_entry_of(current), lecture_video)`.

The lecture's picture, drawn once in `__init__` after the cards exist (before `_building = False`):

```python
        self._lecture_pixmap = self._lecture_picture()
```

```python
    def _lecture_picture(self) -> QPixmap | None:
        image = thumbnail_image(self._session.project, self._session.look, fitted_size(self._size))
        return None if image is None else _pixmap(image, QSize(*THUMB_BOX))
```

(`THUMB_BOX` imported from `episode_cards`.) A cached recitation project and its picture:

```python
    def _recitation_project(self, path: Path) -> Project | None:
        key = _resolved(path)
        assert key is not None
        if key not in self._recitation_projects:
            try:
                self._recitation_projects[key] = load_project(key)
            except (OSError, ValueError, KeyError, TypeError):
                self._recitation_projects[key] = None
        return self._recitation_projects[key]
```

with `self._recitation_projects: dict[Path, Project | None] = {}` in `__init__`; `_recitation_length` reads through it (`project = self._recitation_project(path)`; `None` → unknown).

The card update, called at the end of `_update_total`, `_show_warnings` and `_show_missing` (each already guarded by `_building` where it matters; add `if self._building: return` at the top of `_update_cards`):

```python
    def _update_cards(self) -> None:
        """Each card's picture, length and standing, from what the dialog holds now."""
        if self._building:
            return
        for part, row in (("intro", self._intro), ("outro", self._outro)):
            card = self.cards[part]
            kind = self._kind(part)
            if kind == "clip" and row.path is not None:
                card.set_length(_length_text(row.length) if row.length is not None else t("episode.unknown"))
                if row.frame is not None and not QPixmap(str(row.frame)).isNull():
                    card.set_thumbnail(QPixmap(str(row.frame)))
                else:
                    card.set_icon_tile("film")
            elif kind == "generated":
                box = self.intro_seconds if part == "intro" else self.outro_seconds
                card.set_length(_length_text(float(box.value())))
                # Its picture is set by flush_previews, with the pane's preview.
            else:
                card.set_length("—")
                card.set_placeholder()
            if kind == "clip" and row.missing:
                card.set_chip(t("episode.chip.missing"), "attention", "triangle-alert")
            elif kind == "generated" and self._needs_attention(part):
                card.set_chip(t("episode.chip.attention"), "attention", "triangle-alert")
            else:
                card.set_chip(None)

        card = self.cards["recitation"]
        recitation = self._recitation()
        if recitation is None:
            card.set_length("—")
            card.set_placeholder()
            card.set_chip(None)
        else:
            length = self._recitation_length(recitation)
            card.set_length(_length_text(length) if length is not None else t("episode.unknown"))
            project = self._recitation_project(recitation)
            png = thumbnail_for(project, user_cache_dir()) if project is not None else None
            if png is not None and not QPixmap(str(png)).isNull():
                card.set_thumbnail(QPixmap(str(png)))
            elif project is None:
                card.set_placeholder()
            else:
                card.set_icon_tile("film")
            code = self._recitation_codes.get(_resolved(recitation), "render_first")
            kind, glyph = {
                "rendered": ("accent", "circle-check"),
                "render_first": ("neutral", "info"),
                "damaged": ("attention", "triangle-alert"),
            }[code]
            card.set_chip(t(f"episode.{code}"), kind, glyph)

        card = self.cards["lecture"]
        seconds = self._lecture_seconds
        card.set_length(_length_text(seconds) if seconds is not None else t("episode.unknown"))
        card.set_thumbnail(self._lecture_pixmap)

    def _needs_attention(self, part: str) -> bool:
        """Whether *part*'s warning line has text, or the outro's link is refused."""
        label = self.intro_warning if part == "intro" else self.outro_warning
        return bool(label.text()) or (part == "outro" and self._link_error is not None)
```

In `flush_previews`, after `preview.setPixmap(_pixmap(image, preview.size()))` add `self.cards[part].set_thumbnail(_pixmap(image, QSize(*THUMB_BOX)))`, and in its `except` branch `self.cards[part].set_icon_tile("film")`. Its final `self._show_warnings()` already reaches `_update_cards`.

The first `_update_cards` runs from the initial `_update_total()` in `__init__` (after `_building = False`).

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py tests/test_review_window.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/gui/review/episode_dialog.py tests/test_review_widgets.py
git commit -m "Show each Episode card's picture, length and standing: a clip's frame, a generated part's preview, the recitation's thumbnail and the lecture's own

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Export dialog — format descriptions and the render chip

**Files:**
- Modify: `src/qurantext/gui/review/export_dialog.py` (`_build`, `_set_defaults`)
- Test: `tests/test_review_window.py` (Export section)

**Interfaces:**
- Consumes: Task 3 strings, `widgets.StatusChip`.
- Produces: `ExportDialog.format_hints: dict[str, QLabel]`, `needs_render_chip: StatusChip`.

- [ ] **Step 1: Write the failing tests**

After `test_export_on_the_video_timeline_is_offered_only_after_a_render` add:

```python
def test_each_format_has_a_description_and_the_disabled_radio_says_why(qt_app, tmp_path) -> None:
    from qurantext.gui.i18n import t
    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.session import ReviewSession

    project = _project(tmp_path)
    dialog = ExportDialog(ReviewSession(project))
    for name in ("srt", "vtt", "ass"):
        assert dialog.format_hints[name].text() == t(f"export.format.{name}")
    assert not dialog.needs_render_chip.isHidden()
    assert dialog.needs_render_chip.text_label.text() == t("export.needs_render")
    project.record_render(tmp_path / "v.mp4", preset="social", basmala_offset_s=1.0)
    dialog = ExportDialog(ReviewSession(project))
    assert dialog.needs_render_chip.isHidden()


def test_the_format_descriptions_read_in_arabic(qt_app, tmp_path) -> None:
    from qurantext.gui import i18n
    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.session import ReviewSession

    i18n.set_language("ar")
    dialog = ExportDialog(ReviewSession(_project(tmp_path)))
    assert dialog.format_hints["srt"].text() == i18n.STRINGS["ar"]["export.format.srt"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_window.py -q -k "description"`
Expected: FAIL with `AttributeError: format_hints`.

- [ ] **Step 3: Implement**

In `_build`, replace the `formats_row` block with:

```python
        layout.addWidget(QLabel(t("export.formats")))
        self.format_hints: dict[str, QLabel] = {}
        for name in SUBTITLE_FORMATS:
            box = QCheckBox(name.upper())
            self._format_boxes[name] = box
            layout.addWidget(box)
            hint = QLabel(t(f"export.format.{name}"))
            hint.setWordWrap(True)
            hint.setFont(theme.font("secondary"))
            hint.setForegroundRole(QPalette.ColorRole.PlaceholderText)
            hint.setIndent(_HINT_INDENT)  # follows the text direction, unlike a margin
            self.format_hints[name] = hint
            layout.addWidget(hint)
```

with `_HINT_INDENT = 24` (the indicator's width plus its gap) as a module constant, `from qurantext.gui import theme`, `from PySide6.QtGui import QPalette`, `from qurantext.gui.widgets import StatusChip, make_primary`. Replace the two radio `addWidget` lines with:

```python
        video_row = QHBoxLayout()
        video_row.addWidget(self._video_radio)
        self.needs_render_chip = StatusChip(t("export.needs_render"), "info", "neutral")
        video_row.addWidget(self.needs_render_chip)
        video_row.addStretch(1)
        layout.addLayout(video_row)
        layout.addWidget(self._audio_radio)
```

In `_set_defaults`, after `self._video_radio.setEnabled(available)`:

```python
        self.needs_render_chip.setVisible(not available)
```

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_window.py tests/test_rtl.py -q -k "export or rtl"`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/gui/review/export_dialog.py tests/test_review_window.py
git commit -m "Say under each subtitle format what it is for, and beside the video radio that it needs a render

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Screenshots, fit check, docs and the whole suite

**Files:**
- Modify: `tools/screenshots.py`, `docs/release-checklist.md`, `README.md` (only if it describes the Look panel's combo or the Episode dialog's form)
- Test: `tests/test_screenshots_tool.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Extend the screenshot tool**

In `_shoot`, inside the `for mode in ("recitation", "lecture")` loop, after the first `review-{mode}` grab:

```python
                    if mode == "recitation":
                        review.look_panel.customise_toggle.setChecked(True)
                        _spin(100)
                        written.append(_grab(review, out_dir / f"review-customise-{tag}.png"))
                        review.look_panel.customise_toggle.setChecked(False)
```

and in the `else:` (lecture) branch, before grabbing the Episode dialog:

```python
                        episode = EpisodeDialog(review.session, prefs=prefs, parent=review)
                        episode.intro_kind.setCurrentIndex(episode.intro_kind.findData("generated"))
                        episode.intro_name_edit.setText("دروس الشيخ")
                        episode.flush_previews()
                        _spin(100)
                        written.append(_grab(episode, out_dir / f"episode-{tag}.png"))
```

Update the tool's docstring list of images. If `tests/test_screenshots_tool.py` enumerates expected file names, add `review-customise-<tag>.png`.

- [ ] **Step 2: Run the screenshot tool and look**

```bash
QT_QPA_PLATFORM=offscreen venv/bin/python tools/screenshots.py /tmp/phase-d-shots
```

Open `review-recitation-en-light.png`, `review-customise-en-light.png`, `review-recitation-ar-dark.png`, `episode-en-light.png`, `episode-ar-dark.png`, `export-en-light.png`, `export-ar-light.png` with the Read tool. Check: three tiles per row with names, the gold ring on the chosen palette and background tiles, hex values at the rows' trailing ends (right in English, left in Arabic), readouts, four cards with the intro's pane under them, the descriptions under the formats, the chip beside the radio. Fix what is wrong before going on; the dialog must not exceed 1000 px wide in either language (`episode.width()` printed by a one-off script if in doubt).

- [ ] **Step 3: Docs**

In `docs/release-checklist.md`, in the list of Arabic strings awaiting native review, add the phase D keys: `look.bg.*` (the six shortened names), `look.percent`, `episode.lecture`, `episode.chip.missing`, `episode.chip.attention`, `export.format.srt/vtt/ass`, `export.needs_render`. Grep `README.md` for "Background" / "combo" / "Episode" and update any sentence that describes the old controls.

- [ ] **Step 4: The whole suite and lint**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q
```

Expected: everything passes (the baseline was 2381 passed, 1 skipped; the count grows by this phase's tests, and the ffmpeg-marked frame tests skip only without ffmpeg).

- [ ] **Step 5: Commit**

```bash
git add tools/screenshots.py tests/test_screenshots_tool.py docs/release-checklist.md README.md
git commit -m "Photograph the Look panel with Customise open and the Episode strip with a generated intro, and list the phase D Arabic strings for review

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

(Leave `README.md` out of the `git add` if it did not change.)

---

## Self-review

- **Spec coverage.** §2.1 palette tiles, ring, accent name → Task 1 + 4; colour rows with hex → Task 4; background tiles, `_background_for_kind`, image tile, disabled without a file, shortened names, quiet Choose image → Task 5 (+ Task 2 tile painter, Task 3 names); readouts → Task 4; quiet Reset → Task 4; width → Task 5 test + Task 11 suite. §2.2 strip, cards, pane, selection → Task 7 + 8; thumbnails, lengths, chips, recitation standing, lecture picture → Task 6 + 9. §2.3 descriptions and chip → Task 10. §3 `tile_image` → Task 2; `thumbnail_image` and `clip_frames` → Task 6; theme rules → Task 1; strings → Task 3; screenshots → Task 11. §5 error handling: gone image → Task 5 test; `clip_frame` never raises → Task 6 tests; unloadable recitation → Task 9 (`_recitation_project` None → placeholder); lecture renderer error → `thumbnail_image` returns None → placeholder. §6 testing: each bullet has its task.
- **Placeholders.** None; every step carries its code. Task 9 asks the implementer to read `_recitation_jobs` for its dict keys and Task 5 to read two existing tests before adapting them, which is reading, not guessing.
- **Type consistency.** `set_chip(text, kind, icon_name)` is used with that order in Task 9; `fitted_size` returns `(w, h)` tuples consumed by `thumbnail_image(project, look, size)`; `clip_frame(path, cache_dir, *, seconds, long_side)` matches its tests and its call in `_ClipRow.set`; `_kind_box(kind, part)` is the only signature; `_two_state_icon` is defined in Task 4 and used in Task 5.
- **Review Focus.** Each of the five lines names its test and task.

# Phase A: Presentation Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Qalun its own light and dark theme, a type and spacing scale, bundled icons, an app icon and four composite widgets, applied in place to every existing screen without moving anything.

**Architecture:** One `gui/theme.py` turns a frozen `Tokens` set into a `QPalette` and a generated stylesheet and applies both to the `QApplication` (Fusion forced), with a `system | light | dark` preference that follows the OS colour scheme live. `gui/icons.py` tints bundled Lucide SVGs through QtSvg into cached `QIcon`s, re-tinted on a theme switch by walking every window's buttons. `gui/widgets.py` holds the composites; the existing screens call them in place, keeping every widget attribute name the tests reach.

**Tech Stack:** Python 3.12, PySide6 6.11 (QtCore, QtGui, QtWidgets, QtSvg), Pillow 12 (ICO/ICNS), pytest, ruff 0.15.13, PyInstaller spec at `packaging/qalun.spec`.

**Spec:** `docs/superpowers/specs/2026-10-13-phase-a-presentation-layer-design.md`

## Global Constraints

- Run every command with the project's interpreter: `venv/bin/python`. There is no `python` on PATH. Prefix GUI test runs with `QT_QPA_PLATFORM=offscreen`.
- Tests: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/<file>.py -q`. Lint before each commit: `venv/bin/ruff check src tests tools && venv/bin/ruff format --check src tests tools` (ruff is pinned to 0.15.13; CI runs `ruff format --check`).
- Never wait on the event loop with `QTest.qWait` (it holds the GIL and has deadlocked the suite); use `tests.qt_helpers.spin` / `wait_for`.
- Every widget attribute a test reaches keeps its name and class: `job_list.title_label`, `job_list.refresh_button`, `new_job.heading_label`, `new_job.drop_zone`, `new_job.choose_button`, `new_job.recitation_button`, `new_job.lecture_button`, `new_job.more_button`, `new_job.start_button`, `review.play_button`, `review.render_button`, `review.save_button`, `look_panel.customise_toggle`, and the rest. `make_primary` must not subclass.
- Every new `t("…")` key exists in both `STRINGS["en"]` and `STRINGS["ar"]` in `src/qurantext/gui/i18n.py` (`tests/test_i18n.py::test_every_key_the_code_uses_exists_in_every_language` enforces it). Arabic strings get the native-speaker-review note in the commit message, as earlier phases did.
- The stylesheet names none of `QComboBox`, `QSpinBox`, `QSlider`, `QScrollBar`, `QCheckBox`, `QRadioButton` (a test asserts it).
- Contrast floors, measured with `tests.test_colors.contrast`: text on its surface ≥ 4.5, `on_accent` on `accent` ≥ 4.5, `accent` on surfaces ≥ 3.0, `border` on `window` ≥ 1.5. Adjust a token value, never a threshold.
- Icon names are Lucide's at tag **1.56.0** (three spec names are renamed there: `check-circle` → `circle-check`, `trash-2` → `trash`, `circle-help` → `circle-question-mark`).
- Bundled files live under `src/qurantext/assets/` and are reached with `qurantext.config.paths.bundled_asset(relative)`; the PyInstaller spec already copies the whole folder.
- No layout moves, no new panels, no behaviour change. Commit messages describe the change for a reader of `git log`, as the existing history does, and end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **A theme switch while a review window is open and a word is selected**: the strip, waveform and job rows must repaint in the new palette with the selection and amber still readable, and no icon left in the old colour. Test added to Task 7.
2. **`system` mode on a Qt that reports `Qt.ColorScheme.Unknown`** (Linux with no portal): must resolve to light and never raise. Test added to Task 2.
3. **Arabic with a theme switch**: the mirrored chevrons must stay mirrored after `apply_theme`, since `refresh_icons` rebuilds them. Test added to Task 9.
4. **A stored `theme` value from a future build** (`"amoled"`): reads as `system`, the combo shows System, nothing raises. Test added to Task 2.
5. **A disabled primary button** (Start before a file is chosen): must not look like the enabled one and must still show its text at ≥ 4.5:1. Test added to Task 1 (stylesheet rule present) and Task 8 (Start disabled renders the `border` background).

---

### Task 1: Theme tokens, palette, stylesheet, fonts and spacing

**Files:**
- Create: `src/qurantext/gui/theme.py`
- Create: `tests/test_theme.py`
- Modify: `tests/test_colors.py:40-41` (the LIGHT / DARK fixtures)

**Interfaces:**
- Consumes: `tests.test_colors.contrast(a: QColor, b: QColor) -> float`; `qurantext.gui.colors.warning_color`, `playhead_color`.
- Produces: `Tokens` (frozen dataclass: `name, window, panel, raised, border, text, secondary, accent, on_accent, gold`), `LIGHT`, `DARK`, `MODES = ("system", "light", "dark")`, `palette(tokens) -> QPalette`, `stylesheet(tokens) -> str`, `font(role: str) -> QFont` with roles `title | section | body | secondary | clock`, constants `SP_4 SP_8 SP_12 SP_16 SP_24 SP_32`, `tokens_for(name: str) -> Tokens`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_theme.py
"""The app's own light and dark theme: every colour reads, the sheet stays off Fusion's widgets."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtGui import QColor, QFont, QPalette  # noqa: E402

from qurantext.gui import theme  # noqa: E402
from qurantext.gui.colors import playhead_color, warning_color  # noqa: E402
from tests.test_colors import contrast  # noqa: E402

THEMES = [theme.LIGHT, theme.DARK]
IDS = ["light", "dark"]


def _c(hex_value: str) -> QColor:
    return QColor(hex_value)


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_text_reads_on_every_surface(tokens) -> None:
    for surface in (tokens.window, tokens.panel, tokens.raised):
        assert contrast(_c(tokens.text), _c(surface)) >= 4.5, surface
        assert contrast(_c(tokens.secondary), _c(surface)) >= 4.5, surface


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_the_accent_reads_as_a_control_and_carries_its_text(tokens) -> None:
    assert contrast(_c(tokens.on_accent), _c(tokens.accent)) >= 4.5
    for surface in (tokens.window, tokens.panel):
        assert contrast(_c(tokens.accent), _c(surface)) >= 3.0, surface


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_the_border_is_visible(tokens) -> None:
    assert contrast(_c(tokens.border), _c(tokens.window)) >= 1.5


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_the_fixed_colours_still_read_on_the_new_surfaces(tokens) -> None:
    palette = theme.palette(tokens)
    amber = warning_color(palette)
    for role in (QPalette.ColorRole.Base, QPalette.ColorRole.Window):
        assert contrast(amber, palette.color(role)) >= 4.5
    assert contrast(playhead_color(palette), palette.color(QPalette.ColorRole.Window)) >= 3.0


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_the_palette_maps_every_role_the_sheet_relies_on(tokens) -> None:
    palette = theme.palette(tokens)
    assert palette.color(QPalette.ColorRole.Window).name().upper() == tokens.window.upper()
    assert palette.color(QPalette.ColorRole.Base).name().upper() == tokens.panel.upper()
    assert palette.color(QPalette.ColorRole.Highlight).name().upper() == tokens.accent.upper()
    assert palette.color(QPalette.ColorRole.HighlightedText).name().upper() == tokens.on_accent.upper()
    assert palette.color(QPalette.ColorRole.Link).name().upper() == tokens.accent.upper()
    assert palette.color(QPalette.ColorRole.PlaceholderText).name().upper() == tokens.secondary.upper()
    disabled = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
    assert disabled.name().upper() == tokens.secondary.upper()


def test_light_is_light_and_dark_is_dark() -> None:
    from qurantext.gui.colors import is_light

    assert is_light(theme.palette(theme.LIGHT))
    assert not is_light(theme.palette(theme.DARK))


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_the_sheet_leaves_fusions_widgets_alone(tokens) -> None:
    sheet = theme.stylesheet(tokens)
    for widget in ("QComboBox", "QSpinBox", "QSlider", "QScrollBar", "QCheckBox", "QRadioButton"):
        assert widget not in sheet, widget


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_the_sheet_styles_what_fusion_cannot(tokens) -> None:
    sheet = theme.stylesheet(tokens)
    assert 'QPushButton[primary="true"]' in sheet
    assert 'QPushButton[primary="true"]:disabled' in sheet
    assert "QFrame#dropZone" in sheet
    assert 'QFrame#dropZone[dragOver="true"]' in sheet
    assert 'QFrame[card="true"]' in sheet
    assert "QHeaderView::section" in sheet
    assert "QProgressBar::chunk" in sheet
    assert tokens.accent in sheet and tokens.on_accent in sheet


def test_tokens_are_found_by_name() -> None:
    assert theme.tokens_for("light") is theme.LIGHT
    assert theme.tokens_for("dark") is theme.DARK
    with pytest.raises(KeyError):
        theme.tokens_for("sepia")


def test_fonts_follow_the_scale(qt_app) -> None:
    body = theme.font("body")
    assert theme.font("title").pointSizeF() > theme.font("section").pointSizeF() > body.pointSizeF()
    assert theme.font("secondary").pointSizeF() < body.pointSizeF()
    assert theme.font("section").weight() == QFont.Weight.DemiBold
    assert theme.font("clock").pointSizeF() == body.pointSizeF()
    with pytest.raises(KeyError):
        theme.font("huge")


def test_spacing_is_an_eight_point_scale() -> None:
    assert (theme.SP_4, theme.SP_8, theme.SP_12, theme.SP_16, theme.SP_24, theme.SP_32) == (
        4, 8, 12, 16, 24, 32
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_theme.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'qurantext.gui.theme'`

- [ ] **Step 3: Write `gui/theme.py` (tokens, palette, sheet, fonts, spacing)**

```python
# src/qurantext/gui/theme.py
"""The app's own look: two colour sets, the palette and stylesheet made from them, the type scale.

Qt draws most of a Fusion window from the palette, so the palette carries
the theme and the stylesheet names only what Fusion cannot express from a
palette (a filled primary button, radii, the dashed drop zone). A rule on a
combo, spin box, slider or scroll bar would replace Fusion's drawing of its
parts — the arrows went missing in the first try — so none is written.

``apply_theme`` (below, Task 2) is the one place the palette and the sheet
are set; everything else asks ``current_tokens()``.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette

__all__ = [
    "DARK",
    "LIGHT",
    "MODES",
    "SP_4",
    "SP_8",
    "SP_12",
    "SP_16",
    "SP_24",
    "SP_32",
    "Tokens",
    "font",
    "palette",
    "stylesheet",
    "tokens_for",
]

#: What the theme preference may say; ``system`` follows the desktop.
MODES = ("system", "light", "dark")

SP_4, SP_8, SP_12, SP_16, SP_24, SP_32 = 4, 8, 12, 16, 24, 32


@dataclass(frozen=True, slots=True)
class Tokens:
    """One theme's colours, as ``#RRGGBB`` strings."""

    name: str
    window: str  # the window background
    panel: str  # lists, tables, fields (QPalette.Base)
    raised: str  # cards and rows that sit on the window
    border: str
    text: str
    secondary: str  # detail lines, placeholders, disabled text
    accent: str  # primary buttons, selection, links, focus
    on_accent: str  # text on the accent
    gold: str  # one decorative colour: the app icon, a swatch ring


LIGHT = Tokens(
    name="light",
    window="#F4F3F0",
    panel="#FFFFFF",
    raised="#FFFFFF",
    border="#DDD9D1",
    text="#1C1B1A",
    secondary="#5F5B55",
    accent="#2F5D8A",
    on_accent="#FFFFFF",
    gold="#B8891C",
)

DARK = Tokens(
    name="dark",
    window="#1C1B1A",
    panel="#262523",
    raised="#2E2C29",
    border="#3A3835",
    text="#ECE9E3",
    secondary="#A8A49C",
    accent="#7FB0E6",
    on_accent="#101418",
    gold="#D9B45B",
)

_BY_NAME = {LIGHT.name: LIGHT, DARK.name: DARK}


def tokens_for(name: str) -> Tokens:
    """The tokens called *name* (``light`` or ``dark``); KeyError for any other."""
    return _BY_NAME[name]


def palette(tokens: Tokens) -> QPalette:
    """A palette drawn entirely from *tokens*, for every colour group."""
    p = QPalette()
    role = QPalette.ColorRole
    dark = tokens.name == "dark"
    button = QColor(tokens.raised) if dark else QColor(tokens.panel)
    colours = {
        role.Window: tokens.window,
        role.WindowText: tokens.text,
        role.Base: tokens.panel,
        role.AlternateBase: tokens.window,
        role.Text: tokens.text,
        role.ButtonText: tokens.text,
        role.PlaceholderText: tokens.secondary,
        role.Link: tokens.accent,
        role.LinkVisited: tokens.accent,
        role.Highlight: tokens.accent,
        role.HighlightedText: tokens.on_accent,
        role.ToolTipBase: tokens.panel,
        role.ToolTipText: tokens.text,
        role.Mid: tokens.border,
        role.Dark: "#5A5753" if dark else "#B9B5AD",
        role.Light: "#3A3835" if dark else "#FFFFFF",
        role.Midlight: "#33312E" if dark else "#EDEAE4",
        role.Shadow: "#000000" if dark else "#8E8A83",
    }
    for colour_role, value in colours.items():
        p.setColor(colour_role, QColor(value))
    p.setColor(role.Button, button)
    disabled = QPalette.ColorGroup.Disabled
    for text_role in (role.Text, role.ButtonText, role.WindowText):
        p.setColor(disabled, text_role, QColor(tokens.secondary))
    p.setColor(disabled, role.Highlight, QColor(tokens.border))
    p.setColor(disabled, role.HighlightedText, QColor(tokens.secondary))
    return p


def _shifted(hex_value: str, *, dark: bool, amount: int = 112) -> str:
    """*hex_value* a step lighter on a dark theme, darker on a light one (for hover)."""
    colour = QColor(hex_value)
    return (colour.lighter(amount) if dark else colour.darker(amount)).name()


def stylesheet(tokens: Tokens) -> str:
    """The rules Fusion cannot take from the palette, written from *tokens*."""
    t = tokens
    dark = t.name == "dark"
    hover_primary = _shifted(t.accent, dark=dark)
    return f"""
QPushButton, QToolButton {{
    border: 1px solid {t.border};
    border-radius: 6px;
    padding: 5px 14px;
    background: palette(button);
    color: palette(button-text);
}}
QToolButton[autoRaise="true"] {{ border-color: transparent; background: transparent; }}
QPushButton:hover, QToolButton:hover {{ border-color: {t.accent}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {t.border}; }}
QPushButton:checked, QToolButton:checked {{
    background: {t.accent};
    color: {t.on_accent};
    border-color: {t.accent};
}}
QPushButton:disabled, QToolButton:disabled {{ color: {t.secondary}; border-color: {t.border}; }}
QPushButton:focus, QToolButton:focus {{ outline: none; border: 2px solid {t.accent}; padding: 4px 13px; }}
QPushButton[primary="true"] {{
    background: {t.accent};
    color: {t.on_accent};
    border: none;
    font-weight: 600;
    padding: 7px 22px;
}}
QPushButton[primary="true"]:hover {{ background: {hover_primary}; }}
QPushButton[primary="true"]:focus {{ border: 2px solid {t.text}; padding: 5px 20px; }}
QPushButton[primary="true"]:disabled {{ background: {t.border}; color: {t.secondary}; }}
QFrame[card="true"] {{
    background: {t.raised};
    border: 1px solid {t.border};
    border-radius: 10px;
}}
QFrame#dropZone {{
    background: {t.panel};
    border: 2px dashed {t.border};
    border-radius: 10px;
}}
QFrame#dropZone[dragOver="true"] {{ border: 2px solid {t.accent}; background: {t.window}; }}
QFrame[chip="true"] {{ background: {t.border}; border: none; border-radius: 11px; }}
QListWidget, QTableWidget, QScrollArea {{
    border: 1px solid {t.border};
    border-radius: 8px;
    background: {t.panel};
}}
QScrollArea[frameShape="0"] {{ border: none; border-radius: 0; background: transparent; }}
QHeaderView::section {{
    background: {t.window};
    color: {t.text};
    border: none;
    border-bottom: 1px solid {t.border};
    padding: 6px;
    font-weight: 600;
}}
QProgressBar {{ border: none; border-radius: 3px; background: {t.border}; text-align: center; }}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 3px; }}
QStatusBar {{ background: {t.window}; color: {t.text}; }}
QToolTip {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.border}; padding: 4px; }}
"""


_FONT_ROLES = ("title", "section", "body", "secondary", "clock")


def font(role: str) -> QFont:
    """The application font sized and weighted for *role*; KeyError for an unknown role.

    ``clock`` is the body font with tabular digits, so a running time does
    not jitter as the digits change (a Qt without ``QFont.setFeature``,
    before 6.7, gets the body font as it is).
    """
    if role not in _FONT_ROLES:
        raise KeyError(role)
    from PySide6.QtWidgets import QApplication

    base = QFont(QApplication.font())
    size = base.pointSizeF() if base.pointSizeF() > 0 else 10.0
    if role == "title":
        base.setPointSizeF(size * 1.5)
        base.setWeight(QFont.Weight.DemiBold)
    elif role == "section":
        base.setPointSizeF(size * 1.2)
        base.setWeight(QFont.Weight.DemiBold)
    elif role == "secondary":
        base.setPointSizeF(max(size - 1.0, 7.0))
    elif role == "clock" and hasattr(QFont, "setFeature") and hasattr(QFont, "Tag"):
        base.setFeature(QFont.Tag("tnum"), 1)
    return base
```

- [ ] **Step 4: Move the colour tests' fixtures onto the new surfaces**

In `tests/test_colors.py` replace lines 40–41:

```python
LIGHT = _palette(QColor("#F4F3F0"), QColor("#FFFFFF"))
DARK = _palette(QColor("#1C1B1A"), QColor("#262523"))
```

- [ ] **Step 5: Run the tests; adjust a token if a ratio is short**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_theme.py tests/test_colors.py -q`
Expected: PASS. If `test_the_fixed_colours_still_read_on_the_new_surfaces` or a `test_colors` case fails on the dark theme, darken `DARK.panel` one step (`#242321`) rather than touch `gui/colors.py`; if it fails on light, lighten `LIGHT.window` toward `#F6F5F2`. Record the final values in the commit message.

- [ ] **Step 6: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/theme.py tests/test_theme.py tests/test_colors.py
git commit -m "Give the app its own light and dark colours, a palette and a stylesheet made from them, and a type scale

Two token sets in the ink-and-gold family of the default look. The palette
carries the theme; the sheet names only what Fusion cannot draw from a
palette, so combos, spin boxes and sliders keep their parts. Every text
colour measures 4.5:1 on its surface, by test.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `apply_theme`, the system mode, and `Prefs.theme`

**Files:**
- Modify: `src/qurantext/gui/theme.py` (append)
- Modify: `src/qurantext/gui/prefs.py:107-125` (add the property after `language`)
- Modify: `tests/test_theme.py` (append)
- Modify: `tests/test_prefs.py:14-27` (defaults) and the round-trip test

**Interfaces:**
- Consumes: Task 1's `Tokens`, `LIGHT`, `DARK`, `MODES`, `palette`, `stylesheet`, `tokens_for`.
- Produces: `apply_theme(app: QApplication, mode: str) -> Tokens`, `current_tokens(app: QApplication | None = None) -> Tokens` (LIGHT when nothing was applied), `resolve(mode: str, app) -> Tokens`, `Prefs.theme: str` (getter returns one of `MODES`, default `"system"`; setter raises `ValueError` for anything else). Application properties `"qalun.tokens"` (the `Tokens`) and `"qalun.theme_mode"` (the mode string). `apply_theme` calls `refresh_icons` from `gui.icons` on every top-level widget when that module exists (Task 4 adds it; until then the import is guarded).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_theme.py`:

```python
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


class _Hints:
    """Stands in for QStyleHints: a scheme the test chooses, and the signal Qt would emit."""

    def __init__(self, scheme) -> None:
        self._scheme = scheme
        self._slots = []

    def colorScheme(self):  # noqa: N802 - Qt's name
        return self._scheme

    class _Signal:
        def __init__(self, hints) -> None:
            self._hints = hints

        def connect(self, slot) -> None:
            self._hints._slots.append(slot)

    @property
    def colorSchemeChanged(self):  # noqa: N802 - Qt's name
        return self._Signal(self)

    def change(self, scheme) -> None:
        self._scheme = scheme
        for slot in list(self._slots):
            slot(scheme)


@pytest.fixture()
def hints(qt_app, monkeypatch):
    stand_in = _Hints(Qt.ColorScheme.Light)
    monkeypatch.setattr(theme, "_style_hints", lambda app: stand_in)
    # An earlier apply may have connected the real hints; let this test connect the stand-in.
    qt_app.setProperty(theme._CONNECTED_PROPERTY, False)
    yield stand_in
    qt_app.setProperty(theme._CONNECTED_PROPERTY, False)
    theme.apply_theme(qt_app, "light")


def test_light_and_dark_apply_their_palette_and_sheet(qt_app, hints) -> None:
    tokens = theme.apply_theme(qt_app, "dark")
    assert tokens is theme.DARK
    assert qt_app.palette().color(QPalette.ColorRole.Window).name().upper() == theme.DARK.window
    assert theme.DARK.accent in qt_app.styleSheet()
    assert theme.current_tokens(qt_app) is theme.DARK
    assert theme.apply_theme(qt_app, "light") is theme.LIGHT
    assert qt_app.style().objectName().lower() == "fusion"


def test_system_follows_the_desktop_live(qt_app, hints) -> None:
    hints.change(Qt.ColorScheme.Dark)
    assert theme.apply_theme(qt_app, "system") is theme.DARK
    hints.change(Qt.ColorScheme.Light)
    assert theme.current_tokens(qt_app) is theme.LIGHT
    hints.change(Qt.ColorScheme.Dark)
    assert theme.current_tokens(qt_app) is theme.DARK


def test_a_fixed_theme_ignores_the_desktop(qt_app, hints) -> None:
    theme.apply_theme(qt_app, "light")
    hints.change(Qt.ColorScheme.Dark)
    assert theme.current_tokens(qt_app) is theme.LIGHT


def test_an_unknown_scheme_counts_as_light(qt_app, hints) -> None:
    hints.change(Qt.ColorScheme.Unknown)
    assert theme.apply_theme(qt_app, "system") is theme.LIGHT


def test_an_unknown_mode_is_refused(qt_app, hints) -> None:
    with pytest.raises(ValueError):
        theme.apply_theme(qt_app, "sepia")


def test_current_tokens_before_any_apply_is_light() -> None:
    assert theme.current_tokens(None) is theme.LIGHT
```

In `tests/test_prefs.py`, add to `test_defaults_on_an_empty_ini`:

```python
    assert prefs.theme == "system"
```

and append:

```python
def test_theme_round_trips_and_an_unknown_value_reads_as_system(tmp_path) -> None:
    from PySide6.QtCore import QSettings

    ini = tmp_path / "prefs.ini"
    prefs = Prefs(QSettings(str(ini), QSettings.Format.IniFormat))
    prefs.theme = "dark"
    assert Prefs(QSettings(str(ini), QSettings.Format.IniFormat)).theme == "dark"
    with pytest.raises(ValueError):
        prefs.theme = "amoled"
    ini.write_text("[General]\ntheme=amoled\n", encoding="utf-8")
    assert Prefs(QSettings(str(ini), QSettings.Format.IniFormat)).theme == "system"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_theme.py tests/test_prefs.py -q`
Expected: FAIL with `AttributeError: module 'qurantext.gui.theme' has no attribute '_style_hints'` and `AttributeError: 'Prefs' object has no attribute 'theme'`

- [ ] **Step 3: Append `apply_theme` and friends to `gui/theme.py`**

Add `"apply_theme", "current_tokens", "resolve"` to `__all__`, `from PySide6.QtCore import Qt` to the imports, and append:

```python
#: Application properties: the tokens in force and the mode they came from.
TOKENS_PROPERTY = "qalun.tokens"
MODE_PROPERTY = "qalun.theme_mode"
_CONNECTED_PROPERTY = "qalun.scheme_connected"


def _style_hints(app):
    """Qt's style hints; a seam the tests replace with a scheme of their choosing."""
    return app.styleHints()


def resolve(mode: str, app) -> Tokens:
    """The tokens *mode* means right now; ``system`` asks the desktop, Unknown counts as light."""
    if mode not in MODES:
        raise ValueError(f"Unknown theme {mode!r}; choose from {', '.join(MODES)}.")
    if mode != "system":
        return tokens_for(mode)
    hints = _style_hints(app)
    scheme = hints.colorScheme() if hasattr(hints, "colorScheme") else None
    return DARK if scheme == Qt.ColorScheme.Dark else LIGHT


def current_tokens(app=None) -> Tokens:
    """The tokens in force on *app* (the running application by default); LIGHT before any apply."""
    if app is None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
    tokens = app.property(TOKENS_PROPERTY) if app is not None else None
    return tokens if isinstance(tokens, Tokens) else LIGHT


def apply_theme(app, mode: str) -> Tokens:
    """Put *mode*'s palette and stylesheet on *app* and re-tint every window's icons.

    Fusion is set once, so the palette draws the same on every platform.
    In ``system`` mode the desktop's scheme is followed: the change signal
    is connected once per application, and the slot re-applies only while
    the mode is still ``system``.
    """
    tokens = resolve(mode, app)
    if app.style().objectName().lower() != "fusion":
        app.setStyle("Fusion")
    app.setProperty(MODE_PROPERTY, mode)
    app.setProperty(TOKENS_PROPERTY, tokens)
    app.setPalette(palette(tokens))
    app.setStyleSheet(stylesheet(tokens))
    _follow_the_desktop(app)
    _refresh_every_window(app)
    return tokens


def _follow_the_desktop(app) -> None:
    if app.property(_CONNECTED_PROPERTY):
        return
    hints = _style_hints(app)
    signal = getattr(hints, "colorSchemeChanged", None)
    if signal is None:
        return  # a Qt before 6.5: system resolves once, on apply
    signal.connect(lambda _scheme=None: _on_scheme_changed(app))
    app.setProperty(_CONNECTED_PROPERTY, True)


def _on_scheme_changed(app) -> None:
    if app.property(MODE_PROPERTY) == "system":
        apply_theme(app, "system")


def _refresh_every_window(app) -> None:
    """Re-tint the icons on every top-level widget (a no-op until ``gui.icons`` exists)."""
    try:
        from qurantext.gui.icons import refresh_icons
    except ImportError:
        return
    for widget in app.topLevelWidgets():
        refresh_icons(widget)
```

- [ ] **Step 4: Add `Prefs.theme`**

In `src/qurantext/gui/prefs.py`, add `from qurantext.gui.theme import MODES as THEME_MODES` to the imports, and after the `language` setter (line 125) add:

```python
    # -- theme ------------------------------------------------------------------

    @property
    def theme(self) -> str:
        """``system`` (follow the desktop), ``light`` or ``dark``; anything else reads as ``system``."""
        value = self._settings.value("theme", "system")
        return value if isinstance(value, str) and value in THEME_MODES else "system"

    @theme.setter
    def theme(self, value: str) -> None:
        if value not in THEME_MODES:
            raise ValueError(f"Unknown theme {value!r}; choose from {', '.join(THEME_MODES)}.")
        self._settings.setValue("theme", value)
        self._settings.sync()
```

Check `tests/test_prefs.py::test_every_key_round_trips`: if it iterates a fixed list of keys, add `("theme", "dark")` to that list.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_theme.py tests/test_prefs.py -q`
Expected: PASS

- [ ] **Step 6: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/theme.py src/qurantext/gui/prefs.py tests/test_theme.py tests/test_prefs.py
git commit -m "Apply the theme to the application, follow the desktop's scheme in System mode, and remember the choice

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Bundle the Lucide icons with their licence

**Files:**
- Create: `tools/fetch_icons.py`
- Create: `src/qurantext/assets/icons/*.svg` (31 files) and `src/qurantext/assets/icons/LICENSE`
- Create: `packaging/licenses/Lucide-LICENSE.txt`
- Modify: `THIRD_PARTY_NOTICES.md` (new section after "Amiri font")
- Modify: `tests/test_packaging_spec.py` (append)

**Interfaces:**
- Produces: the file set Task 4 reads; `tools/fetch_icons.py` with `ICON_NAMES: tuple[str, ...]` and `LUCIDE_TAG = "1.56.0"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_packaging_spec.py`:

```python
ICON_DIR = Path(__file__).resolve().parents[1] / "src" / "qurantext" / "assets" / "icons"


def test_every_interface_icon_ships_with_lucides_licence() -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from fetch_icons import ICON_NAMES

    assert len(ICON_NAMES) == 31
    for name in ICON_NAMES:
        svg = ICON_DIR / f"{name}.svg"
        assert svg.is_file(), name
        assert 'stroke="currentColor"' in svg.read_text(encoding="utf-8"), name
    assert "ISC License" in (ICON_DIR / "LICENSE").read_text(encoding="utf-8")


def test_the_third_party_notice_credits_lucide() -> None:
    text = (Path(__file__).resolve().parents[1] / "THIRD_PARTY_NOTICES.md").read_text(
        encoding="utf-8"
    )
    assert "## Lucide icons" in text
    assert "1.56.0" in text and "ISC" in text
    assert "qurantext/assets/icons/LICENSE" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_packaging_spec.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'fetch_icons'`

- [ ] **Step 3: Write the fetch tool**

```python
# tools/fetch_icons.py
"""Download the interface icons from Lucide at a pinned tag, with the licence beside them.

Run once, and again only to change the set or the tag; the files are
committed. Lucide renames icons between versions, so the tag is pinned and
every name below is checked against it.

    venv/bin/python tools/fetch_icons.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

LUCIDE_TAG = "1.56.0"
_RAW = f"https://raw.githubusercontent.com/lucide-icons/lucide/{LUCIDE_TAG}"
ICON_DIR = Path(__file__).resolve().parents[1] / "src" / "qurantext" / "assets" / "icons"
LICENCE_COPY = Path(__file__).resolve().parents[1] / "packaging" / "licenses" / "Lucide-LICENSE.txt"

#: Every icon the windows use. Add here, re-run, and name the new one in
#: ``qurantext.gui.icons.NAMES`` too (its test keeps the two lists equal).
ICON_NAMES: tuple[str, ...] = (
    "play",
    "pause",
    "skip-back",
    "skip-forward",
    "undo-2",
    "redo-2",
    "circle-check",
    "trash",
    "save",
    "download",
    "film",
    "sparkles",
    "palette",
    "image",
    "sun",
    "moon",
    "monitor",
    "refresh-cw",
    "folder-open",
    "folder",
    "x",
    "chevron-right",
    "chevron-down",
    "chevron-left",
    "mic",
    "book-open",
    "pencil",
    "link",
    "qr-code",
    "settings",
    "circle-question-mark",
)


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - a pinned GitHub URL
        return response.read()


def main() -> int:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for name in ICON_NAMES:
        data = _fetch(f"{_RAW}/icons/{name}.svg")
        if b'stroke="currentColor"' not in data:
            print(f"{name}: not a stroke icon, cannot be tinted", file=sys.stderr)
            return 1
        (ICON_DIR / f"{name}.svg").write_bytes(data)
    licence = _fetch(f"{_RAW}/LICENSE")
    (ICON_DIR / "LICENSE").write_bytes(licence)
    LICENCE_COPY.parent.mkdir(parents=True, exist_ok=True)
    LICENCE_COPY.write_bytes(licence)
    print(f"{len(ICON_NAMES)} icons from Lucide {LUCIDE_TAG} in {ICON_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run it and add the notice**

Run: `venv/bin/python tools/fetch_icons.py`
Expected: `31 icons from Lucide 1.56.0 in …/src/qurantext/assets/icons`

Insert into `THIRD_PARTY_NOTICES.md` after the "Amiri font" section:

```markdown
## Lucide icons

The window's icons are from **Lucide**, release 1.56.0,
https://github.com/lucide-icons/lucide/releases/tag/1.56.0, Copyright (c)
Lucide Icons and Contributors, licensed under the ISC License. Thirty-one SVG
files ship unmodified inside the app, the Python package and
`qalun-source.zip`, under `qurantext/assets/icons/` (in the app's folder,
`_internal/qurantext/assets/icons/`); the app recolours them when it draws
them. The licence text is beside them at `qurantext/assets/icons/LICENSE`
and in the source at `packaging/licenses/Lucide-LICENSE.txt`. The ISC
licence is compatible with the GPL-3.0-only licence of Qalun.
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_packaging_spec.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
venv/bin/ruff check tools tests && venv/bin/ruff format tools tests
git add tools/fetch_icons.py src/qurantext/assets/icons packaging/licenses/Lucide-LICENSE.txt THIRD_PARTY_NOTICES.md tests/test_packaging_spec.py
git commit -m "Bundle thirty-one Lucide icons at a pinned tag, with their ISC licence and a notice

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `gui/icons.py`: tinted, cached, mirrored, refreshable

**Files:**
- Create: `src/qurantext/gui/icons.py`
- Create: `tests/test_icons.py`
- Modify: `src/qurantext/config/preflight.py:1130-1155` (one check) and `tests/test_preflight.py:429-431`

**Interfaces:**
- Consumes: Task 1/2 `current_tokens`, `Tokens`; Task 3 files; `qurantext.config.paths.bundled_asset`.
- Produces: `NAMES: frozenset[str]`, `MIRRORED: dict[str, str]`, `ROLES = ("text", "accent", "on_accent", "secondary")`, `ICON_DIR: Path`, `icon(name: str, role: str = "text") -> QIcon` (KeyError for an unknown name or role), `set_icon(button: QAbstractButton, name: str, role: str = "text", size: int = 20) -> None` (also records the triple on the button as property `"qalun.icon"`), `refresh_icons(root: QWidget) -> int` (re-sets every recorded icon under *root*, returns how many), `clear_cache() -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_icons.py
"""Bundled icons: every name draws, takes the theme's colour, mirrors in Arabic, and is re-tinted on a switch."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from qurantext.gui import icons, theme  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from fetch_icons import ICON_NAMES  # noqa: E402


@pytest.fixture(autouse=True)
def _light(qt_app):
    theme.apply_theme(qt_app, "light")
    icons.clear_cache()
    yield
    qt_app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    theme.apply_theme(qt_app, "light")
    icons.clear_cache()


def _colours(pixmap) -> set[str]:
    image = pixmap.toImage()
    found = set()
    for y in range(image.height()):
        for x in range(image.width()):
            colour = image.pixelColor(x, y)
            if colour.alpha() > 200:
                found.add(colour.name().upper())
    return found


def test_the_module_names_exactly_the_bundled_set() -> None:
    assert icons.NAMES == frozenset(ICON_NAMES)


@pytest.mark.parametrize("name", sorted(ICON_NAMES))
def test_every_icon_draws_at_every_size(qt_app, name) -> None:
    drawn = icons.icon(name)
    for size in (16, 20, 24):
        assert not drawn.pixmap(QSize(size, size)).isNull(), size
        assert _colours(drawn.pixmap(QSize(size, size))), f"{name} drew nothing at {size}"


def test_the_role_sets_the_colour(qt_app) -> None:
    accent = icons.icon("play", "accent").pixmap(QSize(24, 24))
    assert theme.LIGHT.accent.upper() in _colours(accent)
    text = icons.icon("play", "text").pixmap(QSize(24, 24))
    assert theme.LIGHT.text.upper() in _colours(text)
    assert theme.LIGHT.accent.upper() not in _colours(text)


def test_disabled_is_drawn_in_the_secondary_colour(qt_app) -> None:
    disabled = icons.icon("save").pixmap(QSize(24, 24), QIcon.Mode.Disabled)
    assert theme.LIGHT.secondary.upper() in _colours(disabled)
    assert theme.LIGHT.text.upper() not in _colours(disabled)


def test_unknown_names_and_roles_raise(qt_app) -> None:
    with pytest.raises(KeyError):
        icons.icon("rocket")
    with pytest.raises(KeyError):
        icons.icon("play", "neon")


def test_the_cache_returns_the_same_icon_until_the_theme_changes(qt_app) -> None:
    first = icons.icon("save")
    assert icons.icon("save").cacheKey() == first.cacheKey()
    theme.apply_theme(qt_app, "dark")
    dark = icons.icon("save")
    assert dark.cacheKey() != first.cacheKey()
    assert theme.DARK.text.upper() in _colours(dark.pixmap(QSize(24, 24)))


def test_directional_icons_mirror_in_a_right_to_left_layout(qt_app) -> None:
    ltr_left = icons.icon("chevron-left").pixmap(QSize(24, 24)).toImage()
    qt_app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    icons.clear_cache()
    rtl_right = icons.icon("chevron-right").pixmap(QSize(24, 24)).toImage()
    assert rtl_right == ltr_left
    assert icons.MIRRORED["skip-back"] == "skip-forward"
    # Undo keeps its direction: its arrow means time, not reading order.
    assert "undo-2" not in icons.MIRRORED


def test_set_icon_records_the_choice_and_refresh_retints_it(qt_app) -> None:
    root = QWidget()
    button = QPushButton("Save", root)
    icons.set_icon(button, "save", size=16)
    assert button.iconSize() == QSize(16, 16)
    assert button.property("qalun.icon") == ("save", "text", 16)
    before = button.icon().cacheKey()
    theme.apply_theme(qt_app, "dark")
    assert button.icon().cacheKey() != before  # apply_theme walked the top-level widgets
    plain = QPushButton("No icon", root)
    assert icons.refresh_icons(root) == 1
    assert plain.icon().isNull()
    root.deleteLater()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_icons.py -q`
Expected: FAIL with `ImportError: cannot import name 'icons' from 'qurantext.gui'`

- [ ] **Step 3: Write `gui/icons.py`**

```python
# src/qurantext/gui/icons.py
"""The bundled Lucide icons, tinted from the theme and cached.

An SVG keeps ``stroke="currentColor"``; drawing it means replacing that
with the role's colour and rendering through QtSvg at each size and pixel
ratio. A ``QIcon`` holds pixels, not a colour role, so a theme switch
rebuilds them: ``set_icon`` records what a button asked for and
``refresh_icons`` (called by ``apply_theme`` on every window) asks again.

Icons that point along the reading direction swap for their mirror under a
right-to-left layout; undo and redo do not, their arrows mean time.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QWidget

from qurantext.config.paths import bundled_asset
from qurantext.gui.theme import Tokens, current_tokens

__all__ = [
    "ICON_DIR",
    "MIRRORED",
    "NAMES",
    "ROLES",
    "clear_cache",
    "icon",
    "refresh_icons",
    "set_icon",
]

ICON_DIR = bundled_asset("icons")

NAMES = frozenset(
    {
        "play", "pause", "skip-back", "skip-forward", "undo-2", "redo-2",
        "circle-check", "trash", "save", "download", "film", "sparkles",
        "palette", "image", "sun", "moon", "monitor", "refresh-cw",
        "folder-open", "folder", "x", "chevron-right", "chevron-down",
        "chevron-left", "mic", "book-open", "pencil", "link", "qr-code",
        "settings", "circle-question-mark",
    }
)  # fmt: skip

#: Icons that point along the reading direction, each with its mirror.
MIRRORED = {
    "chevron-right": "chevron-left",
    "chevron-left": "chevron-right",
    "skip-back": "skip-forward",
    "skip-forward": "skip-back",
}

ROLES = ("text", "accent", "on_accent", "secondary")
#: The property a button carries after ``set_icon``: ``(name, role, size)``.
ICON_PROPERTY = "qalun.icon"

_SIZES = (16, 20, 24)
_RATIOS = (1.0, 2.0)
_cache: dict[tuple[str, str, str, bool], QIcon] = {}


def clear_cache() -> None:
    _cache.clear()


def _svg(name: str) -> bytes:
    if name not in NAMES:
        raise KeyError(name)
    return (ICON_DIR / f"{name}.svg").read_bytes()


def _pixmap(svg: bytes, colour: QColor, size: int, ratio: float) -> QPixmap:
    data = svg.replace(b"currentColor", colour.name().encode("ascii"))
    renderer = QSvgRenderer(QByteArray(data))
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
    finally:
        painter.end()
    return pixmap


def _colour(tokens: Tokens, role: str) -> QColor:
    if role not in ROLES:
        raise KeyError(role)
    return QColor(getattr(tokens, role))


def _rtl() -> bool:
    app = QGuiApplication.instance()
    return app is not None and app.isRightToLeft()


def icon(name: str, role: str = "text") -> QIcon:
    """*name* drawn in the theme's *role* colour (disabled in ``secondary``), mirrored under RTL."""
    tokens = current_tokens()
    rtl = _rtl()
    key = (name, role, tokens.name, rtl)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    drawn_name = MIRRORED.get(name, name) if rtl else name
    svg = _svg(drawn_name)
    normal, disabled = _colour(tokens, role), _colour(tokens, "secondary")
    result = QIcon()
    for size in _SIZES:
        for ratio in _RATIOS:
            result.addPixmap(_pixmap(svg, normal, size, ratio), QIcon.Mode.Normal)
            result.addPixmap(_pixmap(svg, disabled, size, ratio), QIcon.Mode.Disabled)
    _cache[key] = result
    return result


def set_icon(button: QAbstractButton, name: str, role: str = "text", size: int = 20) -> None:
    """Put *name* on *button* at *size* px, and remember it for the next theme switch."""
    button.setIcon(icon(name, role))
    button.setIconSize(QSize(size, size))
    button.setProperty(ICON_PROPERTY, (name, role, size))


def refresh_icons(root: QWidget) -> int:
    """Draw again every icon ``set_icon`` put under *root*; returns how many."""
    count = 0
    for button in root.findChildren(QAbstractButton):
        recorded = button.property(ICON_PROPERTY)
        if isinstance(recorded, (tuple, list)) and len(recorded) == 3:
            name, role, size = recorded
            set_icon(button, str(name), str(role), int(size))
            count += 1
    return count
```

Also make `apply_theme` clear the cache before refreshing: in `theme._refresh_every_window`, after the import, call `clear_cache()` (import it alongside `refresh_icons`).

- [ ] **Step 4: Add the doctor's "Interface icons" check**

In `src/qurantext/config/preflight.py`, before `run_checks`:

```python
def _interface_icons() -> CheckResult:
    """Every icon the windows draw is on disk; a build without them would show blank buttons."""
    try:
        from qurantext.gui.icons import ICON_DIR, NAMES
    except ImportError as error:
        return CheckResult("Interface icons", Status.WARN, f"Qt is not installed ({error})")
    missing = sorted(name for name in NAMES if not (ICON_DIR / f"{name}.svg").is_file())
    if missing:
        return CheckResult(
            "Interface icons",
            Status.FAIL,
            f"{len(missing)} of {len(NAMES)} missing: {_joined(missing[:3])}",
            "The icons ship inside the package under assets/icons; check that assets/ is included.",
        )
    return CheckResult("Interface icons", Status.OK, f"{len(NAMES)} icons in {ICON_DIR.name}/")
```

Add `_interface_icons(),` to the list in `run_checks` right after `_title_parts(),`. In `tests/test_preflight.py::test_release_checks_include_the_new_ones` add `"Interface icons"` to the expected set.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_icons.py tests/test_theme.py tests/test_preflight.py -q`
Expected: PASS

- [ ] **Step 6: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/icons.py src/qurantext/gui/theme.py src/qurantext/config/preflight.py tests/test_icons.py tests/test_preflight.py
git commit -m "Draw the bundled icons in the theme's colours, mirror the directional ones in Arabic, and re-tint them on a switch

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `gui/widgets.py`: the four composites

**Files:**
- Create: `src/qurantext/gui/widgets.py`
- Create: `tests/test_widgets.py`

**Interfaces:**
- Consumes: `theme.font`, `theme.SP_*`, `theme.current_tokens`; `icons.icon`; `colors.warning_color`.
- Produces: `make_primary(button: QPushButton) -> QPushButton`; `SectionHeader(text: str, trailing: QWidget | None = None, parent=None)` with `.label: QLabel` and `set_text(text)`; `Card(parent=None)` (a `QFrame` with property `card=True`, 16 px margins, exposes `.body: QVBoxLayout`); `StatusChip(text: str, icon_name: str | None = None, kind: str = "neutral", parent=None)` with `.text_label`, `.icon_label`, `set_kind(kind)`, `set_text(text)`; `CHIP_KINDS = ("attention", "accent", "neutral")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_widgets.py
"""The composites every screen shares: a primary button, a section header, a card, a status chip."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtWidgets import QDialog, QFrame, QLabel, QPushButton, QWidget  # noqa: E402

from qurantext.gui import theme, widgets  # noqa: E402
from qurantext.gui.colors import warning_color  # noqa: E402


@pytest.fixture(autouse=True)
def _light(qt_app):
    theme.apply_theme(qt_app, "light")
    yield


def test_make_primary_marks_a_plain_button_without_subclassing(qt_app) -> None:
    button = QPushButton("Start")
    assert widgets.make_primary(button) is button
    assert type(button) is QPushButton
    assert button.property("primary") is True
    assert button.isDefault() is False  # not in a dialog


def test_make_primary_makes_the_dialog_default(qt_app) -> None:
    dialog = QDialog()
    button = QPushButton("OK", dialog)
    widgets.make_primary(button)
    assert button.isDefault() is True
    dialog.deleteLater()


def test_a_section_header_uses_the_section_font_and_holds_a_trailing_widget(qt_app) -> None:
    refresh = QPushButton("Refresh")
    header = widgets.SectionHeader("Your jobs", trailing=refresh)
    assert isinstance(header.label, QLabel)
    assert header.label.text() == "Your jobs"
    assert header.label.font().pointSizeF() == theme.font("section").pointSizeF()
    assert refresh.parent() is header
    header.set_text("Jobs")
    assert header.label.text() == "Jobs"


def test_a_card_is_a_framed_raised_surface(qt_app) -> None:
    card = widgets.Card()
    assert isinstance(card, QFrame)
    assert card.property("card") is True
    margins = card.body.contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (16, 16, 16, 16)
    inner = QLabel("inside")
    card.body.addWidget(inner)
    assert inner.parent() is card


def test_a_status_chip_shows_text_an_icon_and_its_kind(qt_app) -> None:
    chip = widgets.StatusChip("Needs review", icon_name="circle-check", kind="attention")
    assert chip.text_label.text() == "Needs review"
    assert not chip.icon_label.pixmap().isNull()
    assert chip.property("chip") is True
    assert chip.property("kind") == "attention"
    assert chip.text_label.palette().color(chip.text_label.foregroundRole()) == warning_color(
        chip.palette()
    )
    chip.set_kind("neutral")
    assert chip.property("kind") == "neutral"
    with pytest.raises(KeyError):
        chip.set_kind("danger")
    plain = widgets.StatusChip("Reviewed")
    assert plain.icon_label.isHidden()
    assert chip.height() >= 22
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_widgets.py -q`
Expected: FAIL with `ImportError: cannot import name 'widgets'`

- [ ] **Step 3: Write `gui/widgets.py`**

```python
# src/qurantext/gui/widgets.py
"""The few composite controls the windows share, so each looks the same everywhere.

``make_primary`` marks a plain ``QPushButton`` rather than replacing it:
every test reaches Start and Render by attribute, and they stay what they
were. The rest are small containers the stylesheet knows by a property.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from qurantext.gui import theme
from qurantext.gui.colors import warning_color
from qurantext.gui.icons import icon

__all__ = ["CHIP_KINDS", "Card", "SectionHeader", "StatusChip", "make_primary"]

CHIP_KINDS = ("attention", "accent", "neutral")


def _repolish(widget: QWidget) -> None:
    """Make the stylesheet read a property set after the widget was styled."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def make_primary(button: QPushButton) -> QPushButton:
    """Fill *button* with the accent: the one action its screen is for. In a dialog, Enter presses it."""
    button.setProperty("primary", True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if isinstance(button.window(), QDialog):
        button.setDefault(True)
    _repolish(button)
    return button


class SectionHeader(QWidget):
    """A section's title in the section font, with room for one control at its far end."""

    def __init__(self, text: str, trailing: QWidget | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SP_8)
        self.label = QLabel(text)
        self.label.setFont(theme.font("section"))
        row.addWidget(self.label)
        row.addStretch(1)
        if trailing is not None:
            trailing.setParent(self)
            row.addWidget(trailing)

    def set_text(self, text: str) -> None:
        self.label.setText(text)


class Card(QFrame):
    """A raised surface with a border and 16 px of room inside; put content in ``body``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(theme.SP_16, theme.SP_16, theme.SP_16, theme.SP_16)
        self.body.setSpacing(theme.SP_8)


class StatusChip(QFrame):
    """An icon and a word in a pill: ``attention`` (amber), ``accent`` or ``neutral``."""

    def __init__(
        self,
        text: str,
        icon_name: str | None = None,
        kind: str = "neutral",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("chip", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(22)
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SP_8, 0, theme.SP_8, 0)
        row.setSpacing(theme.SP_4)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(QSize(16, 16))
        self.icon_label.setScaledContents(True)
        self.text_label = QLabel(text)
        self.text_label.setFont(theme.font("secondary"))
        row.addWidget(self.icon_label)
        row.addWidget(self.text_label)
        self._icon_name = icon_name
        self._kind = kind
        self.set_kind(kind)

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)

    def set_kind(self, kind: str) -> None:
        if kind not in CHIP_KINDS:
            raise KeyError(kind)
        self._kind = kind
        self.setProperty("kind", kind)
        colour = self._colour()
        palette = QPalette(self.text_label.palette())
        palette.setColor(self.text_label.foregroundRole(), colour)
        self.text_label.setPalette(palette)
        self._draw_icon()
        _repolish(self)

    def _colour(self) -> QColor:
        tokens = theme.current_tokens()
        if self._kind == "attention":
            return warning_color(self.palette())
        return QColor(tokens.accent if self._kind == "accent" else tokens.secondary)

    def _draw_icon(self) -> None:
        if self._icon_name is None:
            self.icon_label.hide()
            return
        role = {"attention": "text", "accent": "accent", "neutral": "secondary"}[self._kind]
        pixmap = icon(self._icon_name, role).pixmap(QSize(16, 16))
        if self._kind == "attention":
            # The amber has no token role; tint the pixmap through a mask.
            from PySide6.QtGui import QPainter

            tinted = pixmap.copy()
            painter = QPainter(tinted)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(tinted.rect(), self._colour())
            painter.end()
            pixmap = tinted
        self.icon_label.setPixmap(pixmap)
        self.icon_label.show()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_widgets.py -q`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/widgets.py tests/test_widgets.py
git commit -m "Add the shared composites: a primary button mark, a section header, a card and a status chip

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: The app icon: SVG master, generator, window icon, packaging

**Files:**
- Create: `src/qurantext/assets/icon/qalun.svg`
- Create: `tools/make_app_icon.py`
- Create (generated, committed): `src/qurantext/assets/icon/qalun-{16,24,32,48,64,128,256,512,1024}.png`, `qalun.ico`, `qalun.icns`
- Create: `tests/test_app_icon.py`
- Modify: `src/qurantext/gui/app.py:116-130` (`main`)
- Modify: `packaging/qalun.spec:143-170` (`EXE`, `BUNDLE`) and its imports
- Modify: `tests/test_packaging_spec.py` (append)

**Interfaces:**
- Consumes: `bundled_asset`.
- Produces: `APP_ICON_PNG = bundled_asset("icon/qalun-256.png")` in `gui/app.py`; `tools/make_app_icon.py` with `SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_app_icon.py
"""The app icon: a master, every generated size, and set on the application."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "src" / "qurantext" / "assets" / "icon"
sys.path.insert(0, str(ROOT / "tools"))


def test_the_master_and_every_size_are_committed() -> None:
    from make_app_icon import SIZES

    assert (ICON_DIR / "qalun.svg").is_file()
    for size in SIZES:
        assert (ICON_DIR / f"qalun-{size}.png").is_file(), size
    assert (ICON_DIR / "qalun.ico").is_file()
    assert (ICON_DIR / "qalun.icns").is_file()


def test_the_windows_and_mac_icons_hold_the_sizes_they_need() -> None:
    from PIL import Image

    with Image.open(ICON_DIR / "qalun.ico") as ico:
        assert (256, 256) in ico.info["sizes"]
        assert (16, 16) in ico.info["sizes"]
    with Image.open(ICON_DIR / "qalun.icns") as icns:
        assert icns.size[0] >= 512
    with Image.open(ICON_DIR / "qalun-1024.png") as png:
        assert png.size == (1024, 1024)
        assert png.mode == "RGBA"


def test_the_application_carries_the_icon(qt_app) -> None:
    pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")
    from qurantext.gui.app import APP_ICON_PNG, set_app_icon

    set_app_icon(qt_app)
    assert not qt_app.windowIcon().isNull()
    assert APP_ICON_PNG.is_file()
```

Append to `tests/test_packaging_spec.py`:

```python
def test_the_spec_names_the_app_icon_for_windows_and_mac() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert "assets/icon/qalun.ico" in text or 'assets" / "icon" / "qalun.ico"' in text
    assert "assets/icon/qalun.icns" in text or 'assets" / "icon" / "qalun.icns"' in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_app_icon.py tests/test_packaging_spec.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'make_app_icon'`

- [ ] **Step 3: Draw the master**

```xml
<!-- src/qurantext/assets/icon/qalun.svg -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
  <!-- Ink square with a 22 % corner radius; the gold ayah-end roundel centred on it. -->
  <rect x="0" y="0" width="1024" height="1024" rx="225" ry="225" fill="#1C1B1A"/>
  <circle cx="512" cy="512" r="300" fill="none" stroke="#D9B45B" stroke-width="36"/>
  <circle cx="512" cy="512" r="200" fill="none" stroke="#D9B45B" stroke-width="20"/>
  <circle cx="512" cy="512" r="80" fill="#D9B45B"/>
  <!-- Eight small ticks between the rings, as the Mushaf's ayah-end mark has. -->
  <g stroke="#D9B45B" stroke-width="20" stroke-linecap="round">
    <line x1="512" y1="232" x2="512" y2="292"/>
    <line x1="512" y1="732" x2="512" y2="792"/>
    <line x1="232" y1="512" x2="292" y2="512"/>
    <line x1="732" y1="512" x2="792" y2="512"/>
    <line x1="314" y1="314" x2="356" y2="356"/>
    <line x1="710" y1="710" x2="668" y2="668"/>
    <line x1="710" y1="314" x2="668" y2="356"/>
    <line x1="314" y1="710" x2="356" y2="668"/>
  </g>
</svg>
```

- [ ] **Step 4: Write the generator and run it**

```python
# tools/make_app_icon.py
"""Render the app icon's PNG sizes, the Windows .ico and the macOS .icns from the SVG master.

Run after changing ``qalun.svg``; the outputs are committed so a build needs
no step.

    QT_QPA_PLATFORM=offscreen venv/bin/python tools/make_app_icon.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ICON_DIR = Path(__file__).resolve().parents[1] / "src" / "qurantext" / "assets" / "icon"
MASTER = ICON_DIR / "qalun.svg"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = tuple(size for size in SIZES if size <= 256)


def _render_pngs() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    renderer = QSvgRenderer(str(MASTER))
    for size in SIZES:
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        if not image.save(str(ICON_DIR / f"qalun-{size}.png"), "PNG"):
            raise SystemExit(f"could not write qalun-{size}.png")
    del app


def _pack() -> None:
    from PIL import Image

    with Image.open(ICON_DIR / "qalun-1024.png") as master:
        master = master.convert("RGBA")
        master.save(ICON_DIR / "qalun.ico", sizes=[(s, s) for s in ICO_SIZES])
        master.save(ICON_DIR / "qalun.icns")


def main() -> int:
    _render_pngs()
    _pack()
    print(f"icon written in {ICON_DIR}: {len(SIZES)} PNGs, qalun.ico, qalun.icns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python tools/make_app_icon.py`
Expected: `icon written in …: 9 PNGs, qalun.ico, qalun.icns`. Open `qalun-256.png` (the Read tool shows images) and confirm a gold roundel on an ink square.

- [ ] **Step 5: Set it on the application and in the spec**

In `src/qurantext/gui/app.py` add near the top:

```python
from qurantext.config.paths import bundled_asset

#: The window and task-bar icon; one PNG, Qt scales it for the sizes it needs.
APP_ICON_PNG = bundled_asset("icon/qalun-256.png")


def set_app_icon(app) -> None:
    """Give every window the app icon; a build that lost the file keeps Qt's blank one."""
    from PySide6.QtGui import QIcon

    if APP_ICON_PNG.is_file():
        app.setWindowIcon(QIcon(str(APP_ICON_PNG)))
```

and in `main`, right after `app.setApplicationDisplayName(_APP_NAME)`, call `set_app_icon(app)`.

In `packaging/qalun.spec`: move `import sys` up beside the other imports (remove the later `import sys  # noqa: E402`), define after `ROOT`:

```python
ICON_DIR = ROOT / "src" / "qurantext" / "assets" / "icon"
# PyInstaller takes an .ico on Windows and an .icns on macOS; Linux has no
# executable icon, so none is given there (a stray one only warns).
EXE_ICON = str(ICON_DIR / "qalun.ico") if sys.platform == "win32" else None
```

add `icon=EXE_ICON,` to the `EXE(...)` call and `icon=str(ICON_DIR / "qalun.icns"),` to the `BUNDLE(...)` call.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_app_icon.py tests/test_packaging_spec.py tests/test_entry.py -q`
Expected: PASS

- [ ] **Step 7: Lint and commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/assets/icon tools/make_app_icon.py tests/test_app_icon.py src/qurantext/gui/app.py packaging/qalun.spec tests/test_packaging_spec.py
git commit -m "Give the app an icon: a gold ayah-end roundel on ink, drawn once and packed for every platform

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Turn the theme on: `app.main` and the home footer's Theme combo

**Files:**
- Modify: `src/qurantext/gui/app.py:116-130` (`main`)
- Modify: `src/qurantext/gui/main_window.py:188-245` (`_build`, the footer) and the language section
- Modify: `src/qurantext/gui/i18n.py` (four keys in `en` near line 199 and in `ar` near line 662)
- Modify: `tests/test_gui.py` or `tests/test_home_panels.py` (wherever `MainWindow` is built; append)

**Interfaces:**
- Consumes: `theme.apply_theme`, `theme.MODES`, `Prefs.theme`.
- Produces: `MainWindow.theme_combo: QComboBox` (item data = mode string), `MainWindow.set_theme(code: str) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_home_panels.py` (it has `prefs`, `no_default_job_dirs` and `qt_app` fixtures; `MainWindow` is imported where other tests build it; if not, import it):

```python
def test_the_footer_offers_the_theme_and_applies_it(qt_app, prefs, no_default_job_dirs) -> None:
    from PySide6.QtGui import QPalette

    from qurantext.gui import theme
    from qurantext.gui.main_window import MainWindow

    theme.apply_theme(qt_app, "light")
    window = MainWindow(prefs=prefs)
    try:
        codes = [window.theme_combo.itemData(i) for i in range(window.theme_combo.count())]
        assert codes == ["system", "light", "dark"]
        assert window.theme_combo.currentData() == "system"
        window.theme_combo.setCurrentIndex(codes.index("dark"))
        window.theme_combo.activated.emit(codes.index("dark"))
        assert prefs.theme == "dark"
        assert qt_app.palette().color(QPalette.ColorRole.Window).name().upper() == theme.DARK.window
        assert window.palette().color(QPalette.ColorRole.Window).name().upper() == theme.DARK.window
        # A language switch rebuilds the footer; the choice survives it.
        assert window.set_language("ar")
        assert window.theme_combo.currentData() == "dark"
    finally:
        window.set_language("en")
        theme.apply_theme(qt_app, "light")
        window.close()
        window.deleteLater()


def test_a_theme_switch_retints_an_open_review_window(qt_app, prefs, tmp_path) -> None:
    """Review Focus 1: the strip, the rows and every icon follow the switch."""
    from PySide6.QtGui import QPalette

    from qurantext.gui import theme
    from qurantext.gui.review.player import FakePlayer
    from qurantext.gui.review.window import ReviewWindow
    from qurantext.jobs.project import CaptionCue, Project

    theme.apply_theme(qt_app, "light")
    project = Project(
        audio=str(tmp_path / "a.mp3"),
        mode="recitation",
        cards=[{"surah_num": 25, "from_ayah": 7, "to_ayah": 7, "start_time": 0.0, "end_time": 2.0,
                "word_timings": [{"text": "وَقَالُوا", "start": 0.0, "end": 1.0}]}],
        captions=[],
    )
    review = ReviewWindow(project, player=FakePlayer(10.0), prefs=prefs)
    try:
        review.show()
        before = review.save_button.icon().cacheKey()
        theme.apply_theme(qt_app, "dark")
        assert review.save_button.icon().cacheKey() != before
        assert review.strip.palette().color(QPalette.ColorRole.Window).name().upper() == theme.DARK.window
    finally:
        theme.apply_theme(qt_app, "light")
        review.close()
        review.deleteLater()
```

The second test's `save_button` icon is set in Task 9; until then it asserts a null icon's key changes, which fails. Mark it `@pytest.mark.xfail(strict=True, reason="icons land in Task 9")` now and remove the mark in Task 9. If `Project(...)` needs other fields, copy the constructor call from `tests/test_review_window.py::_project`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_home_panels.py -q -k "theme"`
Expected: FAIL with `AttributeError: 'MainWindow' object has no attribute 'theme_combo'`; the xfail is reported as expected failure.

- [ ] **Step 3: Apply the theme at start-up**

In `src/qurantext/gui/app.py::main`, after `apply_language(app, initial_language(prefs))`:

```python
    from qurantext.gui.theme import apply_theme

    apply_theme(app, prefs.theme)
```

- [ ] **Step 4: Add the strings**

In `STRINGS["en"]` after `"home.language": "Language",`:

```python
        "home.theme": "Theme",
        "home.theme.system": "System",
        "home.theme.light": "Light",
        "home.theme.dark": "Dark",
```

In `STRINGS["ar"]` after `"home.language": "اللغة",`:

```python
        "home.theme": "المظهر",
        "home.theme.system": "حسب النظام",
        "home.theme.light": "فاتح",
        "home.theme.dark": "داكن",
```

- [ ] **Step 5: Add the combo to the footer**

In `main_window.py` imports add `from qurantext.gui.theme import MODES as THEME_MODES, apply_theme`. In `_build`, before `footer.addWidget(QLabel(t("home.language")))`:

```python
        # Beside the language: the other footer-level choice until Settings exists.
        # Never disabled — a theme switch loses nothing, unlike a language switch.
        self.theme_combo = QComboBox()
        for code in THEME_MODES:
            self.theme_combo.addItem(t(f"home.theme.{code}"), code)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(self._prefs.theme))
        self.theme_combo.activated.connect(self._theme_chosen)
        footer.addWidget(QLabel(t("home.theme")))
        footer.addWidget(self.theme_combo)
        footer.addSpacing(12)
```

and after `_language_chosen`:

```python
    def _theme_chosen(self, index: int) -> None:
        self.set_theme(self.theme_combo.itemData(index))

    def set_theme(self, code: str) -> None:
        """Switch every window to *code* and remember it."""
        self._prefs.theme = code
        apply_theme(QApplication.instance(), code)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_home_panels.py tests/test_i18n.py tests/test_rtl.py tests/test_gui.py -q`
Expected: PASS (one xfail)

- [ ] **Step 7: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/app.py src/qurantext/gui/main_window.py src/qurantext/gui/i18n.py tests/test_home_panels.py
git commit -m "Turn the theme on at start-up and offer System, Light or Dark in the home footer

The Arabic strings await a native speaker's review, with the rest.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Apply it to the home panels

**Files:**
- Modify: `src/qurantext/gui/home/job_list.py:110-123` (header) and `:145-160` (action buttons)
- Modify: `src/qurantext/gui/home/new_job.py:52-62` (`_TOGGLE_STYLE`), `:124-180` (heading, drop zone, Choose, mode toggle), `:231-237` (More options), `:296-300` (Start), `:669-673` (`_set_more_options_visibility`)
- Modify: `tests/test_home_panels.py` (append)

**Interfaces:**
- Consumes: `widgets.SectionHeader`, `widgets.Card`, `widgets.make_primary`; `icons.set_icon`; `theme.font`.
- Produces: `JobListPanel.header: SectionHeader` (with `title_label` = `header.label`), `NewJobPanel.heading: SectionHeader` (with `heading_label` = `heading.label`); the drop zone stays `new_job.drop_zone` (now a `Card` with object name `dropZone`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_home_panels.py`:

```python
def test_the_home_panels_wear_the_presentation_layer(qt_app, prefs, store, no_default_job_dirs) -> None:
    from PySide6.QtWidgets import QFrame

    from qurantext.gui import theme
    from qurantext.gui.home.job_list import JobListPanel
    from qurantext.gui.widgets import Card, SectionHeader

    theme.apply_theme(qt_app, "light")
    jobs = JobListPanel(prefs)
    panel = _panel(prefs, store)
    try:
        assert isinstance(jobs.header, SectionHeader) and jobs.title_label is jobs.header.label
        assert jobs.title_label.font().pointSizeF() == theme.font("section").pointSizeF()
        for button, name in (
            (jobs.refresh_button, "refresh-cw"),
            (jobs.open_button, "folder-open"),
            (jobs.reveal_button, "folder"),
            (jobs.remove_button, "x"),
        ):
            assert button.property("qalun.icon")[0] == name, name
        assert isinstance(panel.heading, SectionHeader) and panel.heading_label is panel.heading.label
        assert isinstance(panel.drop_zone, Card) and isinstance(panel.drop_zone, QFrame)
        assert panel.drop_zone.objectName() == "dropZone"
        assert panel.choose_button.property("qalun.icon")[0] == "folder-open"
        assert not panel.choose_button.isFlat()
        assert panel.recitation_button.property("qalun.icon")[0] == "mic"
        assert panel.lecture_button.property("qalun.icon")[0] == "book-open"
        assert panel.start_button.property("primary") is True
        assert panel.more_button.property("qalun.icon")[0] == "chevron-right"
        panel.more_button.setChecked(True)
        assert panel.more_button.property("qalun.icon")[0] == "chevron-down"
        assert panel.recitation_button.styleSheet() == "" and panel.drop_zone.styleSheet() == ""
    finally:
        jobs.stop_reading()
        jobs.deleteLater()
        panel.deleteLater()


def test_a_disabled_start_still_shows_its_text(qt_app, prefs, store) -> None:
    """Review Focus 5: Start before a file is chosen is disabled, primary, and readable."""
    from PySide6.QtWidgets import QStyle, QStyleOptionButton

    from qurantext.gui import theme
    from tests.test_colors import contrast

    theme.apply_theme(qt_app, "light")
    panel = _panel(prefs, store)
    try:
        assert not panel.start_button.isEnabled()
        option = QStyleOptionButton()
        panel.start_button.initStyleOption(option)
        text = option.palette.color(option.palette.ColorGroup.Disabled, option.palette.ColorRole.ButtonText)
        assert contrast(text, option.palette.color(option.palette.ColorRole.Window)) >= 4.5
        assert ("QPushButton[primary=\"true\"]:disabled" in qt_app.styleSheet())
    finally:
        panel.deleteLater()
```

Check the existing test at `tests/test_home_panels.py:936` (`panel.heading_label.text() == "New job"`) and the RTL test `test_more_options_points_the_way_arabic_reads` (line 254 of `tests/test_rtl.py`): the latter reads `more_button.arrowType()`. Change that assertion to read the icon name: `assert panel.more_button.property("qalun.icon")[0] == "chevron-right"` in Arabic too (the icon module mirrors it on draw), and keep the open state asserting `"chevron-down"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_home_panels.py -q -k "presentation or disabled_start"`
Expected: FAIL with `AttributeError: 'JobListPanel' object has no attribute 'header'`

- [ ] **Step 3: Job list header and buttons**

In `job_list.py` imports add `from qurantext.gui.icons import set_icon` and `from qurantext.gui.widgets import SectionHeader`. Replace lines 113–121 (the `header` layout through `layout.addLayout(header)`) with:

```python
        self.refresh_button = QPushButton(t("home.refresh"))
        self.refresh_button.clicked.connect(self.refresh)
        set_icon(self.refresh_button, "refresh-cw", size=16)
        self.header = SectionHeader(t("home.jobs"), trailing=self.refresh_button)
        self.title_label = self.header.label
        layout.addWidget(self.header)
```

After the three action buttons are created (`self.open_button`, `self.reveal_button`, `self.remove_button`) add:

```python
        set_icon(self.open_button, "folder-open", size=16)
        set_icon(self.reveal_button, "folder", size=16)
        set_icon(self.remove_button, "x", size=16)
```

- [ ] **Step 4: New-job heading, drop zone, Choose, mode toggle, More options, Start**

In `new_job.py`: delete `_TOGGLE_STYLE` (lines 52–62) and the `for button in (...): button.setStyleSheet(_TOGGLE_STYLE)` loop. Add imports `from qurantext.gui.icons import set_icon` and `from qurantext.gui.widgets import Card, SectionHeader, make_primary`. Replace the heading block (lines 129–133) with:

```python
        self.heading = SectionHeader(t("home.new_job"))
        self.heading_label = self.heading.label
        layout.addWidget(self.heading)
```

Replace the drop zone creation through `drop_layout.setSpacing(4)` with:

```python
        # A card with a dashed rule: the sheet knows it by its object name, and
        # lights it while an accepted drag is over it (the ``dragOver`` property).
        self.drop_zone = Card()
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setFixedHeight(_DROP_ZONE_HEIGHT)
        self.drop_zone.setProperty("dragOver", False)
        drop_layout = self.drop_zone.body
        drop_layout.setContentsMargins(12, 8, 12, 8)
        drop_layout.setSpacing(4)
```

Replace the Choose button's `setFlat`, `setCursor` and `setStyleSheet` lines with:

```python
        set_icon(self.choose_button, "folder-open", size=16)
```

After the two mode buttons are created add:

```python
        set_icon(self.recitation_button, "mic", size=16)
        set_icon(self.lecture_button, "book-open", size=16)
```

Replace `self.more_button.setArrowType(self._more_arrow(open_=False))` (line 236) with `set_icon(self.more_button, "chevron-right", size=16)`, delete `_more_arrow`, and make `_set_more_options_visibility` read:

```python
    def _set_more_options_visibility(self, open_: bool) -> None:
        self.more_group.setVisible(open_)
        # Down when the options show; else along the reading direction (the
        # icon module mirrors it in Arabic).
        set_icon(self.more_button, "chevron-down" if open_ else "chevron-right", size=16)
        self._show_engine_notes()
```

After `self.start_button.setDefault(True)` add `make_primary(self.start_button)`.

Also keep `_set_drag_over` as it is: it already re-polishes the zone.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_home_panels.py tests/test_rtl.py tests/test_gui.py -q`
Expected: PASS (the Task 7 xfail remains)

- [ ] **Step 6: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/home tests/test_home_panels.py tests/test_rtl.py
git commit -m "Dress the home window: section headers, a carded drop zone, icons on every button and a primary Start

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Apply it to the review window, the Look panel and the dialogs

**Files:**
- Modify: `src/qurantext/gui/review/window.py:276-330` (toolbar), `:380-395` (transport), `:615-625` (`_on_playing_changed`)
- Modify: `src/qurantext/gui/review/look_panel.py:308-318` (title), `:349-356` (Customise toggle), `:390-430` (image, default, reset buttons), `:452-460` (`_customise_arrow`, `_toggle_customise`)
- Modify: `src/qurantext/gui/review/export_dialog.py:117-120`, `src/qurantext/gui/review/ayah_picker.py:154-160`, `src/qurantext/gui/review/episode_dialog.py:391-398`
- Modify: `tests/test_review_window.py`, `tests/test_review_widgets.py`, `tests/test_rtl.py` (append); `tests/test_home_panels.py` (remove the Task 7 xfail mark)

**Interfaces:**
- Consumes: `icons.set_icon`, `widgets.make_primary`, `widgets.SectionHeader`, `theme.font`.
- Produces: `LookPanel.header: SectionHeader`; nothing else new by name.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_review_window.py` (use its `_window(qt_app, tmp_path)` helper):

```python
def test_the_review_window_wears_the_presentation_layer(qt_app, tmp_path) -> None:
    from qurantext.gui import theme

    theme.apply_theme(qt_app, "light")
    window = _window(qt_app, tmp_path)
    try:
        expected = {
            window.save_button: "save",
            window.undo_button: "undo-2",
            window.redo_button: "redo-2",
            window.reviewed_button: "circle-check",
            window.remove_button: "trash",
            window.export_button: "download",
            window.episode_button: "sparkles",
            window.render_button: "film",
            window.play_button: "play",
        }
        for button, name in expected.items():
            assert button.property("qalun.icon")[0] == name, name
        assert window.render_button.property("primary") is True
        assert window.time_label.font().pointSizeF() == theme.font("clock").pointSizeF()
        window.player.play()
        assert window.play_button.property("qalun.icon")[0] == "pause"
        window.player.pause()
        assert window.play_button.property("qalun.icon")[0] == "play"
        assert window.look_panel.header.label.text() == "Look"
        assert window.look_panel.customise_toggle.property("qalun.icon")[0] == "chevron-right"
        window.look_panel.customise_toggle.setChecked(True)
        assert window.look_panel.customise_toggle.property("qalun.icon")[0] == "chevron-down"
        assert window.look_panel.image_button.property("qalun.icon")[0] == "image"
        assert window.look_panel.default_button.property("qalun.icon")[0] == "circle-check"
        assert window.look_panel.reset_button.property("qalun.icon")[0] == "refresh-cw"
        assert window.selection_bar.snap_button.icon().isNull()  # no icons on the nudge row
    finally:
        window.close()
        window.deleteLater()


def test_the_dialogs_confirming_buttons_are_primary(qt_app, tmp_path) -> None:
    from qurantext.gui.review.ayah_picker import AyahPicker
    from qurantext.gui.review.export_dialog import ExportDialog

    window = _window(qt_app, tmp_path)
    try:
        export = ExportDialog(window.session, window)
        assert export._go_button.property("primary") is True and export._go_button.isDefault()
        export.deleteLater()
        picker = AyahPicker(window, surah=25, from_ayah=7, to_ayah=11, db_path=QURAN_DB_PATH)
        assert picker.ok_button.property("primary") is True and picker.ok_button.isDefault()
        picker.deleteLater()
    finally:
        window.close()
        window.deleteLater()
```

(`QURAN_DB_PATH`: import from `qurantext.config.paths` if the module does not already; the episode dialog's OK is covered by the existing episode tests plus the same two assertions added to one of them in `tests/test_episode.py` if it builds the dialog, else skip it there.)

Append to `tests/test_rtl.py` (its fixtures put the whole test in Arabic):

```python
def test_mirrored_chevrons_survive_a_theme_switch(qt_app, review_window) -> None:
    """Review Focus 3: a switch rebuilds the icons; the Arabic ones stay mirrored."""
    from PySide6.QtCore import QSize

    from qurantext.gui import icons, theme

    toggle = review_window.look_panel.customise_toggle
    assert toggle.property("qalun.icon")[0] == "chevron-right"
    theme.apply_theme(qt_app, "dark")
    try:
        rtl = toggle.icon().pixmap(QSize(16, 16)).toImage()
        ltr_left = icons.icon("chevron-left").pixmap(QSize(16, 16)).toImage()
        # Under RTL, "chevron-right" is drawn as chevron-left; both come from the same cache now.
        assert rtl == ltr_left
    finally:
        theme.apply_theme(qt_app, "light")
```

Remove the `xfail` mark from `test_a_theme_switch_retints_an_open_review_window` in `tests/test_home_panels.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_window.py tests/test_rtl.py tests/test_home_panels.py -q -k "presentation or primary or chevrons or retints"`
Expected: FAIL with `TypeError: 'NoneType' object is not subscriptable` (no `qalun.icon` property yet)

- [ ] **Step 3: The review toolbar, transport and clock**

In `review/window.py` imports add `from qurantext.gui.icons import set_icon`, `from qurantext.gui.widgets import make_primary`, `from qurantext.gui import theme`. In `_build`, after the toolbar buttons are created (before `buttons = (...)`):

```python
        for button, name in (
            (self.save_button, "save"),
            (self.undo_button, "undo-2"),
            (self.redo_button, "redo-2"),
            (self.reviewed_button, "circle-check"),
            (self.remove_button, "trash"),
            (self.export_button, "download"),
            (self.episode_button, "sparkles"),
            (self.render_button, "film"),
        ):
            set_icon(button, name)
        make_primary(self.render_button)
```

In `_build_timeline`, after `self.play_button = QPushButton(t("review.play"))` add `set_icon(self.play_button, "play")`; after `self.time_label = QLabel(clock(0.0))` add `self.time_label.setFont(theme.font("clock"))`. In `_on_playing_changed`, after the `setText` line add `set_icon(self.play_button, "pause" if playing else "play")`.

- [ ] **Step 4: The Look panel**

In `look_panel.py` imports add `from qurantext.gui.icons import set_icon` and `from qurantext.gui.widgets import SectionHeader`. Replace the title block (lines 311–316) with:

```python
        self.header = SectionHeader(t("look.title"))
        column.addWidget(self.header)
```

Replace `self.customise_toggle.setArrowType(self._customise_arrow(open_=False))` with `set_icon(self.customise_toggle, "chevron-right", size=16)`; delete `_customise_arrow`; make `_toggle_customise`:

```python
    def _toggle_customise(self, open_: bool) -> None:
        self.customise_box.setVisible(open_)
        set_icon(self.customise_toggle, "chevron-down" if open_ else "chevron-right", size=16)
```

After `self.image_button`, `self.default_button` and `self.reset_button` are created add, respectively, `set_icon(self.image_button, "image", size=16)`, `set_icon(self.default_button, "circle-check", size=16)`, `set_icon(self.reset_button, "refresh-cw", size=16)`.

- [ ] **Step 5: The dialogs**

- `export_dialog.py`: after `self._go_button.setDefault(True)` add `make_primary(self._go_button)` (import from `qurantext.gui.widgets`).
- `ayah_picker.py`: after `self.ok_button: QPushButton = buttons.button(...)` add `make_primary(self.ok_button)`.
- `episode_dialog.py`: after `self.ok_button.setDefault(True)` add `make_primary(self.ok_button)`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_window.py tests/test_review_widgets.py tests/test_rtl.py tests/test_home_panels.py tests/test_episode.py tests/test_export.py -q`
Expected: PASS

- [ ] **Step 7: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/review tests/test_review_window.py tests/test_rtl.py tests/test_home_panels.py
git commit -m "Dress the review window and its dialogs: icons on the toolbar and transport, a primary Render, the clock in tabular digits

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: The screenshot tool, the README line, and the whole suite

**Files:**
- Create: `tools/screenshots.py`
- Create: `tests/test_screenshots_tool.py`
- Modify: `README.md` (the "The window" section: one sentence on Theme)
- Modify: `docs/release-checklist.md` (one item: look at the screenshots in both themes)

**Interfaces:**
- Consumes: everything above.
- Produces: `tools/screenshots.py` with `shoot(out_dir: Path, *, themes=("light", "dark"), languages=("en", "ar")) -> list[Path]` and a `main(argv)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_screenshots_tool.py
"""The phase-review screenshots: every screen, both themes, both languages, into a folder."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


def test_the_tool_writes_one_image_per_screen_theme_and_language(qt_app, tmp_path, no_default_job_dirs) -> None:
    from screenshots import shoot

    written = shoot(tmp_path, themes=("light",), languages=("en",))
    names = {path.name for path in written}
    assert {"home-en-light.png", "review-recitation-en-light.png", "export-en-light.png",
            "ayah-picker-en-light.png", "episode-en-light.png"} <= names
    for path in written:
        assert path.stat().st_size > 1000, path.name
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_screenshots_tool.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'screenshots'`

- [ ] **Step 3: Write the tool**

```python
# tools/screenshots.py
"""Render every window and dialog offscreen, light and dark, English and Arabic, as PNGs.

For the phase reviews: run it before and after a visual change and look at
the pairs. It builds its own project from the Al-Furqan words so it needs
no media on disk; with ``--audio`` and ``--match`` it opens a real job.

    QT_QPA_PLATFORM=offscreen venv/bin/python tools/screenshots.py out/shots
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QCoreApplication, QEvent, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

_CARD = {
    "surah_num": 25, "surah_name": "الفرقان", "from_ayah": 7, "to_ayah": 7,
    "start_time": 0.0, "end_time": 4.0,
    "word_timings": [
        {"text": "وَقَالُوا", "start": 0.0, "end": 1.0},
        {"text": "مَالِ", "start": 1.0, "end": 1.6},
        {"text": "هَٰذَا", "start": 1.6, "end": 2.3},
        {"text": "الرَّسُولِ", "start": 2.3, "end": 4.0},
    ],
}  # fmt: skip


def _spin(ms: int) -> None:
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.005)


def _grab(widget: QWidget, path: Path) -> Path:
    widget.show()
    _spin(300)
    widget.grab().save(str(path))
    return path


def _project(tmp: Path, mode: str):
    from qurantext.jobs.project import CaptionCue, Project

    captions = []
    if mode == "lecture":
        captions = [CaptionCue(start=4.0, end=8.0, text="وهم يملكون عقلا", words=[])]
    return Project(audio=str(tmp / "recording.mp3"), mode=mode, cards=[dict(_CARD)], captions=captions)


def shoot(out_dir: Path, *, themes=("light", "dark"), languages=("en", "ar")) -> list[Path]:
    from qurantext.gui import theme
    from qurantext.gui.language import apply_language
    from qurantext.gui.main_window import MainWindow
    from qurantext.gui.prefs import Prefs
    from qurantext.gui.review.ayah_picker import AyahPicker
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.player import FakePlayer
    from qurantext.gui.review.window import ReviewWindow

    app = QApplication.instance() or QApplication(sys.argv)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for language in languages:
        for name in themes:
            apply_language(app, language)
            theme.apply_theme(app, name)
            tag = f"{language}-{name}"
            ini = out_dir / f"prefs-{tag}.ini"
            prefs = Prefs(QSettings(str(ini), QSettings.Format.IniFormat))
            home = MainWindow(prefs=prefs)
            home.resize(1024, 680)
            _spin(300)
            written.append(_grab(home, out_dir / f"home-{tag}.png"))
            home.close()
            home.deleteLater()
            for mode in ("recitation", "lecture"):
                review = ReviewWindow(_project(out_dir, mode), player=FakePlayer(60.0), prefs=prefs)
                review.resize(1280, 800)
                review.seek(1.2)
                written.append(_grab(review, out_dir / f"review-{mode}-{tag}.png"))
                if mode == "recitation":
                    export = ExportDialog(review.session, review)
                    written.append(_grab(export, out_dir / f"export-{tag}.png"))
                    export.close()
                    picker = AyahPicker(review, surah=25, from_ayah=7, to_ayah=11)
                    written.append(_grab(picker, out_dir / f"ayah-picker-{tag}.png"))
                    picker.close()
                else:
                    episode = EpisodeDialog(review.session, prefs=prefs, parent=review)
                    written.append(_grab(episode, out_dir / f"episode-{tag}.png"))
                    episode.close()
                review._closed = True
                review.close()
                review.deleteLater()
            _spin(100)
    apply_language(app, "en")
    theme.apply_theme(app, "light")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--themes", nargs="+", default=("light", "dark"))
    parser.add_argument("--languages", nargs="+", default=("en", "ar"))
    args = parser.parse_args(argv)
    paths = shoot(args.out_dir, themes=tuple(args.themes), languages=tuple(args.languages))
    print(f"{len(paths)} images in {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

If `Project(...)` requires fields beyond `audio, mode, cards, captions` (check `jobs/project.py:140-170`), pass them as the review-window tests do. The ayah picker's `db_path` default is the real store; `ensure_quran_db` builds it on first use, which the tests' `store` fixture also does.

- [ ] **Step 4: Run the tool and the test; look at the images**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python tools/screenshots.py output/shots-phase-a`
Expected: `20 images in output/shots-phase-a`. Open `home-en-light.png`, `home-en-dark.png`, `review-lecture-en-dark.png`, `home-ar-light.png` with the Read tool and confirm: primary Start and Render filled in blue, icons on every listed button, warm surfaces in both themes, mirrored chevrons in Arabic, combo and spin arrows intact. Then: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_screenshots_tool.py -q` → PASS. (`output/` is git-ignored; do not add the images.)

- [ ] **Step 5: README and checklist**

In `README.md`, in "The window" section, after the sentence on English and Arabic, add:

```markdown
The window follows the desktop's light or dark scheme; **Theme** in the footer
pins it to Light or Dark.
```

In `docs/release-checklist.md`, add one item under the hands-on checks:

```markdown
- [ ] Run `QT_QPA_PLATFORM=offscreen venv/bin/python tools/screenshots.py output/shots` and look at every image in both themes and both languages: primary buttons filled, icons on every button, nothing unreadable.
```

- [ ] **Step 6: Run the whole suite and the linters**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q -x --ignore=tests/test_local_engine_slow.py`
Expected: every test passes (2 113 before this phase plus the new ones). Then `venv/bin/ruff check src tests tools && venv/bin/ruff format --check src tests tools` → clean.

- [ ] **Step 7: Commit**

```bash
git add tools/screenshots.py tests/test_screenshots_tool.py README.md docs/release-checklist.md
git commit -m "Keep the phase-review screenshots as a tool, and say in the README that the window has a theme

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

- Spec §3.1 tokens, palette, fonts, spacing → Task 1; `apply_theme`, system mode, properties, `Prefs.theme` → Task 2; §3.2 sheet → Task 1 (with the Fusion-widget exclusion test); §3.3 icons, mirroring, refresh, doctor line → Tasks 3–4; §3.4 composites → Task 5; §3.5 footer combo and strings → Task 7; §3.6 app icon, `app.main`, spec → Task 6; §3.7 application table → Tasks 8–9 (home, review, Look, dialogs) and Task 10 (screenshot tool); §5 error handling → Task 2 (unknown scheme, old Qt), Task 4 (unknown name), Task 6 (missing PNG keeps Qt's icon), Task 2/7 (unknown pref value); §6 tests → each task; §7 licensing → Task 3.
- Names used across tasks: `theme.apply_theme / current_tokens / font / MODES / LIGHT / DARK / tokens_for`, `icons.set_icon / icon / refresh_icons / clear_cache / NAMES / MIRRORED`, `widgets.make_primary / SectionHeader / Card / StatusChip`, property strings `"primary"`, `"card"`, `"chip"`, `"kind"`, `"dragOver"`, `"qalun.icon"`, `"qalun.tokens"`, `"qalun.theme_mode"` — consistent throughout.
- The spec's icon names `check-circle`, `trash-2`, `circle-help` are `circle-check`, `trash`, `circle-question-mark` at Lucide 1.56.0; the spec is amended in the same commit as this plan.
- Review Focus items 1–5 each have a test in Tasks 7, 2, 9, 2 and 8.

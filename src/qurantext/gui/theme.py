"""The app's own look: two colour sets, the palette and stylesheet made from them, the type scale.

Qt draws most of a Fusion window from the palette, so the palette carries
the theme and the stylesheet names only what Fusion cannot express from a
palette (a filled primary button, radii, the dashed drop zone). A rule on a
combo, spin box, slider or scroll bar would replace Fusion's drawing of its
parts — the arrows went missing in the first try — so none is written. The
progress bar is left to Fusion too: under a rule its label is drawn in one
colour and vanished over the chunk, where Fusion draws it in two.

``apply_theme`` (below, Task 2) is the one place the palette and the sheet
are set; everything else asks ``current_tokens()``.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
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
    "apply_theme",
    "current_tokens",
    "font",
    "palette",
    "resolve",
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
    border="#C9C5BC",
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
    border="#47443F",
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
    padding: 5px 10px;
    background: palette(button);
    color: palette(button-text);
}}
QToolButton[autoRaise="true"] {{
    border-color: transparent;
    background: transparent;
    padding: 2px 4px;
}}
QPushButton:hover, QToolButton:hover {{ border-color: {t.accent}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {t.border}; }}
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
QToolButton[swatch="true"]:checked:focus {{ border-color: {t.accent}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {t.secondary}; border-color: {t.border}; }}
QToolButton[swatch="true"]:disabled {{ border-color: transparent; }}
QPushButton[segment="true"]:checked:disabled, QToolButton[swatch="true"]:checked:disabled {{
    background: {t.panel};
    color: {t.secondary};
    border: 1px solid {t.accent};
}}
QPushButton:focus, QToolButton:focus {{ outline: none; border: 2px solid {t.accent}; padding: 4px 9px; }}
QToolButton[autoRaise="true"]:focus {{ padding: 1px 3px; }}
QPushButton[primary="true"] {{
    background: {t.accent};
    color: {t.on_accent};
    border: none;
    font-weight: 600;
    padding: 7px 18px;
}}
QPushButton[primary="true"]:hover {{ background: {hover_primary}; }}
QPushButton[primary="true"]:focus {{ border: 2px solid {t.text}; padding: 5px 16px; }}
QPushButton[primary="true"]:disabled {{
    background: {t.panel};
    color: {t.secondary};
    border: 1px solid {t.border};
    padding: 6px 17px;
}}
QPushButton[row="true"] {{
    text-align: left;
    background: transparent;
    border: 1px solid transparent;
    padding: 4px 6px;
}}
QPushButton[row="true"]:hover {{ background: {t.raised}; border-color: {t.border}; }}
QPushButton[row="true"]:focus {{ background: {t.raised}; border: 2px solid {t.accent}; padding: 3px 5px; }}
QPushButton[quiet="true"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {t.accent};
}}
QPushButton[quiet="true"]:hover {{ background: {t.raised}; border-color: transparent; }}
QPushButton[quiet="true"]:pressed {{ background: {t.border}; }}
QPushButton[quiet="true"]:focus {{ border: 2px solid {t.accent}; padding: 4px 9px; }}
QPushButton[quiet="true"]:disabled {{ color: {t.secondary}; }}
QLabel[placeholder="true"] {{ border: 2px dashed {t.border}; border-radius: 6px; background: transparent; }}
QFrame[card="true"] {{
    background: {t.raised};
    border: 1px solid {t.border};
    border-radius: 10px;
}}
QFrame[card="true"][empty="true"] {{ border: none; background: {t.border}; border-radius: 2px; }}
QFrame[card="true"][selected="true"] {{ border: 2px solid {t.accent}; }}
QFrame#dropZone {{
    background: {t.panel};
    border: 2px dashed {t.border};
    border-radius: 10px;
}}
QFrame#dropZone[dragOver="true"] {{ border: 2px solid {t.accent}; background: {t.window}; }}
QFrame[separator="true"] {{ color: {t.border}; }}
QFrame[chip="true"] {{ background: {t.window}; border: 1px solid {t.border}; border-radius: 11px; }}
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


#: Application properties: the tokens in force and the mode they came from.
TOKENS_PROPERTY = "qalun.tokens"
MODE_PROPERTY = "qalun.theme_mode"
_CONNECTED_PROPERTY = "qalun.scheme_connected"
_FUSION_PROPERTY = "qalun.fusion_set"


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
    if not app.property(_FUSION_PROPERTY):
        # Not asked of app.style(): once a sheet is set that is Qt's sheet proxy, never "fusion".
        app.setStyle("Fusion")
        app.setProperty(_FUSION_PROPERTY, True)
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
        from qurantext.gui.icons import clear_cache, refresh_icons
    except ImportError:
        return
    clear_cache()
    for widget in app.topLevelWidgets():
        refresh_icons(widget)

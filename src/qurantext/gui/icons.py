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
        "settings", "circle-question-mark", "upload", "file-music", "circle-alert",
        "triangle-alert",
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
_cache: dict[tuple[str, str, str | None, str, bool], QIcon] = {}


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


def icon(name: str, role: str = "text", on_role: str | None = None) -> QIcon:
    """*name* drawn in the theme's *role* colour (disabled in ``secondary``), mirrored under RTL.

    *on_role* is for a checkable button the sheet fills when checked: its
    ``On`` state is drawn in that colour, so the icon reads on the fill as
    the label beside it does. Without it the ``On`` state is the ``Off`` one.
    """
    tokens = current_tokens()
    rtl = _rtl()
    key = (name, role, on_role, tokens.name, rtl)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    drawn_name = MIRRORED.get(name, name) if rtl else name
    svg = _svg(drawn_name)
    normal, disabled = _colour(tokens, role), _colour(tokens, "secondary")
    checked = _colour(tokens, on_role) if on_role is not None else None
    result = QIcon()
    for size in _SIZES:
        for ratio in _RATIOS:
            result.addPixmap(_pixmap(svg, normal, size, ratio), QIcon.Mode.Normal)
            dimmed = _pixmap(svg, disabled, size, ratio)
            result.addPixmap(dimmed, QIcon.Mode.Disabled)
            if checked is not None:
                on = QIcon.State.On
                result.addPixmap(_pixmap(svg, checked, size, ratio), QIcon.Mode.Normal, on)
                # A checked button that is disabled loses its fill (the sheet), so not its grey.
                result.addPixmap(dimmed, QIcon.Mode.Disabled, on)
    _cache[key] = result
    return result


def set_icon(
    button: QAbstractButton,
    name: str,
    role: str = "text",
    size: int = 20,
    on_role: str | None = None,
) -> None:
    """Put *name* on *button* at *size* px, and remember it for the next theme switch.

    The record is ``(name, role, size)``, with *on_role* appended when given.
    """
    button.setIcon(icon(name, role, on_role))
    button.setIconSize(QSize(size, size))
    record = (name, role, size) if on_role is None else (name, role, size, on_role)
    button.setProperty(ICON_PROPERTY, record)


def refresh_icons(root: QWidget) -> int:
    """Draw again every icon ``set_icon`` put under *root*; returns how many."""
    count = 0
    for button in root.findChildren(QAbstractButton):
        recorded = button.property(ICON_PROPERTY)
        if isinstance(recorded, (tuple, list)) and len(recorded) in (3, 4):
            name, role, size = recorded[:3]
            on_role = str(recorded[3]) if len(recorded) == 4 else None
            set_icon(button, str(name), str(role), int(size), on_role)
            count += 1
    return count

# src/qurantext/core/looks.py
"""A video's look: its colours and its background, as one value.

The renderer used to read thirteen module constants. A ``Look`` carries the
same thirteen colours plus the background behind the card, and every render
call receives one, so the review window's preview and an export running at the
same moment can each draw their own. ``NIGHT_GOLD`` is exactly the old
constants, which is why a project that never chose a look renders as before.

No Qt here: the renderer and the jobs use this, and they import no Qt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

__all__ = [
    "BACKGROUND_KINDS",
    "COLOUR_FIELDS",
    "DEFAULT_PRESET",
    "EDITABLE_COLOURS",
    "IMAGE_SUFFIXES",
    "MAX_BLUR",
    "MAX_DIM",
    "MIN_CONTRAST",
    "NIGHT_GOLD",
    "PATTERN_KINDS",
    "PRESETS",
    "RGBA",
    "Background",
    "Look",
    "composite",
    "contrast_ratio",
    "look_from_style",
    "merge_style",
    "readability_warnings",
]

RGBA = tuple[int, int, int, int]

PATTERN_KINDS = ("pattern_stars", "pattern_lattice", "pattern_arches")
BACKGROUND_KINDS = ("solid", "gradient", *PATTERN_KINDS, "image")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
MAX_DIM = 0.8
MAX_BLUR = 20.0
#: WCAG 2.x minimum for normal text.
MIN_CONTRAST = 4.5
DEFAULT_PRESET = "night_gold"

#: The colours the Customise section offers; the rest follow the preset. Every
#: text colour the readability check can name is here, so a warning can always
#: be acted on.
EDITABLE_COLOURS = (
    "body_text",
    "highlight_word",
    "header_text",
    "placeholder_text",
    "card",
    "caption_text",
    "caption_active",
)
#: Text drawn on the card, and text drawn on the caption strip: what the
#: readability check measures. Dimmed and debug text are dim on purpose.
_CARD_TEXT = ("header_text", "body_text", "highlight_word", "placeholder_text")
_CAPTION_TEXT = ("caption_text", "caption_active")


@dataclass(frozen=True, slots=True)
class Background:
    """What fills the frame behind the card.

    ``colour`` is the solid colour, the gradient's top, or a pattern's ground;
    ``colour2`` is the gradient's bottom or a pattern's line colour. ``dim``
    (0–0.8) lays black over it; ``blur`` (0–20) is a Gaussian radius of
    ``blur × frame_height / 1000`` pixels.
    """

    kind: str
    colour: RGBA
    colour2: RGBA
    image: Path | None = None
    dim: float = 0.0
    blur: float = 0.0


@dataclass(frozen=True, slots=True)
class Look:
    frame_bg: RGBA
    card: RGBA
    card_border: RGBA
    header_text: RGBA
    body_text: RGBA
    highlight_word: RGBA
    subtle: RGBA
    debug_text: RGBA
    placeholder_text: RGBA
    caption_bg: RGBA
    caption_text: RGBA
    caption_active: RGBA
    caption_upcoming: RGBA
    background: Background
    base_preset: str = DEFAULT_PRESET

    @property
    def is_preset(self) -> bool:
        return PRESETS.get(self.base_preset) == self

    def to_dict(self, relative_to: Path | None = None) -> dict[str, Any]:
        bg = self.background
        return {
            "preset": self.base_preset,
            "colours": {name: _hex(getattr(self, name)) for name in COLOUR_FIELDS},
            "background": {
                "kind": bg.kind,
                "colour": _hex(bg.colour),
                "colour2": _hex(bg.colour2),
                "image": _store_path(bg.image, relative_to) if bg.image else None,
                "dim": round(bg.dim, 3),
                "blur": round(bg.blur, 3),
            },
        }

    @classmethod
    def from_dict(cls, data: Any, *, base_dir: Path | None = None) -> Look:
        if not isinstance(data, dict):
            return NIGHT_GOLD
        preset_name = data.get("preset")
        base = PRESETS.get(preset_name) if isinstance(preset_name, str) else None
        if base is None:
            base = NIGHT_GOLD
        colours = data.get("colours") if isinstance(data.get("colours"), dict) else {}
        updates = {
            name: parsed
            for name in COLOUR_FIELDS
            if (parsed := _parse_hex(colours.get(name))) is not None
        }
        background = _parse_background(data.get("background"), base.background, base_dir)
        return replace(base, **updates, background=background)


def _parse_background(data: Any, fallback: Background, base_dir: Path | None) -> Background:
    if not isinstance(data, dict):
        return fallback
    kind = data.get("kind")
    if kind not in BACKGROUND_KINDS:
        return fallback
    image = None
    if kind == "image":
        raw = data.get("image")
        if not isinstance(raw, str) or not raw:
            return fallback
        try:
            image = _resolve_path(raw, base_dir)
        except (OSError, ValueError, RuntimeError):
            # "~nosuchuser/…", a NUL byte, a symlink loop: junk opens as the preset.
            return fallback
    return Background(
        kind=kind,
        colour=_parse_hex(data.get("colour")) or fallback.colour,
        colour2=_parse_hex(data.get("colour2")) or fallback.colour2,
        image=image,
        dim=_clamped(data.get("dim"), 0.0, MAX_DIM, fallback.dim),
        blur=_clamped(data.get("blur"), 0.0, MAX_BLUR, fallback.blur),
    )


def _hex(colour: RGBA) -> str:
    return "#" + "".join(f"{channel:02X}" for channel in colour)


_HEX = re.compile(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?")


def _parse_hex(value: Any) -> RGBA | None:
    """``#RRGGBB`` or ``#RRGGBBAA``; anything else (signs, spaces, short forms) is junk."""
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        return None
    channels = [int(value[i : i + 2], 16) for i in range(1, len(value), 2)]
    if len(channels) == 3:
        channels.append(255)
    return tuple(channels)  # type: ignore[return-value]


def _clamped(value: Any, low: float, high: float, fallback: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    return float(min(high, max(low, value)))


# The same rule as jobs/project.py's _store_path/_resolve_path (core must not
# import jobs): relative only when the image lies inside the project folder, so
# moving the folder alone keeps it; anything outside is stored absolute.


def _store_path(path: Path, relative_to: Path | None) -> str:
    """Relative to the project when it lies inside its folder, so the folder can move."""
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, ValueError, RuntimeError):
        return str(path)
    if relative_to is not None:
        try:
            return resolved.relative_to(Path(relative_to).resolve()).as_posix()
        except (OSError, ValueError, RuntimeError):
            pass
    return resolved.as_posix()


def _resolve_path(value: str, base_dir: Path | None) -> Path:
    """May raise OSError, ValueError or RuntimeError on junk; the caller falls back."""
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or base_dir is None:
        return candidate.resolve()
    return (Path(base_dir) / candidate).resolve()


def merge_style(style: dict | None, look: Look, *, relative_to: Path | None = None) -> dict:
    """*style* with the look's keys replaced and every other key kept."""
    return {**(style or {}), **look.to_dict(relative_to)}


def look_from_style(style: dict | None, *, base_dir: Path | None = None) -> Look:
    """The look a project's ``style`` describes; an empty style is ``NIGHT_GOLD``."""
    if not style:
        return NIGHT_GOLD
    return Look.from_dict(style, base_dir=base_dir)


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(colour: tuple[int, ...]) -> float:
    r, g, b = (_linear(c) for c in colour[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: tuple[int, ...], bg: tuple[int, ...]) -> float:
    """WCAG 2.x contrast ratio of two opaque colours (alpha is ignored)."""
    high, low = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def composite(fg: RGBA, bg: tuple[int, ...]) -> tuple[int, int, int]:
    """*fg* laid over an opaque *bg* at its alpha."""
    alpha = fg[3] / 255
    return tuple(round(fg[i] * alpha + bg[i] * (1 - alpha)) for i in range(3))  # type: ignore[return-value]


def readability_warnings(look: Look, background_mean: tuple[int, ...]) -> list[str]:
    """The text colours that fall below 4.5:1 where they are drawn."""
    card = composite(look.card, background_mean)
    strip = composite(look.caption_bg, background_mean)
    low = [n for n in _CARD_TEXT if contrast_ratio(getattr(look, n), card) < MIN_CONTRAST]
    low += [n for n in _CAPTION_TEXT if contrast_ratio(getattr(look, n), strip) < MIN_CONTRAST]
    return low


def _look(name: str, background: Background, **colours: RGBA) -> Look:
    return Look(**colours, background=background, base_preset=name)


COLOUR_FIELDS = tuple(f.name for f in fields(Look) if f.name not in ("background", "base_preset"))

_NIGHT_BG = (10, 10, 12, 255)

PRESETS: dict[str, Look] = {
    "night_gold": _look(
        "night_gold",
        Background("solid", _NIGHT_BG, _NIGHT_BG),
        frame_bg=_NIGHT_BG,
        card=(36, 36, 42, 230),
        card_border=(255, 255, 255, 28),
        header_text=(230, 230, 235, 255),
        body_text=(255, 255, 255, 255),
        highlight_word=(255, 215, 0, 255),
        subtle=(150, 150, 162, 255),
        debug_text=(188, 188, 198, 255),
        placeholder_text=(205, 205, 215, 255),
        caption_bg=(0, 0, 0, 165),
        caption_text=(240, 240, 245, 255),
        caption_active=(128, 226, 234, 255),
        caption_upcoming=(150, 150, 162, 255),
    ),
    "emerald": _look(
        "emerald",
        Background("pattern_stars", (6, 32, 26, 255), (14, 50, 41, 255)),
        frame_bg=(6, 32, 26, 255),
        card=(12, 58, 46, 225),
        card_border=(255, 255, 255, 28),
        header_text=(220, 240, 232, 255),
        body_text=(255, 255, 255, 255),
        highlight_word=(255, 214, 102, 255),
        subtle=(140, 170, 160, 255),
        debug_text=(180, 200, 192, 255),
        placeholder_text=(200, 228, 218, 255),
        caption_bg=(0, 0, 0, 165),
        caption_text=(240, 245, 242, 255),
        caption_active=(152, 240, 200, 255),
        caption_upcoming=(140, 165, 155, 255),
    ),
    "sand": _look(
        "sand",
        Background("pattern_arches", (52, 39, 24, 255), (74, 57, 37, 255)),
        frame_bg=(52, 39, 24, 255),
        card=(250, 240, 222, 235),
        card_border=(0, 0, 0, 30),
        header_text=(110, 70, 30, 255),
        body_text=(40, 30, 20, 255),
        highlight_word=(176, 40, 40, 255),
        subtle=(140, 120, 100, 255),
        debug_text=(110, 95, 80, 255),
        placeholder_text=(90, 70, 50, 255),
        caption_bg=(0, 0, 0, 165),
        caption_text=(245, 238, 225, 255),
        caption_active=(240, 200, 120, 255),
        caption_upcoming=(170, 160, 145, 255),
    ),
    "ink_on_paper": _look(
        "ink_on_paper",
        Background("pattern_lattice", (232, 226, 212, 255), (214, 206, 190, 255)),
        frame_bg=(232, 226, 212, 255),
        card=(252, 250, 244, 240),
        card_border=(0, 0, 0, 36),
        header_text=(60, 60, 70, 255),
        body_text=(20, 20, 24, 255),
        highlight_word=(190, 30, 45, 255),
        subtle=(120, 120, 128, 255),
        debug_text=(90, 90, 100, 255),
        placeholder_text=(70, 70, 80, 255),
        caption_bg=(0, 0, 0, 165),
        caption_text=(255, 255, 255, 255),
        caption_active=(255, 214, 102, 255),
        caption_upcoming=(190, 190, 195, 255),
    ),
    "ocean": _look(
        "ocean",
        Background("gradient", (8, 30, 52, 255), (4, 14, 28, 255)),
        frame_bg=(8, 30, 52, 255),
        card=(16, 48, 78, 225),
        card_border=(255, 255, 255, 30),
        header_text=(210, 230, 245, 255),
        body_text=(255, 255, 255, 255),
        highlight_word=(255, 200, 90, 255),
        subtle=(130, 155, 180, 255),
        debug_text=(170, 190, 210, 255),
        placeholder_text=(190, 215, 235, 255),
        caption_bg=(0, 0, 0, 165),
        caption_text=(235, 242, 250, 255),
        caption_active=(120, 220, 255, 255),
        caption_upcoming=(130, 150, 170, 255),
    ),
    "rose": _look(
        "rose",
        Background("gradient", (48, 16, 28, 255), (24, 8, 14, 255)),
        frame_bg=(48, 16, 28, 255),
        card=(70, 28, 44, 225),
        card_border=(255, 255, 255, 28),
        header_text=(245, 215, 225, 255),
        body_text=(255, 248, 250, 255),
        highlight_word=(255, 205, 120, 255),
        subtle=(175, 140, 155, 255),
        debug_text=(200, 170, 182, 255),
        placeholder_text=(230, 200, 212, 255),
        caption_bg=(0, 0, 0, 165),
        caption_text=(250, 240, 244, 255),
        caption_active=(255, 170, 200, 255),
        caption_upcoming=(165, 135, 148, 255),
    ),
}
NIGHT_GOLD = PRESETS["night_gold"]

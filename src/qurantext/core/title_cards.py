"""Generated title clips: the episode's intro and outro, drawn in the lecture's look.

The intro names the channel (or the speaker) above the surah and its ayat; the
outro shows a closing phrase and, when the person gave a link, a QR code with
the link's plain address under or beside it. Both are drawn on the look's own
background and card panel (:func:`qurantext.core.backgrounds.base_layer`), with
the bundled Amiri font, which has Latin letters as well as Arabic ones; the
Quran font has no Latin and is not used here.

A clip is silent, as long as its spec says, and written by FFmpeg from raw
frames streamed to it: ``<output>.part.mp4`` first, renamed into place when it
is complete. A cancel kills FFmpeg and removes the partial file.

The QR code is never animated, offset or masked. It is fully drawn from 14 % to
86 % of the clip, with a short fade either side, so a phone has at least 70 %
of the outro's frames to read it. Its modules are whole pixels, at least 5 and
enough for the code with its quiet zone to fill a quarter of the frame's short
side: at 4 px a code that decodes from the clip itself no longer does once a
platform has scaled the video down to 480p or 360p, as WhatsApp, Telegram and a
phone's YouTube player do. Its modules are the darker of the look's body text and card
colours on the lighter one: phone scanners expect dark modules on a light
ground, and an inverted code (light on dark) is one many of them, and OpenCV's
detector, cannot read. When the two colours are too close (under 4.5:1) the
code is black on white.

The link text under the code is always laid out left to right, whatever script
its host or path is in; every other text takes its direction from its first
strong letter. "Reveal" uncovers the frame from the edge the reader starts at,
which is part of the spec (``rtl``), so a clip and its preview agree.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tempfile
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from qurantext.config.paths import TEXT_FONT_BOLD_PATH, TEXT_FONT_PATH
from qurantext.core.backgrounds import base_layer
from qurantext.core.frame_renderer import (
    LINE_SPACING_RATIO,
    _card_radius,
    _measure_probe,
    _require_raqm_support,
    fit_font_size,
    load_font,
)
from qurantext.core.looks import MIN_CONTRAST, Look, contrast_ratio
from qurantext.core.qr import qr_image, qr_modules
from qurantext.core.video_common import require_binary
from qurantext.utils.progress import CancelToken, ProgressCallback, report

__all__ = [
    "GENERATOR_VERSION",
    "MAX_SECONDS",
    "MIN_SECONDS",
    "STAGE",
    "STYLES",
    "IntroSpec",
    "OutroSpec",
    "TitleClipError",
    "TitleTextError",
    "missing_glyphs",
    "qr_box",
    "qr_colours",
    "qr_fits",
    "render_title_clip",
    "render_title_frame",
]

#: Part of every clip's cache key: bump it whenever a clip's pixels change for
#: the same spec, so clips made by an earlier version are made again.
GENERATOR_VERSION = 2
STYLES = ("fade", "rise", "reveal")
MIN_SECONDS = 3.0
MAX_SECONDS = 10.0
#: The progress stage a clip reports under.
STAGE = "title_clip"

_TEXT_FADE = 0.6  # seconds the text takes to fade in, and out
_QR_FADE = 0.2  # seconds the QR code takes to fade in, and out
# The share of the clip the QR code is fully drawn: 72 %, so that counted in whole
# frames it is still at least 70 % at any length and frame rate from 17 fps up.
_QR_FROM, _QR_TO = 0.14, 0.86
_REVEAL_SHARE = 0.4  # the share of the clip "reveal" spends uncovering the frame
_RISE = 0.06  # how far below its place "rise" starts the text, as a share of H
_FONT_START = 0.09  # the first size tried for titles, as a share of H
_FONT_MIN = 0.02  # the smallest size, as a share of the frame's short side
_LINK_START = 0.045  # the first size tried for the link text, of the short side
_TITLE_UNDER_NAME = 0.7  # the intro's title starts at this share of the name's size
_MAX_LINES = 2
# Before wrapping, a text may shrink to this share of its first size to stay on one
# line: «دروس الشيخ أحمد» as one line, not «دروس الشيخ» over a lone «أحمد».
_ONE_LINE_SHARE = 0.7
_QR_MIN_SHARE = 0.25  # the code with its quiet zone, at least, of the short side
_QR_QUIET = 4
_QR_MIN_MODULE = 5  # px; 4 px codes stop decoding after a 480p transcode
# The most of the panel's text room the code may take, so the words keep theirs.
_QR_ROOM_PORTRAIT = 0.6  # of the panel's height
_QR_ROOM_LANDSCAPE = 0.5  # of the panel's width
_ELLIPSIS = "…"
# Characters the title font has but cannot draw, and what is drawn instead. Amiri's
# ﷽ (U+FDFD, the basmala ligature) fails to rasterise at every size ("raster
# overflow"), and it is a character this audience types; the words it stands for
# are drawn instead.
_SPELLED_OUT = {"\ufdfd": "بسم الله الرحمن الرحيم"}
_INSTALL_HINT = "Install FFmpeg and try again."
_ERROR_LINES = 8

RGB = tuple[int, int, int]
Box = tuple[int, int, int, int]


class TitleClipError(RuntimeError):
    """FFmpeg could not write the clip; the message ends with what it said."""


class TitleTextError(ValueError):
    """The title font could not measure or draw *text*; the message says which."""

    def __init__(self, text: str, error: OSError) -> None:
        super().__init__(f"the title font cannot draw {text!r}: {error}")
        self.text = text


def _drawable(text: str) -> str:
    """*text* with every character the font cannot draw spelled out (see _SPELLED_OUT)."""
    for char, words in _SPELLED_OUT.items():
        text = text.replace(char, f" {words} ")
    return text


def _check(style: str, seconds: float) -> float:
    """*seconds* as a float, or ``ValueError`` for an unknown style or a length out of range."""
    if style not in STYLES:
        raise ValueError(f"unknown style {style!r}; expected one of {STYLES}")
    seconds = float(seconds)
    if not (math.isfinite(seconds) and MIN_SECONDS <= seconds <= MAX_SECONDS):
        raise ValueError(f"a title clip lasts {MIN_SECONDS:g}-{MAX_SECONDS:g} s, not {seconds}")
    return seconds


def _key(spec: Any) -> str:
    payload = {"kind": type(spec).__name__, "version": GENERATOR_VERSION, **asdict(spec)}
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IntroSpec:
    """The intro: *name* (the channel or speaker) above *title* (the surah and ayat)."""

    name: str
    title: str
    style: str = "fade"
    seconds: float = 5.0
    #: The reader starts on the right: "reveal" uncovers from that edge.
    rtl: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "seconds", _check(self.style, self.seconds))
        object.__setattr__(self, "rtl", bool(self.rtl))

    def cache_key(self) -> str:
        """A sha256 of every field and :data:`GENERATOR_VERSION`, stable across runs."""
        return _key(self)


@dataclass(frozen=True)
class OutroSpec:
    """The outro: *phrase*, and the QR code for *qr_url* with *link_text* by it.

    *qr_url* is the tracked link the code opens; *link_text* the plain address
    written next to it. Either may be None; with no *qr_url* there is no code.
    """

    phrase: str
    link_text: str | None
    qr_url: str | None
    style: str = "fade"
    seconds: float = 6.0
    #: The reader starts on the right: "reveal" uncovers from that edge.
    rtl: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "seconds", _check(self.style, self.seconds))
        object.__setattr__(self, "rtl", bool(self.rtl))

    def cache_key(self) -> str:
        """A sha256 of every field and :data:`GENERATOR_VERSION`, stable across runs."""
        return _key(self)


Spec = IntroSpec | OutroSpec


# --- Text ---------------------------------------------------------------------


def _direction(text: str) -> str:
    """``rtl`` or ``ltr``, from the first strong character (``rtl`` when there is none)."""
    for char in text:
        kind = unicodedata.bidirectional(char)
        if kind in ("R", "AL"):
            return "rtl"
        if kind == "L":
            return "ltr"
    return "rtl"


def _bbox(line: str, font: Any, direction: str) -> Box:
    return _measure_probe().textbbox((0, 0), line or " ", font=font, direction=direction)


def _spacing(font: Any) -> int:
    return max(4, int(font.size * LINE_SPACING_RATIO))


def _block_size(lines: tuple[str, ...], font: Any, direction: str) -> tuple[int, int]:
    boxes = [_bbox(line, font, direction) for line in lines]
    width = max((b[2] - b[0] for b in boxes), default=0)
    height = sum(b[3] - b[1] for b in boxes) + _spacing(font) * max(0, len(lines) - 1)
    return width, height


def _ellipsize(line: str, font: Any, max_width: int, direction: str) -> str:
    """*line*, cut short with an ellipsis at its logical end until it fits *max_width*.

    Cut between words when a whole word fits; inside a word (one long word, a
    link) only when none does.
    """

    def fits(candidate: str) -> bool:
        box = _bbox(candidate, font, direction)
        return box[2] - box[0] <= max_width

    if fits(line + _ELLIPSIS):
        return line + _ELLIPSIS
    spaces = [i for i, char in enumerate(line) if char == " "]
    for cut in reversed(spaces):
        candidate = line[:cut].rstrip() + _ELLIPSIS
        if line[:cut].strip() and fits(candidate):
            return candidate
    for cut in range(len(line) - 1, 0, -1):
        candidate = line[:cut].rstrip() + _ELLIPSIS
        if fits(candidate):
            return candidate
    return _ELLIPSIS


@dataclass(frozen=True)
class _Block:
    lines: tuple[str, ...]
    font: Any
    direction: str
    width: int
    height: int


def _fit(text: str, font_file: Path, *args: Any, **kwargs: Any) -> _Block | None:
    """:func:`_fit_text` on the drawable form of *text*; a font failure is a
    :class:`TitleTextError` naming the text, never a bare ``OSError``."""
    try:
        return _fit_text(_drawable(text), font_file, *args, **kwargs)
    except OSError as error:
        raise TitleTextError(text, error) from error


def _fit_text(
    text: str,
    font_file: Path,
    max_width: int,
    max_height: int,
    start: int,
    minimum: int,
    max_lines: int,
    direction: str | None = None,
    *,
    exact: bool = False,
) -> _Block | None:
    """The largest size from *start* down at which *text* fits in at most *max_lines*.

    One line is preferred to two: sizes down to 70 % of *start* are tried for
    one line first, so a short name does not wrap a word onto a line of its
    own; only text that needs more shrinking than that wraps (at the largest
    size that fits). Sizes are tried with :func:`fit_font_size` (one size at a
    time, so its cache serves every later frame). Text that does not fit even
    at *minimum* keeps its first *max_lines* lines, the last one cut short with
    an ellipsis, so it never leaves the box sideways. *direction* overrides the one guessed from
    the first strong letter (the link text is always ``ltr``). With *exact*,
    text that does not fit by *minimum* gives None instead of being cut short.
    """
    text = " ".join(text.split())
    if not text:
        return None
    direction = direction or _direction(text)
    probe = _measure_probe()
    max_width, max_height = max(1, max_width), max(1, max_height)
    minimum = max(8, minimum)
    size = max(start, minimum)
    if max_lines > 1:
        one_line = _fit_text(
            text,
            font_file,
            max_width,
            max_height,
            size,
            max(minimum, round(size * _ONE_LINE_SHARE)),
            1,
            direction,
            exact=True,
        )
        if one_line is not None:
            return one_line
    while True:
        font, lines = fit_font_size(probe, text, font_file, max_width, max_height, size, size)
        lines = tuple(lines)
        width, height = _block_size(lines, font, direction)
        if len(lines) <= max_lines and width <= max_width and height <= max_height:
            return _Block(lines, font, direction, width, height)
        if size <= minimum:
            break
        size = max(minimum, size - max(2, size // 12))
    if exact:
        return None
    kept = list(lines[:max_lines])
    # Lines that do not fit by height go too: one line at the smallest size always stays.
    while len(kept) > 1 and _block_size(tuple(kept), font, direction)[1] > max_height:
        kept.pop()
    cut_short = len(kept) < len(lines)
    for index, line in enumerate(kept):
        box = _bbox(line, font, direction)
        if box[2] - box[0] > max_width or (cut_short and index == len(kept) - 1):
            kept[index] = _ellipsize(line, font, max_width, direction)
    lines = tuple(kept)
    width, height = _block_size(lines, font, direction)
    return _Block(lines, font, direction, width, height)


def _draw_block(draw: ImageDraw.ImageDraw, block: _Block, centre_x: float, top: float) -> None:
    """Each line centred on *centre_x*, the block's ink starting at *top*."""
    y = top
    for line in block.lines:
        x0, y0, x1, y1 = _bbox(line, block.font, block.direction)
        try:
            draw.text(
                (centre_x - (x0 + x1) / 2, y - y0),
                line,
                font=block.font,
                fill=255,
                direction=block.direction,
            )
        except OSError as error:
            raise TitleTextError(line, error) from error
        y += (y1 - y0) + _spacing(block.font)


# --- Layout -------------------------------------------------------------------


@dataclass(frozen=True)
class _Placed:
    block: _Block
    centre_x: float
    top: float
    #: The look colour that draws it: ``header_text``, ``body_text`` or ``placeholder_text``.
    colour: str

    @property
    def box(self) -> tuple[float, float, float, float]:
        """Where its ink lies in the frame."""
        half = self.block.width / 2
        return (self.centre_x - half, self.top, self.centre_x + half, self.top + self.block.height)


@dataclass(frozen=True)
class _Layout:
    panel: Box
    radius: int
    texts: tuple[_Placed, ...]
    qr_box: Box | None
    #: False when the frame is too small for modules of 5 px (a preview thumbnail).
    qr_scannable: bool


def _panel_size(width: int, height: int) -> tuple[int, int]:
    if height > width:
        return round(width * 0.80), round(height * 0.50)
    return round(width * 0.70), round(height * 0.42)


def _stack(items: list[tuple[str, Any, int]], top: float) -> list[tuple[str, Any, float]]:
    """Lay *items* (name, payload, height) out downwards from *top*, gaps included."""
    placed = []
    y = top
    for name, payload, size in items:
        if name == "gap":
            y += size
            continue
        placed.append((name, payload, y))
        y += size
    return placed


@lru_cache(maxsize=16)
def _layout(spec: Spec, width: int, height: int) -> _Layout:
    _require_raqm_support()
    short = min(width, height)
    portrait = height > width
    pad = max(6, round(0.045 * short))
    margin = round(0.03 * short)
    panel_w, panel_h = _panel_size(width, height)
    max_w, max_h = width - 2 * margin, height - 2 * margin
    start = max(8, round(_FONT_START * height))
    minimum = max(8, round(_FONT_MIN * short))

    qr_side = 0
    qr_scannable = True
    if isinstance(spec, OutroSpec) and spec.qr_url:
        span = qr_modules(spec.qr_url) + 2 * _QR_QUIET
        module = max(_QR_MIN_MODULE, math.ceil(_QR_MIN_SHARE * short / span))
        qr_side = module * span
        # The most the code may take and still leave the words their room.
        if portrait:
            room = min(max_w - 2 * pad, int((max_h - 2 * pad) * _QR_ROOM_PORTRAIT))
        else:
            room = min(max_h - 2 * pad, int((max_w - 3 * pad) * _QR_ROOM_LANDSCAPE))
        if qr_side > room:
            # Only a preview is drawn this small; a clip refuses (qr_fits).
            qr_scannable = False
            # Whole modules when even 1 px ones fit; below that the code is scaled
            # down into the room, so a thumbnail never draws it past the frame.
            qr_side = (room // span) * span if room >= span else max(1, room)
        if portrait:
            panel_w = max(panel_w, qr_side + 2 * pad)
            panel_h = max(panel_h, math.ceil(qr_side / _QR_ROOM_PORTRAIT) + 2 * pad)
        else:
            panel_h = max(panel_h, qr_side + 2 * pad)
            panel_w = max(panel_w, math.ceil(qr_side / _QR_ROOM_LANDSCAPE) + 3 * pad)
    panel_w, panel_h = min(panel_w, max_w), min(panel_h, max_h)
    x0, y0 = (width - panel_w) // 2, (height - panel_h) // 2
    panel = (x0, y0, x0 + panel_w, y0 + panel_h)
    inner = (x0 + pad, y0 + pad, x0 + panel_w - pad, y0 + panel_h - pad)
    inner_w, inner_h = inner[2] - inner[0], inner[3] - inner[1]
    gap = max(4, round(pad * 0.6))
    texts: list[_Placed] = []
    qr_at: Box | None = None

    if isinstance(spec, IntroSpec):
        share = inner_h - gap
        name = _fit(
            spec.name, TEXT_FONT_BOLD_PATH, inner_w, round(share * 0.55), start, minimum, _MAX_LINES
        )
        title_room = inner_h - (name.height + gap if name else 0)
        # Below the name, smaller than it: the title starts at 0.7 of the name's size.
        title_start = round(name.font.size * _TITLE_UNDER_NAME) if name else start
        title = _fit(
            spec.title,
            TEXT_FONT_PATH,
            inner_w,
            title_room,
            title_start,
            min(minimum, title_start),
            _MAX_LINES,
        )
        items = []
        if name:
            items.append(("header_text", name, name.height))
        if name and title:
            items.append(("gap", None, gap))
        if title:
            items.append(("body_text", title, title.height))
        total = sum(size for _, _, size in items)
        centre = (inner[0] + inner[2]) / 2
        for colour, block, top in _stack(items, inner[1] + (inner_h - total) / 2):
            texts.append(_Placed(block, centre, top, colour))
    else:
        link_start = max(8, round(_LINK_START * short))
        link_min = min(link_start, minimum)
        if qr_side and portrait:
            column = inner
        elif qr_side:
            column = (inner[0] + qr_side + pad, inner[1], inner[2], inner[3])
        else:
            column = inner
        col_w = column[2] - column[0]
        link = None
        if spec.link_text:
            link = _fit(
                spec.link_text, TEXT_FONT_PATH, col_w, inner_h, link_start, link_min, 1, "ltr"
            )
        link_gap = max(4, round(pad * 0.4))
        used = (link.height + link_gap if link else 0) + (
            qr_side + gap if qr_side and portrait else 0
        )
        phrase = _fit(
            spec.phrase,
            TEXT_FONT_BOLD_PATH,
            col_w,
            max(1, inner_h - used),
            start,
            minimum,
            _MAX_LINES,
        )
        items: list[tuple[str, Any, int]] = []
        if qr_side and portrait:
            items.append(("qr", None, qr_side))
            if link:
                items += [("gap", None, link_gap), ("placeholder_text", link, link.height)]
            if phrase:
                items += [("gap", None, gap), ("body_text", phrase, phrase.height)]
        else:
            if phrase:
                items.append(("body_text", phrase, phrase.height))
            if phrase and link:
                items.append(("gap", None, gap))
            if link:
                items.append(("placeholder_text", link, link.height))
        total = sum(size for _, _, size in items)
        centre = (column[0] + column[2]) / 2
        for kind, block, top in _stack(items, column[1] + (inner_h - total) / 2):
            if kind == "qr":
                qx = round(centre - qr_side / 2)
                qr_at = (qx, round(top), qx + qr_side, round(top) + qr_side)
            else:
                texts.append(_Placed(block, centre, top, kind))
        if qr_side and not portrait:
            qy = inner[1] + (inner_h - qr_side) // 2
            qr_at = (inner[0], qy, inner[0] + qr_side, qy + qr_side)

    return _Layout(panel, _card_radius(width, height), tuple(texts), qr_at, qr_scannable)


def qr_box(spec: Spec, width: int, height: int) -> Box | None:
    """Where the QR code is drawn in a *width* × *height* frame, or None without one."""
    return _layout(spec, width, height).qr_box


def qr_fits(spec: Spec, width: int, height: int) -> bool:
    """Whether a clip of *spec* at this size can carry its QR code at 5 px modules.

    True without a code. A long link needs more modules, so whether it fits
    depends on the lecture's size, not on a fixed number of characters; this
    is what :func:`render_title_clip` checks before it starts.
    """
    return _layout(spec, width, height).qr_scannable


@lru_cache(maxsize=4)
def _tofu(font_file: Path) -> tuple[tuple[int, int], bytes]:
    """The mask the font draws for a character it has no glyph for."""
    mask = load_font(font_file, 32).getmask("\ue000")
    return mask.size, bytes(mask)


@lru_cache(maxsize=2048)
def _has_glyph(font_file: Path, char: str) -> bool:
    """Whether the font draws *char*: not its missing-glyph box, and not an error."""
    try:
        mask = load_font(font_file, 32).getmask(char)
    except OSError:  # a glyph FreeType cannot rasterise draws nothing either
        return False
    return (mask.size, bytes(mask)) != _tofu(font_file)


def missing_glyphs(text: str) -> str:
    """The characters of *text* the title font cannot draw, each once, in order.

    Amiri draws Arabic and Latin (with its diacritics), not Cyrillic, Bengali
    or emoji, which would come out as empty boxes; the dialog can warn first.
    Spaces and invisible formatting characters are never reported, nor is a
    character the renderer spells out instead of drawing (﷽ becomes the words
    of the basmala).
    """
    missing = []
    for char in dict.fromkeys(_drawable(text)):
        if char.isspace() or unicodedata.category(char) in ("Cc", "Cf"):
            continue
        if not all(_has_glyph(path, char) for path in (TEXT_FONT_PATH, TEXT_FONT_BOLD_PATH)):
            missing.append(char)
    return "".join(missing)


def qr_colours(look: Look) -> tuple[RGB, RGB]:
    """The QR code's (modules, ground): the look's body text and card, dark on light."""
    dark: RGB = tuple(look.body_text[:3])  # type: ignore[assignment]
    light: RGB = tuple(look.card[:3])  # type: ignore[assignment]
    if contrast_ratio(dark, light) < MIN_CONTRAST:
        return (0, 0, 0), (255, 255, 255)
    black = (0, 0, 0)
    if contrast_ratio(dark, black) > contrast_ratio(light, black):
        dark, light = light, dark
    return dark, light


# --- Frames -------------------------------------------------------------------


@dataclass(frozen=True)
class _Scene:
    layout: _Layout
    #: Every text, drawn at full alpha on a transparent panel-sized layer.
    text: Image.Image | None
    qr: Image.Image | None


@lru_cache(maxsize=8)
def _scene(spec: Spec, look: Look, width: int, height: int) -> _Scene:
    layout = _layout(spec, width, height)
    x0, y0, x1, y1 = layout.panel
    text = None
    if layout.texts:
        text = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
        for colour in dict.fromkeys(p.colour for p in layout.texts):
            placed = [p for p in layout.texts if p.colour == colour]
            if not placed:
                continue
            # Drawn white on a mask, then given the colour: a straight alpha
            # edge, with no dark fringe from blending into transparent black.
            mask = Image.new("L", text.size, 0)
            draw = ImageDraw.Draw(mask)
            for p in placed:
                _draw_block(draw, p.block, p.centre_x - x0, p.top - y0)
            rgba = getattr(look, colour)
            fill = Image.new("RGBA", text.size, tuple(rgba[:3]) + (255,))
            fill.putalpha(mask.point([v * rgba[3] // 255 for v in range(256)]))
            text.alpha_composite(fill)
    qr = None
    if layout.qr_box is not None:
        assert isinstance(spec, OutroSpec) and spec.qr_url
        dark, light = qr_colours(look)
        side = layout.qr_box[2] - layout.qr_box[0]
        span = qr_modules(spec.qr_url) + 2 * _QR_QUIET
        qr = qr_image(
            spec.qr_url,
            max(side, span),
            dark,
            light,
            min_module_px=_QR_MIN_MODULE if layout.qr_scannable else 1,
        )
        if qr.width != side:  # a thumbnail smaller than one pixel a module
            qr = qr.resize((side, side), Image.Resampling.BOX)
    return _Scene(layout, text, qr)


def _ramp(x: float) -> float:
    return min(1.0, max(0.0, x))


def _ease(x: float) -> float:
    return 1 - (1 - _ramp(x)) ** 3


def _state(spec: Spec, height: int, t: float) -> tuple[float, int, float, float | None]:
    """(text alpha, text y offset, QR alpha, reveal share or None) at *t* seconds."""
    seconds = spec.seconds
    start = _REVEAL_SHARE * seconds if spec.style == "reveal" else 0.0
    rising = _ramp((t - start) / _TEXT_FADE)
    text_alpha = min(rising, _ramp((seconds - t) / _TEXT_FADE))
    offset = round(_RISE * height * (1 - _ease(rising))) if spec.style == "rise" else 0
    on, off = _QR_FROM * seconds, _QR_TO * seconds
    if t < on:
        qr_alpha = _ramp((t - (on - _QR_FADE)) / _QR_FADE)
    elif t > off:
        qr_alpha = _ramp((off + _QR_FADE - t) / _QR_FADE)
    else:
        qr_alpha = 1.0
    reveal = None
    if spec.style == "reveal" and t < start:
        reveal = _ease(t / start)
    return text_alpha, offset, qr_alpha, reveal


def _compose(
    scene: _Scene, look: Look, width: int, height: int, state: tuple, rtl: bool
) -> Image.Image:
    text_alpha, offset, qr_alpha, reveal = state
    layout = scene.layout
    frame = base_layer(look, width, height, layout.panel, layout.radius).image.copy()
    if reveal is not None:
        # The look uncovers from the edge a reader starts at; the rest is its plain colour.
        shown = round(width * reveal)
        canvas = Image.new("RGBA", (width, height), tuple(look.frame_bg[:3]) + (255,))
        if shown > 0:
            region = (width - shown, 0, width, height) if rtl else (0, 0, shown, height)
            canvas.paste(frame.crop(region), region[:2])
        frame = canvas
    if scene.text is not None and text_alpha > 0:
        layer = scene.text
        if text_alpha < 1:
            layer = layer.copy()
            layer.putalpha(layer.getchannel("A").point(lambda v: round(v * text_alpha)))
        if offset:
            # Moved down inside the panel, and clipped to it.
            shifted = Image.new("RGBA", layer.size, (0, 0, 0, 0))
            shifted.paste(
                layer.crop((0, 0, layer.width, max(0, layer.height - offset))), (0, offset)
            )
            layer = shifted
        frame.alpha_composite(layer, dest=layout.panel[:2])
    if scene.qr is not None and qr_alpha > 0:
        assert layout.qr_box is not None
        if qr_alpha >= 1:
            frame.paste(scene.qr, layout.qr_box[:2])
        else:
            mask = Image.new("L", scene.qr.size, round(255 * qr_alpha))
            frame.paste(scene.qr, layout.qr_box[:2], mask)
    return frame.convert("RGB")


def render_title_frame(
    spec: Spec, look: Look, width: int, height: int, t: float, *, rtl: bool | None = None
) -> Image.Image:
    """The clip's frame at *t* seconds, as an RGB image of *width* × *height*.

    The edge "reveal" uncovers from is the spec's (``spec.rtl``), so a preview
    matches its clip; *rtl* overrides it. Each text's own direction comes from
    its first strong letter, and the link text is always left to right.
    """
    scene = _scene(spec, look, width, height)
    edge = spec.rtl if rtl is None else rtl
    return _compose(scene, look, width, height, _state(spec, height, t), edge)


# --- Clips --------------------------------------------------------------------


def _last_lines(handle: Any) -> str:
    handle.seek(0)
    text = handle.read().decode("utf-8", "replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-_ERROR_LINES:]) or "FFmpeg stopped without saying why."


def _stop(process: subprocess.Popen) -> None:
    """End FFmpeg at once if it still runs, and reap it (the partial file goes anyway)."""
    if process.poll() is None:
        process.kill()
    if process.stdin is not None:
        try:
            process.stdin.close()
        except OSError:  # the pipe broke when FFmpeg ended
            pass
    process.wait()


def render_title_clip(
    spec: Spec,
    look: Look,
    output: Path,
    *,
    width: int,
    height: int,
    fps: int,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> Path:
    """Write *spec* as a silent H.264 clip of *width* × *height* at *fps* to *output*.

    ``round(seconds × fps)`` frames, through a hidden partial file beside
    *output* (``.<stem>.<random>.part.mp4``, so two makers never share one).
    Progress is reported about once per second of video. Raises ``JobCancelled``
    when *cancel* is set, :class:`TitleClipError` when FFmpeg fails,
    ``ValueError`` when the frame is too small for a QR code phones can read
    (:func:`qr_fits`), and ``RuntimeError`` without FFmpeg; no partial file is
    left.
    """
    if cancel is not None:
        cancel.raise_if_cancelled(STAGE)
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError(f"a title clip needs an even width and height, not {width}x{height}")
    if fps <= 0:
        raise ValueError(f"fps must be positive, not {fps}")
    scene = _scene(spec, look, width, height)
    if not scene.layout.qr_scannable:
        raise ValueError(f"{width}x{height} is too small for a QR code phones can read")
    ffmpeg = require_binary("ffmpeg", _INSTALL_HINT)
    output = Path(output)
    partial = output.with_name(f".{output.stem}.{uuid.uuid4().hex[:8]}.part.mp4")
    frames = max(1, round(spec.seconds * fps))
    command = [
        ffmpeg, "-y", "-nostdin", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
        "-framerate", str(fps), "-i", "pipe:0", "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-an", "-movflags", "+faststart", str(partial),
    ]  # fmt: skip
    output.parent.mkdir(parents=True, exist_ok=True)
    report(progress, STAGE, "Drawing the title clip", fraction=0.0)
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors
        )
        try:
            assert process.stdin is not None
            last_state: tuple | None = None
            data = b""
            for index in range(frames):
                if cancel is not None and cancel.cancelled:
                    _stop(process)
                    cancel.raise_if_cancelled(STAGE)
                state = _state(spec, height, index / fps)
                if state != last_state:  # most of a clip is one still frame
                    data = _compose(scene, look, width, height, state, spec.rtl).tobytes()
                    last_state = state
                try:
                    process.stdin.write(data)
                except OSError:
                    # FFmpeg ended early: BrokenPipeError, or EINVAL on Windows.
                    # Its own words say why, below.
                    break
                if (index + 1) % fps == 0 or index + 1 == frames:
                    report(progress, STAGE, "Drawing the title clip", fraction=(index + 1) / frames)
            try:
                process.stdin.close()
            except OSError:  # the flush hit the same closed pipe
                pass
            process.wait()
            if cancel is not None:
                cancel.raise_if_cancelled(STAGE)
            if process.returncode != 0:
                raise TitleClipError(
                    f"FFmpeg could not write the title clip: {_last_lines(errors)}"
                )
            partial.replace(output)
        except BaseException:
            _stop(process)
            partial.unlink(missing_ok=True)
            raise
    report(progress, STAGE, "Drew the title clip", fraction=1.0, done=True)
    return output

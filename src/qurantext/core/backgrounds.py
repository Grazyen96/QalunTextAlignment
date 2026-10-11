# src/qurantext/core/backgrounds.py
"""The part of every frame that does not change: the background and the card panel.

A frame used to start as a flat colour with the card composited onto it from a
fresh full-size overlay, every frame. Now the background may be a gradient, a
drawn pattern or a photo (cover-fitted, blurred, dimmed), which is far too
much to redo per frame, and none of it changes during a render. So the layer
is built once per (look, frame size, card box) and every frame starts from a
copy of it.

A photo that is missing or unreadable never stops a render: the look's preset
background is drawn instead and the layer carries a warning code for the
caller to show.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from qurantext.core.looks import NIGHT_GOLD, PRESETS, Background, Look

__all__ = ["BaseLayer", "background_mean", "base_layer", "clear_cache"]

_CACHE_SIZE = 4
_cache: OrderedDict[tuple, BaseLayer] = OrderedDict()


@dataclass(frozen=True, slots=True)
class BaseLayer:
    #: Shared between frames: copy before drawing on it.
    image: Image.Image
    #: The background's average colour, before the card: what the card sits on.
    mean: tuple[int, int, int]
    warnings: tuple[str, ...] = ()


def clear_cache() -> None:
    _cache.clear()


def _image_stamp(background: Background) -> tuple[int, int] | None:
    if background.kind != "image" or background.image is None:
        return None
    try:
        stat = background.image.stat()
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


def base_layer(
    look: Look, width: int, height: int, card_box: tuple[int, int, int, int], radius: int
) -> BaseLayer:
    key = (look, width, height, card_box, radius, _image_stamp(look.background))
    layer = _cache.get(key)
    if layer is not None:
        _cache.move_to_end(key)
        return layer
    background, mean, warnings = _background_or_fallback(look, width, height)
    image = background.copy()
    _draw_card(image, card_box, radius, look.card, look.card_border)
    layer = BaseLayer(image=image, mean=mean, warnings=warnings)
    _cache[key] = layer
    while len(_cache) > _CACHE_SIZE:
        _cache.popitem(last=False)
    return layer


def background_mean(look: Look, width: int, height: int) -> tuple[int, int, int]:
    return _background_or_fallback(look, width, height)[1]


def _background_or_fallback(
    look: Look, width: int, height: int
) -> tuple[Image.Image, tuple[int, int, int], tuple[str, ...]]:
    warnings: tuple[str, ...] = ()
    try:
        image = _draw_background(look.background, width, height)
    except _ImageProblem as problem:
        warnings = (problem.code,)
        fallback = PRESETS.get(look.base_preset, NIGHT_GOLD).background
        if fallback.kind == "image":  # a preset never has one; belt and braces
            fallback = NIGHT_GOLD.background
        image = _draw_background(fallback, width, height)
    mean = tuple(int(round(c)) for c in ImageStat.Stat(image.convert("RGB")).mean)
    return image, mean, warnings  # type: ignore[return-value]


class _ImageProblem(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _draw_background(background: Background, width: int, height: int) -> Image.Image:
    kind = background.kind
    if kind == "solid":
        # NIGHT_GOLD's solid colour is the old COLOUR_BG, so this is the old frame fill.
        image = Image.new("RGBA", (width, height), background.colour)
    elif kind == "gradient":
        image = _gradient(background.colour, background.colour2, width, height)
    elif kind == "image":
        image = _photo(background.image, width, height)
    else:
        image = Image.new("RGBA", (width, height), background.colour)
        _PATTERNS[kind](ImageDraw.Draw(image), background.colour2, width, height)
    if background.blur > 0:
        image = image.filter(ImageFilter.GaussianBlur(background.blur * height / 1000))
    if background.dim > 0:
        shade = Image.new("RGBA", (width, height), (0, 0, 0, int(round(background.dim * 255))))
        image.alpha_composite(shade)
    return image


def _gradient(top, bottom, width: int, height: int) -> Image.Image:
    mask = Image.linear_gradient("L").resize((width, height))
    return Image.composite(
        Image.new("RGBA", (width, height), bottom), Image.new("RGBA", (width, height), top), mask
    )


def _photo(path: Path | None, width: int, height: int) -> Image.Image:
    if path is None or not path.is_file():
        raise _ImageProblem("image_missing")
    try:
        with Image.open(path) as source:
            source.load()
            rgb = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise _ImageProblem("image_unreadable") from None
    fitted = ImageOps.fit(rgb, (width, height), method=Image.Resampling.LANCZOS)
    return fitted.convert("RGBA")


def _line_width(height: int) -> int:
    return max(1, height // 540)


def _stars(draw: ImageDraw.ImageDraw, colour, width: int, height: int) -> None:
    """Eight-point stars (two overlaid squares) on a square grid."""
    cell = max(24, height // 9)
    r = cell * 0.32
    d = r * 1.414
    lw = _line_width(height)
    for cy in range(cell // 2, height + cell, cell):
        for cx in range(cell // 2, width + cell, cell):
            square = [(cx - r, cy - r), (cx + r, cy - r), (cx + r, cy + r), (cx - r, cy + r)]
            diamond = [(cx, cy - d), (cx + d, cy), (cx, cy + d), (cx - d, cy)]
            for shape in (square, diamond):
                draw.line([*shape, shape[0]], fill=colour, width=lw, joint="curve")


def _lattice(draw: ImageDraw.ImageDraw, colour, width: int, height: int) -> None:
    """Diagonal lines both ways: a lattice of diamonds."""
    cell = max(24, height // 12)
    lw = _line_width(height)
    for k in range(-height, width + height, cell):
        draw.line([(k, 0), (k + height, height)], fill=colour, width=lw)
        draw.line([(k, height), (k + height, 0)], fill=colour, width=lw)


def _arches(draw: ImageDraw.ImageDraw, colour, width: int, height: int) -> None:
    """Rows of round arches on columns."""
    cell = max(24, height // 10)
    lw = _line_width(height)
    for y in range(cell, height + cell, cell):
        for x in range(0, width + cell, cell):
            draw.arc((x, y - cell, x + cell, y), start=180, end=360, fill=colour, width=lw)
            draw.line([(x, y - cell // 2), (x, y)], fill=colour, width=lw)


_PATTERNS = {"pattern_stars": _stars, "pattern_lattice": _lattice, "pattern_arches": _arches}


def _draw_card(image: Image.Image, box, radius: int, fill, outline) -> None:
    """The card panel, drawn exactly as frame_renderer.draw_rounded_rectangle drew it."""
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay, "RGBA").rounded_rectangle(
        box, radius=radius, fill=fill, outline=outline, width=2
    )
    image.alpha_composite(overlay)

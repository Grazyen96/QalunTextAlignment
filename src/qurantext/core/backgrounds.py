# src/qurantext/core/backgrounds.py
"""The part of every frame that does not change: the background and the card panel.

A frame used to start as a flat colour with the card composited onto it from a
fresh full-size overlay, every frame. Now the background may be a gradient, a
drawn pattern or a photo (cover-fitted, blurred, dimmed), which is far too
much to redo per frame, and none of it changes during a render. So the layer
is built once per (what it draws, frame size, card box) and every frame starts
from a copy of it.

Two caches, both behind one lock because a review window's preview (UI
thread) and an export (worker thread) render at the same time:

- the **layer** cache keys only on what the layer draws: the background, the
  card and its border, the base preset (it picks the fallback), the size, the
  card box and radius, plus the photo's size and mtime. A text-colour edit is
  a cache hit;
- the **photo** cache holds a decoded, cover-fitted photo (alpha kept, not yet
  blurred), so a blur, dim or card-colour edit does not decode the file again.
  Its transparent areas show the background colour, and blur and dim are
  applied to the frame-size image when the layer is built.

A photo that is missing or unreadable never stops a render: the look's preset
background is drawn instead and the layer carries a warning code for the
caller to show.
"""

from __future__ import annotations

import io
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageStat

from qurantext.core.looks import NIGHT_GOLD, PRESETS, Background, Look

__all__ = ["BaseLayer", "background_mean", "base_layer", "clear_cache"]

_CACHE_SIZE = 4
_PHOTO_CACHE_SIZE = 3
_MEAN_CACHE_SIZE = 16
#: Above this many pixels (after JPEG's reduced decode) a photo counts as
#: unreadable rather than costing gigabytes. Pillow's own bomb threshold.
_MAX_DECODE_PIXELS = 89_478_485

#: Guards the three caches. Layers and photos are built outside it, so a slow
#: photo decode on one thread never blocks a preview on another; two threads
#: building the same key at once is harmless (the second insert wins).
_lock = threading.Lock()
_cache: OrderedDict[tuple, BaseLayer] = OrderedDict()
_photo_cache: OrderedDict[tuple, Image.Image] = OrderedDict()
_mean_cache: OrderedDict[tuple, tuple] = OrderedDict()

#: EXIF orientation → the transpose that makes the image upright.
_ORIENTATION = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}
_EXIF_ORIENTATION_TAG = 0x0112


@dataclass(frozen=True, slots=True)
class BaseLayer:
    #: Shared between frames: copy before drawing on it.
    image: Image.Image
    #: The background's average colour, before the card: what the card sits on.
    mean: tuple[int, int, int]
    warnings: tuple[str, ...] = ()


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _photo_cache.clear()
        _mean_cache.clear()


def _cached(cache: OrderedDict, key: tuple):
    with _lock:
        value = cache.get(key)
        if value is not None:
            cache.move_to_end(key)
        return value


def _store(cache: OrderedDict, key: tuple, value, limit: int) -> None:
    with _lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)


def _image_stamp(background: Background) -> tuple[int, int] | None:
    if background.kind != "image" or background.image is None:
        return None
    try:
        stat = background.image.stat()
    except (OSError, ValueError):  # unreadable folder, a NUL in a hand-edited path
        return None
    return (stat.st_size, stat.st_mtime_ns)


def _background_key(look: Look, width: int, height: int, stamp) -> tuple:
    """Everything the background's pixels depend on (base_preset picks the fallback)."""
    return (look.background, look.base_preset, width, height, stamp)


def base_layer(
    look: Look, width: int, height: int, card_box: tuple[int, int, int, int], radius: int
) -> BaseLayer:
    stamp = _image_stamp(look.background)
    background_key = _background_key(look, width, height, stamp)
    key = (background_key, look.card, look.card_border, card_box, radius)
    layer = _cached(_cache, key)
    if layer is not None:
        return layer
    background, mean, warnings = _background_or_fallback(look, width, height, stamp)
    image = background.copy()
    _draw_card(image, card_box, radius, look.card, look.card_border)
    layer = BaseLayer(image=image, mean=mean, warnings=warnings)
    _store(_cache, key, layer, _CACHE_SIZE)
    _store(_mean_cache, background_key, mean, _MEAN_CACHE_SIZE)
    return layer


def background_mean(look: Look, width: int, height: int) -> tuple[int, int, int]:
    """The background's average colour at this size; cached, and a photo is decoded once."""
    stamp = _image_stamp(look.background)
    key = _background_key(look, width, height, stamp)
    mean = _cached(_mean_cache, key)
    if mean is None:
        mean = _background_or_fallback(look, width, height, stamp)[1]
        _store(_mean_cache, key, mean, _MEAN_CACHE_SIZE)
    return mean


def _background_or_fallback(
    look: Look, width: int, height: int, stamp
) -> tuple[Image.Image, tuple[int, int, int], tuple[str, ...]]:
    """The background (possibly a shared cached image: copy before drawing on it)."""
    warnings: tuple[str, ...] = ()
    try:
        image = _draw_background(look.background, width, height, stamp)
    except _ImageProblem as problem:
        warnings = (problem.code,)
        fallback = PRESETS.get(look.base_preset, NIGHT_GOLD).background
        if fallback.kind == "image":  # a preset never has one; belt and braces
            fallback = NIGHT_GOLD.background
        image = _draw_background(fallback, width, height, None)
    mean = tuple(int(round(c)) for c in ImageStat.Stat(image.convert("RGB")).mean)
    return image, mean, warnings  # type: ignore[return-value]


class _ImageProblem(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _draw_background(background: Background, width: int, height: int, stamp) -> Image.Image:
    kind = background.kind
    if kind == "solid":
        # NIGHT_GOLD's solid colour is the old COLOUR_BG, so this is the old frame fill.
        image = Image.new("RGBA", (width, height), background.colour)
    elif kind == "gradient":
        image = _gradient(background.colour, background.colour2, width, height)
    elif kind == "image":
        photo = _photo(background.image, stamp, width, height)
        # A transparent photo shows the background colour (opaque: the layer is
        # the bottom of the frame). Compositing onto a new image also leaves the
        # shared cached photo untouched.
        image = Image.new("RGBA", (width, height), (*background.colour[:3], 255))
        image.alpha_composite(photo)
    else:
        image = Image.new("RGBA", (width, height), background.colour)
        _PATTERNS[kind](ImageDraw.Draw(image), background.colour2, width, height)
    if background.blur > 0:
        image = image.filter(_blur_filter(background.blur, height))
    if background.dim > 0:
        shade = Image.new("RGBA", (width, height), (0, 0, 0, int(round(background.dim * 255))))
        image = Image.alpha_composite(image, shade)
    return image


def _blur_filter(blur: float, height: int) -> ImageFilter.GaussianBlur:
    return ImageFilter.GaussianBlur(blur * height / 1000)


def _gradient(top, bottom, width: int, height: int) -> Image.Image:
    mask = Image.linear_gradient("L").resize((width, height))
    return Image.composite(
        Image.new("RGBA", (width, height), bottom), Image.new("RGBA", (width, height), top), mask
    )


def _photo(path: Path | None, stamp, width: int, height: int) -> Image.Image:
    """The photo cover-fitted to the frame (RGBA, unblurred), from the photo cache when it can be.

    Shared between layers: never draw on it.
    """
    if path is None:
        raise _ImageProblem("image_missing")
    key = (path, stamp, width, height)
    image = _cached(_photo_cache, key)
    if image is None:
        image = _decode_photo(path, width, height)
        _store(_photo_cache, key, image, _PHOTO_CACHE_SIZE)
    return image


def _decode_photo(path: Path, width: int, height: int) -> Image.Image:
    """Decode *path* upright as 8-bit RGBA, cover-fitted to width × height, alpha kept.

    This is the "an image never fails a render" boundary: whatever goes wrong
    reading a user's file — it is gone, a folder is unreadable, the path is
    junk, the data is truncated or a decompression bomb, Pillow raises
    something unexpected, memory runs out — becomes ``image_missing`` or
    ``image_unreadable`` and the caller draws the preset background instead.
    """
    try:
        with Image.open(path) as source:
            orientation = _orientation(source)
            if source.format == "JPEG":
                # Decode at 1/2, 1/4 or 1/8 scale when that still covers the
                # frame: a phone photo then never decodes at full resolution.
                source.draft("RGB", _decode_size(source.size, orientation, (width, height)))
            if source.width * source.height > _MAX_DECODE_PIXELS:
                raise _ImageProblem("image_unreadable")
            source.load()
            icc = source.info.get("icc_profile")
            upright = source
            if orientation in _ORIENTATION:
                upright = source.transpose(_ORIENTATION[orientation])
            # RGBA resizes premultiplied in Pillow, so edges do not fringe.
            fitted = ImageOps.fit(
                _eight_bit_rgba(upright), (width, height), method=Image.Resampling.LANCZOS
            )
        return _to_srgb(fitted, icc)
    except _ImageProblem:
        raise
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        raise _ImageProblem("image_missing") from None
    except Exception:  # noqa: BLE001 — see the docstring: never fail a render
        raise _ImageProblem("image_unreadable") from None


def _orientation(source: Image.Image) -> int:
    """The EXIF orientation, or 1 when there is none or the EXIF block is malformed.

    Bad EXIF is not an unreadable image: the pixels are kept, un-rotated.
    """
    try:
        return int(source.getexif().get(_EXIF_ORIENTATION_TAG, 1))
    except Exception:  # noqa: BLE001 — malformed EXIF raises SyntaxError, ValueError, …
        return 1


def _decode_size(
    stored: tuple[int, int], orientation: int, target: tuple[int, int]
) -> tuple[int, int]:
    """The smallest stored-orientation size whose upright cover-fit still fills *target*."""
    sw, sh = stored
    uw, uh = (sh, sw) if orientation in (5, 6, 7, 8) else (sw, sh)
    scale = max(target[0] / uw, target[1] / uh)
    return (max(1, math.ceil(sw * scale)), max(1, math.ceil(sh * scale)))


def _eight_bit_rgba(image: Image.Image) -> Image.Image:
    """8-bit RGBA: 16-bit greys scaled down (not clipped), transparency kept as alpha."""
    if image.mode in ("I;16", "I;16L", "I;16B", "I;16N", "I"):
        values = np.asarray(image).astype(np.int64)
        if image.mode != "I" or values.max(initial=0) > 255:
            values = values >> 8
        image = Image.fromarray(np.clip(values, 0, 255).astype(np.uint8))
    return image if image.mode == "RGBA" else image.convert("RGBA")


def _to_srgb(image: Image.Image, icc: bytes | None) -> Image.Image:
    """Convert an RGBA image from its embedded RGB profile (Display P3, Adobe RGB…) to sRGB."""
    if not icc:
        return image
    try:
        from PIL import ImageCms

        source = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        if source.profile.xcolor_space.strip() != "RGB":
            return image
        converted = ImageCms.profileToProfile(
            image.convert("RGB"), source, ImageCms.createProfile("sRGB"), outputMode="RGB"
        )
    except Exception:  # noqa: BLE001 — a broken profile keeps the pixels as they are
        return image
    if converted is None:
        return image
    converted = converted.convert("RGBA")
    converted.putalpha(image.getchannel("A"))
    return converted


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

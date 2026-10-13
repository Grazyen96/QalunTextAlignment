"""A small picture of each job for the home list: its first card at its own look.

Made where the list is read, on the worker thread, with the same renderer the
preview and the export use, so the picture matches the video before any
render exists. Cached as a PNG under the user's cache directory, keyed by the
project's path, its modification time and its style: a save or a look change
redraws it, nothing else does. No pruning: a few KB each, in a folder the
person may delete at any time.

The cards are handed to the renderer as the preview and the export hand them
(``core.video_common.validated_matches`` then ``cards_on_screen``): the
renderer draws the enriched fields only, so a raw card would draw an empty
panel. The frame is taken halfway into the first card, as the preview takes it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from qurantext.config.paths import DEFAULT_FONT_PATH
from qurantext.config.settings import VIDEO_PRESETS
from qurantext.core.frame_renderer import render_frame_pillow
from qurantext.core.looks import look_from_style
from qurantext.core.video_common import cards_on_screen, validated_matches
from qurantext.jobs.project import Project, job_settings

__all__ = ["LONG_SIDE", "background_for", "cache_key", "thumbnail_for"]

_log = logging.getLogger(__name__)

#: The thumbnail's long side, in pixels.
LONG_SIDE = 96
#: Rendered this many times larger, then shrunk: the renderer's text is laid
#: out for a frame, and a 54 px frame would set it in 2 px letters.
_OVERSAMPLE = 4
#: Folded into every key: bumped when the picture is drawn differently, so a
#: PNG made the old way is never served again (2: the card's text is drawn).
_KEY_VERSION = 2


def cache_key(project: Project) -> str:
    """A name that changes when the file or its look does, and never otherwise."""
    path = project.path
    mtime = path.stat().st_mtime_ns if path is not None and path.exists() else 0
    style = json.dumps(project.style or {}, sort_keys=True)
    raw = f"v{_KEY_VERSION}|{path}|{mtime}|{style}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()  # noqa: S324 - a cache name, not security


def _look(project: Project):
    base_dir = project.path.parent if project.path is not None else None
    return look_from_style(project.style, base_dir=base_dir)


def background_for(project: Project) -> tuple[int, int, int]:
    """The look's frame colour, for the tile drawn when there is no picture."""
    r, g, b, _a = _look(project).frame_bg
    return (r, g, b)


def _size(project: Project) -> tuple[int, int]:
    width, height = VIDEO_PRESETS[job_settings(project).preset][:2]
    if height >= width:
        return (round(LONG_SIDE * width / height), LONG_SIDE)
    return (LONG_SIDE, round(LONG_SIDE * height / width))


def _first_card(project: Project) -> dict | None:
    """The first card the video shows, as the renderer reads it; None when it shows none."""
    cards = cards_on_screen(
        validated_matches(copy.deepcopy(project.cards), bridge_gaps=False),
        project.mode,
        job_settings(project).studied_surah,
    )
    if not cards:
        return None
    return min(cards, key=lambda card: float(card["_start_time"]))


def thumbnail_for(project: Project, cache_dir: Path | None) -> Path | None:
    """The PNG for *project*, made if it is not cached; None when it cannot be.

    None for a project with no card the video would show, no *cache_dir*, a
    cache that cannot be written, or a renderer that raises: the row then
    draws a plain tile.
    """
    if cache_dir is None or not project.cards:
        return None
    try:
        folder = Path(cache_dir) / "thumbs"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{cache_key(project)}.png"
        if target.is_file():
            return target
        card = _first_card(project)
        if card is None:
            return None
        width, height = _size(project)
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
            look=_look(project),
        )
        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        image = Image.fromarray(rgb).resize((width, height), Image.Resampling.LANCZOS)
        _save_atomically(image, target)
        return target
    except Exception as error:  # noqa: BLE001 - a picture is never worth a damaged row
        _log.debug("No thumbnail for %s: %s", project.path, error)
        return None


def _save_atomically(image: Image.Image, target: Path) -> None:
    """Write *image* beside *target*, then move it into place.

    Two reads can overlap (a refresh does not wait for the one before it);
    a reader must find a whole PNG or none, never a half-written one.
    """
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed below, then replaced
        dir=target.parent, prefix=".", suffix=".png.part", delete=False
    )
    try:
        with handle:
            image.save(handle, "PNG")
        os.replace(handle.name, target)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise

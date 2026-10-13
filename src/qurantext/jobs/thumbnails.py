"""A small picture of each job for the home list: its first card at its own look.

Made where the list is read, on the worker thread, with the same renderer the
preview and the export use, so the picture matches the video before any
render exists. Cached as a PNG under the user's cache directory, keyed by the
project's path, its modification time and its style: a save or a look change
redraws it, nothing else does. No pruning: a few KB each, in a folder the
person may delete at any time.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import numpy as np
from PIL import Image

from qurantext.config.paths import DEFAULT_FONT_PATH
from qurantext.config.settings import VIDEO_PRESETS
from qurantext.core.frame_renderer import render_frame_pillow
from qurantext.core.looks import look_from_style
from qurantext.jobs.project import Project, job_settings

__all__ = ["LONG_SIDE", "background_for", "cache_key", "thumbnail_for"]

_log = logging.getLogger(__name__)

#: The thumbnail's long side, in pixels.
LONG_SIDE = 96
#: Rendered this many times larger, then shrunk: the renderer's text is laid
#: out for a frame, and a 54 px frame would set it in 2 px letters.
_OVERSAMPLE = 4


def cache_key(project: Project) -> str:
    """A name that changes when the file or its look does, and never otherwise."""
    path = project.path
    mtime = path.stat().st_mtime_ns if path is not None and path.exists() else 0
    raw = f"{path}|{mtime}|{json.dumps(project.style or {}, sort_keys=True)}"
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


def thumbnail_for(project: Project, cache_dir: Path | None) -> Path | None:
    """The PNG for *project*, made if it is not cached; None when it cannot be.

    None for a project with no cards, no *cache_dir*, a cache that cannot be
    written, or a renderer that raises: the row then draws a plain tile.
    """
    if cache_dir is None or not project.cards:
        return None
    try:
        folder = Path(cache_dir) / "thumbs"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{cache_key(project)}.png"
        if target.is_file():
            return target
        width, height = _size(project)
        card = min(project.cards, key=lambda c: float(c.get("start_time") or 0.0))
        at = float(card.get("start_time") or 0.0)
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
        image.save(target, "PNG")
        return target
    except Exception as error:  # noqa: BLE001 - a picture is never worth a damaged row
        _log.debug("No thumbnail for %s: %s", project.path, error)
        return None

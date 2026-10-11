"""Where a project's look lives on disk: its style entry and its background image.

The person's image is copied next to the project, named by its content, so the
project folder can be moved or shared with the image inside it, and choosing
the same photo twice keeps one copy.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from qurantext.core.looks import (
    IMAGE_SUFFIXES,
    NIGHT_GOLD,
    Look,
    look_from_style,
    merge_style,
)
from qurantext.jobs.project import Project

__all__ = [
    "copy_by_content",
    "has_own_look",
    "import_look_image",
    "look_dir_for",
    "project_look",
    "seed_project_look",
    "set_project_look",
]

#: The style keys a look owns; every other key in a project's style is not its.
_LOOK_KEYS = ("preset", "colours", "background")

#: How much of a source image is read at once while it is hashed and copied.
_CHUNK = 1 << 20


def look_dir_for(project_path: Path) -> Path:
    """``job.qalun.json`` keeps its images in ``job.qalun.look``."""
    return Path(project_path).with_suffix(".look")


def _project_dir(project: Project) -> Path:
    return Path(project.path).parent if project.path is not None else Path.cwd()


def has_own_look(project: Project) -> bool:
    """Whether the project chose a look: its style holds a look key, whatever else it holds."""
    style = project.style
    return isinstance(style, dict) and any(key in style for key in _LOOK_KEYS)


def project_look(project: Project) -> Look:
    return look_from_style(project.style, base_dir=_project_dir(project))


def set_project_look(project: Project, look: Look, *, project_dir: Path | None = None) -> None:
    """Store *look* in the project's style, keeping the keys that are not a look's.

    Night gold is the look of a project that never chose one, so choosing it
    removes the look keys: the style, and with it the content hash, return to
    what they were before any look was chosen.

    The image path is stored relative to *project_dir* when given, else to the
    folder of ``project.path``: a project not yet saved names the folder it
    will be saved in.
    """
    if look == NIGHT_GOLD:
        project.style = {k: v for k, v in project.style.items() if k not in _LOOK_KEYS}
        return
    folder = Path(project_dir) if project_dir is not None else _project_dir(project)
    project.style = merge_style(project.style, look, relative_to=folder)


def seed_project_look(project: Project, project_path: Path, style: dict) -> None:
    """Give a project about to be saved at *project_path* the look *style* describes.

    The look's image is copied beside the project, as choosing it in the review
    would. An image that cannot be copied (gone, not an image, unreadable, a
    folder that refuses it) is not a reason to lose a new job: the look keeps
    naming the image where it was, so the preview and the render fall back to
    the palette's background *and say so* — in the review window's warnings
    strip, and in a render's look warnings (spec §4) — until the person picks
    another image.
    """
    look = look_from_style(style)
    bg = look.background
    if bg.kind == "image" and bg.image is not None:
        try:
            copied = import_look_image(project_path, bg.image)
        except (ValueError, OSError):  # FileNotFoundError is an OSError
            copied = bg.image  # the original, reported where it is used (see above)
        look = replace(look, background=replace(bg, image=copied))
    set_project_look(project, look, project_dir=Path(project_path).parent)


def import_look_image(project_path: Path, source: Path) -> Path:
    """Copy *source* beside the project, named by its content; return the copy.

    See :func:`copy_by_content`, whose errors it raises.
    """
    return copy_by_content(source, look_dir_for(project_path))


def copy_by_content(source: Path, folder: Path) -> Path:
    """Copy *source* into *folder* as ``<sha12><suffix>``; return the copy.

    The source is read once, in chunks, hashing what is written: the copy's
    name is the hash of the bytes it holds even if the source changes while it
    is read, and a large photo is never held in memory whole. The copy lands
    under its final name only when complete, and a failed copy leaves nothing.
    The same bytes copied twice keep one file.

    Raises ``ValueError`` for a type that is not an image the look can show,
    ``FileNotFoundError`` for a missing source, and another ``OSError`` for
    anything the file system refuses (an unreadable source, a read-only
    folder, a folder path that is a file, a full disk).
    """
    source = Path(source).expanduser()
    suffix = source.suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        raise ValueError(f"{source.name}: choose a PNG, JPEG or WebP image.")
    if not source.is_file():
        raise FileNotFoundError(source)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=folder, prefix=".import-", suffix=f"{suffix}.part")
    temporary = Path(name)
    try:
        digest = hashlib.sha256()
        with os.fdopen(handle, "wb") as writer, source.open("rb") as reader:
            while chunk := reader.read(_CHUNK):
                digest.update(chunk)
                writer.write(chunk)
        destination = (folder / f"{digest.hexdigest()[:12]}{suffix}").resolve()
        if destination.is_file():
            temporary.unlink()
        else:
            # A temporary file is private to its owner (0600); the image should
            # be as readable as the project beside it.
            os.chmod(temporary, 0o644)
            temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination

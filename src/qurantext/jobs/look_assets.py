"""Where a project's look lives on disk: its style entry and its background image.

The person's image is copied next to the project, named by its content, so the
project folder can be moved or shared with the image inside it, and choosing
the same photo twice keeps one copy.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from qurantext.core.looks import IMAGE_SUFFIXES, NIGHT_GOLD, Look, look_from_style, merge_style
from qurantext.jobs.project import Project

__all__ = ["import_look_image", "look_dir_for", "project_look", "set_project_look"]

#: The style keys a look owns; every other key in a project's style is not its.
_LOOK_KEYS = ("preset", "colours", "background")


def look_dir_for(project_path: Path) -> Path:
    """``job.qalun.json`` keeps its images in ``job.qalun.look``."""
    return Path(project_path).with_suffix(".look")


def _project_dir(project: Project) -> Path:
    return Path(project.path).parent if project.path is not None else Path.cwd()


def project_look(project: Project) -> Look:
    return look_from_style(project.style, base_dir=_project_dir(project))


def set_project_look(project: Project, look: Look) -> None:
    """Store *look* in the project's style, keeping the keys that are not a look's.

    Night gold is the look of a project that never chose one, so choosing it
    removes the look keys: the style, and with it the content hash, return to
    what they were before any look was chosen.
    """
    if look == NIGHT_GOLD:
        project.style = {k: v for k, v in project.style.items() if k not in _LOOK_KEYS}
        return
    project.style = merge_style(project.style, look, relative_to=_project_dir(project))


def import_look_image(project_path: Path, source: Path) -> Path:
    """Copy *source* beside the project, named by its content; return the copy."""
    source = Path(source).expanduser()
    suffix = source.suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        raise ValueError(f"{source.name}: choose a PNG, JPEG or WebP image.")
    if not source.is_file():
        raise FileNotFoundError(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    folder = look_dir_for(project_path)
    destination = (folder / f"{digest}{suffix}").resolve()
    if not destination.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
    return destination

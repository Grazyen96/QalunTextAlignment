"""Where a lecture's episode lives on disk: its intro, its recitation, its outro.

The intro and outro clips are copied beside the project, named by their
content, so the project folder can be moved or shared with the clips inside it,
and choosing the same clip twice keeps one copy. The recitation is only
referenced, by its project path: it is a live job of its own, which can be
corrected and rendered again, and the episode should use it as it is then.

Paths are stored relative to the project folder when inside it and absolute
otherwise, the rule the look's image follows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qurantext.jobs.look_assets import copy_by_content
from qurantext.jobs.project import Project, _resolve_path, _store_path

__all__ = [
    "EPISODE_SUFFIXES",
    "EpisodeChoice",
    "episode_dir_for",
    "import_episode_clip",
    "project_episode",
    "set_project_episode",
]

#: The clip types an intro or outro can be.
EPISODE_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm")

#: The episode keys the choice owns, in the order they play around the lecture.
_PART_KEYS = ("intro", "recitation", "outro")


@dataclass(frozen=True, slots=True)
class EpisodeChoice:
    """What plays around the lecture: each part is a path, or None when not chosen.

    *intro* and *outro* are video clips; *recitation* is a recitation job's
    project file, whose current video is used.
    """

    intro: Path | None = None
    recitation: Path | None = None
    outro: Path | None = None

    @property
    def parts_set(self) -> tuple[str, ...]:
        """The names of the parts chosen, in playing order."""
        return tuple(key for key in _PART_KEYS if getattr(self, key) is not None)

    @property
    def is_empty(self) -> bool:
        """True when no part is chosen: the lecture is rendered alone."""
        return not self.parts_set


def episode_dir_for(project_path: Path) -> Path:
    """``job.qalun.json`` keeps its episode clips in ``job.qalun.episode``."""
    return Path(project_path).with_suffix(".episode")


def import_episode_clip(project_path: Path, source: Path) -> Path:
    """Copy the clip *source* beside the project, named by its content; return the copy.

    See :func:`~qurantext.jobs.look_assets.copy_by_content`, whose errors it
    raises: ``ValueError`` for a type not in :data:`EPISODE_SUFFIXES`,
    ``FileNotFoundError`` for a missing clip, another ``OSError`` for anything
    the file system refuses.
    """
    return copy_by_content(source, episode_dir_for(project_path), suffixes=EPISODE_SUFFIXES)


def _project_dir(project: Project) -> Path | None:
    return Path(project.path).parent if project.path is not None else None


def project_episode(project: Project) -> EpisodeChoice:
    """The project's episode, with each path resolved against the project folder.

    The file can be hand-edited or written by a newer build, so a value that is
    not a non-empty string reads as "not chosen" rather than failing, and so
    does an intro or outro whose type is not one of :data:`EPISODE_SUFFIXES`.
    """
    episode = project.episode if isinstance(project.episode, dict) else {}
    folder = _project_dir(project)

    def part(key: str) -> Path | None:
        value = episode.get(key)
        if not isinstance(value, str) or not value:
            return None
        path = _resolve_path(value, folder)
        if key != "recitation" and path.suffix.lower() not in EPISODE_SUFFIXES:
            return None
        return path

    return EpisodeChoice(*(part(key) for key in _PART_KEYS))


def set_project_episode(
    project: Project, choice: EpisodeChoice, *, project_dir: Path | None = None
) -> None:
    """Store *choice* in the project's episode, keeping the keys that are not a part.

    Each path is stored relative to *project_dir* when given, else to the
    folder of ``project.path`` (a project not yet saved names the folder it
    will be saved in), and absolute when it is outside that folder or when no
    folder is known: a project with no file and no *project_dir*. A part not
    chosen is removed rather than written as null, so an empty choice returns
    the episode, and with it the content hash, to what it was before any was
    chosen.
    """
    folder = Path(project_dir) if project_dir is not None else _project_dir(project)
    # _store_path(..., None) is absolute: a relative path with nothing known to
    # be relative to would be read later against the project's folder and miss.
    current = project.episode if isinstance(project.episode, dict) else {}
    episode = {k: v for k, v in current.items() if k not in _PART_KEYS}
    for key in _PART_KEYS:
        value = getattr(choice, key)
        if value is not None:
            episode[key] = _store_path(Path(value), folder)
    project.episode = episode

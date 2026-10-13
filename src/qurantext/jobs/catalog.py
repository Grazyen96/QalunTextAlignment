"""Every job the app has made, and what state each is in.

The home window lists these so a job can be reopened without hunting for files.
The project files are the record; nothing else is kept. A file that cannot be
read is listed as damaged rather than skipped, so a job never silently vanishes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qurantext.config.paths import LECTURE_MATCHING_OUTPUT_DIR, RECITATION_MATCHING_OUTPUT_DIR
from qurantext.jobs.project import Project, job_settings, load_project
from qurantext.jobs.thumbnails import background_for, thumbnail_for
from qurantext.utils.progress import CancelToken

__all__ = [
    "CHANGED_SINCE_RENDER",
    "DAMAGED",
    "NEEDS_REVIEW",
    "RENDERED",
    "REVIEWED",
    "JobEntry",
    "ayah_range",
    "default_job_dirs",
    "job_dirs_for",
    "job_status",
    "list_jobs",
]

NEEDS_REVIEW = "needs_review"
REVIEWED = "reviewed"
RENDERED = "rendered"
CHANGED_SINCE_RENDER = "changed_since_render"
DAMAGED = "damaged"


@dataclass(frozen=True, slots=True)
class JobEntry:
    """One row of the job list.

    A damaged entry whose file could not be read carries ``mode=""``, since the
    mode is only known from the file's contents.
    """

    project: Path
    name: str
    mode: str
    status: str
    modified: float
    card_count: int = 0
    ayah_range: str | None = None
    error: str | None = None
    #: The cached picture of the first card, when one could be made.
    thumbnail: Path | None = None
    #: The look's frame colour, for the tile drawn without a picture.
    background: tuple[int, int, int] | None = None


def _background(project: Project) -> tuple[int, int, int] | None:
    try:
        return background_for(project)
    except Exception:  # noqa: BLE001 - a look that cannot be read is not a damaged job
        return None


def job_status(project: Project) -> str:
    if project.render is not None:
        if project.render_is_stale or _choices_changed_since_render(project):
            return CHANGED_SINCE_RENDER
        return RENDERED
    return REVIEWED if project.review.get("state") == "reviewed" else NEEDS_REVIEW


def _choices_changed_since_render(project: Project) -> bool:
    """Whether the job now asks for another size or subtitle choice than its video has.

    A job re-run as "landscape" or "files beside the video" keeps its old
    render record, and that video is no longer what rendering would make. A
    choice the record does not hold (an older render) is not second-guessed.
    """
    render = project.render or {}
    settings = job_settings(project)
    preset, subtitles = render.get("preset"), render.get("subtitles")
    if isinstance(preset, str) and preset != settings.preset:
        return True
    return isinstance(subtitles, str) and subtitles != settings.subtitles


def ayah_range(cards: list[dict[str, Any]]) -> str | None:
    """``25:7–11`` for the span the cards cover (``25:7`` for one ayah), or None when none names a surah."""
    ayat = [c for c in cards if c.get("kind") != "preamble" and c.get("surah_num") is not None]
    if not ayat:
        return None
    first, last = ayat[0], ayat[-1]
    s1, a1 = int(first["surah_num"]), int(first["from_ayah"])
    s2, a2 = int(last["surah_num"]), int(last["to_ayah"])
    if s1 != s2:
        return f"{s1}:{a1}–{s2}:{a2}"
    return f"{s1}:{a1}" if a1 == a2 else f"{s1}:{a1}–{a2}"


def default_job_dirs() -> list[Path]:
    return [RECITATION_MATCHING_OUTPUT_DIR, LECTURE_MATCHING_OUTPUT_DIR]


def job_dirs_for(extra: Iterable[Path]) -> list[Path]:
    """``default_job_dirs()`` plus *extra*, deduped by resolved path, order kept.

    The job list scans the default matching folders plus every output folder
    the person has chosen (``Prefs.job_dirs``), so a job rendered somewhere
    unusual is still found without adding that folder twice.
    """
    dirs = default_job_dirs()
    seen = {folder.resolve() for folder in dirs}
    for folder in extra:
        folder = Path(folder)
        resolved = folder.resolve()
        if resolved not in seen:
            seen.add(resolved)
            dirs.append(folder)
    return dirs


def _entry_for(path: Path, *, thumbnail_cache: Path | None = None) -> JobEntry | None:
    """Build an entry for *path*, or None if the file vanished."""
    try:
        modified = path.stat().st_mtime
    except FileNotFoundError:
        return None
    except OSError as error:
        return JobEntry(
            project=path,
            name=path.name.removesuffix(".qalun.json"),
            mode="",
            status=DAMAGED,
            modified=0.0,
            error=str(error),
        )

    try:
        project = load_project(path)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return JobEntry(
            project=path,
            name=path.name.removesuffix(".qalun.json"),
            mode="",
            status=DAMAGED,
            modified=modified,
            error=str(error),
        )

    try:
        status = job_status(project)
        range_str = ayah_range(project.cards)
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        return JobEntry(
            project=path,
            name=Path(project.audio).stem,
            mode=project.mode,
            status=DAMAGED,
            modified=modified,
            error=str(error),
        )

    return JobEntry(
        project=path,
        name=Path(project.audio).stem,
        mode=project.mode,
        status=status,
        modified=modified,
        card_count=len(project.cards),
        ayah_range=range_str,
        thumbnail=thumbnail_for(project, thumbnail_cache),
        background=_background(project),
    )


def list_jobs(
    dirs: Iterable[Path] | None = None,
    *,
    hidden: frozenset[Path] = frozenset(),
    cancel: CancelToken | None = None,
    thumbnail_cache: Path | None = None,
) -> list[JobEntry]:
    """Projects under *dirs*, newest first.

    Folders are deduped by resolved path, so the same folder listed twice
    (the default matching folder chosen again as an output folder, say) lists
    its jobs once. A project whose resolved path is in *hidden* is skipped —
    "Remove from list" adds it there without touching the file.

    *cancel* is checked before each folder and each file, raising
    ``JobCancelled``: a folder on a slow drive must not hold up a window that
    is closing for as long as the whole read would take.
    """
    entries: list[JobEntry] = []
    seen: set[Path] = set()
    for folder in dirs if dirs is not None else default_job_dirs():
        if cancel is not None:
            cancel.raise_if_cancelled("listing jobs")
        resolved = Path(folder).resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not resolved.is_dir():
            continue
        for path in resolved.glob("*.qalun.json"):
            if cancel is not None:
                cancel.raise_if_cancelled("listing jobs")
            if path.resolve() in hidden:
                continue
            entry = _entry_for(path, thumbnail_cache=thumbnail_cache)
            if entry is not None:
                entries.append(entry)
    entries.sort(key=lambda entry: entry.modified, reverse=True)
    return entries

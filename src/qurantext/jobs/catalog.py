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
from qurantext.jobs.project import Project, load_project

__all__ = [
    "CHANGED_SINCE_RENDER",
    "DAMAGED",
    "NEEDS_REVIEW",
    "RENDERED",
    "REVIEWED",
    "JobEntry",
    "ayah_range",
    "default_job_dirs",
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
    """One row of the job list."""

    project: Path
    name: str
    mode: str
    status: str
    modified: float
    card_count: int = 0
    ayah_range: str | None = None
    error: str | None = None


def job_status(project: Project) -> str:
    if project.render is not None:
        return CHANGED_SINCE_RENDER if project.render_is_stale else RENDERED
    return REVIEWED if project.review.get("state") == "reviewed" else NEEDS_REVIEW


def ayah_range(cards: list[dict[str, Any]]) -> str | None:
    """``25:7–11`` for the span the cards cover, or None when none names a surah."""
    ayat = [c for c in cards if c.get("kind") != "preamble" and c.get("surah_num") is not None]
    if not ayat:
        return None
    first, last = ayat[0], ayat[-1]
    s1, a1 = int(first["surah_num"]), int(first["from_ayah"])
    s2, a2 = int(last["surah_num"]), int(last["to_ayah"])
    return f"{s1}:{a1}–{a2}" if s1 == s2 else f"{s1}:{a1}–{s2}:{a2}"


def default_job_dirs() -> list[Path]:
    return [RECITATION_MATCHING_OUTPUT_DIR, LECTURE_MATCHING_OUTPUT_DIR]


def list_jobs(dirs: Iterable[Path] | None = None) -> list[JobEntry]:
    """Projects under *dirs*, newest first."""
    entries: list[JobEntry] = []
    for folder in dirs if dirs is not None else default_job_dirs():
        folder = Path(folder)
        if not folder.is_dir():
            continue
        for path in folder.glob("*.qalun.json"):
            modified = path.stat().st_mtime
            try:
                project = load_project(path)
            except (OSError, ValueError, KeyError, TypeError) as error:
                entries.append(
                    JobEntry(
                        project=path,
                        name=path.name.removesuffix(".qalun.json"),
                        mode="",
                        status=DAMAGED,
                        modified=modified,
                        error=str(error),
                    )
                )
                continue
            entries.append(
                JobEntry(
                    project=path,
                    name=Path(project.audio).stem,
                    mode=project.mode,
                    status=job_status(project),
                    modified=modified,
                    card_count=len(project.cards),
                    ayah_range=ayah_range(project.cards),
                )
            )
    entries.sort(key=lambda entry: entry.modified, reverse=True)
    return entries

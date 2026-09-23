"""What the window asks the pipeline to do, as one call.

Kept apart from the widgets so it can be tested without a screen: this module
decides the stages, the filenames and the order, and the window only collects
the inputs and draws what comes back. Matching and rendering are separate
calls, so the window can put review between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from qurantext.config.paths import (
    LECTURE_MATCHING_OUTPUT_DIR,
    RECITATION_MATCHING_OUTPUT_DIR,
    VIDEOS_OUTPUT_DIR,
)
from qurantext.jobs.project import Project, save_project
from qurantext.jobs.project_render import render_project
from qurantext.pipelines.detection import run_detection, run_recitation_range
from qurantext.utils.progress import CancelToken, ProgressCallback, report

__all__ = [
    "JobSpec",
    "JobOutcome",
    "project_path_for",
    "run_matching",
    "run_render",
    "run_job",
]


@dataclass(frozen=True, slots=True)
class JobSpec:
    """Everything the window collected before Start was pressed."""

    audio: Path
    quran: Path
    mode: str = "recitation"
    #: Stated range. All three set means detection is skipped entirely.
    surah_num: int | None = None
    from_ayah: int | None = None
    to_ayah: int | None = None
    preset: str = "social"
    render: bool = True
    #: Render as soon as matching finishes, skipping review. For jobs you trust.
    render_right_away: bool = False
    output_dir: Path | None = None

    @property
    def has_stated_range(self) -> bool:
        return (
            self.mode == "recitation"
            and self.surah_num is not None
            and self.from_ayah is not None
            and self.to_ayah is not None
        )

    def validate(self) -> str | None:
        """Return a message to show the user, or None when the job can run."""
        if not self.audio or not Path(self.audio).is_file():
            return "Choose an audio file."
        if not self.quran or not Path(self.quran).is_file():
            return "Choose the Quran text file."
        if self.mode == "recitation" and not self.has_stated_range:
            return "Choose the surah and the ayah range."
        if self.has_stated_range and self.to_ayah < self.from_ayah:  # type: ignore[operator]
            return "The last ayah cannot come before the first."
        return None


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """What a finished job produced, for the window to offer."""

    matches: Path
    video: Path | None
    cards: int
    mode: str
    project: Path | None = None
    subtitles: tuple[Path, ...] = ()


def project_path_for(match_path: Path) -> Path:
    """Where a job's project lives: beside its match file."""
    return Path(match_path).with_suffix(".qalun.json")


def _set_aside(path: Path) -> None:
    """Keep an earlier project instead of overwriting its corrections."""
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        stem = path.name.removesuffix(".qalun.json")
        backup = path.with_name(f"{stem}.{stamp}.qalun-backup.json")
        count = 2
        while backup.exists():
            backup = path.with_name(f"{stem}.{stamp}-{count}.qalun-backup.json")
            count += 1
        path.rename(backup)


def run_matching(
    spec: JobSpec,
    *,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> Project:
    """Find or align the ayat, then write the project the review opens."""
    audio = Path(spec.audio)
    match_dir = Path(
        spec.output_dir
        or (
            RECITATION_MATCHING_OUTPUT_DIR
            if spec.mode == "recitation"
            else LECTURE_MATCHING_OUTPUT_DIR
        )
    )
    match_path = match_dir / f"{audio.stem}_{spec.mode}.json"

    if spec.has_stated_range:
        report(progress, "detect", "Aligning against the ayat you chose...")
        run_recitation_range(
            quran=spec.quran,
            output=match_path,
            surah_num=spec.surah_num,  # type: ignore[arg-type]
            from_ayah=spec.from_ayah,  # type: ignore[arg-type]
            to_ayah=spec.to_ayah,  # type: ignore[arg-type]
            audio=audio,
            echo=False,
            progress=progress,
            cancel=cancel,
        )
    else:
        report(progress, "detect", "Looking for Quran in the audio...")
        run_detection(
            quran=spec.quran,
            output=match_path,
            mode=spec.mode,
            audio=audio,
            echo=False,
            progress=progress,
            cancel=cancel,
        )

    project = Project.from_match_file(match_path, audio, mode=spec.mode)
    destination = project_path_for(match_path)
    _set_aside(destination)
    save_project(project, destination)
    return project


def run_render(
    project: Project,
    *,
    preset: str = "social",
    subtitles: str = "burn",
    formats: tuple[str, ...] = ("srt",),
    output_dir: Path | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> JobOutcome:
    """Render the project — with whatever corrections it now holds."""
    video_dir = Path(output_dir or VIDEOS_OUTPUT_DIR)
    result = render_project(
        project,
        video_dir / f"{Path(project.audio).stem}.mp4",
        preset=preset,
        subtitles=subtitles,
        formats=formats,
        progress=progress,
        cancel=cancel,
    )
    return JobOutcome(
        matches=Path(project.matches),
        video=result.video,
        cards=len(project.cards),
        mode=project.mode,
        project=project.path,
        subtitles=tuple(result.subtitles),
    )


def run_job(
    spec: JobSpec,
    *,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> JobOutcome:
    """Match, then render. Both stages report progress and honour Cancel."""
    project = run_matching(spec, progress=progress, cancel=cancel)
    if not spec.render:
        return JobOutcome(
            matches=Path(project.matches),
            video=None,
            cards=len(project.cards),
            mode=spec.mode,
            project=project.path,
        )
    if cancel is not None:
        cancel.raise_if_cancelled("render")
    return run_render(
        project, preset=spec.preset, output_dir=spec.output_dir, progress=progress, cancel=cancel
    )

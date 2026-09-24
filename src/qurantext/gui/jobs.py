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
from qurantext.gui.i18n import t
from qurantext.jobs.project import (
    JobSettings,
    Project,
    job_settings,
    load_project,
    project_path_for,
    save_project,
    set_job_settings,
)
from qurantext.jobs.project_render import render_project
from qurantext.pipelines.detection import run_detection, run_recitation_range
from qurantext.utils.progress import CancelToken, ProgressCallback, report

__all__ = [
    "JobSpec",
    "JobOutcome",
    "match_path_for",
    "project_path_for",
    "run_matching",
    "run_render",
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
    #: One of ``SUBTITLE_CHOICES``: in the picture, in files beside it, or both.
    subtitles: str = "burn"
    #: Subtitle file formats, when files are written.
    formats: tuple[str, ...] = ("srt",)
    #: Render as soon as matching finishes, skipping review. For jobs you trust.
    render_right_away: bool = False
    output_dir: Path | None = None

    @property
    def settings(self) -> JobSettings:
        """The output choices, as the project keeps them."""
        return JobSettings(
            preset=self.preset,
            subtitles=self.subtitles,
            formats=tuple(self.formats),
            output_dir=Path(self.output_dir) if self.output_dir else None,
        )

    @property
    def has_stated_range(self) -> bool:
        return (
            self.mode == "recitation"
            and self.surah_num is not None
            and self.from_ayah is not None
            and self.to_ayah is not None
        )

    def validate(self) -> str | None:
        """Return an i18n key describing what is missing, or None when the job can run.

        A key rather than English text, so the window can show it translated
        (``qurantext.gui.i18n.t``) instead of baking one language into the model.
        """
        if not self.audio or not Path(self.audio).is_file():
            return "job.need_audio"
        if not self.quran or not Path(self.quran).is_file():
            return "job.need_quran"
        if self.mode == "recitation" and not self.has_stated_range:
            return "job.need_range"
        if self.has_stated_range and self.to_ayah < self.from_ayah:  # type: ignore[operator]
            return "job.bad_range"
        if self.subtitles in ("sidecar", "both") and not self.formats:
            # Files beside the video, in no format, would write nothing.
            return "job.need_format"
        return None


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """What a finished job produced, for the window to offer."""

    matches: Path
    video: Path | None
    cards: int
    project: Path | None = None


def _set_aside(path: Path) -> Path | None:
    """Keep an earlier project instead of overwriting its corrections.

    Returns where it went, or None when there was nothing to keep.
    """
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    stem = path.name.removesuffix(".qalun.json")
    backup = path.with_name(f"{stem}.{stamp}.qalun-backup.json")
    count = 2
    while backup.exists():
        backup = path.with_name(f"{stem}.{stamp}-{count}.qalun-backup.json")
        count += 1
    path.rename(backup)
    return backup


_UNCHANGED = "unchanged"


def _keep_earlier(destination: Path, derived: Project) -> Path | str | None:
    """Back up the project at *destination* unless re-matching reproduced it exactly.

    Returns the backup path, ``"unchanged"`` when the existing project already
    holds exactly what re-matching derived (it is then left alone, review state,
    render record and all), or None when there was nothing there.

    A re-match that yields the same cards and captions has nothing to lose, and a
    backup per run would bury the one that matters. A file that cannot be read
    is always kept: what it held cannot be compared.
    """
    if not destination.exists():
        return None
    try:
        unchanged = load_project(destination).content_hash() == derived.content_hash()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        unchanged = False
    if unchanged:
        return _UNCHANGED
    return _set_aside(destination)


def match_path_for(spec: JobSpec) -> Path:
    """The match file *spec* writes; its project goes beside it (``project_path_for``).

    The one place the rule lives, so the window can tell before Start which
    project a job will replace (and refuse while that project is open in a review).
    """
    match_dir = Path(
        spec.output_dir
        or (
            RECITATION_MATCHING_OUTPUT_DIR
            if spec.mode == "recitation"
            else LECTURE_MATCHING_OUTPUT_DIR
        )
    )
    return match_dir / f"{Path(spec.audio).stem}_{spec.mode}.json"


def run_matching(
    spec: JobSpec,
    *,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> Project:
    """Find or align the ayat, then write the project the review opens.

    An earlier project for the same match file is kept as a backup when its
    content differs, and the backup is reported as progress.
    """
    audio = Path(spec.audio)
    match_path = match_path_for(spec)

    if spec.has_stated_range:
        report(progress, "detect", t("job.progress.aligning"), translated=True)
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
        report(progress, "detect", t("job.progress.detecting"), translated=True)
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
    set_job_settings(project, spec.settings)
    destination = project_path_for(match_path)
    kept = _keep_earlier(destination, project)
    if kept == _UNCHANGED:
        # Same content: leave the file alone (review state, render record and
        # all) unless this run chose differently, and then change only that.
        existing = load_project(destination)
        if job_settings(existing) != job_settings(project):
            set_job_settings(existing, job_settings(project))
            save_project(existing, destination)
        return existing
    if isinstance(kept, Path):
        report(progress, "detect", t("job.progress.kept", name=kept.name), translated=True)
    save_project(project, destination)
    return project


def run_render(
    project: Project,
    *,
    preset: str | None = None,
    subtitles: str | None = None,
    formats: tuple[str, ...] | None = None,
    output_dir: Path | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> JobOutcome:
    """Render the project — with whatever corrections it now holds.

    The preset, subtitles, formats and folder are the job's own
    (:func:`~qurantext.jobs.project.job_settings`), so a render from the review
    makes what the job was started for. A keyword given here wins over the
    job's choice; None means "use the job's".
    """
    settings = job_settings(project)
    video_dir = Path(output_dir or settings.output_dir or VIDEOS_OUTPUT_DIR)
    result = render_project(
        project,
        video_dir / f"{Path(project.audio).stem}.mp4",
        preset=preset if preset is not None else settings.preset,
        subtitles=subtitles if subtitles is not None else settings.subtitles,
        formats=tuple(formats) if formats is not None else settings.formats,
        progress=progress,
        cancel=cancel,
    )
    return JobOutcome(
        matches=Path(project.matches),
        video=result.video,
        cards=len(project.cards),
        project=project.path,
    )

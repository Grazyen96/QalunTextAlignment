"""What the window asks the pipeline to do, as one call.

Kept apart from the widgets so it can be tested without a screen: this module
decides the stages, the filenames and the order, and the window only collects
the inputs and draws what comes back.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qurantext.config.paths import (
    LECTURE_MATCHING_OUTPUT_DIR,
    RECITATION_MATCHING_OUTPUT_DIR,
    VIDEOS_OUTPUT_DIR,
)
from qurantext.jobs.render import RenderRequest, render_video
from qurantext.pipelines.detection import run_detection, run_recitation_range
from qurantext.utils.progress import CancelToken, ProgressCallback, report

__all__ = ["JobSpec", "JobOutcome", "run_job"]


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


def run_job(
    spec: JobSpec,
    *,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> JobOutcome:
    """Match, then render. Both stages report progress and honour Cancel."""
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
        result = run_recitation_range(
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
        result = run_detection(
            quran=spec.quran,
            output=match_path,
            mode=spec.mode,
            audio=audio,
            echo=False,
            progress=progress,
            cancel=cancel,
        )

    cards = len(result.get("matches") or [])
    if not spec.render:
        return JobOutcome(matches=match_path, video=None, cards=cards, mode=spec.mode)

    if cancel is not None:
        cancel.raise_if_cancelled("render")

    video_dir = Path(spec.output_dir or VIDEOS_OUTPUT_DIR)
    video_path = video_dir / f"{audio.stem}.mp4"
    render_result = render_video(
        RenderRequest(
            audio=audio,
            matches=match_path,
            output=video_path,
            preset=spec.preset,
        ),
        progress=progress,
        cancel=cancel,
    )
    return JobOutcome(matches=match_path, video=render_result.output, cards=cards, mode=spec.mode)

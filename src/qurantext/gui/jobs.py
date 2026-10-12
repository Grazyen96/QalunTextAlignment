"""What the window asks the pipeline to do, as one call.

Kept apart from the widgets so it can be tested without a screen: this module
decides the stages, the filenames and the order, and the window only collects
the inputs and draws what comes back. Matching and rendering are separate
calls, so the window can put review between them.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from qurantext.config.paths import (
    LECTURE_MATCHING_OUTPUT_DIR,
    QURAN_DB_PATH,
    RECITATION_MATCHING_OUTPUT_DIR,
)
from qurantext.data.quran_db import stored_surah_names
from qurantext.gui.i18n import t
from qurantext.jobs.episode import (
    EpisodeError,
    assemble_episode,
    episode_path_for,
    recitation_video,
)
from qurantext.jobs.episode_assets import (
    EpisodeChoice,
    GeneratedIntro,
    GeneratedOutro,
    project_episode,
    seed_project_episode,
)
from qurantext.jobs.generated_parts import (
    ensure_generated_part,
    intro_spec_for,
    outro_spec_for,
)
from qurantext.jobs.look_assets import project_look, seed_project_look
from qurantext.jobs.project import (
    JobSettings,
    Project,
    job_settings,
    load_project,
    project_path_for,
    save_project,
    set_job_settings,
)
from qurantext.jobs.project_render import (
    default_video_path,
    export_project_subtitles,
    render_project,
)
from qurantext.pipelines.detection import run_detection, run_recitation_range
from qurantext.utils.progress import (
    CancelToken,
    JobCancelled,
    ProgressCallback,
    ProgressEvent,
    report,
)

__all__ = [
    "JobSpec",
    "JobOutcome",
    "match_path_for",
    "project_path_for",
    "run_matching",
    "run_render",
]

_log = logging.getLogger(__name__)


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
    #: "local" (this computer) or "whisperx" (Replicate). Never switched automatically.
    engine: str = "local"
    output_dir: Path | None = None
    #: The look a brand-new project starts with, as a project style (the
    #: person's default look); empty for Night gold. A re-match never uses it:
    #: the video already has its own look.
    style: dict = field(default_factory=dict)
    #: The surah a lecture's cards keep to; None guesses it. A recitation
    #: states its range instead and ignores this.
    studied_surah: int | None = None
    #: The intro and outro a brand-new lecture starts with (the person's
    #: default episode), as absolute paths; None for a part not set. Like the
    #: look, a re-match never uses them, and a recitation ignores them.
    episode_defaults: tuple[str | None, str | None] = (None, None)
    #: Their original file names, shown in the Episode dialog (the copies are
    #: named by their content); None when unknown.
    episode_default_names: tuple[str | None, str | None] = (None, None)
    #: The default generated intro and outro settings, for a part whose
    #: default is generated rather than a clip (it then has no clip); nothing
    #: is copied for them. Like the clips, only a brand-new lecture uses them.
    episode_generated: tuple[GeneratedIntro | None, GeneratedOutro | None] = (None, None)

    @property
    def settings(self) -> JobSettings:
        """The output choices, as the project keeps them."""
        return JobSettings(
            preset=self.preset,
            subtitles=self.subtitles,
            formats=tuple(self.formats),
            output_dir=Path(self.output_dir) if self.output_dir else None,
            studied_surah=self.studied_surah if self.mode == "lecture" else None,
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
    #: What the look could not do (``image_missing``, ``image_unreadable``):
    #: the video was made with the preset's background instead.
    look_warnings: tuple[str, ...] = ()
    #: The chosen studied surah when none of its ayat had a card, so the video
    #: shows only its opening title card; None otherwise.
    studied_surah_missing: int | None = None
    #: The joined episode (``<stem> – episode.mp4``) when a lecture's episode
    #: was made; None when none was chosen or it failed.
    episode_video: Path | None = None
    #: Why the episode could not be made, already in the window's language;
    #: the lecture's own video is kept whatever it says.
    episode_error: str | None = None


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

    The look, the episode and the output choices are compared on neither side
    (the output choices are the run's own and are written either way), and when
    the content changed the earlier project's style (its look) and episode are
    carried into *derived*: a re-match derives cards and captions only, and the
    look and the intro, recitation and outro the person chose for this video
    are not something it could have changed. The style's image path and the
    episode's clip paths stay valid, as the new project takes the earlier one's
    name and folder.
    For the same reason a studied surah the earlier project chose is carried
    when this run left it to "Detect automatically" (``_with_earlier_surah``).
    """
    if not destination.exists():
        return None
    earlier: Project | None = None
    try:
        earlier = load_project(destination)
        # Content only: the look, the episode and the output choices (the
        # studied surah among them) are not what matching derives.
        unchanged = (
            replace(earlier, style={}, export={}, episode={}).content_hash()
            == replace(derived, style={}, export={}, episode={}).content_hash()
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        earlier, unchanged = None, False
    if unchanged:
        return _UNCHANGED
    if earlier is not None:
        derived.style = copy.deepcopy(earlier.style)
        derived.episode = copy.deepcopy(earlier.episode)
        set_job_settings(derived, _with_earlier_surah(job_settings(derived), earlier))
    return _set_aside(destination)


def _with_earlier_surah(settings: JobSettings, earlier: Project) -> JobSettings:
    """*settings*, keeping *earlier*'s studied surah when they leave it to the guess.

    "Detect automatically" on the new-job screen is the default, not a decision
    to undo one: a surah chosen in the review (or an earlier run) is the
    person's, and a re-match cannot know better. A surah picked explicitly for
    this run wins.
    """
    if settings.studied_surah is not None:
        return settings
    return replace(settings, studied_surah=job_settings(earlier).studied_surah)


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
    notices: list[str] | None = None,
) -> Project:
    """Find or align the ayat, then write the project the review opens.

    An earlier project for the same match file is kept as a backup when its
    content differs, and the backup is reported as progress. What a new
    lecture's default episode could not do (a default clip gone) is reported
    as progress too, and appended to *notices*, already in the window's
    language, for a window that keeps it on screen after the job.
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
            engine=spec.engine,
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
            engine=spec.engine,
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
        chosen = _with_earlier_surah(job_settings(project), existing)
        if job_settings(existing) != chosen:
            set_job_settings(existing, chosen)
            save_project(existing, destination)
        return existing
    if isinstance(kept, Path):
        report(progress, "detect", t("job.progress.kept", name=kept.name), translated=True)
    elif kept is None:
        # Nothing was there: a brand-new video starts with the default look,
        # and a brand-new lecture with the default intro and outro.
        if spec.style:
            seed_project_look(project, destination, spec.style)
        if spec.mode == "lecture" and (any(spec.episode_defaults) or any(spec.episode_generated)):
            intro, outro = (Path(clip) if clip else None for clip in spec.episode_defaults)
            # A default clip that is gone is left out, and said as the backup is.
            seeded = seed_project_episode(
                project,
                destination,
                intro,
                outro,
                names=spec.episode_default_names,
                generated=spec.episode_generated,
            )
            for key, fmt in seeded:
                said = t(key, part=t(f"episode.part.{fmt['part']}"))
                report(progress, "detect", said, translated=True)
                if notices is not None:
                    notices.append(said)
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
    chosen_subtitles = subtitles if subtitles is not None else settings.subtitles
    chosen_formats = tuple(formats) if formats is not None else settings.formats
    lecture = str(project.mode).lower() == "lecture"
    # With an episode to follow, the lecture's render is its first step, and
    # is named so ("Rendering the lecture"), as the recitation and join are.
    with_episode = lecture and not project_episode(project).is_empty
    result = render_project(
        project,
        default_video_path(project, output_dir=output_dir),
        preset=preset if preset is not None else settings.preset,
        subtitles=chosen_subtitles,
        formats=chosen_formats,
        progress=_as_stage(progress, "episode_lecture") if with_episode else progress,
        cancel=cancel,
    )
    episode_video: Path | None = None
    episode_error: str | None = None
    if lecture:
        episode_video, episode_error = _make_episode(
            project,
            Path(result.video),
            subtitles=chosen_subtitles,
            formats=chosen_formats,
            progress=progress,
            cancel=cancel,
        )
    return JobOutcome(
        matches=Path(project.matches),
        video=result.video,
        cards=len(project.cards),
        project=project.path,
        look_warnings=result.render.look_warnings if result.render is not None else (),
        studied_surah_missing=(
            result.render.studied_surah_missing if result.render is not None else None
        ),
        episode_video=episode_video,
        episode_error=episode_error,
    )


def _make_episode(
    project: Project,
    lecture: Path,
    *,
    subtitles: str,
    formats: tuple[str, ...],
    progress: ProgressCallback | None,
    cancel: CancelToken | None,
) -> tuple[Path | None, str | None]:
    """Join the lecture just rendered (*lecture*) with its episode's parts.

    Returns the episode written (None when the episode has no part besides
    the lecture, or it could not be made) and what went wrong, in the window's
    language (None when nothing did). The lecture is complete and recorded by
    now, so nothing here may make the job read as stopped or failed: a cancel
    during the episode, and any error, end in the second value, and the job
    finishes with the lecture's outcome. The join leaves no partial file.
    """
    try:
        return _join_episode(
            project, lecture, subtitles=subtitles, formats=formats, progress=progress, cancel=cancel
        )
    except EpisodeError as error:
        return None, t(error.key, **error.fmt)
    except JobCancelled:
        return None, t("episode.error.cancelled")
    except Exception as error:  # noqa: BLE001 — the lecture's render must stand
        # Not a failure the episode foresaw: the person gets a sentence, and
        # whoever reads the log gets the traceback a bug needs.
        _log.error("The episode step failed unexpectedly", exc_info=True)
        return None, t("episode.error.ffmpeg", reason=str(error) or type(error).__name__)


#: The parts a person adds as clips, by the name the window gives them.
_CLIP_PARTS = ("intro", "outro")


def _part_error(error: EpisodeError, clips: dict[str, Path]) -> EpisodeError:
    """*error*, said as "the intro clip …" when it names a clip by its copy's file name.

    The copies beside the project are named by their content (``3f2a9c1b2d4e.mp4``),
    which tells the person nothing about which part is meant.
    """
    kind = {"episode.error.missing": "missing", "episode.error.not_video": "not_video"}.get(
        error.key
    )
    if kind is None:
        return error
    for part, clip in clips.items():
        if error.fmt.get("name") == clip.name:
            return EpisodeError(f"episode.error.part_{kind}", part=t(f"episode.part.{part}"))
    return error


def _join_episode(
    project: Project,
    lecture: Path,
    *,
    subtitles: str,
    formats: tuple[str, ...],
    progress: ProgressCallback | None,
    cancel: CancelToken | None,
) -> tuple[Path | None, str | None]:
    """:func:`_make_episode`'s work; raises :class:`EpisodeError` for what stops it.

    The intro and outro are looked for first, so a missing outro is said
    before minutes are spent rendering the recitation; a generated intro or
    outro is made then too, at the size and rate the lecture was just
    rendered at, for the same reason (a link too long for a QR code at this
    size stops the episode at once). When the job writes
    subtitle files, the episode gets its own, holding the lecture's cues moved
    to where the lecture starts in it. The episode is recorded in the
    project's render before they are written: a subtitle file that cannot be
    written leaves the episode made, and says so.
    """
    choice = project_episode(project)
    if choice.is_empty:
        return None, None
    clips = {part: getattr(choice, part) for part in _CLIP_PARTS if getattr(choice, part)}
    for part, clip in clips.items():
        if not clip.is_file():
            raise EpisodeError("episode.error.part_missing", part=t(f"episode.part.{part}"))
    made: dict[str, Path] = {}
    if any(choice.is_generated(part) for part in _CLIP_PARTS):
        made = _generated_parts(
            project, choice, *_lecture_geometry(project), progress=progress, cancel=cancel
        )
    intro, outro = made.get("intro", choice.intro), made.get("outro", choice.outro)
    recitation: Path | None = None
    if choice.recitation is not None:
        report(
            progress,
            "episode_recitation",
            t("job.stage.episode_recitation"),
            translated=True,
        )
        recitation = recitation_video(
            choice.recitation,
            avoid=lecture,
            progress=_as_stage(progress, "episode_recitation"),
            cancel=cancel,
        )
    parts = [p for p in (intro, recitation) if p is not None]
    lecture_index = len(parts)
    parts.append(lecture)
    if outro is not None:
        parts.append(outro)
    if len(parts) == 1:
        return None, None
    width, height, fps = _lecture_geometry(project)
    report(progress, "episode_join", t("job.stage.episode_join"), translated=True)
    try:
        joined = assemble_episode(
            parts,
            episode_path_for(lecture),
            lecture_index=lecture_index,
            width=width,
            height=height,
            fps=fps,
            progress=_as_stage(progress, "episode_join"),
            cancel=cancel,
        )
    except EpisodeError as error:
        raise _part_error(error, {**clips, **made}) from error
    # Recorded before the subtitle files, which are extra: the video is made.
    assert project.render is not None  # render_project has just recorded it
    project.render["episode"] = {
        "video": str(joined.output),
        "lecture_offset": round(joined.lecture_offset, 3),
        "durations": [round(d, 3) for d in joined.durations],
    }
    if project.path is not None:
        try:
            save_project(project, project.path)
        except OSError:
            # The episode is on disk either way; the record only names it. The
            # review copies this render back and its next save writes it.
            pass
    if subtitles in ("sidecar", "both") and formats:
        try:
            # Named from the episode's own path: ``with_suffix`` on a bare stem
            # would cut a name with a dot in it ("Tafsir 25.7-11 – episode")
            # back to "Tafsir 25", the lecture's own subtitle file.
            export_project_subtitles(
                project,
                joined.output,
                tuple(formats),
                timeline="video",
                offset=joined.lecture_offset,
            )
        except ValueError:
            pass  # no cue to write: the lecture's render wrote no subtitle file either
        except Exception as error:  # noqa: BLE001 — OSError, or ffprobe unable to read
            if not isinstance(error, OSError):
                _log.error("The episode's subtitle files failed unexpectedly", exc_info=True)
            return joined.output, t(
                "episode.error.subtitles", reason=str(error) or type(error).__name__
            )
    return joined.output, None


def _generated_parts(
    project: Project,
    choice: EpisodeChoice,
    width: int,
    height: int,
    fps: int,
    *,
    progress: ProgressCallback | None,
    cancel: CancelToken | None,
) -> dict[str, Path]:
    """Make (or reuse) the episode's generated parts, in the lecture's look; by part.

    Each is reported as its own stage (``episode_intro``, ``episode_outro``).
    Raises :class:`EpisodeError` with the part said in the window's language.
    """
    look = project_look(project)
    names = stored_surah_names(QURAN_DB_PATH)
    made: dict[str, Path] = {}
    for part in _CLIP_PARTS:
        settings = getattr(choice, f"{part}_generated")
        if settings is None:
            continue
        stage = f"episode_{part}"
        report(progress, stage, t(f"job.stage.{stage}"), translated=True)
        try:
            spec_for = intro_spec_for if part == "intro" else outro_spec_for
            spec = spec_for(project, settings, names)
            made[part] = ensure_generated_part(
                project,
                part,
                spec,
                look,
                width=width,
                height=height,
                fps=fps,
                progress=_as_stage(progress, stage),
                cancel=cancel,
            )
        except EpisodeError as error:
            fmt = dict(error.fmt)
            # The job layer names the part by its key; the window says it.
            if str(fmt.get("part", "")).startswith("episode.part."):
                fmt["part"] = t(str(fmt["part"]))
            raise EpisodeError(error.key, **fmt) from error
        except ValueError as error:
            # A link or a text the dialog refuses: only a hand-edited project has one.
            _log.warning("The generated %s could not be set up", part, exc_info=True)
            raise EpisodeError("episode.error.generate", part=t(f"episode.part.{part}")) from error
    return made


def _as_stage(progress: ProgressCallback | None, stage: str) -> ProgressCallback | None:
    """*progress*, with every event reported under *stage*.

    The recitation's render and the join report as ``render``, the stage of
    the lecture's own render just before; under their own names the window
    can say which part of the episode the percentage is of.
    """
    if progress is None:
        return None

    def relabelled(event: ProgressEvent) -> None:
        progress(replace(event, stage=stage))

    return relabelled


def _lecture_geometry(project: Project) -> tuple[int, int, int]:
    """The size and frame rate the lecture was just rendered at, as its record says."""
    render = project.render or {}
    try:
        return int(render["width"]), int(render["height"]), int(render["fps"])
    except (KeyError, TypeError, ValueError):
        raise EpisodeError(
            "episode.error.ffmpeg", reason="the lecture's size was not recorded"
        ) from None

"""From a project to the deliverables, by one route.

The window and the command line both render through here, so a correction made
in the editor — a retimed word, a moved card, a fixed caption — is what reaches
the video and the subtitle files, whichever surface started the job.

Exporting subtitles does not render. It needs to know which timeline to use:
the original recording's, or the rendered video's, which starts later when a
basmala was spliced in front. The offset is taken from the project's record of
its last render rather than recomputed, so the files match the video that
actually exists.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

from qurantext.config.paths import QURAN_DB_PATH
from qurantext.config.settings import VIDEO_PRESETS
from qurantext.core.looks import Look
from qurantext.core.subtitles import Cue, write_subtitles
from qurantext.core.video_common import get_audio_duration
from qurantext.jobs.export import ExportRequest, ExportResult, build_cues, export_job
from qurantext.jobs.look_assets import project_look, set_project_look
from qurantext.jobs.project import Project, save_project
from qurantext.utils.progress import CancelToken, ProgressCallback

__all__ = ["SUBTITLE_TIMELINES", "export_project_subtitles", "render_project"]

#: Which clock exported subtitles follow.
SUBTITLE_TIMELINES = ("video", "audio")

_DEFAULT_SIZE = (1080, 1920)


def render_project(
    project: Project,
    output: Path,
    *,
    preset: str | None = None,
    subtitles: str = "burn",
    formats: tuple[str, ...] = ("srt",),
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
    font_file: Path | None = None,
    title: str | None = None,
    db_path: Path = QURAN_DB_PATH,
    look: Look | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> ExportResult:
    """Render *project*, remember the render, and save the project if it has a file.

    The cards, captions and style are copied before anything runs, and the
    render is made and hashed from that copy. A render can take minutes in a
    worker while the editor stays open; an edit made meanwhile — a retimed word
    or another look — is not in the video, so it must leave the render looking
    stale rather than be silently credited to it.

    *look* renders a look the project does not hold (the command line's
    ``--look`` on a project that never chose one). The project is not changed,
    but the recorded hash names that look, so the render reads as stale against
    the project's own. A *look* equal to the project's own leaves the style as
    stored: rewriting a hand-edited style into canonical form would record a
    hash the project does not have, and the render would read stale at once.
    """
    if project.matches is None:
        raise ValueError(
            "This project does not record its match file, so it cannot be rendered. "
            "Open it from the job it was made for, or re-run matching."
        )
    snapshot = replace(
        project,
        cards=copy.deepcopy(project.cards),
        captions=copy.deepcopy(project.captions),
        style=copy.deepcopy(project.style),
    )
    own = project_look(snapshot)
    if look is None:
        look = own
    elif look != own:
        set_project_look(snapshot, look)
    rendered_hash = snapshot.content_hash()
    result = export_job(
        ExportRequest(
            audio=Path(snapshot.audio),
            matches=Path(snapshot.matches),
            output=Path(output),
            subtitles=subtitles,
            formats=tuple(formats),
            preset=preset,
            width=width,
            height=height,
            fps=fps,
            font_file=font_file,
            title=title,
            db_path=Path(db_path),
            captions=tuple(snapshot.caption_segments()),
            cards=tuple(snapshot.cards),
            look=look,
        ),
        progress=progress,
        cancel=cancel,
    )
    rendered = result.render
    project.record_render(
        result.video,
        preset=preset,
        basmala_offset_s=rendered.basmala_offset_seconds if rendered is not None else 0.0,
        content_hash=rendered_hash,
        width=rendered.width if rendered is not None else None,
        height=rendered.height if rendered is not None else None,
        fps=rendered.fps if rendered is not None else None,
        subtitles=subtitles,
    )
    if project.path is not None:
        save_project(project, project.path)
    return result


def export_project_subtitles(
    project: Project,
    stem: Path,
    formats: tuple[str, ...],
    *,
    timeline: str = "audio",
    db_path: Path = QURAN_DB_PATH,
) -> list[Path]:
    """Write subtitle files for *project* without rendering anything."""
    if timeline not in SUBTITLE_TIMELINES:
        raise ValueError(f"timeline must be one of {', '.join(SUBTITLE_TIMELINES)}.")
    offset = 0.0
    if timeline == "video":
        if project.render is None:
            raise ValueError(
                "There is no rendered video to line the subtitles up with. "
                "Render first, or export on the original recording's timeline."
            )
        offset = float(project.render.get("basmala_offset_s") or 0.0)

    duration = get_audio_duration(Path(project.audio))
    cues = build_cues(
        Path(project.matches) if project.matches else Path(),
        duration,
        mode=project.mode,
        db_path=Path(db_path),
        captions=tuple(project.caption_segments()),
        cards=tuple(project.cards),
    )
    if not cues:
        raise ValueError("No subtitle lines could be built from this project.")
    if offset:
        cues = [
            Cue(start=c.start + offset, end=c.end + offset, text=c.text, ref=c.ref) for c in cues
        ]

    width, height = _subtitle_size(project.render or {})
    stem = Path(stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    return write_subtitles(cues, stem, tuple(formats), width=width, height=height)


def _subtitle_size(render: dict) -> tuple[int, int]:
    """The rendered video's size when it was recorded, else its preset's, else portrait HD."""
    if render.get("width") and render.get("height"):
        return int(render["width"]), int(render["height"])
    preset = render.get("preset")
    if preset in VIDEO_PRESETS:
        width, height = VIDEO_PRESETS[preset][:2]
        return int(width), int(height)
    return _DEFAULT_SIZE

"""Video-generation pipeline.

Kept as a thin, stable name over :func:`qurantext.jobs.render.render_video`.
It used to marshal its typed arguments into a list of command-line strings and
hand them to a second argparse parser, which meant a caller could get back only
an exit code — no output path, no duration, no progress, no way to cancel.
"""

from __future__ import annotations

from pathlib import Path

from qurantext.core.looks import NIGHT_GOLD, Look
from qurantext.jobs.render import RenderRequest, RenderResult, render_video
from qurantext.utils.progress import CancelToken, ProgressCallback

__all__ = ["RenderRequest", "RenderResult", "render_video", "run_video_generation"]


def run_video_generation(
    *,
    audio: str | Path,
    matches: str | Path,
    output: str | Path,
    font_name: str | None = None,
    font_file: str | Path | None = None,
    renderer: str | None = None,
    preset: str | None = None,
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
    keep_temp: bool = False,
    debug_detected_text: bool = False,
    title: str | None = None,
    captions: tuple[dict, ...] | None = None,
    look: Look = NIGHT_GOLD,
    studied_surah: int | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> RenderResult:
    """Render a video and return what was written."""
    from qurantext.config.settings import get_settings

    request = RenderRequest(
        audio=Path(audio),
        matches=Path(matches),
        output=Path(output),
        renderer=str(renderer or get_settings().video.renderer),
        preset=preset,
        width=width,
        height=height,
        fps=fps,
        font_name=font_name,
        font_file=Path(font_file) if font_file else None,
        title=title,
        debug_detected_text=debug_detected_text,
        keep_temp=keep_temp,
        captions=captions,
        look=look,
        studied_surah=studied_surah,
    )
    return render_video(request, progress=progress, cancel=cancel)

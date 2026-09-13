"""Callable job layer: typed requests, structured progress, cancellation.

Everything a user interface needs to drive the pipeline lives here. The stages
themselves stay in ``core`` and ``pipelines``; this package is the boundary that
turns them into something callable with real arguments, observable while it
runs, and stoppable partway through.
"""

from qurantext.utils.progress import (
    CancelToken,
    ConsoleProgress,
    JobCancelled,
    ProgressCallback,
    ProgressEvent,
    report,
)

from .project import PROJECT_VERSION, CaptionCue, Project, load_project, save_project
from .render import RenderRequest, RenderResult, render_video

__all__ = [
    "PROJECT_VERSION",
    "CancelToken",
    "CaptionCue",
    "ConsoleProgress",
    "JobCancelled",
    "ProgressCallback",
    "ProgressEvent",
    "Project",
    "RenderRequest",
    "RenderResult",
    "load_project",
    "render_video",
    "report",
    "save_project",
]

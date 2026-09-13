"""Callable job layer: typed requests, structured progress, cancellation.

Everything a user interface needs to drive the pipeline lives here. The stages
themselves stay in ``core`` and ``pipelines``; this package is the boundary that
turns them into something callable with real arguments, observable while it
runs, and stoppable partway through.
"""

from .progress import (
    CancelToken,
    ConsoleProgress,
    JobCancelled,
    ProgressCallback,
    ProgressEvent,
    report,
)
from .render import RenderRequest, RenderResult, render_video

__all__ = [
    "CancelToken",
    "ConsoleProgress",
    "JobCancelled",
    "ProgressCallback",
    "ProgressEvent",
    "RenderRequest",
    "RenderResult",
    "render_video",
    "report",
]

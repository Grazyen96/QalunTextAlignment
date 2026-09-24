"""Progress reporting and cancellation for long-running jobs.

The pipeline's slow stages used to communicate by printing to stdout and could
not be stopped once started. Neither works behind a window: a desktop app needs
structured progress it can put on a bar, and a Cancel button that actually takes
effect mid-render.

Both are optional everywhere. A caller that passes nothing gets silence and no
cancellation, so library use and tests are unaffected; the CLI passes
:class:`ConsoleProgress`, which reproduces the terminal output the commands
printed before.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

__all__ = [
    "CancelToken",
    "ConsoleProgress",
    "JobCancelled",
    "ProgressCallback",
    "ProgressEvent",
    "report",
]


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """One progress update from a job stage.

    *fraction* is progress within the current stage, not the whole job, because
    only the caller knows which stages it chose to run. *eta_seconds* is filled
    in only by stages that can estimate it honestly from work already done.
    """

    stage: str
    message: str
    fraction: float | None = None
    eta_seconds: float | None = None
    #: True for a stage's final event, so a reporter can close out its line.
    done: bool = False
    #: True when *message* is already in the window's language: the GUI's own
    #: sentences (``gui/jobs.py``). A window shows only these as they are; any
    #: other message is the pipeline's English log line, and the window names
    #: the stage in its own words instead. The terminal prints both alike.
    translated: bool = False


ProgressCallback = Callable[[ProgressEvent], None]


class JobCancelled(RuntimeError):
    """Raised inside a job when its cancellation token has been set."""


class CancelToken:
    """A thread-safe flag a job polls to decide whether to stop.

    Backed by :class:`threading.Event` so a user interface can set it from the
    thread handling the Cancel button while the job runs on a worker thread.
    """

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Ask the running job to stop at its next checkpoint."""
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self, stage: str = "job") -> None:
        """Abort the job when cancellation has been requested."""
        if self._event.is_set():
            raise JobCancelled(f"{stage} was cancelled")


def report(
    progress: ProgressCallback | None,
    stage: str,
    message: str,
    *,
    fraction: float | None = None,
    eta_seconds: float | None = None,
    done: bool = False,
    translated: bool = False,
) -> None:
    """Send one event to *progress*, if a caller supplied one.

    Keeps the ``if progress is not None`` check out of every call site in the
    pipeline, which is what makes threading progress through cheap enough to do
    everywhere it matters.
    """
    if progress is None:
        return
    progress(
        ProgressEvent(
            stage=stage,
            message=message,
            fraction=fraction,
            eta_seconds=eta_seconds,
            done=done,
            translated=translated,
        )
    )


class ConsoleProgress:
    """Print progress to a terminal the way the commands always have.

    Events carrying a *fraction* redraw one line in place; everything else
    prints normally. Redrawing is skipped when the stream is not a terminal (a
    log file, a CI job) so captured output stays readable one line at a time.
    """

    __slots__ = ("_stream", "_interactive", "_open_line", "_last_redraw", "_min_interval")

    def __init__(self, stream=None, *, min_interval: float = 0.2) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._interactive = bool(getattr(self._stream, "isatty", lambda: False)())
        self._open_line = False
        self._last_redraw = 0.0
        self._min_interval = min_interval

    def __call__(self, event: ProgressEvent) -> None:
        if event.fraction is None:
            self._finish_line()
            print(event.message, file=self._stream, flush=True)
            return

        text = event.message
        if event.eta_seconds is not None and not event.done:
            text = f"{text}  ETA {event.eta_seconds:.0f}s"

        if not self._interactive:
            # Non-terminal: emit only the closing line so logs stay readable.
            if event.done:
                self._finish_line()
                print(text, file=self._stream, flush=True)
            return

        now = time.monotonic()
        if not event.done and now - self._last_redraw < self._min_interval:
            return
        self._last_redraw = now
        print(f"\r{text}   ", end="", file=self._stream, flush=True)
        self._open_line = True
        if event.done:
            self._finish_line()

    def _finish_line(self) -> None:
        if self._open_line:
            print(file=self._stream, flush=True)
            self._open_line = False

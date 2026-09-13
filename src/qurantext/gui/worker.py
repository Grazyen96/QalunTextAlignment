"""Run a job off the UI thread and report it back through signals.

The window must stay responsive while a render runs for minutes, and Cancel has
to take effect while it does. Both are possible because Phase 1 turned the
pipeline into something callable: a job takes a progress callback and a
cancellation token, so the only thing left here is to move it onto a worker
thread and turn its callbacks into Qt signals.

Qt objects belong to the thread that created them, so the job never touches a
widget. It emits; the window's slots run on the UI thread and do the drawing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal

from qurantext.utils.progress import CancelToken, JobCancelled, ProgressEvent

__all__ = ["JobWorker", "run_in_thread"]


class JobWorker(QObject):
    """Runs one callable, forwarding its progress, result and failure."""

    #: A progress update from the job. Carried as the event itself so the window
    #: can decide what to show rather than parsing a formatted string.
    progressed = Signal(object)
    #: The job returned. Carries whatever the job returned.
    finished = Signal(object)
    #: The job raised. Carries a message already fit to show a person.
    failed = Signal(str)
    #: The job stopped because Cancel was pressed.
    cancelled = Signal()
    #: Always emitted last, whatever the outcome, so the window can re-enable.
    done = Signal()

    def __init__(self, job: Callable[..., Any], cancel: CancelToken) -> None:
        super().__init__()
        self._job = job
        self._cancel = cancel

    def run(self) -> None:
        try:
            result = self._job(progress=self._emit, cancel=self._cancel)
        except JobCancelled:
            self.cancelled.emit()
        except Exception as error:  # noqa: BLE001 — a window must never die on a job
            self.failed.emit(_readable(error))
        else:
            self.finished.emit(result)
        finally:
            self.done.emit()

    def _emit(self, event: ProgressEvent) -> None:
        self.progressed.emit(event)


def _readable(error: Exception) -> str:
    """A message worth showing someone who did not write the code."""
    text = str(error).strip()
    if not text:
        return f"{type(error).__name__} (no details given)"
    if isinstance(error, FileNotFoundError):
        return f"File not found: {text}"
    return text


def run_in_thread(
    job: Callable[..., Any],
    cancel: CancelToken,
    *,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    on_finished: Callable[[Any], None] | None = None,
    on_failed: Callable[[str], None] | None = None,
    on_cancelled: Callable[[], None] | None = None,
    on_done: Callable[[], None] | None = None,
) -> tuple[QThread, JobWorker]:
    """Start *job* on a worker thread and wire the callbacks given.

    Returns the thread and worker so the caller can keep them alive; letting
    either be garbage collected while running crashes Qt.
    """
    thread = QThread()
    worker = JobWorker(job, cancel)
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    if on_progress is not None:
        worker.progressed.connect(on_progress)
    if on_finished is not None:
        worker.finished.connect(on_finished)
    if on_failed is not None:
        worker.failed.connect(on_failed)
    if on_cancelled is not None:
        worker.cancelled.connect(on_cancelled)
    if on_done is not None:
        worker.done.connect(on_done)

    # Direct, not queued: the worker emits from inside the thread, and quit() is
    # safe to call from there. Queued, the call would sit in the UI thread's
    # event loop, so anything that waits on the thread without spinning that
    # loop would wait for ever.
    worker.done.connect(thread.quit, Qt.ConnectionType.DirectConnection)
    thread.finished.connect(worker.deleteLater)

    thread.start()
    return thread, worker

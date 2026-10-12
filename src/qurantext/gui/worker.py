"""Run a job off the UI thread and report it back through signals.

The window must stay responsive while a render runs for minutes, and Cancel has
to take effect while it does. Both are possible because Phase 1 turned the
pipeline into something callable: a job takes a progress callback and a
cancellation token, so the only thing left here is to move it onto a worker
thread and turn its callbacks into Qt signals.

Qt objects belong to the thread that created them, so the job never touches a
widget. It emits; the window's slots run on the UI thread and do the drawing.

A job that fails is shown to the person as a sentence, and that is all most
failures need: FFmpeg refusing a file, a missing model, a folder that cannot be
written. A failure nobody wrote a sentence for is a bug, and its traceback goes
to the log (``config.app_log``), which is what someone is asked to send.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal

from qurantext.utils.progress import CancelToken, JobCancelled, ProgressEvent

__all__ = ["JobWorker", "run_in_thread"]

_log = logging.getLogger(__name__)

#: Subclasses of the foreseen types below that are bugs wherever they come from:
#: code nobody finished, a recursion with no end, a text that could not be encoded.
_NEVER_FORESEEN = (NotImplementedError, RecursionError, UnicodeError)


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
            if _foreseen(error):
                # Said to the person in full; the log keeps a line of it, for the
                # timeline, but no traceback: nothing here needs fixing in the code.
                _log.warning("The job stopped: %s", _readable(error))
            else:
                _log.error("The job failed unexpectedly", exc_info=True)
            self.failed.emit(_readable(error))
        else:
            self.finished.emit(result)
        finally:
            self.done.emit()

    def _emit(self, event: ProgressEvent) -> None:
        self.progressed.emit(event)


def _foreseen(error: Exception) -> bool:
    """Is *error* one the code meant to raise, with a sentence for the person?

    Two kinds are. Anything the operating system refused (``OSError``: a file
    not found, a folder not writable, a full disk), which no code change fixes.
    And a ``ValueError`` or ``RuntimeError`` with a message, raised by Qalun's
    own code: that is how every module says "this cannot be done" (FFmpeg
    failed, a bad range, the store unreadable, and the episode's, transcription's
    and store's own error types, which are all ``RuntimeError``). The same types
    raised from inside a library (numpy, json) are a call that went wrong, a bug.
    """
    if isinstance(error, _NEVER_FORESEEN):
        return False
    if isinstance(error, OSError):
        return True
    if not isinstance(error, ValueError | RuntimeError) or not str(error).strip():
        return False
    tb = error.__traceback__
    if tb is None:
        return False
    while tb.tb_next is not None:
        tb = tb.tb_next
    module = tb.tb_frame.f_globals.get("__name__", "")
    return module == "qurantext" or module.startswith("qurantext.")


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
    either be garbage collected while running crashes Qt. Drop them together,
    on the UI thread, once the thread has ended: that is what deletes the worker.
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
    # No ``thread.finished -> worker.deleteLater``: that deletes the worker on its
    # own thread as the thread ends, and deleting a Python-made QObject there
    # takes a Qt signal lock and then asks for the GIL. The UI thread, holding
    # the GIL while it builds a widget and connects its signals, can want that
    # same lock (Qt hashes objects onto a small pool of them), and the two wait
    # for each other for ever; the home window hung that way as it opened,
    # while its job list's first read ended. The worker is Python-owned, so it
    # goes on the UI thread once the caller has waited for the thread and
    # dropped both (``BackgroundJobs`` does), with the GIL already held.

    thread.start()
    return thread, worker

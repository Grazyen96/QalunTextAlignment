"""The review window's background reads: the waveform's peaks and the coverage check.

Both decode the whole recording, which takes seconds on a long lecture, so
they run on worker threads while the window is already usable. This keeps the
thread bookkeeping out of the window: every job's thread, worker and cancel
token stay referenced until it ends (Qt crashes if a running ``QThread`` is
garbage collected), and closing the window cancels them all.

A job that ignores its cancel token (``find_uncovered_speech`` takes none)
may outlive the short wait on close. Its thread is then parked in
:data:`_LINGERING` and dropped by a later :meth:`BackgroundJobs.stop` once it
has finished, instead of being destroyed while it still runs. Nothing here is
called back from a worker thread: finished entries are pruned lazily, on the
UI thread.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread

from qurantext.gui.worker import JobWorker, run_in_thread
from qurantext.utils.progress import CancelToken, ProgressEvent

__all__ = ["BackgroundJobs"]

#: Threads that were still running when their window closed, kept alive until they end.
_LINGERING: list[tuple[QThread, JobWorker]] = []

#: How long closing the window waits for each job to notice it was cancelled.
_CLOSE_WAIT_MS = 2000


class BackgroundJobs(QObject):
    """Runs jobs off the UI thread and cancels whatever is still running on :meth:`stop`.

    *on_finished* and *on_failed* should be bound methods of a ``QObject``
    living on the UI thread, so Qt queues them there; the job itself must never
    touch a widget.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._running: list[tuple[QThread, JobWorker, CancelToken]] = []

    def start(
        self,
        job: Callable[..., Any],
        *,
        on_finished: Callable[[Any], None],
        on_failed: Callable[[str], None],
        on_progress: Callable[[ProgressEvent], None] | None = None,
        on_cancelled: Callable[[], None] | None = None,
        on_done: Callable[[], None] | None = None,
    ) -> CancelToken:
        """Start *job* (called with ``progress=`` and ``cancel=``); returns its token.

        *on_done* runs last whatever the outcome, cancellation included.
        """
        self._prune()
        cancel = CancelToken()
        thread, worker = run_in_thread(
            job,
            cancel,
            on_progress=on_progress,
            on_finished=on_finished,
            on_failed=on_failed,
            on_cancelled=on_cancelled,
            on_done=on_done,
        )
        self._running.append((thread, worker, cancel))
        return cancel

    @property
    def active(self) -> int:
        """How many jobs started here are still running."""
        self._prune()
        return len(self._running)

    def _prune(self) -> None:
        self._running = [entry for entry in self._running if not entry[0].isFinished()]

    def stop(self) -> None:
        """Cancel every running job and wait briefly for each to end."""
        running, self._running = self._running, []
        for _thread, _worker, cancel in running:
            cancel.cancel()
        for thread, worker, _cancel in running:
            thread.quit()
            if not thread.wait(_CLOSE_WAIT_MS):
                _LINGERING.append((thread, worker))
        _LINGERING[:] = [pair for pair in _LINGERING if not pair[0].isFinished()]

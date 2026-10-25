"""The windows' background reads: the waveform's peaks, the coverage check, the job list.

The first two decode the whole recording, which takes seconds on a long
lecture, and the last reads every project in a folder, so they run on worker
threads while the window is already usable. This keeps the
thread bookkeeping out of the window: every job's thread, worker and cancel
token stay referenced until it ends (Qt crashes if a running ``QThread`` is
garbage collected), and closing the window cancels them all.

A job that ignores its cancel token (``speech_levels`` takes none)
may outlive the short wait on close. Its thread is then parked in
:data:`_LINGERING` and dropped by a later :meth:`BackgroundJobs.stop` once it
has finished, instead of being destroyed while it still runs; at exit,
``gui/app.py`` waits for whatever is still parked (:func:`join_lingering`). Nothing here is
called back from a worker thread: finished entries are pruned lazily, on the
UI thread, and each is waited for first so its OS thread has fully exited.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, QThread

from qurantext.gui.worker import JobWorker, run_in_thread
from qurantext.utils.progress import CancelToken, ProgressEvent

__all__ = ["BackgroundJobs", "join_lingering"]

#: Threads that were still running when their window closed, kept alive until they end.
#: A finaliser off the UI thread may append at any time, so the UI thread only
#: ever removes entries from it, one by one, never rebuilds it (which could lose one).
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

    def __del__(self) -> None:
        """Park what still runs when this is dropped without :meth:`stop`.

        A widget can go without anyone stopping its jobs (a panel rebuilt, or
        a test's widget collected), and with it the last reference to a
        ``QThread`` that still runs, which aborts the process. Parked, the
        thread lives on until a later :meth:`stop` or :func:`join_lingering`.

        A finaliser runs on whichever thread drops the last reference, and
        under the cyclic collector that can be a worker. There nothing is
        joined or dropped (dropping a finished ``JobWorker`` deletes a
        Python-made QObject off the UI thread, the pattern that deadlocked the
        home window): every entry is parked, for the UI thread to let go of.
        """
        if not self._running:
            return
        if not _on_ui_thread():
            for thread, worker, cancel in self._running:
                cancel.cancel()
                _LINGERING.append((thread, worker))
            self._running = []
            return
        for thread, worker, cancel in self._running:
            cancel.cancel()
            try:
                thread.quit()
                finished = thread.isFinished()
            except RuntimeError:
                continue  # its C++ side is already gone (at exit): nothing left to run
            if finished:
                _join(thread)
            else:
                _LINGERING.append((thread, worker))
        self._running = []

    def _prune(self) -> None:
        running = []
        for entry in self._running:
            if entry[0].isFinished():
                _join(entry[0])
            else:
                running.append(entry)
        self._running = running

    def stop(self, wait_ms: int = _CLOSE_WAIT_MS) -> bool:
        """Cancel every running job and wait briefly (*wait_ms* each) for each to end.

        Returns whether every one of them ended within its wait; the others are
        parked, and their callbacks still arrive when they end.

        A job with nothing to lose by being cut short (a read whose result is no
        longer wanted) can pass ``wait_ms=0``: it is parked at once rather than
        holding the UI thread up while it finishes.
        """
        running, self._running = self._running, []
        for _thread, _worker, cancel in running:
            cancel.cancel()
        all_ended = True
        for thread, worker, _cancel in running:
            thread.quit()
            if not thread.wait(wait_ms):
                _LINGERING.append((thread, worker))
                all_ended = False
        for pair in list(_LINGERING):
            if pair[0].isFinished():
                _join(pair[0])
                _LINGERING.remove(pair)
        return all_ended


def join_lingering(timeout_ms: int) -> bool:
    """Wait, at most *timeout_ms* in total, for every parked thread to end.

    Called once the event loop has returned, before Python tears the
    ``QThread`` objects down: destroying one that still runs aborts the
    process. Returns whether all of them ended; the ones that did are dropped.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    for pair in list(_LINGERING):
        left_ms = max(0, int((deadline - time.monotonic()) * 1000))
        if pair[0].wait(left_ms):
            _join(pair[0])
            _LINGERING.remove(pair)
    return not _LINGERING


def _on_ui_thread() -> bool:
    """Whether this code runs on the application's thread; True when there is no application.

    With no application (at interpreter teardown) there is no UI thread to
    leave the work to, so the caller does it where it is.
    """
    app = QCoreApplication.instance()
    return app is None or QThread.currentThread() == app.thread()


def _join(thread: QThread) -> None:
    """Wait for a finished *thread*'s OS thread to exit before its last reference goes.

    ``isFinished()`` turns true while the thread is still unwinding, and
    dropping the last reference then frees the ``QThread`` under it — a
    use-after-free that crashed the process (segfault, bus error) when jobs
    ended fast and were pruned at once. ``wait()`` returns as soon as the
    unwinding is done.
    """
    thread.wait()

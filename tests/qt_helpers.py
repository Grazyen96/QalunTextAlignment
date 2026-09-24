"""Waiting on the Qt event loop from a test, without starving worker threads.

Shared by every module whose widgets finish something on a worker thread (the
review window's reads, the home window's job list), so the one safe way to
wait is written once.
"""

from __future__ import annotations

import threading
import time

__all__ = ["blocking_list_jobs", "spin", "wait_for", "wait_until_listed"]


def spin(ms: int) -> None:
    """Run the event loop for about *ms*, never holding the GIL while it waits.

    Not ``QTest.qWait``: PySide6 keeps the GIL for the whole of that call, so a
    worker thread that needs it while holding a Qt lock the UI thread wants
    deadlocks the two (the full suite hung that way). ``processEvents`` and
    ``sendPostedEvents`` release it, and so does ``time.sleep``.
    """
    from PySide6.QtCore import QCoreApplication, QEvent

    deadline = time.monotonic() + ms / 1000
    while True:
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        left = deadline - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(0.005, left))


def wait_for(condition, timeout_ms: int = 10_000) -> bool:
    """Spin the event loop until *condition()* holds (PySide6's QTest has no qWaitFor)."""
    deadline = time.monotonic() + timeout_ms / 1000
    while not condition():
        if time.monotonic() > deadline:
            return False
        spin(20)
    return True


def wait_until_listed(panel, timeout_ms: int = 10_000) -> None:
    """Wait for a ``JobListPanel``'s latest read of the folders to land in its rows.

    The panel reads on a worker thread, so right after it is built or
    refreshed its rows are still the old ones.
    """
    assert wait_for(lambda: not panel.reading, timeout_ms), "the job list's read never landed"


def blocking_list_jobs(monkeypatch):
    """Make a ``JobListPanel``'s reads wait for ``release``; returns (release, started calls).

    Each read lists the folders for real, then waits, so a test can look at
    the panel while a read is still out.
    """
    from qurantext.gui.home import job_list as job_list_module
    from qurantext.jobs import catalog

    release = threading.Event()
    calls: list[int] = []
    real = catalog.list_jobs

    def blocked(*args, **kwargs):
        calls.append(threading.get_ident())
        result = real(*args, **kwargs)
        assert release.wait(10), "the test never released the read"
        return result

    monkeypatch.setattr(job_list_module, "list_jobs", blocked)
    return release, calls

"""Write the app's errors to a file someone can find and send.

Modules log what they did not expect with :mod:`logging` (the episode step's
traceback in ``gui.jobs``, a job folder the list could not read), but nothing
used to configure a handler. From a terminal, Python's last-resort handler still
printed those records; in the packaged app, which is built windowed and starts
with no standard error at all, every one of them went nowhere. So did an
exception that escaped a Qt slot or a background thread: the very report a bug
needs was the one thing no one could ever see.

:func:`configure` gives the ``qurantext`` logger a size-bounded file under
:func:`~qurantext.config.paths.user_log_dir` (1 MB, three older copies) and
routes uncaught exceptions, from the main thread, a Qt slot (PySide6 hands those
to ``sys.excepthook``) or any other thread, through it before the previous hook
runs. Only warnings and worse are kept: this is an error log, not a trace.

Nothing here may stop the window from opening. A data folder that cannot be
written leaves standard error as the only destination, and says nothing about it.

No Qt here, so the command line could use it too, and the tests need no window.
"""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

from qurantext.config.paths import user_log_dir, user_log_file

__all__ = ["LOG_BACKUPS", "LOG_MAX_BYTES", "configure", "install_excepthooks", "setup_logging"]

#: The log's size before it rolls over, and how many older copies are kept: at
#: most 4 MB on disk, years of the occasional error.
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3

#: Every record says when, how bad, from where, and what; a traceback follows on
#: its own lines when the record carries one.
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

#: The logger every module's ``logging.getLogger(__name__)`` descends from.
_ROOT = "qurantext"

#: Set on the handlers and hooks this module installs, so a second call can see
#: them and the tests can take them away again.
_MARK = "_qalun_app_log"

_crash_log = logging.getLogger(f"{_ROOT}.uncaught")


def _usable(stream: object) -> bool:
    """Does *stream* go anywhere? A windowed process starts with no stderr."""
    if stream is None:
        return False
    try:
        stream.fileno()  # type: ignore[attr-defined]
    except Exception:
        return False
    return True


def _file_handler() -> RotatingFileHandler | None:
    """The rotating log file, or None when its folder cannot be made or written."""
    try:
        user_log_dir().mkdir(parents=True, exist_ok=True)
        # Opened now rather than at the first record, so an unwritable folder
        # is found here, where it can be passed over, and not mid-crash.
        return RotatingFileHandler(
            user_log_file(), maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
        )
    except Exception:
        # OSError above all, but a home folder that cannot be resolved raises
        # RuntimeError, and no reason is good enough to keep the window shut.
        return None


def setup_logging() -> Path | None:
    """Send the ``qurantext`` logger's warnings and worse to the log file.

    Also to standard error when there is one, so a terminal still shows them as
    it did before any handler existed. Calling it again changes nothing.
    Returns the log file, or None when only standard error could be used.
    """
    logger = logging.getLogger(_ROOT)
    mine = [handler for handler in logger.handlers if getattr(handler, _MARK, False)]
    if mine:
        files = [h for h in mine if isinstance(h, RotatingFileHandler)]
        return Path(files[0].baseFilename) if files else None

    logger.setLevel(logging.WARNING)
    formatter = logging.Formatter(_FORMAT)
    handlers: list[logging.Handler] = []
    to_file = _file_handler()
    if to_file is not None:
        handlers.append(to_file)
    if _usable(sys.stderr):
        handlers.append(logging.StreamHandler())
    for handler in handlers:
        handler.setFormatter(formatter)
        setattr(handler, _MARK, True)
        logger.addHandler(handler)
    return Path(to_file.baseFilename) if to_file is not None else None


def install_excepthooks() -> None:
    """Log every uncaught exception at CRITICAL, then let the previous hook run.

    The previous hook still prints or reports it as before; this only makes sure
    a copy reaches the log. A Ctrl+C is not a crash, and a thread that ends with
    ``SystemExit`` is not one either (the default thread hook says nothing about it).
    """
    if not getattr(sys.excepthook, _MARK, False):
        previous = sys.excepthook

        def log_uncaught(
            exc_type: type[BaseException],
            exc_value: BaseException,
            tb: TracebackType | None,
        ) -> None:
            if not issubclass(exc_type, KeyboardInterrupt):
                _log_crash("Uncaught exception", (exc_type, exc_value, tb))
            previous(exc_type, exc_value, tb)

        setattr(log_uncaught, _MARK, True)
        log_uncaught.previous = previous  # type: ignore[attr-defined]
        sys.excepthook = log_uncaught

    if not getattr(threading.excepthook, _MARK, False):
        previous_thread = threading.excepthook

        def log_thread(args: threading.ExceptHookArgs) -> None:
            if not issubclass(args.exc_type, SystemExit):
                name = args.thread.name if args.thread is not None else "unknown"
                _log_crash(
                    f"Uncaught exception in thread {name}",
                    (args.exc_type, args.exc_value, args.exc_traceback),
                )
            previous_thread(args)

        setattr(log_thread, _MARK, True)
        log_thread.previous = previous_thread  # type: ignore[attr-defined]
        threading.excepthook = log_thread


def _log_crash(message: str, exc_info: tuple) -> None:
    """Log *message* with *exc_info*; a failure to log must not hide the crash itself."""
    try:
        _crash_log.critical(message, exc_info=exc_info)
    except Exception:
        pass


def configure() -> Path | None:
    """The log file and the hooks, once, at startup; returns the log file or None."""
    path = setup_logging()
    install_excepthooks()
    return path


def _uninstall() -> None:
    """Undo :func:`configure`: close the handlers and restore the earlier hooks (tests)."""
    logger = logging.getLogger(_ROOT)
    for handler in [h for h in logger.handlers if getattr(h, _MARK, False)]:
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)
    if getattr(sys.excepthook, _MARK, False):
        sys.excepthook = sys.excepthook.previous  # type: ignore[attr-defined]
    if getattr(threading.excepthook, _MARK, False):
        threading.excepthook = threading.excepthook.previous  # type: ignore[attr-defined]

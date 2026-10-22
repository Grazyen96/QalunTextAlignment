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
routes uncaught exceptions, from the main thread, a Qt slot or a ``QThread``
(PySide6 hands those to ``sys.excepthook``) or any other thread, through it
before the previous hook runs. Only warnings and worse are kept: this is an
error log, not a trace.

Two windows can run at once, and on Windows a file another process holds open
cannot be renamed, so the standard rotation would fail half way: the older
copies already shifted, the current file unrenamed, and every record dropped
until the other window closed. :class:`SharedRotatingFileHandler` tries the
rename first, and when it is refused keeps appending and tries again later.

A hard crash (Qt aborting on a thread destroyed while running, a segfault in a
native library) never reaches Python's hooks, so on Linux and macOS
:mod:`faulthandler` writes the Python stacks of such a crash to ``faults.log``
beside the log. Not into the log itself: that file is closed and reopened at
each rotation, and faulthandler keeps the descriptor it was given. Not on
Windows, where faulthandler also reports the C++ exceptions Qt and ONNX Runtime
throw and catch themselves, which would fill the file with crashes that were not.

Nothing here may stop the window from opening. A data folder that cannot be
written leaves standard error as the only destination, and says nothing about it.

No Qt here, so the command line could use it too, and the tests need no window;
``gui.app`` routes Qt's own messages into the same logger.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import IO

from qurantext.config.paths import user_log_dir, user_log_file

__all__ = [
    "LOG_BACKUPS",
    "LOG_MAX_BYTES",
    "SharedRotatingFileHandler",
    "configure",
    "enable_fault_log",
    "install_excepthooks",
    "setup_logging",
]

#: The log's size before it rolls over, and how many older copies are kept: at
#: most 4 MB on disk, years of the occasional error.
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3

#: Every record says when, how bad, from where, and what; a traceback follows on
#: its own lines when the record carries one.
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

#: The logger every module's ``logging.getLogger(__name__)`` descends from.
_ROOT = "qurantext"
#: Where uncaught exceptions are logged. Kept off standard error: the previous
#: hook, which still runs, prints them there already.
_UNCAUGHT = f"{_ROOT}.uncaught"

#: Set on the handlers and hooks this module installs, so a second call can see
#: them and the tests can take them away again.
_MARK = "_qalun_app_log"

_crash_log = logging.getLogger(_UNCAUGHT)

#: The file faulthandler writes to, kept open for as long as the process runs,
#: and whether faulthandler was on before (the tests put it back as it was).
_faults: IO[str] | None = None
_faults_were_enabled = False


class SharedRotatingFileHandler(RotatingFileHandler):
    """A rotating log that loses nothing when another process holds it open.

    The rotation renames the current file first, to a name of its own, and
    only once that has worked shifts the older copies along. When the rename is
    refused (Windows, a second window writing to the same file) it reopens the
    current file, keeps appending, and tries again only after another tenth of
    ``maxBytes``, so a refused rotation costs one rename per 100 KB, not one per
    record. The file grows past ``maxBytes`` for as long as the other window
    stays open; that is the price of keeping every record and every copy.
    """

    def __init__(self, filename: os.PathLike[str] | str, **kwargs: object) -> None:
        super().__init__(filename, **kwargs)  # type: ignore[arg-type]
        #: The file's size below which a refused rotation is not tried again; 0 when none was refused.
        self.retry_at = 0

    def shouldRollover(self, record: logging.LogRecord) -> bool:  # noqa: N802 - logging's name
        if self.stream is not None:
            # Measure the file, not what this window wrote: another window appends
            # to it too. Python 3.12.4+ and 3.13 read the position without seeking
            # to the end first (gh-116263), so they would miss the other's writes.
            self.stream.seek(0, os.SEEK_END)
        if not super().shouldRollover(record):
            return False
        if self.retry_at and self.stream is not None and self.stream.tell() < self.retry_at:
            return False
        return True

    def doRollover(self) -> None:  # noqa: N802 - logging's name
        if self.stream is not None:
            self.stream.close()
            self.stream = None  # type: ignore[assignment]
        base = self.baseFilename
        # Unique to this process and this rotation: under a fixed name, a crash
        # between the steps below, or two windows rotating in the same instant,
        # let the next rotation overwrite a copy not yet moved to ``.1``. A crash
        # leaves this file behind under its own name, on disk for whoever looks.
        moving = f"{base}.{os.getpid()}-{uuid.uuid4().hex[:8]}.rotating"
        try:
            os.replace(base, moving)
        except OSError:
            self.stream = self._open()
            self.retry_at = self.stream.tell() + max(1, self.maxBytes // 10)
            return
        self.retry_at = 0
        for index in range(self.backupCount - 1, 0, -1):
            older = f"{base}.{index}"
            if os.path.exists(older):
                try:
                    os.replace(older, f"{base}.{index + 1}")
                except OSError:
                    pass  # that copy stays where it is; the next one overwrites it
        try:
            os.replace(moving, f"{base}.1")
        except OSError:
            pass  # left under its .rotating name, still on disk for whoever looks
        self.stream = self._open()


def _usable(stream: object) -> bool:
    """Does *stream* go anywhere? A windowed process starts with no stderr."""
    if stream is None:
        return False
    try:
        stream.fileno()  # type: ignore[attr-defined]
    except Exception:
        return False
    return True


def _file_handler() -> SharedRotatingFileHandler | None:
    """The rotating log file, or None when its folder cannot be made or written."""
    try:
        user_log_dir().mkdir(parents=True, exist_ok=True)
        # Opened now rather than at the first record, so an unwritable folder
        # is found here, where it can be passed over, and not mid-crash. A
        # character UTF-8 cannot write (a file name's undecodable byte, carried
        # as a surrogate) is escaped rather than losing the whole record.
        return SharedRotatingFileHandler(
            user_log_file(),
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUPS,
            encoding="utf-8",
            errors="backslashreplace",
        )
    except Exception:
        # OSError above all, but a home folder that cannot be resolved raises
        # RuntimeError, and no reason is good enough to keep the window shut.
        return None


def _not_uncaught(record: logging.LogRecord) -> bool:
    """Keep uncaught exceptions off standard error, where the previous hook prints them."""
    return record.name != _UNCAUGHT


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
        to_stderr = logging.StreamHandler()
        to_stderr.addFilter(_not_uncaught)
        handlers.append(to_stderr)
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
                _log_crash(_where("Uncaught exception"), (exc_type, exc_value, tb))
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


def _where(message: str) -> str:
    """*message*, naming the thread when it is not the main one.

    An exception in a ``QThread``'s slot or ``run`` reaches ``sys.excepthook``,
    not the thread hook, so this is where its thread gets named.
    """
    thread = threading.current_thread()
    if thread is threading.main_thread():
        return message
    return f"{message} in thread {thread.name}"


def _log_crash(message: str, exc_info: tuple) -> None:
    """Log *message* with *exc_info*; a failure to log must not hide the crash itself."""
    try:
        _crash_log.critical(message, exc_info=exc_info)
    except Exception:
        pass


def enable_fault_log() -> Path | None:
    """Have :mod:`faulthandler` write a hard crash's stacks to ``faults.log``.

    Linux and macOS only (see the module's docstring). A file grown past
    ``LOG_MAX_BYTES`` is set aside as ``faults.log.1`` first, so it stays bounded
    with no rotation of its own. Returns the file, or None when it is not used.
    """
    global _faults, _faults_were_enabled
    if sys.platform == "win32":
        return None
    if _faults is not None:
        return Path(_faults.name)
    path = user_log_dir() / "faults.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > LOG_MAX_BYTES:
            os.replace(path, path.with_name("faults.log.1"))
        stream = open(path, "a", encoding="utf-8")  # noqa: SIM115 - open for the process's life
    except Exception:
        return None
    try:
        was_enabled = faulthandler.is_enabled()
        faulthandler.enable(file=stream, all_threads=True)
    except Exception:
        stream.close()
        return None
    _faults, _faults_were_enabled = stream, was_enabled
    return path


def configure() -> Path | None:
    """The log file, the hooks and the fault log, once, at startup; returns the log file or None."""
    path = setup_logging()
    install_excepthooks()
    enable_fault_log()
    return path


def _uninstall() -> None:
    """Undo :func:`configure`: close the handlers and restore the earlier hooks (tests)."""
    global _faults
    logger = logging.getLogger(_ROOT)
    for handler in [h for h in logger.handlers if getattr(h, _MARK, False)]:
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)
    if getattr(sys.excepthook, _MARK, False):
        sys.excepthook = sys.excepthook.previous  # type: ignore[attr-defined]
    if getattr(threading.excepthook, _MARK, False):
        threading.excepthook = threading.excepthook.previous  # type: ignore[attr-defined]
    if _faults is not None:
        if _faults_were_enabled and _usable(sys.__stderr__):
            faulthandler.enable(file=sys.__stderr__, all_threads=True)
        else:
            faulthandler.disable()
        _faults.close()
        _faults = None

"""The app's error log: a file someone can find, and the crashes that reach it.

The packaged app is built windowed, so it has no standard error; these records
used to go nowhere. Each test points ``QURANTEXT_DATA_DIR`` at its own folder and
takes the handlers and hooks away again, so nothing leaks into the next test.
"""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

import pytest

from qurantext.config import app_log
from qurantext.config.paths import user_log_dir, user_log_file


@pytest.fixture(autouse=True)
def _own_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    # Recorded here so they come back even if a test fails before _uninstall.
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    yield
    app_log._uninstall()


def _mine() -> list[logging.Handler]:
    return [h for h in logging.getLogger("qurantext").handlers if getattr(h, app_log._MARK, False)]


def _flush() -> None:
    for handler in _mine():
        handler.flush()


def test_the_log_file_is_made_under_the_data_dir(tmp_path) -> None:
    path = app_log.setup_logging()

    assert path == tmp_path / "data" / "logs" / "qalun.log"
    assert path == user_log_file() and path.parent == user_log_dir()
    assert path.is_file()
    (handler,) = [h for h in _mine() if isinstance(h, RotatingFileHandler)]
    assert handler.maxBytes == 1_000_000 and handler.backupCount == 3
    assert handler.encoding == "utf-8"
    assert logging.getLogger("qurantext").level == logging.WARNING


def test_setting_up_twice_installs_one_handler() -> None:
    first = app_log.configure()
    before = list(_mine())
    hook = sys.excepthook
    second = app_log.configure()

    assert first == second
    assert _mine() == before
    assert len([h for h in before if isinstance(h, RotatingFileHandler)]) == 1
    assert sys.excepthook is hook, "the hook is not wrapped a second time"


def test_an_error_with_its_traceback_lands_in_the_file() -> None:
    path = app_log.setup_logging()
    log = logging.getLogger("qurantext.gui.jobs")

    def boom() -> None:
        raise RuntimeError("boom ü ب")

    try:
        boom()
    except RuntimeError:
        log.error("The episode step failed unexpectedly", exc_info=True)
    log.info("not an error, so not kept")
    _flush()

    text = path.read_text(encoding="utf-8")
    assert "ERROR qurantext.gui.jobs: The episode step failed unexpectedly" in text
    assert "Traceback (most recent call last)" in text
    assert "in boom" in text and "RuntimeError: boom ü ب" in text
    assert "not an error" not in text
    # A timestamp leads each record: 2026-10-12 09:41:07,123
    assert text[:4].isdigit() and text[4] == "-"


def test_an_uncaught_exception_is_logged_then_handed_on() -> None:
    seen: list = []
    sys.excepthook = lambda *exc: seen.append(exc)
    path = app_log.configure()

    try:
        raise ValueError("escaped a slot")
    except ValueError:
        exc_info = sys.exc_info()
    sys.excepthook(*exc_info)
    _flush()

    assert seen == [exc_info], "the previous hook still runs, with the same exception"
    text = path.read_text(encoding="utf-8")
    assert "CRITICAL qurantext.uncaught: Uncaught exception" in text
    assert "ValueError: escaped a slot" in text and "Traceback" in text


def test_a_ctrl_c_is_not_logged_as_a_crash() -> None:
    seen: list = []
    sys.excepthook = lambda *exc: seen.append(exc)
    path = app_log.configure()

    sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    _flush()

    assert len(seen) == 1
    assert "CRITICAL" not in path.read_text(encoding="utf-8")


def test_an_exception_in_a_thread_is_logged_then_handed_on() -> None:
    seen: list = []
    threading.excepthook = lambda args: seen.append(args.exc_type)
    path = app_log.configure()

    def work() -> None:
        raise OSError("disk went away")

    thread = threading.Thread(target=work, name="waveform-read")
    thread.start()
    thread.join()
    _flush()

    assert seen == [OSError]
    text = path.read_text(encoding="utf-8")
    assert "CRITICAL qurantext.uncaught: Uncaught exception in thread waveform-read" in text
    assert "OSError: disk went away" in text


def test_an_unwritable_data_dir_falls_back_to_stderr(tmp_path, monkeypatch) -> None:
    # A file where the folder should be: no mkdir can get past it, root or not.
    blocker = tmp_path / "data"
    blocker.write_text("not a folder")
    stderr = (tmp_path / "stderr.txt").open("w", encoding="utf-8")
    monkeypatch.setattr(sys, "stderr", stderr)

    try:
        assert app_log.configure() is None
        assert not [h for h in _mine() if isinstance(h, RotatingFileHandler)]
        logging.getLogger("qurantext.gui.home.job_list").warning("still said somewhere")
        _flush()
    finally:
        app_log._uninstall()
        stderr.close()

    assert "still said somewhere" in (tmp_path / "stderr.txt").read_text(encoding="utf-8")


def test_without_stderr_or_a_folder_nothing_raises(tmp_path, monkeypatch) -> None:
    """A windowed build with an unwritable data folder: quiet, and the window still opens."""
    (tmp_path / "data").write_text("not a folder")
    monkeypatch.setattr(sys, "stderr", None)

    assert app_log.configure() is None
    assert _mine() == []
    logging.getLogger("qurantext.x").error("goes nowhere, harmlessly")

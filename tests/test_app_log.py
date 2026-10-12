"""The app's error log: a file someone can find, and the crashes that reach it.

The packaged app is built windowed, so it has no standard error; these records
used to go nowhere. Each test points ``QURANTEXT_DATA_DIR`` at its own folder and
takes the handlers and hooks away again, so nothing leaks into the next test.
"""

from __future__ import annotations

import logging
import os
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


def test_an_uncaught_exception_is_printed_once_on_a_terminal(tmp_path, monkeypatch) -> None:
    """The previous hook prints it; the log's own stderr copy would be a second one."""
    stderr = (tmp_path / "stderr.txt").open("w", encoding="utf-8")
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)
    try:
        path = app_log.configure()
        try:
            raise ValueError("printed once")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        logging.getLogger("qurantext.gui.jobs").warning("an ordinary warning")
        _flush()
    finally:
        app_log._uninstall()
        stderr.close()

    printed = (tmp_path / "stderr.txt").read_text(encoding="utf-8")
    assert printed.count("ValueError: printed once") == 1
    assert "an ordinary warning" in printed, "everything else still reaches the terminal"
    assert path.read_text(encoding="utf-8").count("ValueError: printed once") == 1


def test_an_uncaught_exception_off_the_main_thread_names_its_thread() -> None:
    """A QThread's slot or run reaches sys.excepthook, not the thread hook."""
    sys.excepthook = lambda *exc: None
    path = app_log.configure()

    def work() -> None:
        try:
            raise RuntimeError("in a worker")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())

    thread = threading.Thread(target=work, name="Dummy-1")
    thread.start()
    thread.join()
    _flush()

    assert "Uncaught exception in thread Dummy-1" in path.read_text(encoding="utf-8")


def test_a_record_utf8_cannot_write_is_kept_escaped() -> None:
    """A Linux file name's undecodable byte arrives as a lone surrogate; the record stays."""
    path = app_log.setup_logging()
    name = b"lesson-\xff.mp3".decode("utf-8", "surrogateescape")

    logging.getLogger("qurantext.gui.home.job_list").error("Could not read %s", name)
    logging.getLogger("qurantext.gui.home.job_list").error("the next record")
    _flush()

    text = path.read_text(encoding="utf-8")
    assert "Could not read lesson-\\udcff.mp3" in text
    assert "the next record" in text


def _fill(path, size: int) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write("x" * size + "\n")


def _backups(path) -> list[str]:
    return [path.with_name(f"qalun.log.{index}").read_text() for index in (1, 2, 3)]


def test_rotation_keeps_three_older_copies() -> None:
    path = app_log.setup_logging()
    for index in (1, 2, 3):
        path.with_name(f"qalun.log.{index}").write_text(f"backup {index}\n")
    _fill(path, app_log.LOG_MAX_BYTES)

    logging.getLogger("qurantext.x").error("after the rollover")
    _flush()

    assert "after the rollover" in path.read_text(encoding="utf-8")
    assert path.stat().st_size < 1000
    assert path.with_name("qalun.log.1").stat().st_size > app_log.LOG_MAX_BYTES
    assert _backups(path)[1:] == ["backup 1\n", "backup 2\n"]
    assert not path.with_name("qalun.log.rotating").exists()


def test_a_refused_rotation_keeps_every_record_and_every_copy(monkeypatch) -> None:
    """Windows, two windows open: the current log cannot be renamed while the other holds it."""
    path = app_log.setup_logging()
    for index in (1, 2, 3):
        path.with_name(f"qalun.log.{index}").write_text(f"backup {index}\n")
    _fill(path, app_log.LOG_MAX_BYTES)

    real_replace, real_rename = os.replace, os.rename
    tries: list[str] = []

    def held_open(real):
        def move(src, dst):
            if os.fspath(src) == str(path):
                tries.append(os.fspath(dst))
                raise PermissionError(32, "The process cannot access the file")
            return real(src, dst)

        return move

    monkeypatch.setattr(os, "replace", held_open(real_replace))
    monkeypatch.setattr(os, "rename", held_open(real_rename))
    log = logging.getLogger("qurantext.gui.jobs")
    for n in range(50):
        log.error("record %d", n)
    _flush()

    text = path.read_text(encoding="utf-8")
    assert all(f"record {n}\n" in text for n in range(50)), "no record is dropped"
    assert _backups(path) == ["backup 1\n", "backup 2\n", "backup 3\n"], "no copy is lost"
    assert len(tries) == 1, "tried once, then not again until another tenth of the size"

    # Past the back-off it tries again and, the other window gone, rotates.
    monkeypatch.setattr(os, "replace", real_replace)
    monkeypatch.setattr(os, "rename", real_rename)
    _fill(path, app_log.LOG_MAX_BYTES // 10)
    log.error("after the other window closed")
    _flush()

    assert "after the other window closed" in path.read_text(encoding="utf-8")
    assert "record 49" in path.with_name("qalun.log.1").read_text(encoding="utf-8")
    assert _backups(path)[1:] == ["backup 1\n", "backup 2\n"]


@pytest.mark.skipif(sys.platform == "win32", reason="the fault log is Linux and macOS only")
def test_a_hard_crash_writes_its_stacks_to_the_fault_log(tmp_path) -> None:
    """Qt's abort on a running thread never reaches Python's hooks; faulthandler sees it."""
    import subprocess
    from pathlib import Path

    import qurantext

    script = (
        "import os, signal\n"
        "from qurantext.config import app_log\n"
        "app_log.configure()\n"
        "os.kill(os.getpid(), signal.SIGABRT)\n"
    )
    env = {
        **os.environ,
        "QURANTEXT_DATA_DIR": str(tmp_path / "data"),
        "PYTHONPATH": str(Path(qurantext.__file__).parents[1]),
    }
    result = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, timeout=60, check=False
    )

    assert result.returncode != 0
    faults = (tmp_path / "data" / "logs" / "faults.log").read_text(encoding="utf-8")
    assert "Fatal Python error: Aborted" in faults
    assert "line 4" in faults, "the Python stack that crashed is named"


@pytest.mark.skipif(sys.platform == "win32", reason="the fault log is Linux and macOS only")
def test_a_large_fault_log_is_set_aside_at_startup(tmp_path) -> None:
    faults = tmp_path / "data" / "logs" / "faults.log"
    faults.parent.mkdir(parents=True)
    faults.write_text("y" * (app_log.LOG_MAX_BYTES + 1))

    assert app_log.enable_fault_log() == faults

    assert faults.stat().st_size == 0
    assert faults.with_name("faults.log.1").stat().st_size == app_log.LOG_MAX_BYTES + 1


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows side of the fault log")
def test_windows_has_no_fault_log() -> None:
    assert app_log.enable_fault_log() is None

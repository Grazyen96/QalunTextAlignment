"""The frozen app's entry point.

Nothing here was covered until a build failed on it. The app is built windowed
so that double-clicking it does not flash a console, and a windowed process on
Windows starts with no standard output at all — so the text commands have to
find somewhere to write, without stealing output from a caller who redirected
them somewhere on purpose.
"""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest

ENTRY = Path(__file__).resolve().parents[1] / "packaging" / "entry.py"


#: What the doctor sets in its own process before Qt reads it; put back after every test.
_DOCTOR_VARIABLES = ("QT_MEDIA_BACKEND", "QT_LOGGING_RULES")


@pytest.fixture(autouse=True)
def _doctor_variables_restored(monkeypatch) -> None:
    for name in _DOCTOR_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="module")
def entry():
    spec = importlib.util.spec_from_file_location("qalun_entry", ENTRY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestStreamDetection:
    def test_no_stream_at_all(self, entry) -> None:
        """What a windowed Windows process actually starts with."""
        assert entry._usable(None) is False

    def test_a_real_file_is_usable(self, entry, tmp_path) -> None:
        with (tmp_path / "out.txt").open("w") as handle:
            assert entry._usable(handle) is True

    def test_an_in_memory_buffer_is_not(self, entry) -> None:
        """It has no file descriptor, so it is not somewhere a child can write."""
        assert entry._usable(io.StringIO()) is False

    def test_attaching_is_a_no_op_off_windows(self, entry) -> None:
        assert entry._attach_console() is None


class TestTextCommands:
    def test_version(self, entry, capsys) -> None:
        from qurantext import __version__

        assert entry.main(["--version"]) == 0
        assert __version__ in capsys.readouterr().out

    def test_help(self, entry, capsys) -> None:
        assert entry.main(["--help"]) == 0
        assert "--doctor" in capsys.readouterr().out

    def test_doctor_returns_a_verdict_and_leaves_a_report(self, entry, capsys) -> None:
        """The exit code is what the build gate reads, so it has to be a number."""
        code = entry.main(["--doctor"])
        assert code in (0, 1)
        out = capsys.readouterr().out
        assert "Arabic shaping" in out
        assert "report was saved to" in out

    def test_report_is_saved_where_it_says(self, entry, tmp_path, monkeypatch) -> None:
        saved = entry._save_report("a report")
        assert saved is not None
        assert Path(saved).read_text(encoding="utf-8") == "a report"

    def test_a_failed_save_does_not_take_the_command_down(self, entry, monkeypatch) -> None:
        """Diagnostics must never be the reason a command fails."""
        import qurantext.config.paths as paths

        def explode() -> Path:
            raise OSError("no writable location")

        monkeypatch.setattr(paths, "user_data_dir", explode)
        assert entry._save_report("a report") is None


def test_preload_runs_before_anything_imports_pillow(entry) -> None:
    """Ordering is the whole point: FriBiDi has to be in the process first."""
    source = ENTRY.read_text(encoding="utf-8")
    body = source[source.index("def main(") :]
    assert body.index("preload_fribidi()") < body.index("--doctor")
    assert "PIL" not in source, "importing Pillow here would defeat the preload"


def test_freeze_support_stays_behind_a_windows_check() -> None:
    """Calling it unconditionally hung the Linux build with no output at all."""
    source = ENTRY.read_text(encoding="utf-8")
    body = source[source.index("def main(") :]
    call = body.index("multiprocessing.freeze_support()")
    guard = body.index('if sys.platform == "win32":')
    assert guard < call, "freeze_support() must stay inside the Windows branch"


def test_every_text_command_can_reach_a_console() -> None:
    """Each one is something a person runs when the window will not help them."""
    source = ENTRY.read_text(encoding="utf-8")
    body = source[source.index("def main(") :]
    for flag in ("--help", "--version", "--doctor", "--cli"):
        branch = body.index(flag)
        following = body[branch : branch + 400]
        assert "_attach_console()" in following, f"{flag} would print nowhere on Windows"


class TestDoctorRelease:
    """The CI gate runs ``--doctor --release``: what a developer is told, a release fails on."""

    @staticmethod
    def _record(monkeypatch) -> list[bool]:
        from qurantext.config import preflight

        seen: list[bool] = []

        def fake(*, release: bool = False):
            seen.append(release)
            return [preflight.CheckResult("A", preflight.Status.OK, "fine")]

        monkeypatch.setattr(preflight, "run_checks", fake)
        return seen

    @pytest.fixture(autouse=True)
    def _no_saved_report(self, entry, monkeypatch) -> None:
        monkeypatch.setattr(entry, "_save_report", lambda report: None)

    @staticmethod
    def _record_environment(monkeypatch) -> list[dict[str, str | None]]:
        """What the checks would see of the two variables Qt reads once."""
        import os

        from qurantext.config import preflight

        seen: list[dict[str, str | None]] = []

        def fake(*, release: bool = False):
            seen.append({name: os.environ.get(name) for name in _DOCTOR_VARIABLES})
            return [preflight.CheckResult("A", preflight.Status.OK, "fine")]

        monkeypatch.setattr(preflight, "run_checks", fake)
        return seen

    def test_release_asks_qt_for_the_ffmpeg_backend(self, entry, monkeypatch, capsys) -> None:
        """Windows and macOS ship a native backend too; the gate must load through FFmpeg."""
        seen = self._record_environment(monkeypatch)
        assert entry.main(["--doctor", "--release"]) == 0
        assert seen[0]["QT_MEDIA_BACKEND"] == "ffmpeg"

    def test_plain_doctor_leaves_the_backend_to_qt(self, entry, monkeypatch, capsys) -> None:
        seen = self._record_environment(monkeypatch)
        assert entry.main(["--doctor"]) == 0
        assert seen[0]["QT_MEDIA_BACKEND"] is None

    def test_a_backend_someone_chose_is_theirs(self, entry, monkeypatch, capsys) -> None:
        monkeypatch.setenv("QT_MEDIA_BACKEND", "windows")
        seen = self._record_environment(monkeypatch)
        entry.main(["--doctor", "--release"])
        assert seen[0]["QT_MEDIA_BACKEND"] == "windows"

    def test_the_ffmpeg_plugin_keeps_quiet_in_the_report(self, entry, monkeypatch, capsys) -> None:
        """It prints the test recording's stream details to stderr, into the report a user sends."""
        seen = self._record_environment(monkeypatch)
        entry.main(["--doctor"])
        assert seen[0]["QT_LOGGING_RULES"] == "qt.multimedia.ffmpeg*=false"

    def test_logging_rules_already_set_are_kept(self, entry, monkeypatch, capsys) -> None:
        monkeypatch.setenv("QT_LOGGING_RULES", "qt.qpa.*=true")
        seen = self._record_environment(monkeypatch)
        entry.main(["--doctor"])
        assert seen[0]["QT_LOGGING_RULES"] == "qt.qpa.*=true;qt.multimedia.ffmpeg*=false"

    def test_release_is_strict(self, entry, monkeypatch, capsys) -> None:
        seen = self._record(monkeypatch)
        assert entry.main(["--doctor", "--release"]) == 0
        assert seen == [True]

    def test_plain_doctor_is_not(self, entry, monkeypatch, capsys) -> None:
        seen = self._record(monkeypatch)
        assert entry.main(["--doctor"]) == 0
        assert seen == [False]

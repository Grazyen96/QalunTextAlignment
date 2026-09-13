"""The startup check.

A packaged app that will not render is exactly when someone has no Python to
diagnose it with, so the checks have to be readable and their remedies have to
be instructions rather than diagnoses.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from qurantext.config import preflight
from qurantext.config.preflight import CheckResult, Status, format_report, run_checks


def test_every_check_reports_a_status_and_a_detail() -> None:
    results = run_checks()
    assert results
    assert all(r.status in (Status.OK, Status.WARN, Status.FAIL) for r in results)
    assert all(r.detail for r in results)


def test_anything_not_ok_says_what_to_do() -> None:
    """A status with no remedy leaves the reader stuck."""
    for result in run_checks():
        if result.status != Status.OK:
            assert result.remedy, f"{result.name} reports a problem with no remedy"


def test_arabic_shaping_is_checked_first() -> None:
    """It is the most likely reason a packaged build draws nothing."""
    assert run_checks()[0].name == "Arabic shaping"


def test_missing_shaping_is_blocking_and_names_each_platform(monkeypatch) -> None:
    class _Features:
        @staticmethod
        def check(name):
            return False

        @staticmethod
        def version(name):
            return "0"

    import PIL

    monkeypatch.setattr(PIL, "features", _Features, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "PIL.features", _Features)

    result = preflight._arabic_shaping()
    assert result.blocking
    for platform_hint in ("apt", "brew", "fribidi.dll"):
        assert platform_hint in result.remedy


def test_the_report_ends_with_a_verdict() -> None:
    ok = [CheckResult("A", Status.OK, "fine")]
    assert format_report(ok).rstrip().endswith("Ready to render.")

    bad = [CheckResult("A", Status.FAIL, "broken", "fix it")]
    report = format_report(bad)
    assert "Cannot render yet" in report
    assert "fix it" in report


def test_a_warning_is_not_a_blocker() -> None:
    results = [CheckResult("A", Status.WARN, "not built yet", "build it")]
    assert not results[0].blocking
    assert format_report(results).rstrip().endswith("Ready to render.")


class TestBundledFriBiDi:
    """Pillow loads FriBiDi by name at runtime and no wheel contains one.

    A packaged app therefore ships its own and loads it before Pillow asks, so
    that the answer does not depend on three different loaders searching three
    different places. These cover the lookup; whether the library shapes Arabic
    is what `--doctor` reports on each platform.
    """

    def test_names_are_what_each_loader_is_asked_for(self, monkeypatch):
        from qurantext.config import fribidi

        monkeypatch.setattr(fribidi.sys, "platform", "win32")
        assert fribidi.fribidi_names()[0] == "fribidi-0.dll"
        monkeypatch.setattr(fribidi.sys, "platform", "darwin")
        assert fribidi.fribidi_names()[0] == "libfribidi.dylib"
        monkeypatch.setattr(fribidi.sys, "platform", "linux")
        assert fribidi.fribidi_names()[0] == "libfribidi.so.0"

    def test_a_checkout_is_left_alone(self, monkeypatch):
        """Outside a frozen app the system library is used, as it always was."""
        from qurantext.config.fribidi import preload_fribidi

        monkeypatch.delattr(sys, "frozen", raising=False)
        assert preload_fribidi() is None

    def test_packaged_app_loads_the_copy_beside_it(self, monkeypatch, tmp_path):
        from qurantext.config import fribidi

        system = Path("/usr/lib/x86_64-linux-gnu/libfribidi.so.0")
        if not system.is_file():
            pytest.skip("no system FriBiDi to copy")
        shutil.copy(system, tmp_path / "libfribidi.so.0")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "qalun"))

        loaded = fribidi.preload_fribidi()
        assert loaded == str(tmp_path / "libfribidi.so.0")

    def test_nothing_shipped_is_not_a_crash(self, monkeypatch, tmp_path):
        """It degrades to the system library; preflight reports the failure."""
        from qurantext.config.fribidi import preload_fribidi

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "qalun"))
        assert preload_fribidi() is None

    def test_a_file_that_is_not_a_library_is_skipped(self, monkeypatch, tmp_path):
        from qurantext.config import fribidi

        for name in fribidi.fribidi_names():
            (tmp_path / name).write_text("not a shared library")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "qalun"))
        assert fribidi.preload_fribidi() is None

    def test_remedy_tells_a_packaged_user_it_is_not_their_fault(self, monkeypatch):
        """The old remedy said to reinstall Pillow, which cannot ever help."""
        from PIL import features

        from qurantext.config import preflight

        monkeypatch.setattr(features, "check", lambda name: False)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        result = preflight._arabic_shaping()
        assert result.status == preflight.Status.FAIL
        assert "reinstall" not in (result.remedy or "").lower()
        assert "report it" in (result.remedy or "").lower()


class TestTranscriptionCheck:
    """A build passed every check here, rendered video, then died mid-job.

    The Replicate client reads its own version out of its installed metadata
    when imported, and a frozen build ships none unless the spec says so. A gate
    that proves rendering and never touches transcription lets that through, so
    this check imports the client for real.
    """

    def test_reports_the_client_version_and_that_a_token_exists(self, monkeypatch) -> None:
        from qurantext.config import preflight
        from qurantext.config.settings import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_secret_value_1234")
        result = preflight._transcription()
        get_settings.cache_clear()

        assert result.status == preflight.Status.OK
        assert "Replicate client" in result.detail

    def test_never_prints_the_whole_token(self, monkeypatch) -> None:
        """It goes in a report people are asked to send to someone else."""
        from qurantext.config import preflight
        from qurantext.config.settings import get_settings

        secret = "r8_secret_value_1234"
        get_settings.cache_clear()
        monkeypatch.setenv("REPLICATE_API_TOKEN", secret)
        result = preflight._transcription()
        get_settings.cache_clear()

        assert secret not in result.detail
        assert secret[-4:] in result.detail

    def test_a_missing_token_warns_and_names_the_file_to_create(self, monkeypatch) -> None:
        from qurantext.config import preflight
        from qurantext.config.settings import get_settings

        get_settings.cache_clear()
        # Empty rather than absent: the process environment is restored over
        # anything a .env file supplies, so this is what "no token" looks like
        # even in a checkout that has one.
        monkeypatch.setenv("REPLICATE_API_TOKEN", "")
        monkeypatch.setattr(preflight, "user_data_dir", lambda: Path("/somewhere/qalun"))
        result = preflight._transcription()
        get_settings.cache_clear()

        assert result.status == preflight.Status.WARN
        assert not result.blocking, "rendering still works without a token"
        assert ".env" in (result.remedy or "")
        assert "REPLICATE_API_TOKEN" in (result.remedy or "")

    def test_missing_metadata_is_caught_here_rather_than_mid_job(self, monkeypatch) -> None:
        """The exact fault: no .dist-info in the bundle, so the import raises."""
        import importlib.metadata as metadata

        from qurantext.config import preflight

        real = metadata.version

        def hidden(name: str) -> str:
            if name == "replicate":
                raise metadata.PackageNotFoundError(name)
            return real(name)

        monkeypatch.setattr(metadata, "version", hidden)
        monkeypatch.delitem(sys.modules, "replicate", raising=False)
        result = preflight._transcription()

        assert result.status == preflight.Status.FAIL
        assert "No package metadata" in result.detail

    def test_a_packaged_user_is_told_it_is_not_their_fault(self, monkeypatch) -> None:
        import importlib.metadata as metadata

        from qurantext.config import preflight

        monkeypatch.setattr(
            metadata, "version", lambda n: (_ for _ in ()).throw(metadata.PackageNotFoundError(n))
        )
        monkeypatch.delitem(sys.modules, "replicate", raising=False)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        result = preflight._transcription()

        assert "report it" in (result.remedy or "").lower()

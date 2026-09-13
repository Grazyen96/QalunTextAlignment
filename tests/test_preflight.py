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

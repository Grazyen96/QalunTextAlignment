"""The startup check.

A packaged app that will not render is exactly when someone has no Python to
diagnose it with, so the checks have to be readable and their remedies have to
be instructions rather than diagnoses.
"""

from __future__ import annotations

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

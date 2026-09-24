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


class TestWhatThePackagedAppMustDo:
    """Playback, Qt's Arabic translation and an Arabic interface font.

    Each is a separate file a frozen build can leave behind while every module
    still imports, so each is exercised rather than imported. A developer's
    checkout is only told; a release (``--doctor --release``, the CI gate) fails.
    """

    def test_playback_loads_a_short_recording(self, qt_app) -> None:
        result = preflight._playback(release=True)
        assert result.status == Status.OK, result
        assert "FFmpeg" in result.detail or "backend" in result.detail

    def test_playback_names_the_backend_it_loaded_through(self, qt_app) -> None:
        """What is on disk is not what plays: Qt falls back when the one asked for fails."""
        result = preflight._playback(release=False)
        assert result.status == Status.OK, result
        assert "through the FFmpeg backend" in result.detail
        assert "plugins on disk: FFmpeg" in result.detail

    def test_the_loaded_plugin_is_found_in_this_process(self, qt_app) -> None:
        preflight._load_test_recording()
        assert preflight._media_backends_loaded() == ["FFmpeg"]

    def test_a_release_that_fell_back_to_another_backend_fails(self, qt_app, monkeypatch) -> None:
        """Qt 6.11 loads an "alternative backend" when the forced one will not load, and
        the recording plays; only the loaded plugin shows FFmpeg was left behind."""
        monkeypatch.setenv("QT_MEDIA_BACKEND", "ffmpeg")
        monkeypatch.setattr(preflight, "_load_test_recording", lambda: (True, "0.50 s"))
        monkeypatch.setattr(
            preflight, "_media_backends_loaded", lambda: ["Windows Media Foundation"]
        )
        result = preflight._playback(release=True)
        assert result.status == Status.FAIL
        assert "not through the FFmpeg backend" in result.detail
        assert "Windows Media Foundation" in result.detail
        assert preflight._playback(release=False).status == Status.WARN

    def test_a_release_that_cannot_tell_its_backend_fails(self, qt_app, monkeypatch) -> None:
        monkeypatch.setenv("QT_MEDIA_BACKEND", "ffmpeg")
        monkeypatch.setattr(preflight, "_load_test_recording", lambda: (True, "0.50 s"))
        monkeypatch.setattr(preflight, "_media_backends_loaded", lambda: None)
        assert preflight._playback(release=True).status == Status.FAIL

    def test_a_forced_backend_that_loaded_is_named_as_forced(self, qt_app, monkeypatch) -> None:
        monkeypatch.setenv("QT_MEDIA_BACKEND", "ffmpeg")
        monkeypatch.setattr(preflight, "_load_test_recording", lambda: (True, "0.50 s"))
        monkeypatch.setattr(preflight, "_media_backends_loaded", lambda: ["FFmpeg"])
        result = preflight._playback(release=True)
        assert result.status == Status.OK
        assert "through the FFmpeg backend, as QT_MEDIA_BACKEND asks;" in result.detail

    def test_playback_missing_is_a_note_for_a_developer_and_a_failure_for_a_release(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            preflight,
            "_import_multimedia",
            lambda: (_ for _ in ()).throw(ImportError("no QtMultimedia")),
        )
        assert preflight._playback(release=False).status == Status.WARN
        assert preflight._playback(release=True).status == Status.FAIL

    def test_a_recording_that_never_loads_fails_a_release(self, qt_app, monkeypatch) -> None:
        """The plugin missing looks like this: the module imports, the file will not load."""
        monkeypatch.setattr(preflight, "_load_test_recording", lambda: (False, "InvalidMedia"))
        result = preflight._playback(release=True)
        assert result.status == Status.FAIL
        assert "InvalidMedia" in result.detail
        assert result.remedy

    def test_the_arabic_window_translation_is_found(self) -> None:
        assert preflight._qt_translation(release=True).status == Status.OK

    def test_a_missing_translation_says_what_the_arabic_window_loses(
        self, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setattr(preflight, "_qt_translations_folder", lambda: str(tmp_path))
        assert preflight._qt_translation(release=False).status == Status.WARN
        result = preflight._qt_translation(release=True)
        assert result.status == Status.FAIL
        assert "English" in result.detail

    def test_no_arabic_font_fails_a_release(self, monkeypatch) -> None:
        monkeypatch.setattr(preflight, "arabic_ui_families", lambda: [])
        assert preflight._arabic_ui_font(release=False).status == Status.WARN
        result = preflight._arabic_ui_font(release=True)
        assert result.status == Status.FAIL
        assert "Noto Sans Arabic" in result.remedy

    def test_an_arabic_font_is_named(self, monkeypatch) -> None:
        monkeypatch.setattr(preflight, "arabic_ui_families", lambda: ["A", "B", "C"])
        result = preflight._arabic_ui_font(release=True)
        assert result.status == Status.OK
        assert "A, B" in result.detail

    def test_a_font_that_cannot_be_measured_is_not_passed(self, monkeypatch) -> None:
        def cannot() -> list[str]:
            raise preflight.CannotMeasureFonts("no display")

        monkeypatch.setattr(preflight, "arabic_ui_families", cannot)
        assert preflight._arabic_ui_font(release=False).status == Status.WARN
        result = preflight._arabic_ui_font(release=True)
        assert result.status == Status.FAIL
        assert "no display" in result.detail

    def test_the_bundled_quran_font_is_not_an_interface_font(self, qt_app) -> None:
        """It has no Latin letters, so finding it must not count as having one."""
        from PySide6.QtGui import QFontDatabase

        from qurantext.config.paths import DEFAULT_FONT_PATH

        font_id = QFontDatabase.addApplicationFont(str(DEFAULT_FONT_PATH))
        assert font_id != -1
        try:
            quran = QFontDatabase.applicationFontFamilies(font_id)[0]
            assert quran in QFontDatabase.families(QFontDatabase.WritingSystem.Arabic)
            assert quran not in preflight.arabic_ui_families()
        finally:
            QFontDatabase.removeApplicationFont(font_id)

    def test_release_checks_include_the_new_ones(self) -> None:
        names = {r.name for r in run_checks(release=True)}
        assert {"Playback", "Window translation", "Arabic interface font"} <= names

    def test_a_headless_linux_doctor_draws_offscreen(self, monkeypatch) -> None:
        """With no platform chosen, Qt would try a display a CI machine lacks, and abort."""
        monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
        monkeypatch.setattr(preflight.sys, "platform", "linux")
        monkeypatch.setattr(preflight, "_platform_plugin_found", lambda name: True)
        assert preflight._doctor_platform() == (True, "offscreen")

    def test_a_chosen_platform_is_left_alone(self, monkeypatch) -> None:
        monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")
        assert preflight._doctor_platform() == (True, None)

    def test_no_platform_plugin_means_no_window_application(self, monkeypatch) -> None:
        monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
        monkeypatch.setattr(preflight.sys, "platform", "win32")
        monkeypatch.setattr(preflight, "_platform_plugin_found", lambda name: False)
        assert preflight._doctor_platform() == (False, None)

    def test_the_platform_plugin_probe_finds_what_qt_ships(self) -> None:
        pytest.importorskip("PySide6")
        assert preflight._platform_plugin_found("offscreen")
        assert not preflight._platform_plugin_found("no-such-platform")

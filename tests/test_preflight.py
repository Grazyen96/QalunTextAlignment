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


def test_the_report_says_which_version_it_is_about() -> None:
    """The report is the file people are asked to send, so it names the version."""
    from qurantext import __version__

    report = format_report([CheckResult("A", Status.OK, "fine")])
    assert report.splitlines()[0] == f"Qalun {__version__} on {sys.platform}"


def test_the_report_names_qaluns_licence_without_judging_it() -> None:
    """Qalun is GPL-3.0-only; the report says so on one line. It is not a check, so it
    can never block, and the verdict is unchanged."""
    report = format_report([CheckResult("A", Status.OK, "fine")])
    licence = [line for line in report.splitlines() if "GPL-3.0-only" in line]
    assert licence == [
        "  licensed GPL-3.0-only, Copyright (C) 2026 Khalil; see LICENSE and THIRD_PARTY_NOTICES.md"
    ]
    assert report.rstrip().endswith("Ready to render.")


def test_a_release_check_that_fails_does_not_claim_rendering_is_broken() -> None:
    """Without playback, Qt's Arabic or an Arabic font the app still renders; the build
    is only unfit to ship, and whoever reads the report should be told that."""
    for name in (
        "Playback",
        "Window translation",
        "Arabic interface font",
        "Transcription",
        "WhisperX online (optional)",
        "On this computer (optional)",
    ):
        report = format_report([CheckResult(name, Status.FAIL, "missing", "fix it")], release=True)
        assert report.rstrip().endswith("Not ready for release: 1 problem(s) above."), name
        assert "Cannot render" not in report


def test_outside_a_release_a_failure_that_leaves_rendering_working_names_what_cannot_run() -> None:
    """A person running a plain doctor is not shipping anything: "Not ready for release"
    would only puzzle them. They are told rendering works and what does not yet."""
    report = format_report([CheckResult("Transcription", Status.FAIL, "missing", "fix it")])
    assert report.rstrip().endswith("Rendering works; Transcription cannot run yet: see above.")
    assert "release" not in report.lower()

    both = [
        CheckResult("Transcription", Status.FAIL, "missing", "fix it"),
        CheckResult("Playback", Status.FAIL, "missing", "fix it"),
    ]
    assert (
        format_report(both)
        .rstrip()
        .endswith("Rendering works; Transcription and Playback cannot run yet: see above.")
    )


def test_a_render_check_that_fails_says_so_whatever_else_fails() -> None:
    results = [
        CheckResult("Arabic shaping", Status.FAIL, "no raqm", "install it"),
        CheckResult("Playback", Status.FAIL, "missing", "fix it"),
    ]
    assert (
        format_report(results)
        .rstrip()
        .endswith("Cannot render yet: 2 problem(s) above must be fixed.")
    )


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
        result = preflight._whisperx_check()
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
        result = preflight._whisperx_check()
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
        monkeypatch.setattr(preflight, "env_dir", lambda: Path("/somewhere/qalun"))
        result = preflight._whisperx_check()
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
        result = preflight._whisperx_check()

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
        result = preflight._whisperx_check()

        assert "report it" in (result.remedy or "").lower()


class TestWhatThePackagedAppMustDo:
    """Playback, Qt's Arabic translation and Qt's font list for the Arabic interface.

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

    def test_a_release_that_loaded_a_second_backend_too_fails(self, qt_app, monkeypatch) -> None:
        """Two loaded means the one asked for was tried and something else took over."""
        monkeypatch.setenv("QT_MEDIA_BACKEND", "ffmpeg")
        monkeypatch.setattr(preflight, "_load_test_recording", lambda: (True, "0.50 s"))
        monkeypatch.setattr(
            preflight, "_media_backends_loaded", lambda: ["FFmpeg", "Windows Media Foundation"]
        )
        assert preflight._playback(release=True).status == Status.FAIL

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

    def test_the_arabic_window_translation_is_found(self, qt_app) -> None:
        assert preflight._qt_translation(release=True).status == Status.OK

    def test_a_missing_translation_says_what_the_arabic_window_loses(
        self, qt_app, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setattr(preflight, "_qt_translations_folder", lambda: str(tmp_path))
        assert preflight._qt_translation(release=False).status == Status.WARN
        result = preflight._qt_translation(release=True)
        assert result.status == Status.FAIL
        assert "English" in result.detail

    def test_no_arabic_font_names_the_bundled_fallback(self, monkeypatch) -> None:
        """The window draws Arabic in the bundled Noto then: nothing to fix, nothing to block."""
        monkeypatch.setattr(preflight, "arabic_ui_families", lambda: [])
        for release in (False, True):
            result = preflight._arabic_ui_font(release=release)
            assert result.status == Status.OK, release
            assert "bundled Noto Sans Arabic" in result.detail
            assert "Quran" not in result.detail and not result.remedy

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
        assert {
            "Playback",
            "Window translation",
            "Arabic interface font",
            "Interface icons",
        } <= names

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


class TestMissingSystemLibrary:
    """Qt links libraries a Linux system provides (EGL, PulseAudio). When one is missing,
    the import fails with the library's name, and that name is the whole diagnosis: the
    report must say which one and where it comes from, not blame packaging or pip."""

    _EGL = ImportError("libEGL.so.1: cannot open shared object file: No such file or directory")
    _PULSE = ImportError("libpulse.so.0: cannot open shared object file: No such file or directory")

    def test_the_missing_library_is_read_from_the_error(self) -> None:
        assert preflight._missing_system_library(self._EGL) == "libEGL.so.1"
        assert preflight._missing_system_library(ImportError("No module named 'PySide6'")) is None

    @pytest.mark.parametrize("frozen", [True, False])
    def test_playback_names_the_library_and_its_package(self, monkeypatch, frozen) -> None:
        monkeypatch.setattr(preflight, "_frozen", lambda: frozen)

        def missing():
            raise self._PULSE

        monkeypatch.setattr(preflight, "_load_test_recording", missing)
        result = preflight._playback(release=True)
        assert result.status == Status.FAIL
        assert "libpulse.so.0" in result.detail
        assert "libpulse0" in result.remedy
        assert "not bundled" not in result.remedy and "pip install" not in result.remedy

    def test_the_font_check_names_the_graphics_library(self, monkeypatch) -> None:
        monkeypatch.setattr(preflight, "_frozen", lambda: True)

        def missing():
            raise self._EGL

        monkeypatch.setattr(preflight, "arabic_ui_families", missing)
        result = preflight._arabic_ui_font(release=True)
        assert result.status == Status.FAIL
        assert "libEGL.so.1" in result.detail
        assert "libegl1" in result.remedy
        assert "Qt is not installed" not in result.detail

    def test_the_icon_check_names_the_module_that_failed(self, monkeypatch) -> None:
        """A Qt without QtSvg is not "Qt is not installed"; the line says what is missing."""
        import builtins

        real_import = builtins.__import__

        def no_svg(name, *args, **kwargs):
            if name == "qurantext.gui.icons":
                raise ImportError("No module named 'PySide6.QtSvg'", name="PySide6.QtSvg")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_svg)
        result = preflight._interface_icons()
        assert result.status == Status.WARN
        assert "PySide6.QtSvg" in result.detail
        assert "Qt is not installed" not in result.detail

    def test_an_unknown_library_still_says_what_to_look_for(self) -> None:
        remedy = preflight._system_library_remedy("libfoo.so.3")
        assert "libfoo.so.3" in remedy


def _lines(results: list[CheckResult]) -> dict[str, CheckResult]:
    return {r.name: r for r in results}


def _hide_replicate_metadata(monkeypatch) -> None:
    """The packaging fault the release gate exists for: no metadata, so the import fails."""
    import importlib.metadata as metadata

    real = metadata.version

    def hidden(name: str) -> str:
        if name == "replicate":
            raise metadata.PackageNotFoundError(name)
        return real(name)

    monkeypatch.setattr(metadata, "version", hidden)
    monkeypatch.delitem(sys.modules, "replicate", raising=False)


class TestTranscriptionEngineChoice:
    """Both engines are reported; only the configured one's problems block."""

    CONFIGURED = "Transcription"
    LOCAL = "On this computer (optional)"
    WHISPERX = "WhisperX online (optional)"

    @pytest.fixture
    def engine(self, monkeypatch):
        from qurantext.config.settings import get_settings

        def use(name: str) -> None:
            monkeypatch.setenv("QURANTEXT_TRANSCRIBE_ENGINE", name)
            get_settings.cache_clear()

        yield use
        get_settings.cache_clear()

    @pytest.fixture
    def local_ready(self, monkeypatch):
        from qurantext.services import engine_local, model_store

        monkeypatch.setattr(engine_local, "runtime_problem", lambda: None)
        monkeypatch.setattr(model_store, "is_installed", lambda m: True)

    def test_local_without_the_runtime_is_blocking(self, engine, monkeypatch) -> None:
        from qurantext.services import engine_local

        engine("local")
        monkeypatch.setattr(engine_local, "runtime_problem", lambda: "no sherpa")
        result = _lines(preflight._transcription())[self.CONFIGURED]
        assert result.status == Status.FAIL and "sherpa-onnx" in result.detail

    def test_a_missing_runtime_from_source_says_how_to_reinstall(self, engine, monkeypatch) -> None:
        from qurantext.services import engine_local

        engine("local")
        monkeypatch.setattr(engine_local, "runtime_problem", lambda: "no sherpa")
        monkeypatch.delattr(sys, "frozen", raising=False)
        remedy = _lines(preflight._transcription())[self.CONFIGURED].remedy
        assert "pip install -e ." in remedy
        assert "WhisperX online" in remedy

    def test_a_missing_runtime_in_the_packaged_app_is_a_packaging_fault(
        self, engine, monkeypatch
    ) -> None:
        """Reinstalling the same download would not help; the person is told so."""
        from qurantext.services import engine_local

        engine("local")
        monkeypatch.setattr(engine_local, "runtime_problem", lambda: "no sherpa")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        remedy = _lines(preflight._transcription())[self.CONFIGURED].remedy
        assert "report it" in remedy.lower()
        assert "pip" not in remedy and "reinstall" not in remedy.lower()
        assert "WhisperX online" in remedy

    def test_runtime_problem_reports_an_unimportable_sherpa(self, monkeypatch) -> None:
        import builtins

        from qurantext.services import engine_local

        real_import = builtins.__import__

        def no_sherpa(name, *args, **kwargs):
            if name == "sherpa_onnx":
                raise ImportError("no sherpa")
            return real_import(name, *args, **kwargs)

        monkeypatch.delitem(sys.modules, "sherpa_onnx", raising=False)
        monkeypatch.setattr(builtins, "__import__", no_sherpa)
        assert engine_local.runtime_problem() == "no sherpa"

    def test_runtime_problem_passes_the_real_runtime(self) -> None:
        """The other local tests stub it, so this is the one that loads sherpa-onnx."""
        pytest.importorskip("sherpa_onnx")
        from qurantext.services import engine_local

        assert engine_local.runtime_problem() is None

    def test_local_with_no_model_yet_only_informs(self, engine, monkeypatch) -> None:
        from qurantext.services import engine_local, model_store

        engine("local")
        monkeypatch.setattr(engine_local, "runtime_problem", lambda: None)
        monkeypatch.setattr(model_store, "is_installed", lambda m: False)
        result = _lines(preflight._transcription())[self.CONFIGURED]
        assert result.status == Status.WARN
        assert "first use" in result.detail
        assert f"about {model_store.LOCAL_MODEL.download_mb} MB" in result.detail

    def test_local_states_the_memory_transcription_needs(
        self, engine, local_ready, monkeypatch
    ) -> None:
        """A long job on a small machine can run out of memory, and on Linux the window
        then simply vanishes, so the doctor says what it takes, as information only,
        installed or not, and for the optional line too."""
        from qurantext.services import engine_local, model_store

        memory = f"up to about {engine_local.PEAK_MEMORY_GB} GB of memory"
        assert engine_local.PEAK_MEMORY_GB == 1.8
        engine("local")
        installed = _lines(preflight._transcription())[self.CONFIGURED]
        assert installed.status == Status.OK and memory in installed.detail
        monkeypatch.setattr(model_store, "is_installed", lambda m: False)
        missing = _lines(preflight._transcription())[self.CONFIGURED]
        assert missing.status == Status.WARN and memory in missing.detail
        engine("whisperx")
        monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_secret_value_1234")
        optional = _lines(preflight._transcription())[self.LOCAL]
        assert optional.status == Status.OK and memory in optional.detail

    def test_local_names_the_model_and_its_licence(self, engine, local_ready) -> None:
        engine("local")
        result = _lines(preflight._transcription())[self.CONFIGURED]
        assert result.status == Status.OK
        assert "NVIDIA" in result.detail and "CC BY 4.0" in result.detail

    def test_the_model_named_is_the_one_the_app_downloads(
        self, engine, local_ready, monkeypatch
    ) -> None:
        """A new model release must not leave the doctor crediting the old one."""
        import dataclasses

        from qurantext.services import model_store

        engine("local")
        assert model_store.LOCAL_MODEL.model_id.split("/")[-1] in (
            _lines(preflight._transcription())[self.CONFIGURED].detail
        )
        newer = dataclasses.replace(model_store.LOCAL_MODEL, model_id="nvidia/stt_ar_newer_v2")
        monkeypatch.setattr(model_store, "LOCAL_MODEL", newer)
        detail = _lines(preflight._transcription())[self.CONFIGURED].detail
        assert "stt_ar_newer_v2" in detail
        assert "pcd_v1.0" not in detail

    def test_no_replicate_token_is_not_a_problem_for_the_local_engine(
        self, engine, local_ready, monkeypatch
    ) -> None:
        monkeypatch.setenv("REPLICATE_API_TOKEN", "")
        engine("local")
        results = preflight._transcription()
        assert not any(r.blocking for r in results)
        whisperx = _lines(results)[self.WHISPERX]
        assert whisperx.status == Status.OK
        assert "no API token" in whisperx.detail
        assert "not needed unless you choose WhisperX online" in whisperx.detail

    def test_local_reports_whisperx_as_information_too(
        self, engine, local_ready, monkeypatch
    ) -> None:
        monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_secret_value_1234")
        engine("local")
        results = preflight._transcription()
        assert [r.name for r in results] == [self.CONFIGURED, self.WHISPERX]
        whisperx = _lines(results)[self.WHISPERX]
        assert whisperx.status == Status.OK and "Replicate client" in whisperx.detail
        assert "r8_secret_value_1234" not in whisperx.detail

    def test_a_broken_replicate_client_is_only_a_note_outside_a_release(
        self, engine, local_ready, monkeypatch
    ) -> None:
        engine("local")
        _hide_replicate_metadata(monkeypatch)
        results = _lines(preflight._transcription(release=False))
        assert results[self.CONFIGURED].status == Status.OK
        assert results[self.WHISPERX].status == Status.WARN
        assert "No package metadata" in results[self.WHISPERX].detail

    def test_a_broken_replicate_client_fails_a_release_whatever_is_configured(
        self, engine, local_ready, monkeypatch
    ) -> None:
        """The window offers WhisperX, so a release must carry its client."""
        engine("local")
        _hide_replicate_metadata(monkeypatch)
        results = preflight._transcription(release=True)
        whisperx = _lines(results)[self.WHISPERX]
        assert whisperx.status == Status.FAIL
        report = format_report(results, release=True)
        assert report.rstrip().endswith("Not ready for release: 1 problem(s) above.")

    def test_a_packaged_broken_client_does_not_claim_transcription_is_down(
        self, engine, local_ready, monkeypatch
    ) -> None:
        engine("local")
        _hide_replicate_metadata(monkeypatch)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        remedy = _lines(preflight._transcription())[self.WHISPERX].remedy
        assert "report it" in remedy.lower()
        assert "on this computer is unaffected" in remedy

    def test_the_release_gate_runs_the_replicate_check(self, engine, monkeypatch) -> None:
        engine("local")
        _hide_replicate_metadata(monkeypatch)
        names = {r.name: r.status for r in run_checks(release=True)}
        assert names[self.WHISPERX] == Status.FAIL

    def test_whisperx_keeps_todays_token_check(self, engine, monkeypatch) -> None:
        monkeypatch.setenv("REPLICATE_API_TOKEN", "")
        engine("whisperx")
        results = preflight._transcription()
        assert results[0] == preflight._whisperx_check()
        assert [r.name for r in results] == [self.CONFIGURED, self.LOCAL]

    def test_whisperx_reports_the_local_engine_as_information(self, engine, monkeypatch) -> None:
        from qurantext.services import engine_local, model_store

        monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_secret_value_1234")
        engine("whisperx")
        monkeypatch.setattr(engine_local, "runtime_problem", lambda: None)
        monkeypatch.setattr(model_store, "is_installed", lambda m: False)
        local = _lines(preflight._transcription(release=True))[self.LOCAL]
        assert local.status == Status.OK, "not downloaded yet is nothing to do"
        assert "NVIDIA" in local.detail and "CC BY 4.0" in local.detail

    def test_whisperx_users_are_only_told_the_local_runtime_is_missing(
        self, engine, monkeypatch
    ) -> None:
        from qurantext.services import engine_local

        monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_secret_value_1234")
        engine("whisperx")
        monkeypatch.setattr(engine_local, "runtime_problem", lambda: "no sherpa")
        for release in (False, True):
            results = preflight._transcription(release=release)
            local = _lines(results)[self.LOCAL]
            assert local.status == Status.WARN, release
            assert local.remedy and "choose WhisperX" not in local.remedy, "they already use it"
            assert not any(r.blocking for r in results), release

    def test_an_unknown_engine_is_a_failure_that_names_the_choices(
        self, engine, local_ready
    ) -> None:
        """The CLI stops with this; the doctor must not report a healthy engine."""
        engine("cohere")
        results = preflight._transcription()
        configured = _lines(results)[self.CONFIGURED]
        assert configured.status == Status.FAIL
        assert "'cohere'" in configured.detail and "local, whisperx" in configured.detail
        assert "QURANTEXT_TRANSCRIBE_ENGINE" in configured.remedy
        assert {self.LOCAL, self.WHISPERX} <= set(_lines(results))
        assert (
            format_report(results)
            .rstrip()
            .endswith("Rendering works; Transcription cannot run yet: see above.")
        )


def test_an_ffmpeg_that_cannot_join_an_episode_is_named(monkeypatch) -> None:
    """The join's filters are checked at the gate, not found missing in a person's first episode."""
    full = frozenset({"apad", "setparams", "sidedata", "zscale", "tonemap"})
    monkeypatch.setattr(preflight, "ffmpeg_filters", lambda path: full)
    assert preflight._episode_join(release=True).status == Status.OK

    monkeypatch.setattr(preflight, "ffmpeg_filters", lambda path: full - {"zscale"})
    result = preflight._episode_join(release=True)
    assert result.status == Status.WARN and "zscale" in result.detail and result.remedy

    monkeypatch.setattr(preflight, "ffmpeg_filters", lambda path: full - {"sidedata"})
    assert preflight._episode_join(release=False).status == Status.WARN
    failed = preflight._episode_join(release=True)
    assert failed.status == Status.FAIL and "sidedata" in failed.detail
    report = format_report([failed], release=True)
    assert "Cannot render" not in report, "the lecture still renders without it"


_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.mark.skipif(not _HAS_FFMPEG, reason="needs FFmpeg and ffprobe")
def test_the_release_gate_joins_two_tiny_clips_for_real(monkeypatch) -> None:
    """A renamed filter option passes the filter list; only a real join finds it."""
    import time

    from qurantext.jobs import episode

    started = time.monotonic()
    passed = preflight._episode_join(release=True)
    assert passed.status in (Status.OK, Status.WARN), passed.detail
    assert "trial join" in passed.detail or passed.status == Status.WARN
    assert time.monotonic() - started < 5, "the gate stays quick"

    real_graph = episode._filter_graph

    def renamed_option(*args, **kwargs):
        inputs, graph = real_graph(*args, **kwargs)
        return inputs, graph.replace("type=DISPLAYMATRIX", "kind=DISPLAYMATRIX")

    monkeypatch.setattr(episode, "_filter_graph", renamed_option)
    failed = preflight._episode_join(release=True)
    assert failed.status == Status.FAIL and "trial join" in failed.detail and failed.remedy
    # A developer's checkout is only told about the filters; it does not join.
    assert preflight._episode_join(release=False).status in (Status.OK, Status.WARN)


@pytest.mark.skipif(not _HAS_FFMPEG, reason="needs FFmpeg and ffprobe")
def test_the_trial_join_runs_the_tone_map_chain_when_ffmpeg_has_it(monkeypatch) -> None:
    """An HDR phone intro is tone-mapped; a renamed zscale option must fail the gate too."""
    from qurantext.core.video_common import ffmpeg_filters, require_binary
    from qurantext.jobs import episode

    if not all(n in ffmpeg_filters(require_binary("ffmpeg")) for n in episode.TONE_MAP_FILTERS):
        pytest.skip("this FFmpeg cannot tone-map")
    graphs: list[str] = []
    real_graph = episode._filter_graph

    def spy(*args, **kwargs):
        inputs, graph = real_graph(*args, **kwargs)
        graphs.append(graph)
        return inputs, graph.replace("tonemap=hable:desat=0", "tonemap=hable:desaturate=0")

    monkeypatch.setattr(episode, "_filter_graph", spy)
    assert preflight._trial_join(tone_map=False) is None, "no HDR clip, no tone-map"
    failed = preflight._trial_join(tone_map=True)
    assert failed is not None and "tonemap" in graphs[-1]


def test_a_trial_join_that_cannot_make_its_folder_fails_politely(monkeypatch) -> None:
    def refused(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(preflight.tempfile, "TemporaryDirectory", refused)
    assert "No space left" in (preflight._trial_join() or "")
    full = frozenset({"apad", "setparams", "sidedata", "zscale", "tonemap"})
    monkeypatch.setattr(preflight, "ffmpeg_filters", lambda path: full)
    monkeypatch.setattr(preflight, "require_binary", lambda name, *a: f"/usr/bin/{name}")
    result = preflight._episode_join(release=True)
    assert result.status == Status.FAIL and "No space left" in result.detail


@pytest.mark.skipif(not _HAS_FFMPEG, reason="needs FFmpeg and ffprobe")
def test_a_trial_join_that_runs_too_long_is_stopped(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "_TRIAL_JOIN_TIMEOUT_S", 0)
    said = preflight._trial_join()
    assert said is not None and "took longer than 0 s" in said


def test_a_failed_trial_join_quotes_ffmpegs_last_line(monkeypatch) -> None:
    full = frozenset({"apad", "setparams", "sidedata", "zscale", "tonemap"})
    monkeypatch.setattr(preflight, "ffmpeg_filters", lambda path: full)
    monkeypatch.setattr(preflight, "require_binary", lambda name, *a: f"/usr/bin/{name}")
    monkeypatch.setattr(
        preflight, "_trial_join", lambda **kwargs: "Parsed_sidedata_1 @ 0x1\nOption not found"
    )
    failed = preflight._episode_join(release=True)
    assert failed.detail.endswith("FFmpeg said: Option not found")


def test_the_trial_join_runs_only_at_the_release_gate(monkeypatch) -> None:
    full = frozenset({"apad", "setparams", "sidedata", "zscale", "tonemap"})
    monkeypatch.setattr(preflight, "ffmpeg_filters", lambda path: full)
    monkeypatch.setattr(preflight, "require_binary", lambda name, *a: f"/usr/bin/{name}")
    calls: list[bool] = []
    monkeypatch.setattr(
        preflight, "_trial_join", lambda **kwargs: calls.append(kwargs["tone_map"]) or "boom"
    )

    assert preflight._episode_join(release=False).status == Status.OK and calls == []
    failed = preflight._episode_join(release=True)
    assert calls == [True], "an FFmpeg that can tone-map joins an HDR clip too"
    assert failed.status == Status.FAIL and "boom" in failed.detail

    monkeypatch.setattr(preflight, "ffmpeg_filters", lambda path: full - {"zscale"})
    preflight._episode_join(release=True)
    assert calls == [True, False]


def test_an_ffmpeg_that_cannot_list_its_filters_is_not_called_incomplete(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "ffmpeg_filters", lambda path: frozenset())
    result = preflight._episode_join(release=True)
    assert result.status == Status.FAIL and "could not list" in result.detail and result.remedy
    assert "no apad" not in result.detail


def test_the_report_names_the_error_log(tmp_path, monkeypatch) -> None:
    """The doctor is what someone runs after a crash; it says where the traceback went."""
    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))

    report = format_report([CheckResult("A", Status.OK, "fine")])

    expected = tmp_path / "data" / "logs" / "qalun.log"
    assert f"  error log in {expected}" in report.splitlines()
    assert not expected.parent.exists(), "naming the log does not make its folder"


def test_the_doctor_checks_what_generated_parts_need(monkeypatch, tmp_path) -> None:
    """The Amiri title font and segno: a build without them renders the lecture and
    fails only when an episode with a generated intro or outro is made."""
    results = {r.name: r for r in run_checks()}
    ok = results["Generated intro and outro"]
    assert ok.status == Status.OK and "Amiri-Regular.ttf" in ok.detail and "segno" in ok.detail

    monkeypatch.setattr(preflight, "TEXT_FONT_BOLD_PATH", tmp_path / "Amiri-Bold.ttf")
    monkeypatch.setitem(sys.modules, "segno", None)  # import segno now raises ImportError
    broken = preflight._title_parts()
    assert broken.status == Status.FAIL and broken.remedy
    assert "Amiri-Bold.ttf" in broken.detail and "segno" in broken.detail


def test_the_interface_font_check_names_the_missing_file(monkeypatch, tmp_path) -> None:
    from qurantext.config import preflight
    from qurantext.config.paths import NOTO_FONT_PATHS

    ok = preflight._interface_font()
    assert ok.status == Status.OK and "NotoSansArabic-Regular.ttf" in ok.detail
    monkeypatch.setattr(preflight, "NOTO_FONT_PATHS", (NOTO_FONT_PATHS[0], tmp_path / "x-Bold.ttf"))
    bad = preflight._interface_font()
    assert bad.status == Status.FAIL and "x-Bold.ttf" in bad.detail and bad.remedy


def test_the_interface_font_is_checked_beside_the_bundled_font() -> None:
    names = [r.name for r in run_checks()]
    assert names.index("Interface font") == names.index("Bundled font") + 1

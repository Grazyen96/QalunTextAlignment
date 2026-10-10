"""Check that this machine can actually render, and say what to do if not.

Everything here failed for someone at some point, in a way that only showed up
deep inside a job:

* **Arabic shaping.** The renderer raises if Pillow reports no raqm support, and
  Pillow's own documentation says raqm needs FriBiDi installed separately. On a
  developer's Linux box it resolves from a system library; on a clean Windows or
  Mac there may be nothing to resolve, and the message the renderer raises then
  is not one a non-developer can act on. This is the single most likely reason a
  packaged build fails to draw anything.
* **FFmpeg.** Located by searching PATH, so an installed app that assumes it is
  there fails at the encode rather than at startup.
* **The store and the font.** Both resolve differently from a checkout than from
  an installed copy.
* **Playback, Qt's Arabic translation and an Arabic interface font.** Each is a
  separate file a frozen build can leave behind while every module still imports,
  so each is exercised here rather than imported. A developer's checkout is only
  told about them; ``run_checks(release=True)`` (``qalun --doctor --release``, the
  build gate) fails on them, because a release without them is broken in Arabic
  or cannot play the recording under review.

Each check answers three questions: is it usable, what exactly is wrong, and
what should the person do. The last one is the point — "libraqm missing" is not
an instruction.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from qurantext.config.fribidi import fribidi_names
from qurantext.config.paths import (
    DEFAULT_FONT_PATH,
    DEFAULT_QURAN_PATH,
    OUTPUT_DIR,
    QURAN_DB_PATH,
    checkout_root,
    user_data_dir,
)
from qurantext.config.settings import describe_secret, env_dir, get_settings
from qurantext.core.video_common import require_binary

if TYPE_CHECKING:
    from qurantext.services.model_store import ModelManifest

__all__ = [
    "CannotMeasureFonts",
    "CheckResult",
    "Status",
    "arabic_ui_families",
    "format_report",
    "prepare_doctor_process",
    "run_checks",
]


class Status:
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: str
    detail: str
    #: What to do about it. Empty when there is nothing to do.
    remedy: str = ""

    @property
    def blocking(self) -> bool:
        return self.status == Status.FAIL


def _ffmpeg_binary(name: str) -> CheckResult:
    # Ask the same way the renderer asks. Checking PATH here while the renderer
    # looks beside the executable first made this report a packaged app broken
    # when it would in fact have rendered — a check that disagrees with the code
    # it is checking is worse than no check.
    try:
        found: str | None = require_binary(name)
    except RuntimeError as error:
        return CheckResult(
            name,
            Status.FAIL,
            str(error).rstrip("."),
            f"Install FFmpeg, which provides {name}. A packaged build should ship "
            "it beside the application rather than rely on PATH.",
        )
    try:
        out = subprocess.run(
            [found, "-version"], check=False, capture_output=True, text=True, timeout=15
        ).stdout.splitlines()
        version = out[0] if out else found
    except (OSError, subprocess.SubprocessError) as error:
        return CheckResult(
            name,
            Status.FAIL,
            f"found but would not run: {error}",
            "Reinstall FFmpeg, or point PATH at a working build.",
        )
    return CheckResult(name, Status.OK, version.strip())


def _arabic_shaping() -> CheckResult:
    """The blocker. Without raqm the renderer refuses to draw at all."""
    try:
        from PIL import __version__ as pillow_version
        from PIL import features
    except ModuleNotFoundError:
        return CheckResult(
            "Arabic shaping",
            Status.FAIL,
            "Pillow is not installed",
            "pip install Pillow",
        )

    if not features.check("raqm"):
        # Pillow reports HarfBuzz and FriBiDi versions *through* raqm, so when
        # raqm is unavailable all three read as missing. Only one of them is
        # ever actually absent: raqm and HarfBuzz are linked into Pillow, and
        # FriBiDi is the one it loads by name at runtime. Naming all three here
        # sent a previous reader looking for two libraries that were present.
        names = ", ".join(fribidi_names())
        if getattr(sys, "frozen", False):
            remedy = (
                "Arabic will not render. This build should carry its own copy of "
                f"FriBiDi ({names}) next to the application and it is missing or "
                "would not load, which is a packaging fault rather than anything "
                "to fix on this machine. Please report it."
            )
        else:
            remedy = (
                "Arabic will not render. Pillow loads FriBiDi at runtime and no "
                "Pillow wheel contains one, so the system must provide it: on "
                "Debian/Ubuntu `apt install libfribidi0`, on macOS `brew install "
                "fribidi`, on Windows put fribidi.dll beside the application. "
                "Reinstalling Pillow does not help."
            )
        return CheckResult(
            "Arabic shaping",
            Status.FAIL,
            f"Pillow {pillow_version} reports no raqm support (FriBiDi did not load)",
            remedy,
        )

    parts = [
        f"{name} {features.version(name)}"
        for name in ("raqm", "harfbuzz", "fribidi")
        if features.check(name)
    ]
    return CheckResult("Arabic shaping", Status.OK, ", ".join(parts))


def _bundled_font() -> CheckResult:
    if DEFAULT_FONT_PATH.is_file():
        size_kb = DEFAULT_FONT_PATH.stat().st_size // 1024
        return CheckResult("Bundled font", Status.OK, f"{DEFAULT_FONT_PATH.name} ({size_kb} KB)")
    return CheckResult(
        "Bundled font",
        Status.FAIL,
        f"missing at {DEFAULT_FONT_PATH}",
        "The font ships inside the package. A build missing it was packaged "
        "without its data files; check that assets/ is included.",
    )


def _bundled_quran() -> CheckResult:
    if DEFAULT_QURAN_PATH.is_file():
        size_kb = DEFAULT_QURAN_PATH.stat().st_size // 1024
        return CheckResult("Quran text", Status.OK, f"{DEFAULT_QURAN_PATH.name} ({size_kb} KB)")
    return CheckResult(
        "Quran text",
        Status.FAIL,
        f"missing at {DEFAULT_QURAN_PATH}",
        "The certified Qalun text ships inside the package. A build missing it "
        "was packaged without its data files; check that assets/ is included.",
    )


def _quran_store() -> CheckResult:
    if QURAN_DB_PATH.is_file():
        size_mb = QURAN_DB_PATH.stat().st_size / 1e6
        return CheckResult("Quran store", Status.OK, f"{QURAN_DB_PATH} ({size_mb:.0f} MB)")
    return CheckResult(
        "Quran store",
        Status.WARN,
        f"not built yet at {QURAN_DB_PATH}",
        "Built automatically the first time it is needed, from the bundled text. "
        "To build it now: `qurantext build-db`.",
    )


def _writable_output() -> CheckResult:
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        probe = OUTPUT_DIR / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        return CheckResult(
            "Output folder",
            Status.FAIL,
            f"{OUTPUT_DIR} is not writable: {error}",
            "Choose a different folder with QURANTEXT_OUTPUT_DIR, or fix the "
            "permissions on this one.",
        )
    return CheckResult("Output folder", Status.OK, str(OUTPUT_DIR))


def _window() -> CheckResult:
    try:
        from PySide6 import QtCore
    except ModuleNotFoundError:
        return CheckResult(
            "Window",
            Status.WARN,
            "Qt is not installed, so only the command line is available",
            "pip install 'qurantext[gui]'",
        )
    return CheckResult("Window", Status.OK, f"Qt {QtCore.qVersion()}")


def _whisperx_check() -> CheckResult:
    """Can we reach the recogniser at all (WhisperX on Replicate)?

    Added because a build passed every check here, rendered video correctly, and
    then died partway through a real job with "No package metadata was found for
    replicate" — the client reads its own version out of its installed metadata
    when imported, and a frozen build ships none unless the spec says so. A gate
    that proves rendering and never touches transcription will keep letting that
    class of fault through, so this imports the thing for real.
    """
    try:
        from importlib.metadata import version

        import replicate  # noqa: F401 - importing it is the point

        # The exact call that failed in the packaged build. replicate/client.py
        # runs it at import time, so asking directly keeps this check pinned to
        # the real failure rather than to a symptom of it.
        client_version = version("replicate")
    except Exception as error:  # noqa: BLE001 - any import failure is the same news
        detail = f"the Replicate client will not import: {error}"
        if getattr(sys, "frozen", False):
            remedy = (
                "Transcription cannot run. This is a packaging fault rather than "
                "anything to fix on this machine. Please report it."
            )
        else:
            remedy = "Reinstall the app's dependencies: pip install -e '.[gui]'"
        return CheckResult("Transcription", Status.FAIL, detail, remedy)

    token = get_settings().replicate_api_token
    if not token:
        return CheckResult(
            "Transcription",
            Status.WARN,
            f"Replicate client {client_version}, but no API token is set",
            "Transcribing audio needs a Replicate API token. Put a file named "
            f".env in {env_dir()} containing a single line: "
            "REPLICATE_API_TOKEN=your-token. Then restart the app — settings are "
            "read once at startup. Everything else works without it.",
        )
    # Described the same way the rejection message describes it, so the two can
    # be held side by side when a token is refused.
    return CheckResult(
        "Transcription",
        Status.OK,
        f"Replicate client {client_version}, token: {describe_secret(token)}",
    )


#: The configured engine's line. The other engine's line has its own name, so a
#: reader can tell which one their jobs use.
_TRANSCRIPTION = "Transcription"
_LOCAL_OPTIONAL = "On this computer (optional)"
_WHISPERX_OPTIONAL = "WhisperX online (optional)"
#: How the configured local line begins; the optional line's name already says it.
_ON_THIS_COMPUTER = "on this computer with "


def _model_credit(manifest: ModelManifest) -> str:
    """The model's attribution, its id read from the manifest the app downloads."""
    return f"NVIDIA FastConformer Arabic ({manifest.model_id.rsplit('/', 1)[-1]}), CC BY 4.0"


def _transcription(release: bool = False) -> list[CheckResult]:
    """Both engines: the configured one as "Transcription", the other as information.

    Only the configured engine's problems block. The other line never fails, with
    one exception: under *release* (the build gate) a Replicate client that will
    not import fails whatever is configured, because the window offers WhisperX
    and a release must carry its client. Someone who transcribes on their own
    computer never needs a Replicate token, so its absence is not a problem to them.
    """
    from qurantext.services.transcription import resolve_engine

    settings = get_settings()
    try:
        configured = resolve_engine(None, settings)
    except ValueError as error:
        # The words a CLI job stops with, so the doctor and the failed job agree.
        unknown = CheckResult(
            _TRANSCRIPTION,
            Status.FAIL,
            str(error),
            "Set QURANTEXT_TRANSCRIBE_ENGINE to local or whisperx, or remove it "
            "(the default is local).",
        )
        return [unknown, _optional_local(), _optional_whisperx(release)]
    if configured == "whisperx":
        return [_whisperx_check(), _optional_local()]
    return [_local_engine_check(), _optional_whisperx(release)]


def _optional_whisperx(release: bool) -> CheckResult:
    """WhisperX when it is not the configured engine: information, bar the build gate."""
    result = _whisperx_check()
    if result.status == Status.FAIL:
        # The client will not import. A person is told; a release build fails.
        remedy = result.remedy.replace(
            "Transcription cannot run.",
            "WhisperX online cannot run; transcription on this computer is unaffected.",
        )
        return CheckResult(_WHISPERX_OPTIONAL, _strict(release), result.detail, remedy)
    if result.status == Status.WARN:
        # Only a missing token warns, and nobody needs one until they choose WhisperX.
        return CheckResult(
            _WHISPERX_OPTIONAL,
            Status.OK,
            f"{result.detail}; not needed unless you choose WhisperX online",
        )
    return CheckResult(_WHISPERX_OPTIONAL, Status.OK, result.detail)


def _optional_local() -> CheckResult:
    """Transcription on this computer when WhisperX is configured: information only."""
    result = _local_engine_check(offer_whisperx=False)
    if result.status == Status.FAIL:
        return CheckResult(_LOCAL_OPTIONAL, Status.WARN, result.detail, result.remedy)
    # Not downloaded yet is nothing to do for someone who uses WhisperX.
    return CheckResult(_LOCAL_OPTIONAL, Status.OK, result.detail.removeprefix(_ON_THIS_COMPUTER))


def _local_engine_check(*, offer_whisperx: bool = True) -> CheckResult:
    """The local engine's runtime and model. *offer_whisperx*: name the other engine
    as a way round a broken runtime (not to someone already using it)."""
    from qurantext.services import engine_local, model_store

    manifest = model_store.LOCAL_MODEL
    credit = _model_credit(manifest)
    problem = engine_local.runtime_problem()
    if problem is not None:
        if _frozen():
            remedy = (
                "Transcription on this computer cannot start. This is a packaging fault "
                "rather than anything to fix on this machine. Please report it."
            )
        else:
            remedy = (
                "Transcription on this computer cannot start. Reinstall the app's "
                "dependencies: `pip install -e .` installs sherpa-onnx."
            )
        if offer_whisperx:
            remedy += " Until then, you can choose WhisperX online instead."
        return CheckResult(
            _TRANSCRIPTION,
            Status.FAIL,
            f"the speech runtime (sherpa-onnx) did not load: {problem}",
            remedy,
        )
    if not model_store.is_installed(manifest):
        return CheckResult(
            _TRANSCRIPTION,
            Status.WARN,
            f"{_ON_THIS_COMPUTER}{credit}; the model downloads once, on first "
            f"use (about {manifest.download_mb} MB), into {model_store.models_dir()}",
            "Nothing to do: the first transcription downloads it. It needs an internet "
            "connection that one time.",
        )
    return CheckResult(
        _TRANSCRIPTION,
        Status.OK,
        f"{_ON_THIS_COMPUTER}{credit}, installed in {model_store.model_dir(manifest)}",
    )


#: How long the playback check waits for Qt to report its test recording loaded.
_PLAYBACK_TIMEOUT_MS = 5000

#: The Qt application the checks made for themselves, held so it outlives them.
_doctor_app: object | None = None

#: The platform plugin a window application uses where there is a real one to use.
_NATIVE_PLATFORMS = {"win32": "windows", "darwin": "cocoa"}

#: Qt multimedia plugin file stems, and the backend each one is.
_MEDIA_BACKENDS = {
    "ffmpeg": "FFmpeg",
    "darwin": "AVFoundation",
    "windows": "Windows Media Foundation",
    "gstreamer": "GStreamer",
}


class CannotMeasureFonts(RuntimeError):
    """This process has no Qt window application and cannot safely make one.

    Qt only lists fonts through a window application (``QGuiApplication``), and
    making one without a platform plugin to back it aborts the whole process
    rather than raising — so the checks say they could not tell instead.
    """


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


#: The loader's words when a library a module links is not on the system.
_MISSING_LIBRARY = re.compile(r"(lib[\w.+-]+?\.so[\w.]*): cannot open shared object file")

#: The Debian/Ubuntu package for the system libraries Qt links that no build may
#: carry (EGL, GL: they belong to the machine's graphics driver) or that a build
#: made on a bare machine left out. Anything else is named for a package search.
_LIBRARY_PACKAGES = {
    "libEGL.so.1": "libegl1",
    "libGL.so.1": "libgl1",
    "libOpenGL.so.0": "libopengl0",
    "libpulse.so.0": "libpulse0",
    "libxkbcommon.so.0": "libxkbcommon0",
    "libxkbcommon-x11.so.0": "libxkbcommon-x11-0",
    "libxcb-cursor.so.0": "libxcb-cursor0",
    "libfontconfig.so.1": "libfontconfig1",
    "libdbus-1.so.3": "libdbus-1-3",
}


def _missing_system_library(error: BaseException) -> str | None:
    """The library an import failed for, when the failure is a missing system library.

    Qt's modules link libraries a Linux system provides (EGL through the graphics
    driver, PulseAudio for sound). When one is absent the import fails with its
    file name, and that name is the whole diagnosis, so the checks report it
    instead of blaming the build or the Python install.
    """
    match = _MISSING_LIBRARY.search(str(error))
    return match.group(1) if match else None


def _system_library_remedy(library: str) -> str:
    package = _LIBRARY_PACKAGES.get(library)
    where = (
        f"on Debian or Ubuntu: sudo apt install {package}"
        if package
        else f"search your distribution's packages for {library}"
    )
    return (
        f"This machine is missing {library}, a system library Qt needs. "
        f"Install the package that provides it ({where}), then run this again."
    )


def _qt_import_failure(name: str, release: bool, what: str, error: ImportError) -> CheckResult:
    """A Qt import that failed: a missing system library named as such, else Qt absent."""
    library = _missing_system_library(error)
    if library is not None:
        return CheckResult(
            name,
            _strict(release),
            f"{what}: the system library {library} is missing",
            _system_library_remedy(library),
        )
    return CheckResult(
        name, _strict(release), f"Qt is not installed ({error})", "pip install 'qurantext[gui]'"
    )


def _strict(release: bool) -> str:
    """What a missing capability is: a note in a checkout, a failure in a release."""
    return Status.FAIL if release else Status.WARN


def _platform_plugin_found(name: str) -> bool:
    """Is Qt's platform plugin *name* on disk where Qt will look for it?

    Asked before making a window application because Qt does not report a
    missing platform plugin: it prints a message and aborts the process, and the
    doctor would die without saying anything a person can act on.
    """
    import PySide6
    from PySide6.QtCore import QCoreApplication

    # Before an application exists Qt's own list lacks the executable's folder,
    # which Qt also searches once one does; and a frozen build keeps the plugins
    # inside its copy of the PySide6 package. Look everywhere Qt will.
    roots = [
        *QCoreApplication.libraryPaths(),
        str(Path(PySide6.__file__).parent / "Qt" / "plugins"),
        str(Path(sys.executable).parent),
    ]
    folders = [Path(root) / "platforms" for root in roots]
    if extra := os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH"):
        folders.append(Path(extra))
    return any(any(folder.glob(f"*q{name}.*")) for folder in folders if folder.is_dir())


def _doctor_platform() -> tuple[bool, str | None]:
    """Can the checks make a window application, and on which platform plugin?

    Returns whether one can be made and the platform to ask for (None for Qt's
    own choice). A platform someone chose with ``QT_QPA_PLATFORM`` is theirs.
    Otherwise Linux (and any other Unix) draws offscreen: its font list comes from
    fontconfig either way, and the build gate runs there with no display, where
    Qt's default (xcb) aborts the process. Windows and macOS use their native
    plugin, which is what their font list comes from.
    """
    if os.environ.get("QT_QPA_PLATFORM"):
        return True, None
    native = _NATIVE_PLATFORMS.get(sys.platform)
    name = native or "offscreen"
    if not _platform_plugin_found(name):
        return False, None
    return True, None if native else "offscreen"


def _qt_application(*, window: bool):
    """This process's Qt application, made for the checks only when there is none.

    The window and the tests already have a ``QApplication``, and that one is
    used. ``--doctor`` has none, so one is made — a ``QApplication`` when a
    platform plugin can back it, so that a window or a test started later in the
    same process can still use it; otherwise a ``QCoreApplication``, which is
    enough to load media but not to list fonts. Returns None when *window* is
    asked for and cannot be had.
    """
    global _doctor_app
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance()
    if app is not None:
        return app
    usable, platform = _doctor_platform()
    if usable:
        from PySide6.QtWidgets import QApplication

        _doctor_app = QApplication(["qalun", *(["-platform", platform] if platform else [])])
    elif window:
        return None
    else:
        _doctor_app = QCoreApplication(["qalun"])
    return _doctor_app


def _import_multimedia():
    from PySide6 import QtMultimedia  # optional part of Qt (PySide6-Addons)

    return QtMultimedia


def _load_test_recording() -> tuple[bool, str]:
    """Load half a second of silence through ``QMediaPlayer``: (loaded, what happened).

    Waits at most ``_PLAYBACK_TIMEOUT_MS`` for Qt to settle on loaded or invalid.
    No audio output is attached: loading needs none, and CI machines have none.
    """
    multimedia = _import_multimedia()
    from PySide6.QtCore import QEventLoop, QTimer, QUrl

    _qt_application(window=False)
    statuses = multimedia.QMediaPlayer.MediaStatus
    settled = (statuses.LoadedMedia, statuses.InvalidMedia)
    # ignore_cleanup_errors: on Windows a player that has not quite let go of the
    # file would otherwise turn a passing check into a crash.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        path = Path(folder) / "preflight.wav"
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            out.writeframes(bytes(2 * 8000))

        player = multimedia.QMediaPlayer()
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)

        def on_status(status) -> None:
            if status in settled:
                loop.quit()

        player.mediaStatusChanged.connect(on_status)
        player.setSource(QUrl.fromLocalFile(str(path)))
        if player.mediaStatus() not in settled:
            timer.start(_PLAYBACK_TIMEOUT_MS)
            loop.exec()
            timer.stop()
        status, duration_ms = player.mediaStatus(), player.duration()
        error = player.errorString()
        player.mediaStatusChanged.disconnect(on_status)
        player.setSource(QUrl())  # let go of the file before its folder goes
        del player

    if status == statuses.LoadedMedia and duration_ms > 0:
        return True, f"{duration_ms / 1000:.2f} s"
    if status == statuses.LoadedMedia:
        return False, "LoadedMedia with no duration"
    if status not in settled:
        return False, f"still {status.name} after {_PLAYBACK_TIMEOUT_MS // 1000} s"
    return False, f"{status.name}: {error}" if error else status.name


def _media_plugins() -> list[str]:
    """The multimedia backends whose plugin files are where Qt looks, by name."""
    from PySide6.QtCore import QCoreApplication

    files = [
        plugin.name.lower()
        for path in QCoreApplication.libraryPaths()
        if (Path(path) / "multimedia").is_dir()
        for plugin in (Path(path) / "multimedia").iterdir()
    ]
    return [label for stem, label in _MEDIA_BACKENDS.items() if any(stem in f for f in files)]


def _loaded_library_names() -> set[str]:
    """The file names of the shared libraries this process has loaded, lower-cased.

    Asked of the system rather than of Qt, which has no public way to say which
    multimedia backend it chose.
    """
    import ctypes

    if sys.platform == "win32":
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.argtypes = []
        psapi.EnumProcessModules.restype = wintypes.BOOL
        psapi.EnumProcessModules.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.HMODULE),
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        psapi.GetModuleFileNameExW.restype = wintypes.DWORD
        psapi.GetModuleFileNameExW.argtypes = [
            wintypes.HANDLE,
            wintypes.HMODULE,
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        process = kernel32.GetCurrentProcess()
        modules = (wintypes.HMODULE * 4096)()
        needed = wintypes.DWORD()
        if not psapi.EnumProcessModules(
            process, modules, ctypes.sizeof(modules), ctypes.byref(needed)
        ):
            raise ctypes.WinError()
        count = min(needed.value // ctypes.sizeof(wintypes.HMODULE), len(modules))
        buffer = ctypes.create_unicode_buffer(32768)
        found = set()
        for module in modules[:count]:
            if psapi.GetModuleFileNameExW(process, module, buffer, len(buffer)):
                found.add(Path(buffer.value).name.lower())
        return found
    if sys.platform == "darwin":
        system = ctypes.CDLL(None)
        system._dyld_image_count.restype = ctypes.c_uint32
        system._dyld_get_image_name.restype = ctypes.c_char_p
        system._dyld_get_image_name.argtypes = [ctypes.c_uint32]
        return {
            Path(os.fsdecode(image)).name.lower()
            for index in range(system._dyld_image_count())
            if (image := system._dyld_get_image_name(index))
        }
    with open("/proc/self/maps", encoding="utf-8", errors="replace") as maps:
        return {Path(line.split()[-1]).name.lower() for line in maps if "/" in line}


def _media_backends_loaded() -> list[str] | None:
    """The multimedia backends whose plugin this process has loaded; None if it cannot tell.

    What is on disk, or asked for in ``QT_MEDIA_BACKEND``, is not proof of what
    plays: when the backend asked for will not load, Qt 6.11 loads "an
    alternative backend" and the test recording plays through that. A Windows
    build that lost its FFmpeg plugin would pass on Windows Media Foundation,
    which cannot decode Opus. The library Qt actually loaded is the proof.
    """
    try:
        names = _loaded_library_names()
    except Exception:  # noqa: BLE001 - any failure to ask means the same: cannot tell
        return None
    plugins = [name for name in names if "mediaplugin" in name]
    return [label for stem, label in _MEDIA_BACKENDS.items() if any(stem in n for n in plugins)]


def _playback(release: bool) -> CheckResult:
    """Can this machine play the recording under review?

    Loads a half-second WAV written on the spot through ``QMediaPlayer`` and waits
    (bounded, 5 s) for Qt to report it loaded with a duration. Importing the module
    is not enough: the FFmpeg multimedia plugin is a separate file a frozen build can
    leave behind, and without it the module imports and every file fails to load.
    Needs no sound device — CI machines have none — so audio outputs are only noted.
    """
    name = "Playback"
    if _frozen():
        remedy = (
            "This is a packaging fault: the Qt multimedia plugin was not bundled. Please report it."
        )
    else:
        remedy = "pip install -e '.[gui]' (PySide6-Addons carries Qt Multimedia)"
    without = "the review window opens with playback disabled"
    try:
        loaded, what = _load_test_recording()
    except ImportError as error:
        library = _missing_system_library(error)
        if library is not None:
            return CheckResult(
                name,
                _strict(release),
                f"Qt Multimedia will not import: the system library {library} is missing; "
                f"{without}",
                _system_library_remedy(library),
            )
        return CheckResult(
            name, _strict(release), f"Qt Multimedia will not import ({error}); {without}", remedy
        )
    except Exception as error:  # noqa: BLE001 - any failure to start is the same news
        return CheckResult(
            name, _strict(release), f"Qt Multimedia would not start ({error}); {without}", remedy
        )
    if not loaded:
        return CheckResult(
            name,
            _strict(release),
            f"a short test recording would not load ({what}); {without}",
            remedy,
        )
    forced = os.environ.get("QT_MEDIA_BACKEND", "")
    in_use = _media_backends_loaded()
    on_disk = f"plugins on disk: {', '.join(_media_plugins()) or 'none named'}"
    if forced:
        wanted = _MEDIA_BACKENDS.get(forced.lower(), forced)
        # Only it: a second backend loaded means Qt tried it and fell back.
        if in_use != [wanted]:
            got = ", ".join(in_use) if in_use else "cannot tell which"
            return CheckResult(
                name,
                _strict(release),
                f"the test recording loaded, but not through the {wanted} backend "
                f"QT_MEDIA_BACKEND asks for (loaded: {got}; {on_disk})",
                remedy,
            )
    if in_use:
        through = f"through the {' / '.join(in_use)} backend"
        through += ", as QT_MEDIA_BACKEND asks" if forced else ""
    else:
        through = "backend in use unknown"
    multimedia = _import_multimedia()
    formats = len(
        multimedia.QMediaFormat().supportedFileFormats(
            multimedia.QMediaFormat.ConversionMode.Decode
        )
    )
    outputs = len(multimedia.QMediaDevices.audioOutputs())
    heard = f"{outputs} audio output(s)" if outputs else "no audio output (loading needs none)"
    return CheckResult(
        name,
        Status.OK,
        f"loaded a {what} test recording {through}; {on_disk}; "
        f"{formats} decodable format(s), {heard}",
    )


def _qt_translations_folder() -> str:
    from PySide6.QtCore import QLibraryInfo

    return QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)


def _qt_translation(release: bool) -> CheckResult:
    """Will Qt's own buttons and dialogs be in Arabic in the Arabic window?

    The window's words are ours, but OK/Cancel, the file dialog and the
    right-click menus are Qt's, translated by ``qtbase_ar.qm`` in Qt's
    translations folder — a data file a frozen build can leave out while
    everything else works. Loaded here exactly as the window loads it.
    """
    name = "Window translation"
    try:
        from PySide6.QtCore import QTranslator

        folder = _qt_translations_folder()
    except ImportError as error:
        return _qt_import_failure(name, release, "Qt will not import", error)
    if QTranslator().load("qtbase_ar", folder):
        return CheckResult(name, Status.OK, f"qtbase_ar in {folder}")
    if _frozen():
        remedy = "This is a packaging fault: Qt's translations were not bundled. Please report it."
    else:
        remedy = "Reinstall PySide6, whose wheel carries Qt's translations: pip install -e '.[gui]'"
    return CheckResult(
        name,
        _strict(release),
        f"no qtbase_ar in {folder}: Qt's own buttons will stay English in the Arabic window",
        remedy,
    )


def _quran_font_family() -> str | None:
    """The family name of the bundled Quran font, read from the file without installing it."""
    from PySide6.QtGui import QRawFont

    if not DEFAULT_FONT_PATH.is_file():
        return None
    raw = QRawFont(str(DEFAULT_FONT_PATH), 12)
    return raw.familyName() if raw.isValid() else None


def arabic_ui_families() -> list[str]:
    """The font families on this machine that can draw Arabic interface text.

    Qt's list of families supporting the Arabic writing system, without the
    bundled Quran font: it has Arabic letters but no Latin ones, so it can stand
    in for Arabic but never be the interface font, and it is in the list whenever
    the window has registered it (or someone installed it). Uses the running Qt
    application, or makes one for the doctor (see ``_qt_application``).

    Raises ``CannotMeasureFonts`` when this process has no window application and
    cannot make one, and ``ImportError`` when Qt is not installed.
    """
    from PySide6.QtGui import QFontDatabase, QGuiApplication

    app = _qt_application(window=True)
    if app is None:
        raise CannotMeasureFonts(
            "no Qt platform plugin was found, so no window application can start to list fonts"
        )
    if not isinstance(app, QGuiApplication):
        raise CannotMeasureFonts("this process runs Qt without a window, which cannot list fonts")
    quran = _quran_font_family()
    return [
        family
        for family in QFontDatabase.families(QFontDatabase.WritingSystem.Arabic)
        if family != quran and not QFontDatabase.isPrivateFamily(family)
    ]


def _arabic_ui_font(release: bool) -> CheckResult:
    """Can the Arabic window draw its words in a font meant for an interface?

    A machine with no Arabic font shows the Arabic window as empty boxes; Qalun
    then falls back to its bundled Quran font, which is legible but not meant for
    interface text, so a release is checked on a machine that has a real one.
    """
    name = "Arabic interface font"
    try:
        families = arabic_ui_families()
    except ImportError as error:
        return _qt_import_failure(name, release, "Qt's drawing library will not load", error)
    except CannotMeasureFonts as error:
        if _frozen():
            remedy = (
                "This is a packaging fault: Qt's platform plugin was not bundled. Please report it."
            )
        else:
            remedy = "Run the check where Qt can start, or set QT_QPA_PLATFORM=offscreen."
        return CheckResult(name, _strict(release), f"cannot tell: {error}", remedy)
    if families:
        shown = ", ".join(families[:2])
        more = f" and {len(families) - 2} more" if len(families) > 2 else ""
        return CheckResult(name, Status.OK, f"{shown}{more}")
    return CheckResult(
        name,
        _strict(release),
        "no installed font can draw Arabic interface text",
        "Install an Arabic font (for example Noto Sans Arabic); Qalun falls back to its "
        "bundled Quran font for Arabic letters, which is legible but not meant for "
        "interface text.",
    )


#: Checks whose failure leaves rendering working: the job, the review window or
#: the Arabic interface is what suffers, so the report must not say "Cannot render".
_NOT_RENDERING = frozenset(
    {
        _TRANSCRIPTION,
        _LOCAL_OPTIONAL,
        _WHISPERX_OPTIONAL,
        "Window",
        "Playback",
        "Window translation",
        "Arabic interface font",
    }
)

#: Qt logging rules for the doctor: the FFmpeg plugin prints the test recording's
#: stream details to stderr, noise in the report a person sends.
_DOCTOR_LOGGING_RULES = "qt.multimedia.ffmpeg*=false"


def prepare_doctor_process(*, release: bool = False) -> None:
    """Set, in this process's environment, what Qt reads once when it starts.

    Called by ``--doctor`` before the checks, so before anything imports Qt; a
    process that already runs Qt is not changed by it. *release* asks Qt for the
    FFmpeg multimedia backend (unless someone already chose one): Windows and
    macOS ship a native backend beside it, and the gate must prove FFmpeg, not
    whichever backend loaded. Logging rules already set are kept.
    """
    if release:
        os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
    rules = os.environ.get("QT_LOGGING_RULES", "")
    if _DOCTOR_LOGGING_RULES not in rules.split(";"):
        rules = f"{rules};{_DOCTOR_LOGGING_RULES}" if rules else _DOCTOR_LOGGING_RULES
    os.environ["QT_LOGGING_RULES"] = rules


def run_checks(*, release: bool = False) -> list[CheckResult]:
    """Every check, in the order a person would want to read them.

    *release* makes playback, Qt's Arabic translation, an Arabic interface
    font and the Replicate client blocking: a developer's checkout is only told
    about them, a release build (``qalun --doctor --release``, the CI gate) must
    have them.
    """
    return [
        _arabic_shaping(),
        _ffmpeg_binary("ffmpeg"),
        _ffmpeg_binary("ffprobe"),
        *_transcription(release),
        _bundled_font(),
        _bundled_quran(),
        _quran_store(),
        _writable_output(),
        _window(),
        _playback(release),
        _qt_translation(release),
        _arabic_ui_font(release),
    ]


def _joined(names: list[str]) -> str:
    """``A``, ``A and B``, ``A, B and C``."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def format_report(results: list[CheckResult], *, release: bool = False) -> str:
    """The checks as text, with the remedies for anything that needs one.

    The closing line says what the failures mean for whoever reads it. A render
    check failing means nothing renders. Anything else failing leaves rendering
    working: under *release* (the build gate) that build is not fit to ship; in a
    person's own ``--doctor`` it names what cannot run yet, since they are not
    shipping anything and "not ready for release" would only puzzle them.
    """
    marks = {Status.OK: "ok  ", Status.WARN: "note", Status.FAIL: "FAIL"}
    lines = [
        f"Qalun on {sys.platform}",
        f"  running from {'a checkout' if checkout_root() else 'an installed copy'}",
        f"  app data in {user_data_dir()}",
        "",
    ]
    width = max(len(r.name) for r in results)
    for result in results:
        lines.append(f"  [{marks[result.status]}] {result.name:<{width}}  {result.detail}")
    remedies = [r for r in results if r.remedy and r.status != Status.OK]
    if remedies:
        lines.append("")
        for result in remedies:
            lines.append(f"  {result.name}: {result.remedy}")
    blocking = [r for r in results if r.blocking]
    lines.append("")
    if not blocking:
        lines.append("Ready to render.")
    elif any(r.name not in _NOT_RENDERING for r in blocking):
        lines.append(f"Cannot render yet: {len(blocking)} problem(s) above must be fixed.")
    elif release:
        lines.append(f"Not ready for release: {len(blocking)} problem(s) above.")
    else:
        names = _joined([r.name for r in blocking])
        lines.append(f"Rendering works; {names} cannot run yet: see above.")
    return "\n".join(lines)

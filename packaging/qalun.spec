# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Qalun desktop app.

Build from the repository root:

    pip install -e '.[gui]' pyinstaller
    pyinstaller packaging/qalun.spec --noconfirm

What this has to get right, beyond the obvious:

* **Package data.** The Qalun font lives inside the package and a frozen build
  does not copy it on its own. Without it the renderer cannot find its default
  font, which is the failure the wheel had before it declared package data.
* **FriBiDi.** Pillow loads it by name at runtime, and no Pillow wheel on any
  platform contains one — opening the Windows, macOS and Linux wheels shows
  HarfBuzz vendored and FriBiDi absent, because FriBiDi is LGPL and loading it
  at runtime is what keeps the wheel redistributable. Without it Arabic does
  not shape and the renderer refuses to draw, which was exactly the macOS build
  failure. The build copies one in beside the executable, and the app loads it
  itself at startup rather than trusting three different loaders to find it;
  see qurantext.config.fribidi. `--doctor` reports whether it resolved.
* **Package metadata.** The Replicate client reads its own version out of its
  installed metadata the moment it is imported, and a frozen build ships no
  .dist-info unless told to. Without this the app renders perfectly and then
  fails at transcription with "No package metadata was found for replicate" —
  a failure that only appears once a job is already running.
* **The local transcription engine.** sherpa-onnx's wheel carries native
  libraries (its own and ONNX Runtime) that the import graph cannot see, and
  the licences that have to travel with them. The speech model is not bundled:
  it downloads on first use, over HTTPS, trusting certifi's bundle as well as
  the system's, so certifi's cacert.pem travels too.
* **FFmpeg.** Not bundled here, because the binary is large and its licensing
  depends on the build you choose. Ship one beside the executable and put that
  directory on PATH, or accept the system install. `doctor` reports which.
"""

import sys
from importlib.metadata import distribution
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

ROOT = Path(SPECPATH).parent
ICON_DIR = ROOT / "src" / "qurantext" / "assets" / "icon"
# PyInstaller takes an .ico on Windows (assets/icon/qalun.ico) and an .icns on
# macOS (assets/icon/qalun.icns); Linux has no executable icon, so none is
# given there (a stray one only warns).
EXE_ICON = str(ICON_DIR / "qalun.ico") if sys.platform == "win32" else None

datas = [
    # The bundled font, kept at the path qurantext.config.paths expects.
    (str(ROOT / "src" / "qurantext" / "assets"), "qurantext/assets"),
    # Credits the speech model (CC BY 4.0) and the engine. Lands at the top of
    # the bundle's data folder (_internal/, or Contents/Resources on macOS).
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
    # Qalun's own licence, GPL-3.0-only, the full text, in the same place.
    (str(ROOT / "LICENSE"), "."),
    # segno (BSD 3-Clause) is pure Python, so its code goes into the archive and
    # its metadata, with the licence, stays behind. The repository keeps it.
    (str(ROOT / "packaging" / "licenses" / "segno-LICENSE.txt"), "."),
]

# The local transcription engine. Its wheel carries native libraries
# (sherpa-onnx's own and ONNX Runtime) that the import graph cannot see.
sherpa_binaries = collect_dynamic_libs("sherpa_onnx")
sherpa_hidden = collect_submodules("sherpa_onnx")

# Their licences go beside them. sherpa-onnx (Apache 2.0) ships its own in the
# wheel's metadata, taken from there so it always matches the version built.
# ONNX Runtime (MIT) is inside sherpa_onnx/lib but neither its licence nor the
# notices for the code inside it (ThirdPartyNotices.txt) are in the wheel, so the
# repository keeps both; see packaging/licenses/README.md.
_sherpa_licence = next(
    (f for f in distribution("sherpa_onnx").files or () if f.name in ("LICENSE", "LICENSE.txt")),
    None,
)
if _sherpa_licence is None:
    raise SystemExit("qalun.spec: the installed sherpa-onnx carries no LICENSE to ship")
datas += [
    (str(_sherpa_licence.locate()), "sherpa_onnx"),
    (str(ROOT / "packaging" / "licenses" / "onnxruntime-LICENSE"), "sherpa_onnx/lib"),
    (str(ROOT / "packaging" / "licenses" / "onnxruntime-ThirdPartyNotices.txt"), "sherpa_onnx/lib"),
]
# The Linux wheel also vendors ALSA's libasound (LGPL-2.1) into sherpa_onnx.libs/,
# linked dynamically. Its licence goes beside it; the other wheels carry none.
if any(f.name.startswith("libasound") for f in distribution("sherpa_onnx").files or ()):
    datas.append(
        (str(ROOT / "packaging" / "licenses" / "libasound-LGPL-2.1.txt"), "sherpa_onnx.libs")
    )

# The model download trusts certifi's bundle as well as the system's: a frozen
# app's OpenSSL looks where the build machine kept its certificates, which a
# Mac or another Linux does not have. certifi.where() must find cacert.pem.
datas += collect_data_files("certifi")
# certifi is MPL-2.0, and its licence travels in its metadata. replicate's
# recursive copy below brings it too, but naming it here keeps it if replicate goes.
datas += copy_metadata("certifi")
# idna (BSD 3-Clause) encodes the outro link's international host names. Its
# licence travels in its metadata, which replicate's recursive copy also brings;
# named here so it stays if replicate goes.
datas += copy_metadata("idna")

# replicate/__about__.py runs `version("replicate")` at import time, so the
# package's metadata has to travel with it or the import raises. recursive=True
# because its dependencies do the same thing, and finding out which ones one
# traceback at a time is not a use of anyone's afternoon.
datas += copy_metadata("replicate", recursive=True)

# Pillow's own shared libraries are collected by PyInstaller's Pillow hook into
# pillow.libs/ with the right search path. Do NOT add collect_dynamic_libs("PIL")
# here: that copies them to the bundle root as well, where Pillow's libharfbuzz
# shadows the one Qt ships, and the app hangs on startup before reaching a single
# line of its own code. Note that no amount of collecting produces FriBiDi — it
# is not in the wheel to collect. The build supplies that separately.
binaries = [*sherpa_binaries]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "qurantext.gui.app", "qurantext.gui.main_window",
        # The review window's player. It is imported inside a function, behind a
        # try, so that a machine without it only loses playback; named here so a
        # release never depends on the analysis following that lazy import. Its
        # PyInstaller hook brings the rest: plugins/multimedia (the FFmpeg media
        # plugin), the libav*/libsw* it links from PySide6's Qt/lib, and
        # translations/qtmultimedia_*.qm. QtCore's hook brings qtbase_*.qm.
        "PySide6.QtMultimedia",
        # The local engine is imported lazily, inside the engine's functions.
        *sherpa_hidden,
    ],
    excludes=[
        # Nothing here is used, and each drags in a lot.
        "tkinter", "matplotlib", "scipy", "pandas", "pytest",
        "PySide6.QtWebEngineCore", "PySide6.QtQuick3D", "PySide6.Qt3DCore",
        "PySide6.QtCharts", "PySide6.QtDataVisualization",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="qalun",
    console=False,
    disable_windowed_traceback=False,
    icon=EXE_ICON,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="qalun",
)

# macOS wants an app bundle; the others take the COLLECT directory as-is.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Qalun.app",
        icon=str(ICON_DIR / "qalun.icns"),
        bundle_identifier="de.project-bay.qalun",
        info_plist={
            "CFBundleName": "Qalun",
            "CFBundleDisplayName": "Qalun",
            "NSHighResolutionCapable": True,
            # Needed for the file dialog to reach the user's own media folders.
            "NSDocumentsFolderUsageDescription": "Qalun opens the audio you choose.",
            "NSDownloadsFolderUsageDescription": "Qalun opens the audio you choose.",
        },
    )

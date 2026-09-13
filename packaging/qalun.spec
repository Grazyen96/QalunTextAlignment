# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Qalun desktop app.

Build from the repository root:

    pip install -e '.[gui]' pyinstaller
    pyinstaller packaging/qalun.spec --noconfirm

What this has to get right, beyond the obvious:

* **Package data.** The Qalun font lives inside the package and a frozen build
  does not copy it on its own. Without it the renderer cannot find its default
  font, which is the failure the wheel had before it declared package data.
* **FriBiDi.** Pillow's raqm support loads it at runtime and it is the single
  most likely reason a packaged build draws nothing. On Linux and macOS the
  shared library is collected below when present; on Windows put fribidi.dll
  next to the executable. `qurantext doctor` reports whether it resolved.
* **FFmpeg.** Not bundled here, because the binary is large and its licensing
  depends on the build you choose. Ship one beside the executable and put that
  directory on PATH, or accept the system install. `doctor` reports which.
"""

from pathlib import Path

ROOT = Path(SPECPATH).parent

datas = [
    # The bundled font, kept at the path qurantext.config.paths expects.
    (str(ROOT / "src" / "qurantext" / "assets"), "qurantext/assets"),
]

# Pillow's own shared libraries are collected by PyInstaller's Pillow hook into
# pillow.libs/ with the right search path, raqm and FriBiDi included. Do NOT add
# collect_dynamic_libs("PIL") here: that copies them to the bundle root as well,
# where Pillow's libharfbuzz shadows the one Qt ships, and the app hangs on
# startup before reaching a single line of its own code.
binaries = []

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=["qurantext.gui.app", "qurantext.gui.main_window"],
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
import sys  # noqa: E402

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Qalun.app",
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

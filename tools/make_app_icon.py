"""Render the app icon's PNG sizes, the Windows .ico and the macOS .icns from the SVG master.

Run after changing ``qalun.svg``; the outputs are committed so a build needs
no step.

    QT_QPA_PLATFORM=offscreen venv/bin/python tools/make_app_icon.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ICON_DIR = Path(__file__).resolve().parents[1] / "src" / "qurantext" / "assets" / "icon"
MASTER = ICON_DIR / "qalun.svg"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = tuple(size for size in SIZES if size <= 256)


def _render_pngs() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    renderer = QSvgRenderer(str(MASTER))
    for size in SIZES:
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        if not image.save(str(ICON_DIR / f"qalun-{size}.png"), "PNG"):
            raise SystemExit(f"could not write qalun-{size}.png")
    del app


def _pack() -> None:
    from PIL import Image

    with Image.open(ICON_DIR / "qalun-1024.png") as master:
        master = master.convert("RGBA")
        master.save(ICON_DIR / "qalun.ico", sizes=[(s, s) for s in ICO_SIZES])
        master.save(ICON_DIR / "qalun.icns")


def main() -> int:
    _render_pngs()
    _pack()
    print(f"icon written in {ICON_DIR}: {len(SIZES)} PNGs, qalun.ico, qalun.icns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

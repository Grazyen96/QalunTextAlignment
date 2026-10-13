"""The app icon: a master, every generated size, and set on the application."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "src" / "qurantext" / "assets" / "icon"
sys.path.insert(0, str(ROOT / "tools"))


def test_the_master_and_every_size_are_committed() -> None:
    from make_app_icon import SIZES

    assert (ICON_DIR / "qalun.svg").is_file()
    for size in SIZES:
        assert (ICON_DIR / f"qalun-{size}.png").is_file(), size
    assert (ICON_DIR / "qalun.ico").is_file()
    assert (ICON_DIR / "qalun.icns").is_file()


def test_the_windows_and_mac_icons_hold_the_sizes_they_need() -> None:
    from PIL import Image

    with Image.open(ICON_DIR / "qalun.ico") as ico:
        assert (256, 256) in ico.info["sizes"]
        assert (16, 16) in ico.info["sizes"]
    with Image.open(ICON_DIR / "qalun.icns") as icns:
        assert icns.size[0] >= 512
    with Image.open(ICON_DIR / "qalun-1024.png") as png:
        assert png.size == (1024, 1024)
        assert png.mode == "RGBA"


def test_the_application_carries_the_icon(qt_app) -> None:
    pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")
    from qurantext.gui.app import APP_ICON_PNG, set_app_icon

    set_app_icon(qt_app)
    assert not qt_app.windowIcon().isNull()
    assert APP_ICON_PNG.is_file()

"""The phase-review screenshots: every screen, both themes, both languages, into a folder."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


def test_the_tool_writes_one_image_per_screen_theme_and_language(
    qt_app, tmp_path, no_default_job_dirs
) -> None:
    from screenshots import shoot

    written = shoot(tmp_path, themes=("light",), languages=("en",))
    names = {path.name for path in written}
    assert {
        "home-en-light.png",
        "home-running-en-light.png",
        "review-rendering-en-light.png",
        "review-recitation-en-light.png",
        "export-en-light.png",
        "ayah-picker-en-light.png",
        "episode-en-light.png",
        "home-empty-en-light.png",
        "settings-general-en-light.png",
        "settings-about-en-light.png",
    } <= names
    for path in written:
        assert path.stat().st_size > 1000, path.name

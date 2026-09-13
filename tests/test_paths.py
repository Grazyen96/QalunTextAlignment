"""Where files live, on a checkout and on an installed machine.

Every path used to hang off the repository root, computed by walking three
directories up from this package. Installed as a wheel that lands inside the
Python installation, so the bundled font, the Quran store and the basmala audio
all pointed at places that do not exist. These pin the two modes.
"""

from __future__ import annotations

import sys

import pytest

from qurantext.config import paths


def test_the_bundled_font_travels_with_the_package() -> None:
    """The renderer's default font must be readable wherever the code is installed."""
    assert paths.DEFAULT_FONT_PATH.exists(), paths.DEFAULT_FONT_PATH
    # Inside the package, not beside a source checkout that will not be shipped.
    assert paths.DEFAULT_FONT_PATH.is_relative_to(paths.bundled_asset(""))
    package_dir = paths.bundled_asset("").parent
    assert package_dir.name == "qurantext"


def test_the_default_font_setting_points_at_the_bundled_file() -> None:
    from qurantext.config.settings import DEFAULT_VIDEO_FONT_FILE

    assert DEFAULT_VIDEO_FONT_FILE == str(paths.DEFAULT_FONT_PATH)


def test_running_from_this_checkout_is_detected() -> None:
    """The test suite runs from source, so the repository must be found."""
    root = paths.checkout_root()
    assert root is not None
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "qurantext").is_dir()


def test_a_checkout_needs_its_marker_files_not_just_its_depth(tmp_path, monkeypatch) -> None:
    """An installed package three levels inside something is not a checkout."""
    fake = tmp_path / "lib" / "python3.12" / "site-packages" / "qurantext" / "config"
    fake.mkdir(parents=True)
    monkeypatch.setattr(paths, "__file__", str(fake / "paths.py"))
    paths.checkout_root.cache_clear()
    try:
        assert paths.checkout_root() is None
    finally:
        paths.checkout_root.cache_clear()


@pytest.mark.parametrize(
    ("platform", "env", "expected_tail"),
    [
        ("win32", {"LOCALAPPDATA": "/fake/AppData/Local"}, ("AppData", "Local", "Qalun")),
        ("darwin", {}, ("Library", "Application Support", "Qalun")),
        ("linux", {"XDG_DATA_HOME": "/fake/xdg"}, ("xdg", "qalun")),
    ],
)
def test_user_data_dir_follows_each_platform(monkeypatch, platform, env, expected_tail) -> None:
    monkeypatch.delenv("QURANTEXT_DATA_DIR", raising=False)
    for key in ("LOCALAPPDATA", "APPDATA", "XDG_DATA_HOME"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "platform", platform)

    parts = paths.user_data_dir().parts
    assert parts[-len(expected_tail) :] == expected_tail


def test_linux_falls_back_to_the_xdg_default(monkeypatch) -> None:
    monkeypatch.delenv("QURANTEXT_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert paths.user_data_dir().parts[-3:] == (".local", "share", "qalun")


def test_the_data_dir_override_wins_on_every_platform(monkeypatch, tmp_path) -> None:
    """A desktop app sets this once the user picks a working folder."""
    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "chosen"))
    for platform in ("win32", "darwin", "linux"):
        monkeypatch.setattr(sys, "platform", platform)
        assert paths.user_data_dir() == tmp_path / "chosen"

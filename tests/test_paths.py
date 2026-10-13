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


def test_the_quran_text_ships_with_the_package() -> None:
    """The app carries its own certified text.

    Not only for convenience: the parser expects one file's exact conventions,
    and the ayah numbering has to be the Madani counting the rest of the data
    assumes. "Bring your own text" is a way to get subtly wrong output rather
    than an obvious failure.
    """
    assert paths.DEFAULT_QURAN_PATH.exists(), paths.DEFAULT_QURAN_PATH
    assert paths.DEFAULT_QURAN_PATH.is_relative_to(paths.bundled_asset(""))
    assert paths.DEFAULT_QURAN_PATH.stat().st_size > 1_000_000


def test_the_bundled_text_parses_to_the_expected_shape() -> None:
    from qurantext.core.quran_parser import parse_ayat

    ayat = parse_ayat(paths.DEFAULT_QURAN_PATH)
    assert len({a["surah_num"] for a in ayat}) == 114
    assert len(ayat) == 6214, "Madani counting, which the store and index assume"


def test_resolve_quran_path_prefers_what_it_is_given(tmp_path) -> None:
    mine = tmp_path / "mine.txt"
    mine.write_text("سُورَةُ الفَاتِحَةِ\n", encoding="utf-8")
    assert paths.resolve_quran_path(mine) == mine.resolve()
    assert paths.resolve_quran_path(None) == paths.DEFAULT_QURAN_PATH


def test_a_path_that_does_not_exist_fails_clearly(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="Quran text file not found"):
        paths.resolve_quran_path(tmp_path / "absent.txt")


def test_a_saved_path_to_the_retired_ver05_text_reads_as_the_bundled_one(tmp_path) -> None:
    """Ver05 was bundled before v10 and an older settings file may still name it.

    The old file is gone after the update, so that path is the bundled text now;
    a Ver05 copy of the person's own, outside the package, is left alone.
    """
    old_bundled = tmp_path / "_internal" / "qurantext" / "assets" / "quran"
    gone = old_bundled / "UthmanicQaloon1-Ver05.txt"
    assert paths.redirect_retired_quran(gone) == paths.DEFAULT_QURAN_PATH
    assert paths.resolve_quran_path(gone) == paths.DEFAULT_QURAN_PATH

    old_bundled.mkdir(parents=True)
    gone.write_text("سُورَةُ الفَاتِحَةِ\n", encoding="utf-8")
    assert paths.redirect_retired_quran(gone) == gone, "still there, so still the choice"

    own = tmp_path / "input" / "quran" / "UthmanicQaloon1-Ver05.txt"
    assert paths.redirect_retired_quran(own) == own
    with pytest.raises(FileNotFoundError, match="Quran text file not found"):
        paths.resolve_quran_path(own)


def test_the_notices_file_is_found_in_a_checkout_and_in_a_bundle(monkeypatch, tmp_path) -> None:
    import sys

    from qurantext.config.paths import notices_path

    assert notices_path().name == "THIRD_PARTY_NOTICES.md"
    assert notices_path().is_file()  # the checkout's own copy
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert notices_path() == tmp_path / "THIRD_PARTY_NOTICES.md"

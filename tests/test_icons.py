"""Bundled icons: every name draws, takes the theme's colour, mirrors in Arabic, and is re-tinted on a switch."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QPushButton, QWidget  # noqa: E402

from qurantext.gui import icons, theme  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from fetch_icons import ICON_NAMES  # noqa: E402


@pytest.fixture(autouse=True)
def _light(qt_app):
    """Each test starts in Light with nothing cached; conftest puts the theme back after."""
    theme.apply_theme(qt_app, "light")
    icons.clear_cache()


def _colours(pixmap) -> set[str]:
    image = pixmap.toImage()
    found = set()
    for y in range(image.height()):
        for x in range(image.width()):
            colour = image.pixelColor(x, y)
            if colour.alpha() > 200:
                found.add(colour.name().upper())
    return found


def test_the_module_names_exactly_the_bundled_set() -> None:
    assert icons.NAMES == frozenset(ICON_NAMES)


@pytest.mark.parametrize("name", sorted(ICON_NAMES))
def test_every_icon_draws_at_every_size(qt_app, name) -> None:
    drawn = icons.icon(name)
    for size in (16, 20, 24):
        assert not drawn.pixmap(QSize(size, size)).isNull(), size
        assert _colours(drawn.pixmap(QSize(size, size))), f"{name} drew nothing at {size}"


def test_the_role_sets_the_colour(qt_app) -> None:
    accent = icons.icon("play", "accent").pixmap(QSize(24, 24))
    assert theme.LIGHT.accent.upper() in _colours(accent)
    text = icons.icon("play", "text").pixmap(QSize(24, 24))
    assert theme.LIGHT.text.upper() in _colours(text)
    assert theme.LIGHT.accent.upper() not in _colours(text)


def test_disabled_is_drawn_in_the_secondary_colour(qt_app) -> None:
    disabled = icons.icon("save").pixmap(QSize(24, 24), QIcon.Mode.Disabled)
    assert theme.LIGHT.secondary.upper() in _colours(disabled)
    assert theme.LIGHT.text.upper() not in _colours(disabled)


def test_unknown_names_and_roles_raise(qt_app) -> None:
    with pytest.raises(KeyError):
        icons.icon("rocket")
    with pytest.raises(KeyError):
        icons.icon("play", "neon")


def test_the_cache_returns_the_same_icon_until_the_theme_changes(qt_app) -> None:
    first = icons.icon("save")
    assert icons.icon("save").cacheKey() == first.cacheKey()
    theme.apply_theme(qt_app, "dark")
    dark = icons.icon("save")
    assert dark.cacheKey() != first.cacheKey()
    assert theme.DARK.text.upper() in _colours(dark.pixmap(QSize(24, 24)))


def test_directional_icons_mirror_in_a_right_to_left_layout(qt_app) -> None:
    ltr_left = icons.icon("chevron-left").pixmap(QSize(24, 24)).toImage()
    qt_app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    icons.clear_cache()
    rtl_right = icons.icon("chevron-right").pixmap(QSize(24, 24)).toImage()
    assert rtl_right == ltr_left
    assert icons.MIRRORED["skip-back"] == "skip-forward"
    # Undo keeps its direction: its arrow means time, not reading order.
    assert "undo-2" not in icons.MIRRORED


def test_set_icon_records_the_choice_and_refresh_retints_it(qt_app) -> None:
    root = QWidget()
    button = QPushButton("Save", root)
    icons.set_icon(button, "save", size=16)
    assert button.iconSize() == QSize(16, 16)
    assert button.property("qalun.icon") == ("save", "text", 16)
    before = button.icon().cacheKey()
    theme.apply_theme(qt_app, "dark")
    assert button.icon().cacheKey() != before  # apply_theme walked the top-level widgets
    plain = QPushButton("No icon", root)
    assert icons.refresh_icons(root) == 1
    assert plain.icon().isNull()
    root.deleteLater()


def test_an_on_role_draws_the_checked_state_in_that_colour(qt_app) -> None:
    """A checked button the sheet fills draws its icon in on_accent; disabled stays grey."""
    drawn = icons.icon("mic", "text", on_role="on_accent")
    on = drawn.pixmap(QSize(16, 16), QIcon.Mode.Normal, QIcon.State.On)
    off = drawn.pixmap(QSize(16, 16), QIcon.Mode.Normal, QIcon.State.Off)
    assert theme.LIGHT.on_accent.upper() in _colours(on)
    assert theme.LIGHT.text.upper() in _colours(off)
    disabled_on = drawn.pixmap(QSize(16, 16), QIcon.Mode.Disabled, QIcon.State.On)
    assert theme.LIGHT.secondary.upper() in _colours(disabled_on)
    # Without an on_role the checked state is the plain one (a disclosure chevron).
    plain = icons.icon("chevron-down").pixmap(QSize(16, 16), QIcon.Mode.Normal, QIcon.State.On)
    assert theme.LIGHT.text.upper() in _colours(plain)


def test_a_refresh_keeps_the_on_role(qt_app) -> None:
    root = QWidget()
    button = QPushButton("Recitation", root)
    button.setCheckable(True)
    icons.set_icon(button, "mic", size=16, on_role="on_accent")
    assert button.property("qalun.icon") == ("mic", "text", 16, "on_accent")
    theme.apply_theme(qt_app, "dark")
    on = button.icon().pixmap(QSize(16, 16), QIcon.Mode.Normal, QIcon.State.On)
    assert theme.DARK.on_accent.upper() in _colours(on)
    root.deleteLater()


def test_mirror_false_keeps_a_directional_icon_as_drawn_under_rtl(qt_app) -> None:
    ltr = icons.icon("chevron-right").pixmap(QSize(16, 16)).toImage()
    qt_app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    try:
        icons.clear_cache()
        kept = icons.icon("chevron-right", mirror=False).pixmap(QSize(16, 16)).toImage()
        flipped = icons.icon("chevron-right").pixmap(QSize(16, 16)).toImage()
        assert kept == ltr and flipped != ltr
        root = QWidget()
        button = QPushButton(root)
        icons.set_icon(button, "chevron-right", size=16, mirror=False)
        assert button.property("qalun.icon") == ("chevron-right", "text", 16, None, False)
        assert icons.refresh_icons(root) == 1
        assert button.icon().pixmap(QSize(16, 16)).toImage() == ltr
    finally:
        qt_app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        icons.clear_cache()

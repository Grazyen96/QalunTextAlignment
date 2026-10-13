"""The home window's header: icon, name, and the three buttons at its far end."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import Qt  # noqa: E402

from qurantext.gui import theme  # noqa: E402
from qurantext.gui.home.header import HeaderBar  # noqa: E402
from qurantext.gui.i18n import t  # noqa: E402


@pytest.fixture()
def header(qt_app):
    theme.apply_theme(qt_app, "light")
    bar = HeaderBar()
    yield bar
    bar.deleteLater()


def test_it_shows_the_icon_and_the_name_in_the_title_font(header) -> None:
    assert not header.icon_label.pixmap().isNull()
    assert header.title_label.text() == "Qalun"
    assert header.title_label.font().pointSizeF() == theme.font("title").pointSizeF()
    assert header.sizeHint().height() <= 48


def test_the_three_buttons_carry_icons_tooltips_and_signals(header) -> None:
    seen = []
    header.theme_toggle_requested.connect(lambda: seen.append("theme"))
    header.settings_requested.connect(lambda: seen.append("settings"))
    header.help_requested.connect(lambda: seen.append("help"))
    for button, name, key in (
        (header.theme_button, "moon", "home.header.theme_to_dark"),
        (header.settings_button, "settings", "home.header.settings"),
        (header.help_button, "circle-question-mark", "home.header.help"),
    ):
        assert button.property("qalun.icon")[0] == name
        assert button.toolTip() == t(key)
        assert button.autoRaise()
        button.click()
    assert seen == ["theme", "settings", "help"]


def test_show_theme_flips_the_toggles_icon_and_tooltip(header) -> None:
    header.show_theme("dark")
    assert header.theme_button.property("qalun.icon")[0] == "sun"
    assert header.theme_button.toolTip() == t("home.header.theme_to_light")
    header.show_theme("light")
    assert header.theme_button.property("qalun.icon")[0] == "moon"


def test_the_buttons_sit_at_the_trailing_edge(qt_app, header) -> None:
    header.resize(800, 48)
    header.show()
    from tests.qt_helpers import spin

    spin(50)
    assert header.help_button.x() > header.title_label.x()
    qt_app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    try:
        mirrored = HeaderBar()
        mirrored.resize(800, 48)
        mirrored.show()
        spin(50)
        assert mirrored.help_button.x() < mirrored.title_label.x()
        mirrored.deleteLater()
    finally:
        qt_app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

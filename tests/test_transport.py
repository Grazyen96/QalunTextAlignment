"""The transport row: every playback and nudge action as an icon button, the rate in one click."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import QSize, Qt  # noqa: E402

from qurantext.gui import icons, theme  # noqa: E402
from qurantext.gui.i18n import clock, t  # noqa: E402
from qurantext.gui.review.player import RATES  # noqa: E402
from qurantext.gui.review.selection_bar import NUDGE_S, SelectionBar  # noqa: E402
from qurantext.gui.review.transport import Transport  # noqa: E402


@pytest.fixture()
def transport(qt_app):
    theme.apply_theme(qt_app, "light")
    made = Transport(RATES)
    yield made
    made.deleteLater()


def test_the_buttons_carry_icons_and_fire_their_signals(transport) -> None:
    seen = []
    transport.step_requested.connect(lambda d: seen.append(("step", d)))
    transport.play_toggled.connect(lambda: seen.append("play"))
    transport.nudge_requested.connect(lambda d: seen.append(("nudge", round(d, 3))))
    transport.snap_requested.connect(lambda: seen.append("snap"))
    for button, name in (
        (transport.prev_word_button, "skip-back"),
        (transport.play_button, "play"),
        (transport.next_word_button, "skip-forward"),
        (transport.minus_button, "chevron-right"),
        (transport.snap_button, "crosshair"),
        (transport.plus_button, "chevron-left"),
    ):
        assert button.property("qalun.icon")[0] == name, name
    transport.set_selection(True)
    transport.prev_word_button.click()
    transport.play_button.click()
    transport.next_word_button.click()
    transport.minus_button.click()
    transport.snap_button.click()
    transport.plus_button.click()
    assert seen == [
        ("step", -1),
        "play",
        ("step", 1),
        ("nudge", -NUDGE_S),
        "snap",
        ("nudge", NUDGE_S),
    ]


def test_the_rate_is_a_segmented_choice(transport) -> None:
    seen = []
    transport.rate_changed.connect(seen.append)
    assert list(transport.rate_buttons) == list(RATES)
    assert transport.rate_buttons[1.0].isChecked()
    transport.rate_buttons[0.5].click()
    assert seen == [0.5] and not transport.rate_buttons[1.0].isChecked()
    transport.set_rate(0.75)
    assert transport.rate_buttons[0.75].isChecked() and seen == [0.5]


def test_playing_and_time_and_selection_show(transport) -> None:
    transport.set_playing(True)
    assert transport.play_button.property("qalun.icon")[0] == "pause"
    assert transport.play_button.toolTip().startswith(t("review.pause"))
    transport.set_time(96.5)
    assert transport.time_label.text() == clock(96.5)
    transport.set_selection(False)
    assert not transport.minus_button.isEnabled() and not transport.snap_button.isEnabled()


def test_the_nudge_chevrons_keep_their_direction_in_arabic(qt_app) -> None:
    ltr = Transport(RATES)
    minus_ltr = ltr.minus_button.icon().pixmap(QSize(16, 16)).toImage()
    qt_app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    try:
        icons.clear_cache()
        rtl = Transport(RATES)
        assert rtl.minus_button.icon().pixmap(QSize(16, 16)).toImage() == minus_ltr
        assert (
            rtl.prev_word_button.icon().pixmap(QSize(16, 16)).toImage()
            != ltr.prev_word_button.icon().pixmap(QSize(16, 16)).toImage()
        )
        rtl.deleteLater()
    finally:
        qt_app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        icons.clear_cache()
    ltr.deleteLater()


def test_the_selection_bar_delegates_its_buttons_to_the_transport(transport) -> None:
    bar = SelectionBar(transport)
    assert bar.minus_button is transport.minus_button
    assert bar.snap_button is transport.snap_button
    bar.show_word(None)
    assert bar.label.text() == t("review.no_selection")

"""The composites every screen shares: a primary button, a section header, a card, a status chip."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QDialog, QFrame, QLabel, QPushButton, QSizePolicy  # noqa: E402

from qurantext.gui import theme, widgets  # noqa: E402
from qurantext.gui.colors import warning_color  # noqa: E402
from tests.test_colors import contrast  # noqa: E402


@pytest.fixture(autouse=True)
def _light(qt_app):
    theme.apply_theme(qt_app, "light")
    yield


def test_make_primary_marks_a_plain_button_without_subclassing(qt_app) -> None:
    button = QPushButton("Start")
    assert widgets.make_primary(button) is button
    assert type(button) is QPushButton
    assert button.property("primary") is True
    assert button.isDefault() is False  # not in a dialog


def test_make_primary_makes_the_dialog_default(qt_app) -> None:
    dialog = QDialog()
    button = QPushButton("OK", dialog)
    widgets.make_primary(button)
    assert button.isDefault() is True
    dialog.deleteLater()


def test_a_section_header_uses_the_section_font_and_holds_a_trailing_widget(qt_app) -> None:
    refresh = QPushButton("Refresh")
    header = widgets.SectionHeader("Your jobs", trailing=refresh)
    assert isinstance(header.label, QLabel)
    assert header.label.text() == "Your jobs"
    assert header.label.font().pointSizeF() == theme.font("section").pointSizeF()
    assert refresh.parent() is header
    header.set_text("Jobs")
    assert header.label.text() == "Jobs"


def test_a_card_is_a_framed_raised_surface(qt_app) -> None:
    card = widgets.Card()
    assert isinstance(card, QFrame)
    assert card.property("card") is True
    margins = card.body.contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (16, 16, 16, 16)
    inner = QLabel("inside")
    card.body.addWidget(inner)
    assert inner.parent() is card


def test_a_status_chip_shows_text_an_icon_and_its_kind(qt_app) -> None:
    chip = widgets.StatusChip("Needs review", icon_name="circle-check", kind="attention")
    assert chip.text_label.text() == "Needs review"
    assert not chip.icon_label.pixmap().isNull()
    assert chip.property("chip") is True
    assert chip.property("kind") == "attention"
    assert chip.text_label.palette().color(chip.text_label.foregroundRole()) == warning_color(
        chip.palette()
    )
    chip.set_kind("neutral")
    assert chip.property("kind") == "neutral"
    with pytest.raises(KeyError):
        chip.set_kind("danger")
    plain = widgets.StatusChip("Reviewed")
    assert plain.icon_label.isHidden()
    assert chip.height() >= 22


def test_the_composites_take_only_the_height_they_need(qt_app) -> None:
    """Beside a hidden list, a header must not take half the column's spare height."""
    for widget in (
        widgets.SectionHeader("Your jobs"),
        widgets.Card(),
        widgets.StatusChip("Needs review"),
    ):
        assert widget.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed, widget


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("kind", widgets.CHIP_KINDS)
def test_a_chips_word_reads_on_its_fill(qt_app, mode, kind) -> None:
    """The chip sits on the window colour with a border outline, so each kind's word reads."""
    tokens = theme.tokens_for(mode)
    theme.apply_theme(qt_app, mode)
    assert f"background: {tokens.window}" in qt_app.styleSheet().split('QFrame[chip="true"]')[1]
    chip = widgets.StatusChip("Needs review", icon_name="circle-check", kind=kind)
    shown = chip.text_label.palette().color(chip.text_label.foregroundRole())
    assert contrast(shown, QColor(tokens.window)) >= 4.5


def test_a_chip_takes_the_new_colours_on_a_theme_switch(qt_app) -> None:
    chip = widgets.StatusChip("Needs review", icon_name="circle-check", kind="accent")
    theme.apply_theme(qt_app, "dark")
    shown = chip.text_label.palette().color(chip.text_label.foregroundRole())
    assert shown == QColor(theme.DARK.accent)

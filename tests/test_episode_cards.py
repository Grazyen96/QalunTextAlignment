# tests/test_episode_cards.py
"""One card of the Episode strip: title, controls, thumbnail, length, chip, selection."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QComboBox

from qurantext.gui.review.episode_cards import CARD_WIDTH, THUMB_BOX, PartCard, fitted_size


def test_fitted_size_keeps_the_frames_shape_inside_the_box() -> None:
    assert fitted_size((1920, 1080)) == (176, 99)
    assert fitted_size((1080, 1920)) == (56, 99)
    assert fitted_size((100, 100), (50, 80)) == (50, 50)


def test_a_card_starts_empty_with_a_dash_and_no_chip(qt_app) -> None:
    card = PartCard("Intro")
    assert card.title_label.text() == "Intro" and card.width() == CARD_WIDTH
    assert card.thumb_label.property("placeholder") is True
    assert card.thumb_label.size().toTuple() == THUMB_BOX
    assert card.length_label.text() == "—" and card.chip.isHidden()


def test_a_thumbnail_a_tile_and_a_placeholder_swap_in_and_out(qt_app) -> None:
    card = PartCard("Intro")
    pixmap = QPixmap(352, 198)
    pixmap.fill(QColor(200, 0, 0))
    card.set_thumbnail(pixmap)
    assert card.thumb_label.property("placeholder") is False
    assert card.thumb_label.pixmap().size().toTuple() == THUMB_BOX
    card.set_icon_tile("film")
    assert card.thumb_label.pixmap().width() < 100
    card.set_thumbnail(None)
    assert card.thumb_label.property("placeholder") is True


def test_the_chip_shows_its_text_kind_and_icon_or_hides(qt_app) -> None:
    card = PartCard("Outro")
    card.set_chip("Needs attention", "attention", "triangle-alert")
    assert not card.chip.isHidden() and card.chip.text_label.text() == "Needs attention"
    assert card.chip.property("kind") == "attention"
    card.set_chip(None)
    assert card.chip.isHidden()


def test_a_click_a_key_or_focus_in_a_control_asks_for_selection(qt_app) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent

    card = PartCard("Intro")
    combo = QComboBox()
    card.add_control(combo)
    asked = []
    card.select_requested.connect(lambda: asked.append(True))
    card.click()
    assert asked == [True]
    qt_app.sendEvent(combo, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason))
    assert asked == [True, True]
    card.set_selected(True)
    assert card.selected and card.property("selected") is True
    card.set_selectable(False)
    card.click()
    assert asked == [True, True], "an unselectable card asks for nothing"

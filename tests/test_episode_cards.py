# tests/test_episode_cards.py
"""One card of the Episode strip: title, controls, thumbnail, length, chip, selection."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QComboBox  # noqa: E402

from qurantext.gui.review.episode_cards import (  # noqa: E402
    CARD_WIDTH,
    THUMB_BOX,
    PartCard,
    fitted_size,
)


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


def test_a_nested_control_layout_is_added_once_and_its_widgets_are_watched(qt_app) -> None:
    from PySide6.QtCore import QEvent, qInstallMessageHandler
    from PySide6.QtGui import QFocusEvent
    from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout

    card = PartCard("Intro")
    column = QVBoxLayout()
    buttons = QHBoxLayout()
    choose = QPushButton("Choose")
    buttons.addWidget(choose)
    column.addLayout(buttons)
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda _kind, _context, text: messages.append(text))
    try:
        card.add_control_layout(column)
    finally:
        qInstallMessageHandler(previous)
    # The inner row is the column's: adding it to the card as well is what Qt warns about.
    assert not [text for text in messages if "already has a parent" in text]
    assert buttons.parent() is column
    asked = []
    card.select_requested.connect(lambda: asked.append(True))
    qt_app.sendEvent(choose, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
    assert asked == [True]


def test_the_card_holds_its_picture_centred_and_selection_moves_nothing(qt_app) -> None:
    from PySide6.QtWidgets import QApplication

    from qurantext.gui import theme

    theme.apply_theme(qt_app, "light")
    card = PartCard("Intro")
    card.show()
    QApplication.processEvents()
    assert card.minimumSizeHint().width() == CARD_WIDTH
    before = card.thumb_label.geometry()
    # Centred: as much room on the left as on the right.
    assert before.x() == CARD_WIDTH - before.right() - 1
    card.set_selected(True)
    card.layout().activate()
    QApplication.processEvents()
    assert card.minimumSizeHint().width() == CARD_WIDTH
    assert card.thumb_label.geometry() == before
    card.close()


def test_enter_selects_only_from_the_card_itself_not_from_its_controls(qt_app) -> None:
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    card = PartCard("Intro")
    combo = QComboBox()
    card.add_control(combo)
    card.show()
    card.activateWindow()
    asked = []
    card.select_requested.connect(lambda: asked.append(True))
    combo.setFocus()
    QApplication.processEvents()
    asked.clear()  # focus landing on the control asked once; that is not the key
    QTest.keyClick(combo, Qt.Key.Key_Return)
    assert asked == [], "Enter in a control goes on to the dialog's OK"
    card.setFocus()
    QApplication.processEvents()
    QTest.keyClick(card, Qt.Key.Key_Space)
    QTest.keyClick(card, Qt.Key.Key_Return)
    assert asked == [True, True]
    card.close()

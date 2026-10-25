"""Quran words in the review window are drawn in the bundled Quran face.

The shipped text writes open tanween as U+0657, U+065E and U+0656, which
only ``qaloon.10.ttf`` draws as open tanween; the interface font's Arabic
fallback draws an inverted damma, a fatha with two dots and a subscript alef.
So the word strip, the segment table's card text and the selection bar draw a
card's words in that face, and a lecture's recognised speech keeps the
interface font.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="the review widgets need Qt")

from PySide6.QtCore import Qt  # noqa: E402

JANNATUN = "\u062c\u064e\u0646\u0651\u064e\u0629\u065e"
RAJULAN = "\u0631\u064e\u062c\u064f\u0644\u0627\u0657"
JANNATIN = "\u062c\u064e\u0646\u0651\u064e\u0670\u062a\u0656"


def _recitation_session():
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import Project

    cards = [
        {
            "surah_num": 25,
            "from_ayah": 7,
            "to_ayah": 7,
            "full_text": f"{JANNATUN} {RAJULAN} {JANNATIN}",
            "confidence": 1.0,
            "start_time": 0.0,
            "end_time": 10.0,
            "word_timings": [
                {"word": JANNATUN, "start": 1.0, "end": 2.0},
                {"word": RAJULAN, "start": 2.0, "end": 3.0},
                {"word": JANNATIN, "start": 3.0, "end": 4.0},
            ],
        }
    ]
    return ReviewSession(Project(audio=Path("a.mp3"), cards=cards))


def _lecture_session():
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import CaptionCue, Project

    project = Project(
        audio=Path("d.mp3"),
        mode="lecture",
        captions=[
            CaptionCue(5.0, 6.0, "spoken", words=[{"word": "spoken", "start": 5.0, "end": 6.0}])
        ],
    )
    return ReviewSession(project)


def _strip(session):
    from qurantext.gui.review.viewport import Viewport
    from qurantext.gui.review.word_strip import WordStrip

    vp = Viewport()
    vp.set_duration(10.0)
    vp.set_window(0.0, 10.0)
    strip = WordStrip(vp, session)
    strip.resize(1000, 44)
    return strip


def _bar():
    from qurantext.gui.review.player import RATES
    from qurantext.gui.review.selection_bar import SelectionBar
    from qurantext.gui.review.transport import Transport

    return SelectionBar(Transport(RATES))


def _row_of(table, kind: str) -> int:
    return next(
        r
        for r in range(table.rowCount())
        if table.item(r, 0).data(Qt.ItemDataRole.UserRole)[0] == kind
    )


def test_the_quran_face_is_the_bundled_qaloon_face(qt_app) -> None:
    from qurantext.gui.quran_face import quran_font_family

    assert "QALOON" in quran_font_family().upper()


def test_with_quran_face_puts_the_quran_family_first(qt_app) -> None:
    from PySide6.QtGui import QFont

    from qurantext.gui.quran_face import quran_font_family, with_quran_face

    base = QFont(["Sans Serif"], 11)
    font = with_quran_face(base)
    assert font.families() == [quran_font_family(), *base.families()]
    assert font.pointSize() == 11
    assert base.families() == ["Sans Serif"]  # a copy: the font handed in is left alone


def test_card_text_cells_use_the_quran_face_first(qt_app) -> None:
    from qurantext.gui.quran_face import quran_font_family
    from qurantext.gui.review.segment_list import SegmentList
    from qurantext.gui.review.session import CARD

    table = SegmentList(_recitation_session())
    text_item = table.item(_row_of(table, CARD), 2)
    assert text_item.font().families()[0] == quran_font_family()


def test_caption_cells_keep_the_table_font(qt_app) -> None:
    from qurantext.gui.quran_face import quran_font_family
    from qurantext.gui.review.segment_list import SegmentList
    from qurantext.gui.review.session import CAPTION

    table = SegmentList(_lecture_session())
    text_item = table.item(_row_of(table, CAPTION), 2)
    assert text_item.font().families()[:1] != [quran_font_family()]


def test_the_strip_draws_card_words_in_the_quran_face(qt_app) -> None:
    from qurantext.gui.quran_face import quran_font_family

    session = _recitation_session()
    strip = _strip(session)
    card_word = session.words()[0]
    assert strip.font_for(card_word).families()[0] == quran_font_family()
    assert not strip.grab().isNull()


def test_the_strip_draws_caption_words_in_its_own_font(qt_app) -> None:
    session = _lecture_session()
    strip = _strip(session)
    caption_word = session.words()[0]
    assert strip.font_for(caption_word) == strip.font()


def test_the_selection_bar_names_a_quran_word_in_the_quran_face(qt_app) -> None:
    from qurantext.gui import theme
    from qurantext.gui.quran_face import quran_font_family

    bar = _bar()
    bar.show_word(_recitation_session().words()[0])
    assert bar.label.font().families()[0] == quran_font_family()
    bar.show_word(None)
    assert bar.label.font() == theme.font("section")


def test_the_selection_bar_names_a_spoken_word_in_its_own_font(qt_app) -> None:
    from qurantext.gui import theme

    bar = _bar()
    bar.show_word(_lecture_session().words()[0])
    assert bar.label.font() == theme.font("section")


def test_without_the_quran_face_the_widgets_keep_their_font(qt_app, monkeypatch) -> None:
    from qurantext.gui import quran_face, theme
    from qurantext.gui.review.segment_list import SegmentList
    from qurantext.gui.review.session import CARD

    monkeypatch.setattr(quran_face, "quran_font_family", lambda: "")
    session = _recitation_session()

    table = SegmentList(session)
    text_item = table.item(_row_of(table, CARD), 2)
    assert text_item.font().families() == table.font().families()

    strip = _strip(session)
    card_word = session.words()[0]
    assert strip.font_for(card_word) == strip.font()
    assert not strip.grab().isNull()  # painting does not raise

    bar = _bar()
    bar.show_word(card_word)
    assert bar.label.font() == theme.font("section")


def test_selecting_a_quran_word_does_not_make_the_bar_taller(qt_app) -> None:
    """The Quran face's line is taller than the section font's; the bar keeps one height."""
    bar = _bar()
    bar.show_word(None)
    empty = bar.sizeHint().height()
    bar.show_word(_recitation_session().words()[0])
    assert bar.sizeHint().height() == empty

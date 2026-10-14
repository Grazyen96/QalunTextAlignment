"""Every binding, in a sheet a person can open with ?."""

from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from qurantext.gui.i18n import t  # noqa: E402
from qurantext.gui.language import apply_language  # noqa: E402
from qurantext.gui.review.shortcut_sheet import BINDINGS, ShortcutSheet, hint_html  # noqa: E402


def test_the_sheet_lists_every_binding_in_three_groups(qt_app) -> None:
    sheet = ShortcutSheet()
    rows = sheet.rows()
    assert len(rows) == len(BINDINGS)
    keys = [row[0] for row in rows]
    for expected in (
        "Space",
        "←",
        "→",
        "[",
        "]",
        ",",
        ".",
        "Ctrl+Z",
        "Ctrl+Shift+Z",
        "Ctrl+S",
        "?",
    ):
        assert any(expected in key for key in keys), expected
    assert {group for group, _, _ in BINDINGS} == {"playback", "editing", "file"}
    assert sheet.windowTitle().strip("\u200e\u200f") == t("review.shortcuts.title")
    assert not sheet.isModal()
    sheet.deleteLater()


def test_every_binding_reads_in_arabic_too(qt_app) -> None:
    apply_language(qt_app, "ar")
    try:
        sheet = ShortcutSheet()
        assert all(action for _, action in sheet.rows())
        sheet.deleteLater()
    finally:
        apply_language(qt_app, "en")


def test_the_hint_is_short_and_links_to_the_sheet() -> None:
    assert 'href="shortcuts"' in hint_html()
    assert hint_html() == t("review.hint")
    shown = re.sub(r"<[^>]+>", "", hint_html())  # the words, without the link's markup
    assert len(shown) <= 80


@pytest.mark.parametrize("language", ["en", "ar"])
def test_every_row_is_readable_and_no_row_overlaps_the_next(qt_app, language) -> None:
    """A wrapped action text gets its whole height, at the sheet's least width."""
    from qurantext.gui import theme

    apply_language(qt_app, language)
    theme.apply_theme(qt_app, "light")
    try:
        sheet = ShortcutSheet()
        sheet.show()
        sheet.adjustSize()
        qt_app.processEvents()
        assert sheet.width() >= ShortcutSheet.MIN_WIDTH
        for _grid, labels in sheet.groups:
            for (keys_n, action_n), (keys_next, action_next) in zip(
                labels, labels[1:], strict=False
            ):
                assert action_n.geometry().bottom() < action_next.geometry().top(), action_n.text()
                assert keys_n.geometry().bottom() < keys_next.geometry().top(), keys_n.text()
            for _keys, action in labels:
                assert action.height() >= action.heightForWidth(action.width()), action.text()
        # One keys column for every group: the actions line up down the sheet.
        edges = {
            action.mapTo(sheet, action.rect().topLeft()).x()
            for _grid, labels in sheet.groups
            for _keys, action in labels
        }
        assert len(edges) == 1, edges
        sheet.deleteLater()
    finally:
        apply_language(qt_app, "en")


def test_the_space_bar_is_named_in_the_sheet_s_language(qt_app) -> None:
    apply_language(qt_app, "ar")
    try:
        sheet = ShortcutSheet()
        assert sheet.rows()[0][0] == t("review.key_space") != "Space"
        sheet.deleteLater()
    finally:
        apply_language(qt_app, "en")


def test_every_key_the_window_answers_to_is_on_the_sheet(qt_app, tmp_path) -> None:
    """Spec section 6: each binding in ``window._keys`` appears in ``BINDINGS``."""
    from qurantext.gui.review.player import FakePlayer
    from qurantext.gui.review.window import ReviewWindow
    from qurantext.jobs.project import Project, save_project

    project = Project(audio=tmp_path / "missing.mp3", cards=[])
    save_project(project, tmp_path / "m.qalun.json")
    window = ReviewWindow(project, player=FakePlayer(duration=10.0))
    try:
        shown = " ".join(keys for _, keys, _ in BINDINGS)
        arrows = {"Left": "←", "Right": "→"}
        # Key-press aliases of a key the sheet already names (what a shifted
        # press reports on a US layout).
        aliases = {"Shift+>": "Shift+.", "Shift+<": "Shift+,", "Shift+?": "?", "Shift+/": "?"}
        for sequence in window._keys:
            name = arrows.get(sequence, aliases.get(sequence, sequence))
            assert name in shown, sequence
    finally:
        window.close()
        window.deleteLater()

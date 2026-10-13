"""Every binding, in a sheet a person can open with ?."""

from __future__ import annotations

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
    assert len(hint_html()) < len(t("review.hint")) + 1

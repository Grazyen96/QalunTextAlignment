"""Every word the window shows comes from one table, so a second language is one more table."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from qurantext.gui import i18n

GUI_SOURCE = Path(__file__).resolve().parents[1] / "src" / "qurantext" / "gui"
_CALL = re.compile(r"""\bt\(\s*["']([a-z0-9_.]+)["']""")


def test_t_formats_and_falls_back() -> None:
    i18n.STRINGS["en"]["test.greeting"] = "Hello {name}"
    try:
        assert i18n.t("test.greeting", name="Khalil") == "Hello Khalil"
        assert i18n.t("test.not_there") == "test.not_there"
    finally:
        del i18n.STRINGS["en"]["test.greeting"]


def test_an_unknown_language_is_refused() -> None:
    with pytest.raises(ValueError):
        i18n.set_language("xx")
    assert i18n.current_language() == "en"


def test_every_key_the_code_uses_exists_in_every_language() -> None:
    used = set()
    for path in GUI_SOURCE.rglob("*.py"):
        used |= set(_CALL.findall(path.read_text(encoding="utf-8")))
    for language in i18n.LANGUAGES:
        missing = sorted(used - set(i18n.STRINGS[language]))
        assert not missing, f"{language} is missing: {missing}"


def test_every_language_has_the_same_keys_and_placeholders() -> None:
    fields = re.compile(r"{(\w+)}")
    english = i18n.STRINGS["en"]
    for language in i18n.LANGUAGES:
        table = i18n.STRINGS[language]
        assert set(table) == set(english)
        for key, text in english.items():
            assert set(fields.findall(table[key])) == set(fields.findall(text)), key

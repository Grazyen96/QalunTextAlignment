"""Every word the window shows comes from one table, so a second language is one more table."""

from __future__ import annotations

import re
import string
import subprocess
import sys
from pathlib import Path

import pytest

from qurantext.gui import i18n
from qurantext.gui.i18n import (
    LANGUAGE_NAMES,
    RTL_LANGUAGES,
    is_rtl,
    ltr,
    plural_category,
    set_language,
    t,
    time_span,
    tn,
)

GUI_SOURCE = Path(__file__).resolve().parents[1] / "src" / "qurantext" / "gui"
_FSI, _PDI, _LRI = "⁨", "⁩", "⁦"
_CALL = re.compile(r"""\btn?\(\s*["']([a-z0-9_.]+)["']""")

#: The plural forms each language's table must give (CLDR cardinal categories).
#: Arabic is named before its table exists, so the table cannot land short of them.
_PLURAL_CATEGORIES = {
    "en": ("one", "other"),
    "ar": ("zero", "one", "two", "few", "many", "other"),
}


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


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
    assert "review.gaps" in used, "tn( calls must count too"
    for language in i18n.LANGUAGES:
        missing = sorted(used - set(i18n.STRINGS[language]))
        assert not missing, f"{language} is missing: {missing}"


@pytest.mark.parametrize(
    ("n", "category"),
    [
        (0, "zero"),
        (1, "one"),
        (2, "two"),
        (3, "few"),
        (10, "few"),
        (11, "many"),
        (99, "many"),
        (100, "other"),
        (102, "other"),
        (103, "few"),
        (111, "many"),
    ],
)
def test_arabic_plural_categories(n, category) -> None:
    assert plural_category("ar", n) == category


def test_english_plural_categories() -> None:
    assert [plural_category("en", n) for n in (0, 1, 2)] == ["other", "one", "other"]


def test_tn_picks_the_variant_and_formats_count() -> None:
    i18n.STRINGS["en"]["test.files"] = {"one": "{count} file", "other": "{count} files"}
    try:
        assert tn("test.files", 1) == "1 file"
        assert tn("test.files", 3) == "3 files"
        assert tn("test.not_there", 3) == "test.not_there"
    finally:
        del i18n.STRINGS["en"]["test.files"]


def test_t_refuses_a_plural_key() -> None:
    i18n.STRINGS["en"]["test.files"] = {"one": "{count} file", "other": "{count} files"}
    try:
        with pytest.raises(TypeError):
            t("test.files", count=2)
    finally:
        del i18n.STRINGS["en"]["test.files"]


def _add_rtl_language(monkeypatch, key: str, text: str | dict[str, str]) -> None:
    """A throwaway right-to-left language carrying one key, so no real table is needed."""
    monkeypatch.setitem(i18n.STRINGS, "rtl_test", {key: text})
    monkeypatch.setattr(i18n, "RTL_LANGUAGES", frozenset({"rtl_test"}))
    monkeypatch.setattr(i18n, "LANGUAGES", (*i18n.LANGUAGES, "rtl_test"))
    monkeypatch.setitem(i18n.STRINGS["en"], key, text)


def test_values_are_isolated_only_in_a_right_to_left_language(monkeypatch) -> None:
    _add_rtl_language(monkeypatch, "test.gap", "gap {span} s")
    try:
        assert t("test.gap", span=time_span(1.5, 2.25)) == "gap 1.50–2.25 s"
        set_language("rtl_test")
        assert t("test.gap", span=time_span(1.5, 2.25)) == f"gap {_FSI}1.50–2.25{_PDI} s"
        assert ltr("1.50") == f"{_LRI}1.50{_PDI}"
        assert is_rtl()
        assert not is_rtl("en")
    finally:
        set_language("en")
    assert ltr("1.50") == "1.50"
    assert not is_rtl()


def test_format_specs_still_apply_inside_isolation(monkeypatch) -> None:
    _add_rtl_language(monkeypatch, "test.duration", "{duration:.1f} s")
    try:
        assert t("test.duration", duration=3.24) == "3.2 s"
        set_language("rtl_test")
        assert t("test.duration", duration=3.24) == f"{_FSI}3.2{_PDI} s"
    finally:
        set_language("en")


def test_plural_counts_are_isolated_too(monkeypatch) -> None:
    _add_rtl_language(monkeypatch, "test.files", {"one": "{count} file", "other": "{count} files"})
    try:
        set_language("rtl_test")
        assert tn("test.files", 3) == f"{_FSI}3{_PDI} files"
    finally:
        set_language("en")


def test_time_span_formats_one_value() -> None:
    assert time_span(12.3, 15.2) == "12.30–15.20"
    assert time_span(1.0, 2.0, digits=1, sep=" → ") == "1.0 → 2.0"


def test_language_names_cover_every_language() -> None:
    assert set(i18n.LANGUAGES) <= set(LANGUAGE_NAMES)
    assert RTL_LANGUAGES <= set(LANGUAGE_NAMES)
    assert LANGUAGE_NAMES == {"en": "English", "ar": "العربية"}
    assert RTL_LANGUAGES == frozenset({"ar"})


def test_every_language_has_the_same_keys_and_placeholders() -> None:
    english = i18n.STRINGS["en"]
    for language in i18n.LANGUAGES:
        table = i18n.STRINGS[language]
        assert set(table) == set(english), language
        for key, text in english.items():
            value = table[key]
            assert isinstance(value, dict) == isinstance(text, dict), key
            if isinstance(text, dict):
                assert {"one", "other"} <= set(text), key
                needed = set(_PLURAL_CATEGORIES[language])
                assert needed <= set(value), (language, key)
                # "other" carries every field; a variant may drop {count} ("one file")
                assert _fields(value["other"]) == _fields(text["other"]), (language, key)
                for variant in value.values():
                    assert _fields(variant) <= _fields(text["other"]), (language, key)
            else:
                assert _fields(value) == _fields(text), (language, key)


def test_the_counted_strings_read_naturally_in_english() -> None:
    assert tn("home.cards", 1) == "1 card"
    assert tn("home.cards", 2) == "2 cards"
    assert tn("review.gaps", 1) == "1 stretch of speech has no word:"
    assert tn("review.gaps", 4) == "4 stretches of speech have no word:"
    assert tn("review.more_gaps", 3) == "…and 3 more"
    assert tn("export.done", 1, names="a.srt") == "Wrote 1 file: a.srt"
    assert tn("export.done", 2, names="a.srt, a.vtt") == "Wrote 2 files: a.srt, a.vtt"
    assert tn("home.finished.matched", 1) == "Matched 1 card. The review is open."
    assert tn("home.finished.matched", 3) == "Matched 3 cards. The review is open."
    assert tn("home.surah_item", 7, num=1, name="Al-Fatiha") == "1. Al-Fatiha  (7 ayat)"
    assert not any(
        "(s)" in variant or "(es)" in variant
        for value in i18n.STRINGS["en"].values()
        for variant in (value.values() if isinstance(value, dict) else [value])
    )


def test_errors_are_framed_in_a_sentence() -> None:
    assert t("review.save_failed", details="disk full") == (
        "The corrections were not saved: disk full"
    )
    assert t("export.failed", details="disk full") == "The subtitles were not written: disk full"
    assert t("session.card_follows_words") == (
        "This card's times follow its words; retime the words instead."
    )
    assert t("session.no_file") == "This project has no file to write back to."
    assert t("home.busy_matching") == (
        "This job is running again; open its review once it finishes."
    )


def test_the_table_imports_no_qt() -> None:
    """The review session raises errors in these words, and it must stay Qt-free."""
    probe = (
        "import sys, qurantext.gui.i18n; print(any(m.startswith('PySide6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"

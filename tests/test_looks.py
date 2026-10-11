# tests/test_looks.py
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from qurantext.core import frame_renderer as fr
from qurantext.core.looks import (
    COLOUR_FIELDS,
    NIGHT_GOLD,
    PRESETS,
    Background,
    Look,
    composite,
    contrast_ratio,
    look_from_style,
    merge_style,
    readability_warnings,
)


def test_night_gold_is_todays_constants() -> None:
    assert NIGHT_GOLD.frame_bg == fr.COLOUR_BG
    assert NIGHT_GOLD.card == fr.COLOUR_CARD
    assert NIGHT_GOLD.card_border == fr.COLOUR_CARD_BORDER
    assert NIGHT_GOLD.header_text == fr.COLOUR_HEADER_TEXT
    assert NIGHT_GOLD.body_text == fr.COLOUR_BODY_TEXT
    assert NIGHT_GOLD.highlight_word == fr.COLOUR_HIGHLIGHT_WORD
    assert NIGHT_GOLD.subtle == fr.COLOUR_SUBTLE
    assert NIGHT_GOLD.debug_text == fr.COLOUR_DEBUG_TEXT
    assert NIGHT_GOLD.placeholder_text == fr.COLOUR_PLACEHOLDER_TEXT
    assert NIGHT_GOLD.caption_bg == fr.COLOUR_CAPTION_BG
    assert NIGHT_GOLD.caption_text == fr.COLOUR_CAPTION_TEXT
    assert NIGHT_GOLD.caption_active == fr.COLOUR_CAPTION_ACTIVE
    assert NIGHT_GOLD.caption_upcoming == fr.COLOUR_CAPTION_UPCOMING
    assert NIGHT_GOLD.background == Background("solid", fr.COLOUR_BG, fr.COLOUR_BG)


def test_the_six_presets_exist_and_are_hashable() -> None:
    assert list(PRESETS) == ["night_gold", "emerald", "sand", "ink_on_paper", "ocean", "rose"]
    assert len({hash(look) for look in PRESETS.values()}) == 6
    assert all(look.base_preset == name for name, look in PRESETS.items())


@pytest.mark.parametrize("name", list(PRESETS))
def test_every_preset_round_trips(name: str) -> None:
    look = PRESETS[name]
    assert Look.from_dict(look.to_dict()) == look


def test_an_empty_or_missing_style_is_night_gold() -> None:
    assert look_from_style({}) == NIGHT_GOLD
    assert look_from_style(None) == NIGHT_GOLD


def test_from_dict_tolerates_junk_field_by_field() -> None:
    data = PRESETS["emerald"].to_dict()
    data["colours"]["body_text"] = "#zzz"
    data["colours"]["highlight_word"] = 5
    data["background"]["dim"] = "lots"
    data["background"]["kind"] = "lava"
    look = Look.from_dict(data)
    emerald = PRESETS["emerald"]
    assert look.body_text == emerald.body_text
    assert look.highlight_word == emerald.highlight_word
    assert look.background == emerald.background
    assert look.header_text == emerald.header_text
    assert Look.from_dict({"colours": 5, "background": [], "preset": 3}) == NIGHT_GOLD
    assert Look.from_dict({"preset": "no_such"}) == NIGHT_GOLD


def test_values_are_clamped() -> None:
    data = NIGHT_GOLD.to_dict()
    data["background"].update(kind="solid", dim=3.0, blur=-4)
    look = Look.from_dict(data)
    assert look.background.dim == 0.8
    assert look.background.blur == 0.0


def test_image_path_is_stored_relative_and_resolved_back(tmp_path: Path) -> None:
    image = tmp_path / "job.look" / "abc.png"
    look = replace(
        NIGHT_GOLD, background=Background("image", (0, 0, 0, 255), (0, 0, 0, 255), image, 0.35, 2)
    )
    data = look.to_dict(relative_to=tmp_path)
    assert data["background"]["image"] == "job.look/abc.png"
    assert Look.from_dict(data, base_dir=tmp_path).background.image == image


def test_an_image_background_without_a_path_falls_back() -> None:
    data = NIGHT_GOLD.to_dict()
    data["background"]["kind"] = "image"
    data["background"]["image"] = None
    assert Look.from_dict(data).background == NIGHT_GOLD.background


def test_merge_style_keeps_unknown_keys() -> None:
    style = {"future_thing": {"x": 1}, "colours": {"body_text": "#00000000"}}
    merged = merge_style(style, PRESETS["sand"])
    assert merged["future_thing"] == {"x": 1}
    assert merged["colours"] == PRESETS["sand"].to_dict()["colours"]


def test_colour_strings_are_rrggbbaa() -> None:
    assert NIGHT_GOLD.to_dict()["colours"]["highlight_word"] == "#FFD700FF"


def test_is_preset() -> None:
    assert PRESETS["rose"].is_preset
    assert not replace(PRESETS["rose"], body_text=(1, 2, 3, 255)).is_preset


def test_contrast_ratio_known_pairs() -> None:
    assert contrast_ratio((0, 0, 0, 255), (255, 255, 255, 255)) == pytest.approx(21.0)
    assert contrast_ratio((255, 255, 255, 255), (255, 255, 255, 255)) == pytest.approx(1.0)
    assert contrast_ratio((118, 118, 118, 255), (255, 255, 255, 255)) == pytest.approx(
        4.54, abs=0.01
    )


def test_composite_blends_by_alpha() -> None:
    assert composite((255, 255, 255, 0), (10, 20, 30)) == (10, 20, 30)
    assert composite((255, 255, 255, 255), (10, 20, 30)) == (255, 255, 255)


@pytest.mark.parametrize("name", list(PRESETS))
def test_no_preset_warns_on_its_own_background(name: str) -> None:
    look = PRESETS[name]
    c1, c2 = look.background.colour, look.background.colour2
    mean = tuple((c1[i] + c2[i]) // 2 for i in range(3))
    assert readability_warnings(look, mean) == []


def test_unreadable_text_is_named() -> None:
    look = replace(NIGHT_GOLD, body_text=(40, 40, 46, 255))
    assert readability_warnings(look, (10, 10, 12)) == ["body_text"]


def test_colour_fields_cover_every_colour() -> None:
    assert len(COLOUR_FIELDS) == 13

# tests/test_backgrounds.py
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from qurantext.core import backgrounds
from qurantext.core.backgrounds import background_mean, base_layer, clear_cache
from qurantext.core.looks import NIGHT_GOLD, PATTERN_KINDS, PRESETS

CARD = (40, 100, 500, 800)


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def _with_bg(**kw) -> object:
    bg = NIGHT_GOLD.background
    return replace(NIGHT_GOLD, background=replace(bg, **kw))


def test_night_gold_layer_is_the_old_frame_start() -> None:
    """Same pixels as Image.new(COLOUR_BG) + the old draw_rounded_rectangle."""
    from qurantext.core.frame_renderer import COLOUR_BG, COLOUR_CARD, draw_rounded_rectangle

    old = Image.new("RGBA", (540, 960), COLOUR_BG)
    draw_rounded_rectangle(old, CARD, 24, COLOUR_CARD)
    assert base_layer(NIGHT_GOLD, 540, 960, CARD, 24).image.tobytes() == old.tobytes()


@pytest.mark.parametrize("name", list(PRESETS))
@pytest.mark.parametrize("size", [(540, 960), (1920, 1080)])
def test_every_preset_draws_at_each_size(name: str, size: tuple[int, int]) -> None:
    layer = base_layer(PRESETS[name], *size, CARD, 24)
    assert layer.image.size == size and layer.image.mode == "RGBA"
    assert layer.warnings == ()


@pytest.mark.parametrize("kind", PATTERN_KINDS)
def test_patterns_draw_lines_in_colour2(kind: str) -> None:
    look = _with_bg(kind=kind, colour=(0, 0, 0, 255), colour2=(255, 0, 0, 255))
    layer = base_layer(look, 540, 960, (10, 10, 20, 20), 2)
    pixels = np.array(layer.image.convert("RGB"))
    assert (pixels[:, :, 0] > 200).any() and (pixels[:, :, 0] < 50).any()


def test_gradient_runs_top_to_bottom() -> None:
    look = _with_bg(kind="gradient", colour=(0, 0, 0, 255), colour2=(255, 255, 255, 255))
    px = np.array(base_layer(look, 100, 200, (10, 10, 20, 20), 2).image.convert("L"))
    assert px[2, 50] < 20 and px[-3, 50] > 235


def _photo(path: Path, size=(400, 100)) -> Path:
    image = Image.new("RGB", size, (255, 0, 0))
    image.paste((0, 0, 255), (size[0] // 2, 0, size[0], size[1]))  # right half blue
    image.save(path)
    return path


def test_image_is_cover_fitted_not_stretched(tmp_path: Path) -> None:
    look = _with_bg(kind="image", image=_photo(tmp_path / "wide.png"), dim=0.0, blur=0.0)
    px = np.array(base_layer(look, 100, 100, (10, 10, 20, 20), 2).image.convert("RGB"))
    # 400×100 cover-fitted into 100×100 keeps the centre 100×100: half red, half blue.
    assert tuple(px[50, 10]) == (255, 0, 0)
    assert tuple(px[50, 90]) == (0, 0, 255)


def test_dim_darkens_and_blur_softens(tmp_path: Path) -> None:
    photo = _photo(tmp_path / "p.png", (100, 100))
    plain = np.array(
        base_layer(_with_bg(kind="image", image=photo), 100, 100, (10, 10, 20, 20), 2).image
    )
    dimmed = np.array(
        base_layer(
            _with_bg(kind="image", image=photo, dim=0.5), 100, 100, (10, 10, 20, 20), 2
        ).image
    )
    blurred = np.array(
        base_layer(
            _with_bg(kind="image", image=photo, blur=20), 100, 100, (10, 10, 20, 20), 2
        ).image
    )
    assert dimmed[50, 10, 0] < plain[50, 10, 0] * 0.6
    assert 0 < blurred[50, 50, 0] < 255 and 0 < blurred[50, 50, 2] < 255


def test_missing_and_corrupt_images_fall_back_with_a_code(tmp_path: Path) -> None:
    missing = _with_bg(kind="image", image=tmp_path / "gone.png")
    layer = base_layer(missing, 100, 100, (10, 10, 20, 20), 2)
    assert layer.warnings == ("image_missing",)
    fallback = base_layer(
        replace(missing, background=NIGHT_GOLD.background), 100, 100, (10, 10, 20, 20), 2
    )
    assert layer.image.tobytes() == fallback.image.tobytes()

    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    assert base_layer(
        _with_bg(kind="image", image=bad), 100, 100, (10, 10, 20, 20), 2
    ).warnings == ("image_unreadable",)


def test_the_layer_is_built_once_per_look_and_size(tmp_path: Path, monkeypatch) -> None:
    calls = []
    real = backgrounds._draw_background
    monkeypatch.setattr(backgrounds, "_draw_background", lambda *a: calls.append(a) or real(*a))
    look = _with_bg(kind="image", image=_photo(tmp_path / "p.png"))
    for _ in range(50):
        base_layer(look, 200, 200, CARD, 10)
    assert len(calls) == 1


def test_a_replaced_image_is_noticed(tmp_path: Path) -> None:
    import os

    path = _photo(tmp_path / "p.png")
    look = _with_bg(kind="image", image=path)
    first = base_layer(look, 50, 50, (10, 10, 20, 20), 2).image.tobytes()
    Image.new("RGB", (400, 100), (0, 255, 0)).save(path)
    os.utime(path, ns=(1, 10**18))
    assert base_layer(look, 50, 50, (10, 10, 20, 20), 2).image.tobytes() != first


def test_background_mean() -> None:
    look = _with_bg(kind="solid", colour=(10, 20, 30, 255))
    assert background_mean(look, 50, 50) == (10, 20, 30)

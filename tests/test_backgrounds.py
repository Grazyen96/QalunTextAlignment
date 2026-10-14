# tests/test_backgrounds.py
from __future__ import annotations

import os
from dataclasses import fields, replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from qurantext.core import backgrounds
from qurantext.core.backgrounds import background_mean, base_layer, clear_cache
from qurantext.core.looks import COLOUR_FIELDS, NIGHT_GOLD, PATTERN_KINDS, PRESETS, Background

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


# --- I1: an image never fails a render -------------------------------------

_BAD_EXIF = b"Exif\x00\x00XX\x00*\x00\x00\x00\x08"


def _image_layer(path, size=(100, 100)):
    return base_layer(_with_bg(kind="image", image=path), *size, (10, 10, 20, 20), 2)


@pytest.mark.parametrize("fmt", ["PNG", "WEBP"])
def test_malformed_exif_keeps_the_pixels_unrotated(tmp_path: Path, fmt: str) -> None:
    path = tmp_path / f"bad_exif.{fmt.lower()}"
    Image.new("RGB", (100, 100), (255, 0, 0)).save(path, fmt, exif=_BAD_EXIF, lossless=True)
    with pytest.raises(SyntaxError):  # the input really is malformed: "not a TIFF file"
        Image.open(path).getexif()
    layer = _image_layer(path)
    assert layer.warnings == ()
    assert tuple(np.array(layer.image.convert("RGB"))[50, 5]) == (255, 0, 0)


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root reads anything")
def test_an_image_in_an_unreadable_folder_falls_back(tmp_path: Path) -> None:
    folder = tmp_path / "locked"
    folder.mkdir()
    path = _photo(folder / "p.png")
    folder.chmod(0o600)  # no execute: nothing inside can be stat'ed or opened
    try:
        assert _image_layer(path).warnings == ("image_unreadable",)
    finally:
        folder.chmod(0o700)


def test_a_nul_byte_in_the_path_falls_back() -> None:
    assert _image_layer(Path("a\x00b.png")).warnings == ("image_unreadable",)


def test_a_folder_named_as_the_image_falls_back(tmp_path: Path) -> None:
    assert _image_layer(tmp_path).warnings == ("image_missing",)


def test_a_decompression_bomb_falls_back(tmp_path: Path, monkeypatch) -> None:
    path = _photo(tmp_path / "p.png")  # 40,000 px
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # > 2× this raises in Image.open
    assert _image_layer(path).warnings == ("image_unreadable",)


def test_an_image_over_the_decode_cap_falls_back(tmp_path: Path, monkeypatch) -> None:
    path = _photo(tmp_path / "p.png")
    monkeypatch.setattr(backgrounds, "_MAX_DECODE_PIXELS", 39_999)
    assert _image_layer(path).warnings == ("image_unreadable",)


@pytest.mark.parametrize("error", [RuntimeError("boom"), MemoryError(), SyntaxError("x")])
def test_any_pillow_exception_falls_back(tmp_path: Path, monkeypatch, error) -> None:
    path = _photo(tmp_path / "p.png")

    def explode(*_a, **_k):
        raise error

    monkeypatch.setattr(Image, "open", explode)
    assert _image_layer(path).warnings == ("image_unreadable",)


def test_missing_image_on_a_patterned_preset_draws_that_preset(tmp_path: Path) -> None:
    emerald = PRESETS["emerald"]
    missing = replace(emerald, background=_with_bg(kind="image", image=tmp_path / "x").background)
    layer = base_layer(missing, 200, 300, CARD, 10)
    assert layer.warnings == ("image_missing",)
    assert layer.image.tobytes() == base_layer(emerald, 200, 300, CARD, 10).image.tobytes()


# --- photos: orientation, reduced decode, alpha, 16-bit ------------------


def _split(size, first, second, *, vertical_split: bool = True) -> Image.Image:
    image = Image.new("RGB", size, first)
    w, h = size
    image.paste(second, (w // 2, 0, w, h) if vertical_split else (0, h // 2, w, h))
    return image


def test_exif_orientation_is_applied(tmp_path: Path) -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # stored sideways: display rotated 90° clockwise
    path = tmp_path / "o.png"
    _split((40, 20), (255, 0, 0), (0, 0, 255)).save(path, exif=exif.tobytes())
    px = np.array(_image_layer(path, (50, 100)).image.convert("RGB"))
    assert tuple(px[10, 25]) == (255, 0, 0)  # the stored left half is now on top
    assert tuple(px[90, 25]) == (0, 0, 255)


def test_a_rotated_jpeg_decodes_reduced_and_upright(tmp_path: Path, monkeypatch) -> None:
    exif = Image.Exif()
    exif[0x0112] = 6
    path = tmp_path / "o.jpg"
    _split((800, 400), (255, 0, 0), (0, 0, 255)).save(path, exif=exif.tobytes(), quality=95)
    loaded = []
    real_load = Image.Image.load

    def spy(self):
        loaded.append(self.size)
        return real_load(self)

    monkeypatch.setattr(Image.Image, "load", spy)
    px = np.array(_image_layer(path, (50, 100)).image.convert("RGB")).astype(int)
    assert (100, 50) in loaded and (800, 400) not in loaded  # 1/8 scale, never full size
    assert px[10, 25, 0] > 200 and px[10, 25, 2] < 60
    assert px[90, 25, 2] > 200 and px[90, 25, 0] < 60


def test_a_phone_mpo_jpeg_decodes_reduced_too(tmp_path: Path, monkeypatch) -> None:
    """Phones and cameras save multi-picture JPEGs, which Pillow names "MPO"."""
    path = tmp_path / "phone.jpg"
    first = Image.new("RGB", (800, 400), (255, 0, 0))
    first.save(
        path, format="MPO", save_all=True, append_images=[Image.new("RGB", (800, 400), "blue")]
    )
    assert Image.open(path).format == "MPO"
    loaded = []
    real_load = Image.Image.load

    def spy(self):
        loaded.append(self.size)
        return real_load(self)

    monkeypatch.setattr(Image.Image, "load", spy)
    px = np.array(_image_layer(path, (100, 50)).image.convert("RGB")).astype(int)
    assert (100, 50) in loaded and (800, 400) not in loaded  # 1/8 scale, never full size
    assert px[25, 50, 0] > 200 and px[25, 50, 2] < 60  # the first picture, not the second


@pytest.mark.parametrize(
    ("stored", "orientation", "target", "expected"),
    [
        ((800, 400), 1, (100, 100), (200, 100)),
        ((800, 400), 6, (50, 100), (100, 50)),  # axes swap for orientations 5–8
        ((4000, 3000), 1, (1080, 1920), (2560, 1920)),
    ],
)
def test_decode_size_still_covers_the_frame(stored, orientation, target, expected) -> None:
    assert backgrounds._decode_size(stored, orientation, target) == expected


_GROUND = (0, 128, 255, 255)


def _ground_layer(path, **kw):
    look = _with_bg(kind="image", image=path, colour=_GROUND, **kw)
    return base_layer(look, 50, 50, (10, 10, 20, 20), 2)


def test_transparent_pixels_show_the_background_colour(tmp_path: Path) -> None:
    path = tmp_path / "a.png"
    image = Image.new("RGBA", (50, 50), (255, 255, 255, 0))  # transparent left half
    image.paste((255, 0, 0, 255), (25, 0, 50, 50))  # opaque red right half
    image.save(path)
    px = np.array(_ground_layer(path).image.convert("RGB"))
    assert tuple(px[25, 3]) == _GROUND[:3]
    assert tuple(px[25, 46]) == (255, 0, 0)
    dimmed = np.array(_ground_layer(path, dim=0.5).image.convert("RGB"))
    # Dim comes after: the background colour itself is dimmed by half.
    assert np.abs(dimmed[25, 3].astype(int) - np.array(_GROUND[:3]) * 0.5).max() <= 1

    palette = tmp_path / "p.png"
    image = Image.new("P", (50, 50), 0)
    image.putpalette([255, 255, 255] + [0, 0, 0] * 255)
    image.save(palette, transparency=0)
    px = np.array(_ground_layer(palette).image.convert("RGB"))
    assert tuple(px[25, 5]) == _GROUND[:3]


def test_sixteen_bit_grey_is_scaled_not_clipped(tmp_path: Path) -> None:
    path = tmp_path / "g16.png"
    Image.fromarray(np.full((50, 50), 32768, dtype=np.uint16)).save(path)
    px = np.array(_image_layer(path, (50, 50)).image.convert("RGB"))
    assert tuple(px[25, 5]) == (128, 128, 128)


def test_an_embedded_rgb_profile_is_converted_to_srgb(tmp_path: Path) -> None:
    from PIL import ImageCms

    srgb_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    path = tmp_path / "icc.png"
    Image.new("RGB", (50, 50), (200, 100, 50)).save(path, icc_profile=srgb_profile.tobytes())
    px = np.array(_image_layer(path, (50, 50)).image.convert("RGB")).astype(int)
    assert np.abs(px[25, 5] - (200, 100, 50)).max() <= 1  # sRGB → sRGB is the identity
    junk = tmp_path / "junk_icc.png"
    Image.new("RGB", (50, 50), (200, 100, 50)).save(junk, icc_profile=b"not a profile")
    layer = _image_layer(junk, (50, 50))
    assert layer.warnings == ()
    assert tuple(np.array(layer.image.convert("RGB"))[25, 5]) == (200, 100, 50)


# --- I3: the key is what the layer draws ------------------------------------


def _counting(monkeypatch) -> dict[str, int]:
    counts = {"background": 0, "decode": 0}
    real_bg, real_decode = backgrounds._draw_background, backgrounds._decode_photo

    def bg(*a):
        counts["background"] += 1
        return real_bg(*a)

    def decode(*a):
        counts["decode"] += 1
        return real_decode(*a)

    monkeypatch.setattr(backgrounds, "_draw_background", bg)
    monkeypatch.setattr(backgrounds, "_decode_photo", decode)
    return counts


_NOT_IN_THE_LAYER = [f for f in COLOUR_FIELDS if f not in ("card", "card_border")]


@pytest.mark.parametrize("name", _NOT_IN_THE_LAYER)
def test_a_text_colour_change_does_not_rebuild_the_layer(
    tmp_path: Path, monkeypatch, name: str
) -> None:
    counts = _counting(monkeypatch)
    look = _with_bg(kind="image", image=_photo(tmp_path / "p.png"), dim=0.3, blur=2)
    first = base_layer(look, 200, 300, CARD, 10)
    again = base_layer(replace(look, **{name: (255, 0, 255, 255)}), 200, 300, CARD, 10)
    assert again is first
    assert counts == {"background": 1, "decode": 1}


def test_dim_and_card_changes_reuse_the_decoded_photo(tmp_path: Path, monkeypatch) -> None:
    counts = _counting(monkeypatch)
    look = _with_bg(kind="image", image=_photo(tmp_path / "p.png"), dim=0.3, blur=2)
    base_layer(look, 200, 300, CARD, 10)
    base_layer(replace(look, background=replace(look.background, dim=0.6)), 200, 300, CARD, 10)
    base_layer(replace(look, card=(1, 2, 3, 200)), 200, 300, CARD, 10)
    base_layer(replace(look, card_border=(9, 9, 9, 99)), 200, 300, CARD, 10)
    assert counts == {"background": 4, "decode": 1}


def test_dragging_the_blur_slider_never_decodes_the_photo_again(
    tmp_path: Path, monkeypatch
) -> None:
    counts = _counting(monkeypatch)
    look = _with_bg(kind="image", image=_photo(tmp_path / "p.png"), dim=0.3, blur=0)
    layers = [
        base_layer(replace(look, background=replace(look.background, blur=b)), 200, 300, CARD, 10)
        for b in (0, 1, 2, 4, 8, 16, 20)
    ]
    assert counts == {"background": 7, "decode": 1}
    assert len({layer.image.tobytes() for layer in layers}) == 7  # each blur still shows


def test_blur_is_applied_at_frame_size_after_the_fit(tmp_path: Path) -> None:
    """Same pixels as blurring the fitted, unblurred layer: the source is never blurred."""
    from PIL import ImageFilter

    photo = _photo(tmp_path / "p.png", (100, 100))
    sharp = base_layer(_with_bg(kind="image", image=photo), 100, 100, (0, 0, 1, 1), 0)
    blurred = base_layer(_with_bg(kind="image", image=photo, blur=20), 100, 100, (0, 0, 1, 1), 0)
    clear_cache()
    expected = backgrounds._draw_background(
        _with_bg(kind="image", image=photo).background, 100, 100, None
    ).filter(ImageFilter.GaussianBlur(20 * 100 / 1000))
    assert sharp.image.tobytes() != blurred.image.tobytes()
    assert np.array_equal(np.array(blurred.image)[50:, 50:], np.array(expected)[50:, 50:])


def _key_variants(tmp_path: Path) -> dict[str, tuple]:
    """One change per field of the layer key; each must change the pixels."""
    photo = _photo(tmp_path / "p.png")
    other = _photo(tmp_path / "q.png", (100, 400))
    look = _with_bg(kind="image", image=photo, dim=0.2, blur=1)
    bg = look.background
    args = (look, 200, 300, CARD, 10)
    missing = replace(look, background=replace(bg, image=tmp_path / "gone.png"))
    return {
        "base": args,
        "background.kind": (replace(look, background=replace(bg, kind="solid")), *args[1:]),
        "background.colour": (
            replace(look, background=replace(NIGHT_GOLD.background, colour=(9, 99, 9, 255))),
            *args[1:],
        ),
        "background.colour2": (
            replace(look, background=Background("gradient", (0, 0, 0, 255), (250, 0, 0, 255))),
            *args[1:],
        ),
        "background.image": (replace(look, background=replace(bg, image=other)), *args[1:]),
        "background.dim": (replace(look, background=replace(bg, dim=0.7)), *args[1:]),
        "background.blur": (replace(look, background=replace(bg, blur=15)), *args[1:]),
        "card": (replace(look, card=(250, 0, 0, 255)), *args[1:]),
        "card_border": (replace(look, card_border=(0, 250, 0, 255)), *args[1:]),
        "width": (look, 210, 300, CARD, 10),
        "height": (look, 200, 310, CARD, 10),
        "card_box": (look, 200, 300, (20, 30, 150, 250), 10),
        "radius": (look, 200, 300, CARD, 40),
        # base_preset only matters when the photo fails: compare two fallbacks.
        "base_preset.night": (missing, *args[1:]),
        "base_preset.emerald": (replace(missing, base_preset="emerald"), *args[1:]),
    }


def test_every_field_in_the_key_changes_the_layer(tmp_path: Path) -> None:
    variants = _key_variants(tmp_path)
    pixels = {name: base_layer(*args).image for name, args in variants.items()}
    base = pixels["base"]
    for name, image in pixels.items():
        if name in ("base", "base_preset.emerald"):
            continue
        assert image.size != base.size or image.tobytes() != base.tobytes(), name
    assert pixels["base_preset.night"].tobytes() != pixels["base_preset.emerald"].tobytes()


def test_the_key_fields_are_the_ones_the_test_covers() -> None:
    """A new Background field must be added to the key test above."""
    assert [f.name for f in fields(Background)] == [
        "kind",
        "colour",
        "colour2",
        "image",
        "dim",
        "blur",
    ]


# --- I2: one lock around the caches -----------------------------------------


def test_the_caches_survive_concurrent_use() -> None:
    import sys
    import threading

    looks = [_with_bg(kind="solid", colour=(i, i, i, 255)) for i in range(3)]
    sizes = [(8 + i, 8 + i) for i in range(7)]
    errors: list[BaseException] = []

    def hammer(seed: int) -> None:
        try:
            for i in range(3000):
                look = looks[(i + seed) % len(looks)]
                w, h = sizes[(i * 3 + seed) % len(sizes)]
                base_layer(look, w, h, (1, 1, 4, 4), 1)
                if i % 7 == 0:
                    background_mean(look, w, h)
        except BaseException as error:  # noqa: BLE001 — collected for the assert
            errors.append(error)

    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=hammer, args=(s,)) for s in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        sys.setswitchinterval(interval)
    assert errors == []
    assert len(backgrounds._cache) <= backgrounds._CACHE_SIZE


# --- M6: the LRU of 4, the mean, the layer is never drawn on ----------------


def test_the_cache_keeps_the_four_most_recent_layers(monkeypatch) -> None:
    counts = _counting(monkeypatch)
    sizes = [(20 + i, 20) for i in range(5)]
    for size in sizes[:4]:
        base_layer(NIGHT_GOLD, *size, (1, 1, 4, 4), 1)
    base_layer(NIGHT_GOLD, *sizes[0], (1, 1, 4, 4), 1)  # touch the oldest: now the newest
    base_layer(NIGHT_GOLD, *sizes[4], (1, 1, 4, 4), 1)  # evicts sizes[1]
    assert counts["background"] == 5
    base_layer(NIGHT_GOLD, *sizes[0], (1, 1, 4, 4), 1)
    assert counts["background"] == 5  # still cached
    base_layer(NIGHT_GOLD, *sizes[1], (1, 1, 4, 4), 1)
    assert counts["background"] == 6  # was evicted


def test_background_mean_is_cached_and_shares_the_photo(tmp_path: Path, monkeypatch) -> None:
    counts = _counting(monkeypatch)
    look = _with_bg(kind="image", image=_photo(tmp_path / "p.png"))
    layer = base_layer(look, 200, 300, CARD, 10)
    assert background_mean(look, 200, 300) == layer.mean
    assert background_mean(look, 200, 300) == layer.mean
    assert counts == {"background": 1, "decode": 1}


def test_rendering_never_draws_on_the_cached_layer() -> None:
    from qurantext.config.paths import DEFAULT_FONT_PATH
    from qurantext.core.frame_renderer import frame_base_layer, render_frame_pillow

    look = PRESETS["sand"]
    layer = frame_base_layer(look, 540, 960, reserve_caption_band=True)
    before = layer.image.tobytes()
    render_frame_pillow(
        0.0, None, 540, 960, DEFAULT_FONT_PATH, title="قالون", caption_text="بسم", look=look
    )
    assert frame_base_layer(look, 540, 960, reserve_caption_band=True) is layer
    assert layer.image.tobytes() == before


# -- tiles for the Look panel ------------------------------------------------------


def test_a_tile_has_the_asked_size_for_every_kind(tmp_path) -> None:
    from qurantext.core.backgrounds import tile_image
    from qurantext.core.looks import BACKGROUND_KINDS

    for kind in BACKGROUND_KINDS:
        if kind == "image":
            continue
        bg = Background(kind, (20, 30, 40, 255), (200, 200, 200, 255))
        assert tile_image(bg, 56, 36).size == (56, 36), kind


def test_a_solid_tile_is_its_colour_and_a_pattern_tile_is_not() -> None:
    from qurantext.core.backgrounds import tile_image

    solid = tile_image(Background("solid", (20, 30, 40, 255), (20, 30, 40, 255)), 56, 36)
    assert solid.convert("RGB").getpixel((28, 18)) == (20, 30, 40)
    stars = tile_image(Background("pattern_stars", (20, 30, 40, 255), (230, 200, 90, 255)), 56, 36)
    colours = np.unique(np.asarray(stars.convert("RGB")).reshape(-1, 3), axis=0)
    assert len(colours) > 1, "the lines reach the small tile"


def test_a_tile_ignores_dim_and_blur() -> None:
    from qurantext.core.backgrounds import tile_image

    plain = Background("solid", (200, 100, 50, 255), (200, 100, 50, 255))
    dimmed = replace(plain, dim=0.8, blur=20.0)
    assert tile_image(dimmed, 8, 8).tobytes() == tile_image(plain, 8, 8).tobytes()


def test_an_image_tile_shows_the_photo_and_a_gone_one_raises(tmp_path) -> None:
    from qurantext.core.backgrounds import tile_image

    photo = tmp_path / "p.png"
    Image.new("RGB", (40, 40), (250, 10, 10)).save(photo)
    bg = Background("image", (0, 0, 0, 255), (0, 0, 0, 255), image=photo)
    assert tile_image(bg, 16, 16).convert("RGB").getpixel((8, 8)) == (250, 10, 10)
    photo.unlink()
    with pytest.raises(ValueError, match="image_missing"):
        tile_image(bg, 16, 16)

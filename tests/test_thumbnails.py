# tests/test_thumbnails.py
"""A job's thumbnail: the first card at the job's look, cached by path, time and style."""

from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from qurantext.jobs import thumbnails
from qurantext.jobs.project import Project, load_project, save_project

_CARD = {
    "surah_num": 25, "surah_name": "الفرقان", "from_ayah": 7, "to_ayah": 7,
    "start_time": 1.0, "end_time": 4.0,
    "full_text": "وَقَالُوا مَالِ هَٰذَا الرَّسُولِ يَأْكُلُ الطَّعَامَ",
    "word_timings": [{"word": "وَقَالُوا", "start": 1.0, "end": 2.0}],
}  # fmt: skip


def _project(tmp_path: Path, *, cards=None, style=None, preset="social") -> Project:
    project = Project(
        audio=tmp_path / "a.mp3",
        mode="recitation",
        cards=cards if cards is not None else [dict(_CARD)],
        style=style or {},
        export={"preset": preset, "subtitles": "burn"},
    )
    path = tmp_path / "a_recitation.qalun.json"
    save_project(project, path)
    return load_project(path)


def test_a_portrait_job_gets_a_portrait_png_96_tall(tmp_path) -> None:
    png = thumbnails.thumbnail_for(_project(tmp_path), tmp_path / "cache")
    assert png is not None and png.is_file()
    with Image.open(png) as image:
        assert image.size == (54, 96)


def test_a_landscape_job_gets_a_landscape_png_96_wide(tmp_path) -> None:
    png = thumbnails.thumbnail_for(_project(tmp_path, preset="high"), tmp_path / "cache")
    with Image.open(png) as image:
        assert image.size == (96, 54)


def test_the_key_follows_the_file_time_and_the_style_only(tmp_path, monkeypatch) -> None:
    project = _project(tmp_path)
    first = thumbnails.cache_key(project)
    assert thumbnails.cache_key(project) == first  # time passing changes nothing
    project.style = {"preset": "emerald"}
    assert thumbnails.cache_key(project) != first
    project.style = {}
    later = time.time() + 100
    import os

    os.utime(project.path, (later, later))
    assert thumbnails.cache_key(project) != first


def test_a_hit_does_not_render_again(tmp_path, monkeypatch) -> None:
    project = _project(tmp_path)
    calls = []
    real = thumbnails.render_frame_pillow

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(thumbnails, "render_frame_pillow", counting)
    thumbnails.thumbnail_for(project, tmp_path / "cache")
    thumbnails.thumbnail_for(project, tmp_path / "cache")
    assert len(calls) == 1


def test_no_cards_means_no_thumbnail(tmp_path) -> None:
    assert thumbnails.thumbnail_for(_project(tmp_path, cards=[]), tmp_path / "cache") is None


def test_a_renderer_failure_means_no_thumbnail_and_no_exception(tmp_path, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("no font")

    monkeypatch.setattr(thumbnails, "render_frame_pillow", boom)
    assert thumbnails.thumbnail_for(_project(tmp_path), tmp_path / "cache") is None


def test_a_missing_look_image_still_yields_a_thumbnail(tmp_path) -> None:
    """Review Focus 2: the base layer falls back when the image is gone."""
    style = {"preset": "night_gold", "background": {"kind": "image", "image": "gone.jpg"}}
    png = thumbnails.thumbnail_for(_project(tmp_path, style=style), tmp_path / "cache")
    assert png is not None


def test_no_cache_dir_means_no_thumbnail(tmp_path) -> None:
    png = thumbnails.thumbnail_for(_project(tmp_path), None)
    assert png is None  # nothing to keep it in: the row draws the tile


def test_background_is_the_looks_frame_colour(tmp_path) -> None:
    project = _project(tmp_path, style={"preset": "sand"})
    from qurantext.core.looks import PRESETS

    assert thumbnails.background_for(project) == PRESETS["sand"].frame_bg[:3]


def test_the_renderer_gets_the_card_as_the_video_draws_it(tmp_path, monkeypatch) -> None:
    """The renderer reads the enriched fields only; a raw card drew an empty panel."""
    seen = []
    real = thumbnails.render_frame_pillow

    def spying(at, card, *args, **kwargs):
        seen.append((at, card))
        return real(at, card, *args, **kwargs)

    monkeypatch.setattr(thumbnails, "render_frame_pillow", spying)
    thumbnails.thumbnail_for(_project(tmp_path), tmp_path / "cache")
    ((at, card),) = seen
    assert card["_display_text"] == _CARD["full_text"]
    assert card["_word_timings"] and card["_start_time"] == 1.0
    assert at == 2.5  # halfway into the first card, as the preview takes it


def test_the_png_shows_more_than_one_colour(tmp_path) -> None:
    png = thumbnails.thumbnail_for(_project(tmp_path), tmp_path / "cache")
    with Image.open(png) as image:
        colours = image.convert("RGB").getcolors(maxcolors=1 << 16)
    assert colours is not None and len(colours) > 1


def test_the_card_s_text_is_drawn(tmp_path) -> None:
    """The same look with the ayah's text has more ink than with a blank body."""
    from qurantext.core.video_common import validated_matches

    with_text = thumbnails.thumbnail_for(_project(tmp_path), tmp_path / "cache")
    blank_dir = tmp_path / "blank"
    blank_dir.mkdir()
    blank_card = dict(_CARD, full_text=" ", text="ـ")  # a tatweel: valid, draws next to nothing
    assert validated_matches([blank_card], bridge_gaps=False)
    blank = thumbnails.thumbnail_for(_project(blank_dir, cards=[blank_card]), tmp_path / "cache")

    def colours(png) -> int:
        with Image.open(png) as image:
            return len(image.convert("RGB").getcolors(maxcolors=1 << 16))

    assert colours(with_text) > colours(blank)


def test_a_card_the_video_would_not_show_means_no_thumbnail(tmp_path) -> None:
    broken = {k: v for k, v in _CARD.items() if k != "full_text"}  # no text: dropped
    assert thumbnails.thumbnail_for(_project(tmp_path, cards=[broken]), tmp_path / "cache") is None


def test_the_key_carries_its_version(tmp_path, monkeypatch) -> None:
    """A PNG cached before the card's text was drawn is never served again."""
    project = _project(tmp_path)
    now = thumbnails.cache_key(project)
    monkeypatch.setattr(thumbnails, "_KEY_VERSION", thumbnails._KEY_VERSION + 1)
    assert thumbnails.cache_key(project) != now


def test_the_png_is_written_whole_and_leaves_no_part_file(tmp_path) -> None:
    png = thumbnails.thumbnail_for(_project(tmp_path), tmp_path / "cache")
    assert [p.name for p in png.parent.iterdir()] == [png.name]


def test_thumbnail_image_draws_at_the_asked_size_with_the_given_look(tmp_path) -> None:
    from qurantext.core.looks import PRESETS

    project = _project(tmp_path)
    image = thumbnails.thumbnail_image(project, PRESETS["ocean"], (56, 99))
    assert image is not None and image.size == (56, 99)
    corner = image.convert("RGB").getpixel((2, 2))
    # The renderer shades the frame a hair (a vignette), so the corner is the colour within 2.
    assert all(
        abs(got - want) <= 2
        for got, want in zip(corner, PRESETS["ocean"].frame_bg[:3], strict=True)
    )


def test_thumbnail_image_is_none_for_no_cards_or_a_failing_renderer(tmp_path, monkeypatch) -> None:
    from qurantext.core.looks import NIGHT_GOLD

    assert thumbnails.thumbnail_image(_project(tmp_path, cards=[]), NIGHT_GOLD, (54, 96)) is None

    def boom(*a, **k):
        raise RuntimeError("no renderer")

    monkeypatch.setattr(thumbnails, "render_frame_pillow", boom)
    assert thumbnails.thumbnail_image(_project(tmp_path), NIGHT_GOLD, (54, 96)) is None

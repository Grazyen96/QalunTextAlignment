import json
import shutil
import subprocess

import numpy as np
import pytest

from qurantext.core.looks import NIGHT_GOLD, PRESETS
from qurantext.core.title_cards import (
    STYLES,
    IntroSpec,
    OutroSpec,
    qr_box,
    render_title_clip,
    render_title_frame,
)

URL = "https://example.org/dars?utm_campaign=qalun-025&utm_source=youtube&utm_medium=video&utm_content=outro-qr"
OUTRO = OutroSpec("جزاكم الله خيرًا", "example.org/dars", URL)
INTRO = IntroSpec("دروس الشيخ", "سورة الفرقان · الآيات ٤٤–٤٩")


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("spec", [INTRO, OUTRO])
def test_frames_draw_text_by_the_middle(style, spec):
    from dataclasses import replace

    spec = replace(spec, style=style)
    base = np.array(render_title_frame(spec, NIGHT_GOLD, 960, 540, 0.0))
    mid = np.array(render_title_frame(spec, NIGHT_GOLD, 960, 540, spec.seconds / 2))
    assert (np.abs(mid.astype(int) - base.astype(int)) > 40).sum() > 500


@pytest.mark.parametrize("look", [NIGHT_GOLD, PRESETS["ink_on_paper"], PRESETS["sand"]])
@pytest.mark.parametrize("size", [(1080, 1920), (1920, 1080)])
def test_qr_decodes_on_light_and_dark_looks(look, size):
    cv2 = pytest.importorskip("cv2")
    frame = np.array(render_title_frame(OUTRO, look, *size, OUTRO.seconds / 2))
    data, *_ = cv2.QRCodeDetector().detectAndDecode(frame[:, :, ::-1])
    assert data == URL


def test_qr_is_steady_for_most_of_the_outro():
    box = qr_box(OUTRO, 960, 540)
    steady = [
        np.array(render_title_frame(OUTRO, NIGHT_GOLD, 960, 540, t).crop(box))
        for t in (OUTRO.seconds * f for f in (0.16, 0.5, 0.84))
    ]
    assert all((a == steady[0]).all() for a in steady)


def test_layout_fits_portrait_and_landscape():
    for w, h in ((1080, 1920), (1920, 1080)):
        x0, y0, x1, y1 = qr_box(OUTRO, w, h)
        assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h
        assert (x1 - x0) >= 0.25 * min(w, h)


def test_long_text_stays_inside_the_panel():
    long = IntroSpec("دروس " * 30, "سورة الفرقان · الآيات ٤٤–٤٩")
    img = np.array(render_title_frame(long, NIGHT_GOLD, 960, 540, long.seconds / 2))
    # Nothing is drawn in the outer 3 % margin, which lies outside the panel.
    edge = img[:, : int(960 * 0.03)]
    base = np.array(render_title_frame(long, NIGHT_GOLD, 960, 540, 0.0))[:, : int(960 * 0.03)]
    assert (edge == base).all()


def test_a_latin_name_is_drawn_not_boxes():
    from dataclasses import replace

    a = np.array(
        render_title_frame(replace(INTRO, name="Dars of Sheikh Ahmad"), NIGHT_GOLD, 960, 540, 2.5)
    )
    b = np.array(
        render_title_frame(replace(INTRO, name="Dars of Sheikh Ahmed"), NIGHT_GOLD, 960, 540, 2.5)
    )
    assert (a != b).any()  # a different letter draws differently, so the glyphs are real


def test_cache_key_changes_with_every_field():
    from dataclasses import replace

    keys = {
        OUTRO.cache_key(),
        replace(OUTRO, qr_url=URL + "x").cache_key(),
        replace(OUTRO, style="rise").cache_key(),
        replace(OUTRO, seconds=7).cache_key(),
    }
    assert len(keys) == 4


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs FFmpeg")
def test_clip_is_silent_and_exact(tmp_path):
    out = render_title_clip(INTRO, NIGHT_GOLD, tmp_path / "i.mp4", width=640, height=360, fps=25)
    probe = json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(out)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    streams = probe["streams"]
    assert [s["codec_type"] for s in streams] == ["video"]
    assert (streams[0]["width"], streams[0]["height"], streams[0]["r_frame_rate"]) == (
        640,
        360,
        "25/1",
    )
    assert abs(float(probe["format"]["duration"]) - 5.0) <= 1 / 25 + 1e-6
    assert not list(tmp_path.glob("*.part*"))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs FFmpeg")
def test_cancel_leaves_nothing(tmp_path):
    from qurantext.utils.progress import CancelToken, JobCancelled

    token = CancelToken()
    token.cancel()
    with pytest.raises(JobCancelled):
        render_title_clip(
            INTRO, NIGHT_GOLD, tmp_path / "i.mp4", width=640, height=360, fps=25, cancel=token
        )
    assert not list(tmp_path.iterdir())


def test_qr_modules_are_always_darker_than_their_ground():
    """Phone scanners, and OpenCV, expect dark modules on a light ground: an inverted
    code (Night gold's white body text on its dark card) does not read."""
    from qurantext.core.looks import contrast_ratio
    from qurantext.core.title_cards import qr_colours

    black = (0, 0, 0)
    for look in PRESETS.values():
        dark, light = qr_colours(look)
        assert contrast_ratio(dark, black) < contrast_ratio(light, black)
        assert contrast_ratio(dark, light) >= 4.5


@pytest.mark.parametrize("bad", [{"style": "spin"}, {"seconds": 2.9}, {"seconds": 10.5}])
def test_specs_refuse_unknown_styles_and_lengths(bad):
    from dataclasses import replace

    with pytest.raises(ValueError):
        replace(INTRO, **bad)


def test_a_preview_draws_a_small_code_but_a_clip_refuses_it(tmp_path):
    """A 320 px thumbnail is never scanned, so it may draw modules under 4 px; a
    clip that small would put an unreadable code in front of viewers."""
    frame = render_title_frame(OUTRO, NIGHT_GOLD, 320, 180, OUTRO.seconds / 2)
    assert frame.size == (320, 180)
    with pytest.raises(ValueError):
        render_title_clip(OUTRO, NIGHT_GOLD, tmp_path / "o.mp4", width=320, height=180, fps=25)
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs FFmpeg")
def test_cancel_while_writing_kills_ffmpeg_and_leaves_nothing(tmp_path):
    from qurantext.utils.progress import CancelToken, JobCancelled

    token = CancelToken()
    seen = []

    def progress(event):
        seen.append(event.fraction)
        if len(seen) == 3:
            token.cancel()

    with pytest.raises(JobCancelled):
        render_title_clip(
            INTRO,
            NIGHT_GOLD,
            tmp_path / "i.mp4",
            width=320,
            height=180,
            fps=25,
            progress=progress,
            cancel=token,
        )
    assert len(seen) < 10
    assert not list(tmp_path.iterdir())

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
INTRO = IntroSpec("دروس الشيخ", "سورة الفرقان، الآيات ٤٤–٤٩")


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
    long = IntroSpec("دروس " * 30, "سورة الفرقان، الآيات ٤٤–٤٩")
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


# --- The fix wave (phase-1 review I2-I4, m1, m2, m6, m11; the title-size ruling) -----

from dataclasses import replace  # noqa: E402

from qurantext.core.title_cards import _layout, _state, missing_glyphs  # noqa: E402
from qurantext.core.tracked_link import readable_link, tracked_link  # noqa: E402

#: A typical tracked link: 143 characters, 49 modules a side.
TYPICAL = tracked_link(
    "https://example.org/dars/tafsir-al-furqan?ref=channel12",
    platform="youtube",
    campaign="qalun-025-044-049",
)
LONG_NAME = "دروس الشيخ " * 12
LONG_PHRASE = "سبحانك اللهم وبحمدك، أشهد أن لا إله إلا أنت، أستغفرك وأتوب إليك " * 3


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _inside(inner, outer):
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and (inner[3] <= outer[3])
    )


@pytest.mark.parametrize(
    "size", [(1080, 1920), (1920, 1080), (1080, 1080), (1080, 1350), (960, 540), (1280, 720)]
)
@pytest.mark.parametrize(
    "spec",
    [
        IntroSpec(LONG_NAME, LONG_NAME),
        OutroSpec(LONG_PHRASE, "example.org/" + "dars/" * 30, URL),
        OutroSpec(LONG_PHRASE, readable_link(TYPICAL), TYPICAL),
        OutroSpec("جزاكم الله خيرًا", "example.org/d", URL + "&x=" + "a" * 600),
    ],
    ids=["long-intro", "long-link-text", "typical", "600-char-link"],
)
def test_text_and_qr_stay_inside_the_panel_and_apart(spec, size):
    layout = _layout(spec, *size)
    boxes = [p.box for p in layout.texts]
    assert boxes, "something is drawn"
    for box in boxes + ([layout.qr_box] if layout.qr_box else []):
        assert _inside(box, layout.panel), (box, layout.panel)
    for i, box in enumerate(boxes):
        if layout.qr_box:
            assert not _overlap(box, layout.qr_box), (box, layout.qr_box)
        for other in boxes[i + 1 :]:
            assert not _overlap(box, other)


@pytest.mark.parametrize("size", [(960, 540), (1080, 1920), (1920, 1080)])
def test_long_text_is_fitted_not_cut_at_the_panel_edge(size):
    """Text is drawn on a panel-sized layer, so text that was never fitted would be cut
    at the panel's edge rather than reach the frame's margin. Every pixel the text
    changes must lie inside the panel's padding."""
    long = IntroSpec("دروس " * 30, "Dars of Sheikh " * 20)
    w, h = size
    mid = np.array(render_title_frame(long, NIGHT_GOLD, w, h, long.seconds / 2)).astype(int)
    bare = np.array(render_title_frame(long, NIGHT_GOLD, w, h, 0.0)).astype(int)
    ys, xs = np.nonzero(np.abs(mid - bare).sum(axis=2) > 0)
    x0, y0, x1, y1 = _layout(long, w, h).panel
    inset = round(0.02 * min(w, h))
    assert xs.min() >= x0 + inset and xs.max() < x1 - inset
    assert ys.min() >= y0 + inset and ys.max() < y1 - inset


def _ink_components(spec) -> int:
    cv2 = pytest.importorskip("cv2")
    mid = np.array(render_title_frame(spec, NIGHT_GOLD, 960, 540, spec.seconds / 2).convert("L"))
    bare = np.array(render_title_frame(spec, NIGHT_GOLD, 960, 540, 0.0).convert("L"))
    ink = (np.abs(mid.astype(int) - bare.astype(int)) > 60).astype(np.uint8)
    count, _ = cv2.connectedComponents(ink)
    return count - 1


def test_arabic_is_shaped_into_joined_forms():
    """«محمد» shaped is one joined stroke; its letters held apart (ZWNJ) are four."""
    assert _ink_components(IntroSpec("محمد", "")) <= 2
    assert _ink_components(IntroSpec("‌".join("محمد"), "")) >= 4


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("spec", [INTRO, OUTRO])
def test_every_style_ends_on_the_bare_look(style, spec):
    styled = replace(spec, style=style)
    end = np.array(render_title_frame(styled, NIGHT_GOLD, 960, 540, styled.seconds))
    bare = np.array(render_title_frame(replace(spec, style="fade"), NIGHT_GOLD, 960, 540, 0.0))
    assert (end == bare).all()


@pytest.mark.parametrize("fps", [17, 24, 25, 30, 50, 60])
def test_qr_is_fully_drawn_in_at_least_70_percent_of_frames(fps):
    for tenths in range(30, 101, 5):
        spec = replace(OUTRO, seconds=tenths / 10)
        frames = round(spec.seconds * fps)
        full = sum(_state(spec, 540, i / fps)[2] >= 1 for i in range(frames))
        assert full >= 0.70 * frames, (spec.seconds, fps, full, frames)


def test_qr_modules_are_whole_pixels_of_at_least_five():
    for w, h in ((960, 540), (1280, 720), (1920, 1080), (1080, 1920)):
        for url in (URL, TYPICAL):
            spec = replace(OUTRO, qr_url=url)
            x0, _, x1, _ = qr_box(spec, w, h)
            from qurantext.core.qr import qr_modules

            span = qr_modules(url) + 8
            assert (x1 - x0) % span == 0 and (x1 - x0) // span >= 5
            assert x1 - x0 >= 0.25 * min(w, h)


def _decode_either(cv2, frame) -> str:
    """The code's text by OpenCV's classic detector, or its ArUco-based one if present."""
    data, *_ = cv2.QRCodeDetector().detectAndDecode(frame)
    if not data and hasattr(cv2, "QRCodeDetectorAruco"):
        data, *_ = cv2.QRCodeDetectorAruco().detectAndDecode(frame)
    return data


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs FFmpeg")
@pytest.mark.parametrize(
    "size, look",
    [((1920, 1080), PRESETS["sand"]), ((1080, 1920), NIGHT_GOLD)],
    ids=["16x9", "9x16"],
)
def test_qr_survives_a_480p_and_360p_transcode(tmp_path, size, look):
    """WhatsApp, Telegram and a phone's YouTube player show the video at 480p or less.
    The code is read back from the real clip after such a transcode, scaled up again
    as a full-screen player does. 480p is the gate. At 360p a module is 1.7 px, at the
    detector's own limit, so a miss there is reported as a warning, not a failure."""
    import warnings

    cv2 = pytest.importorskip("cv2")
    w, h = size
    spec = OutroSpec("جزاكم الله خيرًا", readable_link(TYPICAL), TYPICAL, seconds=3)
    clip = render_title_clip(spec, look, tmp_path / "o.mp4", width=w, height=h, fps=10)
    for short in (480, 360):
        small = tmp_path / f"o{short}.mp4"
        scale = f"scale=-2:{short}" if w > h else f"scale={short}:-2"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf", scale,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", str(small)],
            check=True,
        )  # fmt: skip
        capture = cv2.VideoCapture(str(small))
        capture.set(cv2.CAP_PROP_POS_FRAMES, 15)
        ok, frame = capture.read()
        capture.release()
        assert ok
        frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_LINEAR)
        data = _decode_either(cv2, frame)
        if short == 480:
            assert data == TYPICAL
        elif data != TYPICAL:
            warnings.warn(f"QR code not read after a 360p transcode at {w}x{h}", stacklevel=1)


def test_the_link_text_is_left_to_right_and_the_outro_uses_the_spec_colours():
    spec = OutroSpec("جزاكم الله خيرًا", "مثال.com/دروس", URL)
    texts = {p.colour: p.block for p in _layout(spec, 1920, 1080).texts}
    assert set(texts) == {"body_text", "placeholder_text"}
    assert texts["placeholder_text"].direction == "ltr"
    assert texts["body_text"].direction == "rtl"


@pytest.mark.parametrize("size", [(1080, 1920), (1920, 1080), (960, 540)])
def test_the_title_is_smaller_than_the_name(size):
    name, title = _layout(INTRO, *size).texts
    assert title.block.font.size <= round(0.7 * name.block.font.size)


def test_reveal_direction_is_part_of_the_spec():
    sand = PRESETS["sand"]
    rtl = replace(OUTRO, style="reveal")
    ltr = replace(rtl, rtl=False)
    assert rtl.cache_key() != ltr.cache_key()
    # A third of the way in, the left of the panel is uncovered only when reading starts left.
    a = np.array(render_title_frame(ltr, sand, 960, 540, 0.3))
    b = np.array(render_title_frame(rtl, sand, 960, 540, 0.3))
    assert tuple(b[270, 200]) == sand.frame_bg[:3] != tuple(a[270, 200])
    assert (np.array(render_title_frame(rtl, sand, 960, 540, 0.3, rtl=False)) == a).all()


def test_missing_glyphs_names_what_amiri_cannot_draw():
    assert missing_glyphs("Dars دروس، ٤٤–٤٩ … café \u200f") == ""
    assert missing_glyphs("Дars ব😀 Д") == "Дব😀"


BASMALA = "\ufdfd"


@pytest.mark.parametrize(
    "spec",
    [
        IntroSpec(f"{BASMALA} دروس الشيخ", "سورة الفرقان"),
        OutroSpec(f"{BASMALA}", "example.org/d", URL),
    ],
    ids=["name", "phrase"],
)
@pytest.mark.parametrize("size", [(1920, 1080), (1080, 1920), (320, 180)])
def test_the_basmala_ligature_is_drawn_spelled_out(spec, size):
    """Amiri cannot rasterise ﷽ (U+FDFD) at any size: FreeType says "raster overflow".
    The words it stands for are drawn instead, so the frame renders and has text."""
    mid = np.array(render_title_frame(spec, NIGHT_GOLD, *size, spec.seconds / 2))
    bare = np.array(render_title_frame(spec, NIGHT_GOLD, *size, 0.0))
    assert (np.abs(mid.astype(int) - bare.astype(int)) > 40).sum() > 50
    drawn = " ".join(line for p in _layout(spec, *size).texts for line in p.block.lines)
    assert "\ufdfd" not in drawn and "بسم" in drawn


def test_a_font_failure_is_a_clear_error_not_a_crash(monkeypatch):
    from qurantext.core import title_cards

    def broken(*args, **kwargs):
        raise OSError("raster overflow")

    monkeypatch.setattr(title_cards, "fit_font_size", broken)
    spec = IntroSpec("اسم لم يقس بعد", "")
    with pytest.raises(title_cards.TitleTextError) as caught:
        render_title_frame(spec, NIGHT_GOLD, 960, 540, 2.5)
    assert isinstance(caught.value, ValueError) and "اسم لم يقس بعد" in str(caught.value)


def test_glyph_checks_survive_glyphs_the_font_cannot_rasterise():
    from qurantext.config.paths import TEXT_FONT_PATH
    from qurantext.core.title_cards import _has_glyph

    assert _has_glyph(TEXT_FONT_PATH, BASMALA) is False  # raises "raster overflow" inside
    # The renderer spells it out, so the dialog has nothing to warn about.
    assert missing_glyphs(f"{BASMALA} دروس") == ""


def test_a_tiny_preview_keeps_a_huge_code_inside_the_frame():
    """A 320×180 thumbnail of a link near the QR code's limit (about 2,300 characters)."""
    base = "https://example.org/d?x="
    huge = tracked_link(base + "a" * 2190, platform="youtube", campaign="c")
    assert len(huge) > 2250
    spec = replace(OUTRO, qr_url=huge)
    for w, h in ((320, 180), (180, 320)):
        x0, y0, x1, y1 = qr_box(spec, w, h)
        assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h
        assert _inside((x0, y0, x1, y1), _layout(spec, w, h).panel)
        assert render_title_frame(spec, NIGHT_GOLD, w, h, 3.0).size == (w, h)


@pytest.mark.parametrize("size", [(1080, 1920), (1920, 1080), (960, 540)])
def test_a_short_name_shrinks_rather_than_leave_a_word_alone(size):
    """«دروس الشيخ أحمد» stays on one line, smaller, rather than «أحمد» under the rest;
    so does the title under it."""
    spec = IntroSpec("دروس الشيخ أحمد", "سورة الفرقان، الآيات ٤٤–٤٩")
    name, title = _layout(spec, *size).texts
    assert name.block.lines == ("دروس الشيخ أحمد",)
    assert title.block.lines == ("سورة الفرقان، الآيات ٤٤–٤٩",)
    start = round(0.09 * size[1])
    assert name.block.font.size >= round(0.7 * start) - 1, "no smaller than 70 % of its start"


def test_text_that_needs_more_than_that_still_wraps_at_the_larger_size():
    """Below 70 % of the start size one line is not worth it: two lines, larger."""
    from qurantext.config.paths import TEXT_FONT_BOLD_PATH
    from qurantext.core.title_cards import _fit_text

    text = "دروس الشيخ أحمد في تفسير سورة الفرقان"
    width, start = 600, 120
    one = _fit_text(text, TEXT_FONT_BOLD_PATH, width, 400, start, 12, 1)
    assert len(one.lines) == 1 and one.font.size < round(0.7 * start), "one line needs less"
    block = _fit_text(text, TEXT_FONT_BOLD_PATH, width, 400, start, 12, 2)
    assert len(block.lines) == 2 and block.font.size > one.font.size
    # The same fit with a start it can keep to within 70 % stays on one line.
    near = _fit_text(text, TEXT_FONT_BOLD_PATH, width, 400, round(one.font.size / 0.75), 12, 2)
    assert near.lines == (text,)

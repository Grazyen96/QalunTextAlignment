"""Drawing one frame, so a style can be judged without rendering the video.

Checking how a video looked meant rendering the whole thing. The renderer
already draws exactly one frame at an arbitrary time, which is what makes this
nearly free.
"""

from __future__ import annotations

import json

import pytest

from qurantext.config.paths import DEFAULT_FONT_PATH
from qurantext.jobs.preview import PreviewRequest, render_preview

pytest.importorskip("PIL", reason="the preview needs Pillow")

pytestmark = pytest.mark.skipif(not DEFAULT_FONT_PATH.exists(), reason="bundled font not present")


def _matches(tmp_path, *, mode="recitation"):
    path = tmp_path / "m.json"
    path.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "surah_num": 25,
                        "surah_name": "سُورَةُ الفُرقَانِ",
                        "from_ayah": 7,
                        "to_ayah": 7,
                        "full_text": "وَقَالُواْ مَالِ هَٰذَا اَ۬لرَّسُولِ",
                        "confidence": 1.0,
                        "start_time": 2.0,
                        "end_time": 6.0,
                    },
                    {
                        "surah_num": 25,
                        "surah_name": "سُورَةُ الفُرقَانِ",
                        "from_ayah": 8,
                        "to_ayah": 8,
                        "full_text": "أَوْ يُلْقَيٰ إِلَيْهِ كَنزٌ",
                        "confidence": 1.0,
                        "start_time": 6.0,
                        "end_time": 10.0,
                    },
                ],
                "meta": {"mode": mode},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_a_frame_is_written_at_the_requested_moment(tmp_path) -> None:
    result = render_preview(
        PreviewRequest(
            matches=_matches(tmp_path),
            output=tmp_path / "p.png",
            at=7.0,
            width=320,
            height=240,
            font_file=DEFAULT_FONT_PATH,
        )
    )
    assert result.output.exists() and result.output.stat().st_size > 0
    assert result.at == 7.0
    assert (result.width, result.height) == (320, 240)
    assert result.card == "25:8", "the second card is the one showing at 7s"


def test_the_default_moment_skips_the_opening_placeholder(tmp_path) -> None:
    """Previewing the placeholder tells you nothing about the style."""
    result = render_preview(
        PreviewRequest(
            matches=_matches(tmp_path),
            output=tmp_path / "p.png",
            width=320,
            height=240,
            font_file=DEFAULT_FONT_PATH,
        )
    )
    assert result.card == "25:7"
    assert 2.0 < result.at < 6.0


def test_the_png_has_the_requested_size_and_is_readable(tmp_path) -> None:
    from PIL import Image

    result = render_preview(
        PreviewRequest(
            matches=_matches(tmp_path),
            output=tmp_path / "p.png",
            at=3.0,
            width=240,
            height=426,
            font_file=DEFAULT_FONT_PATH,
        )
    )
    with Image.open(result.output) as image:
        assert image.size == (240, 426)
        assert image.mode in ("RGB", "RGBA")


def test_a_preset_sets_the_size(tmp_path) -> None:
    result = render_preview(
        PreviewRequest(
            matches=_matches(tmp_path),
            output=tmp_path / "p.png",
            at=3.0,
            preset="social",
            font_file=DEFAULT_FONT_PATH,
        )
    )
    assert (result.width, result.height) == (1080, 1920)


def test_a_moment_before_any_card_shows_the_placeholder(tmp_path) -> None:
    result = render_preview(
        PreviewRequest(
            matches=_matches(tmp_path),
            output=tmp_path / "p.png",
            at=0.5,
            width=240,
            height=180,
            font_file=DEFAULT_FONT_PATH,
        )
    )
    assert result.card is None
    assert result.output.exists()


def test_a_missing_match_file_says_so(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        render_preview(PreviewRequest(matches=tmp_path / "nope.json", output=tmp_path / "p.png"))


def test_the_preview_colours_match_the_renderer(tmp_path) -> None:
    """The PNG must not come out with its channels swapped.

    render_frame_pillow hands back BGR for the encoder; a PNG wants RGB. The
    card is a light grey on a near-black ground, so a swap would be invisible
    there — check against the gold highlight instead, which is strongly warm.
    """
    import numpy as np
    from PIL import Image

    from qurantext.core.frame_renderer import COLOUR_HIGHLIGHT_WORD

    matches = tmp_path / "m.json"
    matches.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "surah_num": 25,
                        "surah_name": "س",
                        "from_ayah": 7,
                        "to_ayah": 7,
                        "full_text": "وَقَالُواْ مَالِ هَٰذَا",
                        "confidence": 1.0,
                        "start_time": 0.0,
                        "end_time": 3.0,
                        "word_timings": [
                            {"word": "وَقَالُواْ", "start": 0.0, "end": 1.0},
                            {"word": "مَالِ", "start": 1.0, "end": 2.0},
                            {"word": "هَٰذَا", "start": 2.0, "end": 3.0},
                        ],
                    }
                ],
                "meta": {"mode": "recitation"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = render_preview(
        PreviewRequest(
            matches=matches,
            output=tmp_path / "p.png",
            at=1.5,
            width=480,
            height=320,
            font_file=DEFAULT_FONT_PATH,
        )
    )
    with Image.open(result.output) as image:
        pixels = np.array(image.convert("RGB")).reshape(-1, 3).astype(int)

    gold = np.array(COLOUR_HIGHLIGHT_WORD[:3])
    distance = np.abs(pixels - gold).sum(axis=1)
    assert (distance < 40).any(), "the gold highlight is missing or its channels are swapped"

"""Today's frames, pinned byte for byte, so the Look refactor provably changes nothing.

The fixture is written once by ``tools/pin_frame_reference.py`` *before* the
renderer changes. Glyph pixels depend on FreeType/Raqm/Pillow, so the fixture
records those versions and the test skips anywhere else.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import __version__ as PIL_VERSION
from PIL import features

from qurantext.config.paths import DEFAULT_FONT_PATH
from qurantext.core.frame_renderer import render_frame_pillow

FIXTURE = Path(__file__).parent / "fixtures" / "frame_reference.json"

_AYAH = {
    "surah_name": "سُورَةُ الفُرقَانِ",
    "from_ayah": 1,
    "to_ayah": 1,
    "_display_text": "تَبَٰرَكَ اَ۬لذِے نَزَّلَ اَ۬لْفُرْقَانَ عَلَيٰ عَبْدِهِۦ لِيَكُونَ لِلْعَٰلَمِينَ نَذِيراً ١",
    "_start_time": 0.0,
    "_end_time": 4.0,
    "_word_timings": [{"start": 0.5 * i, "end": 0.5 * i + 0.4} for i in range(8)],
}
_CAPTION_WT = [
    {"word": w, "start": 0.4 * i, "end": 0.4 * i + 0.3}
    for i, w in enumerate("قال الشيخ في درسه اليوم".split())
]


def environment() -> dict[str, str]:
    return {
        "pillow": PIL_VERSION,
        "freetype2": str(features.version("freetype2")),
        "raqm": str(features.version("raqm")),
    }


def _frames(**kw) -> dict:
    font = DEFAULT_FONT_PATH
    return {
        "ayah_portrait": lambda: render_frame_pillow(
            1.2, dict(_AYAH), 540, 960, font, reserve_caption_band=False, **kw
        ),
        "ayah_with_caption": lambda: render_frame_pillow(
            1.2,
            dict(_AYAH),
            960,
            540,
            font,
            caption_text="قال الشيخ في درسه اليوم",
            caption_word_timings=_CAPTION_WT,
            **kw,
        ),
        "placeholder": lambda: render_frame_pillow(
            0.0, None, 540, 960, font, title="قالون", reserve_caption_band=False, **kw
        ),
        "placeholder_subtitle": lambda: render_frame_pillow(
            0.0,
            None,
            960,
            540,
            font,
            title="سُورَةُ الفُرقَانِ",
            placeholder_subtitle="الآيات ١-٥",
            caption_text="بسم الله",
            **kw,
        ),
    }


FRAMES = _frames()


def digest(frame) -> str:
    return hashlib.sha256(frame.tobytes()).hexdigest()


def _reference() -> dict:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if data["environment"] != environment():
        pytest.skip(f"frame reference pinned under {data['environment']}, not {environment()}")
    return data["frames"]


@pytest.mark.parametrize("name", sorted(FRAMES))
def test_frames_are_byte_identical_to_the_reference(name: str) -> None:
    assert digest(FRAMES[name]()) == _reference()[name]

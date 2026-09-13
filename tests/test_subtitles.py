"""Subtitle cues and the files they are written to.

Subtitles were only ever burned into the picture or staged for a Premiere
panel. These pin the replacement: the same cues written to the formats every
tool already reads.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from qurantext.core.subtitles import (
    SUBTITLE_FORMATS,
    Cue,
    card_ref,
    latched_card_windows,
    write_ass,
    write_srt,
    write_subtitles,
    write_vtt,
)

_FFMPEG = shutil.which("ffmpeg")

CUES = [
    Cue(0.0, 2.5, "أَوَّل", ref="25:7"),
    Cue(2.5, 5.0, "ثَانِي", ref="25:8"),
]


def test_srt_is_numbered_and_ordered(tmp_path) -> None:
    path = write_srt(CUES, tmp_path / "out.srt")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("1\n")
    assert "00:00:00,000 --> 00:00:02,500" in text
    assert "00:00:02,500 --> 00:00:05,000" in text
    assert text.count(" --> ") == 2


def test_srt_can_carry_a_byte_order_mark(tmp_path) -> None:
    """Some editors only detect UTF-8 with one, and Arabic arrives as mojibake without."""
    plain = write_srt(CUES, tmp_path / "a.srt").read_bytes()
    marked = write_srt(CUES, tmp_path / "b.srt", bom=True).read_bytes()
    assert not plain.startswith(b"\xef\xbb\xbf")
    assert marked.startswith(b"\xef\xbb\xbf")


def test_vtt_uses_dots_and_keeps_the_ayah_ref(tmp_path) -> None:
    text = write_vtt(CUES, tmp_path / "out.vtt").read_text(encoding="utf-8")
    assert text.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:02.500" in text
    assert "25:7" in text, "the ayah reference is useful as a cue identifier"


def test_ass_carries_a_style_block(tmp_path) -> None:
    text = write_ass(CUES, tmp_path / "out.ass", width=1080, height=1920).read_text(
        encoding="utf-8-sig"
    )
    assert "[V4+ Styles]" in text and "[Events]" in text
    assert "PlayResX: 1080" in text and "PlayResY: 1920" in text
    assert text.count("Dialogue:") == 2


def test_unusable_cues_are_dropped_not_written(tmp_path) -> None:
    """A zero-length or empty cue is a broken line in every player."""
    messy = [
        Cue(1.0, 1.0, "zero length"),
        Cue(2.0, 3.0, "   "),
        Cue(5.0, 4.0, "backwards"),
        Cue(0.0, 1.0, "keep me"),
    ]
    text = write_srt(messy, tmp_path / "out.srt").read_text(encoding="utf-8")
    assert text.count(" --> ") == 1
    assert "keep me" in text


def test_cues_are_written_in_time_order(tmp_path) -> None:
    shuffled = [Cue(4.0, 5.0, "second"), Cue(0.0, 1.0, "first")]
    text = write_srt(shuffled, tmp_path / "out.srt").read_text(encoding="utf-8")
    assert text.index("first") < text.index("second")


def test_write_subtitles_makes_one_file_per_format(tmp_path) -> None:
    written = write_subtitles(CUES, tmp_path / "job", SUBTITLE_FORMATS)
    assert [p.suffix for p in written] == [".srt", ".vtt", ".ass"]
    assert all(p.exists() and p.stat().st_size > 0 for p in written)


def test_an_unknown_format_says_what_is_available(tmp_path) -> None:
    with pytest.raises(ValueError, match="Choose from"):
        write_subtitles(CUES, tmp_path / "job", ("srt", "docx"))


@pytest.mark.skipif(not _FFMPEG, reason="needs ffmpeg")
@pytest.mark.parametrize("fmt", SUBTITLE_FORMATS)
def test_every_format_is_read_back_by_a_real_parser(tmp_path, fmt) -> None:
    """Written is not the same as readable. Round-trip each through FFmpeg."""
    source = write_subtitles(CUES, tmp_path / "job", (fmt,))[0]
    target = tmp_path / f"roundtrip_{fmt}.srt"
    subprocess.run([_FFMPEG, "-v", "error", "-y", "-i", str(source), str(target)], check=True)
    assert len(re.findall(r" --> ", target.read_text(encoding="utf-8"))) == len(CUES)


# --- card windows -------------------------------------------------------------


def _card(start: float, end: float, **extra) -> dict:
    return {"_start_time": start, "_end_time": end, **extra}


def test_card_windows_tile_the_timeline() -> None:
    """The renderer latches, so a card holds until the next one starts."""
    cards = [_card(0.0, 1.0), _card(5.0, 6.0), _card(9.0, 10.0)]
    windows = latched_card_windows(cards, duration=20.0)

    assert windows == [(0.0, 5.0), (5.0, 9.0), (9.0, 20.0)]
    for (_, end), (start, _) in zip(windows, windows[1:], strict=False):
        assert end == start, "gaps would blank the subtitle where the video shows a card"


def test_the_last_card_holds_to_whichever_is_later() -> None:
    cards = [_card(0.0, 30.0)]
    assert latched_card_windows(cards, duration=10.0) == [(0.0, 30.0)]
    assert latched_card_windows(cards, duration=40.0) == [(0.0, 40.0)]


@pytest.mark.parametrize(
    ("card", "expected"),
    [
        ({"surah_num": 25, "from_ayah": 7, "to_ayah": 7}, "25:7"),
        ({"surah_num": 25, "from_ayah": 1, "to_ayah": 5}, "25:1-5"),
        ({"kind": "preamble", "preamble_kind": "basmala"}, "preamble:basmala"),
    ],
)
def test_card_refs_read_the_way_people_cite_ayat(card, expected) -> None:
    assert card_ref(card) == expected

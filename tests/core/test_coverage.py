"""Finding recited audio that no word covers.

The prototype in docs/findings/forced-alignment-prototype.md showed the
recogniser can drop speech outright, and that an aligner's confidence score is
*higher* where it is wrong. So confidence cannot tell a reviewer where to look.
This can, from the waveform alone.

Audio is synthesised here rather than taken from input/, so these run on a
fresh clone.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from qurantext.core.coverage import find_uncovered_speech, speech_levels, uncovered_from_levels

_FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(not _FFMPEG, reason="needs ffmpeg")


def _audio(path, spec: str):
    """Render a lavfi expression to a small wav."""
    subprocess.run(
        [_FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", spec, str(path)],
        check=True,
    )
    return path


def _tone_then_silence_then_tone(tmp_path):
    """Loud 0-4s, silent 4-8s, loud 8-12s."""
    loud_a = _audio(tmp_path / "a.wav", "sine=frequency=300:duration=4")
    quiet = _audio(tmp_path / "b.wav", "anullsrc=r=44100:cl=mono:duration=4")
    loud_b = _audio(tmp_path / "c.wav", "sine=frequency=300:duration=4")
    out = tmp_path / "joined.wav"
    listing = tmp_path / "list.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in (loud_a, quiet, loud_b)), encoding="utf-8")
    subprocess.run(
        [
            _FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c",
            "copy",
            str(out),
        ],
        check=True,
    )
    return out


def test_speech_levels_separates_loud_from_silent(tmp_path) -> None:
    audio = _tone_then_silence_then_tone(tmp_path)
    times, levels, floor = speech_levels(audio)

    assert len(times) == len(levels) > 0
    loud = [db for t, db in zip(times, levels, strict=True) if t < 3.5]
    silent = [db for t, db in zip(times, levels, strict=True) if 4.5 < t < 7.5]
    assert min(loud) > max(silent) + 20, (min(loud), max(silent))
    assert floor < min(loud)


def test_uncovered_speech_is_found_where_words_are_missing(tmp_path) -> None:
    """The second tone has no word on it, so it must be reported."""
    audio = _tone_then_silence_then_tone(tmp_path)
    words = [{"word": "one", "start": 0.0, "end": 4.0}]

    gaps = find_uncovered_speech(audio, words)

    assert len(gaps) == 1, [g.describe() for g in gaps]
    gap = gaps[0]
    assert 7.5 <= gap.start <= 8.5, gap.describe()
    assert 11.5 <= gap.end <= 12.5, gap.describe()
    assert gap.duration == pytest.approx(4.0, abs=0.6)
    assert "carries no word" in gap.describe()


def test_silence_between_words_is_not_reported(tmp_path) -> None:
    """A genuine pause is not dropped audio, however long it is."""
    audio = _tone_then_silence_then_tone(tmp_path)
    words = [
        {"word": "one", "start": 0.0, "end": 4.0},
        {"word": "two", "start": 8.0, "end": 12.0},
    ]
    assert find_uncovered_speech(audio, words) == []


def test_short_stretches_are_ignored(tmp_path) -> None:
    """Breaths and word junctures must not drown the real findings."""
    audio = _tone_then_silence_then_tone(tmp_path)
    words = [{"word": "one", "start": 0.0, "end": 4.0}]

    assert find_uncovered_speech(audio, words, min_seconds=10.0) == []
    assert find_uncovered_speech(audio, words, min_seconds=1.0)


def test_overlapping_and_unordered_spans_still_cover(tmp_path) -> None:
    """Word spans overlap and are not always sorted; coverage must handle both."""
    audio = _tone_then_silence_then_tone(tmp_path)
    words = [
        {"word": "late", "start": 8.0, "end": 12.0},
        {"word": "early", "start": 0.0, "end": 2.5},
        {"word": "overlaps", "start": 2.0, "end": 4.0},
    ]
    assert find_uncovered_speech(audio, words) == []


def test_entries_without_usable_timings_are_ignored_not_trusted(tmp_path) -> None:
    """A None start must not be read as covering the clip."""
    audio = _tone_then_silence_then_tone(tmp_path)
    words = [
        {"word": "ok", "start": 0.0, "end": 4.0},
        {"word": "broken", "start": None, "end": None},
    ]
    gaps = find_uncovered_speech(audio, words)
    assert len(gaps) == 1


def test_no_words_at_all_reports_every_loud_stretch(tmp_path) -> None:
    audio = _tone_then_silence_then_tone(tmp_path)
    gaps = find_uncovered_speech(audio, [])
    assert len(gaps) == 2
    assert sum(g.duration for g in gaps) == pytest.approx(8.0, abs=1.0)


def test_levels_read_once_give_the_same_answer_as_reading_them_again(tmp_path) -> None:
    """The review window decodes once and re-checks from the levels after every edit."""
    audio = _tone_then_silence_then_tone(tmp_path)
    words = [{"word": "one", "start": 0.0, "end": 4.0}]
    times, levels, floor = speech_levels(audio)

    assert uncovered_from_levels(times, levels, floor, words) == find_uncovered_speech(audio, words)
    assert uncovered_from_levels(times, levels, floor, [{"start": 0.0, "end": 12.5}]) == []
    assert uncovered_from_levels([], [], floor, words) == []

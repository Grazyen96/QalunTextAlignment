"""The rules every timing edit obeys, kept out of the widgets.

A reviewer drags, nudges and ripples; these are what stop an edit from making
two words overlap, swap order, or leave a card window disagreeing with its words.
"""

from __future__ import annotations

import pytest

from qurantext.core.timing_edit import (
    MIN_WORD_S,
    count_edited,
    derive_card_windows,
    retime,
    ripple,
)


def _words(*spans):
    return [{"word": f"w{i}", "start": s, "end": e} for i, (s, e) in enumerate(spans)]


def test_retime_moves_one_word_and_marks_it_edited() -> None:
    words = _words((0.0, 1.0), (1.0, 2.0), (2.0, 3.0))
    out = retime(words, 1, start=1.2, end=1.8)
    assert (out[1]["start"], out[1]["end"]) == (1.2, 1.8)
    assert out[1]["edited"] is True
    assert "edited" not in out[0] and "edited" not in out[2]
    assert words[1]["start"] == 1.0, "input must not be mutated"


def test_retime_start_earlier_trims_the_previous_word_instead_of_overlapping() -> None:
    out = retime(_words((0.0, 1.0), (1.0, 2.0)), 1, start=0.6)
    assert out[1]["start"] == 0.6
    assert out[0]["end"] == 0.6
    assert out[0]["edited"] is True


def test_retime_start_cannot_pass_the_previous_word_start() -> None:
    out = retime(_words((0.5, 1.0), (1.0, 2.0)), 1, start=0.1)
    assert out[1]["start"] == pytest.approx(0.5 + MIN_WORD_S)
    assert out[0]["end"] == pytest.approx(0.5 + MIN_WORD_S)


def test_retime_end_later_pushes_the_next_word_start() -> None:
    out = retime(_words((0.0, 1.0), (1.0, 2.0)), 0, end=1.4)
    assert out[0]["end"] == 1.4
    assert out[1]["start"] == 1.4


def test_retime_end_cannot_pass_the_next_word_end() -> None:
    out = retime(_words((0.0, 1.0), (1.0, 2.0)), 0, end=9.0)
    assert out[0]["end"] == pytest.approx(2.0 - MIN_WORD_S)


def test_retime_keeps_a_minimum_length() -> None:
    out = retime(_words((0.0, 1.0)), 0, start=5.0)
    assert out[0]["start"] == pytest.approx(1.0 - MIN_WORD_S)
    out = retime(_words((0.0, 1.0)), 0, end=-3.0)
    assert out[0]["end"] == pytest.approx(MIN_WORD_S)


def test_the_first_word_cannot_start_before_zero() -> None:
    out = retime(_words((0.5, 1.0)), 0, start=-2.0)
    assert out[0]["start"] == 0.0


def test_ripple_shifts_the_word_and_everything_after_it() -> None:
    words = _words((0.0, 1.0), (1.0, 2.0), (6.0, 7.0), (7.0, 8.0))
    out = ripple(words, 2, -3.5)
    assert [(w["start"], w["end"]) for w in out] == [
        (0.0, 1.0),
        (1.0, 2.0),
        (2.5, 3.5),
        (3.5, 4.5),
    ]
    assert [bool(w.get("edited")) for w in out] == [False, False, True, True]


def test_ripple_is_clamped_by_the_previous_word_and_trims_it() -> None:
    out = ripple(_words((0.0, 2.0), (3.0, 4.0)), 1, -10.0)
    assert out[1]["start"] == pytest.approx(MIN_WORD_S)
    assert out[0]["end"] == pytest.approx(MIN_WORD_S)


def test_ripple_does_not_run_past_the_audio() -> None:
    out = ripple(_words((0.0, 1.0), (1.0, 2.0)), 0, 5.0, duration=3.0)
    assert out[-1]["end"] == 3.0
    assert out[0]["start"] == 1.0


def test_card_windows_follow_their_first_words() -> None:
    cards = [
        {
            "from_ayah": 7,
            "start_time": 0.0,
            "end_time": 10.0,
            "word_timings": _words((0.4, 1.0), (1.0, 2.0)),
        },
        {
            "from_ayah": 8,
            "start_time": 10.0,
            "end_time": 20.0,
            "word_timings": _words((12.0, 13.0), (13.0, 25.0)),
        },
    ]
    out = derive_card_windows(cards)
    assert (out[0]["start_time"], out[0]["end_time"]) == (0.4, 12.0)
    assert (out[1]["start_time"], out[1]["end_time"]) == (12.0, 25.0)
    assert cards[0]["start_time"] == 0.0, "input must not be mutated"


def test_the_last_card_keeps_its_end_when_its_words_end_earlier() -> None:
    cards = [{"start_time": 0.0, "end_time": 96.57, "word_timings": _words((0.1, 1.0))}]
    assert derive_card_windows(cards)[0]["end_time"] == 96.57


def test_cards_without_word_timings_are_left_alone() -> None:
    cards = [{"start_time": 3.0, "end_time": 5.0}]
    out = derive_card_windows(cards)
    assert out == cards and out[0] is not cards[0]


def test_count_edited() -> None:
    words = retime(_words((0.0, 1.0), (1.0, 2.0), (2.0, 3.0)), 1, start=1.1)
    assert count_edited(words) == 1


def test_the_25_7_gap_can_be_closed_by_retiming(tmp_path) -> None:
    """The measured 7.5 s hole after نذيرا is something an edit can close.

    This does not claim which timing is right — the prototype could not settle
    that without a listener. It proves the tool can express the fix.
    """
    import shutil
    from pathlib import Path

    from qurantext.core.coverage import find_uncovered_speech
    from qurantext.jobs.project import Project

    audio = Path("input/recitations/furquanTra7-11.mp3")
    matches = Path("output/recitation_matching/furquanTra7-11_recitation.json")
    if not (audio.is_file() and matches.is_file() and shutil.which("ffmpeg")):
        pytest.skip("needs the local furquanTra7-11 recording and its match file")

    project = Project.from_match_file(matches, audio)
    words = project.cards[0]["word_timings"]
    before = find_uncovered_speech(audio, words)
    assert any(g.start < 20.0 < g.end for g in before), "expected the known gap near 16.7–24.2 s"

    last_of_25_7 = next(i for i, w in enumerate(words) if w["end"] >= 16.6)
    following_start = float(words[last_of_25_7 + 1]["start"])
    fixed = retime(words, last_of_25_7, end=following_start)
    after = find_uncovered_speech(audio, fixed)
    assert not any(g.start < 20.0 < g.end for g in after)

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
    retime_in_cards,
    ripple,
    ripple_in_cards,
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

    root = Path(__file__).resolve().parents[1]
    audio = root / "input/recitations/furquanTra7-11.mp3"
    matches = root / "output/recitation_matching/furquanTra7-11_recitation.json"
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


# -- collapsed runs -----------------------------------------------------------
#
# Real alignment output contains runs of words squeezed to nothing (furqanTra
# has 188 zero-length words around 128.657 s). The rules must hold there too.


def _collapsed():
    return _words(*([(10.0, 10.0)] * 5), (10.0, 11.0))


def _assert_postconditions(words) -> None:
    for word in words:
        assert word["start"] <= word["end"], word
    for a, b in zip(words, words[1:], strict=False):
        assert a["start"] <= b["start"], (a, b)
        assert a["end"] <= b["start"], (a, b)


def test_a_no_op_retime_in_a_collapsed_run_changes_nothing() -> None:
    words = _collapsed()
    for i, word in enumerate(words):
        assert retime(words, i, start=word["start"]) == words
        assert retime(words, i, end=word["end"]) == words
        assert retime(words, i, start=word["start"], end=word["end"]) == words


def test_a_no_op_retime_of_a_short_word_changes_nothing() -> None:
    words = _words((0.0, 1.0), (1.0, 1.02), (1.02, 2.0))
    assert retime(words, 1, start=1.0) == words
    assert retime(words, 1, end=1.02) == words


def test_retime_inside_a_collapsed_run_never_inverts_a_word() -> None:
    words = _collapsed()
    for i in range(1, 4):
        for request in (9.0, 9.99, 10.0, 10.01, 10.5, 12.0):
            _assert_postconditions(retime(words, i, start=request))
            _assert_postconditions(retime(words, i, end=request))
    # The middle of a run is pinned by its neighbours' other edges.
    assert retime(words, 2, end=10.5) == words
    assert retime(words, 2, start=9.5) == words


def test_the_last_word_of_a_collapsed_run_can_be_lengthened_into_the_next() -> None:
    out = retime(_collapsed(), 4, end=10.5)
    assert (out[4]["start"], out[4]["end"]) == (10.0, 10.5)
    assert (out[5]["start"], out[5]["end"]) == (10.5, 11.0)
    _assert_postconditions(out)


def test_a_short_word_may_stay_short_but_is_never_made_shorter() -> None:
    words = _words((0.0, 1.0), (1.0, 1.02), (1.02, 2.0))
    out = retime(words, 1, end=1.03)
    assert out[1]["end"] == 1.03, "lengthening a short word is allowed below the minimum"
    assert retime(words, 1, end=1.01) == words
    assert retime(words, 1, start=1.01) == words


def test_ripple_of_a_collapsed_run() -> None:
    words = _collapsed()
    out = ripple(words, 0, -1.0)
    assert [(w["start"], w["end"]) for w in out] == [(9.0, 9.0)] * 5 + [(9.0, 10.0)]
    _assert_postconditions(out)
    # Inside the run, an earlier word already sits on the same instant.
    assert ripple(words, 2, -1.0) == words
    later = ripple(words, 2, 0.5)
    assert [(w["start"], w["end"]) for w in later][1:3] == [(10.0, 10.0), (10.5, 10.5)]
    _assert_postconditions(later)


def test_ripple_never_moves_against_the_request_when_words_run_past_the_audio() -> None:
    words = _words((0.0, 1.0), (1.0, 5.0))
    assert ripple(words, 1, 1.0, duration=4.0) == words


def test_edits_hold_the_rules_over_many_random_requests() -> None:
    import random

    rng = random.Random(20260923)
    for _ in range(300):
        t, spans = rng.uniform(0.0, 3.0), []
        for _ in range(rng.randint(1, 12)):
            length = rng.choice([0.0, 0.0, 0.01, 0.03, rng.uniform(0.0, 1.5)])
            start = round(t, 3)
            end = round(t + length, 3)
            spans.append((start, end))
            t = end + rng.choice([0.0, 0.0, rng.uniform(0.0, 0.5)])
        words = _words(*spans)
        for _ in range(10):
            i = rng.randrange(len(words))
            kind = rng.choice(["start", "end", "both", "ripple", "noop"])
            joined = rng.choice([False, True])
            if kind == "start":
                out = retime(words, i, start=rng.uniform(-1.0, t + 1.0), keep_joined=joined)
            elif kind == "end":
                out = retime(words, i, end=rng.uniform(-1.0, t + 1.0), keep_joined=joined)
            elif kind == "both":
                out = retime(
                    words,
                    i,
                    start=rng.uniform(-1.0, t + 1.0),
                    end=rng.uniform(-1.0, t + 1.0),
                    keep_joined=joined,
                )
            elif kind == "ripple":
                out = ripple(words, i, rng.uniform(-3.0, 3.0), duration=t + rng.uniform(-1, 2))
            else:
                out = retime(
                    words, i, start=words[i]["start"], end=words[i]["end"], keep_joined=joined
                )
                assert out == words
            _assert_postconditions(out)
            words = out


def _spans(words):
    return [(w["start"], w["end"]) for w in words]


def test_a_joined_end_nudged_out_and_back_puts_the_neighbour_back() -> None:
    words = _words((0.0, 1.0), (1.0, 2.0), (2.0, 3.0))
    out = retime(words, 0, end=1.05, keep_joined=True)
    assert _spans(out)[:2] == [(0.0, 1.05), (1.05, 2.0)]
    back = retime(out, 0, end=1.0, keep_joined=True)
    assert _spans(back) == _spans(words)


def test_a_joined_start_nudged_out_and_back_puts_the_neighbour_back() -> None:
    words = _words((0.0, 1.0), (1.0, 2.0))
    out = retime(words, 1, start=1.05, keep_joined=True)
    assert _spans(out) == [(0.0, 1.05), (1.05, 2.0)], "the shared edge moves with it"
    back = retime(out, 1, start=1.0, keep_joined=True)
    assert _spans(back) == _spans(words)
    earlier = retime(words, 1, start=0.95, keep_joined=True)
    assert _spans(retime(earlier, 1, start=1.0, keep_joined=True)) == _spans(words)


def test_without_keep_joined_a_shortened_word_leaves_a_gap() -> None:
    words = _words((0.0, 1.0), (1.0, 2.0))
    assert _spans(retime(words, 0, end=0.95)) == [(0.0, 0.95), (1.0, 2.0)]
    assert _spans(retime(words, 1, start=1.05)) == [(0.0, 1.0), (1.05, 2.0)]


def test_an_edge_with_a_gap_never_moves_the_neighbour() -> None:
    words = _words((0.0, 1.0), (1.2, 2.0), (2.5, 3.0))
    for request in (0.8, 0.95, 1.05, 1.15, 1.2):
        out = retime(words, 0, end=request, keep_joined=True)
        assert _spans(out)[1] == (1.2, 2.0), request
    for request in (2.1, 2.3, 2.45):
        out = retime(words, 2, start=request, keep_joined=True)
        assert _spans(out)[1] == (1.2, 2.0), request


def test_a_joined_edge_is_still_bounded_by_both_words() -> None:
    words = _words((0.0, 1.0), (1.0, 2.0))
    shortened = retime(words, 0, end=-5.0, keep_joined=True)
    assert shortened[0]["end"] == pytest.approx(MIN_WORD_S)
    assert shortened[1]["start"] == shortened[0]["end"]
    lengthened = retime(words, 0, end=9.0, keep_joined=True)
    assert lengthened[0]["end"] == pytest.approx(2.0 - MIN_WORD_S)
    assert lengthened[1]["start"] == lengthened[0]["end"]
    later = retime(words, 1, start=9.0, keep_joined=True)
    assert later[1]["start"] == pytest.approx(2.0 - MIN_WORD_S)
    assert later[0]["end"] == later[1]["start"]
    _assert_postconditions(shortened)
    _assert_postconditions(lengthened)
    _assert_postconditions(later)


def test_joined_is_judged_on_the_millisecond_grid() -> None:
    words = _words((0.0, 1.0000000000000002), (1.0, 2.0))
    out = retime(words, 0, end=0.95, keep_joined=True)
    assert _spans(out) == [(0.0, 0.95), (0.95, 2.0)]


def test_keep_joined_inside_a_collapsed_run_keeps_the_rules() -> None:
    words = _collapsed()
    for i in range(len(words)):
        for request in (9.0, 9.5, 9.99, 10.0, 10.01, 10.5, 12.0):
            _assert_postconditions(retime(words, i, start=request, keep_joined=True))
            _assert_postconditions(retime(words, i, end=request, keep_joined=True))
    assert retime(words, 2, end=10.5, keep_joined=True) == words
    assert retime(words, 2, start=9.5, keep_joined=True) == words


# -- editing across cards -----------------------------------------------------


def _cards():
    return [
        {
            "from_ayah": 7,
            "start_time": 0.0,
            "end_time": 2.0,
            "word_timings": _words((0.0, 1.0), (1.0, 2.0)),
        },
        {"kind": "preamble", "start_time": 5.0, "end_time": 6.0},
        {
            "from_ayah": 8,
            "start_time": 2.0,
            "end_time": 30.0,
            "word_timings": _words((2.0, 3.0), (3.0, 4.0)),
        },
    ]


def test_lengthening_a_cards_last_word_trims_the_next_cards_first_word() -> None:
    cards = _cards()
    out = retime_in_cards(cards, 0, 1, end=9.0)
    assert out[0]["word_timings"][1]["end"] == pytest.approx(3.0 - MIN_WORD_S)
    assert out[2]["word_timings"][0]["start"] == pytest.approx(3.0 - MIN_WORD_S)
    assert out[2]["word_timings"][0]["edited"] is True
    assert out[0]["end_time"] == pytest.approx(3.0 - MIN_WORD_S), "window re-derived"
    assert out[2]["start_time"] == pytest.approx(3.0 - MIN_WORD_S)


def test_a_joined_edge_across_cards_moves_back_with_keep_joined() -> None:
    cards = _cards()
    out = retime_in_cards(cards, 0, 1, end=2.05, keep_joined=True)
    assert out[2]["word_timings"][0]["start"] == 2.05
    back = retime_in_cards(out, 0, 1, end=2.0, keep_joined=True)
    assert back[2]["word_timings"][0]["start"] == 2.0
    assert back[2]["start_time"] == 2.0 and back[0]["end_time"] == 2.0
    assert retime_in_cards(out, 0, 1, end=2.0)[2]["word_timings"][0]["start"] == 2.05


def test_a_ripple_inside_one_card_carries_into_the_next() -> None:
    cards = _cards()
    out = ripple_in_cards(cards, 0, 1, 0.5)
    assert [(w["start"], w["end"]) for w in out[0]["word_timings"]] == [(0.0, 1.0), (1.5, 2.5)]
    assert [(w["start"], w["end"]) for w in out[2]["word_timings"]] == [(2.5, 3.5), (3.5, 4.5)]
    assert (out[2]["start_time"], out[2]["end_time"]) == (2.5, 30.0)
    assert out[0]["end_time"] == 2.5


def test_a_ripple_in_cards_respects_the_audio_end() -> None:
    out = ripple_in_cards(_cards(), 2, 0, 10.0, duration=5.0)
    assert out[2]["word_timings"][-1]["end"] == 5.0


def test_untimed_cards_pass_through_untouched() -> None:
    cards = _cards()
    out = retime_in_cards(cards, 2, 0, start=2.5)
    assert out[1] == cards[1]


def test_editing_in_cards_does_not_mutate_the_input() -> None:
    import copy

    cards = _cards()
    before = copy.deepcopy(cards)
    retime_in_cards(cards, 0, 1, end=9.0)
    ripple_in_cards(cards, 0, 0, 1.0)
    assert cards == before


def test_editing_a_card_without_words_is_an_error() -> None:
    with pytest.raises(ValueError, match="word timings"):
        retime_in_cards(_cards(), 1, 0, start=5.5)


@pytest.mark.parametrize("index", [-1, 3, 99])
def test_retime_and_ripple_refuse_an_index_that_is_not_there(index) -> None:
    words = _words((0.0, 1.0), (1.0, 2.0), (2.0, 3.0))
    with pytest.raises(IndexError):
        retime(words, index, start=0.5)
    with pytest.raises(IndexError):
        ripple(words, index, 0.5)


@pytest.mark.parametrize(("card_index", "word_index"), [(-1, 0), (5, 0), (0, -1), (0, 9)])
def test_card_edits_refuse_an_index_that_is_not_there(card_index, word_index) -> None:
    from qurantext.core.timing_edit import retime_in_cards, ripple_in_cards

    cards = [
        {"start_time": 0.0, "end_time": 2.0, "word_timings": _words((0.0, 1.0), (1.0, 2.0))},
        {"start_time": 2.0, "end_time": 4.0, "word_timings": _words((2.0, 3.0), (3.0, 4.0))},
    ]
    with pytest.raises(IndexError):
        retime_in_cards(cards, card_index, word_index, start=0.5)
    with pytest.raises(IndexError):
        ripple_in_cards(cards, card_index, word_index, 0.5)


def test_off_grid_times_never_invert_a_neighbour() -> None:
    words = [{"word": "a", "start": 0.4, "end": 0.5}, {"word": "b", "start": 0.5006, "end": 0.5009}]
    out = retime(words, 0, end=1.0)
    for word in out:
        assert word["start"] <= word["end"]
    assert out[0]["end"] <= out[1]["start"]


def test_a_sub_millisecond_ripple_does_not_shorten_a_word() -> None:
    words = _words((76.5, 76.563), (76.563, 76.603), (76.603, 77.0))
    out = ripple(words, 1, -0.0025)
    assert round(out[1]["end"] - out[1]["start"], 3) == 0.04


def test_cue_bounds_grow_to_cover_the_words() -> None:
    from qurantext.core.timing_edit import cue_bounds

    assert cue_bounds(1.0, 2.0, _words((0.8, 1.2), (1.2, 2.5))) == (0.8, 2.5)
    assert cue_bounds(1.0, 2.0, _words((1.1, 1.2))) == (1.0, 2.0)
    assert cue_bounds(1.0, 2.0, []) == (1.0, 2.0)

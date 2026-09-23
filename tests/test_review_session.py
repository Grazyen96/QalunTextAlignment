"""The editing model behind the review window, tested without a screen."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from qurantext.gui.review.session import CAPTION, CARD, ReviewSession, WordRef
from qurantext.jobs.project import CaptionCue, Project, load_project, save_project


def _w(text, start, end):
    return {"word": text, "start": start, "end": end}


def _recitation(tmp_path=None):
    cards = [
        {
            "surah_num": 25,
            "from_ayah": 7,
            "to_ayah": 7,
            "full_text": "a b",
            "confidence": 1.0,
            "start_time": 0.0,
            "end_time": 2.0,
            "word_timings": [_w("a", 0.0, 1.0), _w("b", 1.0, 2.0)],
        },
        {
            "surah_num": 25,
            "from_ayah": 8,
            "to_ayah": 8,
            "full_text": "c d",
            "confidence": 1.0,
            "start_time": 2.0,
            "end_time": 10.0,
            "word_timings": [_w("c", 2.0, 3.0), _w("d", 3.0, 4.0)],
        },
    ]
    project = Project(audio=(tmp_path or Path(".")) / "a.mp3", mode="recitation", cards=cards)
    if tmp_path is not None:
        save_project(project, tmp_path / "job.qalun.json")
    return project


def _lecture():
    return Project(
        audio=Path("dars.mp3"),
        mode="lecture",
        cards=[
            {
                "surah_num": 1,
                "from_ayah": 1,
                "to_ayah": 1,
                "full_text": "x",
                "confidence": 1.0,
                "start_time": 5.0,
                "end_time": 8.0,
            }
        ],
        captions=[
            CaptionCue(0.0, 2.0, "one two", words=[_w("one", 0.0, 1.0), _w("two", 1.0, 2.0)]),
            CaptionCue(2.5, 4.0, "three", words=[_w("three", 2.5, 4.0)]),
        ],
    )


def _long_lecture(cues=1000, words_per_cue=5, word_len=0.1):
    """A lecture with 1,000 cues of 5 words each: 5,000 caption words, no gaps."""
    captions = []
    t = 0.0
    for i in range(cues):
        words = []
        for j in range(words_per_cue):
            words.append(_w(f"w{i}_{j}", t, t + word_len))
            t += word_len
        text = " ".join(w["word"] for w in words)
        captions.append(CaptionCue(words[0]["start"], words[-1]["end"], text, words=words))
    return Project(audio=Path("dars.mp3"), mode="lecture", cards=[], captions=captions)


def test_words_are_the_primary_kind_in_time_order() -> None:
    session = ReviewSession(_recitation())
    assert session.primary_kind == CARD
    assert [w.text for w in session.words()] == ["a", "b", "c", "d"]
    assert session.words()[2].ref == WordRef(CARD, 1, 0)
    lecture = ReviewSession(_lecture())
    assert lecture.primary_kind == CAPTION
    assert [w.text for w in lecture.words()] == ["one", "two", "three"]


def test_lookups_follow_the_renderer() -> None:
    session = ReviewSession(_recitation())
    assert session.word_at(1.5) == WordRef(CARD, 0, 1)
    assert session.word_at(-1.0) is None
    assert session.card_at(9.0) == 1
    assert session.card_at(-0.1) is None
    lecture = ReviewSession(_lecture())
    assert lecture.caption_at(2.2) is None
    assert lecture.caption_at(3.0) == 1


def test_step_moves_between_words_across_cards() -> None:
    session = ReviewSession(_recitation())
    assert session.step(None, +1) == WordRef(CARD, 0, 0)
    assert session.step(WordRef(CARD, 0, 1), +1) == WordRef(CARD, 1, 0)
    assert session.step(WordRef(CARD, 0, 0), -1) is None


def test_retime_goes_through_the_card_rules_and_rederives_windows() -> None:
    session = ReviewSession(_recitation())
    session.retime(WordRef(CARD, 1, 0), start=2.5)
    card = session.project.cards[1]
    assert card["word_timings"][0]["start"] == 2.5 and card["word_timings"][0]["edited"]
    assert card["start_time"] == 2.5
    assert session.project.cards[0]["end_time"] == 2.5
    assert session.dirty and session.can_undo
    assert session.retimed_count(CARD, 1) == 1


def test_ripple_carries_into_later_cards() -> None:
    session = ReviewSession(_recitation())
    session.ripple(WordRef(CARD, 0, 1), 0.5)
    assert [w.start for w in session.words()] == [0.0, 1.5, 2.5, 3.5]


def test_caption_retime_grows_the_line_to_cover_its_words() -> None:
    session = ReviewSession(_lecture())
    session.retime(WordRef(CAPTION, 1, 0), end=4.6)
    cue = session.project.captions[1]
    assert cue.words[0]["end"] == 4.6 and cue.end == 4.6


def test_caption_text_edits_keep_timings_when_the_count_holds() -> None:
    session = ReviewSession(_lecture())
    session.set_caption_text(0, "one too")
    assert [w["word"] for w in session.project.captions[0].words] == ["one", "too"]


def test_card_times_are_editable_only_without_word_timings() -> None:
    lecture = ReviewSession(_lecture())
    lecture.set_card_times(0, start=6.0, end=5.0)
    assert (lecture.project.cards[0]["start_time"], lecture.project.cards[0]["end_time"]) == (
        6.0,
        6.0,
    )
    with pytest.raises(ValueError):
        ReviewSession(_recitation()).set_card_times(0, start=1.0)


def test_a_gesture_is_one_undo_step_and_an_empty_one_is_none() -> None:
    session = ReviewSession(_recitation())
    session.begin_gesture()
    for value in (0.2, 0.3, 0.4):
        session.retime(WordRef(CARD, 0, 1), start=1.0 + value)
    session.end_gesture()
    assert session.words()[1].start == 1.4
    assert session.undo() is True
    assert session.words()[1].start == 1.0
    assert session.undo() is False
    assert session.redo() is True and session.words()[1].start == 1.4

    session.begin_gesture()
    session.end_gesture()
    session.undo()
    assert session.words()[1].start == 1.0, "the empty gesture left no entry of its own"


def test_undo_back_to_the_saved_state_is_clean(tmp_path) -> None:
    session = ReviewSession(load_project(_recitation(tmp_path).path))
    assert not session.dirty
    session.retime(WordRef(CARD, 0, 0), end=0.8)
    assert session.dirty
    session.undo()
    assert not session.dirty


def test_save_writes_back_and_clears_dirty(tmp_path) -> None:
    session = ReviewSession(load_project(_recitation(tmp_path).path))
    session.retime(WordRef(CARD, 0, 0), end=0.8)
    session.mark_reviewed()
    path = session.save()
    assert not session.dirty
    reloaded = load_project(path)
    assert reloaded.cards[0]["word_timings"][0]["end"] == 0.8
    assert reloaded.review["state"] == "reviewed"


def test_save_without_a_file_says_so() -> None:
    with pytest.raises(ValueError):
        ReviewSession(_recitation()).save()


def test_removing_a_card_never_touches_quran_text() -> None:
    session = ReviewSession(_recitation())
    text = session.project.cards[1]["full_text"]
    session.remove_card(0)
    assert len(session.project.cards) == 1 and session.project.cards[0]["full_text"] == text
    session.undo()
    assert len(session.project.cards) == 2


def test_frame_inputs_give_the_active_card_and_caption() -> None:
    card, caption, band = ReviewSession(_recitation()).frame_inputs(2.5)
    assert card["from_ayah"] == 8 and "_start_time" in card
    assert caption is None and band is False
    card, caption, band = ReviewSession(_lecture()).frame_inputs(1.0)
    assert card is None and caption["text"] == "one two" and band is True


def test_coverage_words_are_the_primary_kind() -> None:
    assert len(ReviewSession(_recitation()).coverage_words()) == 4
    assert len(ReviewSession(_lecture()).coverage_words()) == 3


def test_revision_moves_on_every_change() -> None:
    session = ReviewSession(_recitation())
    start = session.revision
    session.retime(WordRef(CARD, 0, 0), end=0.9)
    session.undo()
    session.redo()
    assert session.revision == start + 3


def test_words_are_cached_until_the_next_change() -> None:
    session = ReviewSession(_recitation())
    first = session.words()
    assert session.words() is first
    session.retime(WordRef(CARD, 0, 0), end=0.9)
    assert session.words() is not first


def test_word_at_is_fast_on_a_long_lecture() -> None:
    session = ReviewSession(_long_lecture())
    words = session.words()
    assert len(words) == 5000

    def brute_force(t: float):
        found = None
        for tw in words:
            if tw.start <= t:
                found = tw.ref
            else:
                break
        return found

    sample_times = [words[i].start + 0.05 for i in range(0, len(words), 100)]
    assert len(sample_times) == 50
    for t in sample_times:
        assert session.word_at(t) == brute_force(t)

    calls = 200
    started = time.perf_counter()
    for _ in range(calls):
        session.word_at(sample_times[0])
    elapsed_ms = (time.perf_counter() - started) * 1000 / calls
    assert elapsed_ms < 1.0, f"word_at averaged {elapsed_ms:.3f} ms/call over {calls} calls"


def test_words_in_returns_the_visible_slice() -> None:
    session = ReviewSession(_long_lecture())
    words = session.words()
    assert len(words) == 5000

    def brute_force(t0: float, t1: float):
        return [tw.ref for tw in words if tw.end >= t0 and tw.start <= t1]

    for t0, t1 in [(0.0, 1.0), (10.0, 12.5), (250.0, 260.0), (499.5, 500.0), (500.0, 500.0)]:
        got = [tw.ref for tw in session.words_in(t0, t1)]
        assert got == brute_force(t0, t1), f"window ({t0}, {t1})"

    # A word that starts before t0 but still ends inside the window must be
    # found even though its start is outside [t0, t1].
    straddling = words[400]
    t0 = straddling.start + 0.05
    t1 = straddling.end + 0.2
    got = [tw.ref for tw in session.words_in(t0, t1)]
    assert straddling.ref in got
    assert got == brute_force(t0, t1)


def test_a_snap_only_noop_is_not_dirty() -> None:
    noisy = 1.0000000000000002
    project = _lecture()
    project.captions[0] = CaptionCue(
        0.0, 2.0, "one two", words=[_w("one", 0.0, noisy), _w("two", noisy, 2.0)]
    )
    session = ReviewSession(project)
    session.retime(WordRef(CAPTION, 0, 0), end=1.0)
    assert not session.dirty

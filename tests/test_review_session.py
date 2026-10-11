"""The editing model behind the review window, tested without a screen."""

from __future__ import annotations

import copy
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


def test_revert_restores_the_last_saved_state(tmp_path) -> None:
    session = ReviewSession(_recitation(tmp_path))
    ref = WordRef(CARD, 0, 0)
    session.retime(ref, end=0.8)
    session.save()
    session.retime(ref, end=0.6)
    session.remove_card(1)
    before = session.revision
    session.revert()
    assert not session.dirty
    assert session.revision != before
    assert session.word(ref).end == 0.8
    assert len(session.project.cards) == 2
    # Discarded means discarded: nothing to undo back into.
    assert not session.can_undo and not session.can_redo


def test_revert_without_a_save_restores_the_loaded_state() -> None:
    session = ReviewSession(_lecture())
    session.set_caption_text(0, "one two!")
    session.remove_caption(1)
    session.revert()
    assert not session.dirty
    assert [cue.text for cue in session.project.captions] == ["one two", "three"]


def test_a_drag_past_the_next_word_and_back_leaves_it_untouched() -> None:
    session = ReviewSession(_recitation())
    a, b = WordRef(CARD, 0, 0), WordRef(CARD, 0, 1)
    session.begin_gesture()
    session.drag_retime(a, end=1.5)
    assert session.word(b).start == 1.5
    before = session.revision
    session.drag_retime(a, end=1.0)
    assert session.revision != before
    session.end_gesture()
    assert (session.word(b).start, session.word(b).end) == (1.0, 2.0)
    assert session.word(a).end == 1.0
    assert not session.can_undo, "a drag that ends where it began is no undo step"


def test_a_ripple_past_the_clamp_and_back_ends_where_it_began() -> None:
    session = ReviewSession(_recitation())
    c = WordRef(CARD, 1, 0)
    session.begin_gesture()
    session.drag_ripple(c, -5.0)
    assert session.word(c).start == pytest.approx(1.04)
    session.drag_ripple(c, 0.0)
    session.end_gesture()
    assert session.word(c).start == 2.0
    assert session.word(WordRef(CARD, 0, 1)).end == 2.0


def test_drag_edits_need_a_gesture() -> None:
    session = ReviewSession(_recitation())
    with pytest.raises(RuntimeError):
        session.drag_retime(WordRef(CARD, 0, 0), end=1.5)
    with pytest.raises(RuntimeError):
        session.drag_ripple(WordRef(CARD, 0, 0), 0.5)


def test_removing_a_card_lets_the_previous_card_close_the_hole() -> None:
    project = _recitation()
    project.cards.append(
        {
            "surah_num": 25,
            "from_ayah": 9,
            "to_ayah": 9,
            "full_text": "e",
            "confidence": 1.0,
            "start_time": 5.0,
            "end_time": 10.0,
            "word_timings": [_w("e", 5.0, 6.0)],
        }
    )
    project.cards[1]["end_time"] = 5.0
    session = ReviewSession(project)
    before = [dict(card) for card in session.project.cards]
    session.remove_card(1)
    assert [card["from_ayah"] for card in session.project.cards] == [7, 9]
    assert session.project.cards[0]["end_time"] == 5.0
    session.undo()
    assert session.project.cards == before


def test_removing_a_lecture_card_leaves_the_others_alone() -> None:
    session = ReviewSession(_lecture())
    session.project.cards.append(dict(session.project.cards[0], start_time=9.0, end_time=9.5))
    session.remove_card(1)
    assert session.project.cards[0]["end_time"] == 8.0


def _real_shaped_recitation(tmp_path):
    """A project as matching writes it: card windows a hair off the words they hold.

    Detection rounds a card's window on its own, so a real project opens with
    ``start_time`` 0.11 over a first word at 0.109 (and an end a little before
    the last word's). Any timing edit re-derives the windows from the words.
    """
    cards = [
        {
            "surah_num": 25,
            "from_ayah": 7,
            "to_ayah": 11,
            "full_text": "a b c",
            "confidence": 0.96,
            "start_time": 0.11,
            "end_time": 2.57,
            "word_timings": [_w("a", 0.109, 1.37), _w("b", 1.37, 1.9), _w("c", 1.95, 2.573)],
        }
    ]
    project = Project(audio=tmp_path / "a.mp3", mode="recitation", cards=cards)
    save_project(project, tmp_path / "job.qalun.json")
    return load_project(tmp_path / "job.qalun.json")


def test_a_drag_out_and_back_on_a_real_shaped_project_is_no_edit(tmp_path) -> None:
    session = ReviewSession(_real_shaped_recitation(tmp_path))
    before = copy.deepcopy(session.project.cards)
    ref = WordRef(CARD, 0, 1)
    session.begin_gesture()
    session.drag_retime(ref, end=1.8)
    assert session.dirty
    session.drag_retime(ref, end=1.9)
    session.end_gesture()
    assert not session.dirty
    assert not session.can_undo
    assert session.project.cards == before


def test_a_drag_that_moved_something_is_still_an_edit(tmp_path) -> None:
    session = ReviewSession(_real_shaped_recitation(tmp_path))
    ref = WordRef(CARD, 0, 1)
    session.begin_gesture()
    session.drag_retime(ref, end=1.8)
    session.end_gesture()
    assert session.dirty and session.can_undo
    assert session.word(ref).end == 1.8
    session.undo()
    assert not session.dirty


def test_a_nudge_and_back_on_a_shared_edge_is_the_start_state(tmp_path) -> None:
    """``.`` then ``,``: the end touched the next start, so the next start comes back too."""
    session = ReviewSession(load_project(_recitation(tmp_path).path))
    before = copy.deepcopy(session.project.cards)
    a, b = WordRef(CARD, 0, 0), WordRef(CARD, 0, 1)
    session.retime(a, end=session.word(a).end + 0.05)
    assert (session.word(a).end, session.word(b).start) == (1.05, 1.05)
    assert session.dirty
    session.retime(a, end=session.word(a).end - 0.05)
    assert (session.word(b).start, session.word(b).end) == (1.0, 2.0)
    assert not session.dirty
    assert session.project.cards == before


def test_a_nudge_back_across_cards_puts_the_next_card_back() -> None:
    session = ReviewSession(_recitation())
    before = copy.deepcopy(session.project.cards)
    last_of_first = WordRef(CARD, 0, 1)
    session.retime(last_of_first, end=2.05)
    assert session.project.cards[1]["start_time"] == 2.05
    session.retime(last_of_first, end=2.0)
    assert session.project.cards == before and not session.dirty


def test_nudging_back_part_of_the_way_is_still_an_edit() -> None:
    session = ReviewSession(_recitation())
    a, b = WordRef(CARD, 0, 0), WordRef(CARD, 0, 1)
    session.retime(a, end=1.05)
    session.retime(a, end=1.01)
    assert session.dirty
    assert (session.word(a).end, session.word(b).start) == (1.01, 1.01)
    assert session.word(a).edited and session.word(b).edited


def test_a_drag_of_a_shared_edge_pulls_the_neighbour_along() -> None:
    session = ReviewSession(_recitation())
    a, b = WordRef(CARD, 0, 0), WordRef(CARD, 0, 1)
    session.begin_gesture()
    session.drag_retime(a, end=0.8)
    session.end_gesture()
    assert (session.word(a).end, session.word(b).start) == (0.8, 0.8)


def test_a_caption_nudge_and_back_is_the_start_state() -> None:
    session = ReviewSession(_lecture())
    before = copy.deepcopy(session.project.captions)
    one = WordRef(CAPTION, 0, 0)
    session.retime(one, end=1.05)
    session.retime(one, end=1.0)
    assert session.project.captions == before and not session.dirty


def test_a_gesture_that_changes_nothing_keeps_redo() -> None:
    """A click on a word begins and ends a gesture; it must not throw away redo."""
    session = ReviewSession(_recitation())
    ref = WordRef(CARD, 0, 1)
    session.retime(ref, end=1.5)
    session.undo()
    assert session.can_redo

    session.begin_gesture()
    session.end_gesture()
    assert session.can_redo, "a click with no movement"

    session.begin_gesture()
    session.drag_retime(ref, end=1.6)
    session.drag_retime(ref, end=2.0)
    session.end_gesture()
    assert session.can_redo, "a drag that came back where it began"

    session.redo()
    assert session.words()[1].end == 1.5

    session.undo()
    session.begin_gesture()
    session.drag_retime(ref, end=1.7)
    session.end_gesture()
    assert not session.can_redo, "a real edit starts a new branch"
    assert session.words()[1].end == 1.7


def test_an_edge_dragged_without_keep_joined_opens_a_gap() -> None:
    session = ReviewSession(_recitation())
    session.begin_gesture()
    session.drag_retime(WordRef(CARD, 0, 0), end=0.8, keep_joined=False)
    session.end_gesture()
    words = session.words()
    assert (words[0].end, words[1].start) == (0.8, 1.0), "the neighbour stays put"

    joined = ReviewSession(_recitation())
    joined.begin_gesture()
    joined.drag_retime(WordRef(CARD, 0, 0), end=0.8)
    joined.end_gesture()
    words = joined.words()
    assert (words[0].end, words[1].start) == (0.8, 0.8), "by default a shared edge stays shared"


# -- the look ------------------------------------------------------------------


@pytest.fixture
def session(tmp_path):
    """A saved recitation's session, so ``save`` has a file to write to."""
    return ReviewSession(load_project(_recitation(tmp_path).path))


def test_a_new_session_shows_night_gold_and_is_clean(session) -> None:
    from qurantext.core.looks import NIGHT_GOLD

    assert session.look == NIGHT_GOLD and not session.dirty


def test_set_look_is_one_undo_step_and_makes_the_session_dirty(session) -> None:
    from qurantext.core.looks import NIGHT_GOLD, PRESETS

    session.set_look(PRESETS["emerald"])
    assert session.look == PRESETS["emerald"] and session.dirty and session.can_undo
    assert session.undo()
    assert session.look == NIGHT_GOLD and not session.dirty
    assert session.redo()
    assert session.look == PRESETS["emerald"]


def test_setting_the_same_look_is_no_edit(session) -> None:
    from qurantext.core.looks import NIGHT_GOLD

    session.set_look(NIGHT_GOLD)
    assert not session.can_undo and not session.dirty


def test_a_slider_drag_is_one_undo_step(session) -> None:
    from dataclasses import replace

    from qurantext.core.looks import NIGHT_GOLD, PRESETS

    session.begin_gesture()
    for dim in (0.1, 0.2, 0.3):
        bg = replace(PRESETS["ocean"].background, dim=dim)
        session.set_look(replace(PRESETS["ocean"], background=bg))
    session.end_gesture()
    assert session.undo() and session.look == NIGHT_GOLD and not session.can_undo


def test_save_and_revert_include_the_look(session) -> None:
    from qurantext.core.looks import PRESETS

    session.set_look(PRESETS["rose"])
    session.save()
    assert not session.dirty
    session.set_look(PRESETS["sand"])
    session.revert()
    assert session.look == PRESETS["rose"]


def test_a_timing_gesture_that_ends_where_it_began_still_settles(session) -> None:
    # Existing behaviour must hold with the 4-tuple snapshot: begin_gesture();
    # end_gesture() with no change → not dirty, nothing to undo.
    session.begin_gesture()
    session.end_gesture()
    assert not session.dirty and not session.can_undo


def test_the_live_frame_of_a_lecture_skips_a_quote_from_another_surah() -> None:
    project = _lecture()
    studied = project.cards[0]
    project.cards.append(
        dict(studied, surah_num=2, from_ayah=255, to_ayah=255, start_time=8.5, end_time=9.0)
    )
    session = ReviewSession(project)

    card, _caption, _band = session.frame_inputs(8.7)
    assert (card["surah_num"], card["from_ayah"]) == (1, 1)
    assert len(session.project.cards) == 2, "the quote stays in the project, only off the card"


# -- the studied surah -----------------------------------------------------------


def _lecture_with_a_quote(tmp_path=None):
    project = _lecture()
    studied = project.cards[0]
    project.cards.append(
        dict(studied, surah_num=2, from_ayah=255, to_ayah=255, start_time=8.5, end_time=9.0)
    )
    if tmp_path is not None:
        save_project(project, tmp_path / "dars.qalun.json")
    return project


def test_the_live_frame_follows_the_chosen_surah() -> None:
    session = ReviewSession(_lecture_with_a_quote())
    assert session.studied_surah is None
    session.set_studied_surah(2)
    card, _caption, _band = session.frame_inputs(8.7)
    assert (card["surah_num"], card["from_ayah"]) == (2, 255)
    assert session.frame_inputs(6.0)[0] is None, "al-Fatiha is off the card now"


def test_choosing_a_surah_is_one_undo_step_and_makes_the_session_dirty() -> None:
    session = ReviewSession(_lecture_with_a_quote())
    session.set_studied_surah(2)
    assert session.studied_surah == 2 and session.dirty and session.can_undo
    assert session.project.export["studied_surah"] == 2
    assert session.undo()
    assert session.studied_surah is None and not session.dirty
    assert "studied_surah" not in session.project.export
    assert session.redo()
    assert session.studied_surah == 2 and session.dirty


def test_choosing_the_same_surah_is_no_edit() -> None:
    session = ReviewSession(_lecture_with_a_quote())
    session.set_studied_surah(None)
    assert not session.can_undo and not session.dirty


def test_save_and_revert_include_the_studied_surah(tmp_path) -> None:
    from qurantext.jobs.project import job_settings

    session = ReviewSession(load_project(_lecture_with_a_quote(tmp_path).path))
    session.set_studied_surah(1)
    session.save()
    assert job_settings(load_project(session.project.path)).studied_surah == 1
    session.set_studied_surah(2)
    session.revert()
    assert session.studied_surah == 1 and not session.dirty


def test_undoing_a_retime_keeps_a_surah_chosen_before_it() -> None:
    """Each undo step puts back exactly what it took, the surah choice among it."""
    session = ReviewSession(_lecture_with_a_quote())
    session.set_studied_surah(2)
    ref = session.words(CAPTION)[0].ref
    session.retime(ref, end=0.9)
    assert session.undo()
    assert session.studied_surah == 2
    assert session.undo()
    assert session.studied_surah is None


def test_a_chosen_surah_with_no_card_is_reported() -> None:
    session = ReviewSession(_lecture_with_a_quote())
    assert session.missing_studied_surah is None
    session.set_studied_surah(2)
    assert session.missing_studied_surah is None
    session.set_studied_surah(114)
    assert session.missing_studied_surah == 114
    assert session.validated_cards() == [], "only the opening title card is left"


def test_a_recitation_never_reports_a_missing_surah() -> None:
    project = _recitation()
    project.export["studied_surah"] = 114
    assert ReviewSession(project).missing_studied_surah is None


def test_a_chosen_surah_whose_only_card_cannot_be_drawn_is_reported() -> None:
    """Judged on the drawn cards: a card lasting no time is no card on screen."""
    project = _lecture_with_a_quote()
    project.cards[1]["end_time"] = project.cards[1]["start_time"]
    session = ReviewSession(project)
    session.set_studied_surah(2)
    assert session.missing_studied_surah == 2


# -- hand-made ayah cards ------------------------------------------------------


@pytest.fixture
def db(store):
    """The word-level store the suite builds once per module (``conftest.store``)."""
    return store


@pytest.fixture
def lecture_session(tmp_path):
    """A saved lecture quoting 25:7 at 10–20 s and 25:8 at 30–40 s, 100 s long."""
    project = Project(
        audio=tmp_path / "dars.mp3",
        mode="lecture",
        cards=[
            {
                "surah_num": 25,
                "from_ayah": 7,
                "to_ayah": 7,
                "text": "وقالوا مال هذا الرسول",
                "full_text": "وقالوا مال هذا الرسول",
                "confidence": 0.9,
                "start_time": 10.0,
                "end_time": 20.0,
            },
            {
                "surah_num": 25,
                "from_ayah": 8,
                "to_ayah": 8,
                "text": "أو يلقى إليه كنز",
                "full_text": "أو يلقى إليه كنز",
                "confidence": 0.9,
                "start_time": 30.0,
                "end_time": 40.0,
            },
        ],
    )
    save_project(project, tmp_path / "dars.qalun.json")
    return ReviewSession(load_project(project.path), duration=100.0)


def _refs(session):
    return [
        (
            c["surah_num"],
            c["from_ayah"],
            c["to_ayah"],
            c["start_time"],
            c["end_time"],
            bool(c.get("manual")),
        )
        for c in session.project.cards
    ]


def test_insert_between_cards_runs_until_the_next(lecture_session, db):
    i = lecture_session.insert_manual_card(25.0, 25, 7, 7, db_path=db)
    assert _refs(lecture_session)[i] == (25, 7, 7, 25.0, 30.0, True)
    assert lecture_session.dirty and lecture_session.can_undo


def test_insert_inside_a_card_trims_it_and_one_undo_restores_both(lecture_session, db):
    before = _refs(lecture_session)
    lecture_session.insert_manual_card(15.0, 25, 5, 6, db_path=db)
    refs = _refs(lecture_session)
    assert refs[0][4] == 15.0  # 25:7 now ends at the playhead
    assert refs[1] == (25, 5, 6, 15.0, 30.0, True)
    assert lecture_session.undo()
    assert _refs(lecture_session) == before and not lecture_session.dirty


def test_insert_before_the_first_card(lecture_session, db):
    i = lecture_session.insert_manual_card(2.0, 25, 1, 1, db_path=db)
    assert i == 0 and _refs(lecture_session)[0] == (25, 1, 1, 2.0, 10.0, True)


def test_insert_after_the_last_card_runs_to_the_end_of_the_recording(lecture_session, db):
    i = lecture_session.insert_manual_card(50.0, 25, 9, 9, db_path=db)
    assert _refs(lecture_session)[i][3:5] == (50.0, 100.0)


def test_insert_at_the_very_end_still_lasts_half_a_second(lecture_session, db):
    i = lecture_session.insert_manual_card(100.0, 25, 9, 9, db_path=db)
    start, end = _refs(lecture_session)[i][3:5]
    assert start == 99.5 and end == 100.0


def test_insert_without_duration_or_next_card_lasts_ten_seconds(lecture_session, db):
    lecture_session.duration = None
    i = lecture_session.insert_manual_card(50.0, 25, 9, 9, db_path=db)
    assert _refs(lecture_session)[i][3:5] == (50.0, 60.0)


def test_insert_at_a_cards_start_changes_that_card(lecture_session, db):
    i = lecture_session.insert_manual_card(30.03, 2, 255, 255, db_path=db)
    assert len(lecture_session.project.cards) == 2
    assert _refs(lecture_session)[i] == (2, 255, 255, 30.0, 40.0, True)
    assert lecture_session.undo() and not lecture_session.can_undo


def test_change_keeps_times_and_drops_detection_fields(lecture_session, db):
    lecture_session.project.cards[0]["detected_text"] = "قال"
    lecture_session.project.cards[0]["_matched_words"] = 3
    lecture_session.change_card_ayah(0, 25, 3, 4, db_path=db)
    card = lecture_session.project.cards[0]
    assert (card["from_ayah"], card["to_ayah"]) == (3, 4)
    assert (card["start_time"], card["end_time"]) == (10, 20)
    assert card["manual"] is True and card["detected_text"] == "" and "_matched_words" not in card
    assert lecture_session.is_manual(0)


def test_invalid_reference_leaves_no_edit(lecture_session, db):
    with pytest.raises(ValueError):
        lecture_session.insert_manual_card(25.0, 25, 9, 7, db_path=db)
    assert not lecture_session.can_undo and not lecture_session.dirty


def test_recitation_projects_refuse_manual_cards(session, db):
    # `session` is the module's existing recitation fixture
    with pytest.raises(ValueError):
        session.insert_manual_card(1.0, 25, 1, 1, db_path=db)
    with pytest.raises(ValueError):
        session.change_card_ayah(0, 25, 1, 1, db_path=db)


def test_a_manual_card_makes_a_render_stale(lecture_session, db):
    lecture_session.project.record_render(Path("v.mp4"), preset=None, basmala_offset_s=0.0)
    lecture_session.insert_manual_card(25.0, 25, 7, 7, db_path=db)
    assert lecture_session.project.render_is_stale

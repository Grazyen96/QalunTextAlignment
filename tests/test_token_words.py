from __future__ import annotations

import pytest

from qurantext.core.token_words import tokens_to_words

M = "▁"


def _w(words):
    return [(w["word"], w["start"], w["end"]) for w in words]


def test_the_word_mark_starts_a_word_and_pieces_join_it() -> None:
    words = tokens_to_words([f"{M}وقا", "لوا", f"{M}ما"], [0.0, 0.16, 0.8], window_end=2.0)
    assert [w["word"] for w in words] == ["وقالوا", "ما"]


def test_start_is_the_first_token_and_end_is_the_next_start() -> None:
    words = tokens_to_words([f"{M}a", "b", f"{M}c"], [1.0, 1.2, 1.4], window_end=3.0)
    assert _w(words)[0] == ("ab", 1.0, 1.4)


def test_end_is_capped_half_a_second_after_the_last_token() -> None:
    words = tokens_to_words([f"{M}a", f"{M}b"], [1.0, 5.0], window_end=9.0)
    assert _w(words)[0] == ("a", 1.0, 1.5)


def test_the_last_word_is_capped_at_the_window_end() -> None:
    words = tokens_to_words([f"{M}a"], [2.8], window_end=3.0)
    assert _w(words) == [("a", 2.8, 3.0)]


def test_offset_moves_everything_into_the_recording() -> None:
    words = tokens_to_words([f"{M}a"], [0.5], window_end=1.0, offset=60.0)
    assert _w(words) == [("a", 60.5, 61.0)]


def test_a_bare_mark_starts_the_next_piece_as_a_word() -> None:
    words = tokens_to_words([f"{M}a", M, "b"], [0.0, 0.4, 0.48], window_end=2.0)
    assert [w["word"] for w in words] == ["a", "b"]
    assert words[1]["start"] == 0.48


def test_punctuation_attaches_to_the_word_before() -> None:
    words = tokens_to_words([f"{M}a", "،", f"{M}b", "."], [0.0, 0.2, 0.4, 0.6], window_end=1.0)
    assert [w["word"] for w in words] == ["a،", "b."]


def test_leading_punctuation_is_dropped() -> None:
    words = tokens_to_words(["،", f"{M}a"], [0.0, 0.2], window_end=1.0)
    assert [w["word"] for w in words] == ["a"]


def test_a_leading_space_starts_a_word_like_the_mark() -> None:
    # sherpa-onnx's Python API renders the SentencePiece mark as a leading space.
    words = tokens_to_words([" وقا", "لوا", " ما"], [0.0, 0.16, 0.8], window_end=2.0)
    assert [w["word"] for w in words] == ["وقالوا", "ما"]
    assert _w(words)[0] == ("وقالوا", 0.0, 0.66)


def test_a_bare_space_starts_the_next_piece_as_a_word() -> None:
    words = tokens_to_words([" a", " ", "b"], [0.0, 0.4, 0.48], window_end=2.0)
    assert [w["word"] for w in words] == ["a", "b"]
    assert words[1]["start"] == 0.48


def test_punctuation_after_a_leading_space_attaches_to_the_word_before() -> None:
    words = tokens_to_words([" a", " ،", "b"], [0.0, 0.2, 0.3], window_end=1.0)
    assert [w["word"] for w in words] == ["a،", "b"]


def test_a_marked_punctuation_token_still_starts_the_next_piece() -> None:
    words = tokens_to_words([f"{M}a", f"{M}،", "b"], [0.0, 0.2, 0.3], window_end=1.0)
    assert [w["word"] for w in words] == ["a،", "b"]


def test_special_tokens_are_not_speech() -> None:
    words = tokens_to_words(
        [" a", "<unk>", " b", " <blk>", " c"], [0, 0.1, 0.2, 0.3, 0.4], window_end=1.0
    )
    assert [w["word"] for w in words] == ["a", "b", "c"]


def test_a_continuation_with_nothing_before_starts_a_word() -> None:
    words = tokens_to_words(["ab", "c"], [0.0, 0.1], window_end=1.0)
    assert [w["word"] for w in words] == ["abc"]


def test_two_words_on_one_frame_keep_end_equal_to_start() -> None:
    words = tokens_to_words([f"{M}a", f"{M}b"], [0.4, 0.4], window_end=1.0)
    assert words[0]["end"] == words[0]["start"] == 0.4


def test_diacritics_stay_in_the_word() -> None:
    text = "وَقَالُوا"
    assert tokens_to_words([f"{M}{text}"], [0.0], window_end=1.0)[0]["word"] == text


def test_every_word_scores_one() -> None:
    assert {w["score"] for w in tokens_to_words([f"{M}a", f"{M}b"], [0, 1], window_end=2)} == {1.0}


def test_mismatched_lengths_are_an_error() -> None:
    with pytest.raises(ValueError):
        tokens_to_words([f"{M}a"], [0.0, 1.0], window_end=2.0)


def test_no_tokens_no_words() -> None:
    assert tokens_to_words([], [], window_end=2.0) == []


def _load_reference(monkeypatch):
    """Import the bake-off's function by path (prototypes/ is not a package)."""
    import importlib.util
    import sys
    import types
    from pathlib import Path

    proto = Path(__file__).resolve().parents[1] / "prototypes" / "asr_bakeoff"
    if not (proto / "run_sherpa.py").exists():
        pytest.skip("prototype not present")
    monkeypatch.syspath_prepend(str(proto))
    if importlib.util.find_spec("sherpa_onnx") is None:
        monkeypatch.setitem(sys.modules, "sherpa_onnx", types.ModuleType("sherpa_onnx"))
    try:
        spec = importlib.util.spec_from_file_location("_run_sherpa_ref", proto / "run_sherpa.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"cannot import the prototype: {exc}")
    return module.tokens_to_words


def test_it_matches_the_bakeoff_reference(monkeypatch) -> None:
    reference = _load_reference(monkeypatch)
    cases = [
        ([f"{M}وقا", "لوا", f"{M}ما"], [0.0, 0.16, 0.8]),
        (
            [" وقا", "لوا", " ", "ما", " ،", "<unk>", " x", "."],
            [0, 0.2, 0.3, 0.35, 0.5, 0.6, 0.9, 2.0],
        ),
        (["،", f"{M}a", M, "b", f"{M}،", "c"], [0.0, 0.2, 0.4, 0.48, 0.6, 0.7]),
        (["ab", "c", f"{M}<blk>", f"{M}d"], [0.1, 0.3, 5.0, 5.2]),
    ]
    for tokens, times in cases:
        kw = {"window_end": 6.0, "offset": 12.0}
        assert tokens_to_words(tokens, times, **kw) == reference(tokens, times, **kw)

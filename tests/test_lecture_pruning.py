"""The cheap upper bound that lets the matcher skip hopeless candidates.

Fuzzy scoring (``partial_ratio``) is nearly all of the matcher's time, and on a
real lecture about 95% of the candidates it scores could never reach the
threshold. ``score_upper_bound`` says so without the fuzzy step. These tests pin
the one property that makes skipping safe: the bound is never below the score,
so nothing the matcher used to accept is ever skipped.
"""

from __future__ import annotations

import random

import pytest

from qurantext.core import lecture_matching
from qurantext.core.lecture_matching import (
    detect_quran_mentions_in_lecture,
    score_span_for_lecture,
    score_upper_bound,
)

# Short normalised Arabic words, so random spans and windows share words often
# enough to exercise every part of the score.
_VOCAB = ["قال", "الذين", "كفروا", "ربك", "على", "كل", "شيء", "قدير", "الله", "من", "في", "لا"]


def _phrase(rng: random.Random, low: int, high: int) -> str:
    return " ".join(rng.choice(_VOCAB) for _ in range(rng.randint(low, high)))


def test_the_bound_is_never_below_the_score() -> None:
    rng = random.Random(20261010)
    for _ in range(3000):
        span = _phrase(rng, 1, 12)
        window = _phrase(rng, 1, 35)
        assert score_span_for_lecture(span, window) <= score_upper_bound(span, window)


def test_the_bound_equals_the_score_when_the_texts_match_exactly() -> None:
    text = "قال الذين كفروا لولا نزل عليه القرءان"
    assert score_upper_bound(text, text) == score_span_for_lecture(text, text) == 1.0


def test_empty_text_bounds_to_zero_like_the_score() -> None:
    assert score_upper_bound("", "قال") == score_span_for_lecture("", "قال") == 0.0
    assert score_upper_bound("قال", "") == score_span_for_lecture("قال", "") == 0.0


def test_the_bound_is_rounded_like_the_score() -> None:
    """Rounding keeps order, so a rounded bound still never falls below a rounded score."""
    value = score_upper_bound("قال الذين كفروا", "قال ربك على كل شيء قدير الله")
    assert value == round(value, 4)


def _ayah(num: int, text: str) -> dict:
    return {
        "surah_num": 25,
        "surah_name": "سُورَةُ الفُرقَانِ",
        "ayah_num": num,
        "text_raw": text,
        "text_norm": text,
        "_index": num - 1,
    }


def _words(text: str, start: float = 0.0) -> list[dict]:
    return [
        {"word_raw": w, "word_norm": w, "start": start + i, "end": start + i + 0.5}
        for i, w in enumerate(text.split())
    ]


def test_only_candidates_that_could_pass_reach_the_fuzzy_step(monkeypatch) -> None:
    """Commentary sharing a few words with an ayah is ruled out by the bound alone."""
    scored: list[tuple[str, str]] = []
    real = lecture_matching.score_span_for_lecture

    def spy(span: str, window: str) -> float:
        scored.append((span, window))
        return real(span, window)

    monkeypatch.setattr(lecture_matching, "score_span_for_lecture", spy)
    ayah = "تبارك الذي نزل الفرقان على عبده ليكون للعالمين نذيرا"
    commentary = "ثم قال الشيخ ان هذا الكلام على عبده في الدرس وهو كلام طويل جدا عن معنى اخر تماما"
    detect_quran_mentions_in_lecture(
        [_ayah(1, ayah)], _words(commentary), max_span=1, max_merged_ayat=1
    )

    threshold = lecture_matching.DEFAULT_LECTURE_THRESHOLD
    assert all(score_upper_bound(span, window) >= threshold for span, window in scored)


def test_a_real_quote_is_still_found() -> None:
    ayah = "تبارك الذي نزل الفرقان على عبده ليكون للعالمين نذيرا"
    ayat = [_ayah(1, ayah), _ayah(2, "الذي له ملك السماوات والارض ولم يتخذ ولدا")]
    lecture = f"قال الشيخ في درسه اليوم {ayah} ثم شرح معناها للطلاب"
    mentions = detect_quran_mentions_in_lecture(
        ayat, _words(lecture), max_span=1, max_merged_ayat=1
    )
    assert [(m["from_ayah"], m["to_ayah"]) for m in mentions] == [(1, 1)]


@pytest.mark.parametrize("seed", range(3))
def test_pruning_changes_no_result(monkeypatch, seed: int) -> None:
    """The matcher with the bound gives exactly what it gives when nothing is pruned."""
    rng = random.Random(seed)
    ayat = [_ayah(i + 1, _phrase(rng, 6, 10)) for i in range(4)]
    pieces = []
    for _ in range(3):
        pieces.append(_phrase(rng, 5, 10))
        pieces.append(rng.choice(ayat)["text_norm"])
    words = _words(" ".join(pieces))
    options = {"max_span": 2, "max_merged_ayat": 2, "max_window_words": 14}

    pruned = detect_quran_mentions_in_lecture(ayat, words, **options)
    monkeypatch.setattr(lecture_matching, "score_upper_bound", lambda _s, _w: 1.0)
    unpruned = detect_quran_mentions_in_lecture(ayat, words, **options)
    assert pruned and pruned == unpruned

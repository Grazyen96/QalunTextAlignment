"""Timing a recitation whose range the user stated.

Detection was never the right question for recitation. Searching for the range
cost ~583 s on a nineteen-minute recitation, 99% of the mode's runtime, and had
no way to decline: the range finder returns its best candidate whatever the
score. Told the range, the work is alignment over known text.
"""

from __future__ import annotations

import json

import pytest

from qurantext.config.paths import QURAN_INPUT_DIR
from qurantext.pipelines.detection import cards_for_range, run_recitation_range

QURAN_FILE = QURAN_INPUT_DIR / "UthmanicQaloon1-Ver05.txt"
pytestmark = pytest.mark.skipif(not QURAN_FILE.exists(), reason="shipped Quran file not present")


def _ayat(count: int, surah: int = 25, first: int = 1) -> list[dict]:
    return [
        {
            "surah_num": surah,
            "surah_name": "سُورَةُ الفُرقَانِ",
            "ayah_num": first + i,
            "text_raw": f"كلمة{i} كلمتان{i}",
            "text_norm": f"كلمة{i} كلمتان{i}",
            "_index": i,
        }
        for i in range(count)
    ]


def test_cards_chunk_the_range_in_order() -> None:
    cards = cards_for_range(_ayat(7, first=1), max_span=3)

    assert [(c["from_ayah"], c["to_ayah"]) for c in cards] == [(1, 3), (4, 6), (7, 7)]
    assert all(c["surah_num"] == 25 for c in cards)
    # The range was stated, so nothing about which ayah is uncertain.
    assert all(c["confidence"] == 1.0 for c in cards)
    # Every ayah's text appears exactly once across the cards.
    joined = "\n".join(c["full_text"] for c in cards)
    for ayah in _ayat(7, first=1):
        assert joined.count(ayah["text_raw"]) == 1


def test_a_single_ayah_is_one_card() -> None:
    cards = cards_for_range(_ayat(1, first=5), max_span=5)
    assert len(cards) == 1
    assert (cards[0]["from_ayah"], cards[0]["to_ayah"]) == (5, 5)


def _transcript(tmp_path, ayat_text: list[str]):
    """A transcript whose words are the canonical ones, one per second."""
    words, t = [], 0.0
    for text in ayat_text:
        for token in text.split():
            words.append({"word": token, "start": t, "end": t + 0.8})
            t += 1.0
    path = tmp_path / "wx.json"
    path.write_text(
        json.dumps({"segments": [{"words": words}]}, ensure_ascii=False), encoding="utf-8"
    )
    return path


def test_stated_range_times_every_ayah_it_was_given(tmp_path) -> None:
    from qurantext.core.quran_parser import parse_ayat

    chosen = [
        a for a in parse_ayat(QURAN_FILE) if a["surah_num"] == 25 and 7 <= a["ayah_num"] <= 11
    ]
    whisperx = _transcript(tmp_path, [a["text_raw"] for a in chosen])
    out = tmp_path / "result.json"

    result = run_recitation_range(
        quran=QURAN_FILE,
        output=out,
        surah_num=25,
        from_ayah=7,
        to_ayah=11,
        whisperx=whisperx,
        echo=False,
    )

    covered = set()
    for card in result["matches"]:
        if card.get("kind") == "preamble":
            continue
        covered |= set(range(card["from_ayah"], card["to_ayah"] + 1))
    assert covered == {7, 8, 9, 10, 11}

    assert result["meta"]["range_source"] == "stated"
    assert result["meta"]["detected_surah_num"] == 25
    assert out.exists()

    timings = [w for m in result["matches"] for w in m.get("word_timings", [])]
    assert timings, "the whole point is to produce word timings"
    starts = [w["start"] for w in timings]
    assert starts == sorted(starts), "highlight timings must never move backwards"


def test_an_impossible_range_says_what_is_available(tmp_path) -> None:
    whisperx = _transcript(tmp_path, ["كلمة"])
    with pytest.raises(ValueError, match="surah 25 has ayat"):
        run_recitation_range(
            quran=QURAN_FILE,
            output=tmp_path / "r.json",
            surah_num=25,
            from_ayah=900,
            to_ayah=999,
            whisperx=whisperx,
            echo=False,
        )


@pytest.mark.parametrize(
    ("surah", "first", "last", "message"),
    [
        (0, 1, 2, "between 1 and 114"),
        (115, 1, 2, "between 1 and 114"),
        (25, 0, 2, "Invalid ayah range"),
        (25, 9, 3, "Invalid ayah range"),
    ],
)
def test_a_nonsensical_range_is_refused_before_any_work(
    tmp_path, surah, first, last, message
) -> None:
    with pytest.raises(ValueError, match=message):
        run_recitation_range(
            quran=QURAN_FILE,
            output=tmp_path / "r.json",
            surah_num=surah,
            from_ayah=first,
            to_ayah=last,
            whisperx=tmp_path / "missing.json",
            echo=False,
        )


def test_exactly_one_transcript_source_is_required(tmp_path) -> None:
    with pytest.raises(ValueError, match="Exactly one"):
        run_recitation_range(
            quran=QURAN_FILE,
            output=tmp_path / "r.json",
            surah_num=25,
            from_ayah=7,
            to_ayah=11,
            echo=False,
        )

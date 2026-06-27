"""Unit tests for the lecture one-ayah-at-a-time timeline selector."""

from __future__ import annotations

from qurantext.core.lecture_matching import select_lecture_timeline


def _m(surah, ayah, start, end, conf):
    return {
        "surah_num": surah,
        "surah_name": f"surah-{surah}",
        "from_ayah": ayah,
        "to_ayah": ayah,
        "full_text": f"text-{surah}:{ayah}",
        "detected_text": "x",
        "confidence": conf,
        "start_time": start,
        "end_time": end,
    }


def test_timeline_is_single_ayah_and_non_overlapping() -> None:
    # Two sequential ayat whose wide windows overlap: 7 dominant early, 8 late.
    matches = [
        _m(25, 7, 33.0, 233.0, 0.90),
        _m(25, 8, 233.0, 271.0, 0.94),
        _m(25, 8, 236.0, 261.0, 0.90),  # duplicate fragment of ayah 8
    ]
    timeline = select_lecture_timeline(matches)

    assert all(c["from_ayah"] == c["to_ayah"] for c in timeline)
    assert [c["from_ayah"] for c in timeline] == [7, 8]
    for prev, nxt in zip(timeline, timeline[1:], strict=False):
        assert nxt["start_time"] >= prev["end_time"]  # no overlap


def test_timeline_consolidates_same_ayah_persisting_across_gap() -> None:
    # Same ayah quoted, gap, then quoted again with nothing else between → one
    # card that persists (only changes when a different ayah is detected).
    matches = [
        _m(25, 7, 33.0, 68.0, 0.90),
        _m(25, 7, 223.0, 233.0, 0.82),
    ]
    timeline = select_lecture_timeline(matches)
    assert len(timeline) == 1
    assert timeline[0]["from_ayah"] == 7
    assert timeline[0]["start_time"] == 33.0
    assert timeline[0]["end_time"] == 233.0


def test_timeline_prefers_surrounding_surah_for_near_duplicate() -> None:
    # Furqan(25) #9 ≈ Isra(17) #48: Isra scores marginally higher but sits
    # between Furqan #8 and #10, so continuity must pick Furqan #9.
    matches = [
        _m(25, 8, 233.0, 271.0, 0.94),
        _m(17, 48, 310.0, 349.0, 0.93),  # higher confidence, wrong surah
        _m(25, 9, 315.0, 348.0, 0.86),  # right surah, within margin
        _m(25, 10, 373.0, 411.0, 0.89),
    ]
    timeline = select_lecture_timeline(matches)
    assert [(c["surah_num"], c["from_ayah"]) for c in timeline] == [
        (25, 8),
        (25, 9),
        (25, 10),
    ]


def test_timeline_keeps_genuine_cross_surah_reference() -> None:
    # No near-duplicate in the surrounding surah → the cross-surah quote stays.
    matches = [
        _m(25, 8, 233.0, 271.0, 0.94),
        _m(17, 1, 310.0, 349.0, 0.93),  # genuinely different ayah, no Furqan rival
        _m(25, 10, 373.0, 411.0, 0.89),
    ]
    timeline = select_lecture_timeline(matches)
    assert (17, 1) in [(c["surah_num"], c["from_ayah"]) for c in timeline]

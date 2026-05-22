from qurantext.core.frame_renderer import ActiveMatchTracker, active_match_at


def _timed_matches() -> list[dict]:
    return [
        {
            "id": "a",
            "_start_time": 0.0,
            "_end_time": 2.0,
            "_confidence": 0.6,
            "_duration": 2.0,
        },
        {
            "id": "b",
            "_start_time": 1.0,
            "_end_time": 3.0,
            "_confidence": 0.9,
            "_duration": 2.0,
        },
        {
            "id": "c",
            "_start_time": 3.2,
            "_end_time": 4.5,
            "_confidence": 0.7,
            "_duration": 1.3,
        },
    ]


def test_active_match_tracker_matches_legacy_selection_for_monotonic_times() -> None:
    matches = _timed_matches()
    tracker = ActiveMatchTracker(matches)

    for timestamp in (0.0, 0.5, 1.5, 2.5, 3.0, 3.3, 4.6):
        expected = active_match_at(matches, timestamp)
        actual = tracker.at(timestamp)
        assert (actual or {}).get("id") == (expected or {}).get("id")


def test_active_match_at_prefers_higher_confidence_then_longer_duration() -> None:
    matches = [
        {
            "id": "shorter",
            "_start_time": 0.0,
            "_end_time": 2.0,
            "_confidence": 0.8,
            "_duration": 2.0,
        },
        {
            "id": "longer",
            "_start_time": 0.5,
            "_end_time": 3.0,
            "_confidence": 0.8,
            "_duration": 2.5,
        },
    ]

    assert active_match_at(matches, 1.0)["id"] == "longer"


import json
from unittest.mock import patch

import pytest

from qurantext.config.paths import PROJECT_ROOT
from qurantext.core.ass_renderer import _audio_encode_args, _probe_audio_codec, _wrap_ass_body_text
from qurantext.core.frame_renderer import (
    ActiveMatchTracker,
    _count_non_marker_words,
    active_match_at,
    active_word_timing_index,
    render_frame_pillow,
)
from qurantext.core.video_common import load_caption_segments, validated_matches

_BUNDLED_FONT = PROJECT_ROOT / "fonts" / "qaloon.10.ttf"


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


# ---------------------------------------------------------------------------
# _probe_audio_codec
# ---------------------------------------------------------------------------


def test_probe_audio_codec_parses_ffprobe_aac_output() -> None:
    fake_stdout = "aac\n192000\n"
    with (
        patch("qurantext.core.ass_renderer.require_binary", return_value="ffprobe"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value.stdout = fake_stdout
        codec, bitrate_kbps = _probe_audio_codec(__import__("pathlib").Path("audio.m4a"))

    assert codec == "aac"
    assert bitrate_kbps == 192


def test_probe_audio_codec_returns_empty_on_oserror() -> None:
    with (
        patch("qurantext.core.ass_renderer.require_binary", return_value="ffprobe"),
        patch("subprocess.run", side_effect=OSError("not found")),
    ):
        codec, bitrate_kbps = _probe_audio_codec(__import__("pathlib").Path("audio.m4a"))

    assert codec == ""
    assert bitrate_kbps == 0


# ---------------------------------------------------------------------------
# _audio_encode_args
# ---------------------------------------------------------------------------


def test_audio_encode_args_copies_aac_stream_when_bitrate_sufficient() -> None:
    with patch("qurantext.core.ass_renderer._probe_audio_codec", return_value=("aac", 192)):
        args = _audio_encode_args(__import__("pathlib").Path("audio.m4a"))
    assert args == ["-c:a", "copy"]


def test_audio_encode_args_reencodes_when_codec_is_not_aac() -> None:
    with patch("qurantext.core.ass_renderer._probe_audio_codec", return_value=("mp3", 320)):
        args = _audio_encode_args(__import__("pathlib").Path("audio.mp3"))
    assert args == ["-c:a", "aac", "-b:a", "192k"]


def test_audio_encode_args_reencodes_when_aac_bitrate_is_low() -> None:
    with patch("qurantext.core.ass_renderer._probe_audio_codec", return_value=("aac", 64)):
        args = _audio_encode_args(__import__("pathlib").Path("audio.m4a"))
    assert args == ["-c:a", "aac", "-b:a", "192k"]


# ---------------------------------------------------------------------------
# _wrap_ass_body_text
# ---------------------------------------------------------------------------


def test_wrap_ass_body_text_inserts_newlines_at_word_boundaries() -> None:
    long_text = "كلمة " * 20  # 20 words; each "كلمة " is 6 chars
    wrapped = _wrap_ass_body_text(long_text.strip(), max_chars=30)
    for line in wrapped.split("\n"):
        assert len(line) <= 30


def test_wrap_ass_body_text_short_text_unchanged() -> None:
    short_text = "بسم الله"
    assert _wrap_ass_body_text(short_text) == short_text


# ---------------------------------------------------------------------------
# word-highlight building blocks
# ---------------------------------------------------------------------------


def test_count_non_marker_words_skips_ayah_markers() -> None:
    assert _count_non_marker_words("الحمد لله ٧ رب العالمين ١") == 4
    assert _count_non_marker_words("") == 0


def test_validated_matches_bridges_gaps_between_groups() -> None:
    matches = [
        {"start_time": 0.0, "end_time": 2.0, "full_text": "ا"},
        # Gap from 2.0 -> 5.0 would render as black; should be bridged.
        {"start_time": 5.0, "end_time": 7.0, "full_text": "ب"},
    ]
    enriched = validated_matches(matches)
    assert enriched[0]["_end_time"] == 2.0
    assert enriched[1]["_start_time"] == 2.0  # pulled back to previous end
    assert enriched[1]["_end_time"] == 7.0
    assert enriched[1]["_duration"] == 5.0


def test_validated_matches_leaves_overlapping_groups_untouched() -> None:
    matches = [
        {"start_time": 0.0, "end_time": 3.0, "full_text": "ا"},
        {"start_time": 1.0, "end_time": 4.0, "full_text": "ب"},  # overlaps, no gap
    ]
    enriched = validated_matches(matches)
    assert enriched[1]["_start_time"] == 1.0


def test_validated_matches_no_bridge_preserves_original_times() -> None:
    # The frame renderer latches the centre card, so it disables bridging: each
    # match must keep its own detected start/end and the gap is left intact.
    matches = [
        {"start_time": 0.0, "end_time": 2.0, "full_text": "ا"},
        {"start_time": 5.0, "end_time": 7.0, "full_text": "ب"},
    ]
    enriched = validated_matches(matches, bridge_gaps=False)
    assert enriched[0]["_end_time"] == 2.0
    assert enriched[1]["_start_time"] == 5.0  # NOT pulled back to the previous end
    assert enriched[1]["_end_time"] == 7.0


def test_validated_matches_splits_long_pause_at_midpoint() -> None:
    # A long pause (gap 10.0s > 3.0s threshold) meets in the middle: previous
    # card holds to the midpoint, next card appears there.
    matches = [
        {"start_time": 0.0, "end_time": 2.0, "full_text": "ا"},
        {"start_time": 12.0, "end_time": 14.0, "full_text": "ب"},
    ]
    enriched = validated_matches(matches)
    assert enriched[0]["_end_time"] == 7.0  # 2.0 + 10.0/2
    assert enriched[1]["_start_time"] == 7.0
    assert enriched[1]["_end_time"] == 14.0


def test_active_word_timing_index_holds_last_started_during_silence() -> None:
    word_timings = [{"start": 0.0, "end": 1.0}, {"start": 2.0, "end": 3.0}]
    assert active_word_timing_index(word_timings, 0.5) == 0
    assert active_word_timing_index(word_timings, 1.5) == 0  # gap -> last started word
    assert active_word_timing_index(word_timings, 2.5) == 1
    assert active_word_timing_index(word_timings, -1.0) is None
    assert active_word_timing_index([], 0.0) is None


def test_load_caption_segments_reads_transcript(tmp_path) -> None:
    transcript = tmp_path / "lecture_whisperx_raw.json"
    transcript.write_text(
        json.dumps(
            {
                "segments": [
                    {"start": 1.0, "end": 3.0, "text": " يقول المحاضر "},
                    {"start": 5.0, "end": 6.5, "text": "ثم تلا الآية"},
                    {"start": 7.0, "end": 6.0, "text": "زمن غير صالح"},  # end < start → dropped
                ]
            }
        ),
        encoding="utf-8",
    )
    matches_file = tmp_path / "lecture_lecture.json"
    matches_file.write_text(
        json.dumps({"matches": [], "meta": {"whisperx_raw_output_path": str(transcript)}}),
        encoding="utf-8",
    )

    segments = load_caption_segments(matches_file)
    assert [s["text"] for s in segments] == ["يقول المحاضر", "ثم تلا الآية"]
    assert segments[0]["start"] == 1.0 and segments[0]["end"] == 3.0


def test_load_caption_segments_missing_meta_returns_empty(tmp_path) -> None:
    matches_file = tmp_path / "lecture_lecture.json"
    matches_file.write_text(json.dumps({"matches": []}), encoding="utf-8")
    assert load_caption_segments(matches_file) == []


@pytest.mark.skipif(not _BUNDLED_FONT.exists(), reason="bundled font missing")
def test_render_frame_pillow_placeholder_and_caption_render() -> None:
    from PIL import features

    if not features.check("raqm"):
        pytest.skip("Pillow built without libraqm")

    # match=None → placeholder title in the centre; caption_text → bottom band.
    frame = render_frame_pillow(
        0.0, None, 480, 320, _BUNDLED_FONT, caption_text="يقول المحاضر", title="القرآن الكريم"
    )
    assert frame.shape == (320, 480, 3)


def test_render_frame_pillow_placeholder_with_lecture_subtitle_renders() -> None:
    from PIL import features

    if not features.check("raqm"):
        pytest.skip("Pillow built without libraqm")

    frame = render_frame_pillow(
        0.0,
        None,
        480,
        320,
        _BUNDLED_FONT,
        caption_text="يقول المحاضر",
        title="سورة الأنفال",
        placeholder_subtitle="تدبر الآيات من الآية 7 إلى الآية 11",
    )
    assert frame.shape == (320, 480, 3)


def test_lecture_intro_lines_spans_ayah_range_within_surah() -> None:
    from qurantext.core.video_common import lecture_intro_lines

    matches = [
        {"surah_name": "سورة الأنفال", "from_ayah": 9, "to_ayah": 11, "_start_time": 10.0},
        {"surah_name": "سورة الأنفال", "from_ayah": 7, "to_ayah": 8, "_start_time": 2.0},
    ]
    assert lecture_intro_lines(matches) == (
        "سورة الأنفال",
        "تدبر الآيات من الآية 7 إلى الآية 11",
    )


def test_lecture_intro_lines_single_ayah() -> None:
    from qurantext.core.video_common import lecture_intro_lines

    matches = [{"surah_name": "سورة الفاتحة", "from_ayah": 5, "to_ayah": 5, "_start_time": 1.0}]
    assert lecture_intro_lines(matches) == ("سورة الفاتحة", "تدبر الآية 5")


def test_lecture_intro_lines_returns_none_without_ayah_numbers() -> None:
    from qurantext.core.video_common import lecture_intro_lines

    assert lecture_intro_lines([{"surah_name": "سورة الفاتحة", "_start_time": 1.0}]) is None
    assert lecture_intro_lines([]) is None


@pytest.mark.skipif(not _BUNDLED_FONT.exists(), reason="bundled font missing")
def test_render_frame_pillow_produces_valid_highlighted_frame() -> None:
    from PIL import features

    if not features.check("raqm"):
        pytest.skip("Pillow built without libraqm")

    match = {
        "surah_name": "سُورَةُ الفَاتِحَةِ",
        "from_ayah": 1,
        "to_ayah": 1,
        "_display_text": "الحمد لله رب العالمين",
        "_start_time": 0.0,
        "_end_time": 2.0,
        "_word_timings": [
            {"word": "الحمد", "start": 0.0, "end": 0.5},
            {"word": "لله", "start": 0.5, "end": 1.0},
        ],
    }
    # t=0.7 falls on the second word; should render without raising.
    frame = render_frame_pillow(0.7, match, 480, 320, _BUNDLED_FONT)
    assert frame.shape == (320, 480, 3)

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import qurantext.core.frame_renderer as frame_renderer
from qurantext.config.paths import DEFAULT_FONT_PATH
from qurantext.core.ass_renderer import _audio_encode_args, _probe_audio_codec, _wrap_ass_body_text
from qurantext.core.frame_renderer import (
    ActiveMatchTracker,
    _caption_window,
    _count_non_marker_words,
    active_match_at,
    active_word_timing_index,
    draw_caption_progressive,
    render_frame_pillow,
)
from qurantext.core.video_common import load_caption_segments, validated_matches

_BUNDLED_FONT = DEFAULT_FONT_PATH


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


def test_load_caption_segments_attaches_word_timings(tmp_path) -> None:
    transcript = tmp_path / "lecture_whisperx_raw.json"
    transcript.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "start": 1.0,
                        "end": 3.0,
                        "text": "يقول المحاضر",
                        "words": [
                            {"word": "يقول", "start": 1.0, "end": 1.8},
                            {"word": "المحاضر", "start": 1.8, "end": 3.0},
                        ],
                    }
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

    seg = load_caption_segments(matches_file)[0]
    # Text is rebuilt from the word tokens so token N lines up with timing N.
    assert seg["text"] == "يقول المحاضر"
    assert [w["word"] for w in seg["word_timings"]] == ["يقول", "المحاضر"]
    assert (seg["word_timings"][0]["start"], seg["word_timings"][0]["end"]) == (1.0, 1.8)


def test_caption_window_shows_all_words_when_within_cap() -> None:
    wt = [{"word": f"w{i}"} for i in range(5)]
    words, local = _caption_window(wt, active_idx=2, max_words=28)
    assert words == ["w0", "w1", "w2", "w3", "w4"]
    assert local == 2  # index unchanged when nothing is dropped


def test_caption_window_pages_long_caption_around_active_word() -> None:
    wt = [{"word": f"w{i}"} for i in range(33)]

    # Active word in the first chunk: show words 0..27, index unchanged.
    words, local = _caption_window(wt, active_idx=5, max_words=28)
    assert len(words) == 28 and words[0] == "w0" and words[-1] == "w27"
    assert local == 5

    # Active word in the second chunk: show the remainder, index made local.
    words, local = _caption_window(wt, active_idx=30, max_words=28)
    assert words == [f"w{i}" for i in range(28, 33)]
    assert local == 2  # 30 - 28

    # No active word yet -> first chunk, no local highlight.
    words, local = _caption_window(wt, active_idx=None, max_words=28)
    assert len(words) == 28 and local is None


def test_draw_caption_progressive_colours_words_by_spoken_state(monkeypatch) -> None:
    # Isolate the colour logic from Pillow measurement/drawing.
    monkeypatch.setattr(frame_renderer, "_multiline_metrics", lambda *a, **k: (0, 0))
    monkeypatch.setattr(frame_renderer, "measure_text_bbox", lambda *a, **k: (0, 10))
    captured: list[tuple[list[str], list[tuple]]] = []
    monkeypatch.setattr(
        frame_renderer,
        "draw_rtl_line_colored",
        lambda draw, words, fills, font, x0, x1, y: captured.append((words, fills)),
    )

    lines = ["قال المفسرون في", "هذه الآية"]  # 5 words: indices 0..4
    draw_caption_progressive(None, lines, None, (0, 0, 100, 100), 4, active_word_idx=2)
    fills = [f for _, line_fills in captured for f in line_fills]
    assert fills == [
        frame_renderer.COLOUR_CAPTION_TEXT,  # 0 spoken
        frame_renderer.COLOUR_CAPTION_TEXT,  # 1 spoken
        frame_renderer.COLOUR_CAPTION_ACTIVE,  # 2 active (soft cyan)
        frame_renderer.COLOUR_CAPTION_UPCOMING,  # 3 upcoming
        frame_renderer.COLOUR_CAPTION_UPCOMING,  # 4 upcoming
    ]

    # Before the first spoken word every token is upcoming.
    captured.clear()
    draw_caption_progressive(None, lines, None, (0, 0, 100, 100), 4, active_word_idx=None)
    fills = [f for _, line_fills in captured for f in line_fills]
    assert all(f == frame_renderer.COLOUR_CAPTION_UPCOMING for f in fills)


@pytest.mark.skipif(not _BUNDLED_FONT.exists(), reason="bundled font missing")
def test_render_frame_pillow_karaoke_caption_renders() -> None:
    from PIL import features

    if not features.check("raqm"):
        pytest.skip("Pillow built without libraqm")

    wt = [
        {"word": "يقول", "start": 0.0, "end": 0.5},
        {"word": "المحاضر", "start": 0.5, "end": 1.0},
    ]
    frame = render_frame_pillow(
        0.7,  # second word active
        None,
        480,
        320,
        _BUNDLED_FONT,
        caption_text="يقول المحاضر",
        caption_word_timings=wt,
    )
    assert frame.shape == (320, 480, 3)


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


def test_a_multi_ayah_header_joins_its_numbers_with_a_hyphen() -> None:
    """The bundled Qaloon font has no en dash; one drew as a blank ("الآيات 7  11")."""
    from qurantext.core.video_common import ayah_label

    label = ayah_label({"surah_name": "سورة الفرقان", "from_ayah": 7, "to_ayah": 11})
    assert label == "سورة الفرقان - الآيات 7 - 11"


@pytest.mark.skipif(not DEFAULT_FONT_PATH.exists(), reason="bundled font missing")
def test_every_header_and_intro_character_has_a_glyph_in_the_bundled_font() -> None:
    """A character the font lacks draws as nothing, and the header silently loses it.

    Marks (Mn), spaces (Zs) and format characters (Cf) have no ink of their own.
    """
    import unicodedata

    from PIL import ImageFont

    from qurantext.core.frame_renderer import DEFAULT_PLACEHOLDER_TITLE
    from qurantext.core.video_common import ayah_label, lecture_intro_lines

    font = ImageFont.truetype(str(DEFAULT_FONT_PATH), 40)
    intro_range = lecture_intro_lines(
        [{"surah_name": "سورة الأنفال", "from_ayah": 7, "to_ayah": 11, "_start_time": 0.0}]
    )
    intro_single = lecture_intro_lines(
        [{"surah_name": "سورة الفاتحة", "from_ayah": 5, "to_ayah": 5, "_start_time": 0.0}]
    )
    assert intro_range is not None and intro_single is not None
    texts = [
        ayah_label({"surah_name": "سورة الفرقان", "from_ayah": 7, "to_ayah": 11}),
        ayah_label({"surah_name": "سورة الفرقان", "from_ayah": 7, "to_ayah": 7}),
        ayah_label({"from_ayah": 7, "to_ayah": 11}),  # the unknown-surah name
        DEFAULT_PLACEHOLDER_TITLE,
        *intro_range,
        *intro_single,
    ]
    missing = {
        f"U+{ord(c):04X}"
        for text in texts
        for c in text
        if unicodedata.category(c) not in ("Mn", "Zs", "Cf") and font.getmask(c).getbbox() is None
    }
    assert not missing, sorted(missing)


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


# --- frame encoder (B3: frames stream straight into FFmpeg) -------------------

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


@pytest.mark.skipif(
    not (_FFMPEG and _FFPROBE and _BUNDLED_FONT.exists()),
    reason="needs ffmpeg, ffprobe and the bundled font",
)
def test_write_frame_video_produces_h264_with_audio_and_no_leftovers(tmp_path) -> None:
    """The renderer must emit a playable H.264 file in one encode.

    Frames used to go through an OpenCV MPEG-4 Part 2 intermediate that FFmpeg
    then decoded and re-encoded, which cost a second full encode and left a
    large temp file beside the user's output. This pins the replacement: correct
    codec, correct geometry, the audio carried through, and nothing left behind.
    """
    audio = tmp_path / "silence.m4a"
    subprocess.run(
        [
            _FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "2",
            "-c:a",
            "aac",
            str(audio),
        ],
        check=True,
    )

    output = tmp_path / "out.mp4"
    matches = validated_matches(
        [
            {
                "surah_num": 25,
                "surah_name": "سُورَةُ الفُرقَانِ",
                "from_ayah": 7,
                "to_ayah": 7,
                "full_text": "وَقَالُواْ مَالِ هَٰذَا اَ۬لرَّسُولِ",
                "confidence": 0.9,
                "start_time": 0.0,
                "end_time": 2.0,
            }
        ],
        bridge_gaps=False,
    )

    frame_renderer.write_frame_video(
        matches,
        2.0,
        audio,
        output,
        320,
        240,
        10,
        _BUNDLED_FONT,
        log_path=tmp_path / "enc.log",
    )

    assert output.exists() and output.stat().st_size > 0

    probe = subprocess.run(
        [
            _FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,codec_type,width,height",
            "-of",
            "csv=p=0",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "h264" in probe, probe
    assert "320,240" in probe.replace(" ", ""), probe
    assert "audio" in probe, probe

    # One encode, no silent intermediate anywhere near the deliverable.
    assert list(tmp_path.glob("*.silent.mp4")) == []


@pytest.mark.skipif(not _BUNDLED_FONT.exists(), reason="bundled font not present")
def test_write_frame_video_reports_ffmpeg_failure(tmp_path) -> None:
    """A dead encoder must surface FFmpeg's own output, not a bare exit code."""
    output = tmp_path / "out.mp4"
    with pytest.raises(RuntimeError) as excinfo:
        frame_renderer.write_frame_video(
            [],
            1.0,
            tmp_path / "missing-audio.m4a",
            output,
            160,
            120,
            5,
            _BUNDLED_FONT,
            log_path=tmp_path / "enc.log",
        )
    assert "FFmpeg" in str(excinfo.value)


# --- the look reaches every frame ----------------------------------------------


@pytest.mark.skipif(not _BUNDLED_FONT.exists(), reason="bundled font missing")
def test_render_frame_pillow_draws_the_highlight_in_the_looks_colour() -> None:
    from dataclasses import replace

    import numpy as np

    from qurantext.core.looks import NIGHT_GOLD

    magenta = (255, 0, 255, 255)
    look = replace(NIGHT_GOLD, highlight_word=magenta)
    match = {
        "surah_name": "سُورَةُ الفُرقَانِ",
        "from_ayah": 1,
        "to_ayah": 1,
        "_display_text": "تَبَٰرَكَ اَ۬لذِے نَزَّلَ",
        "_start_time": 0.0,
        "_end_time": 3.0,
        "_word_timings": [
            {"start": 0.0, "end": 1.0},
            {"start": 1.0, "end": 2.0},
            {"start": 2.0, "end": 3.0},
        ],
    }
    frame = render_frame_pillow(
        0.5, match, 540, 960, _BUNDLED_FONT, reserve_caption_band=False, look=look
    )
    bgr = np.array(frame)
    assert ((bgr[:, :, 2] == 255) & (bgr[:, :, 1] == 0) & (bgr[:, :, 0] == 255)).any()


@pytest.mark.skipif(
    not (_FFMPEG and _FFPROBE and _BUNDLED_FONT.exists()),
    reason="needs ffmpeg, ffprobe and the bundled font",
)
def test_write_frame_video_passes_the_look_to_every_frame(monkeypatch, tmp_path) -> None:
    from qurantext.core.looks import PRESETS

    seen = []
    real = frame_renderer.render_frame_pillow

    def spy(*args, **kwargs):
        seen.append(kwargs.get("look"))
        return real(*args, **kwargs)

    monkeypatch.setattr(frame_renderer, "render_frame_pillow", spy)
    audio = tmp_path / "silence.m4a"
    subprocess.run(
        [
            _FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "2",
            "-c:a",
            "aac",
            str(audio),
        ],
        check=True,
    )
    matches = validated_matches(
        [
            {
                "surah_num": 25,
                "surah_name": "سُورَةُ الفُرقَانِ",
                "from_ayah": 7,
                "to_ayah": 7,
                "full_text": "وَقَالُواْ مَالِ هَٰذَا اَ۬لرَّسُولِ",
                "confidence": 0.9,
                "start_time": 0.0,
                "end_time": 2.0,
            }
        ],
        bridge_gaps=False,
    )

    warnings = frame_renderer.write_frame_video(
        matches,
        2.0,
        audio,
        tmp_path / "out.mp4",
        320,
        240,
        10,
        _BUNDLED_FONT,
        log_path=tmp_path / "enc.log",
        look=PRESETS["ocean"],
    )

    assert seen and all(look is PRESETS["ocean"] for look in seen)
    assert warnings == ()


def test_write_frame_video_reports_the_warnings_its_frames_saw(monkeypatch, tmp_path) -> None:
    """Taken before the encode: an image that appears mid-render does not erase the warning."""
    import io
    from dataclasses import replace

    import numpy as np
    from PIL import Image

    from qurantext.core.backgrounds import clear_cache
    from qurantext.core.looks import NIGHT_GOLD

    clear_cache()
    image = tmp_path / "bg.png"
    look = replace(NIGHT_GOLD, background=replace(NIGHT_GOLD.background, kind="image", image=image))

    def fake_frame(t, match, width, height, font_file, **kwargs):
        Image.new("RGB", (8, 8), (255, 0, 0)).save(image)  # the photo turns up mid-render
        return np.zeros((height, width, 3), np.uint8)

    class _Encoder:
        stdin = io.BytesIO()
        returncode = 0

        def wait(self):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(frame_renderer, "render_frame_pillow", fake_frame)
    monkeypatch.setattr(frame_renderer, "_start_frame_encoder", lambda *a, **k: _Encoder())
    warnings = frame_renderer.write_frame_video(
        [],
        1.0,
        tmp_path / "a.m4a",
        tmp_path / "o.mp4",
        32,
        24,
        10,
        _BUNDLED_FONT,
        log_path=tmp_path / "enc.log",
        look=look,
    )
    clear_cache()
    assert warnings == ("image_missing",)


def test_render_frame_video_passes_the_look_and_collects_its_warnings(
    monkeypatch, tmp_path
) -> None:
    from qurantext.core.looks import PRESETS

    seen = {}

    def fake_write(*args, **kwargs):
        seen.update(kwargs)
        return ("image_unreadable",)

    monkeypatch.setattr(frame_renderer, "write_frame_video", fake_write)
    monkeypatch.setattr(frame_renderer, "_require_raqm_support", lambda: None)
    monkeypatch.setattr(frame_renderer, "require_binary", lambda *a, **k: None)
    monkeypatch.setattr(frame_renderer, "get_audio_duration", lambda _path: 3.0)
    collected: list[str] = ["earlier"]

    duration = frame_renderer.render_frame_video(
        tmp_path / "a.m4a",
        [],
        tmp_path / "o.mp4",
        32,
        24,
        10,
        _BUNDLED_FONT,
        look=PRESETS["rose"],
        look_warnings=collected,
    )

    assert duration == 3.0
    assert seen["look"] is PRESETS["rose"]
    assert collected == ["earlier", "image_unreadable"]
    # Without a list the warnings are simply not collected; the return stays the duration.
    assert (
        frame_renderer.render_frame_video(
            tmp_path / "a.m4a", [], tmp_path / "o.mp4", 32, 24, 10, _BUNDLED_FONT
        )
        == 3.0
    )
    assert seen["look"] is frame_renderer.NIGHT_GOLD


# --- locating helper binaries -------------------------------------------------


def test_a_packaged_app_uses_the_ffmpeg_it_shipped_with(tmp_path, monkeypatch) -> None:
    """Someone who double-clicks an app has put nothing on PATH.

    A packaged build ships FFmpeg beside its own executable, and must prefer it
    so the version it was tested against is the one that runs.
    """
    from qurantext.core import video_common

    app_dir = tmp_path / "app"
    app_dir.mkdir()
    shipped = app_dir / "ffmpeg"
    shipped.write_text("#!/bin/sh\n", encoding="utf-8")
    shipped.chmod(0o755)

    monkeypatch.setattr(video_common.sys, "frozen", True, raising=False)
    monkeypatch.setattr(video_common.sys, "executable", str(app_dir / "qalun"))

    assert video_common.require_binary("ffmpeg") == str(shipped)


def test_windows_executables_are_found_too(tmp_path, monkeypatch) -> None:
    from qurantext.core import video_common

    app_dir = tmp_path / "app"
    app_dir.mkdir()
    shipped = app_dir / "ffprobe.exe"
    shipped.write_text("", encoding="utf-8")

    monkeypatch.setattr(video_common.sys, "frozen", True, raising=False)
    monkeypatch.setattr(video_common.sys, "executable", str(app_dir / "qalun.exe"))

    assert video_common.require_binary("ffprobe") == str(shipped)


def test_a_normal_install_still_uses_path(monkeypatch) -> None:
    from qurantext.core import video_common

    monkeypatch.delattr(video_common.sys, "frozen", raising=False)
    assert video_common.bundled_binary_dir() is None
    # ffmpeg is a hard requirement of the suite's render tests, so it is present.
    if shutil.which("ffmpeg"):
        assert video_common.require_binary("ffmpeg") == shutil.which("ffmpeg")


def test_a_missing_binary_says_where_it_looked(monkeypatch) -> None:
    from qurantext.core import video_common

    monkeypatch.delattr(video_common.sys, "frozen", raising=False)
    monkeypatch.setattr(video_common.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="in PATH"):
        video_common.require_binary("definitely-not-a-real-binary", "Install it.")


def test_active_caption_index_is_the_latest_started_cue_if_it_still_covers_t() -> None:
    from qurantext.core.frame_renderer import active_caption_index

    # Out of order on purpose: the rule is by start time, the index is the input's.
    captions = [
        {"text": "second", "start": 2.0, "end": 4.0},
        {"text": "first", "start": 0.0, "end": 3.0},
        {"text": "late", "start": 6.0, "end": 6.5},
    ]
    assert active_caption_index(captions, 1.0) == 1
    assert active_caption_index(captions, 2.5) == 0
    assert active_caption_index(captions, 5.0) is None
    assert active_caption_index(captions, -1.0) is None
    assert active_caption_index([], 1.0) is None


@pytest.mark.skipif(not _BUNDLED_FONT.exists(), reason="bundled font not present")
def test_overlapping_captions_the_renderer_the_preview_and_the_review_agree(
    tmp_path, monkeypatch
) -> None:
    import io

    import numpy as np

    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs import preview as preview_module
    from qurantext.jobs.project import CaptionCue, Project

    captions = [
        {"text": "first", "start": 0.0, "end": 3.0, "word_timings": []},
        {"text": "second", "start": 2.0, "end": 4.0, "word_timings": []},
    ]
    at = 2.5
    drawn: list[tuple[float, str]] = []

    def fake_frame(t, match, width, height, font_file, **kwargs):
        drawn.append((t, kwargs.get("caption_text", "")))
        return np.zeros((height, width, 3), np.uint8)

    class _Encoder:
        stdin = io.BytesIO()
        returncode = 0

        def wait(self):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(frame_renderer, "render_frame_pillow", fake_frame)
    monkeypatch.setattr(frame_renderer, "_start_frame_encoder", lambda *a, **k: _Encoder())
    frame_renderer.write_frame_video(
        [],
        5.0,
        tmp_path / "a.m4a",
        tmp_path / "o.mp4",
        32,
        24,
        10,
        _BUNDLED_FONT,
        captions=captions,
        log_path=tmp_path / "enc.log",
    )
    rendered = [text for t, text in drawn if t <= at][-1]

    drawn.clear()
    matches = tmp_path / "m.json"
    matches.write_text(json.dumps({"matches": [], "meta": {"mode": "lecture"}}), encoding="utf-8")
    monkeypatch.setattr(preview_module, "load_caption_segments", lambda _path: captions)
    preview_module.render_preview(
        preview_module.PreviewRequest(
            matches=matches,
            output=tmp_path / "p.png",
            at=at,
            width=32,
            height=24,
            font_file=_BUNDLED_FONT,
        )
    )
    previewed = drawn[-1][1]

    session = ReviewSession(
        Project(
            audio=tmp_path / "a.m4a",
            mode="lecture",
            captions=[CaptionCue(c["start"], c["end"], c["text"]) for c in captions],
        )
    )
    reviewed = session.project.captions[session.caption_at(at)].text

    assert rendered == previewed == reviewed == "second"


def test_write_frame_video_hands_one_layer_to_every_frame(monkeypatch, tmp_path) -> None:
    """The layer is fetched once; an eviction mid-render cannot rebuild it for later frames."""
    import io

    import numpy as np

    from qurantext.core import backgrounds
    from qurantext.core.looks import PRESETS

    builds = []
    real_base_layer = backgrounds.base_layer

    def counting_base_layer(*args, **kwargs):
        builds.append(args)
        return real_base_layer(*args, **kwargs)

    seen = []

    def fake_frame(t, match, width, height, font_file, **kwargs):
        seen.append(kwargs.get("base"))
        backgrounds.clear_cache()  # another surface evicts the layer mid-render
        return np.zeros((height, width, 3), np.uint8)

    class _Encoder:
        stdin = io.BytesIO()
        returncode = 0

        def wait(self):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(backgrounds, "base_layer", counting_base_layer)
    monkeypatch.setattr(frame_renderer, "render_frame_pillow", fake_frame)
    monkeypatch.setattr(frame_renderer, "_start_frame_encoder", lambda *a, **k: _Encoder())
    captions = [
        {"start": 0.0, "end": 0.5, "text": "one"},
        {"start": 0.5, "end": 1.0, "text": "two"},
    ]
    frame_renderer.write_frame_video(
        [],
        1.0,
        tmp_path / "a.m4a",
        tmp_path / "o.mp4",
        32,
        24,
        10,
        _BUNDLED_FONT,
        captions=captions,
        log_path=tmp_path / "enc.log",
        look=PRESETS["ocean"],
    )
    backgrounds.clear_cache()
    assert len(seen) >= 2
    assert all(base is seen[0] for base in seen) and seen[0] is not None
    assert len(builds) == 1


@pytest.mark.skipif(not _BUNDLED_FONT.exists(), reason="needs the bundled font")
def test_render_frame_pillow_draws_on_the_layer_it_is_handed() -> None:
    import numpy as np

    from qurantext.core.looks import NIGHT_GOLD, PRESETS

    ocean = frame_renderer.frame_base_layer(PRESETS["ocean"], 120, 80, reserve_caption_band=True)
    handed = render_frame_pillow(0.0, None, 120, 80, _BUNDLED_FONT, look=NIGHT_GOLD, base=ocean)
    looked_up = render_frame_pillow(0.0, None, 120, 80, _BUNDLED_FONT, look=NIGHT_GOLD)
    corner = np.array(ocean.image.convert("RGB"))[0, 0][::-1]  # the frame is BGR
    assert tuple(handed[0, 0]) == tuple(corner)
    assert tuple(handed[0, 0]) != tuple(looked_up[0, 0])


def _card(surah, ayah, start, end, name=None):
    return {
        "surah_num": surah,
        "surah_name": name or f"surah {surah}",
        "from_ayah": ayah,
        "to_ayah": ayah,
        "full_text": f"{surah}:{ayah}",
        "start_time": start,
        "end_time": end,
    }


def test_a_lecture_shows_only_the_surah_it_studies() -> None:
    """A quote from another surah explains the ayah at hand; it is not the ayah at hand."""
    from qurantext.core.video_common import cards_on_screen

    cards = [
        _card(17, 23, 0.0, 4.0),  # an opening quote, before the studied surah starts
        _card(25, 7, 5.0, 15.0),
        _card(17, 48, 16.0, 20.0),
        _card(25, 8, 21.0, 30.0),
    ]
    assert [(c["surah_num"], c["from_ayah"]) for c in cards_on_screen(cards, "lecture")] == [
        (25, 7),
        (25, 8),
    ]


def test_the_studied_surah_is_the_one_with_the_most_time_not_the_most_cards() -> None:
    from qurantext.core.video_common import cards_on_screen

    cards = [
        _card(2, 255, 0.0, 1.0),
        _card(2, 256, 1.0, 2.0),
        _card(2, 257, 2.0, 3.0),
        _card(25, 7, 3.0, 20.0),
    ]
    assert [c["surah_num"] for c in cards_on_screen(cards, "lecture")] == [25]


def test_a_tie_goes_to_the_surah_heard_first() -> None:
    from qurantext.core.video_common import cards_on_screen

    cards = [_card(25, 7, 0.0, 5.0), _card(17, 48, 5.0, 10.0)]
    assert [c["surah_num"] for c in cards_on_screen(cards, "lecture")] == [25]


def test_validated_cards_are_filtered_by_their_own_times() -> None:
    from qurantext.core.video_common import cards_on_screen

    cards = validated_matches(
        [
            dict(_card(25, 7, 0.0, 9.0), full_text="x"),
            dict(_card(17, 48, 9.0, 10.0), full_text="y"),
        ],
        bridge_gaps=False,
    )
    assert [c["surah_num"] for c in cards_on_screen(cards, "lecture")] == [25]


def test_cards_without_a_surah_are_kept() -> None:
    from qurantext.core.video_common import cards_on_screen

    preamble = {"kind": "preamble", "start_time": 0.0, "end_time": 2.0}
    cards = [preamble, _card(25, 7, 2.0, 9.0), _card(17, 48, 9.0, 10.0)]
    assert cards_on_screen(cards, "lecture") == cards[:2]


def test_a_recitation_keeps_every_card() -> None:
    """A recitation states its own range; nothing in it is a quotation."""
    from qurantext.core.video_common import cards_on_screen

    cards = [_card(25, 75, 0.0, 9.0), _card(26, 1, 9.0, 10.0)]
    assert cards_on_screen(cards, "recitation") == cards
    assert cards_on_screen(cards, None) == cards


def test_a_chosen_surah_overrides_the_guess() -> None:
    """The guess would keep al-Furqan (heard longest); the person said al-Isra."""
    from qurantext.core.video_common import cards_on_screen

    cards = [_card(25, 7, 0.0, 15.0), _card(17, 48, 15.0, 20.0), _card(25, 8, 20.0, 30.0)]
    assert [c["surah_num"] for c in cards_on_screen(cards, "lecture")] == [25, 25]
    assert [c["surah_num"] for c in cards_on_screen(cards, "lecture", 17)] == [17]


def test_a_chosen_surah_applies_even_when_only_one_surah_was_heard() -> None:
    from qurantext.core.video_common import cards_on_screen

    cards = [_card(2, 255, 0.0, 9.0), _card(2, 256, 9.0, 10.0)]
    assert cards_on_screen(cards, "lecture") == cards, "the guess keeps the only surah"
    assert cards_on_screen(cards, "lecture", 25) == [], "the choice is obeyed as given"


def test_a_chosen_surah_with_no_card_leaves_only_the_surah_less_ones() -> None:
    from qurantext.core.video_common import cards_on_screen, has_surah_cards

    preamble = {"kind": "preamble", "start_time": 0.0, "end_time": 2.0}
    cards = [preamble, _card(25, 7, 2.0, 9.0), _card(17, 48, 9.0, 10.0)]
    assert cards_on_screen(cards, "lecture", 1) == [preamble]
    assert not has_surah_cards(cards, 1) and has_surah_cards(cards, 17)


def test_a_chosen_surah_keeps_cards_without_a_surah() -> None:
    from qurantext.core.video_common import cards_on_screen

    preamble = {"kind": "preamble", "start_time": 0.0, "end_time": 2.0}
    cards = [preamble, _card(25, 7, 2.0, 9.0), _card(17, 48, 9.0, 10.0)]
    assert cards_on_screen(cards, "lecture", 17) == [preamble, cards[2]]


def test_a_recitation_ignores_a_chosen_surah() -> None:
    from qurantext.core.video_common import cards_on_screen

    cards = [_card(25, 75, 0.0, 9.0), _card(26, 1, 9.0, 10.0)]
    assert cards_on_screen(cards, "recitation", 26) == cards


def test_a_manual_card_from_another_surah_is_kept_under_the_automatic_rule() -> None:
    from qurantext.core.video_common import cards_on_screen

    cards = [
        _card(25, 7, 0.0, 30.0),
        _card(25, 8, 30.0, 60.0),
        {**_card(2, 255, 60.0, 65.0), "manual": True},
        _card(2, 256, 65.0, 66.0),  # a detected quote from another surah
    ]
    refs = [(c["surah_num"], c["from_ayah"]) for c in cards_on_screen(cards, "lecture")]
    assert (2, 255) in refs and (2, 256) not in refs


def test_a_manual_card_is_kept_under_a_chosen_surah() -> None:
    from qurantext.core.video_common import cards_on_screen

    cards = [_card(25, 7, 0.0, 30.0), {**_card(2, 255, 30.0, 35.0), "manual": True}]
    shown = cards_on_screen(cards, "lecture", studied_surah=25)
    assert [(c["surah_num"], c["from_ayah"]) for c in shown] == [(25, 7), (2, 255)]


def test_manual_cards_do_not_vote_in_the_automatic_guess() -> None:
    from qurantext.core.video_common import cards_on_screen

    cards = [
        _card(25, 7, 0.0, 10.0),
        {**_card(2, 255, 10.0, 60.0), "manual": True},  # on screen longest, but by hand
        _card(25, 8, 60.0, 65.0),
        _card(3, 1, 65.0, 66.0),  # a detected quote: hidden, so a guess was made
    ]
    shown = cards_on_screen(cards, "lecture")
    assert [(c["surah_num"], c["from_ayah"]) for c in shown] == [(25, 7), (2, 255), (25, 8)]


def _explained_lecture() -> list[dict]:
    """15 detected 10 s quotes of surah 25, then 2:255 placed by hand for 5 minutes."""
    cards = [_card(25, 1 + i, 20.0 * i, 20.0 * i + 10.0) for i in range(15)]
    cards.append({**_card(2, 255, 300.0, 600.0), "manual": True})
    return cards


def test_one_long_manual_cross_reference_does_not_hide_the_detected_quotes() -> None:
    """The review's case: a 300 s explanation card outweighs 150 s of quotes if it votes."""
    from qurantext.core.video_common import cards_on_screen

    shown = cards_on_screen(_explained_lecture(), "lecture")
    refs = [(c["surah_num"], c["from_ayah"]) for c in shown]
    assert refs == [(25, 1 + i) for i in range(15)] + [(2, 255)]


def test_the_review_session_keeps_the_detected_quotes_beside_a_long_manual_card() -> None:
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import Project

    session = ReviewSession(
        Project(audio=Path("dars.mp3"), mode="lecture", cards=_explained_lecture())
    )
    refs = [(c["surah_num"], c["from_ayah"]) for c in session.validated_cards()]
    assert refs == [(25, 1 + i) for i in range(15)] + [(2, 255)]


def test_only_a_json_true_makes_a_card_manual_everywhere() -> None:
    """One predicate: the window's mark and the video's filter agree on ``"manual": 1``."""
    from qurantext.core.video_common import cards_on_screen, is_manual_card
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import Project

    cards = [_card(25, 7, 0.0, 30.0), {**_card(2, 255, 30.0, 35.0), "manual": 1}]
    assert not is_manual_card(cards[1])
    assert (
        ReviewSession(Project(audio=Path("a.mp3"), mode="lecture", cards=cards)).is_manual(1)
        is False
    )
    assert cards_on_screen(cards, "lecture", studied_surah=25) == [cards[0]]


def _intro_cards() -> list[dict]:
    """Surah 25's detected 7–10, with 2:255 placed by hand before them."""
    return [
        {**_card(2, 255, 5.0, 9.0, name="سورة البقرة"), "manual": True},
        _card(25, 7, 10.0, 20.0, name="سورة الفرقان"),
        _card(25, 10, 20.0, 30.0, name="سورة الفرقان"),
    ]


@pytest.mark.parametrize("studied", [25, None], ids=["chosen", "guessed"])
def test_the_opening_title_announces_the_detected_surah_not_a_manual_card_before_it(
    studied,
) -> None:
    from qurantext.core.frame_renderer import placeholder_lines
    from qurantext.core.video_common import cards_on_screen, validated_matches

    shown = cards_on_screen(
        validated_matches(_intro_cards(), bridge_gaps=False), "lecture", studied
    )
    assert placeholder_lines(shown, reserve_caption_band=True) == (
        "سورة الفرقان",
        "تدبر الآيات من الآية 7 إلى الآية 10",
    )


def test_the_opening_title_falls_back_to_manual_cards_when_no_detected_card_names_a_surah() -> None:
    from qurantext.core.video_common import lecture_intro_lines

    preamble = {"kind": "preamble", "_start_time": 0.0}
    manual = {
        "surah_name": "سورة البقرة",
        "from_ayah": 255,
        "to_ayah": 256,
        "_start_time": 5.0,
        "manual": True,
    }
    assert lecture_intro_lines([preamble, manual]) == (
        "سورة البقرة",
        "تدبر الآيات من الآية 255 إلى الآية 256",
    )


def test_a_manual_card_of_the_announced_surah_widens_the_span() -> None:
    from qurantext.core.video_common import lecture_intro_lines

    matches = [
        {"surah_name": "سورة الفرقان", "from_ayah": 7, "to_ayah": 7, "_start_time": 1.0},
        {
            "surah_name": "سورة الفرقان",
            "from_ayah": 3,
            "to_ayah": 3,
            "_start_time": 9.0,
            "manual": True,
        },
    ]
    assert lecture_intro_lines(matches) == ("سورة الفرقان", "تدبر الآيات من الآية 3 إلى الآية 7")


_MANUAL_LECTURE = [
    _card(25, 7, 0.0, 3.0),
    {**_card(2, 255, 4.0, 7.0), "manual": True},
    _card(25, 8, 7.0, 8.0),
]


@pytest.mark.skipif(not _BUNDLED_FONT.exists(), reason="bundled font not present")
def test_a_manual_card_from_another_surah_is_drawn_by_export_preview_and_review(
    tmp_path, monkeypatch, no_basmala
) -> None:
    """A hand-made card from another surah shows everywhere, even under a chosen surah."""
    import io

    import numpy as np

    from qurantext.core.subtitles import card_ref
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.preview import PreviewRequest, render_preview
    from qurantext.jobs.project import Project
    from qurantext.jobs.render import RenderRequest, render_video
    from tests.media_helpers import MEDIA_AVAILABLE, MEDIA_REASON, build_job

    if not MEDIA_AVAILABLE:
        pytest.skip(MEDIA_REASON)
    audio, matches = build_job(tmp_path, seconds=8.0)
    matches.write_text(
        json.dumps({"matches": _MANUAL_LECTURE, "meta": {"mode": "lecture"}}),
        encoding="utf-8",
    )
    drawn: list[tuple[float, str | None]] = []

    def fake_frame(t, match, width, height, font_file, **kwargs):
        drawn.append((t, card_ref(match) if match else None))
        return np.zeros((height, width, 3), np.uint8)

    class _Encoder:
        stdin = io.BytesIO()
        returncode = 0

        def wait(self):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(frame_renderer, "render_frame_pillow", fake_frame)
    monkeypatch.setattr(frame_renderer, "_start_frame_encoder", lambda *a, **k: _Encoder())
    render_video(
        RenderRequest(
            audio=audio,
            matches=matches,
            output=tmp_path / "v.mp4",
            width=32,
            height=24,
            fps=10,
            font_file=_BUNDLED_FONT,
            studied_surah=25,
        )
    )
    rendered = list(drawn)
    project = Project(
        audio=audio,
        mode="lecture",
        cards=[dict(c) for c in _MANUAL_LECTURE],
        export={"studied_surah": 25},
    )
    session = ReviewSession(project)

    for at in (1.05, 5.05, 7.55):
        exported = [ref for t, ref in rendered if t <= at + 1e-9][-1]
        previewed = render_preview(
            PreviewRequest(
                matches=matches,
                output=tmp_path / "p.png",
                at=at,
                width=32,
                height=24,
                font_file=_BUNDLED_FONT,
                studied_surah=25,
            )
        ).card
        card = session.frame_inputs(at)[0]
        reviewed = card_ref(card) if card else None
        assert exported == previewed == reviewed, at
        if at == 5.05:
            assert reviewed == "2:255"


# The shapes a review fuzz found the export and the review disagreeing on: a card
# with no time on screen, and one with no text, both counted toward the guess in
# the export (which picks before validating) but not in the review (after).
_DEGENERATE_LECTURE = [
    dict(_card(2, 1, 0.0, 0.0), full_text="a"),
    dict(_card(1, 1, 3.0, 3.0), full_text="b"),
    dict(_card(1, 2, 5.0, 5.0), full_text="c"),
    dict(_card(2, 2, 5.0, 7.0), full_text="d"),
    dict(_card(3, 1, 1.0, 3.0), full_text="e"),
    dict(_card(2, 3, 7.0, 7.5), full_text=""),  # no display text
]


@pytest.mark.parametrize("chosen", [None, 1, 2, 3])
def test_picking_before_or_after_validation_keeps_the_same_cards(chosen, capsys) -> None:
    from qurantext.core.video_common import cards_on_screen

    def ids(cards):
        return sorted((c["surah_num"], c["from_ayah"]) for c in cards)

    cards = [dict(c) for c in _DEGENERATE_LECTURE]
    export = validated_matches(cards_on_screen(cards, "lecture", chosen), bridge_gaps=False)
    review = cards_on_screen(validated_matches(cards, bridge_gaps=False), "lecture", chosen)
    assert ids(export) == ids(review)
    if chosen is None:
        assert ids(review) == [(3, 1)], "a tie of 2s each goes to al-Imran's first hearing"


def test_a_chosen_surah_whose_only_cards_cannot_be_drawn_counts_as_missing() -> None:
    from qurantext.core.video_common import has_surah_cards

    assert not has_surah_cards(_DEGENERATE_LECTURE, 1), "both of its cards last no time"
    assert has_surah_cards(_DEGENERATE_LECTURE, 2)


@pytest.mark.skipif(not _BUNDLED_FONT.exists(), reason="bundled font not present")
@pytest.mark.parametrize("chosen", [None, 2])
def test_the_export_the_preview_and_the_review_show_the_same_lecture_card(
    tmp_path, monkeypatch, no_basmala, chosen
) -> None:
    """One lecture, one rule: every surface draws the same card at the same moment."""
    import io

    import numpy as np

    from qurantext.core.subtitles import card_ref
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.preview import PreviewRequest, render_preview
    from qurantext.jobs.project import Project
    from qurantext.jobs.render import RenderRequest, render_video
    from tests.media_helpers import MEDIA_AVAILABLE, MEDIA_REASON, build_job

    if not MEDIA_AVAILABLE:
        pytest.skip(MEDIA_REASON)
    audio, matches = build_job(tmp_path, seconds=8.0)
    matches.write_text(
        json.dumps({"matches": _DEGENERATE_LECTURE, "meta": {"mode": "lecture"}}),
        encoding="utf-8",
    )
    drawn: list[tuple[float, str | None]] = []

    def fake_frame(t, match, width, height, font_file, **kwargs):
        drawn.append((t, card_ref(match) if match else None))
        return np.zeros((height, width, 3), np.uint8)

    class _Encoder:
        stdin = io.BytesIO()
        returncode = 0

        def wait(self):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(frame_renderer, "render_frame_pillow", fake_frame)
    monkeypatch.setattr(frame_renderer, "_start_frame_encoder", lambda *a, **k: _Encoder())
    render_video(
        RenderRequest(
            audio=audio,
            matches=matches,
            output=tmp_path / "v.mp4",
            width=32,
            height=24,
            fps=10,
            font_file=_BUNDLED_FONT,
            studied_surah=chosen,
        )
    )
    rendered = list(drawn)
    project = Project(
        audio=audio,
        mode="lecture",
        cards=[dict(c) for c in _DEGENERATE_LECTURE],
        export={} if chosen is None else {"studied_surah": chosen},
    )
    session = ReviewSession(project)

    for at in (0.55, 2.05, 4.05, 6.05, 7.75):
        exported = [ref for t, ref in rendered if t <= at + 1e-9][-1]
        previewed = render_preview(
            PreviewRequest(
                matches=matches,
                output=tmp_path / "p.png",
                at=at,
                width=32,
                height=24,
                font_file=_BUNDLED_FONT,
                studied_surah=chosen,
            )
        ).card
        card = session.frame_inputs(at)[0]
        reviewed = card_ref(card) if card else None
        assert exported == previewed == reviewed, at
    expected = "3:1" if chosen is None else "2:2"
    assert reviewed == expected

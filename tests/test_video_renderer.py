import json
import shutil
import subprocess
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

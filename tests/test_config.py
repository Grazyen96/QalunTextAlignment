from pathlib import Path

from qurantext.cli.main import build_parser as build_cli_parser
from qurantext.config.paths import ensure_required_directories
from qurantext.config.settings import get_settings
from qurantext.pipelines.detection import build_parser as build_detection_parser


def test_ensure_required_directories_creates_standard_tree() -> None:
    ensure_required_directories()

    for relative_path in (
        Path("input/quran"),
        Path("input/lectures"),
        Path("input/recitations"),
        Path("output/videos"),
        Path("output/recitation_matching"),
        Path("output/lecture_matching"),
        Path("output/whisperx_transcripts"),
        Path("output/range_matching"),
    ):
        assert relative_path.is_dir()


def test_get_settings_reads_matching_and_video_env_overrides(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("QURANTEXT_RANGE_HEAD_WORDS", "12")
    monkeypatch.setenv("QURANTEXT_RANGE_SEARCH_RANGE", "7")
    monkeypatch.setenv("QURANTEXT_LECTURE_THRESHOLD", "0.66")
    monkeypatch.setenv("QURANTEXT_VIDEO_WIDTH", "1280")
    monkeypatch.setenv("QURANTEXT_VIDEO_RENDERER", "frame")

    settings = get_settings()

    assert settings.range_matching.head_words == 12
    assert settings.range_matching.search_range == 7
    assert settings.lecture_matching.min_score == 0.66
    assert settings.video.width == 1280
    assert settings.video.renderer == "frame"

    get_settings.cache_clear()


def test_cli_parsers_use_centralized_settings_defaults(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("QURANTEXT_RANGE_TAIL_WORDS", "14")
    monkeypatch.setenv("QURANTEXT_LECTURE_MAX_SPAN", "8")
    monkeypatch.setenv("QURANTEXT_VIDEO_FPS", "30")

    detection_args = build_detection_parser().parse_args(
        ["--quran", "sample.txt", "--whisperx", "sample.json"]
    )
    cli_args = build_cli_parser().parse_args(
        ["generate-video", "--audio", "a.mp3", "--matches", "m.json"]
    )

    assert detection_args.tail_words == 14
    assert detection_args.max_span == 8
    assert cli_args.fps == 30


def test_default_video_settings_are_frame_renderer_720p(monkeypatch) -> None:
    get_settings.cache_clear()
    # Clear any overrides so the compiled-in defaults apply.
    for key in ("QURANTEXT_VIDEO_RENDERER", "QURANTEXT_VIDEO_WIDTH", "QURANTEXT_VIDEO_HEIGHT"):
        monkeypatch.delenv(key, raising=False)

    settings = get_settings()

    assert settings.video.renderer == "frame"
    assert settings.video.width == 1280
    assert settings.video.height == 720

    get_settings.cache_clear()

    get_settings.cache_clear()


from pathlib import Path

from qurantext.cli.main import build_parser as build_cli_parser
from qurantext.config.paths import ensure_required_directories
from qurantext.config.settings import VIDEO_PRESETS, get_settings


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
    """One parser now, and it must still read its defaults from settings.

    detection and video rendering each carried their own argparse CLI with
    independently drifting defaults; both are gone and `qurantext` is the only
    parser. These are the same assertions, made against it.
    """
    get_settings.cache_clear()
    monkeypatch.setenv("QURANTEXT_RANGE_TAIL_WORDS", "14")
    monkeypatch.setenv("QURANTEXT_LECTURE_MAX_SPAN", "8")
    monkeypatch.setenv("QURANTEXT_VIDEO_FPS", "30")

    detection_args = build_cli_parser().parse_args(
        ["range-match", "--quran", "sample.txt", "--whisperx", "sample.json"]
    )
    cli_args = build_cli_parser().parse_args(
        ["generate-video", "--audio", "a.mp3", "--matches", "m.json"]
    )
    # width/height/fps resolve in _resolve_preset (parse-time default is None so
    # explicit flags can be told apart from defaults), but the env override must
    # still flow through the centralized settings.
    from qurantext.cli.main import _resolve_preset

    _resolve_preset(cli_args)

    assert detection_args.tail_words == 14
    assert detection_args.max_span == 8
    assert cli_args.fps == 30
    # The `--whisperx` alias the compatibility shims forward still resolves.
    assert detection_args.whisperx_json == "sample.json"


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


def test_video_presets_contains_expected_keys() -> None:
    assert set(VIDEO_PRESETS) >= {"fast", "standard", "high", "social"}
    for name, (w, h, fps) in VIDEO_PRESETS.items():
        assert w > 0 and h > 0 and fps > 0, f"preset '{name}' has invalid values"


def test_preset_flag_overrides_width_height_fps_in_cli() -> None:
    get_settings.cache_clear()
    args = build_cli_parser().parse_args(
        ["generate-video", "--audio", "a.mp3", "--matches", "m.json", "--preset", "high"]
    )
    from qurantext.cli.main import _resolve_preset

    _resolve_preset(args)

    w, h, f = VIDEO_PRESETS["high"]
    assert args.width == w
    assert args.height == h
    assert args.fps == f

    get_settings.cache_clear()

    get_settings.cache_clear()


def test_lecture_render_defaults_to_portrait_social_preset() -> None:
    get_settings.cache_clear()
    from qurantext.cli.main import _resolve_preset

    args = build_cli_parser().parse_args(
        ["run-all", "--quran", "q.txt", "--audio", "a.wav", "--mode", "lecture", "--render-video"]
    )
    _resolve_preset(args)

    sw, sh, sf = VIDEO_PRESETS["social"]
    assert (args.width, args.height, args.fps) == (sw, sh, sf)
    # Not consumed as an explicit preset (nothing to override downstream).
    assert args.preset is None

    get_settings.cache_clear()


def test_lecture_render_respects_explicit_preset_and_dimensions() -> None:
    get_settings.cache_clear()
    from qurantext.cli.main import _resolve_preset

    base = [
        "run-all",
        "--quran",
        "q.txt",
        "--audio",
        "a.wav",
        "--mode",
        "lecture",
        "--render-video",
    ]

    with_preset = build_cli_parser().parse_args(base + ["--preset", "high"])
    _resolve_preset(with_preset)
    assert (with_preset.width, with_preset.height) == VIDEO_PRESETS["high"][:2]

    with_dims = build_cli_parser().parse_args(base + ["--width", "1280", "--height", "720"])
    _resolve_preset(with_dims)
    assert (with_dims.width, with_dims.height) == (1280, 720)

    get_settings.cache_clear()


def test_recitation_render_defaults_to_portrait_social_preset() -> None:
    get_settings.cache_clear()
    from qurantext.cli.main import _resolve_preset

    args = build_cli_parser().parse_args(
        [
            "run-all",
            "--quran",
            "q.txt",
            "--audio",
            "a.wav",
            "--mode",
            "recitation",
            "--render-video",
        ]
    )
    _resolve_preset(args)

    sw, sh, sf = VIDEO_PRESETS["social"]
    assert (args.width, args.height, args.fps) == (sw, sh, sf)

    get_settings.cache_clear()

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qurantext import __version__
from qurantext.config.paths import (
    LECTURE_MATCHING_OUTPUT_DIR,
    RANGE_MATCHING_OUTPUT_DIR,
    RECITATION_MATCHING_OUTPUT_DIR,
    VIDEOS_OUTPUT_DIR,
    WHISPERX_TRANSCRIPTS_OUTPUT_DIR,
)
from qurantext.config.settings import VIDEO_PRESETS, get_settings
from qurantext.io.readers import load_json
from qurantext.pipelines.detection import run_detection
from qurantext.pipelines.recitation import build_recitation_output_paths, run_word_alignment
from qurantext.pipelines.video import run_video_generation
from qurantext.services.transcription import WhisperXServiceError, transcribe_audio


def _default_detection_output(
    source_path: str,
    output_dir: str,
    suffix: str,
) -> str:
    source = Path(source_path)
    return str(Path(output_dir) / f"{source.stem}{suffix}")


def _run_word_align(args: argparse.Namespace) -> int:
    whisperx_output = load_json(args.whisperx_json) if args.whisperx_json else None
    output_paths = build_recitation_output_paths(
        args.audio,
        output_dir=args.output_dir,
        base_name=args.base_name,
    )
    result = run_word_alignment(
        args.quran,
        args.audio,
        output_paths=output_paths,
        whisperx_output=whisperx_output,
    )
    print(f"Saved alignment JSON to {result.output_paths.alignment_json}")
    print(f"Saved manual-check JSON to {result.output_paths.manual_check_json}")
    print(f"Saved SRT captions to {result.output_paths.captions_srt}")
    return 0


def _run_detection_mode(args: argparse.Namespace) -> int:
    source_path = args.whisperx_json or args.audio
    output_path = args.output or _default_detection_output(
        source_path,
        args.output_dir,
        args.output_suffix,
    )
    run_detection(
        quran=args.quran,
        output=output_path,
        mode=args.mode,
        whisperx=args.whisperx_json,
        audio=args.audio,
        surah=getattr(args, "surah", None),
        head_words=args.head_words,
        tail_words=args.tail_words,
        search_range=args.search_range,
        low_conf=args.low_conf,
        max_span=args.max_span,
        lecture_threshold=args.lecture_threshold,
        min_matched_words=args.min_matched_words,
        echo=True,
    )
    return 0


def _run_transcribe(args: argparse.Namespace) -> int:
    output_path = args.output or _default_detection_output(
        args.audio,
        args.output_dir,
        "_whisperx_raw.json",
    )
    try:
        result = transcribe_audio(args.audio, save_raw_to=output_path)
    except (FileNotFoundError, WhisperXServiceError) as error:
        raise SystemExit(str(error)) from error
    print(f"Saved WhisperX raw JSON to {result.raw_output_path}")
    print(f"Segments: {result.segment_count}; words: {result.word_count}")
    return 0


def _resolve_preset(args: argparse.Namespace) -> argparse.Namespace:
    """Apply --preset overrides to width/height/fps on *args* (mutates in place)."""
    preset = getattr(args, "preset", None)
    if preset is not None:
        w, h, f = VIDEO_PRESETS[preset]
        args.width = w
        args.height = h
        args.fps = f
    return args


def _run_generate_video(args: argparse.Namespace) -> int:
    _resolve_preset(args)
    output_path = args.output or _default_detection_output(
        args.audio,
        args.output_dir,
        f"_{args.renderer}.mp4",
    )
    return run_video_generation(
        audio=args.audio,
        matches=args.matches,
        output=output_path,
        preset=getattr(args, "preset", None),
        font_name=args.font_name,
        font_file=args.font_file,
        renderer=args.renderer,
        width=args.width,
        height=args.height,
        fps=args.fps,
        keep_temp=args.keep_temp,
        debug_detected_text=args.debug_detected_text,
    )


def _run_all(args: argparse.Namespace) -> int:
    # Pre-flight: reject incompatible flags BEFORE running any (billed) work.
    if args.render_video and args.mode == "range":
        raise SystemExit("--render-video is only supported for lecture or recitation workflows.")
    _resolve_preset(args)
    default_output_dir = {
        "range": str(RANGE_MATCHING_OUTPUT_DIR),
        "lecture": str(LECTURE_MATCHING_OUTPUT_DIR),
        "recitation": str(RECITATION_MATCHING_OUTPUT_DIR),
    }[args.mode]
    default_suffix = {
        "range": "_range.json",
        "lecture": "_lecture.json",
        "recitation": "_recitation.json",
    }[args.mode]
    output_path = args.output or _default_detection_output(
        args.audio,
        args.output_dir or default_output_dir,
        default_suffix,
    )
    run_detection(
        quran=args.quran,
        output=output_path,
        mode=args.mode,
        audio=args.audio,
        surah=args.surah,
        head_words=args.head_words,
        tail_words=args.tail_words,
        search_range=args.search_range,
        low_conf=args.low_conf,
        max_span=args.max_span,
        lecture_threshold=args.lecture_threshold,
        min_matched_words=args.min_matched_words,
        echo=True,
    )

    if not args.render_video:
        return 0

    video_output = args.video_output or _default_detection_output(
        args.audio,
        args.video_output_dir,
        f"_{args.renderer}.mp4",
    )
    return run_video_generation(
        audio=args.audio,
        matches=output_path,
        output=video_output,
        preset=getattr(args, "preset", None),
        font_name=args.font_name,
        font_file=args.font_file,
        renderer=args.renderer,
        width=args.width,
        height=args.height,
        fps=args.fps,
        keep_temp=args.keep_temp,
        debug_detected_text=args.debug_detected_text,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="qurantext",
        description=("QuranText command-line interface."),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    word_align_parser = subparsers.add_parser(
        "word-align",
        help="Run the legacy word-level recitation alignment workflow.",
    )
    word_align_parser.add_argument("--quran", required=True, help="Path to the Quran text file.")
    word_align_parser.add_argument("--audio", required=True, help="Path to the audio file.")
    word_align_parser.add_argument(
        "--whisperx-json",
        help="Optional path to a saved WhisperX JSON response. Skips the API call when provided.",
    )
    word_align_parser.add_argument(
        "--output-dir",
        default=str(RECITATION_MATCHING_OUTPUT_DIR),
        help="Directory where alignment artifacts should be written.",
    )
    word_align_parser.add_argument(
        "--base-name",
        help="Optional output filename stem. Defaults to the audio filename stem.",
    )
    word_align_parser.set_defaults(handler=_run_word_align)

    for command_name, mode, output_dir, output_suffix, help_text in (
        (
            "range-match",
            "range",
            str(RANGE_MATCHING_OUTPUT_DIR),
            "_range.json",
            "Detect the first and last ayah in a transcript.",
        ),
        (
            "lecture-match",
            "lecture",
            str(LECTURE_MATCHING_OUTPUT_DIR),
            "_lecture.json",
            "Detect Quran mentions inside lecture-style audio.",
        ),
        (
            "recitation-match",
            "recitation",
            str(RECITATION_MATCHING_OUTPUT_DIR),
            "_recitation.json",
            "Detect recitation range and timestamped Quran spans.",
        ),
    ):
        subparser = subparsers.add_parser(command_name, help=help_text)
        subparser.add_argument("--quran", required=True, help="Path to the Quran text file.")
        source_group = subparser.add_mutually_exclusive_group(required=True)
        source_group.add_argument(
            "--whisperx-json",
            help="Path to an existing WhisperX JSON transcription output.",
        )
        source_group.add_argument(
            "--audio",
            help="Path to an audio file to transcribe with WhisperX via Replicate.",
        )
        subparser.add_argument("--output", help="Explicit path for the output JSON.")
        subparser.add_argument(
            "--output-dir",
            default=output_dir,
            help="Directory where output JSON should be written when --output is omitted.",
        )
        subparser.add_argument(
            "--surah",
            default=None,
            help="Optional surah name to restrict search to. Ignored in lecture mode.",
        )
        subparser.add_argument("--head-words", type=int, default=settings.range_matching.head_words)
        subparser.add_argument("--tail-words", type=int, default=settings.range_matching.tail_words)
        subparser.add_argument(
            "--search-range", type=int, default=settings.range_matching.search_range
        )
        subparser.add_argument("--low-conf", type=float, default=settings.range_matching.low_conf)
        subparser.add_argument("--max-span", type=int, default=settings.lecture_matching.max_span)
        subparser.add_argument(
            "--lecture-threshold", type=float, default=settings.lecture_matching.min_score
        )
        subparser.add_argument(
            "--min-matched-words",
            type=int,
            default=settings.lecture_matching.min_matched_words,
        )
        subparser.set_defaults(
            handler=_run_detection_mode,
            mode=mode,
            output_suffix=output_suffix,
        )

    transcribe_parser = subparsers.add_parser(
        "transcribe",
        help="Run WhisperX transcription and save the raw JSON output.",
    )
    transcribe_parser.add_argument("--audio", required=True, help="Path to the audio file.")
    transcribe_parser.add_argument("--output", help="Explicit path for the raw WhisperX JSON.")
    transcribe_parser.add_argument(
        "--output-dir",
        default=str(WHISPERX_TRANSCRIPTS_OUTPUT_DIR),
        help="Directory where raw WhisperX JSON should be written when --output is omitted.",
    )
    transcribe_parser.set_defaults(handler=_run_transcribe)

    video_parser = subparsers.add_parser(
        "generate-video",
        help="Render an MP4 from lecture or recitation match results.",
    )
    video_parser.add_argument("--audio", required=True, help="Path to the original audio file.")
    video_parser.add_argument(
        "--matches", required=True, help="Path to the match JSON result file."
    )
    video_parser.add_argument("--output", help="Explicit path for the output MP4 video.")
    video_parser.add_argument(
        "--output-dir",
        default=str(VIDEOS_OUTPUT_DIR),
        help="Directory where the output MP4 should be written when --output is omitted.",
    )
    video_parser.add_argument("--font-name", default=None)
    video_parser.add_argument("--font-file", default=None)
    video_parser.add_argument(
        "--renderer", choices=["ass", "frame"], default=settings.video.renderer
    )
    video_parser.add_argument(
        "--preset",
        choices=sorted(VIDEO_PRESETS),
        default=None,
        help=(
            "Named quality preset that sets width, height and fps together. "
            "Overrides --width / --height / --fps when specified. "
            "Choices: "
            + ", ".join(f"{k} ({v[0]}x{v[1]}@{v[2]}fps)" for k, v in sorted(VIDEO_PRESETS.items()))
        ),
    )
    video_parser.add_argument("--width", type=int, default=settings.video.width)
    video_parser.add_argument("--height", type=int, default=settings.video.height)
    video_parser.add_argument("--fps", type=int, default=settings.video.fps)
    video_parser.add_argument("--keep-temp", action="store_true")
    video_parser.add_argument("--debug-detected-text", action="store_true")
    video_parser.set_defaults(handler=_run_generate_video)

    run_all_parser = subparsers.add_parser(
        "run-all",
        help="Run audio transcription plus Quran matching, with optional video rendering.",
    )
    run_all_parser.add_argument("--quran", required=True, help="Path to the Quran text file.")
    run_all_parser.add_argument("--audio", required=True, help="Path to the audio file.")
    run_all_parser.add_argument(
        "--mode",
        choices=["range", "lecture", "recitation"],
        default="recitation",
        help="Which end-to-end matching workflow to run.",
    )
    run_all_parser.add_argument("--output", help="Explicit path for the detection JSON output.")
    run_all_parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory where detection JSON should be written when --output is omitted.",
    )
    run_all_parser.add_argument("--surah", default=None)
    run_all_parser.add_argument(
        "--head-words", type=int, default=settings.range_matching.head_words
    )
    run_all_parser.add_argument(
        "--tail-words", type=int, default=settings.range_matching.tail_words
    )
    run_all_parser.add_argument(
        "--search-range", type=int, default=settings.range_matching.search_range
    )
    run_all_parser.add_argument("--low-conf", type=float, default=settings.range_matching.low_conf)
    run_all_parser.add_argument("--max-span", type=int, default=settings.lecture_matching.max_span)
    run_all_parser.add_argument(
        "--lecture-threshold", type=float, default=settings.lecture_matching.min_score
    )
    run_all_parser.add_argument(
        "--min-matched-words",
        type=int,
        default=settings.lecture_matching.min_matched_words,
    )
    run_all_parser.add_argument(
        "--render-video",
        action="store_true",
        help="Render a video after matching completes. Only valid for lecture or recitation mode.",
    )
    run_all_parser.add_argument("--video-output", help="Explicit path for the rendered video.")
    run_all_parser.add_argument(
        "--video-output-dir",
        default=str(VIDEOS_OUTPUT_DIR),
        help="Directory where the video should be written when --video-output is omitted.",
    )
    run_all_parser.add_argument("--font-name", default=None)
    run_all_parser.add_argument("--font-file", default=None)
    run_all_parser.add_argument(
        "--renderer", choices=["ass", "frame"], default=settings.video.renderer
    )
    run_all_parser.add_argument(
        "--preset",
        choices=sorted(VIDEO_PRESETS),
        default=None,
        help=(
            "Named quality preset that sets width, height and fps together. "
            "Overrides --width / --height / --fps when specified."
        ),
    )
    run_all_parser.add_argument("--width", type=int, default=settings.video.width)
    run_all_parser.add_argument("--height", type=int, default=settings.video.height)
    run_all_parser.add_argument("--fps", type=int, default=settings.video.fps)
    run_all_parser.add_argument("--keep-temp", action="store_true")
    run_all_parser.add_argument("--debug-detected-text", action="store_true")
    run_all_parser.set_defaults(handler=_run_all)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the QuranText CLI."""
    try:
        parser = build_parser()
    except ValueError as error:
        # e.g. a malformed QURANTEXT_* env override; report cleanly instead of
        # crashing before argparse (which would break even `--help`).
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return args.handler(args)
    except (FileNotFoundError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        # WhisperXServiceError is a RuntimeError; json.JSONDecodeError is a
        # ValueError — both are covered. SystemExit (used for pre-flight guards)
        # is not an Exception, so it propagates with its own message/exit code.
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

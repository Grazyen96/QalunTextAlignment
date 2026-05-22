from __future__ import annotations

import argparse
import sys
from pathlib import Path

from qurantext.config.settings import DEFAULT_VIDEO_FPS, DEFAULT_VIDEO_HEIGHT, DEFAULT_VIDEO_WIDTH, get_settings
from qurantext.core.ass_renderer import build_ass, render_ass_video, validate_font_name
from qurantext.core.frame_renderer import (
    ActiveMatchTracker,
    active_match_at,
    render_frame_pillow,
    render_frame_video,
    validate_font_file,
    write_silent_frame_video,
)
from qurantext.core.video_common import (
    ass_time,
    ayah_label,
    escape_ass,
    load_matches,
    validate_dimensions,
    validate_fps,
    validate_input_file,
    warn,
)

DEFAULT_WIDTH = DEFAULT_VIDEO_WIDTH
DEFAULT_HEIGHT = DEFAULT_VIDEO_HEIGHT
DEFAULT_FRAME_RATE = DEFAULT_VIDEO_FPS


def build_parser() -> argparse.ArgumentParser:
    """Build the video-rendering CLI parser."""
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Render an MP4 with Qur'an ayat using ASS subtitles or a frame-based renderer.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--audio", required=True, help="Path to the original audio file.")
    parser.add_argument("--matches", required=True, help="Path to the lecture JSON result file.")
    parser.add_argument("--output", required=True, help="Path to the output MP4 video.")
    parser.add_argument(
        "--font-name", default=None, help="Installed font family name for ASS rendering."
    )
    parser.add_argument("--font-file", default=None, help="Font file path for frame rendering.")
    parser.add_argument(
        "--renderer",
        choices=["ass", "frame"],
        default=settings.video.renderer,
        help="Choose the renderer implementation.",
    )
    parser.add_argument("--width", type=int, default=settings.video.width, help="Output video width.")
    parser.add_argument("--height", type=int, default=settings.video.height, help="Output video height.")
    parser.add_argument(
        "--fps", type=int, default=settings.video.fps, help="Output video frame rate."
    )
    parser.add_argument(
        "--keep-temp", action="store_true", help="Keep temporary intermediate files."
    )
    parser.add_argument(
        "--debug-detected-text",
        action="store_true",
        help="Render the detected transcript fragment in small debug text in frame mode.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse video-rendering CLI arguments."""
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the packaged video-rendering CLI."""
    args = parse_args(argv)

    try:
        audio_path = Path(args.audio).expanduser().resolve()
        matches_path = Path(args.matches).expanduser().resolve()
        output_path = Path(args.output).expanduser().resolve()
        font_file_path = Path(args.font_file).expanduser().resolve() if args.font_file else None
        ass_path = output_path.with_suffix(".ass")

        validate_input_file(audio_path, "Audio file")
        validate_input_file(matches_path, "Matches JSON")
        validate_dimensions(args.width, args.height)
        validate_fps(args.fps)

        matches = load_matches(matches_path)
        if not matches:
            print(
                "No matches were found in the lecture JSON. Rendering a black video with the original audio and no active ayah overlays.",
                file=sys.stderr,
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if args.renderer == "ass":
            if font_file_path is not None:
                warn("Ignoring --font-file because --renderer ass uses installed --font-name fonts.")
            if args.debug_detected_text:
                warn("Ignoring --debug-detected-text because it only applies to --renderer frame.")
            if not args.font_name:
                raise ValueError("--font-name is required when --renderer ass is selected")
            validate_font_name(args.font_name)

            ass_document = build_ass(matches, args.font_name.strip(), args.width, args.height)
            ass_path.write_text(ass_document, encoding="utf-8-sig")
            render_ass_video(audio_path, ass_path, output_path, args.width, args.height, fps=args.fps)
            print(f"ASS subtitle saved to: {ass_path}")
        else:
            if args.font_name:
                warn("Ignoring --font-name because --renderer frame uses --font-file instead.")
            if font_file_path is None:
                raise ValueError("--font-file is required when --renderer frame is selected")
            validate_font_file(font_file_path)
            render_frame_video(
                audio_path,
                matches,
                output_path,
                args.width,
                args.height,
                args.fps,
                font_file_path,
                keep_temp=args.keep_temp,
                debug_detected_text=args.debug_detected_text,
            )

    except (FileNotFoundError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"MP4 video saved to: {output_path}")
    return 0


__all__ = [
    "ActiveMatchTracker",
    "DEFAULT_FRAME_RATE",
    "DEFAULT_HEIGHT",
    "DEFAULT_WIDTH",
    "active_match_at",
    "ass_time",
    "ayah_label",
    "build_ass",
    "build_parser",
    "escape_ass",
    "load_matches",
    "main",
    "parse_args",
    "render_frame_pillow",
    "render_frame_video",
    "validate_font_file",
    "validate_font_name",
    "write_silent_frame_video",
]


if __name__ == "__main__":
    raise SystemExit(main())

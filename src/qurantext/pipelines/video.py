from __future__ import annotations

from qurantext.config.settings import get_settings
from qurantext.core.video_renderer import main as render_video_main


def run_video_generation(
    *,
    audio: str,
    matches: str,
    output: str,
    font_name: str | None = None,
    font_file: str | None = None,
    renderer: str | None = None,
    preset: str | None = None,
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
    keep_temp: bool = False,
    debug_detected_text: bool = False,
    title: str | None = None,
) -> int:
    """Run the video renderer using explicit function arguments."""
    settings = get_settings()
    resolved_renderer = str(renderer or settings.video.renderer)
    argv: list[str] = [
        "--audio",
        audio,
        "--matches",
        matches,
        "--output",
        output,
        "--renderer",
        resolved_renderer,
    ]
    if preset is not None:
        argv.extend(["--preset", preset])
    if font_name:
        argv.extend(["--font-name", font_name])
    if font_file:
        argv.extend(["--font-file", font_file])
    if title:
        argv.extend(["--title", title])
    if width is not None:
        argv.extend(["--width", str(width)])
    elif settings.video.width:
        argv.extend(["--width", str(settings.video.width)])
    if height is not None:
        argv.extend(["--height", str(height)])
    elif settings.video.height:
        argv.extend(["--height", str(settings.video.height)])
    if fps is not None:
        argv.extend(["--fps", str(fps)])
    elif settings.video.fps:
        argv.extend(["--fps", str(settings.video.fps)])
    if keep_temp:
        argv.append("--keep-temp")
    if debug_detected_text:
        argv.append("--debug-detected-text")
    return render_video_main(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the packaged video pipeline CLI."""
    return render_video_main(argv)

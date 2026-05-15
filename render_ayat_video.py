#!/usr/bin/env python3
"""
Render an MP4 video from lecture-mode Qur'an matches.

The script supports two renderers:

* ``ass``   — the existing FFmpeg + ASS subtitle workflow.
* ``frame`` — a frame-by-frame Pillow/OpenCV renderer for richer styling.

Arabic rendering note:
FFmpeg must be built with ``libass`` and ideally ``harfbuzz``, ``fribidi``, and
``fontconfig`` support. If Arabic letters appear disconnected, reversed, or the
selected font is not applied, the issue is usually the local FFmpeg/libass
build or a missing font installation rather than this script.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FRAME_RATE = 25

COLOUR_BG = (10, 10, 12, 255)
COLOUR_CARD = (36, 36, 42, 230)
COLOUR_CARD_BORDER = (255, 255, 255, 28)
COLOUR_HEADER_TEXT = (230, 230, 235, 255)
COLOUR_BODY_TEXT = (255, 255, 255, 255)
COLOUR_DEBUG_TEXT = (188, 188, 198, 255)
COLOUR_SUBTLE = (150, 150, 162, 255)

CARD_WIDTH_RATIO = 0.86
CARD_HEIGHT_RATIO = 0.78
CARD_HEIGHT_RATIO_DEBUG = 0.84
CARD_RADIUS_RATIO = 0.024
CARD_PADDING_X_RATIO = 0.055
CARD_PADDING_Y_RATIO = 0.06
HEADER_FONT_RATIO = 0.036
BODY_FONT_START_RATIO = 0.064
BODY_FONT_MIN_RATIO = 0.026
DEBUG_FONT_START_RATIO = 0.025
DEBUG_FONT_MIN_RATIO = 0.015
LINE_SPACING_RATIO = 0.30
SECTION_GAP_RATIO = 0.02


@lru_cache(maxsize=1)
def _frame_dependencies() -> tuple[Any, Any, Any, Any, Any, Any]:
    try:
        import numpy as np
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "frame renderer requires numpy. Install it with: pip install numpy"
        ) from error

    try:
        import cv2  # type: ignore[import-not-found]
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "frame renderer requires opencv-python. Install it with: pip install opencv-python"
        ) from error

    try:
        from PIL import Image, ImageDraw, ImageFont, features
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "frame renderer requires Pillow. Install it with: pip install pillow"
        ) from error

    return np, cv2, Image, ImageDraw, ImageFont, features


@lru_cache(maxsize=1)
def _require_raqm_support() -> None:
    _, _, _, _, _, features = _frame_dependencies()
    if not features.check("raqm"):
        raise RuntimeError(
            "Pillow was not built with libraqm. Arabic shaping/RTL rendering may be incorrect. "
            "Frame renderer requires libraqm support, so install a Pillow build with libraqm enabled."
        )


def ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format ``H:MM:SS.cs``."""
    if not math.isfinite(seconds):
        raise ValueError(f"Timestamp must be finite, got: {seconds!r}")

    total_centiseconds = max(0, int(round(seconds * 100)))
    hours, remainder = divmod(total_centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def escape_ass(text: str) -> str:
    """Escape ASS-sensitive characters and convert newlines to ``\\N``."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    escaped = (
        normalized.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )
    return escaped.replace("\n", r"\N")


def ayah_label(match: dict[str, Any]) -> str:
    """Return a user-facing label for one ayah or an ayah range."""
    surah_name = str(match.get("surah_name") or "سورة غير معروفة").strip()
    from_ayah = match.get("from_ayah")
    to_ayah = match.get("to_ayah")

    if isinstance(from_ayah, int) and isinstance(to_ayah, int):
        if from_ayah == to_ayah:
            return f"{surah_name} - الآية {from_ayah}"
        return f"{surah_name} - الآيات {from_ayah} – {to_ayah}"

    return surah_name


def _ayah_range_text(match: dict[str, Any]) -> str:
    from_ayah = match.get("from_ayah")
    to_ayah = match.get("to_ayah")
    if isinstance(from_ayah, int) and isinstance(to_ayah, int):
        if from_ayah == to_ayah:
            return f"الآية {from_ayah}"
        return f"الآيات {from_ayah} – {to_ayah}"
    return ""


def _style_font_size(height: int) -> int:
    return max(28, round(54 * (height / 1080)))


def _style_margin_lr(width: int) -> int:
    return max(60, round(140 * (width / 1920)))


def _style_margin_v(height: int) -> int:
    return max(48, round(80 * (height / 1080)))


def _warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr)


def _coerce_time(value: Any, field_name: str, match_index: int) -> float:
    try:
        time_value = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"match #{match_index}: invalid {field_name} value {value!r}"
        ) from error

    if not math.isfinite(time_value):
        raise ValueError(f"match #{match_index}: {field_name} must be finite")

    return time_value


def _match_confidence(match: dict[str, Any]) -> float:
    try:
        confidence = float(match.get("confidence", 0.0))
    except (TypeError, ValueError):
        return 0.0
    return confidence if math.isfinite(confidence) else 0.0


def _match_display_text(match: dict[str, Any], match_index: int) -> str:
    for key in ("full_text", "full_ayah_text", "text"):
        value = match.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    raise ValueError(
        f"match #{match_index}: missing display text; expected one of "
        f"'full_text', 'full_ayah_text', or 'text'"
    )


def _validated_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid_matches: list[dict[str, Any]] = []
    for match_index, match in enumerate(matches, start=1):
        try:
            start_time = _coerce_time(match.get("start_time"), "start_time", match_index)
            end_time = _coerce_time(match.get("end_time"), "end_time", match_index)
            if end_time <= start_time:
                raise ValueError(
                    f"match #{match_index}: end_time ({end_time}) must be greater than "
                    f"start_time ({start_time})"
                )
            enriched = dict(match)
            enriched["_display_text"] = _match_display_text(match, match_index)
            enriched["_start_time"] = start_time
            enriched["_end_time"] = end_time
            enriched["_duration"] = end_time - start_time
            enriched["_confidence"] = _match_confidence(match)
            valid_matches.append(enriched)
        except ValueError as error:
            _warn(f"Skipping {error}.")
    return valid_matches


def build_ass(matches: list[dict[str, Any]], font_name: str, width: int, height: int) -> str:
    """Build a complete ASS subtitle document from lecture matches."""
    font_size = _style_font_size(height)
    margin_lr = _style_margin_lr(width)
    margin_v = _style_margin_v(height)

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        (
            "Style: Ayah,"
            f"{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H99000000,"
            f"0,0,0,0,100,100,0,0,3,2,0,5,{margin_lr},{margin_lr},{margin_v},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    valid_events = 0
    for match in _validated_matches(matches):
        label = ayah_label(match)
        dialogue_text = f"{{\\an5}}{escape_ass(label)}\\N\\N{escape_ass(match['_display_text'])}"
        lines.append(
            f"Dialogue: 0,{ass_time(match['_start_time'])},{ass_time(match['_end_time'])},Ayah,,0,0,0,,{dialogue_text}"
        )
        valid_events += 1

    if valid_events == 0 and matches:
        _warn("No valid subtitle events were generated from the provided matches.")

    return "\n".join(lines) + "\n"


def _escape_ffmpeg_filter_path(path: Path) -> str:
    """Escape a path for FFmpeg filter arguments like ``ass=filename=...``."""
    resolved = path.resolve().as_posix()
    escaped = (
        resolved.replace("\\", r"\\")
        .replace("'", r"\'")
        .replace(":", r"\:")
        .replace(",", r"\,")
        .replace("[", r"\[")
        .replace("]", r"\]")
        .replace(";", r"\;")
    )
    return f"filename='{escaped}'"


def _require_binary(binary_name: str, install_hint: str | None = None) -> str:
    binary_path = shutil.which(binary_name)
    if binary_path:
        return binary_path

    hint = f" {install_hint}" if install_hint else ""
    raise RuntimeError(f"{binary_name} was not found in PATH.{hint}")


def get_audio_duration(audio_path: Path) -> float:
    """Read audio duration in seconds using ffprobe."""
    ffprobe_path = _require_binary(
        "ffprobe",
        "Install FFmpeg/ffprobe and try again.",
    )
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        str(audio_path),
    ]

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "ffprobe could not be executed. Install FFmpeg/ffprobe and ensure it is in PATH."
        ) from error

    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "unknown ffprobe error").strip()
        raise RuntimeError(f"ffprobe failed while reading audio duration: {details}")

    raw_value = (completed.stdout or "").strip()
    try:
        duration = float(raw_value)
    except ValueError as error:
        raise RuntimeError(f"ffprobe returned an invalid duration: {raw_value!r}") from error

    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError(f"ffprobe returned a non-positive duration: {duration!r}")
    return duration


def render_video(
    audio_path: Path,
    ass_path: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: int = DEFAULT_FRAME_RATE,
) -> None:
    """Render the final MP4 using FFmpeg + ASS subtitles."""
    ffmpeg_path = _require_binary(
        "ffmpeg",
        "Install FFmpeg with libass support, then run this command again.",
    )

    command = [
        ffmpeg_path,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={width}x{height}:r={fps}",
        "-i",
        str(audio_path),
        "-vf",
        f"ass={_escape_ffmpeg_filter_path(ass_path)}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output_path),
    ]

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "FFmpeg could not be executed. Ensure it is installed and available in PATH."
        ) from error

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        details = stderr or stdout or "unknown FFmpeg error"
        raise RuntimeError(f"FFmpeg failed while rendering the video: {details}")


def active_match_at(matches: list[dict[str, Any]], t: float) -> dict[str, Any] | None:
    """Return the highest-priority match active at timestamp ``t``."""
    active: list[dict[str, Any]] = []
    for match in matches:
        start_time = match.get("_start_time")
        end_time = match.get("_end_time")
        if not isinstance(start_time, (int, float)) or not isinstance(end_time, (int, float)):
            continue
        if start_time <= t <= end_time:
            active.append(match)

    if not active:
        return None

    active.sort(
        key=lambda match: (
            float(match.get("_confidence", 0.0)),
            float(match.get("_duration", 0.0)),
        ),
        reverse=True,
    )
    return active[0]


def load_font(font_file: Path, size: int) -> Any:
    """Load a TrueType/OpenType font file for frame rendering."""
    _, _, _, _, image_font, _ = _frame_dependencies()
    try:
        return image_font.truetype(str(font_file), size=size)
    except OSError as error:
        raise RuntimeError(f"Failed to load font file '{font_file}': {error}") from error


def measure_text_bbox(draw: Any, text: str, font: Any) -> tuple[int, int]:
    """Measure text width and height using Pillow."""
    probe_text = text if text else " "
    bbox = draw.textbbox((0, 0), probe_text, font=font, direction="rtl")
    return max(0, bbox[2] - bbox[0]), max(0, bbox[3] - bbox[1])


def wrap_text_to_width(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    """Wrap text by spaces while preserving explicit newlines."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = normalized.split("\n")
    wrapped: list[str] = []

    for paragraph in paragraphs:
        stripped = paragraph.strip()
        if not stripped:
            wrapped.append("")
            continue

        words = stripped.split()
        current = words[0]

        for word in words[1:]:
            candidate = f"{current} {word}"
            if draw.textlength(candidate, font=font, direction="rtl") <= max_width:
                current = candidate
                continue

            wrapped.append(current)
            current = word

        wrapped.append(current)

    return wrapped or [""]


def _multiline_metrics(draw: Any, lines: list[str], font: Any, line_spacing: int) -> tuple[int, int]:
    widths: list[int] = []
    heights: list[int] = []
    for line in lines:
        width, height = measure_text_bbox(draw, line, font)
        widths.append(width)
        heights.append(height)

    total_height = sum(heights)
    if len(lines) > 1:
        total_height += line_spacing * (len(lines) - 1)
    return (max(widths) if widths else 0), total_height


def fit_font_size(
    draw: Any,
    text: str,
    font_file: Path,
    max_width: int,
    max_height: int,
    start_size: int,
    min_size: int,
) -> tuple[Any, list[str]]:
    """Fit wrapped text into the given box by reducing the font size."""
    min_size = max(8, min_size)
    best_font = load_font(font_file, min_size)
    best_lines = wrap_text_to_width(draw, text, best_font, max_width)

    for size in range(max(start_size, min_size), min_size - 1, -2):
        font = load_font(font_file, size)
        lines = wrap_text_to_width(draw, text, font, max_width)
        line_spacing = max(4, int(size * LINE_SPACING_RATIO))
        width, height = _multiline_metrics(draw, lines, font, line_spacing)
        if width <= max_width and height <= max_height:
            return font, lines
        best_font = font
        best_lines = lines

    return best_font, best_lines


def draw_rounded_rectangle(image: Any, box: tuple[int, int, int, int], radius: int, fill: tuple[int, int, int, int]) -> None:
    """Draw a semi-transparent rounded rectangle using Pillow."""
    _, _, image_module, image_draw, _, _ = _frame_dependencies()
    overlay = image_module.new("RGBA", image.size, (0, 0, 0, 0))
    draw = image_draw.Draw(overlay, "RGBA")

    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=COLOUR_CARD_BORDER, width=2)
    else:
        x0, y0, x1, y1 = box
        draw.rectangle((x0 + radius, y0, x1 - radius, y1), fill=fill)
        draw.rectangle((x0, y0 + radius, x1, y1 - radius), fill=fill)
        draw.ellipse((x0, y0, x0 + 2 * radius, y0 + 2 * radius), fill=fill)
        draw.ellipse((x1 - 2 * radius, y0, x1, y0 + 2 * radius), fill=fill)
        draw.ellipse((x0, y1 - 2 * radius, x0 + 2 * radius, y1), fill=fill)
        draw.ellipse((x1 - 2 * radius, y1 - 2 * radius, x1, y1), fill=fill)

    image.alpha_composite(overlay)


def draw_centered_multiline_text(
    draw: Any,
    lines: list[str],
    font: Any,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int, int],
    line_spacing: int,
) -> None:
    """Draw multiline text centered inside a bounding box."""
    x0, y0, x1, y1 = box
    _, total_height = _multiline_metrics(draw, lines, font, line_spacing)
    current_y = y0 + max(0, ((y1 - y0) - total_height) / 2)

    for line in lines:
        line_width, line_height = measure_text_bbox(draw, line, font)
        current_x = x0 + max(0, ((x1 - x0) - line_width) / 2)
        draw.text(
            (current_x, current_y),
            line,
            font=font,
            fill=fill,
            direction="rtl",
            align="center",
        )
        current_y += line_height + line_spacing


def render_frame_pillow(
    t: float,
    match: dict[str, Any] | None,
    width: int,
    height: int,
    font_file: Path,
    debug_detected_text: bool = False,
) -> Any:
    """Render one styled frame as a BGR numpy array for OpenCV."""
    np, _, image_module, image_draw, _, _ = _frame_dependencies()
    image = image_module.new("RGBA", (width, height), COLOUR_BG)

    if match is not None:
        draw = image_draw.Draw(image)
        card_width = int(width * CARD_WIDTH_RATIO)
        card_height = int(height * (CARD_HEIGHT_RATIO_DEBUG if debug_detected_text else CARD_HEIGHT_RATIO))
        card_x0 = (width - card_width) // 2
        card_y0 = (height - card_height) // 2
        card_x1 = card_x0 + card_width
        card_y1 = card_y0 + card_height
        radius = max(18, int(min(width, height) * CARD_RADIUS_RATIO))
        draw_rounded_rectangle(image, (card_x0, card_y0, card_x1, card_y1), radius, COLOUR_CARD)

        draw = image_draw.Draw(image)
        pad_x = int(card_width * CARD_PADDING_X_RATIO)
        pad_y = int(card_height * CARD_PADDING_Y_RATIO)
        gap = max(12, int(height * SECTION_GAP_RATIO))

        header_text = ayah_label(match)
        header_font = load_font(font_file, max(18, int(height * HEADER_FONT_RATIO)))
        header_height = measure_text_bbox(draw, header_text, header_font)[1]

        debug_lines: list[str] = []
        debug_font = None
        debug_height = 0
        if debug_detected_text:
            detected_text = str(match.get("detected_text") or "").strip()
            if detected_text:
                debug_font, debug_lines = fit_font_size(
                    draw,
                    detected_text,
                    font_file,
                    max_width=card_width - (2 * pad_x),
                    max_height=max(32, int(card_height * 0.16)),
                    start_size=max(16, int(height * DEBUG_FONT_START_RATIO)),
                    min_size=max(12, int(height * DEBUG_FONT_MIN_RATIO)),
                )
                debug_spacing = max(4, int(debug_font.size * LINE_SPACING_RATIO))
                _, debug_height = _multiline_metrics(draw, debug_lines, debug_font, debug_spacing)
            else:
                debug_detected_text = False

        body_top = card_y0 + pad_y + header_height + gap
        body_bottom = card_y1 - pad_y - (debug_height + gap if debug_detected_text and debug_lines else 0)
        body_box = (card_x0 + pad_x, body_top, card_x1 - pad_x, max(body_top, body_bottom))
        body_font, body_lines = fit_font_size(
            draw,
            str(match.get("_display_text") or ""),
            font_file,
            max_width=body_box[2] - body_box[0],
            max_height=max(40, body_box[3] - body_box[1]),
            start_size=max(24, int(height * BODY_FONT_START_RATIO)),
            min_size=max(16, int(height * BODY_FONT_MIN_RATIO)),
        )

        header_box = (card_x0 + pad_x, card_y0 + pad_y, card_x1 - pad_x, card_y0 + pad_y + header_height)
        draw_centered_multiline_text(draw, [header_text], header_font, header_box, COLOUR_HEADER_TEXT, 0)

        body_spacing = max(4, int(body_font.size * LINE_SPACING_RATIO))
        draw_centered_multiline_text(draw, body_lines, body_font, body_box, COLOUR_BODY_TEXT, body_spacing)

        if debug_detected_text and debug_lines and debug_font is not None:
            debug_spacing = max(4, int(debug_font.size * LINE_SPACING_RATIO))
            debug_label = "النص المكتشف"
            label_font = load_font(font_file, max(14, debug_font.size))
            label_width, label_height = measure_text_bbox(draw, debug_label, label_font)
            label_y = card_y1 - pad_y - debug_height - gap - label_height
            draw.text(
                (card_x0 + ((card_width - label_width) / 2), label_y),
                debug_label,
                font=label_font,
                fill=COLOUR_SUBTLE,
                direction="rtl",
                align="center",
            )
            debug_box = (card_x0 + pad_x, label_y + label_height + 6, card_x1 - pad_x, card_y1 - pad_y)
            draw_centered_multiline_text(draw, debug_lines, debug_font, debug_box, COLOUR_DEBUG_TEXT, debug_spacing)

    rgb = image.convert("RGB")
    frame = np.array(rgb)
    return frame[:, :, ::-1].copy()


def write_silent_frame_video(
    matches: list[dict[str, Any]],
    duration: float,
    temp_video_path: Path,
    width: int,
    height: int,
    fps: int,
    font_file: Path,
    debug_detected_text: bool = False,
) -> None:
    """Write a silent temporary MP4 using OpenCV."""
    _, cv2, _, _, _, _ = _frame_dependencies()
    total_frames = max(1, int(math.ceil(duration * fps)))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(temp_video_path), fourcc, float(fps), (width, height))
    if not writer.isOpened():
        raise RuntimeError(
            f"OpenCV failed to open the temporary video writer for '{temp_video_path}'."
        )

    _REPORT_EVERY = max(1, fps * 10)  # print progress every ~10 s of video
    t0 = time.monotonic()

    try:
        for frame_index in range(total_frames):
            t = frame_index / fps
            match = active_match_at(matches, t)
            frame = render_frame_pillow(
                t,
                match,
                width,
                height,
                font_file,
                debug_detected_text=debug_detected_text,
            )
            writer.write(frame)

            if frame_index % _REPORT_EVERY == 0 or frame_index == total_frames - 1:
                elapsed = time.monotonic() - t0
                pct = (frame_index + 1) / total_frames
                eta = (elapsed / pct - elapsed) if pct > 0 else 0
                print(
                    f"\r  Frames {frame_index + 1:>6}/{total_frames}"
                    f"  ({pct * 100:.1f}%)"
                    f"  elapsed {elapsed:.0f}s"
                    f"  ETA {eta:.0f}s      ",
                    end="",
                    flush=True,
                )
        print()  # newline after progress line
    finally:
        writer.release()


def mux_audio_video(silent_video_path: Path, audio_path: Path, output_path: Path) -> None:
    """Mux the original audio into the temporary silent video."""
    ffmpeg_path = _require_binary("ffmpeg", "Install FFmpeg and try again.")
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(silent_video_path),
        "-i",
        str(audio_path),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "unknown FFmpeg error").strip()
        raise RuntimeError(f"FFmpeg failed while muxing the final video: {details}")


def render_frame_video(
    audio_path: Path,
    matches: list[dict[str, Any]],
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    font_file: Path,
    keep_temp: bool = False,
    debug_detected_text: bool = False,
) -> Path | None:
    """Render a styled frame-by-frame video and mux the original audio."""
    _frame_dependencies()
    _require_raqm_support()
    _require_binary("ffmpeg", "Install FFmpeg and try again.")
    _require_binary("ffprobe", "Install FFmpeg/ffprobe and try again.")

    duration = get_audio_duration(audio_path)
    valid_matches = _validated_matches(matches)
    if not valid_matches and matches:
        _warn("No valid timed matches remained for the frame renderer; rendering a dark video with audio only.")

    total_frames = max(1, int(math.ceil(duration * fps)))
    print(
        f"  Video: {duration:.1f}s  ×  {fps} fps  =  {total_frames:,} frames  "
        f"({width}×{height})"
    )

    temp_dir = output_path.parent
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_handle = tempfile.NamedTemporaryFile(
        prefix=f"{output_path.stem}.",
        suffix=".silent.mp4",
        dir=temp_dir,
        delete=False,
    )
    temp_handle.close()
    temp_video_path = Path(temp_handle.name)

    grand_start = time.monotonic()

    try:
        print("  [1/2] Rendering frames...")
        t0 = time.monotonic()
        write_silent_frame_video(
            valid_matches,
            duration,
            temp_video_path,
            width,
            height,
            fps,
            font_file,
            debug_detected_text=debug_detected_text,
        )
        frame_elapsed = time.monotonic() - t0
        print(f"  [1/2] Done — {frame_elapsed:.1f}s  ({total_frames / frame_elapsed:.1f} fps rendered)")

        print("  [2/2] Muxing audio...")
        t0 = time.monotonic()
        mux_audio_video(temp_video_path, audio_path, output_path)
        mux_elapsed = time.monotonic() - t0
        print(f"  [2/2] Done — {mux_elapsed:.1f}s")

    finally:
        if keep_temp:
            print(f"Temporary silent video kept at: {temp_video_path}")
        else:
            temp_video_path.unlink(missing_ok=True)

    total_elapsed = time.monotonic() - grand_start
    mins, secs = divmod(int(total_elapsed), 60)
    print(f"  Total render time: {mins}m {secs:02d}s")

    return temp_video_path if keep_temp else None


def _validate_input_file(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"{label} is not a file: {path}")


def _validate_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise ValueError("--width and --height must both be positive integers")


def _validate_fps(fps: int) -> None:
    if fps <= 0:
        raise ValueError("--fps must be a positive integer")


def _validate_font_name(font_name: str) -> None:
    cleaned = font_name.strip()
    if not cleaned:
        raise ValueError("--font-name cannot be empty")
    if "," in cleaned:
        raise ValueError("--font-name cannot contain commas because ASS style fields are comma-separated")

    fc_list = shutil.which("fc-list")
    if fc_list:
        try:
            result = subprocess.run(
                [fc_list, f":family={cleaned}", "family"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as error:
            raise RuntimeError(f"Failed to validate font '{cleaned}' with fontconfig: {error}") from error

        families = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        requested = cleaned.casefold()
        for family_line in families:
            for family in (part.strip() for part in family_line.split(",")):
                if family.casefold() == requested:
                    return

        raise ValueError(
            f"Font '{cleaned}' was not found on this system. Install it first or choose another --font-name."
        )

    common_dirs = [
        Path.home() / ".fonts",
        Path.home() / ".local/share/fonts",
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
    ]
    requested = cleaned.casefold().replace(" ", "")
    for directory in common_dirs:
        if not directory.exists():
            continue
        for candidate in directory.rglob("*"):
            if not candidate.is_file():
                continue
            candidate_key = candidate.stem.casefold().replace(" ", "")
            if candidate_key == requested:
                return

    raise ValueError(
        f"Could not validate font '{cleaned}' because fontconfig is unavailable and no matching font file "
        "was found in standard font directories. Install fontconfig or use a system-installed font name."
    )


def _validate_font_file(font_file: Path) -> None:
    _validate_input_file(font_file, "Font file")
    if font_file.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
        _warn(
            f"Font file '{font_file.name}' does not use a typical TTF/OTF/TTC extension; attempting to load it anyway."
        )


def _load_matches(matches_path: Path) -> list[dict[str, Any]]:
    try:
        with matches_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as error:
        raise ValueError(f"Failed to parse JSON '{matches_path}': {error}") from error

    if not isinstance(payload, dict):
        raise ValueError("Lecture JSON root must be an object containing a 'matches' list")

    matches = payload.get("matches")
    if matches is None:
        raise ValueError("Lecture JSON is missing the required 'matches' field")
    if not isinstance(matches, list):
        raise ValueError("Lecture JSON field 'matches' must be a list")

    normalized_matches: list[dict[str, Any]] = []
    for index, item in enumerate(matches, start=1):
        if not isinstance(item, dict):
            _warn(f"Skipping non-object entry at matches[{index - 1}].")
            continue
        normalized_matches.append(item)
    return normalized_matches


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render an MP4 with Qur'an ayat using ASS subtitles or a frame-based renderer.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--audio", required=True, help="Path to the original audio file.")
    parser.add_argument("--matches", required=True, help="Path to the lecture JSON result file.")
    parser.add_argument("--output", required=True, help="Path to the output MP4 video.")
    parser.add_argument("--font-name", default=None, help="Installed font family name for ASS rendering.")
    parser.add_argument("--font-file", default=None, help="Font file path for frame rendering.")
    parser.add_argument(
        "--renderer",
        choices=["ass", "frame"],
        default="ass",
        help="Choose the renderer implementation.",
    )
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="Output video width.")
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help="Output video height.")
    parser.add_argument("--fps", type=int, default=DEFAULT_FRAME_RATE, help="Output video frame rate.")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary intermediate files.")
    parser.add_argument(
        "--debug-detected-text",
        action="store_true",
        help="Render the detected transcript fragment in small debug text in frame mode.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        audio_path = Path(args.audio).expanduser().resolve()
        matches_path = Path(args.matches).expanduser().resolve()
        output_path = Path(args.output).expanduser().resolve()
        font_file_path = Path(args.font_file).expanduser().resolve() if args.font_file else None
        ass_path = output_path.with_suffix(".ass")

        _validate_input_file(audio_path, "Audio file")
        _validate_input_file(matches_path, "Matches JSON")
        _validate_dimensions(args.width, args.height)
        _validate_fps(args.fps)

        matches = _load_matches(matches_path)
        if not matches:
            print(
                "No matches were found in the lecture JSON. Rendering a black video with the original audio and no active ayah overlays.",
                file=sys.stderr,
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if args.renderer == "ass":
            if font_file_path is not None:
                _warn("Ignoring --font-file because --renderer ass uses installed --font-name fonts.")
            if args.debug_detected_text:
                _warn("Ignoring --debug-detected-text because it only applies to --renderer frame.")
            if not args.font_name:
                raise ValueError("--font-name is required when --renderer ass is selected")
            _validate_font_name(args.font_name)

            ass_document = build_ass(matches, args.font_name.strip(), args.width, args.height)
            ass_path.write_text(ass_document, encoding="utf-8-sig")
            render_video(audio_path, ass_path, output_path, args.width, args.height, fps=args.fps)
            print(f"ASS subtitle saved to: {ass_path}")
        else:
            if args.font_name:
                _warn("Ignoring --font-name because --renderer frame uses --font-file instead.")
            if font_file_path is None:
                raise ValueError("--font-file is required when --renderer frame is selected")
            _validate_font_file(font_file_path)
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
        raise SystemExit(1) from error

    print(f"MP4 video saved to: {output_path}")


if __name__ == "__main__":
    main()


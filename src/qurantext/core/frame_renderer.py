from __future__ import annotations

import math
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from qurantext.core.video_common import ayah_label, get_audio_duration, require_binary, validated_matches, validate_input_file, warn

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


@dataclass(slots=True)
class ActiveMatchTracker:
    """Track active matches efficiently while timestamps advance monotonically."""

    matches: list[dict[str, Any]]
    _next_index: int = 0
    _active: list[dict[str, Any]] = field(default_factory=list)

    def at(self, t: float) -> dict[str, Any] | None:
        while self._next_index < len(self.matches):
            next_match = self.matches[self._next_index]
            start_time = next_match.get("_start_time")
            if not isinstance(start_time, (int, float)) or start_time > t:
                break
            self._active.append(next_match)
            self._next_index += 1

        self._active = [
            match
            for match in self._active
            if isinstance(match.get("_end_time"), (int, float)) and float(match["_end_time"]) >= t
        ]
        if not self._active:
            return None

        return max(
            self._active,
            key=lambda match: (
                float(match.get("_confidence", 0.0)),
                float(match.get("_duration", 0.0)),
            ),
        )


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


def _multiline_metrics(
    draw: Any, lines: list[str], font: Any, line_spacing: int
) -> tuple[int, int]:
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


def draw_rounded_rectangle(
    image: Any, box: tuple[int, int, int, int], radius: int, fill: tuple[int, int, int, int]
) -> None:
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
        card_height = int(
            height * (CARD_HEIGHT_RATIO_DEBUG if debug_detected_text else CARD_HEIGHT_RATIO)
        )
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
        body_bottom = (
            card_y1 - pad_y - (debug_height + gap if debug_detected_text and debug_lines else 0)
        )
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

        header_box = (
            card_x0 + pad_x,
            card_y0 + pad_y,
            card_x1 - pad_x,
            card_y0 + pad_y + header_height,
        )
        draw_centered_multiline_text(
            draw, [header_text], header_font, header_box, COLOUR_HEADER_TEXT, 0
        )

        body_spacing = max(4, int(body_font.size * LINE_SPACING_RATIO))
        draw_centered_multiline_text(
            draw, body_lines, body_font, body_box, COLOUR_BODY_TEXT, body_spacing
        )

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
            debug_box = (
                card_x0 + pad_x,
                label_y + label_height + 6,
                card_x1 - pad_x,
                card_y1 - pad_y,
            )
            draw_centered_multiline_text(
                draw, debug_lines, debug_font, debug_box, COLOUR_DEBUG_TEXT, debug_spacing
            )

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

    report_every = max(1, fps * 10)
    t0 = time.monotonic()
    active_tracker = ActiveMatchTracker(
        sorted(matches, key=lambda match: float(match.get("_start_time", math.inf)))
    )

    try:
        for frame_index in range(total_frames):
            t = frame_index / fps
            match = active_tracker.at(t)
            frame = render_frame_pillow(
                t,
                match,
                width,
                height,
                font_file,
                debug_detected_text=debug_detected_text,
            )
            writer.write(frame)

            if frame_index % report_every == 0 or frame_index == total_frames - 1:
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
        print()
    finally:
        writer.release()


def mux_audio_video(silent_video_path: Path, audio_path: Path, output_path: Path) -> None:
    """Mux the original audio into the temporary silent video."""
    ffmpeg_path = require_binary("ffmpeg", "Install FFmpeg and try again.")
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
    require_binary("ffmpeg", "Install FFmpeg and try again.")
    require_binary("ffprobe", "Install FFmpeg/ffprobe and try again.")

    duration = get_audio_duration(audio_path)
    valid_matches = validated_matches(matches)
    if not valid_matches and matches:
        warn(
            "No valid timed matches remained for the frame renderer; rendering a dark video with audio only."
        )

    total_frames = max(1, int(math.ceil(duration * fps)))
    print(f"  Video: {duration:.1f}s  ×  {fps} fps  =  {total_frames:,} frames  ({width}×{height})")

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
        print(
            f"  [1/2] Done — {frame_elapsed:.1f}s  ({total_frames / frame_elapsed:.1f} fps rendered)"
        )

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


def validate_font_file(font_file: Path) -> None:
    validate_input_file(font_file, "Font file")
    if font_file.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
        warn(
            f"Font file '{font_file.name}' does not use a typical TTF/OTF/TTC extension; attempting to load it anyway."
        )


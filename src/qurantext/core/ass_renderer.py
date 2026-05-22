from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

from qurantext.core.video_common import ass_time, ayah_label, escape_ass, require_binary, validated_matches, warn


def _style_font_size(height: int) -> int:
    return max(28, round(54 * (height / 1080)))


def _style_margin_lr(width: int) -> int:
    return max(60, round(140 * (width / 1920)))


def _style_margin_v(height: int) -> int:
    return max(48, round(80 * (height / 1080)))


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
    for match in validated_matches(matches):
        label = ayah_label(match)
        dialogue_text = f"{{\\an5}}{escape_ass(label)}\\N\\N{escape_ass(match['_display_text'])}"
        lines.append(
            f"Dialogue: 0,{ass_time(match['_start_time'])},{ass_time(match['_end_time'])},Ayah,,0,0,0,,{dialogue_text}"
        )
        valid_events += 1

    if valid_events == 0 and matches:
        warn("No valid subtitle events were generated from the provided matches.")

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


def render_ass_video(
    audio_path: Path,
    ass_path: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: int,
) -> None:
    """Render the final MP4 using FFmpeg + ASS subtitles."""
    ffmpeg_path = require_binary(
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


def validate_font_name(font_name: str) -> None:
    cleaned = font_name.strip()
    if not cleaned:
        raise ValueError("--font-name cannot be empty")
    if "," in cleaned:
        raise ValueError(
            "--font-name cannot contain commas because ASS style fields are comma-separated"
        )

    fc_list = cast(str | None, shutil.which("fc-list"))
    if fc_list:
        try:
            result = subprocess.run(
                [fc_list, f":family={cleaned}", "family"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as error:
            raise RuntimeError(
                f"Failed to validate font '{cleaned}' with fontconfig: {error}"
            ) from error

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


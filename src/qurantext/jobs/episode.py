"""The episode: an intro, a recitation, the lecture and an outro, joined into one video.

Each part is probed first, so a missing clip or a file that is not a video is
named before anything is encoded. The parts are then joined in one FFmpeg run
through the ``concat`` filter, every part scaled and letterboxed to the
lecture's own size and frame rate: an intro filmed on a phone, upright or on
its side, comes out upright inside black bars rather than stretched. FFmpeg
applies a clip's rotation metadata as it decodes, so a portrait clip recorded
as a rotated landscape stream arrives upright without help; the rotation is
then removed from the joined video, which is upright throughout. A part with no
sound gets silence of its own length, so the episode's audio is continuous.

The episode is written to ``<output>.part.mp4`` and renamed into place only
when it is complete; a failure or a cancel removes the partial file. Errors
carry an i18n key and its values (:class:`EpisodeError`), so the window can
say what went wrong in the person's language.
"""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qurantext.core.video_common import require_binary
from qurantext.utils.progress import CancelToken, ProgressCallback, report

__all__ = [
    "EpisodeError",
    "EpisodeResult",
    "STAGE",
    "PartInfo",
    "assemble_episode",
    "episode_path_for",
    "probe_part",
]

_INSTALL_HINT = "Install FFmpeg and try again."
#: The progress stage the join reports under. Joining is the end of the
#: render, so the window says "Rendering — N%" for it without a sentence of its
#: own; the job layer announces the join itself in the window's language.
STAGE = "render"
#: How long a probe of one clip may take before the clip is called unreadable.
_PROBE_TIMEOUT_S = 60
#: How many of FFmpeg's last error lines a failed join reports.
_ERROR_LINES = 5
#: The frame renderer's encoding, so the episode looks like the lecture inside it.
_ENCODE_ARGS = (
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
)


class EpisodeError(RuntimeError):
    """An episode that could not be made, said as an i18n *key* and its *fmt* values.

    The job layer does not translate; the window turns it into a sentence with
    ``t(error.key, **error.fmt)``.
    """

    def __init__(self, key: str, **fmt: Any) -> None:
        self.key = key
        self.fmt: dict[str, Any] = dict(fmt)
        details = ", ".join(f"{name}={value!r}" for name, value in self.fmt.items())
        super().__init__(f"{key} ({details})" if details else key)


@dataclass(frozen=True, slots=True)
class PartInfo:
    """What the join needs to know about one part."""

    path: Path
    duration: float
    has_video: bool
    has_audio: bool


@dataclass(frozen=True, slots=True)
class EpisodeResult:
    """The episode written, each part's length in order, and where the lecture starts in it."""

    output: Path
    durations: tuple[float, ...]
    #: Seconds of episode before the lecture: where its subtitles move to.
    lecture_offset: float


def episode_path_for(lecture_video: Path) -> Path:
    """``lec.mp4`` gets its episode beside it as ``lec – episode.mp4``."""
    lecture_video = Path(lecture_video)
    return lecture_video.with_name(f"{lecture_video.stem} – episode.mp4")


def _duration(value: Any) -> float | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def probe_part(path: Path) -> PartInfo:
    """Read *path*'s length and streams with ffprobe.

    Raises :class:`EpisodeError` with ``episode.error.missing`` when the file is
    not there, and with ``episode.error.not_video`` when ffprobe cannot read it,
    it holds no picture (an audio file's cover art is not one) or it has no
    length.
    """
    path = Path(path)
    if not path.is_file():
        raise EpisodeError("episode.error.missing", name=path.name)
    try:
        ffprobe = require_binary("ffprobe", _INSTALL_HINT)
    except RuntimeError as error:
        raise EpisodeError("episode.error.ffmpeg", reason=str(error)) from error
    try:
        completed = subprocess.run(
            [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_PROBE_TIMEOUT_S,
        )
        data = json.loads(completed.stdout or "{}")
    except (subprocess.SubprocessError, OSError, ValueError) as error:
        raise EpisodeError("episode.error.not_video", name=path.name) from error
    streams = data.get("streams") if isinstance(data, dict) else None
    streams = [s for s in streams or [] if isinstance(s, dict)]
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")
        ),
        None,
    )
    if video is None:
        raise EpisodeError("episode.error.not_video", name=path.name)
    duration = _duration((data.get("format") or {}).get("duration")) or _duration(
        video.get("duration")
    )
    if duration is None:
        raise EpisodeError("episode.error.not_video", name=path.name)
    return PartInfo(
        path=path,
        duration=duration,
        has_video=True,
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def _filter_graph(
    infos: list[PartInfo], width: int, height: int, fps: int
) -> tuple[list[str], str]:
    """Extra lavfi inputs (silence for parts without audio) and the filter graph."""
    extra_inputs: list[str] = []
    chains: list[str] = []
    labels: list[str] = []
    silence_index = len(infos)
    for i, info in enumerate(infos):
        chains.append(
            f"[{i}:v:0]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={fps},"
            f"format=yuv420p[v{i}]"
        )
        if info.has_audio:
            source = f"[{i}:a:0]"
        else:
            extra_inputs += [
                "-f",
                "lavfi",
                "-t",
                f"{info.duration:.3f}",
                "-i",
                "anullsrc=r=48000:cl=stereo",
            ]
            source = f"[{silence_index}:a:0]"
            silence_index += 1
        chains.append(
            f"{source}aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=0:{info.duration:.3f},asetpts=PTS-STARTPTS[a{i}]"
        )
        labels.append(f"[v{i}][a{i}]")
    # FFmpeg turns a rotated clip upright as it decodes, yet still hands its
    # rotation on to the joined frames, and the episode file would then tell
    # players to turn the whole video. Every part is upright by now: drop it.
    chains.append(
        f"{''.join(labels)}concat=n={len(infos)}:v=1:a=1[joined][a];"
        "[joined]sidedata=mode=delete:type=DISPLAYMATRIX[v]"
    )
    return extra_inputs, ";".join(chains)


def _last_lines(handle: Any, count: int) -> str:
    handle.seek(0)
    text = handle.read().decode("utf-8", "replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-count:]) or "FFmpeg stopped without saying why."


def _stop(process: subprocess.Popen[str]) -> None:
    """End FFmpeg if it still runs, and reap it."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    process.wait()


def assemble_episode(
    parts: list[Path],
    output: Path,
    *,
    lecture_index: int,
    width: int,
    height: int,
    fps: int,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> EpisodeResult:
    """Join *parts*, in order, into *output* at *width* × *height* and *fps*.

    *lecture_index* is the lecture's place in *parts*; the result says how far
    into the episode it starts. Raises :class:`EpisodeError` for a part that is
    missing or not a video and for a failed join, and ``JobCancelled`` when
    *cancel* is set; either way no partial file is left.
    """
    if not parts:
        raise ValueError("An episode needs at least one part.")
    if not 0 <= lecture_index < len(parts):
        raise ValueError(f"lecture_index {lecture_index} is not one of the {len(parts)} parts.")
    if cancel is not None:
        cancel.raise_if_cancelled("episode")
    infos = [probe_part(Path(part)) for part in parts]
    try:
        ffmpeg = require_binary("ffmpeg", _INSTALL_HINT)
    except RuntimeError as error:
        raise EpisodeError("episode.error.ffmpeg", reason=str(error)) from error

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f"{output.name}.part.mp4")
    extra_inputs, graph = _filter_graph(infos, width, height, fps)
    command = [ffmpeg, "-y", "-nostdin", "-v", "error", "-progress", "pipe:1", "-nostats"]
    for info in infos:
        command += ["-i", str(info.path)]
    command += [*extra_inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]"]
    command += [*_ENCODE_ARGS, str(partial)]

    durations = tuple(info.duration for info in infos)
    total = sum(durations)
    report(progress, STAGE, "Joining the episode", fraction=0.0)
    with tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                # FFmpeg's complaints go to a file nobody has to drain while it runs.
                stderr=errors,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as error:
            raise EpisodeError("episode.error.ffmpeg", reason=str(error)) from error
        try:
            assert process.stdout is not None
            for line in process.stdout:
                if cancel is not None and cancel.cancelled:
                    _stop(process)
                    cancel.raise_if_cancelled("episode")
                key, _, value = line.strip().partition("=")
                if key == "out_time_us" and value.isdigit() and total > 0:
                    done = min(1.0, int(value) / 1_000_000 / total)
                    report(progress, STAGE, "Joining the episode", fraction=done)
            process.wait()
            if cancel is not None:
                cancel.raise_if_cancelled("episode")
            if process.returncode != 0:
                reason = _last_lines(errors, _ERROR_LINES)
                raise EpisodeError("episode.error.ffmpeg", reason=reason)
            try:
                partial.replace(output)
            except OSError as error:
                raise EpisodeError("episode.error.ffmpeg", reason=str(error)) from error
        except BaseException:
            _stop(process)
            partial.unlink(missing_ok=True)
            raise
        finally:
            if process.stdout is not None:
                process.stdout.close()
    report(progress, STAGE, "Joined the episode", fraction=1.0, done=True)
    return EpisodeResult(
        output=output,
        durations=durations,
        lecture_offset=sum(durations[:lecture_index]),
    )

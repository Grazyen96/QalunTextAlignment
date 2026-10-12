"""The episode: an intro, a recitation, the lecture and an outro, joined into one video.

Each part is probed first, so a missing clip or a file that is not a video is
named before anything is encoded. The parts are then joined in one FFmpeg run
through the ``concat`` filter, every part scaled and letterboxed to the
lecture's own size and frame rate: an intro filmed on a phone, upright or on
its side, comes out upright inside black bars rather than stretched. FFmpeg
applies a clip's rotation metadata as it decodes, so a portrait clip recorded
as a rotated landscape stream arrives upright without help; the rotation is
then removed from the joined video, which is upright throughout. A clip whose
pixels are not square is shown at its display shape. An HDR clip (a phone's
HLG or PQ video) is tone-mapped to ordinary BT.709 first, and the joined video
carries no colour tags, as the lecture's own render does not: one HDR intro
must not make players read the whole episode as HDR.

Each part's sound is made exactly as long as the part: sound that starts after
the picture keeps its delay, a short track is padded with silence and a part
with none gets silence of its own. The parts' lengths therefore add up to the
episode's, which is what puts the lecture, and its shifted subtitles, where
:attr:`EpisodeResult.lecture_offset` says.

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
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qurantext.core.video_common import ffmpeg_filters, require_binary
from qurantext.jobs.catalog import RENDERED, job_status
from qurantext.jobs.project import Project, job_settings, load_project, save_project
from qurantext.jobs.project_render import default_video_path, render_project
from qurantext.utils.progress import CancelToken, JobCancelled, ProgressCallback, report

__all__ = [
    "EpisodeError",
    "EpisodeResult",
    "REQUIRED_FILTERS",
    "STAGE",
    "TONE_MAP_FILTERS",
    "PartInfo",
    "assemble_episode",
    "episode_path_for",
    "probe_part",
    "recitation_needs_render",
    "recitation_video",
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
#: Transfer characteristics of HDR video: PQ (HDR10, Dolby Vision) and HLG.
_HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})
#: Filters every join needs, beyond FFmpeg's ever-present scale/pad/concat.
REQUIRED_FILTERS = ("apad", "setparams", "sidedata")
#: Filters an HDR part is tone-mapped with; without them it is only untagged.
TONE_MAP_FILTERS = ("zscale", "tonemap")
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
    #: The stream index of the picture: the first video that is not cover art.
    video_stream: int = 0
    #: The stream index of the sound: the first audio track FFmpeg can decode.
    audio_stream: int | None = None
    #: The picture's transfer characteristic as ffprobe names it, when tagged.
    color_transfer: str | None = None
    color_primaries: str | None = None
    color_space: str | None = None
    #: The picture's pixels are not square (an anamorphic recording).
    anamorphic: bool = False

    @property
    def is_hdr(self) -> bool:
        return self.color_transfer in _HDR_TRANSFERS


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


def _same_file(a: Path, b: Path) -> bool:
    """Whether *a* and *b* name one file, also on a file system that ignores case."""
    a, b = Path(a), Path(b)
    if a.resolve() == b.resolve():
        return True
    try:
        return a.exists() and b.exists() and a.samefile(b)
    except OSError:
        return False


def recitation_needs_render(project: Project, *, avoid: Path | None = None) -> bool:
    """Whether :func:`recitation_video` would render *project* before using it.

    It reuses the recorded render only when the job list calls it current
    (nothing it was made from, nor the job's size or subtitles choice, has
    changed since), its file is still there, and that file is not *avoid* —
    the lecture's own video, which a recitation whose recording has the same
    name may have been rendered over. The Episode dialog says "will be rendered
    first" by this same rule.
    """
    render = project.render
    if render is None or not render.get("video") or job_status(project) != RENDERED:
        return True
    video = Path(render["video"])
    if not video.is_file():
        return True
    return avoid is not None and _same_file(video, avoid)


def recitation_video(
    project_path: Path,
    *,
    avoid: Path | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> Path:
    """The current video of the recitation job at *project_path*, rendered first if need be.

    A recorded render is used when :func:`recitation_needs_render` allows it.
    Otherwise the recitation is rendered again with its own job settings and no
    subtitle files, to the file a render from the window would write — unless
    that is *avoid* (the lecture's video, when both recordings share a name),
    in which case to ``<stem> – recitation.mp4`` beside it.
    It is written under a temporary name in that folder and moved into place
    when complete, so a cancel or failure leaves the earlier video as it was.

    The render is made from the project as loaded here, but its record is
    written onto the project file as it is when the render ends: a correction
    saved meanwhile from an open review is kept, and reads as made after the
    render (stale) rather than being overwritten.

    Raises :class:`EpisodeError` (``episode.error.recitation``) when the
    project is missing or unreadable, is not a recitation, or fails to render.
    A cancel is not a failure and passes through as ``JobCancelled``.
    """
    path = Path(project_path)
    try:
        project = load_project(path)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise EpisodeError("episode.error.recitation", reason=str(error)) from error
    if str(project.mode).lower() != "recitation":
        raise EpisodeError(
            "episode.error.recitation", reason=f"{path.name} is not a recitation job."
        )
    if not recitation_needs_render(project, avoid=avoid):
        assert project.render is not None
        return Path(project.render["video"])
    target = default_video_path(project)
    if avoid is not None and _same_file(target, avoid):
        target = target.with_name(f"{target.stem} – recitation.mp4")
    settings = job_settings(project)
    # Rendered under a name of its own and moved into place when complete: a
    # render of the same recitation from its own review may be writing the
    # target right now, and a cancel or failure here must not take the
    # earlier video with it (the renderer deletes what it was writing).
    partial = target.with_name(f".{target.stem}.{uuid.uuid4().hex[:8]}.part.mp4")
    try:
        result = render_project(
            project,
            partial,
            preset=settings.preset,
            # The job's own choice, so the job list does not call the render
            # "changed since"; a recitation has no live captions to burn.
            subtitles=settings.subtitles,
            formats=(),
            progress=progress,
            cancel=cancel,
            save=False,
        )
    except JobCancelled:
        partial.unlink(missing_ok=True)
        raise
    except Exception as error:  # any render failure is the recitation's, said in a sentence
        partial.unlink(missing_ok=True)
        raise EpisodeError("episode.error.recitation", reason=str(error)) from error
    try:
        Path(result.video).replace(target)
    except OSError as error:
        Path(result.video).unlink(missing_ok=True)
        raise EpisodeError("episode.error.recitation", reason=str(error)) from error
    if project.render is not None and project.render.get("video"):
        # The record names the file where it now is, not where it was made.
        project.render["video"] = target.expanduser().resolve()
    _record_on_the_file(path, project.render, target)
    return target


def _record_on_the_file(path: Path, record: dict[str, Any] | None, video: Path) -> None:
    """Write the render *record* of *video* onto the project file as it is now.

    The video exists whatever happens here; the record only spares the next
    episode a render. A project that cannot be read back or saved (moved,
    deleted, a full disk) is left as it is, and the next episode renders again.
    """
    if record is None or not record.get("video") or not _same_file(record["video"], video):
        return
    try:
        fresh = load_project(path)
        fresh.render = dict(record)
        save_project(fresh, path)
    except (OSError, ValueError, KeyError, TypeError):
        return


def _duration(value: Any) -> float | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def _tag_duration(stream: dict[str, Any]) -> float | None:
    """A Matroska stream's ``DURATION`` tag (``00:01:02.500000000``) in seconds."""
    tags = stream.get("tags") or {}
    value = next((v for k, v in tags.items() if str(k).upper() == "DURATION"), None)
    if not isinstance(value, str):
        return None
    try:
        hours, minutes, seconds = value.strip().split(":")
        return _duration(int(hours) * 3600 + int(minutes) * 60 + float(seconds))
    except ValueError:
        return None


def _packet_duration(ffprobe: str, path: Path, stream: int, start: float) -> float | None:
    """The end of *stream*'s last packet, for a file that states no length.

    A WebM recorded in a browser, or anything written as it went, has no
    duration in its header; reading every packet's time is the honest answer.
    """
    try:
        out = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                str(stream),
                "-show_entries",
                "packet=pts_time,duration_time",
                "-of",
                "csv=p=0",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_PROBE_TIMEOUT_S,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    end = None
    for line in out.splitlines():
        fields = line.strip().split(",")
        pts = _number(fields[0]) if fields else None
        if pts is None:
            continue
        length = _number(fields[1]) if len(fields) > 1 else None
        stop = pts + (length or 0.0)
        end = stop if end is None else max(end, stop)
    return _duration(end - start) if end is not None else None


def _number(value: str) -> float | None:
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _anamorphic(stream: dict[str, Any]) -> bool:
    num, _, den = str(stream.get("sample_aspect_ratio") or "").partition(":")
    try:
        n, d = int(num), int(den)
    except ValueError:
        return False
    return n > 0 and d > 0 and n != d


def _decodable(stream: dict[str, Any]) -> bool:
    return str(stream.get("codec_name") or "none") != "none"


def probe_part(path: Path) -> PartInfo:
    """Read *path*'s length and streams with ffprobe.

    The length is the container's, else the picture stream's, else its
    Matroska ``DURATION`` tag, else the end of its last packet. Raises
    :class:`EpisodeError` with ``episode.error.missing`` when the file is not
    there, and with ``episode.error.not_video`` when ffprobe cannot read it,
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
    if not isinstance(data, dict):
        raise EpisodeError("episode.error.not_video", name=path.name)
    streams = [s for s in data.get("streams") or [] if isinstance(s, dict)]
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video"
            and _decodable(s)
            and not (s.get("disposition") or {}).get("attached_pic")
        ),
        None,
    )
    if video is None or not isinstance(video.get("index"), int):
        raise EpisodeError("episode.error.not_video", name=path.name)
    audio = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "audio" and _decodable(s) and isinstance(s.get("index"), int)
        ),
        None,
    )
    fmt = data.get("format") or {}
    duration = (
        _duration(fmt.get("duration"))
        or _duration(video.get("duration"))
        or _tag_duration(video)
        or _packet_duration(
            ffprobe, path, video["index"], _number(str(fmt.get("start_time"))) or 0.0
        )
    )
    if duration is None:
        raise EpisodeError("episode.error.not_video", name=path.name)

    def tag(key: str) -> str | None:
        value = video.get(key)
        return value if isinstance(value, str) and value not in ("", "unknown") else None

    return PartInfo(
        path=path,
        duration=duration,
        has_video=True,
        has_audio=audio is not None,
        video_stream=video["index"],
        audio_stream=audio["index"] if audio is not None else None,
        color_transfer=tag("color_transfer"),
        color_primaries=tag("color_primaries"),
        color_space=tag("color_space"),
        anamorphic=_anamorphic(video),
    )


def _tone_map(info: PartInfo) -> str:
    """Filters that turn an HDR picture into ordinary 8-bit BT.709.

    The input's transfer is named from the probe; primaries and matrix fall
    back to BT.2020, which every HDR format uses, when the clip does not say.
    """
    given = f"tin={info.color_transfer}"
    if info.color_primaries is None:
        given += ":pin=bt2020"
    if info.color_space is None:
        given += ":min=2020_ncl"
    return (
        f"zscale={given}:t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
        "tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,"
    )


def _filter_graph(
    infos: list[PartInfo], width: int, height: int, fps: int, *, tone_map: bool = True
) -> tuple[list[str], str]:
    """Extra lavfi inputs (silence for parts without audio) and the filter graph.

    *tone_map* False leaves HDR pictures as they are (only untagged), for an
    FFmpeg built without ``zscale``.
    """
    extra_inputs: list[str] = []
    chains: list[str] = []
    labels: list[str] = []
    silence_index = len(infos)
    for i, info in enumerate(infos):
        before = _tone_map(info) if tone_map and info.is_hdr else ""
        if info.anamorphic:
            before += "scale=trunc(iw*sar/2)*2:ih,setsar=1,"
        chains.append(
            f"[{i}:{info.video_stream}]{before}"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={fps},"
            # Untagged before concat, too: FFmpeg would otherwise convert every
            # later part to the first part's colour matrix (a BT.709 phone clip
            # or a tone-mapped HDR intro), shifting the lecture's colours.
            "format=yuv420p,"
            f"setparams=color_primaries=unknown:color_trc=unknown:colorspace=unknown[v{i}]"
        )
        if info.audio_stream is not None:
            source = f"[{i}:{info.audio_stream}]"
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
        # async + first_pts=0 keep sound that starts after the picture where it
        # is, with silence before it; apad + atrim make it exactly the part's
        # length, so the parts add up and nothing drifts after them.
        chains.append(
            f"{source}aresample=48000:async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad,atrim=0:{info.duration:.3f},asetpts=PTS-STARTPTS[a{i}]"
        )
        labels.append(f"[v{i}][a{i}]")
    # FFmpeg turns a rotated clip upright as it decodes, yet still hands its
    # rotation on to the joined frames, and the episode file would then tell
    # players to turn the whole video. Every part is upright by now: drop it.
    # The first part's colour tags would likewise label the whole file (an HDR
    # intro making the lecture read as HDR); the lecture's own render carries
    # none, so neither does the episode.
    chains.append(
        f"{''.join(labels)}concat=n={len(infos)}:v=1:a=1[joined][a];"
        "[joined]setparams=color_primaries=unknown:color_trc=unknown:colorspace=unknown,"
        "sidedata=mode=delete:type=DISPLAYMATRIX[v]"
    )
    return extra_inputs, ";".join(chains)


def _last_lines(handle: Any, count: int) -> str:
    handle.seek(0)
    text = handle.read().decode("utf-8", "replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-count:]) or "FFmpeg stopped without saying why."


def _stop(process: subprocess.Popen[str]) -> None:
    """End FFmpeg at once if it still runs, and reap it.

    Killed, not asked: the partial file is deleted anyway, and a polite stop
    makes FFmpeg flush its encoder and rewrite the whole file for
    ``+faststart`` first — seconds of work on a long lecture, while the person
    who pressed Cancel waits.
    """
    if process.poll() is None:
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
    missing or not a video and for a failed join (a folder that cannot be
    written included), and ``JobCancelled`` when *cancel* is set; either way no
    partial file is left.
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
    tone_map = all(name in ffmpeg_filters(ffmpeg) for name in TONE_MAP_FILTERS)

    output = Path(output)
    partial = output.with_name(f"{output.name}.part.mp4")
    extra_inputs, graph = _filter_graph(infos, width, height, fps, tone_map=tone_map)
    command = [ffmpeg, "-y", "-nostdin", "-v", "error", "-progress", "pipe:1", "-nostats"]
    for info in infos:
        command += ["-i", str(info.path)]
    command += [*extra_inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]"]
    command += [*_ENCODE_ARGS, str(partial)]

    durations = tuple(info.duration for info in infos)
    total = sum(durations)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        errors = tempfile.TemporaryFile()
    except OSError as error:
        raise EpisodeError("episode.error.ffmpeg", reason=str(error)) from error
    report(progress, STAGE, "Joining the episode", fraction=0.0)
    with errors:
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

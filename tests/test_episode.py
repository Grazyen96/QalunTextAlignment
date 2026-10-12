"""Joining an intro, a recitation, the lecture and an outro into one episode video."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from qurantext.jobs.episode import (
    EpisodeError,
    PartInfo,
    _filter_graph,
    assemble_episode,
    episode_path_for,
    probe_part,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="needs FFmpeg"
)


def _make(path: Path, *, size="640x360", fps=25, seconds=1.0, audio=True, rotate=None) -> Path:
    """A short test clip; *rotate* records rotation metadata, the way a phone does."""
    target = path if rotate is None else path.with_name(f"unrotated-{path.name}")
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={size}:rate={fps}:duration={seconds}",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    subprocess.run([*cmd, str(target)], check=True)
    if rotate is not None:
        # FFmpeg 6+ ignores `-metadata:s:v:0 rotate=` when writing, and
        # `-display_rotation` on an input that is re-encoded is applied to the
        # pixels (autorotate). Copying the stream keeps it as metadata. Older
        # FFmpeg has no -display_rotation but still honours the metadata form.
        quiet = ["ffmpeg", "-y", "-loglevel", "error"]
        ways = [
            [*quiet, "-display_rotation", str(rotate), "-i", str(target), "-c", "copy", str(path)],
            [
                *quiet,
                "-i",
                str(target),
                "-c",
                "copy",
                "-metadata:s:v:0",
                f"rotate={rotate}",
                str(path),
            ],
        ]
        if not any(subprocess.run(way, capture_output=True).returncode == 0 for way in ways):
            pytest.skip("this FFmpeg cannot write rotation metadata")
        target.unlink()
    return path


def _streams(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)


def test_episode_path_name():
    assert episode_path_for(Path("/v/lec.mp4")) == Path("/v/lec – episode.mp4")


def test_probe_reports_streams(tmp_path):
    info = probe_part(_make(tmp_path / "a.mp4", audio=False))
    assert info.has_video and not info.has_audio and 0.9 < info.duration < 1.1


def test_probe_refuses_missing_and_non_video(tmp_path):
    with pytest.raises(EpisodeError) as missing:
        probe_part(tmp_path / "none.mp4")
    assert missing.value.key == "episode.error.missing"
    (tmp_path / "bad.mp4").write_bytes(b"nope")
    with pytest.raises(EpisodeError) as bad:
        probe_part(tmp_path / "bad.mp4")
    assert bad.value.key == "episode.error.not_video"


def test_probe_refuses_a_sound_file(tmp_path):
    sound = tmp_path / "s.m4a"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=1",
            "-c:a",
            "aac",
            str(sound),
        ],
        check=True,
    )
    with pytest.raises(EpisodeError) as error:
        probe_part(sound)
    assert error.value.key == "episode.error.not_video" and error.value.fmt == {"name": "s.m4a"}


def test_parts_are_joined_at_the_lecture_geometry(tmp_path):
    parts = [
        _make(tmp_path / "intro.mp4", size="640x360", fps=25, seconds=1),
        _make(tmp_path / "rec.mp4", size="360x640", fps=30, seconds=2),
        _make(tmp_path / "lec.mp4", size="1080x1920", fps=30, seconds=1),
    ]
    out = tmp_path / "ep.mp4"
    result = assemble_episode(parts, out, lecture_index=2, width=1080, height=1920, fps=30)
    data = _streams(out)
    video = [s for s in data["streams"] if s["codec_type"] == "video"]
    audio = [s for s in data["streams"] if s["codec_type"] == "audio"]
    assert len(video) == 1 and (video[0]["width"], video[0]["height"]) == (1080, 1920)
    assert video[0]["r_frame_rate"] == "30/1"
    assert len(audio) == 1 and audio[0]["sample_rate"] == "48000" and audio[0]["channels"] == 2
    assert abs(float(data["format"]["duration"]) - 4.0) < 0.15
    assert abs(result.lecture_offset - 3.0) < 0.1 and len(result.durations) == 3
    assert not (tmp_path / "ep.mp4.part.mp4").exists()


def test_parts_without_audio_get_silence(tmp_path):
    parts = [
        _make(tmp_path / "a.mp4", audio=False, seconds=1),
        _make(tmp_path / "b.mp4", seconds=1),
    ]
    out = tmp_path / "ep.mp4"
    assemble_episode(parts, out, lecture_index=1, width=640, height=360, fps=25)
    audio = [s for s in _streams(out)["streams"] if s["codec_type"] == "audio"]
    assert len(audio) == 1 and abs(float(audio[0]["duration"]) - 2.0) < 0.15


def test_rotated_and_odd_sized_clips_are_letterboxed(tmp_path):
    parts = [
        _make(tmp_path / "phone.mp4", size="640x360", rotate=90, seconds=1),
        _make(tmp_path / "lec.mp4", size="640x360", seconds=1),
    ]
    out = tmp_path / "ep.mp4"
    assemble_episode(parts, out, lecture_index=1, width=640, height=360, fps=25)
    # Extract the first frame. The rotated phone clip is shown upright (taller than
    # wide), so the left and right edges are black bars.
    frame = tmp_path / "f.png"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(out), "-frames:v", "1", str(frame)],
        check=True,
    )
    from PIL import Image

    img = Image.open(frame).convert("RGB")
    assert img.getpixel((5, 180)) == (0, 0, 0) and img.getpixel((634, 180)) == (0, 0, 0)
    assert img.getpixel((320, 180)) != (0, 0, 0)
    # Upright in the file itself: no rotation is handed on for a player to apply.
    (video,) = [s for s in _streams(out)["streams"] if s["codec_type"] == "video"]
    assert (video["width"], video["height"]) == (640, 360)
    assert not any("rotation" in d for d in video.get("side_data_list", []))


def test_cancel_removes_the_partial_file(tmp_path):
    from qurantext.utils.progress import CancelToken, JobCancelled

    parts = [_make(tmp_path / "a.mp4", seconds=2), _make(tmp_path / "b.mp4", seconds=2)]
    token = CancelToken()
    token.cancel()
    with pytest.raises(JobCancelled):
        assemble_episode(
            parts, tmp_path / "ep.mp4", lecture_index=1, width=640, height=360, fps=25, cancel=token
        )
    assert not list(tmp_path.glob("ep.mp4*"))


def test_cancel_during_the_join_stops_ffmpeg_and_removes_the_partial_file(tmp_path):
    from qurantext.utils.progress import CancelToken, JobCancelled

    parts = [_make(tmp_path / "a.mp4", seconds=2), _make(tmp_path / "b.mp4", seconds=2)]
    token = CancelToken()
    seen = []

    def on_progress(event):
        seen.append(event)
        token.cancel()  # the first report from inside the run

    with pytest.raises(JobCancelled):
        assemble_episode(
            parts,
            tmp_path / "ep.mp4",
            lecture_index=1,
            width=640,
            height=360,
            fps=25,
            progress=on_progress,
            cancel=token,
        )
    assert seen and not list(tmp_path.glob("ep.mp4*"))


def test_a_failed_join_says_why_and_leaves_nothing(tmp_path, monkeypatch):
    from qurantext.jobs import episode

    parts = [_make(tmp_path / "a.mp4"), _make(tmp_path / "b.mp4")]
    # A filter graph FFmpeg refuses stands in for any failure inside the run.
    monkeypatch.setattr(episode, "_filter_graph", lambda *a, **k: ([], "[0:v:0]nosuchfilter[v]"))
    with pytest.raises(EpisodeError) as error:
        assemble_episode(parts, tmp_path / "ep.mp4", lecture_index=1, width=640, height=360, fps=25)
    assert error.value.key == "episode.error.ffmpeg" and error.value.fmt["reason"]
    assert not list(tmp_path.glob("ep.mp4*"))


def test_progress_ends_with_a_finished_report(tmp_path):
    parts = [_make(tmp_path / "a.mp4"), _make(tmp_path / "b.mp4")]
    events = []
    assemble_episode(
        parts,
        tmp_path / "ep.mp4",
        lecture_index=0,
        width=640,
        height=360,
        fps=25,
        progress=events.append,
    )
    assert events[-1].done and events[-1].fraction == 1.0
    # A stage the window knows, so the join shows a percentage, not "Working…".
    assert all(e.stage == "render" for e in events)


# -- markers: a white flash in the picture and a beep in the sound -------------------


def _marker_clip(
    path: Path,
    *,
    seconds: float,
    mark: float | None = None,
    audio_delay: float = 0.0,
    audio_seconds: float | None = None,
) -> Path:
    """A black clip that flashes white and beeps at *mark* seconds of its own time.

    *audio_delay* starts the sound track that much after the picture, as a clip
    trimmed by stream copy or a screen recording can; the beep still falls on
    the flash.
    """
    flash = (
        f",drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='between(t,{mark},{mark + 0.12})'"
        if mark is not None
        else ""
    )
    beep_at = (mark - audio_delay) if mark is not None else -10
    length = audio_seconds if audio_seconds is not None else seconds - audio_delay
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=black:s=320x180:r=25:d={seconds}{flash}",
            "-itsoffset",
            str(audio_delay),
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc='0.8*sin(2*PI*1000*t)*between(t,{beep_at},{beep_at + 0.1})':s=48000:d={length}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )
    return path


def _flash_time(path: Path, fps: int = 25) -> float:
    import numpy as np

    raw = subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vf",
            "scale=16:9,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 16 * 9).mean(axis=1)
    return int(np.argmax(frames > 128)) / fps


def _beep_time(path: Path) -> float:
    import numpy as np

    raw = subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            "48000",
            # Measured from the file's time zero, as a player hears it, not
            # from the first sample of a sound track that starts late.
            "-af",
            "aresample=async=1:first_pts=0",
            "-f",
            "f32le",
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    samples = np.abs(np.frombuffer(raw, dtype=np.float32))
    return int(np.argmax(samples > 0.3)) / 48000


def test_sound_that_starts_late_keeps_its_place(tmp_path):
    """A clip whose sound track starts 0.5 s after its picture stays in sync."""
    late = _marker_clip(tmp_path / "late.mp4", seconds=3, mark=1.5, audio_delay=0.5)
    assert abs(_beep_time(late) - _flash_time(late)) < 0.05, "the fixture itself is in sync"
    intro = _marker_clip(tmp_path / "intro.mp4", seconds=1)
    out = tmp_path / "ep.mp4"
    result = assemble_episode([intro, late], out, lecture_index=1, width=320, height=180, fps=25)
    flash, beep = _flash_time(out), _beep_time(out)
    assert abs(flash - (result.lecture_offset + 1.5)) < 0.06
    assert abs(beep - flash) < 0.05, f"beep at {beep:.3f} s, flash at {flash:.3f} s"


def test_each_part_s_sound_lasts_as_long_as_the_part(tmp_path):
    """A short sound track is padded, so the next part and the end are where the lengths say."""
    short = _marker_clip(tmp_path / "short.mp4", seconds=2, audio_seconds=0.5)
    marked = _marker_clip(tmp_path / "marked.mp4", seconds=2, mark=0.5)
    out = tmp_path / "ep.mp4"
    result = assemble_episode(
        [short, marked, short], out, lecture_index=1, width=320, height=180, fps=25
    )
    assert abs(_beep_time(out) - (result.lecture_offset + 0.5)) < 0.05
    (audio,) = [s for s in _streams(out)["streams"] if s["codec_type"] == "audio"]
    assert abs(float(audio["duration"]) - sum(result.durations)) < 0.1


def _hlg(path: Path) -> Path:
    """A 10-bit clip tagged BT.2020 / HLG, as an iPhone records by default."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=360x640:rate=25:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p10le",
            "-color_primaries",
            "bt2020",
            "-color_trc",
            "arib-std-b67",
            "-colorspace",
            "bt2020nc",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.mark.parametrize("tone_map", [True, False], ids=["tone-mapped", "no-zscale"])
def test_an_hdr_intro_does_not_make_the_episode_hdr(tmp_path, monkeypatch, tone_map):
    from qurantext.jobs import episode

    if not tone_map:  # an FFmpeg built without zscale: the tags must still go
        monkeypatch.setattr(episode, "ffmpeg_filters", lambda path: frozenset())
    intro = _hlg(tmp_path / "phone.mp4")
    info = probe_part(intro)
    assert info.is_hdr and info.color_transfer == "arib-std-b67"
    out = tmp_path / "ep.mp4"
    lecture = _make(tmp_path / "lec.mp4", size="640x360")
    assemble_episode([intro, lecture], out, lecture_index=1, width=640, height=360, fps=25)
    (video,) = [s for s in _streams(out)["streams"] if s["codec_type"] == "video"]
    assert video["pix_fmt"] == "yuv420p"
    for key in ("color_primaries", "color_transfer", "color_space"):
        # Untagged, as the lecture's own render is; never BT.2020 or HLG.
        assert video.get(key, "unknown") == "unknown", (key, video.get(key))


def test_hdr_parts_are_tone_mapped_when_ffmpeg_can():
    hdr = PartInfo(Path("a.mov"), 1.0, True, False, color_transfer="smpte2084")
    sdr = PartInfo(Path("b.mp4"), 1.0, True, True, audio_stream=1)
    _, graph = _filter_graph([hdr, sdr], 640, 360, 25)
    first, _, rest = graph.partition(";")
    assert "tonemap" in first and "tin=smpte2084:pin=bt2020:min=2020_ncl" in first
    assert "tonemap" not in rest and "[1:1]aresample" in rest
    _, untouched = _filter_graph([hdr, sdr], 640, 360, 25, tone_map=False)
    assert "tonemap" not in untouched and "setparams=color_primaries=unknown" in untouched


def test_non_square_pixels_are_shown_at_their_display_shape(tmp_path):
    """480×360 pixels at 4:3 show as 640×360: the frame is filled, not pillarboxed."""
    clip = tmp_path / "anamorphic.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=480x360:r=25:d=1,setsar=4/3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
    )
    assert probe_part(clip).anamorphic
    out = tmp_path / "ep.mp4"
    assemble_episode([clip], out, lecture_index=0, width=640, height=360, fps=25)
    frame = tmp_path / "f.png"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(out), "-frames:v", "1", str(frame)],
        check=True,
    )
    from PIL import Image

    img = Image.open(frame).convert("RGB")
    left = img.getpixel((5, 180))
    assert left[0] > 150 and left[1] < 80, left


def test_cancel_mid_join_stops_at_once(tmp_path):
    import time

    from qurantext.utils.progress import CancelToken, JobCancelled

    long_clip = tmp_path / "long.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=25:duration=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(long_clip),
        ],
        check=True,
    )
    token = CancelToken()
    cancelled_at: list[float] = []
    events = 0

    def on_progress(event):
        nonlocal events
        events += 1
        if events == 2:  # the first report from inside the run
            cancelled_at.append(time.monotonic())
            token.cancel()

    with pytest.raises(JobCancelled):
        assemble_episode(
            [long_clip],
            tmp_path / "ep.mp4",
            lecture_index=0,
            width=1280,
            height=720,
            fps=25,
            progress=on_progress,
            cancel=token,
        )
    assert cancelled_at and time.monotonic() - cancelled_at[0] < 2.0
    assert not list(tmp_path.glob("ep.mp4*"))


def test_a_clip_that_states_no_length_is_measured(tmp_path):
    """A Matroska written to a pipe, like a browser's recording, has no duration in its header."""
    clip = tmp_path / "streamed.mkv"
    with clip.open("wb") as sink:
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=320x180:rate=25:duration=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-f",
                "matroska",
                "pipe:1",
            ],
            check=True,
            stdout=sink,
        )
    data = _streams(clip)
    assert "duration" not in data["format"], "the fixture must state no length"
    assert abs(probe_part(clip).duration - 2.0) < 0.1


def test_the_picture_and_sound_are_the_streams_the_probe_chose(tmp_path):
    """Sound first, picture second: the graph maps by stream index, not by type."""
    swapped = tmp_path / "swapped.mp4"
    plain = _make(tmp_path / "plain.mp4")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(plain),
            "-map",
            "0:a",
            "-map",
            "0:v",
            "-c",
            "copy",
            str(swapped),
        ],
        check=True,
    )
    info = probe_part(swapped)
    assert (info.audio_stream, info.video_stream) == (0, 1)
    out = tmp_path / "ep.mp4"
    assemble_episode([swapped], out, lecture_index=0, width=640, height=360, fps=25)
    kinds = sorted(s["codec_type"] for s in _streams(out)["streams"])
    assert kinds == ["audio", "video"]


def test_a_folder_that_cannot_be_written_is_an_episode_error(tmp_path):
    import os

    clip = _make(tmp_path / "a.mp4")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip("running with permissions that ignore the folder's mode")
        with pytest.raises(EpisodeError) as error:
            assemble_episode(
                [clip], locked / "sub" / "ep.mp4", lecture_index=0, width=640, height=360, fps=25
            )
        assert error.value.key == "episode.error.ffmpeg"
    finally:
        locked.chmod(0o700)


def _yuv_frame(path: Path, at: float, size: tuple[int, int] = (640, 360)):
    import numpy as np

    raw = subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv420p",
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    w, h = size
    planes = np.frombuffer(raw, dtype=np.uint8).astype(np.int16)
    y, u, v = planes[: w * h], planes[w * h : w * h * 5 // 4], planes[w * h * 5 // 4 :]
    return y, u, v


def _bt709_intro(path: Path) -> Path:
    """An ordinary SDR phone clip, tagged BT.709."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=360x640:rate=25:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.mark.parametrize("intro_kind", ["bt709", "hlg", "hlg-no-zscale"])
def test_the_lecture_keeps_its_colours_whatever_comes_first(tmp_path, monkeypatch, intro_kind):
    """A tagged intro first must not convert the lecture to its colour matrix."""
    import numpy as np

    from qurantext.jobs import episode

    if intro_kind == "hlg-no-zscale":
        monkeypatch.setattr(episode, "ffmpeg_filters", lambda path: frozenset())
    intro = (_bt709_intro if intro_kind == "bt709" else _hlg)(tmp_path / "intro.mp4")
    lecture = tmp_path / "lec.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "smptebars=size=640x360:rate=25:duration=2",
            "-c:v",
            "libx264",
            "-qp",
            "0",
            "-pix_fmt",
            "yuv420p",
            str(lecture),
        ],
        check=True,
    )
    out = tmp_path / "ep.mp4"
    result = assemble_episode([intro, lecture], out, lecture_index=1, width=640, height=360, fps=25)
    source = _yuv_frame(lecture, 1.0)
    joined = _yuv_frame(out, result.lecture_offset + 1.0)
    for name, a, b in zip("YUV", source, joined, strict=True):
        shift = float(np.abs(a - b).mean())
        assert shift < 1.0, f"{name} moved by {shift:.2f} levels on average"


def test_an_episode_open_in_another_program_is_said_in_a_sentence(tmp_path, monkeypatch):
    """Windows refuses to replace a file a player has open: "[WinError 32] …"."""
    from qurantext.gui.i18n import t

    clip = _make(tmp_path / "a.mp4")
    out = tmp_path / "ep.mp4"
    out.write_bytes(b"the episode a player has open")
    real_replace = Path.replace

    def locked(self, target):
        if Path(target) == out:
            raise PermissionError(13, "[WinError 32] The process cannot access the file")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", locked)
    with pytest.raises(EpisodeError) as error:
        assemble_episode([clip], out, lecture_index=0, width=640, height=360, fps=25)
    assert error.value.key == "episode.error.locked" and error.value.fmt == {"name": "ep.mp4"}
    said = t(error.value.key, **error.value.fmt)
    assert "ep.mp4" in said and "WinError" not in said
    assert out.read_bytes() == b"the episode a player has open"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.mp4", "ep.mp4"], "no partial file"

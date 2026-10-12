"""Joining an intro, a recitation, the lecture and an outro into one episode video."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from qurantext.jobs.episode import EpisodeError, assemble_episode, episode_path_for, probe_part

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
        # This FFmpeg ignores `-metadata:s:v:0 rotate=` when writing, and
        # `-display_rotation` on an input that is re-encoded is applied to the
        # pixels (autorotate). Copying the stream keeps it as metadata.
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-display_rotation",
                str(rotate),
                "-i",
                str(target),
                "-c",
                "copy",
                str(path),
            ],
            check=True,
        )
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
    monkeypatch.setattr(episode, "_filter_graph", lambda *a: ([], "[0:v:0]nosuchfilter[v]"))
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

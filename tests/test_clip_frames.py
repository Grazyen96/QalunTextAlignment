# tests/test_clip_frames.py
"""A still from a clip for the Episode dialog's cards: grabbed once, then served from the cache."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from qurantext.jobs import clip_frames
from qurantext.jobs.clip_frames import clip_frame

ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _clip(path: Path, size: str = "160x90") -> Path:
    subprocess.run(
        [shutil.which("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
         f"color=c=red:s={size}:d=1", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )  # fmt: skip
    return path


@ffmpeg
def test_a_landscape_clip_gives_a_176_wide_png_served_from_the_cache_next_time(
    tmp_path, monkeypatch
) -> None:
    clip = _clip(tmp_path / "intro.mp4")
    png = clip_frame(clip, tmp_path / "cache", seconds=1.0)
    assert png is not None and png.parent == tmp_path / "cache" / "thumbs"
    with Image.open(png) as image:
        assert image.size == (176, 99)
        assert image.convert("RGB").getpixel((88, 49))[0] > 200
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    assert clip_frame(clip, tmp_path / "cache", seconds=1.0) == png
    assert not calls, "a hit does not run ffmpeg"


@ffmpeg
def test_a_portrait_clip_gives_a_176_tall_png(tmp_path) -> None:
    png = clip_frame(_clip(tmp_path / "up.mp4", "90x160"), tmp_path / "cache", seconds=None)
    with Image.open(png) as image:
        assert image.size == (99, 176)


def test_no_cache_dir_a_missing_file_and_a_missing_ffmpeg_give_none(tmp_path, monkeypatch) -> None:
    assert clip_frame(tmp_path / "x.mp4", None, seconds=1.0) is None
    assert clip_frame(tmp_path / "x.mp4", tmp_path / "cache", seconds=1.0) is None
    (tmp_path / "y.mp4").write_bytes(b"not a video")

    def missing(name, hint=None):
        raise RuntimeError("no ffmpeg")

    monkeypatch.setattr(clip_frames, "require_binary", missing)
    assert clip_frame(tmp_path / "y.mp4", tmp_path / "cache", seconds=1.0) is None


def test_a_failing_or_slow_ffmpeg_gives_none_and_leaves_no_part_file(tmp_path, monkeypatch) -> None:
    (tmp_path / "y.mp4").write_bytes(b"not a video")
    monkeypatch.setattr(clip_frames, "require_binary", lambda name, hint=None: "ffmpeg")

    def fails(*a, **k):
        raise subprocess.CalledProcessError(1, a[0])

    monkeypatch.setattr(subprocess, "run", fails)
    assert clip_frame(tmp_path / "y.mp4", tmp_path / "cache", seconds=1.0) is None

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], clip_frames.TIMEOUT_S)

    monkeypatch.setattr(subprocess, "run", slow)
    assert clip_frame(tmp_path / "y.mp4", tmp_path / "cache", seconds=1.0) is None
    assert not list((tmp_path / "cache" / "thumbs").glob("*.part"))


@ffmpeg
def test_a_seek_past_the_picture_falls_back_to_the_first_frame(tmp_path) -> None:
    """A short picture under a long sound: half the length lands after the last frame."""
    clip = _clip(tmp_path / "sting.mp4")
    png = clip_frame(clip, tmp_path / "cache", seconds=10.0)  # the seek lands at 5 s
    assert png is not None and png.stat().st_size > 0
    with Image.open(png) as image:
        assert image.size == (176, 99)


def test_an_empty_frame_twice_gives_none_and_caches_nothing(tmp_path, monkeypatch) -> None:
    (tmp_path / "y.mp4").write_bytes(b"a clip")
    monkeypatch.setattr(clip_frames, "require_binary", lambda name, hint=None: "ffmpeg")
    seeks = []

    def writes_nothing(command, **kwargs):
        seeks.append(command[command.index("-ss") + 1])
        Path(command[-1]).write_bytes(b"")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", writes_nothing)
    assert clip_frame(tmp_path / "y.mp4", tmp_path / "cache", seconds=10.0) is None
    assert seeks == ["5.000", "0.000"]
    assert not list((tmp_path / "cache" / "thumbs").iterdir())

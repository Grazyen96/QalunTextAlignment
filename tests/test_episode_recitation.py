"""The recitation part of an episode: its current video, rendered first when stale.

No FFmpeg is needed: the render is replaced by a fake that records how it was asked.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qurantext.jobs.episode import EpisodeError, recitation_video
from qurantext.jobs.project import (
    CaptionCue,
    JobSettings,
    Project,
    save_project,
    set_job_settings,
)
from qurantext.jobs.project_render import default_video_path
from qurantext.utils.progress import JobCancelled


@pytest.fixture()
def recitation_project(tmp_path: Path) -> Project:
    """A saved recitation whose recorded render exists and matches its content."""
    words = [{"word": "w", "start": 0.5, "end": 1.0}]
    project = Project(
        audio=tmp_path / "a.mp3",
        matches=tmp_path / "m.json",
        mode="recitation",
        cards=[
            {
                "surah_num": 25,
                "from_ayah": 7,
                "to_ayah": 7,
                "start_time": 0.5,
                "end_time": 2.0,
                "word_timings": words,
            }
        ],
    )
    set_job_settings(project, JobSettings(preset="fast", output_dir=tmp_path / "videos"))
    video = tmp_path / "videos" / "a.mp4"
    video.parent.mkdir()
    video.touch()
    project.record_render(video, preset="fast", basmala_offset_s=0.0)
    save_project(project, tmp_path / "rec.qalun.json")
    return project


@pytest.fixture()
def lecture_project(tmp_path: Path) -> Project:
    project = Project(
        audio=tmp_path / "dars.mp3",
        mode="lecture",
        cards=[{"surah_num": 25, "from_ayah": 7, "to_ayah": 7, "start_time": 0.0, "end_time": 4.0}],
        captions=[CaptionCue(0.0, 2.0, "first line")],
    )
    save_project(project, tmp_path / "lec.qalun.json")
    return project


def test_a_current_render_is_reused(tmp_path, monkeypatch, recitation_project):
    calls = []
    monkeypatch.setattr("qurantext.jobs.episode.render_project", lambda *a, **k: calls.append(1))
    assert recitation_video(recitation_project.path) == Path(recitation_project.render["video"])
    assert calls == []


def test_a_stale_render_is_rendered_again(tmp_path, monkeypatch, recitation_project):
    recitation_project.cards[0]["end_time"] += 0.5  # change the content
    save_project(recitation_project, recitation_project.path)
    seen = {}

    def fake(project, output, **kw):
        seen.update(kw, output=output)
        return SimpleNamespace(video=output)

    monkeypatch.setattr("qurantext.jobs.episode.render_project", fake)
    video = recitation_video(recitation_project.path)
    assert seen["subtitles"] == "sidecar" and seen["formats"] == () and video == seen["output"]
    assert seen["preset"] == "fast"
    assert seen["output"] == default_video_path(recitation_project) == tmp_path / "videos" / "a.mp4"


def test_a_render_whose_file_is_gone_is_rendered_again(tmp_path, monkeypatch, recitation_project):
    Path(recitation_project.render["video"]).unlink()
    calls = []

    def fake(project, output, **kw):
        calls.append(output)
        return SimpleNamespace(video=output)

    monkeypatch.setattr("qurantext.jobs.episode.render_project", fake)
    assert recitation_video(recitation_project.path) == calls[0]


def test_a_missing_or_wrong_project_raises(tmp_path, lecture_project):
    with pytest.raises(EpisodeError):
        recitation_video(tmp_path / "gone.qalun.json")
    with pytest.raises(EpisodeError) as wrong:
        recitation_video(lecture_project.path)  # a lecture, not a recitation
    assert (
        wrong.value.key == "episode.error.recitation"
        and "lec.qalun.json" in wrong.value.fmt["reason"]
    )


def test_a_failed_render_is_said_as_a_recitation_error(monkeypatch, recitation_project):
    recitation_project.cards[0]["end_time"] += 0.5
    save_project(recitation_project, recitation_project.path)

    def broken(*a, **k):
        raise RuntimeError("FFmpeg failed")

    monkeypatch.setattr("qurantext.jobs.episode.render_project", broken)
    with pytest.raises(EpisodeError) as error:
        recitation_video(recitation_project.path)
    assert error.value.key == "episode.error.recitation" and error.value.fmt == {
        "reason": "FFmpeg failed"
    }


def test_a_cancelled_render_passes_through(monkeypatch, recitation_project):
    recitation_project.cards[0]["end_time"] += 0.5
    save_project(recitation_project, recitation_project.path)

    def cancelled(*a, **k):
        raise JobCancelled("render was cancelled")

    monkeypatch.setattr("qurantext.jobs.episode.render_project", cancelled)
    with pytest.raises(JobCancelled):
        recitation_video(recitation_project.path)


def test_default_video_path_prefers_the_given_folder(tmp_path, recitation_project):
    assert (
        default_video_path(recitation_project, output_dir=tmp_path / "x")
        == tmp_path / "x" / "a.mp4"
    )

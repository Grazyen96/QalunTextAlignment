"""The recitation part of an episode: its current video, rendered first when stale.

No FFmpeg is needed: the render is replaced by a fake that records how it was asked.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qurantext.jobs.catalog import CHANGED_SINCE_RENDER, RENDERED, job_status
from qurantext.jobs.episode import EpisodeError, recitation_needs_render, recitation_video
from qurantext.jobs.project import (
    CaptionCue,
    JobSettings,
    Project,
    job_settings,
    load_project,
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
    set_job_settings(
        project, JobSettings(preset="fast", subtitles="both", output_dir=tmp_path / "videos")
    )
    video = tmp_path / "videos" / "a.mp4"
    video.parent.mkdir()
    video.touch()
    project.record_render(video, preset="fast", basmala_offset_s=0.0, subtitles="both")
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
        output.write_bytes(b"new render")
        return SimpleNamespace(video=output)

    monkeypatch.setattr("qurantext.jobs.episode.render_project", fake)
    video = recitation_video(recitation_project.path)
    # The job's own choices, so the job list calls the new render current; no files.
    assert seen["subtitles"] == "both" and seen["formats"] == ()
    assert seen["preset"] == "fast" and seen["save"] is False
    # Written beside the target under a name of its own, then moved into place.
    assert video == default_video_path(recitation_project) == tmp_path / "videos" / "a.mp4"
    assert seen["output"].parent == video.parent and seen["output"] != video
    assert video.read_bytes() == b"new render" and not seen["output"].exists()


def test_a_render_whose_file_is_gone_is_rendered_again(tmp_path, monkeypatch, recitation_project):
    Path(recitation_project.render["video"]).unlink()
    calls = []

    def fake(project, output, **kw):
        calls.append(output)
        output.write_bytes(b"new render")
        return SimpleNamespace(video=output)

    monkeypatch.setattr("qurantext.jobs.episode.render_project", fake)
    assert recitation_video(recitation_project.path) == default_video_path(recitation_project)
    assert len(calls) == 1


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


def _fake_export(monkeypatch, during=None):
    """Replace the encoder under the real ``render_project``; *during* runs mid-render."""
    from qurantext.jobs.export import ExportResult
    from qurantext.jobs.render import RenderResult

    requests = []

    def fake(request, progress=None, cancel=None):
        requests.append(request)
        if during is not None:
            during()
        request.output.parent.mkdir(parents=True, exist_ok=True)
        request.output.write_bytes(b"video")
        return ExportResult(
            video=request.output,
            render=RenderResult(
                output=request.output, width=960, height=540, fps=24, duration_seconds=2.0
            ),
        )

    monkeypatch.setattr("qurantext.jobs.project_render.export_job", fake)
    return requests


def _make_stale(project: Project) -> None:
    project.cards[0]["end_time"] += 0.5
    save_project(project, project.path)


def test_the_recitation_s_own_record_reads_rendered_afterwards(monkeypatch, recitation_project):
    _make_stale(recitation_project)
    requests = _fake_export(monkeypatch)
    video = recitation_video(recitation_project.path)
    assert requests and requests[0].subtitles == "both" and requests[0].formats == ()
    again = load_project(recitation_project.path)
    assert again.render["video"] == video and again.render["subtitles"] == "both"
    assert again.render_is_stale is False and job_status(again) == RENDERED


def test_a_correction_saved_during_the_render_is_kept(monkeypatch, recitation_project):
    _make_stale(recitation_project)

    def review_saves_a_correction():
        opened = load_project(recitation_project.path)
        opened.cards[0]["end_time"] = 9.99
        save_project(opened, opened.path)

    _fake_export(monkeypatch, during=review_saves_a_correction)
    video = recitation_video(recitation_project.path)
    again = load_project(recitation_project.path)
    assert again.cards[0]["end_time"] == 9.99, "the correction was overwritten"
    assert again.render["video"] == video
    # The render was made before the correction, so it reads as stale, not current.
    assert again.render_is_stale is True and job_status(again) == CHANGED_SINCE_RENDER


def test_a_recitation_never_renders_over_the_lecture(tmp_path, monkeypatch, recitation_project):
    """Both recordings named ``a``: the recitation goes to ``a – recitation.mp4``."""
    lecture_video = default_video_path(recitation_project)  # the lecture's file, same name
    _make_stale(recitation_project)
    _fake_export(monkeypatch)
    video = recitation_video(recitation_project.path, avoid=lecture_video)
    assert video == lecture_video.with_name("a – recitation.mp4")
    assert lecture_video.read_bytes() == b"", "the lecture video was written over"


def test_a_recorded_render_that_is_now_the_lecture_is_not_reused(
    tmp_path, monkeypatch, recitation_project
):
    lecture_video = Path(recitation_project.render["video"])  # current, but the lecture's path
    assert not recitation_needs_render(recitation_project)
    assert recitation_needs_render(recitation_project, avoid=lecture_video)
    _fake_export(monkeypatch)
    video = recitation_video(recitation_project.path, avoid=lecture_video)
    assert video.name == "a – recitation.mp4"


def test_a_size_change_since_the_render_renders_again(monkeypatch, recitation_project):
    """The rule matches the job list's: another preset is a render that is not current."""
    set_job_settings(
        recitation_project, JobSettings(**{**_settings(recitation_project), "preset": "high"})
    )
    save_project(recitation_project, recitation_project.path)
    assert recitation_needs_render(load_project(recitation_project.path))
    requests = _fake_export(monkeypatch)
    recitation_video(recitation_project.path)
    assert requests[0].preset == "high"


def _settings(project: Project) -> dict:
    from dataclasses import asdict

    return asdict(job_settings(project))


@pytest.mark.parametrize("stop", [JobCancelled("cancelled"), RuntimeError("FFmpeg failed")])
def test_a_stopped_render_keeps_the_earlier_video(monkeypatch, recitation_project, stop):
    """The renderer deletes what it was writing; that must not be the earlier video."""
    earlier = Path(recitation_project.render["video"])
    earlier.write_bytes(b"earlier render")
    _make_stale(recitation_project)
    written = []

    def stopped(project, output, **kw):
        written.append(output)
        output.write_bytes(b"half")
        raise stop

    monkeypatch.setattr("qurantext.jobs.episode.render_project", stopped)
    with pytest.raises((JobCancelled, EpisodeError)):
        recitation_video(recitation_project.path)
    assert earlier.read_bytes() == b"earlier render"
    assert written and written[0] != earlier and not written[0].exists()


def test_two_renders_of_one_recitation_write_separate_files(monkeypatch, recitation_project):
    """Another render of the same recitation (from its own review) may be under way."""
    _make_stale(recitation_project)
    outputs = []

    def fake(project, output, **kw):
        outputs.append(output)
        output.write_bytes(b"render")
        return SimpleNamespace(video=output)

    monkeypatch.setattr("qurantext.jobs.episode.render_project", fake)
    recitation_video(recitation_project.path)
    recitation_video(recitation_project.path)
    assert len(set(outputs)) == 2 and default_video_path(recitation_project) not in outputs


def test_a_newer_render_of_the_recitation_is_not_moved_over(monkeypatch, recitation_project):
    """Its own review rendered it again while the episode's render ran: that one is kept."""
    import os

    earlier = Path(recitation_project.render["video"])
    earlier.write_bytes(b"earlier render")
    os.utime(earlier, ns=(1_000_000_000, 1_000_000_000))
    _make_stale(recitation_project)

    def review_renders_meanwhile():
        earlier.write_bytes(b"the review's newer render")

    _fake_export(monkeypatch, during=review_renders_meanwhile)
    with pytest.raises(EpisodeError) as raised:
        recitation_video(recitation_project.path)
    assert raised.value.key == "episode.error.recitation_changed"
    assert raised.value.fmt == {"name": earlier.name}
    assert earlier.read_bytes() == b"the review's newer render"
    leftovers = [p.name for p in earlier.parent.iterdir() if p.name.endswith(".part.mp4")]
    assert leftovers == [], "the episode's own render is removed"


def test_a_recitation_target_that_appears_meanwhile_is_not_moved_over(
    monkeypatch, recitation_project
):
    earlier = Path(recitation_project.render["video"])
    earlier.unlink()
    _make_stale(recitation_project)
    _fake_export(monkeypatch, during=lambda: earlier.write_bytes(b"someone else's"))
    with pytest.raises(EpisodeError) as raised:
        recitation_video(recitation_project.path)
    assert raised.value.key == "episode.error.recitation_changed"
    assert earlier.read_bytes() == b"someone else's"


def test_a_locked_recitation_video_is_said_in_a_sentence(monkeypatch, recitation_project):
    """Windows refuses to replace a file a player has open: "[WinError 32] …"."""
    from qurantext.gui.i18n import t

    earlier = Path(recitation_project.render["video"])
    _make_stale(recitation_project)
    _fake_export(monkeypatch)
    real_replace = Path.replace

    def locked(self, target):
        if Path(target) == earlier:
            raise PermissionError(13, "[WinError 32] The process cannot access the file")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", locked)
    with pytest.raises(EpisodeError) as raised:
        recitation_video(recitation_project.path)
    assert raised.value.key == "episode.error.locked"
    said = t(raised.value.key, **raised.value.fmt)
    assert earlier.name in said and "WinError" not in said
    leftovers = [p.name for p in earlier.parent.iterdir() if p.name.endswith(".part.mp4")]
    assert leftovers == []

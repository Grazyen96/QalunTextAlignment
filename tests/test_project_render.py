"""A project is what gets rendered and exported, so corrections reach the output."""

from __future__ import annotations

import pytest

from qurantext.config.paths import DEFAULT_FONT_PATH
from qurantext.jobs.project import Project, load_project, save_project
from qurantext.jobs.project_render import export_project_subtitles, render_project
from tests.test_export import _job, no_basmala, pytestmark, store  # noqa: F401,F811


def _project(tmp_path):
    audio, matches = _job(tmp_path)
    project = Project.from_match_file(matches, audio)
    save_project(project, tmp_path / "job.qalun.json")
    return project


def test_render_project_records_the_render_and_saves(tmp_path, store, no_basmala) -> None:  # noqa: F811
    project = _project(tmp_path)
    result = render_project(
        project,
        tmp_path / "v.mp4",
        width=160,
        height=120,
        fps=8,
        font_file=DEFAULT_FONT_PATH,
        db_path=store,
    )
    assert result.video.exists()
    reloaded = load_project(project.path)
    assert reloaded.render["video"] == result.video
    assert reloaded.render_is_stale is False


def test_render_project_follows_the_projects_cards(tmp_path, store, no_basmala) -> None:  # noqa: F811
    project = _project(tmp_path)
    project.cards[0]["start_time"] = 1.0
    result = render_project(
        project,
        tmp_path / "v.mp4",
        subtitles="sidecar",
        formats=("srt",),
        width=160,
        height=120,
        fps=8,
        font_file=DEFAULT_FONT_PATH,
        db_path=store,
    )
    srt = result.subtitles[0].read_text(encoding="utf-8-sig")
    assert "00:00:01,000 -->" in srt


def test_export_writes_the_chosen_formats_without_rendering(tmp_path, store) -> None:  # noqa: F811
    project = _project(tmp_path)
    written = export_project_subtitles(
        project, tmp_path / "out" / "clip", ("srt", "vtt", "ass"), db_path=store
    )
    assert sorted(p.suffix for p in written) == [".ass", ".srt", ".vtt"]
    assert not list(tmp_path.glob("**/*.mp4"))


def test_export_on_the_video_timeline_applies_the_basmala_offset(tmp_path, store) -> None:  # noqa: F811
    project = _project(tmp_path)
    with pytest.raises(ValueError, match="rendered"):
        export_project_subtitles(project, tmp_path / "a", ("srt",), timeline="video", db_path=store)

    project.record_render(tmp_path / "v.mp4", preset="social", basmala_offset_s=2.0)
    (path,) = export_project_subtitles(
        project, tmp_path / "b", ("srt",), timeline="video", db_path=store
    )
    assert "00:00:02,000 -->" in path.read_text(encoding="utf-8-sig")


def test_the_render_records_the_content_it_started_from(tmp_path, monkeypatch) -> None:
    """An edit made while a render runs must leave that render looking stale."""
    from qurantext.jobs import project_render
    from qurantext.jobs.export import ExportResult
    from qurantext.jobs.render import RenderResult

    words = [{"word": "w", "start": 0.5, "end": 1.0}]
    project = Project(
        audio=tmp_path / "a.mp3",
        matches=tmp_path / "m.json",
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
    seen = {}

    def fake_export_job(request, *, progress=None, cancel=None):
        project.cards[0]["word_timings"][0]["start"] = 0.7  # the user keeps editing
        project.cards[0]["start_time"] = 0.7
        seen["cards"] = request.cards
        video = tmp_path / "v.mp4"
        return ExportResult(
            video=video,
            render=RenderResult(output=video, width=160, height=120, fps=8, duration_seconds=2.0),
        )

    monkeypatch.setattr(project_render, "export_job", fake_export_job)
    render_project(project, tmp_path / "v.mp4", preset="social")

    assert seen["cards"][0]["start_time"] == 0.5, "rendered from the snapshot"
    assert seen["cards"][0]["word_timings"][0]["start"] == 0.5
    assert project.render_is_stale is True
    assert (project.render["width"], project.render["height"], project.render["fps"]) == (
        160,
        120,
        8,
    )
    assert project.render["preset"] == "social"


def test_ass_export_uses_the_recorded_render_size(tmp_path, store) -> None:  # noqa: F811
    project = _project(tmp_path)
    project.record_render(
        tmp_path / "v.mp4", preset="social", basmala_offset_s=0.0, width=720, height=404, fps=25
    )
    (path,) = export_project_subtitles(project, tmp_path / "c", ("ass",), db_path=store)
    text = path.read_text(encoding="utf-8-sig")
    assert "PlayResX: 720" in text and "PlayResY: 404" in text

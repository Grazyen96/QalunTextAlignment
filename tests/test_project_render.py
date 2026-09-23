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

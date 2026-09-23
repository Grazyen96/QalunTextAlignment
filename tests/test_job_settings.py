"""The job's output choices, kept with the job in its project file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qurantext.jobs.project import (
    SUBTITLE_CHOICES,
    JobSettings,
    Project,
    job_settings,
    load_project,
    save_project,
    set_job_settings,
)


def test_a_project_without_choices_reads_the_defaults() -> None:
    settings = job_settings(Project(audio=Path("a.mp3")))
    assert settings == JobSettings()
    assert settings == JobSettings("social", "burn", ("srt",), None)
    assert SUBTITLE_CHOICES == ("burn", "sidecar", "both")


def test_choices_survive_a_save_and_a_load(tmp_path) -> None:
    project = Project(audio=tmp_path / "a.mp3")
    chosen = JobSettings(
        preset="fast", subtitles="both", formats=("srt", "vtt"), output_dir=tmp_path / "jobs"
    )
    set_job_settings(project, chosen)
    path = save_project(project, tmp_path / "jobs" / "a.qalun.json")

    raw = json.loads(path.read_text(encoding="utf-8"))["export"]
    assert raw == {
        "preset": "fast",
        "subtitles": "both",
        "formats": ["srt", "vtt"],
        "output_dir": ".",
    }, "stored as plain JSON, the folder relative to the project file like its other paths"
    assert job_settings(load_project(path)) == JobSettings(
        "fast", "both", ("srt", "vtt"), (tmp_path / "jobs").resolve()
    )


def test_an_output_folder_elsewhere_is_stored_absolute(tmp_path) -> None:
    project = Project(audio=tmp_path / "a.mp3")
    set_job_settings(project, JobSettings(output_dir=tmp_path / "videos"))
    path = save_project(project, tmp_path / "jobs" / "a.qalun.json")
    raw = json.loads(path.read_text(encoding="utf-8"))["export"]
    assert raw["output_dir"] == (tmp_path / "videos").resolve().as_posix()
    assert job_settings(load_project(path)).output_dir == (tmp_path / "videos").resolve()


def test_the_output_folder_follows_a_moved_job_folder(tmp_path) -> None:
    project = Project(audio=tmp_path / "old" / "a.mp3")
    set_job_settings(project, JobSettings(output_dir=tmp_path / "old"))
    save_project(project, tmp_path / "old" / "a.qalun.json")
    (tmp_path / "old").rename(tmp_path / "new")
    moved = load_project(tmp_path / "new" / "a.qalun.json")
    assert job_settings(moved).output_dir == (tmp_path / "new").resolve()


def test_clearing_the_output_folder_removes_it() -> None:
    project = Project(audio=Path("a.mp3"))
    set_job_settings(project, JobSettings(output_dir=Path("/tmp/somewhere")))
    set_job_settings(project, JobSettings())
    assert "output_dir" not in project.export
    assert job_settings(project).output_dir is None


@pytest.mark.parametrize(
    ("export", "expected"),
    [
        ({"preset": "cinema"}, JobSettings()),
        ({"preset": 7}, JobSettings()),
        ({"subtitles": "karaoke"}, JobSettings()),
        ({"subtitles": None}, JobSettings()),
        ({"formats": "srt"}, JobSettings()),
        ({"formats": ["docx"]}, JobSettings()),
        ({"formats": []}, JobSettings()),
        ({"formats": ["vtt", "docx", "vtt"]}, JobSettings(formats=("vtt",))),
        ({"output_dir": 3}, JobSettings()),
        ({"output_dir": ""}, JobSettings()),
    ],
)
def test_unknown_or_invalid_choices_fall_back_to_the_defaults(export, expected) -> None:
    assert job_settings(Project(audio=Path("a.mp3"), export=export)) == expected


def test_setting_the_choices_keeps_the_other_export_keys(tmp_path) -> None:
    project = Project(audio=tmp_path / "a.mp3", export={"future": {"x": 1}, "preset": "fast"})
    set_job_settings(project, JobSettings(preset="high", subtitles="sidecar"))
    assert project.export["future"] == {"x": 1}
    path = save_project(project, tmp_path / "a.qalun.json")
    reloaded = load_project(path)
    assert reloaded.export["future"] == {"x": 1}
    assert job_settings(reloaded) == JobSettings(preset="high", subtitles="sidecar")


def test_the_choices_are_not_part_of_the_content_hash() -> None:
    project = Project(audio=Path("a.mp3"))
    before = project.content_hash()
    set_job_settings(project, JobSettings(preset="fast"))
    assert project.content_hash() == before

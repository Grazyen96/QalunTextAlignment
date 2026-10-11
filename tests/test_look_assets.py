from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from qurantext.core.looks import NIGHT_GOLD, PRESETS, Background
from qurantext.jobs.look_assets import (
    import_look_image,
    look_dir_for,
    project_look,
    set_project_look,
)
from qurantext.jobs.project import CaptionCue, Project, load_project, save_project


def _project(tmp_path: Path) -> Project:
    project = Project(
        audio=tmp_path / "dars.mp3",
        mode="lecture",
        cards=[{"surah_num": 25, "from_ayah": 7, "to_ayah": 7, "start_time": 0.0, "end_time": 4.0}],
        captions=[CaptionCue(0.0, 2.0, "first line")],
    )
    save_project(project, tmp_path / "job.qalun.json")
    return project


def _png(path: Path) -> Path:
    Image.new("RGB", (8, 8), (9, 9, 9)).save(path)
    return path


def test_import_copies_once_and_stores_relative(tmp_path: Path) -> None:
    project_path = tmp_path / "job.qalun.json"
    src = tmp_path / "Photo.JPG"
    Image.new("RGB", (10, 10), (1, 2, 3)).save(src, "JPEG")
    first = import_look_image(project_path, src)
    second = import_look_image(project_path, src)
    assert first == second
    assert first.parent == look_dir_for(project_path) == tmp_path / "job.qalun.look"
    assert first.suffix == ".jpg" and len(first.stem) == 12
    assert len(list(first.parent.iterdir())) == 1


def test_import_refuses_other_types_and_missing_files(tmp_path: Path) -> None:
    (tmp_path / "a.gif").write_bytes(b"GIF89a")
    with pytest.raises(ValueError):
        import_look_image(tmp_path / "job.qalun.json", tmp_path / "a.gif")
    with pytest.raises(FileNotFoundError):
        import_look_image(tmp_path / "job.qalun.json", tmp_path / "none.png")


def test_project_look_round_trips_through_the_file_and_survives_a_move(tmp_path: Path) -> None:
    project = _project(tmp_path)
    image = import_look_image(project.path, _png(tmp_path / "bg.png"))
    look = replace(
        PRESETS["ocean"],
        background=Background("image", (0, 0, 0, 255), (0, 0, 0, 255), image, 0.35, 0),
    )
    set_project_look(project, look)
    save_project(project, project.path)
    assert project.style["background"]["image"] == "job.qalun.look/" + image.name

    moved = tmp_path / "moved"
    moved.mkdir()
    for p in tmp_path.iterdir():
        if p != moved:
            p.rename(moved / p.name)
    reloaded = load_project(moved / project.path.name)
    assert (
        project_look(reloaded).background.image == (moved / "job.qalun.look" / image.name).resolve()
    )


def test_night_gold_on_an_empty_style_stays_empty(tmp_path: Path) -> None:
    project = _project(tmp_path)
    set_project_look(project, NIGHT_GOLD)
    assert project.style == {}


def test_choosing_night_gold_again_restores_the_empty_style_and_hash(tmp_path: Path) -> None:
    project = _project(tmp_path)
    original = project.content_hash()
    set_project_look(project, PRESETS["emerald"])
    assert project.style["preset"] == "emerald"
    assert project.content_hash() != original
    set_project_look(project, NIGHT_GOLD)
    assert project.style == {}
    assert project.content_hash() == original


def test_choosing_night_gold_keeps_keys_that_are_not_a_look(tmp_path: Path) -> None:
    project = _project(tmp_path)
    project.style = {"future_option": 3}
    set_project_look(project, PRESETS["emerald"])
    set_project_look(project, NIGHT_GOLD)
    assert project.style == {"future_option": 3}

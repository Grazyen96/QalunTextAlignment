"""A lecture's episode choices, kept in its project with its clips copied beside it."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from qurantext.jobs.episode_assets import (
    EpisodeChoice,
    episode_dir_for,
    import_episode_clip,
    project_episode,
    set_project_episode,
)
from qurantext.jobs.project import CaptionCue, Project, load_project, save_project


@pytest.fixture()
def lecture_project(tmp_path: Path) -> Project:
    """A minimal lecture project saved at ``tmp_path / "lec.qalun.json"``."""
    project = Project(
        audio=tmp_path / "dars.mp3",
        mode="lecture",
        cards=[{"surah_num": 25, "from_ayah": 7, "to_ayah": 7, "start_time": 0.0, "end_time": 4.0}],
        captions=[CaptionCue(0.0, 2.0, "first line")],
    )
    save_project(project, tmp_path / "lec.qalun.json")
    return project


def _clip(path: Path, data: bytes = b"\x00\x00\x00\x18ftypmp42") -> Path:
    path.write_bytes(data)
    return path


def test_import_copies_once_beside_the_project(tmp_path):
    project_path = tmp_path / "lec.qalun.json"
    a = import_episode_clip(project_path, _clip(tmp_path / "Intro.MP4"))
    b = import_episode_clip(project_path, _clip(tmp_path / "copy.mp4"))
    assert a == b and a.parent == episode_dir_for(project_path) == tmp_path / "lec.qalun.episode"
    assert a.suffix == ".mp4" and (a.stat().st_mode & 0o777) == 0o644


def test_import_refuses_non_video_types(tmp_path):
    with pytest.raises(ValueError):
        import_episode_clip(tmp_path / "lec.qalun.json", _clip(tmp_path / "x.gif"))


def test_episode_round_trips_and_keeps_unknown_keys(tmp_path, lecture_project):
    intro = import_episode_clip(lecture_project.path, _clip(tmp_path / "i.mp4"))
    rec = tmp_path / "rec.qalun.json"
    lecture_project.episode = {"future": 1}
    set_project_episode(lecture_project, EpisodeChoice(intro, rec, None))
    save_project(lecture_project, lecture_project.path)
    again = load_project(lecture_project.path)
    assert again.episode["future"] == 1
    assert again.episode["intro"] == "lec.qalun.episode/" + intro.name
    assert project_episode(again) == EpisodeChoice(intro.resolve(), rec.resolve(), None)


def test_episode_paths_survive_moving_the_folder(tmp_path, lecture_project):
    intro = import_episode_clip(lecture_project.path, _clip(tmp_path / "i.mp4"))
    set_project_episode(lecture_project, EpisodeChoice(intro, None, None))
    save_project(lecture_project, lecture_project.path)
    moved = tmp_path / "moved"
    moved.mkdir()
    for p in list(tmp_path.iterdir()):
        if p != moved:
            p.rename(moved / p.name)
    again = load_project(moved / "lec.qalun.json")
    assert project_episode(again).intro == (moved / "lec.qalun.episode" / intro.name).resolve()


def test_junk_values_become_none(lecture_project):
    lecture_project.episode = {"intro": 5, "recitation": ["x"], "outro": None}
    assert project_episode(lecture_project) == EpisodeChoice(None, None, None)


def test_an_empty_choice_clears_to_an_empty_dict(lecture_project, tmp_path):
    set_project_episode(lecture_project, EpisodeChoice(None, tmp_path / "r.qalun.json", None))
    set_project_episode(lecture_project, EpisodeChoice(None, None, None))
    assert lecture_project.episode == {}


def test_a_path_outside_the_project_folder_is_stored_absolute(tmp_path, lecture_project):
    elsewhere = tmp_path.parent / "elsewhere" / "rec.qalun.json"
    set_project_episode(lecture_project, EpisodeChoice(None, elsewhere, None))
    assert lecture_project.episode["recitation"] == elsewhere.resolve().as_posix()


def test_the_choice_says_which_parts_are_set():
    assert EpisodeChoice().is_empty and EpisodeChoice().parts_set == ()
    choice = EpisodeChoice(Path("i.mp4"), None, Path("o.mp4"))
    assert not choice.is_empty and choice.parts_set == ("intro", "outro")


def test_a_non_dict_episode_in_the_file_reads_as_empty(tmp_path, lecture_project):
    import json

    data = json.loads(lecture_project.path.read_text(encoding="utf-8"))
    data["episode"] = ["junk"]
    lecture_project.path.write_text(json.dumps(data), encoding="utf-8")
    assert load_project(lecture_project.path).episode == {}


def test_an_intro_or_outro_of_an_unknown_type_is_ignored(lecture_project):
    lecture_project.episode = {"intro": "notes.txt", "outro": "end.MOV", "recitation": "r.json"}
    choice = project_episode(lecture_project)
    assert choice.intro is None and choice.outro is not None and choice.recitation is not None


def test_an_unsaved_project_stores_absolute_paths(tmp_path, monkeypatch):
    """With no file and no folder given, a relative path would be read later against the wrong folder."""
    monkeypatch.chdir(tmp_path)
    project = Project(audio=tmp_path / "dars.mp3", mode="lecture")
    clip = tmp_path / "clips" / "intro.mp4"
    set_project_episode(project, EpisodeChoice(clip, None, None))
    assert project.episode["intro"] == clip.resolve().as_posix()


def test_a_clip_keeps_its_original_name_beside_its_copy(tmp_path, lecture_project):
    copy = import_episode_clip(lecture_project.path, _clip(tmp_path / "Channel intro.mp4"))
    choice = EpisodeChoice(copy, None, None, intro_name="Channel intro.mp4")
    set_project_episode(lecture_project, choice)
    assert lecture_project.episode == {
        "intro": f"lec.qalun.episode/{copy.name}",
        "intro_name": "Channel intro.mp4",
    }
    save_project(lecture_project, lecture_project.path)
    assert project_episode(load_project(lecture_project.path)) == choice


def test_a_name_goes_with_its_clip(lecture_project, tmp_path):
    """A name for a part not chosen is not stored; removing the clip drops its name."""
    clip = tmp_path / "intro.mp4"
    set_project_episode(lecture_project, EpisodeChoice(clip, None, None, intro_name="Intro.mp4"))
    set_project_episode(lecture_project, EpisodeChoice(None, None, None, outro_name="End.mov"))
    assert lecture_project.episode == {}


@pytest.mark.parametrize("name", [3, "", "  ", ["x"]])
def test_a_name_of_the_wrong_shape_is_unknown(lecture_project, name):
    lecture_project.episode = {"intro": "intro.mp4", "intro_name": name, "outro_name": "x.mov"}
    choice = project_episode(lecture_project)
    assert choice.intro is not None and choice.intro_name is None
    assert choice.outro_name is None, "a name without its clip is nothing"


def test_seeding_keeps_the_default_s_name(tmp_path, lecture_project):
    from qurantext.jobs.episode_assets import seed_project_episode

    project = Project(audio=tmp_path / "new.mp3", mode="lecture")
    default = _clip(tmp_path / "3f2a9c1b2d4e.mp4")  # the app keeps it by its content
    notices = seed_project_episode(
        project, tmp_path / "new.qalun.json", default, None, names=("Channel intro.mp4", None)
    )
    assert notices == []
    assert project_episode(project).intro_name == "Channel intro.mp4"
    assert project.episode["intro_name"] == "Channel intro.mp4"


# --- generated intro and outro settings -----------------------------------------


def test_generated_settings_round_trip_through_the_project(lecture_project):
    from qurantext.jobs.episode_assets import GeneratedIntro, GeneratedOutro

    outro = GeneratedOutro(link="example.org", platform="telegram")
    intro = GeneratedIntro(name="دروس الشيخ أحمد", style="reveal", seconds=7.5)
    set_project_episode(
        lecture_project, EpisodeChoice(intro_generated=intro, outro_generated=outro)
    )
    save_project(lecture_project, lecture_project.path)

    again = project_episode(load_project(lecture_project.path))
    assert again.outro_generated == outro and again.intro_generated == intro
    assert again.outro_generated.phrase == "جزاكم الله خيرًا", "the default phrase"
    assert again.intro is None and again.outro is None
    assert again.parts_set == ("intro", "outro") and not again.is_empty
    assert again.is_generated("outro") and not again.is_generated("recitation")


def test_junk_generated_settings_fall_back(lecture_project):
    from qurantext.jobs.episode_assets import GeneratedOutro

    lecture_project.episode = {
        "outro_generated": {"seconds": "lots", "style": "spin", "platform": 5, "link": "ex.org"}
    }
    outro = project_episode(lecture_project).outro_generated
    assert outro == GeneratedOutro(link="ex.org")
    assert (outro.seconds, outro.style, outro.platform) == (6.0, "fade", "youtube")

    lecture_project.episode = {"outro_generated": {"seconds": 99, "phrase": 3, "name": None}}
    outro = project_episode(lecture_project).outro_generated
    assert outro.seconds == 10.0 and outro.phrase == "جزاكم الله خيرًا", "clamped; a default"
    lecture_project.episode = {"intro_generated": {"seconds": 1, "name": ["x"]}}
    intro = project_episode(lecture_project).intro_generated
    assert (intro.seconds, intro.name) == (3.0, "")
    lecture_project.episode = {"intro_generated": {"seconds": float("nan"), "style": "rise"}}
    assert project_episode(lecture_project).intro_generated.seconds == 5.0
    assert project_episode(lecture_project).intro_generated.style == "rise"

    for junk in ("fade", 3, ["seconds"], None, True):
        lecture_project.episode = {"intro_generated": junk, "outro_generated": junk}
        choice = project_episode(lecture_project)
        assert choice.intro_generated is None and choice.outro_generated is None, junk
        assert choice.is_empty, junk


def test_a_part_is_either_a_clip_or_generated(tmp_path, lecture_project):
    from qurantext.jobs.episode_assets import GeneratedIntro

    clip = import_episode_clip(lecture_project.path, _clip(tmp_path / "i.mp4"))
    set_project_episode(lecture_project, EpisodeChoice(intro=clip, intro_name="Channel.mp4"))
    assert {"intro", "intro_name"} <= set(lecture_project.episode)

    # A generated intro after a clip removes the clip's keys.
    current = project_episode(lecture_project)
    set_project_episode(
        lecture_project, replace(current, intro_generated=GeneratedIntro(name="دروس"))
    )
    assert set(lecture_project.episode) == {"intro_generated"}
    assert project_episode(lecture_project).intro is None

    # And the reverse: a clip after a generated intro removes its settings.
    set_project_episode(lecture_project, EpisodeChoice(intro=clip))
    assert set(lecture_project.episode) == {"intro"}
    assert project_episode(lecture_project).intro_generated is None

    # Given both, the generated settings win; a hand-edited file holding both reads so too.
    both = EpisodeChoice(intro=clip, intro_name="x.mp4", intro_generated=GeneratedIntro())
    assert both.intro is None and both.intro_name is None
    lecture_project.episode = {"intro": "lec.qalun.episode/" + clip.name, "intro_generated": {}}
    read = project_episode(lecture_project)
    assert read.intro is None and read.intro_generated == GeneratedIntro()


def test_seeding_stores_generated_defaults_without_copying(tmp_path):
    from qurantext.jobs.episode_assets import GeneratedOutro, seed_project_episode

    project = Project(audio=tmp_path / "new.mp3", mode="lecture")
    clip = _clip(tmp_path / "3f2a9c1b2d4e.mp4")
    outro = GeneratedOutro(link="example.org/dars", platform="tiktok")
    notices = seed_project_episode(
        project, tmp_path / "new.qalun.json", clip, clip, generated=(None, outro)
    )
    assert notices == []
    choice = project_episode(project)
    assert choice.outro_generated == outro and choice.outro is None
    assert choice.intro is not None, "the intro clip is still copied"
    copies = list(episode_dir_for(tmp_path / "new.qalun.json").iterdir())
    assert [copy.name for copy in copies] == [choice.intro.name], "one copy: the intro's"

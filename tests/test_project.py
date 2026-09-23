"""The project file, which is what makes a subtitle correction survive.

Captions used to be rebuilt from the raw recognition JSON on every render, so
an edit had nowhere to live. These pin the replacement: derive once, store,
and read back from the store.
"""

from __future__ import annotations

import json
import os

import pytest

from qurantext.jobs.project import (
    PROJECT_VERSION,
    CaptionCue,
    Project,
    load_project,
    save_project,
)


def _match_payload() -> dict:
    return {
        "matches": [
            {
                "surah_num": 25,
                "surah_name": "سُورَةُ الفُرقَانِ",
                "from_ayah": 7,
                "to_ayah": 7,
                "full_text": "وَقَالُواْ مَالِ هَٰذَا اَ۬لرَّسُولِ",
                "confidence": 0.9,
                "start_time": 0.0,
                "end_time": 4.0,
            }
        ],
        "meta": {"mode": "lecture"},
    }


def _project(tmp_path) -> Project:
    return Project(
        audio=tmp_path / "dars.mp3",
        mode="lecture",
        cards=_match_payload()["matches"],
        captions=[
            CaptionCue(0.0, 2.0, "first line", words=[{"word": "first", "start": 0.0, "end": 1.0}]),
            CaptionCue(2.0, 4.0, "second line"),
        ],
    )


def test_round_trip_preserves_cards_captions_and_mode(tmp_path) -> None:
    path = save_project(_project(tmp_path), tmp_path / "job.qalun.json")
    loaded = load_project(path)

    assert loaded.mode == "lecture"
    assert len(loaded.cards) == 1
    assert [c.text for c in loaded.captions] == ["first line", "second line"]
    assert loaded.captions[0].words[0]["word"] == "first"
    assert loaded.path == path


def test_a_corrected_caption_is_what_the_renderer_receives(tmp_path) -> None:
    """The point of the whole file: an edit reaches the render."""
    path = save_project(_project(tmp_path), tmp_path / "job.qalun.json")

    data = json.loads(path.read_text(encoding="utf-8"))
    data["captions"][0]["text"] = "corrected by hand"
    data["captions"][0].pop("words", None)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    segments = load_project(path).caption_segments()
    assert segments[0]["text"] == "corrected by hand"
    assert segments[0]["word_timings"] == []
    assert segments[1]["text"] == "second line"


def test_editing_text_keeps_word_timings_when_the_word_count_is_unchanged() -> None:
    cue = CaptionCue(
        0.0,
        2.0,
        "one two",
        words=[
            {"word": "one", "start": 0.0, "end": 1.0},
            {"word": "two", "start": 1.0, "end": 2.0},
        ],
    )
    assert cue.edited("one two") is cue

    fixed = cue.edited("one too")
    assert fixed.text == "one too"
    assert [w["word"] for w in fixed.words] == ["one", "too"]
    assert [w["start"] for w in fixed.words] == [0.0, 1.0]
    assert cue.words[1]["word"] == "two", "the original cue must not be mutated"


def test_editing_text_drops_word_timings_when_the_word_count_changes() -> None:
    cue = CaptionCue(0.0, 1.0, "original", words=[{"word": "original", "start": 0.0, "end": 1.0}])
    changed = cue.edited("two words")
    assert changed.words == []
    assert cue.words


def test_media_paths_are_stored_relative_so_a_project_folder_can_move(tmp_path) -> None:
    audio = tmp_path / "audio" / "dars.mp3"
    audio.parent.mkdir()
    audio.touch()
    project = Project(audio=audio, mode="lecture")
    path = save_project(project, tmp_path / "job.qalun.json")

    stored = json.loads(path.read_text(encoding="utf-8"))["audio"]
    assert stored == "audio/dars.mp3", stored

    moved = tmp_path / "elsewhere"
    moved.mkdir()
    (moved / "audio").mkdir()
    (moved / "audio" / "dars.mp3").touch()
    (moved / "job.qalun.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    assert load_project(moved / "job.qalun.json").audio == (moved / "audio" / "dars.mp3").resolve()


def test_an_absolute_path_outside_the_project_folder_stays_absolute(tmp_path) -> None:
    outside = tmp_path.parent / "outside.mp3"
    project = Project(audio=outside, mode="recitation")
    path = save_project(project, tmp_path / "job.qalun.json")
    assert json.loads(path.read_text(encoding="utf-8"))["audio"].startswith("/")


def test_from_match_file_derives_cards_and_mode(tmp_path) -> None:
    matches = tmp_path / "m.json"
    matches.write_text(json.dumps(_match_payload(), ensure_ascii=False), encoding="utf-8")

    project = Project.from_match_file(matches, tmp_path / "dars.mp3")
    assert project.mode == "lecture"
    assert len(project.cards) == 1
    # No transcript path in meta, so there are no cues to derive; that is a
    # warning in the renderer, not a failure here.
    assert project.captions == []


def test_an_unknown_project_version_is_refused(tmp_path) -> None:
    path = tmp_path / "job.qalun.json"
    path.write_text(json.dumps({"project_version": "999", "audio": "a.mp3"}), encoding="utf-8")
    with pytest.raises(ValueError, match="999"):
        load_project(path)


def test_a_missing_or_malformed_project_fails_clearly(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="Project file not found"):
        load_project(tmp_path / "nope.json")

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Failed to parse project file"):
        load_project(bad)


def test_current_version_is_written(tmp_path) -> None:
    path = save_project(_project(tmp_path), tmp_path / "job.qalun.json")
    assert json.loads(path.read_text(encoding="utf-8"))["project_version"] == PROJECT_VERSION


def test_version_one_files_load_and_are_written_back_as_version_two(tmp_path) -> None:
    path = tmp_path / "job.qalun.json"
    path.write_text(
        json.dumps({"project_version": "1", "audio": "a.mp3", "mode": "lecture", "cards": []}),
        encoding="utf-8",
    )
    project = load_project(path)
    assert project.matches is None
    assert project.review["state"] == "needs_review"
    assert project.render is None
    save_project(project, path)
    assert json.loads(path.read_text(encoding="utf-8"))["project_version"] == "2"


def test_unknown_top_level_keys_survive_a_round_trip(tmp_path) -> None:
    path = tmp_path / "job.qalun.json"
    save_project(_project(tmp_path), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["written_by_a_newer_build"] = {"keep": True}
    path.write_text(json.dumps(data), encoding="utf-8")

    save_project(load_project(path), path)
    assert json.loads(path.read_text(encoding="utf-8"))["written_by_a_newer_build"] == {
        "keep": True
    }


def test_from_match_file_remembers_the_match_file(tmp_path) -> None:
    matches = tmp_path / "m.json"
    matches.write_text(json.dumps(_match_payload(), ensure_ascii=False), encoding="utf-8")
    project = Project.from_match_file(matches, tmp_path / "dars.mp3")
    assert project.matches == matches.resolve()

    path = save_project(project, tmp_path / "job.qalun.json")
    assert json.loads(path.read_text(encoding="utf-8"))["matches"] == "m.json"
    assert load_project(path).matches == matches.resolve()


def test_a_render_is_stale_only_after_the_content_changes(tmp_path) -> None:
    project = _project(tmp_path)
    assert project.render_is_stale is False

    project.record_render(tmp_path / "v.mp4", preset="social", basmala_offset_s=3.25)
    assert project.render["basmala_offset_s"] == 3.25
    assert project.render_is_stale is False

    path = save_project(project, tmp_path / "job.qalun.json")
    reloaded = load_project(path)
    assert reloaded.render_is_stale is False, "saving right after a render is not a change"
    assert reloaded.render["video"] == (tmp_path / "v.mp4").resolve()

    reloaded.cards[0]["start_time"] = 0.5
    assert reloaded.render_is_stale is True


def test_mark_reviewed_records_state_and_time(tmp_path) -> None:
    from datetime import datetime

    project = _project(tmp_path)
    project.mark_reviewed(datetime(2026, 9, 23, 10, 0, 0))
    assert project.review == {"state": "reviewed", "reviewed_at": "2026-09-23T10:00:00"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cards", {"0": {"surah_num": 25}}),
        ("cards", {}),
        ("cards", [{"surah_num": 25}, "not a card"]),
        ("captions", {"start": 0.0}),
        ("captions", ["not a cue"]),
    ],
)
def test_a_malformed_cards_or_captions_shape_is_refused_by_name(tmp_path, field, value) -> None:
    path = tmp_path / "p.qalun.json"
    path.write_text(json.dumps({"audio": "a.mp3", field: value}), encoding="utf-8")
    with pytest.raises(ValueError, match=field):
        load_project(path)


def test_record_render_takes_a_given_content_hash_verbatim(tmp_path) -> None:
    project = Project(audio=tmp_path / "a.mp3")
    project.record_render(
        tmp_path / "v.mp4", preset=None, basmala_offset_s=0.0, content_hash="abc", width=10
    )
    assert project.render["content_hash"] == "abc"
    assert project.render_is_stale is True
    assert project.render["width"] == 10


def test_project_path_for_sits_beside_the_match_file(tmp_path) -> None:
    from qurantext.jobs.project import project_path_for

    assert project_path_for(tmp_path / "clip_recitation.json") == (
        tmp_path / "clip_recitation.qalun.json"
    )


def test_project_init_writes_where_the_app_looks_by_default(tmp_path, capsys) -> None:
    """The CLI and the window must agree, or the job list never shows a CLI project."""
    from qurantext.cli.main import main
    from qurantext.jobs.project import project_path_for

    matches = tmp_path / "matching" / "clip_lecture.json"
    matches.parent.mkdir()
    matches.write_text(json.dumps(_match_payload(), ensure_ascii=False), encoding="utf-8")
    audio = tmp_path / "media" / "clip.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"")

    assert main(["project", "init", "--audio", str(audio), "--matches", str(matches)]) == 0
    expected = project_path_for(matches.resolve())
    assert expected.is_file()
    assert not audio.with_suffix(".qalun.json").exists()
    assert str(expected) in capsys.readouterr().out


def test_a_save_that_fails_partway_leaves_the_previous_file_intact(tmp_path, monkeypatch) -> None:
    from qurantext.jobs import project as project_module

    path = save_project(_project(tmp_path), tmp_path / "p.qalun.json")
    before = path.read_text(encoding="utf-8")

    def failing_dump(obj, handle, **kwargs):
        handle.write('{"project_version": "2", "cards": [')
        raise OSError("No space left on device")

    monkeypatch.setattr(project_module.json, "dump", failing_dump)
    changed = _project(tmp_path)
    changed.cards = []
    with pytest.raises(OSError, match="No space"):
        save_project(changed, path)

    assert path.read_text(encoding="utf-8") == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["p.qalun.json"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_an_atomic_save_keeps_ordinary_permissions(tmp_path) -> None:
    path = save_project(_project(tmp_path), tmp_path / "p.qalun.json")
    assert path.stat().st_mode & 0o777 == 0o644
    path.chmod(0o640)
    save_project(_project(tmp_path), path)
    assert path.stat().st_mode & 0o777 == 0o640

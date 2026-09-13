"""The project file, which is what makes a subtitle correction survive.

Captions used to be rebuilt from the raw recognition JSON on every render, so
an edit had nowhere to live. These pin the replacement: derive once, store,
and read back from the store.
"""

from __future__ import annotations

import json

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


def test_editing_text_drops_word_timings_that_no_longer_match() -> None:
    cue = CaptionCue(0.0, 1.0, "original", words=[{"word": "original", "start": 0.0, "end": 1.0}])
    assert cue.edited("original") is cue

    changed = cue.edited("rewritten")
    assert changed.text == "rewritten"
    assert changed.words == []
    assert cue.words, "the original cue must not be mutated"


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

"""The job list: every project the app has made, and what state it is in."""

from __future__ import annotations

import json
import os
from pathlib import Path as PathlibPath
from unittest.mock import patch

from qurantext.jobs.catalog import (
    CHANGED_SINCE_RENDER,
    DAMAGED,
    NEEDS_REVIEW,
    RENDERED,
    REVIEWED,
    ayah_range,
    default_job_dirs,
    job_dirs_for,
    list_jobs,
)
from qurantext.jobs.project import Project, save_project
from qurantext.utils.progress import CancelToken, JobCancelled


def _card(surah, a, b, kind=None):
    card = {"surah_num": surah, "from_ayah": a, "to_ayah": b, "start_time": 0.0, "end_time": 1.0}
    if kind:
        card["kind"] = kind
    return card


def _save(tmp_path, name, **changes):
    project = Project(audio=tmp_path / f"{name}.mp3", mode="recitation", cards=[_card(25, 7, 11)])
    for key, value in changes.items():
        setattr(project, key, value)
    return save_project(project, tmp_path / f"{name}_recitation.qalun.json")


def test_statuses(tmp_path) -> None:
    _save(tmp_path, "fresh")
    reviewed = Project(audio=tmp_path / "r.mp3", cards=[_card(1, 1, 7)])
    reviewed.mark_reviewed()
    save_project(reviewed, tmp_path / "r_recitation.qalun.json")
    rendered = Project(audio=tmp_path / "v.mp3", cards=[_card(1, 1, 7)])
    rendered.record_render(tmp_path / "v.mp4", preset="social", basmala_offset_s=0.0)
    save_project(rendered, tmp_path / "v_recitation.qalun.json")
    changed = Project(audio=tmp_path / "c.mp3", cards=[_card(1, 1, 7)])
    changed.record_render(tmp_path / "c.mp4", preset="social", basmala_offset_s=0.0)
    changed.cards[0]["start_time"] = 0.5
    save_project(changed, tmp_path / "c_recitation.qalun.json")

    by_name = {entry.name: entry.status for entry in list_jobs([tmp_path])}
    assert by_name == {
        "fresh": NEEDS_REVIEW,
        "r": REVIEWED,
        "v": RENDERED,
        "c": CHANGED_SINCE_RENDER,
    }


def test_newest_first_and_backups_are_not_jobs(tmp_path) -> None:
    older = _save(tmp_path, "older")
    newer = _save(tmp_path, "newer")
    os.utime(older, (1_000_000, 1_000_000))
    (tmp_path / "newer_recitation.20260923T101200.qalun-backup.json").write_text("{}")
    assert [entry.name for entry in list_jobs([tmp_path])] == ["newer", "older"]
    assert newer.exists()


def test_a_damaged_file_is_listed_not_skipped(tmp_path) -> None:
    (tmp_path / "broken.qalun.json").write_text("{not json", encoding="utf-8")
    (entry,) = list_jobs([tmp_path])
    assert entry.status == DAMAGED and entry.error


def test_missing_folders_are_fine(tmp_path) -> None:
    assert list_jobs([tmp_path / "nope"]) == []


def test_ayah_range() -> None:
    assert ayah_range([_card(25, 7, 8), _card(25, 9, 11)]) == "25:7–11"
    assert ayah_range([_card(25, 77, 77), _card(26, 1, 3)]) == "25:77–26:3"
    assert ayah_range([_card(None, None, None, kind="preamble"), _card(1, 1, 7)]) == "1:1–7"
    assert ayah_range([]) is None


def test_a_malformed_card_marks_only_that_job_damaged(tmp_path) -> None:
    _save(tmp_path, "good")
    bad_path = tmp_path / "bad_recitation.qalun.json"
    bad_project = {
        "audio": str(tmp_path / "bad.mp3"),
        "mode": "recitation",
        "cards": [
            {"surah_num": 5, "from_ayah": None, "to_ayah": None, "start_time": 0.0, "end_time": 1.0}
        ],
        "review": {},
    }
    bad_path.write_text(json.dumps(bad_project), encoding="utf-8")

    entries = list_jobs([tmp_path])
    by_name = {entry.name: entry.status for entry in entries}
    assert by_name == {"good": NEEDS_REVIEW, "bad": DAMAGED}
    assert next(e for e in entries if e.name == "bad").error


def test_a_file_that_vanishes_mid_scan_is_skipped(tmp_path) -> None:
    _save(tmp_path, "good")
    vanishing = _save(tmp_path, "vanishing")

    original_stat = PathlibPath.stat
    vanishing_str = str(vanishing)

    def stat_wrapper(self):
        if isinstance(self, PathlibPath) and str(self) == vanishing_str:
            raise FileNotFoundError(f"{self} disappeared")
        return original_stat(self)

    with patch.object(PathlibPath, "stat", stat_wrapper):
        entries = list_jobs([tmp_path])

    names = [entry.name for entry in entries]
    assert "good" in names
    assert "vanishing" not in names


def test_a_malformed_cards_shape_marks_the_job_damaged(tmp_path) -> None:
    _save(tmp_path, "good")
    for name, cards in (("dict", {"0": _card(25, 7, 8)}), ("mixed", [_card(25, 7, 8), 3])):
        (tmp_path / f"{name}_recitation.qalun.json").write_text(
            json.dumps({"audio": str(tmp_path / f"{name}.mp3"), "cards": cards}), encoding="utf-8"
        )
    by_name = {entry.name: entry.status for entry in list_jobs([tmp_path])}
    assert by_name == {
        "good": NEEDS_REVIEW,
        "dict_recitation": DAMAGED,
        "mixed_recitation": DAMAGED,
    }


def test_a_derive_stage_attribute_error_marks_the_job_damaged(tmp_path) -> None:
    _save(tmp_path, "odd")
    with patch("qurantext.jobs.catalog.ayah_range", side_effect=AttributeError("no get")):
        (entry,) = list_jobs([tmp_path])
    assert entry.status == DAMAGED and "no get" in entry.error


def test_a_duplicate_folder_lists_its_jobs_once(tmp_path) -> None:
    _save(tmp_path, "a")
    symlinked = tmp_path / "alias"
    symlinked.symlink_to(tmp_path, target_is_directory=True)
    assert [entry.name for entry in list_jobs([tmp_path, tmp_path, symlinked])] == ["a"]


def test_a_hidden_project_is_skipped(tmp_path) -> None:
    kept = _save(tmp_path, "kept")
    hidden = _save(tmp_path, "hidden")
    entries = list_jobs([tmp_path], hidden=frozenset({hidden.resolve()}))
    assert [entry.name for entry in entries] == ["kept"]
    assert kept.exists() and hidden.exists(), "hiding never touches the file"


def test_job_dirs_for_adds_new_folders_after_the_defaults(tmp_path) -> None:
    extra = tmp_path / "custom"
    assert job_dirs_for([extra]) == [*default_job_dirs(), extra]


def test_job_dirs_for_dedupes_against_the_defaults_and_itself(tmp_path) -> None:
    defaults = default_job_dirs()
    extra = tmp_path / "custom"
    result = job_dirs_for([defaults[0], extra, extra])
    assert result == [*defaults, extra]


def test_an_unreadable_file_is_listed_as_damaged(tmp_path) -> None:
    locked = _save(tmp_path, "locked")
    original_stat = PathlibPath.stat

    def stat_wrapper(self, *args, **kwargs):
        if str(self) == str(locked):
            raise PermissionError(f"{self}: permission denied")
        return original_stat(self, *args, **kwargs)

    with patch.object(PathlibPath, "stat", stat_wrapper):
        (entry,) = list_jobs([tmp_path])
    assert entry.status == DAMAGED
    assert entry.mode == "" and entry.modified == 0.0
    assert "permission denied" in entry.error


def test_a_job_whose_choices_changed_since_its_render_reads_changed(tmp_path) -> None:
    """Re-run as another size or subtitle choice, the video on disk is not what the job makes."""
    from qurantext.jobs.project import JobSettings, set_job_settings

    def rendered(name, **settings):
        project = Project(audio=tmp_path / f"{name}.mp3", cards=[_card(1, 1, 7)])
        project.record_render(
            tmp_path / f"{name}.mp4", preset="social", basmala_offset_s=0.0, subtitles="burn"
        )
        set_job_settings(project, JobSettings(**settings))
        save_project(project, tmp_path / f"{name}_recitation.qalun.json")

    rendered("same", preset="social", subtitles="burn")
    rendered("resized", preset="high", subtitles="burn")
    rendered("resubbed", preset="social", subtitles="sidecar")
    old = Project(audio=tmp_path / "old.mp3", cards=[_card(1, 1, 7)])
    old.record_render(tmp_path / "old.mp4", preset="social", basmala_offset_s=0.0)
    set_job_settings(old, JobSettings(subtitles="both"))
    save_project(old, tmp_path / "old_recitation.qalun.json")

    by_name = {entry.name: entry.status for entry in list_jobs([tmp_path])}
    assert by_name == {
        "same": RENDERED,
        "resized": CHANGED_SINCE_RENDER,
        "resubbed": CHANGED_SINCE_RENDER,
        "old": RENDERED,  # a render that did not record its subtitles is not second-guessed
    }


def test_a_cancelled_listing_stops_between_files(tmp_path, monkeypatch) -> None:
    """A folder on a slow drive must not hold up whoever cancelled the read."""
    import pytest

    from qurantext.jobs import catalog

    for name in ("a", "b", "c"):
        _save(tmp_path, name)
    cancel = CancelToken()
    opened: list[PathlibPath] = []
    real = catalog._entry_for

    def entry_then_cancel(path):
        opened.append(path)
        cancel.cancel()
        return real(path)

    monkeypatch.setattr(catalog, "_entry_for", entry_then_cancel)
    with pytest.raises(JobCancelled):
        list_jobs([tmp_path], cancel=cancel)
    assert len(opened) == 1


def test_a_cancelled_listing_does_not_start(tmp_path) -> None:
    import pytest

    cancel = CancelToken()
    cancel.cancel()
    with pytest.raises(JobCancelled):
        list_jobs([tmp_path], cancel=cancel)

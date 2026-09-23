"""The job list: every project the app has made, and what state it is in."""

from __future__ import annotations

import os

from qurantext.jobs.catalog import (
    CHANGED_SINCE_RENDER,
    DAMAGED,
    NEEDS_REVIEW,
    RENDERED,
    REVIEWED,
    ayah_range,
    list_jobs,
)
from qurantext.jobs.project import Project, save_project


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

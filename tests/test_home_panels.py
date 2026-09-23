"""The home window's panels: the job list (Task 3) and the new-job form (Task 4)."""

from __future__ import annotations

import os

import pytest
from PySide6.QtCore import QSettings, Qt

from qurantext.gui.home.job_list import JobListPanel
from qurantext.gui.i18n import t
from qurantext.gui.prefs import Prefs
from qurantext.jobs.catalog import DAMAGED
from qurantext.jobs.project import Project, save_project


@pytest.fixture()
def prefs(tmp_path):
    """A ``Prefs`` over a throwaway INI, scanning one tmp folder for jobs."""
    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    result = Prefs(settings)
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    result.job_dirs = [jobs_dir]
    return result


def _card(surah=25, a=7, b=8):
    return {"surah_num": surah, "from_ayah": a, "to_ayah": b, "start_time": 0.0, "end_time": 5.0}


def _save(jobs_dir, name, **changes):
    project = Project(audio=jobs_dir / f"{name}.m4a", mode="recitation", cards=[_card()])
    for key, value in changes.items():
        setattr(project, key, value)
    return save_project(project, jobs_dir / f"{name}_recitation.qalun.json")


def test_rows_appear_newest_first_with_status(qt_app, prefs) -> None:
    jobs_dir = prefs.job_dirs[0]

    older = _save(jobs_dir, "older")
    os.utime(older, (1_000_000, 1_000_000))

    reviewed_project = Project(audio=jobs_dir / "reviewed.m4a", mode="recitation", cards=[_card()])
    reviewed_project.mark_reviewed()
    save_project(reviewed_project, jobs_dir / "reviewed_recitation.qalun.json")

    panel = JobListPanel(prefs)

    assert panel.list.count() == 2
    names = [panel.list.itemWidget(panel.list.item(i)).name_label.text() for i in range(2)]
    assert names == ["reviewed", "older"]

    older_detail = panel.list.itemWidget(panel.list.item(1)).detail_label.text()
    assert t("home.status.needs_review") in older_detail
    assert t("home.mode.recitation") in older_detail
    assert "25:7" in older_detail

    reviewed_detail = panel.list.itemWidget(panel.list.item(0)).detail_label.text()
    assert t("home.status.reviewed") in reviewed_detail


def test_double_click_emits_open_requested(qt_app, prefs) -> None:
    jobs_dir = prefs.job_dirs[0]
    saved = _save(jobs_dir, "one")

    panel = JobListPanel(prefs)
    received = []
    panel.open_requested.connect(received.append)

    panel.list.itemActivated.emit(panel.list.item(0))

    assert received == [saved]


def test_remove_from_list_hides_and_persists(qt_app, prefs, tmp_path) -> None:
    jobs_dir = prefs.job_dirs[0]
    kept = _save(jobs_dir, "kept")
    removed = _save(jobs_dir, "removed")

    panel = JobListPanel(prefs)
    assert panel.list.count() == 2

    panel.remove_from_list(removed)

    assert panel.list.count() == 1
    remaining = panel.list.itemWidget(panel.list.item(0)).name_label.text()
    assert remaining == "kept"
    assert removed.exists(), "removing from the list never touches the file"

    # A fresh panel built on the same INI must not show it either.
    fresh_settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    fresh_prefs = Prefs(fresh_settings)
    fresh_panel = JobListPanel(fresh_prefs)
    fresh_names = [
        fresh_panel.list.itemWidget(fresh_panel.list.item(i)).name_label.text()
        for i in range(fresh_panel.list.count())
    ]
    assert fresh_names == ["kept"]
    assert kept.exists()


def test_set_running_adds_and_removes_transient_row(qt_app, prefs) -> None:
    panel = JobListPanel(prefs)
    assert panel.list.count() == 0

    panel.set_running("recitation.m4a", "Aligning… 40%")
    assert panel.list.count() == 1
    assert "recitation.m4a" in panel.list.item(0).text()
    assert "40%" in panel.list.item(0).text()

    panel.set_running("recitation.m4a", "Aligning… 80%")
    assert panel.list.count() == 1
    assert "80%" in panel.list.item(0).text()

    panel.set_running("recitation.m4a", None)
    assert panel.list.count() == 0


def test_damaged_file_is_listed_and_does_not_open(qt_app, prefs) -> None:
    jobs_dir = prefs.job_dirs[0]
    (jobs_dir / "broken.qalun.json").write_text("{not json", encoding="utf-8")

    panel = JobListPanel(prefs)
    received = []
    panel.open_requested.connect(received.append)

    assert panel.list.count() == 1
    entry = panel.list.item(0).data(Qt.ItemDataRole.UserRole)
    assert entry.status == DAMAGED

    panel.list.itemActivated.emit(panel.list.item(0))
    assert received == []

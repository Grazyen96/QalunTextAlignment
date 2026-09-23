"""The home window's panels: the job list (Task 3) and the new-job form (Task 4)."""

from __future__ import annotations

import os

import pytest
from PySide6.QtCore import QMimeData, QPointF, QSettings, Qt, QUrl
from PySide6.QtGui import QDropEvent

from qurantext.gui.home.job_list import JobListPanel
from qurantext.gui.home.new_job import NewJobPanel
from qurantext.gui.i18n import t
from qurantext.gui.jobs import JobSpec
from qurantext.gui.prefs import Prefs
from qurantext.jobs.catalog import DAMAGED
from qurantext.jobs.project import Project, save_project
from tests.media_helpers import QURAN_FILE


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


def test_double_clicking_a_damaged_row_emits_its_error(qt_app, prefs) -> None:
    jobs_dir = prefs.job_dirs[0]
    (jobs_dir / "broken.qalun.json").write_text("{not json", encoding="utf-8")

    panel = JobListPanel(prefs)
    errors = []
    panel.damaged_activated.connect(errors.append)

    panel.list.itemActivated.emit(panel.list.item(0))

    entry = panel.list.item(0).data(Qt.ItemDataRole.UserRole)
    assert errors == [entry.error] and entry.error


def test_refresh_keeps_the_running_row(qt_app, prefs) -> None:
    """A job saved elsewhere (a review's Save) refreshes the list mid-job; the row stays."""
    jobs_dir = prefs.job_dirs[0]
    _save(jobs_dir, "done")
    panel = JobListPanel(prefs)

    panel.set_running("recitation.m4a", "Aligning… 40%")
    panel.refresh()

    assert panel.list.count() == 2
    assert "40%" in panel.list.item(0).text()
    assert panel.list.item(0).data(Qt.ItemDataRole.UserRole) is None

    panel.set_running("recitation.m4a", "Aligning… 60%")
    assert panel.list.count() == 2 and "60%" in panel.list.item(0).text()

    panel.set_running("recitation.m4a", None)
    panel.refresh()
    assert panel.list.count() == 1


# -- NewJobPanel ----------------------------------------------------------------------


def _panel(prefs, store, quran_default=QURAN_FILE):
    return NewJobPanel(prefs, quran_default=quran_default, db_path=store)


def _select_surah(panel, surah_num):
    for i in range(panel.surah_box.count()):
        data = panel.surah_box.itemData(i)
        if data is not None and data["surah_num"] == surah_num:
            panel.surah_box.setCurrentIndex(i)
            return
    raise AssertionError(f"surah {surah_num} not in the picker")


def _drop(panel, path):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    event = QDropEvent(
        QPointF(0, 0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.dropEvent(event)
    return event


def test_toggling_mode_hides_the_range_and_persists(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    panel.show()
    assert panel.range_widget.isVisible()

    panel.lecture_button.setChecked(True)
    assert not panel.range_widget.isVisible()
    assert prefs.mode == "lecture"

    fresh = _panel(prefs, store)
    fresh.show()
    assert fresh.lecture_button.isChecked()
    assert not fresh.range_widget.isVisible()


def test_preset_combo_shows_readable_names_and_persists(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    names = [panel.preset_box.itemText(i) for i in range(panel.preset_box.count())]
    assert names == [
        t("preset.social"),
        t("preset.high"),
        t("preset.standard"),
        t("preset.fast"),
    ]

    panel.preset_box.setCurrentIndex(panel.preset_box.findData("high"))
    assert prefs.preset == "high"

    fresh = _panel(prefs, store)
    assert fresh.preset_box.currentData() == "high"


def test_more_options_open_and_closed_persists(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    panel.show()
    assert not panel.more_group.isVisible()

    panel.more_button.setChecked(True)
    assert panel.more_group.isVisible()
    assert prefs.more_options_open is True

    fresh = _panel(prefs, store)
    fresh.show()
    assert fresh.more_button.isChecked()
    assert fresh.more_group.isVisible()

    fresh.more_button.setChecked(False)
    assert not fresh.more_group.isVisible()
    assert prefs.more_options_open is False


def test_spec_reflects_every_control(qt_app, prefs, tmp_path, store) -> None:
    panel = _panel(prefs, store)
    audio = tmp_path / "a.mp3"
    audio.touch()
    panel.set_audio(audio)
    _select_surah(panel, 25)
    panel.from_spin.setValue(7)
    panel.to_spin.setValue(8)
    panel.preset_box.setCurrentIndex(panel.preset_box.findData("high"))

    panel.more_button.setChecked(True)
    panel.subtitle_buttons["sidecar"].setChecked(True)
    panel.format_boxes["srt"].setChecked(False)
    panel.format_boxes["vtt"].setChecked(True)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    panel.set_output_dir(out_dir)
    panel.render_right_away_box.setChecked(True)

    spec = panel.spec()
    assert spec.audio == audio
    assert spec.quran == QURAN_FILE
    assert spec.mode == "recitation"
    assert spec.surah_num == 25
    assert spec.from_ayah == 7
    assert spec.to_ayah == 8
    assert spec.preset == "high"
    assert spec.subtitles == "sidecar"
    assert spec.formats == ("vtt",)
    assert spec.render_right_away is True
    assert spec.output_dir == out_dir


def test_problem_gives_the_right_key_for_each_missing_input(qt_app, prefs, tmp_path, store) -> None:
    panel = _panel(prefs, store)
    assert panel.problem() == "job.need_audio"
    assert panel.problem_label.text() == t("job.need_audio")

    audio = tmp_path / "a.mp3"
    audio.touch()
    panel.set_audio(audio)
    # The picker defaults to its first surah once the store loads (as main_window's
    # does today), so reaching "no range chosen" needs an explicit empty selection.
    panel.surah_box.setCurrentIndex(-1)
    assert panel.problem() == "job.need_range"
    assert panel.problem_label.text() == t("job.need_range")

    _select_surah(panel, 25)
    panel.from_spin.setValue(8)
    # The spin boxes nudge each other so "to" can never fall below "from" through
    # ordinary use (see _range_changed); block the signal to hold an invalid pair
    # anyway, so validate()'s own defence against it is exercised end to end.
    panel.to_spin.blockSignals(True)
    panel.to_spin.setValue(7)
    panel.to_spin.blockSignals(False)
    assert panel.problem() == "job.bad_range"
    panel._refresh()  # the blocked signal skipped the label's own update
    assert panel.problem_label.text() == t("job.bad_range")

    panel.from_spin.setValue(7)
    panel.to_spin.setValue(8)
    assert panel.problem() is None
    assert panel.problem_label.text() == ""


def test_problem_reports_a_missing_quran_text(qt_app, prefs, tmp_path, store) -> None:
    panel = _panel(prefs, store, quran_default=None)
    audio = tmp_path / "a.mp3"
    audio.touch()
    panel.set_audio(audio)

    assert panel.problem() == "job.need_quran"
    assert panel.problem_label.text() == t("job.need_quran")


def test_dropping_an_audio_file_sets_it(qt_app, prefs, tmp_path, store) -> None:
    panel = _panel(prefs, store)
    audio = tmp_path / "a.mp3"
    audio.touch()

    _drop(panel, audio)

    assert panel.spec().audio == audio


def test_dropping_a_non_audio_file_is_refused(qt_app, prefs, tmp_path, store) -> None:
    panel = _panel(prefs, store)
    bad = tmp_path / "notes.txt"
    bad.write_text("hello", encoding="utf-8")

    _drop(panel, bad)

    assert panel.problem() == "job.need_audio"


def test_start_requested_carries_the_spec(qt_app, prefs, tmp_path, store) -> None:
    panel = _panel(prefs, store)
    audio = tmp_path / "a.mp3"
    audio.touch()
    panel.set_audio(audio)
    _select_surah(panel, 25)
    assert panel.problem() is None

    received = []
    panel.start_requested.connect(received.append)
    panel.start_button.click()

    assert len(received) == 1
    assert isinstance(received[0], JobSpec)
    assert received[0].audio == audio
    assert received[0].surah_num == 25


def test_set_running_true_disables_inputs(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    panel.show()

    panel.set_running(True)

    assert not panel.choose_button.isEnabled()
    assert not panel.recitation_button.isEnabled()
    assert not panel.surah_box.isEnabled()
    assert not panel.preset_box.isEnabled()
    assert not panel.start_button.isVisible()
    assert panel.cancel_button.isVisible()
    assert panel.progress_bar.isVisible()

    received = []
    panel.cancel_requested.connect(lambda: received.append(True))
    panel.cancel_button.click()
    assert received == [True]

    panel.set_running(False)
    assert panel.choose_button.isEnabled()
    assert panel.start_button.isVisible()
    assert not panel.cancel_button.isVisible()
    assert not panel.progress_bar.isVisible()


def test_show_status_says_how_the_last_job_ended(qt_app, prefs, store) -> None:
    """``set_running(False)`` hides the running status; the ending is shown after it."""
    panel = _panel(prefs, store)
    panel.show()
    panel.set_running(True)
    panel.set_running(False)

    panel.show_status("Stopped.")
    assert panel.status_label.isVisible() and panel.status_label.text() == "Stopped."

    panel.show_status("")
    assert not panel.status_label.isVisible()


def test_a_quran_override_that_is_gone_falls_back_to_the_default(
    qt_app, prefs, store, tmp_path
) -> None:
    """The override wins only while its file exists; the choice itself is kept."""
    gone = tmp_path / "gone.txt"
    prefs.quran_override = gone

    panel = _panel(prefs, store)

    assert panel.spec().quran == QURAN_FILE
    assert panel.quran_label.text() == t("home.quran_override.default")
    assert prefs.quran_override == gone.resolve(), "an unmounted drive must not erase it"


def test_a_quran_override_that_exists_wins_over_the_default(qt_app, prefs, store, tmp_path) -> None:
    prefs.quran_override = QURAN_FILE

    panel = _panel(prefs, store, quran_default=tmp_path / "default.txt")

    assert panel.spec().quran == QURAN_FILE.resolve()
    assert panel.quran_label.text() == t(
        "home.quran_override.custom", path=str(QURAN_FILE.resolve())
    )

"""The home window's panels: the job list (Task 3) and the new-job form (Task 4)."""

from __future__ import annotations

import gc
import logging
import os
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")
from PySide6.QtCore import QMimeData, QPointF, QSettings, Qt, QUrl
from PySide6.QtGui import QDropEvent

from qurantext.gui.colors import warning_color
from qurantext.gui.home import job_list as job_list_module
from qurantext.gui.home.job_list import JobListPanel
from qurantext.gui.home.new_job import NewJobPanel
from qurantext.gui.i18n import path_text, t
from qurantext.gui.jobs import JobSpec
from qurantext.gui.prefs import Prefs
from qurantext.gui.review.background import join_lingering
from qurantext.jobs import catalog
from qurantext.jobs.catalog import DAMAGED
from qurantext.jobs.project import Project, save_project
from qurantext.utils.progress import CancelToken, JobCancelled
from tests.media_helpers import QURAN_FILE
from tests.qt_helpers import blocking_list_jobs, spin, wait_for, wait_until_listed


@pytest.fixture()
def prefs(tmp_path, no_default_job_dirs):
    """A ``Prefs`` over a throwaway INI, scanning one tmp folder for jobs (and nothing else)."""
    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    result = Prefs(settings)
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    result.job_dirs = [jobs_dir]
    return result


def _card(surah=25, a=7, b=8):
    return {"surah_num": surah, "from_ayah": a, "to_ayah": b, "start_time": 0.0, "end_time": 5.0}


def _listed(prefs):
    """A ``JobListPanel`` whose first read of the folders has landed."""
    panel = JobListPanel(prefs)
    wait_until_listed(panel)
    return panel


def _running_text(panel):
    """The transient running row's words (row 0), drawn by its row widget."""
    return panel.list.itemWidget(panel.list.item(0)).label.text()


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

    panel = _listed(prefs)

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

    panel = _listed(prefs)
    received = []
    panel.open_requested.connect(received.append)

    panel.list.itemActivated.emit(panel.list.item(0))

    assert received == [saved]


def test_remove_from_list_hides_and_persists(qt_app, prefs, tmp_path) -> None:
    jobs_dir = prefs.job_dirs[0]
    kept = _save(jobs_dir, "kept")
    removed = _save(jobs_dir, "removed")

    panel = _listed(prefs)
    assert panel.list.count() == 2

    panel.remove_from_list(removed)
    wait_until_listed(panel)

    assert panel.list.count() == 1
    remaining = panel.list.itemWidget(panel.list.item(0)).name_label.text()
    assert remaining == "kept"
    assert removed.exists(), "removing from the list never touches the file"

    # A fresh panel built on the same INI must not show it either.
    fresh_settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    fresh_prefs = Prefs(fresh_settings)
    fresh_panel = _listed(fresh_prefs)
    fresh_names = [
        fresh_panel.list.itemWidget(fresh_panel.list.item(i)).name_label.text()
        for i in range(fresh_panel.list.count())
    ]
    assert fresh_names == ["kept"]
    assert kept.exists()


def test_set_running_adds_and_removes_transient_row(qt_app, prefs) -> None:
    panel = _listed(prefs)
    assert panel.list.count() == 0

    panel.set_running("recitation.m4a", "Aligning… 40%")
    assert panel.list.count() == 1
    assert "recitation.m4a" in _running_text(panel)
    assert "40%" in _running_text(panel)

    panel.set_running("recitation.m4a", "Aligning… 80%")
    assert panel.list.count() == 1
    assert "80%" in _running_text(panel)

    panel.set_running("recitation.m4a", None)
    assert panel.list.count() == 0


def test_the_running_row_shows_how_far_the_job_is(qt_app, prefs) -> None:
    panel = _listed(prefs)

    panel.set_running("a.m4a", "Starting…")
    bar = panel.list.itemWidget(panel.list.item(0)).progress_bar
    assert (bar.minimum(), bar.maximum()) == (0, 0), "no fraction yet: a busy indicator"

    panel.set_running("a.m4a", "Matching — 40%", 0.4)
    bar = panel.list.itemWidget(panel.list.item(0)).progress_bar
    assert (bar.maximum(), bar.value()) == (100, 40)
    assert "40%" in _running_text(panel)

    panel.refresh()
    wait_until_listed(panel)
    bar = panel.list.itemWidget(panel.list.item(0)).progress_bar
    assert bar.value() == 40, "a refresh mid-job keeps the bar where it was"


def test_rows_name_their_folder_so_two_jobs_of_one_name_differ(qt_app, prefs, tmp_path) -> None:
    first = prefs.job_dirs[0]
    second = tmp_path / "other"
    second.mkdir()
    prefs.job_dirs = [first, second]
    _save(first, "same")
    _save(second, "same")

    panel = _listed(prefs)

    tips = sorted(panel.list.item(i).toolTip() for i in range(panel.list.count()))
    assert tips == sorted([str(first.resolve()), str(second.resolve())])
    row = panel.list.itemWidget(panel.list.item(0))
    assert row.toolTip() == panel.list.item(0).toolTip()


def test_damaged_file_is_listed_and_does_not_open(qt_app, prefs) -> None:
    jobs_dir = prefs.job_dirs[0]
    (jobs_dir / "broken.qalun.json").write_text("{not json", encoding="utf-8")

    panel = _listed(prefs)
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

    panel = _listed(prefs)
    errors = []
    panel.damaged_activated.connect(errors.append)

    panel.list.itemActivated.emit(panel.list.item(0))

    entry = panel.list.item(0).data(Qt.ItemDataRole.UserRole)
    assert errors == [entry.error] and entry.error


def test_a_row_that_needs_attention_is_amber_and_bold(qt_app, prefs) -> None:
    """Colour alone is not enough (and was never shown): the status is bold too."""
    jobs_dir = prefs.job_dirs[0]
    _save(jobs_dir, "pending")
    reviewed = Project(audio=jobs_dir / "calm.m4a", mode="recitation", cards=[_card()])
    reviewed.mark_reviewed()
    save_project(reviewed, jobs_dir / "calm_recitation.qalun.json")
    (jobs_dir / "broken.qalun.json").write_text("{not json", encoding="utf-8")

    panel = _listed(prefs)
    panel.resize(300, 400)
    panel.show()
    rows = {}
    for i in range(panel.list.count()):
        row = panel.list.itemWidget(panel.list.item(i))
        rows[row.name_label.text()] = row.detail_label

    pending = rows["pending"]
    assert pending.palette().color(pending.foregroundRole()) == warning_color(pending.palette())
    assert pending.font().bold()
    assert rows["broken"].font().bold()

    calm = rows["calm"]
    assert calm.palette().color(calm.foregroundRole()) != warning_color(calm.palette())
    assert not calm.font().bold()
    panel.close()


def _two_jobs(prefs):
    folder = prefs.job_dirs[0]
    for name in ("first", "second"):
        matches = folder / f"{name}_recitation.json"
        matches.write_text('{"matches": [], "meta": {"mode": "recitation"}}', encoding="utf-8")
        save_project(
            Project(audio=folder / f"{name}.mp3", cards=[_card()], matches=matches),
            folder / f"{name}_recitation.qalun.json",
        )


def test_the_action_buttons_wait_for_a_current_row(qt_app, prefs) -> None:
    _two_jobs(prefs)
    panel = _listed(prefs)
    for button in (panel.open_button, panel.reveal_button, panel.remove_button):
        assert not button.isEnabled()
    panel.list.setCurrentRow(0)
    for button in (panel.open_button, panel.reveal_button, panel.remove_button):
        assert button.isEnabled()


def test_the_open_button_opens_the_current_row(qt_app, prefs) -> None:
    _two_jobs(prefs)
    panel = _listed(prefs)
    opened = []
    panel.open_requested.connect(opened.append)
    panel.list.setCurrentRow(1)
    panel.open_button.click()
    assert opened == [panel.list.item(1).data(Qt.ItemDataRole.UserRole).project]


def test_the_remove_button_hides_the_current_row(qt_app, prefs) -> None:
    _two_jobs(prefs)
    panel = _listed(prefs)
    gone = panel.list.item(0).data(Qt.ItemDataRole.UserRole).project
    panel.list.setCurrentRow(0)
    panel.remove_button.click()
    wait_until_listed(panel)
    assert panel.list.count() == 1
    assert gone.resolve() in prefs.hidden_jobs
    # The next row takes the removed one's place, so the buttons stay on.
    assert panel.list.currentRow() == 0
    assert panel.remove_button.isEnabled()


def test_the_reveal_button_asks_to_show_the_current_row(qt_app, prefs) -> None:
    _two_jobs(prefs)
    panel = _listed(prefs)
    shown = []
    panel.reveal_requested.connect(shown.append)
    panel.list.setCurrentRow(0)
    panel.reveal_button.click()
    assert shown == [panel.list.item(0).data(Qt.ItemDataRole.UserRole).project]


def test_the_action_buttons_sit_under_the_list_and_are_named(qt_app, prefs) -> None:
    panel = _listed(prefs)
    layout = panel.layout()
    assert layout.indexOf(panel.actions_row) > layout.indexOf(panel.list)
    assert panel.open_button.text() == t("home.open")
    assert panel.reveal_button.text() == t("home.show_in_folder")
    assert panel.remove_button.text() == t("home.remove_from_list")


def test_a_row_built_on_a_dark_palette_gets_the_dark_amber(qt_app, prefs) -> None:
    from PySide6.QtGui import QColor, QPalette

    from qurantext.gui import colors

    _two_jobs(prefs)
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    dark.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
    before = qt_app.palette()
    qt_app.setPalette(dark)
    try:
        panel = _listed(prefs)
        row = panel.list.itemWidget(panel.list.item(0))
        shown = row.detail_label.palette().color(row.detail_label.foregroundRole())
        assert shown == colors.warning_color(dark)
        assert shown != colors.warning_color(before)
    finally:
        qt_app.setPalette(before)


def test_rows_on_screen_take_the_new_amber_when_the_theme_switches(qt_app, prefs) -> None:
    """A real Light to Dark switch, sheet and all: the listed amber row is recoloured."""
    from PySide6.QtGui import QColor

    from qurantext.gui import colors, theme

    _two_jobs(prefs)
    theme.apply_theme(qt_app, "light")
    panel = _listed(prefs)
    try:
        panel.show()
        row = panel.list.itemWidget(panel.list.item(0))
        label = row.detail_label
        light = theme.palette(theme.LIGHT)
        assert label.palette().color(label.foregroundRole()) == colors.warning_color(light)
        theme.apply_theme(qt_app, "dark")
        spin(0)
        dark = theme.palette(theme.DARK)
        assert label.palette().color(label.foregroundRole()) == colors.warning_color(dark)
        # A selected row takes the new theme's text on the highlight too.
        panel.list.setCurrentRow(0)
        theme.apply_theme(qt_app, "light")
        spin(0)
        on_highlight = QColor(theme.LIGHT.on_accent)
        for line in (row.name_label, row.detail_label):
            assert line.palette().color(line.foregroundRole()) == on_highlight
    finally:
        panel.close()


@pytest.mark.parametrize("language", ["en", "ar"])
def test_with_no_jobs_the_header_stays_at_the_top(qt_app, prefs, language) -> None:
    """The title and Refresh head their column; the spare height goes below, not above."""
    from qurantext.gui import theme
    from qurantext.gui.language import apply_language

    apply_language(qt_app, language)
    theme.apply_theme(qt_app, "light")
    panel = _listed(prefs)
    try:
        panel.resize(400, 680)
        panel.show()
        spin(0)
        assert panel.list.count() == 0
        assert panel.header.mapTo(panel, panel.header.rect().topLeft()).y() <= 40
        assert panel.header.height() == panel.header.sizeHint().height()
    finally:
        panel.stop_reading()
        panel.close()


def test_a_selected_row_draws_its_lines_in_the_highlighted_text(qt_app, prefs) -> None:
    from PySide6.QtGui import QPalette

    _two_jobs(prefs)
    panel = _listed(prefs)
    panel.show()
    row = panel.list.itemWidget(panel.list.item(0))
    on_highlight = row.palette().color(QPalette.ColorRole.HighlightedText)
    panel.list.setCurrentRow(0)
    for label in (row.name_label, row.detail_label):
        assert label.palette().color(label.foregroundRole()) == on_highlight
    assert row.detail_label.font().bold()  # the cue that is not a colour stays
    panel.list.setCurrentRow(1)
    shown = row.detail_label.palette().color(row.detail_label.foregroundRole())
    assert shown == warning_color(row.palette())
    panel.close()


def test_a_refresh_keeps_the_current_row_and_its_buttons(qt_app, prefs) -> None:
    _two_jobs(prefs)
    panel = _listed(prefs)
    panel.list.setCurrentRow(1)
    kept = panel.list.item(1).data(Qt.ItemDataRole.UserRole).project
    panel.refresh()
    wait_until_listed(panel)
    assert panel.list.currentItem().data(Qt.ItemDataRole.UserRole).project == kept
    for button in (panel.open_button, panel.reveal_button, panel.remove_button):
        assert button.isEnabled()


def test_refresh_keeps_the_running_row(qt_app, prefs) -> None:
    """A job saved elsewhere (a review's Save) refreshes the list mid-job; the row stays."""
    jobs_dir = prefs.job_dirs[0]
    _save(jobs_dir, "done")
    panel = _listed(prefs)

    panel.set_running("recitation.m4a", "Aligning… 40%")
    panel.refresh()
    wait_until_listed(panel)

    assert panel.list.count() == 2
    assert "40%" in _running_text(panel)
    assert panel.list.item(0).data(Qt.ItemDataRole.UserRole) is None

    panel.set_running("recitation.m4a", "Aligning… 60%")
    assert panel.list.count() == 2 and "60%" in _running_text(panel)

    panel.set_running("recitation.m4a", None)
    panel.refresh()
    wait_until_listed(panel)
    assert panel.list.count() == 1


# -- reading off the UI thread -----------------------------------------------------------


def test_refresh_reads_projects_off_the_ui_thread(qt_app, prefs, monkeypatch) -> None:
    seen = {}
    real = catalog.list_jobs

    def spy(*args, **kwargs):
        seen["thread"] = threading.get_ident()
        return real(*args, **kwargs)

    monkeypatch.setattr(job_list_module, "list_jobs", spy)
    panel = JobListPanel(prefs)
    assert wait_for(lambda: "thread" in seen)
    assert seen["thread"] != threading.get_ident()
    wait_until_listed(panel)


def test_refresh_returns_before_the_read_and_says_so_when_it_lands(
    qt_app, prefs, monkeypatch
) -> None:
    _save(prefs.job_dirs[0], "one")
    release, _calls = blocking_list_jobs(monkeypatch)

    panel = JobListPanel(prefs)  # would hang here if the read ran on this thread
    landed = []
    panel.refreshed.connect(lambda: landed.append(panel.list.count()))
    assert panel.reading and panel.list.count() == 0

    release.set()
    wait_until_listed(panel)
    assert landed == [1], "refreshed is emitted once, after the rows are rebuilt"


def test_the_first_read_does_not_claim_there_are_no_jobs(qt_app, prefs, monkeypatch) -> None:
    """Until the folders have been read, "your jobs appear here" would be a guess."""
    _save(prefs.job_dirs[0], "one")
    release, _calls = blocking_list_jobs(monkeypatch)

    panel = JobListPanel(prefs)
    assert panel.empty_label.text() == t("home.reading")
    assert panel.empty_label.text() != t("home.empty")

    release.set()
    wait_until_listed(panel)
    assert panel.list.count() == 1

    panel.remove_from_list(prefs.job_dirs[0] / "one_recitation.qalun.json")
    wait_until_listed(panel)
    assert panel.empty_label.text() == t("home.empty")
    assert not panel.empty_label.isHidden() and panel.list.isHidden()


def test_a_refresh_of_an_empty_list_says_it_is_reading(qt_app, prefs, monkeypatch) -> None:
    """Not only the first read: "your jobs appear here" is wrong while any read is out."""
    panel = _listed(prefs)
    assert panel.empty_label.text() == t("home.empty")
    release, _calls = blocking_list_jobs(monkeypatch)

    panel.refresh()
    assert panel.empty_label.text() == t("home.reading")

    release.set()
    wait_until_listed(panel)
    assert panel.empty_label.text() == t("home.empty")


def test_an_ended_job_keeps_its_row_until_the_read_that_lists_it_lands(
    qt_app, prefs, monkeypatch
) -> None:
    """Taking the row away at once left a gap, and after a first job an empty list
    claiming there were no jobs, for as long as the read took."""
    panel = _listed(prefs)
    release, _calls = blocking_list_jobs(monkeypatch)
    panel.set_running("one.m4a", "Aligning… 90%")
    _save(prefs.job_dirs[0], "one")  # what the job saved as it ended

    panel.end_running()
    panel.set_running("", None)  # the window clears the row as the job's thread ends
    assert panel.reading
    assert panel.list.count() == 1 and "90%" in _running_text(panel)
    assert panel.empty_label.isHidden()

    release.set()
    wait_until_listed(panel)
    assert panel.list.count() == 1
    assert panel.list.item(0).data(Qt.ItemDataRole.UserRole).name == "one"


def test_a_job_started_before_the_read_lands_keeps_its_own_row(qt_app, prefs, monkeypatch) -> None:
    panel = _listed(prefs)
    release, _calls = blocking_list_jobs(monkeypatch)
    panel.set_running("one.m4a", "Aligning… 90%")
    panel.end_running()
    panel.set_running("two.m4a", "Starting…")

    release.set()
    wait_until_listed(panel)
    assert panel.list.count() == 1 and "two.m4a" in _running_text(panel)


def test_remove_from_list_takes_the_row_away_at_once(qt_app, prefs, monkeypatch) -> None:
    jobs_dir = prefs.job_dirs[0]
    _save(jobs_dir, "one")
    _save(jobs_dir, "two")
    panel = _listed(prefs)
    release, _calls = blocking_list_jobs(monkeypatch)

    panel.remove_from_list(jobs_dir / "one_recitation.qalun.json")
    names = [panel.list.item(i).data(Qt.ItemDataRole.UserRole).name for i in range(1)]
    assert panel.list.count() == 1 and names == ["two"], "gone before the read lands"

    release.set()
    wait_until_listed(panel)
    assert panel.list.count() == 1


def test_a_cancelled_read_stops_instead_of_returning_an_empty_listing(prefs) -> None:
    """Stopping the panel cancels its read; it must stop, not report that nothing was found."""
    cancel = CancelToken()
    cancel.cancel()
    with pytest.raises(JobCancelled):
        job_list_module._read_jobs(1, list(prefs.job_dirs), frozenset(), cancel=cancel)


def test_stopping_a_slow_read_lets_its_thread_end_soon(qt_app, prefs, monkeypatch) -> None:
    """A folder on an unresponsive drive held the exit up for as long as the read took
    (up to the app's 30 s bound): the read ignored its cancel token."""
    jobs_dir = prefs.job_dirs[0]
    for index in range(100):
        (jobs_dir / f"{index}.qalun.json").write_text("{}", encoding="utf-8")
    opened = threading.Event()

    def slow(path, **kwargs):
        opened.set()
        time.sleep(0.1)  # 100 files: 10 s uncancelled
        return None

    monkeypatch.setattr(catalog, "_entry_for", slow)
    panel = JobListPanel(prefs)
    try:
        assert wait_for(opened.is_set)
        panel.stop_reading()
        started = time.monotonic()
        assert join_lingering(3000), "the read went on after it was cancelled"
        assert time.monotonic() - started < 3
    finally:
        assert join_lingering(15_000)


def test_a_failed_read_is_logged_and_leaves_the_rows(prefs, monkeypatch, caplog) -> None:
    def unreadable(*args, **kwargs):
        raise OSError("the network drive went away")

    monkeypatch.setattr(job_list_module, "list_jobs", unreadable)
    with caplog.at_level(logging.WARNING, logger=job_list_module.__name__):
        listing = job_list_module._read_jobs(7, [], frozenset())
    assert listing.generation == 7 and listing.entries is None
    assert "the network drive went away" in caplog.text


def test_a_read_that_fails_lands_as_itself_not_as_the_newest(
    qt_app, prefs, monkeypatch, caplog
) -> None:
    """An older read failing while a newer one is out must not end the wait for the newer."""
    panel = _listed(prefs)
    gates: dict[int, threading.Event] = {}
    real = job_list_module._read_jobs

    def reads(generation, extra, hidden, **kwargs):
        assert gates.setdefault(generation, threading.Event()).wait(10)
        if generation == older:
            raise OSError("the network drive went away")
        return real(generation, extra, hidden, **kwargs)

    monkeypatch.setattr(job_list_module, "_read_jobs", reads)
    landed = []
    panel.refreshed.connect(lambda: landed.append(panel._shown_generation))
    panel.refresh()
    older = panel._generation
    panel.refresh()
    newer = panel._generation
    gates.setdefault(older, threading.Event())
    gates.setdefault(newer, threading.Event())

    with caplog.at_level(logging.WARNING, logger=job_list_module.__name__):
        gates[older].set()
        assert wait_for(lambda: "the network drive went away" in caplog.text)
        spin(50)
        assert panel.reading and landed == [], "the newer read is still out"

    gates[newer].set()
    wait_until_listed(panel)
    assert landed == [newer]


def test_a_late_stale_read_never_overwrites_a_newer_one(qt_app, prefs, monkeypatch) -> None:
    jobs_dir = prefs.job_dirs[0]
    _save(jobs_dir, "one")
    panel = _listed(prefs)

    first_read_done = threading.Event()
    release_first = threading.Event()
    calls: list[int] = []
    real = catalog.list_jobs

    def reads(*args, **kwargs):
        calls.append(1)
        result = real(*args, **kwargs)
        if len(calls) == 1:  # the first refresh: sees only "one", then arrives late
            first_read_done.set()
            assert release_first.wait(10), "the test never released the first read"
        return result

    monkeypatch.setattr(job_list_module, "list_jobs", reads)
    landed = []
    panel.refreshed.connect(lambda: landed.append(panel.list.count()))

    panel.refresh()
    assert wait_for(first_read_done.is_set)
    _save(jobs_dir, "two")
    panel.refresh()
    wait_until_listed(panel)
    assert panel.list.count() == 2

    release_first.set()
    assert wait_for(lambda: panel._reads.active == 0)
    spin(100)  # let the stale result's queued call be delivered
    assert panel.list.count() == 2, "the first refresh's older rows were dropped"
    assert landed == [2]


def test_a_panel_dropped_while_it_reads_does_not_take_the_process_down(
    qt_app, prefs, monkeypatch
) -> None:
    """Destroying a QThread that still runs aborts; the running read is parked instead."""
    release, calls = blocking_list_jobs(monkeypatch)
    panel = JobListPanel(prefs)
    assert wait_for(lambda: calls)
    del panel
    gc.collect()
    release.set()
    assert join_lingering(10_000)


def test_closing_the_home_window_while_it_reads_does_not_crash(qt_app, prefs, monkeypatch) -> None:
    from qurantext.gui.main_window import MainWindow

    release, calls = blocking_list_jobs(monkeypatch)
    window = MainWindow(prefs=prefs)
    window.show()
    assert wait_for(lambda: calls)
    assert window.job_list.reading

    assert window.close()
    release.set()
    assert join_lingering(10_000)
    window.deleteLater()
    spin(50)


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


def test_the_form_reads_top_down_with_choose_inside_the_drop_zone(qt_app, prefs, store) -> None:
    from PySide6.QtWidgets import QHBoxLayout

    from qurantext.gui import theme

    panel = _panel(prefs, store)
    panel.resize(700, 640)
    panel.show()

    assert panel.heading_label.text() == "New job"
    assert panel.drop_zone.height() == panel.drop_zone.maximumHeight() == 96
    assert panel.choose_button.parentWidget() is panel.drop_zone
    assert panel.choose_button.text() == t("home.choose")

    # The reason Start is disabled sits beside Start, not at the far end of the form.
    row = panel.start_button.parentWidget().layout()
    buttons_row = next(
        item.layout()
        for item in (row.itemAt(i) for i in range(row.count()))
        if isinstance(item.layout(), QHBoxLayout) and item.layout().indexOf(panel.start_button) >= 0
    )
    assert buttons_row.indexOf(panel.problem_label) >= 0

    # The free space goes to the bottom, so the controls stay together at the top.
    last = row.itemAt(row.count() - 1)
    assert last.spacerItem() is not None

    margins = panel.range_widget.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (0, 0, 0, 0)

    # The chosen mode is shown by the app's sheet, not a sheet of the button's own.
    assert panel.recitation_button.styleSheet() == ""
    assert panel.recitation_button.property("segment") is True
    assert 'QPushButton[segment="true"]:checked' in theme.stylesheet(theme.LIGHT)
    panel.close()


def test_the_surah_picker_and_file_filters_read_from_the_string_table(
    qt_app, prefs, store, monkeypatch
) -> None:
    from qurantext.gui.home import new_job as module

    panel = _panel(prefs, store)
    first = panel.surah_box.itemData(0)
    assert panel.surah_box.itemText(0) == f"1. {first['name']}  (7 ayat)"

    filters: list = []

    def fake_open(parent, title, folder, filter_text):
        filters.append(filter_text)
        return "", ""

    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", fake_open)
    panel._choose_audio()
    panel._choose_quran_override()
    assert filters[0].startswith(t("home.filter.audio") + " (")
    assert filters[1].startswith(t("home.filter.text") + " (")
    assert all(f.endswith(t("home.filter.all") + " (*)") for f in filters)


def test_the_last_surah_and_range_come_back(qt_app, prefs, store, tmp_path) -> None:
    panel = _panel(prefs, store)
    _select_surah(panel, 25)
    panel.from_spin.setValue(7)
    panel.to_spin.setValue(11)

    fresh = _panel(Prefs(QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)), store)
    spec = fresh.spec()
    assert (spec.surah_num, spec.from_ayah, spec.to_ayah) == (25, 7, 11)


def test_a_remembered_range_is_clamped_to_the_surah(qt_app, prefs, store) -> None:
    prefs.surah_num, prefs.from_ayah, prefs.to_ayah = 1, 5, 99  # al-Fatiha has 7

    spec = _panel(prefs, store).spec()

    assert (spec.surah_num, spec.from_ayah, spec.to_ayah) == (1, 5, 7)


def test_an_arabic_file_name_does_not_turn_the_running_row_around(qt_app, prefs) -> None:
    """Isolated, an Arabic name cannot make the English line right to left."""
    panel = _listed(prefs)
    panel.set_running("تلاوة.m4a", "Starting…")
    assert _running_text(panel) == "\u2068تلاوة.m4a\u2069 — Starting…"


def test_a_long_audio_path_is_elided_to_one_line_with_the_full_path_as_tooltip(
    qt_app, prefs, store
) -> None:
    """The drop zone has a fixed height: a wrapped path would be clipped, not shown."""
    panel = _panel(prefs, store)
    # Twelve folders, not one name twelve times as long: no file system takes a 264-byte name.
    deep = Path("/tmp", *["very-long-folder-name"] * 12, "تلاوة.mp3")
    panel.set_audio(deep)
    label = panel.drop_label
    panel.resize(700, 600)
    panel.show()
    qt_app.processEvents()
    metrics = label.fontMetrics()
    for line in label.text().split("\n"):
        assert metrics.horizontalAdvance(line) <= label.width()
    assert label.toolTip() == path_text(deep), "the whole path, kept in its order"
    assert "…" in label.text()
    folder_line = label.text().split("\n")[1]
    assert folder_line.startswith("\u2066") and folder_line.endswith("\u2069"), "still isolated"


def _audio_mime(tmp_path):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "take.mp3"))])
    return mime


def test_the_drop_zone_lights_up_while_a_drag_is_over_it_and_not_after(
    qt_app, prefs, store, tmp_path
) -> None:
    from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent

    panel = _panel(prefs, store)
    mime = _audio_mime(tmp_path)  # the event does not own it: keep it alive
    enter = QDragEnterEvent(
        QPointF(10, 10).toPoint(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    qt_app.sendEvent(panel, enter)
    assert panel.drop_zone.property("dragOver") is True
    qt_app.sendEvent(panel, QDragLeaveEvent())
    assert panel.drop_zone.property("dragOver") is False


def test_a_drop_puts_the_zone_back_to_normal(qt_app, prefs, store, tmp_path) -> None:
    from PySide6.QtGui import QDragEnterEvent

    panel = _panel(prefs, store)
    mime = _audio_mime(tmp_path)
    qt_app.sendEvent(
        panel,
        QDragEnterEvent(
            QPointF(10, 10).toPoint(),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    qt_app.sendEvent(
        panel,
        QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert panel.audio_path == tmp_path / "take.mp3"
    assert panel.drop_zone.property("dragOver") is False


def test_the_progress_bar_leaves_the_words_to_the_status_line(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    assert not panel.progress_bar.isTextVisible()


def test_the_range_labels_name_their_spin_boxes(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    assert panel.range_from_label.buddy() is panel.from_spin
    assert panel.range_to_label.buddy() is panel.to_spin


def test_the_more_options_are_labelled_rows_that_hide_together(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    form = panel.more_form
    labels = {
        form.labelForField(panel.quran_row).text(): panel.quran_row,
        form.labelForField(panel.output_row).text(): panel.output_row,
        form.labelForField(panel.subtitles_row).text(): panel.subtitles_row,
        form.labelForField(panel.formats_widget).text(): panel.formats_widget,
    }
    assert set(labels) == {
        t("home.quran_text"),
        t("home.output_dir"),
        t("home.subtitles"),
        t("home.formats"),
    }
    panel.subtitle_buttons["burn"].setChecked(True)
    assert panel.formats_widget.isHidden()
    assert form.labelForField(panel.formats_widget).isHidden()
    panel.subtitle_buttons["both"].setChecked(True)
    assert not panel.formats_widget.isHidden()
    assert not form.labelForField(panel.formats_widget).isHidden()


def test_the_value_texts_no_longer_repeat_their_labels(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    assert panel.quran_label.text() == t("home.quran_override.default")
    assert ":" not in t("home.quran_override.default")
    assert ":" not in t("home.output_dir.default")


def test_the_two_forms_share_one_label_column(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    panel.more_button.setChecked(True)
    panel.resize(800, 700)
    panel.show()
    spin(50)
    upper = panel.surah_box.x()
    lower = panel.quran_row.x()
    assert abs(upper - lower) <= 2


def test_a_folded_whisperx_choice_without_a_token_is_still_said(
    qt_app, prefs, store, monkeypatch
) -> None:
    """More options is folded by default; the note must not fold away with it."""
    from qurantext.config.settings import env_dir, get_settings

    monkeypatch.setenv("REPLICATE_API_TOKEN", "")
    get_settings.cache_clear()
    try:
        prefs.engine = "whisperx"
        prefs.more_options_open = False
        panel = _panel(prefs, store)
        assert panel.more_group.isHidden()
        assert not panel.engine_hint_label.isHidden()
        hint = panel.engine_hint_label.text()
        assert hint.startswith(t("home.engine.folded"))
        assert t("home.engine.no_token", folder=path_text(env_dir())) in hint

        # Open, the note sits under the engine row instead, and only there.
        panel.more_button.setChecked(True)
        assert panel.engine_hint_label.isHidden()
        assert not panel.no_token_label.isHidden()
        panel.more_button.setChecked(False)
        assert not panel.engine_hint_label.isHidden()
    finally:
        get_settings.cache_clear()


def test_a_folded_whisperx_choice_says_the_recording_goes_online(
    qt_app, prefs, store, monkeypatch
) -> None:
    from qurantext.config.settings import get_settings

    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_test")
    get_settings.cache_clear()
    try:
        prefs.engine = "whisperx"
        prefs.more_options_open = False
        panel = _panel(prefs, store)
        assert not panel.engine_hint_label.isHidden()
        assert panel.engine_hint_label.text() == t("home.engine.folded")
    finally:
        get_settings.cache_clear()


def test_the_folded_hint_does_not_widen_the_panel(qt_app, prefs, store, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings

    from qurantext.config.settings import get_settings

    monkeypatch.setenv("REPLICATE_API_TOKEN", "")
    get_settings.cache_clear()
    try:
        local = Prefs(QSettings(str(tmp_path / "local.ini"), QSettings.Format.IniFormat))
        local.more_options_open = False
        baseline = _panel(local, store).minimumSizeHint().width()
        prefs.engine = "whisperx"
        prefs.more_options_open = False
        assert _panel(prefs, store).minimumSizeHint().width() <= baseline
    finally:
        get_settings.cache_clear()


def test_a_folded_local_choice_needs_no_hint(qt_app, prefs, store) -> None:
    prefs.more_options_open = False
    panel = _panel(prefs, store)
    assert panel.engine_hint_label.isHidden()
    panel.more_button.setChecked(True)
    panel.engine_buttons["whisperx"].setChecked(True)
    assert panel.engine_hint_label.isHidden(), "open, the engine row itself shows the choice"
    panel.engine_buttons["local"].setChecked(True)
    panel.more_button.setChecked(False)
    assert panel.engine_hint_label.isHidden()


@pytest.mark.parametrize("more_open", [False, True])
def test_a_malformed_setting_with_whisperx_remembered_still_opens(
    qt_app, prefs, store, monkeypatch, more_open
) -> None:
    """Reading the token reads every setting; one typo there must not stop the window."""
    from qurantext.config.settings import get_settings

    monkeypatch.setenv("QURANTEXT_VIDEO_FPS", "30fps")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError):
            get_settings()
        prefs.engine = "whisperx"
        prefs.more_options_open = more_open
        panel = _panel(prefs, store)
        assert panel.engine_buttons["whisperx"].isChecked()
        assert panel.no_token_label.isHidden(), "the token is unknown, not missing"
        panel.engine_buttons["local"].setChecked(True)
        panel.engine_buttons["whisperx"].setChecked(True)
        assert panel.spec().engine == "whisperx"
    finally:
        get_settings.cache_clear()


def test_a_malformed_setting_with_whisperx_remembered_still_opens_the_window(
    qt_app, prefs, monkeypatch
) -> None:
    from qurantext.config.settings import get_settings
    from qurantext.gui.main_window import MainWindow

    monkeypatch.setenv("QURANTEXT_VIDEO_FPS", "30fps")
    get_settings.cache_clear()
    try:
        prefs.engine = "whisperx"
        window = MainWindow(prefs=prefs)
        assert window.new_job.engine_buttons["whisperx"].isChecked()
        window.close()
        window.deleteLater()
        spin(50)
    finally:
        get_settings.cache_clear()


def test_the_engine_cannot_change_while_a_job_runs(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    panel.set_running(True)
    assert not any(button.isEnabled() for button in panel.engine_buttons.values())
    panel.set_running(False)
    assert all(button.isEnabled() for button in panel.engine_buttons.values())


# -- a lecture's studied surah ------------------------------------------------------


def test_a_lecture_offers_the_surah_picker_detecting_by_default(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    panel.show()
    panel.lecture_button.setChecked(True)
    box = panel.studied_surah_box
    assert box.isVisible() and not panel.surah_box.isVisible()
    assert not panel.range_widget.isVisible(), "a lecture states no ayat range"
    assert panel._form.labelForField(box).isVisible()
    assert box.count() == 115
    assert box.currentIndex() == 0 and box.currentText() == t("surah.detect")
    assert box.itemText(box.findData(25)).startswith("25. "), "named from the store"
    assert box.itemText(box.findData(25)) != t("surah.number", num=25)
    assert panel.spec().studied_surah is None

    panel.recitation_button.setChecked(True)
    assert not box.isVisible() and panel.surah_box.isVisible()


def test_the_lecture_surah_is_remembered_apart_from_the_recitations(
    qt_app, prefs, store, tmp_path
) -> None:
    panel = _panel(prefs, store)
    _select_surah(panel, 2)
    panel.lecture_button.setChecked(True)
    panel.studied_surah_box.setCurrentIndex(panel.studied_surah_box.findData(25))
    assert prefs.lecture_surah == 25 and prefs.surah_num == 2

    fresh = _panel(Prefs(QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)), store)
    assert fresh.studied_surah_box.currentData() == 25
    assert fresh.spec().studied_surah == 25
    assert fresh.surah_box.currentData()["surah_num"] == 2

    fresh.studied_surah_box.setCurrentIndex(0)
    assert prefs.lecture_surah is None


def test_a_recitation_spec_carries_no_studied_surah(qt_app, prefs, store) -> None:
    prefs.lecture_surah = 25
    panel = _panel(prefs, store)
    panel.recitation_button.setChecked(True)
    assert panel.spec().studied_surah is None
    assert panel.spec().settings.studied_surah is None


def test_a_lecture_spec_carries_the_default_episode(
    qt_app, prefs, store, tmp_path, monkeypatch
) -> None:
    """A new lecture starts with the remembered intro and outro; a recitation ignores them."""
    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    intro = tmp_path / "intro.mp4"
    intro.write_bytes(b"intro")
    prefs.save_default_episode(intro, None)
    stored, _ = prefs.default_episode

    panel = _panel(prefs, store)
    panel.lecture_button.setChecked(True)
    assert panel.spec().episode_defaults == (str(stored), None)
    panel.recitation_button.setChecked(True)
    assert panel.spec().episode_defaults == (None, None)


def test_a_lecture_spec_carries_the_default_generated_parts(
    qt_app, prefs, store, tmp_path, monkeypatch
) -> None:
    """A part whose default is generated reaches the job as its settings, not as a clip."""
    from qurantext.jobs.episode_assets import GeneratedOutro

    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    outro = GeneratedOutro(link="example.org", platform="instagram")
    prefs.save_default_episode(None, None, outro_generated=outro)

    panel = _panel(prefs, store)
    panel.lecture_button.setChecked(True)
    assert panel.spec().episode_generated == (None, outro)
    assert panel.spec().episode_defaults == (None, None)
    panel.recitation_button.setChecked(True)
    assert panel.spec().episode_generated == (None, None)


def test_the_footer_offers_the_theme_and_applies_it(qt_app, prefs, no_default_job_dirs) -> None:
    from PySide6.QtGui import QPalette

    from qurantext.gui import theme
    from qurantext.gui.main_window import MainWindow

    theme.apply_theme(qt_app, "light")
    window = MainWindow(prefs=prefs)
    try:
        codes = [window.theme_combo.itemData(i) for i in range(window.theme_combo.count())]
        assert codes == ["system", "light", "dark"]
        assert window.theme_combo.currentData() == "system"
        window.theme_combo.setCurrentIndex(codes.index("dark"))
        window.theme_combo.activated.emit(codes.index("dark"))
        assert prefs.theme == "dark"
        assert qt_app.palette().color(QPalette.ColorRole.Window).name().upper() == theme.DARK.window
        assert window.palette().color(QPalette.ColorRole.Window).name().upper() == theme.DARK.window
        # A language switch rebuilds the footer; the choice survives it.
        assert window.set_language("ar")
        assert window.theme_combo.currentData() == "dark"
    finally:
        window.set_language("en")
        window.job_list.stop_reading()
        window.close()
        window.deleteLater()


def test_a_theme_switch_retints_an_open_review_window(qt_app, prefs, tmp_path) -> None:
    """Review Focus 1: the strip, the rows and every icon follow the switch."""
    from PySide6.QtGui import QPalette

    from qurantext.gui import theme
    from qurantext.gui.review.player import FakePlayer
    from qurantext.gui.review.window import ReviewWindow

    theme.apply_theme(qt_app, "light")
    cards = [
        {
            "surah_num": 25,
            "from_ayah": 7,
            "to_ayah": 7,
            "full_text": "a b",
            "confidence": 1.0,
            "start_time": 0.0,
            "end_time": 10.0,
            "word_timings": [
                {"word": "a", "start": 1.0, "end": 2.0},
                {"word": "b", "start": 2.0, "end": 3.0},
            ],
        }
    ]
    project = Project(audio=tmp_path / "missing.mp3", cards=cards)
    review = ReviewWindow(project, player=FakePlayer(duration=10.0), prefs=prefs)
    try:
        review.show()
        before = review.save_button.icon().cacheKey()
        theme.apply_theme(qt_app, "dark")
        assert review.save_button.icon().cacheKey() != before
        assert (
            review.strip.palette().color(QPalette.ColorRole.Window).name().upper()
            == theme.DARK.window
        )
    finally:
        review.close()
        review.deleteLater()


def test_the_home_panels_wear_the_presentation_layer(
    qt_app, prefs, store, no_default_job_dirs
) -> None:
    from PySide6.QtWidgets import QFrame

    from qurantext.gui import theme
    from qurantext.gui.home.job_list import JobListPanel
    from qurantext.gui.widgets import Card, SectionHeader

    theme.apply_theme(qt_app, "light")
    jobs = JobListPanel(prefs)
    panel = _panel(prefs, store)
    try:
        assert isinstance(jobs.header, SectionHeader) and jobs.title_label is jobs.header.label
        assert jobs.title_label.font().pointSizeF() == theme.font("section").pointSizeF()
        for button, name in (
            (jobs.refresh_button, "refresh-cw"),
            (jobs.open_button, "folder-open"),
            (jobs.reveal_button, "folder"),
            (jobs.remove_button, "x"),
        ):
            assert button.property("qalun.icon")[0] == name, name
        assert (
            isinstance(panel.heading, SectionHeader) and panel.heading_label is panel.heading.label
        )
        assert isinstance(panel.drop_zone, Card) and isinstance(panel.drop_zone, QFrame)
        assert panel.drop_zone.objectName() == "dropZone"
        assert panel.choose_button.property("qalun.icon")[0] == "folder-open"
        assert not panel.choose_button.isFlat()
        assert panel.recitation_button.property("qalun.icon")[0] == "mic"
        assert panel.lecture_button.property("qalun.icon")[0] == "book-open"
        assert panel.start_button.property("primary") is True
        assert panel.more_button.property("qalun.icon")[0] == "chevron-right"
        panel.more_button.setChecked(True)
        assert panel.more_button.property("qalun.icon")[0] == "chevron-down"
        assert panel.recitation_button.styleSheet() == "" and panel.drop_zone.styleSheet() == ""
    finally:
        jobs.stop_reading()
        jobs.deleteLater()
        panel.deleteLater()


def test_the_chosen_mode_is_filled_and_its_icon_reads_on_the_fill(qt_app, prefs, store) -> None:
    """The mode toggle is a segment: checked, its icon's On pixmap is drawn in on_accent."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon

    from qurantext.gui import theme

    theme.apply_theme(qt_app, "light")
    panel = _panel(prefs, store)
    try:
        panel.lecture_button.setChecked(True)
        for button in (panel.recitation_button, panel.lecture_button):
            assert button.property("segment") is True
        assert panel.more_button.property("segment") is None  # a disclosure, never filled
        on = panel.lecture_button.icon().pixmap(QSize(16, 16), QIcon.Mode.Normal, QIcon.State.On)
        image = on.toImage()
        colours = {
            image.pixelColor(x, y).name().upper()
            for x in range(image.width())
            for y in range(image.height())
            if image.pixelColor(x, y).alpha() > 200
        }
        assert theme.LIGHT.on_accent.upper() in colours
        sheet = qt_app.styleSheet()
        assert 'QPushButton[segment="true"]:checked' in sheet
        assert "QPushButton:checked" not in sheet and "QToolButton:checked" not in sheet
    finally:
        panel.deleteLater()


def test_a_disabled_start_still_shows_its_text(qt_app, prefs, store) -> None:
    """Review Focus 5: Start before a file is chosen is disabled, primary, and readable.

    Measured from what the sheet draws it with (its disabled-primary rule),
    not from the palette, which the sheet overrides.
    """
    from PySide6.QtGui import QColor

    from qurantext.gui import theme
    from tests.test_colors import contrast
    from tests.test_theme import _rule

    theme.apply_theme(qt_app, "light")
    panel = _panel(prefs, store)
    try:
        assert not panel.start_button.isEnabled()
        assert panel.start_button.property("primary") is True
        rule = _rule(qt_app.styleSheet(), 'QPushButton[primary="true"]:disabled')
        assert contrast(QColor(rule["color"]), QColor(rule["background"])) >= 4.5
    finally:
        panel.deleteLater()

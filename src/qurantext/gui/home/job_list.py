"""The home window's list of every job it knows about.

Each row is one project file: its name, what kind of job it is, how much of
the Quran it covers, and where it stands (needs review, reviewed, rendered,
changed since the last render, or damaged). "Remove from list" only hides a
job — see ``jobs/catalog.py`` — it never touches the file, so a mistaken
removal costs nothing to undo (re-add the folder, or edit the prefs file).

A row that cannot be read (``DAMAGED``) is still listed, with its error kept
on the row as a status tip; double-clicking it hands that error to whoever
shows it (``damaged_activated``) instead of trying to open a project that
failed to load.

The folders are read on a worker thread (:meth:`JobListPanel.refresh`): a
folder of hundreds of projects, or one on a slow network drive, would
otherwise freeze the whole window while every file is opened and parsed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySide6.QtCore import QEvent, QItemSelectionModel, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qurantext.gui.colors import warning_color
from qurantext.gui.i18n import t, tn
from qurantext.gui.prefs import Prefs
from qurantext.gui.review.background import BackgroundJobs
from qurantext.jobs.catalog import (
    CHANGED_SINCE_RENDER,
    DAMAGED,
    NEEDS_REVIEW,
    RENDERED,
    REVIEWED,
    JobEntry,
    job_dirs_for,
    list_jobs,
)
from qurantext.utils.progress import CancelToken, JobCancelled

__all__ = ["JobListPanel"]

_log = logging.getLogger(__name__)

_STATUS_KEYS = {
    NEEDS_REVIEW: "home.status.needs_review",
    REVIEWED: "home.status.reviewed",
    RENDERED: "home.status.rendered",
    CHANGED_SINCE_RENDER: "home.status.changed_since_render",
    DAMAGED: "home.status.damaged",
}
_WARNING_STATUSES = frozenset({NEEDS_REVIEW, CHANGED_SINCE_RENDER})
#: Statuses that ask the person to do something, drawn bold: a cue that does
#: not depend on telling amber from the text colour.
_ATTENTION_STATUSES = frozenset({NEEDS_REVIEW, CHANGED_SINCE_RENDER, DAMAGED})


class JobListPanel(QWidget):
    """Every job under ``prefs.job_dirs`` (plus the default matching folders), newest first."""

    #: A row was opened (double-click or Enter); carries the project's Path.
    open_requested = Signal(object)
    #: "Show in folder" was chosen; carries the project's Path. The panel does
    #: not reveal it itself — ``MainWindow`` owns that call.
    reveal_requested = Signal(object)
    #: A damaged row was opened; carries its error, for ``MainWindow`` to show.
    damaged_activated = Signal(str)
    #: The rows were rebuilt from the latest read of the folders.
    refreshed = Signal()

    def __init__(self, prefs: Prefs, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._prefs = prefs
        #: The running job's row label, or None, and how far it is (None: not
        #: known). Kept apart from the row itself so :meth:`refresh` can put
        #: the row back after rebuilding the list.
        self._running_label: str | None = None
        self._running_fraction: float | None = None
        #: The transient "matching…" row set_running adds, or None.
        self._running_item: QListWidgetItem | None = None
        #: The running job has ended (:meth:`end_running`): its row goes when
        #: the read that lists the job in its place lands.
        self._running_ends_on_read = False
        #: Reads the folders off the UI thread (see :meth:`refresh`).
        self._reads = BackgroundJobs(self)
        #: Bumped by every refresh; a read that lands under an older number is
        #: dropped, so a slow early read can never overwrite a newer one.
        self._generation = 0
        #: The number of the read the rows show now; 0 until the first lands.
        self._shown_generation = 0
        #: Each read still out, by number: what hears of it failing (see ``_Read``).
        self._pending: dict[int, _Read] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        self.title_label = QLabel(t("home.jobs"))
        bold = self.title_label.font()
        bold.setBold(True)
        self.title_label.setFont(bold)
        header.addWidget(self.title_label)
        header.addStretch(1)
        self.refresh_button = QPushButton(t("home.refresh"))
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.itemActivated.connect(self._on_activated)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list)

        self.empty_label = QLabel()  # its words are set by _update_empty_state
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

        # The actions a row offers, where a person can see them: the context
        # menu and double-click stay, but nothing told anyone they were there,
        # and a keyboard user could reach neither.
        self.actions_row = QWidget()
        actions = QHBoxLayout(self.actions_row)
        actions.setContentsMargins(0, 0, 0, 0)
        self.open_button = QPushButton(t("home.open"))
        self.reveal_button = QPushButton(t("home.show_in_folder"))
        self.remove_button = QPushButton(t("home.remove_from_list"))
        for button in (self.open_button, self.reveal_button, self.remove_button):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addWidget(self.actions_row)
        self.open_button.clicked.connect(self._open_current)
        self.reveal_button.clicked.connect(self._reveal_current)
        self.remove_button.clicked.connect(self._remove_current)
        self.list.currentItemChanged.connect(lambda *_: self._update_actions())
        self.list.itemSelectionChanged.connect(self._show_selected_rows)
        self._update_actions()

        self.refresh()

    # -- filling ----------------------------------------------------------------

    def refresh(self) -> None:
        """Start reading the folders again; returns at once, the rows follow.

        The current rows stay up until the read lands (:meth:`_on_listed`),
        so a refresh does not blank the list. What to read is taken here, on
        the UI thread, where ``Prefs`` lives; only the file system is touched
        on the worker.
        """
        self._generation += 1
        read = self._pending[self._generation] = _Read(self, self._generation)
        self._reads.start(
            partial(
                _read_jobs, self._generation, list(self._prefs.job_dirs), self._prefs.hidden_jobs
            ),
            on_finished=self._on_listed,
            # _read_jobs catches what it can, so this is only a backstop; bound
            # methods all the same, so they run on the UI thread.
            on_failed=read.failed,
            on_done=read.done,
        )
        self._update_empty_state()

    @property
    def reading(self) -> bool:
        """Whether the latest refresh's read has yet to land in the rows."""
        return self._shown_generation != self._generation

    def stop_reading(self) -> None:
        """Let go of any read still running; for whoever is about to drop this panel.

        A read has nothing to lose by being cut short, so this does not wait
        for it: it is cancelled, which it notices between files, and its thread
        is parked until it ends (see ``review/background.py``).
        """
        self._reads.stop(wait_ms=0)

    def _on_listed(self, listing: _Listing) -> None:
        """Rebuild the rows from *listing*, keeping the running job's row on top.

        A refresh can come mid-job (a review saved, or Refresh pressed); the
        running job has no project file to be read back yet, so its row is put
        back rather than vanishing until the next progress update. A folder
        that could not be read leaves the rows as they were.
        """
        if listing.generation != self._generation:
            return  # a newer refresh is on its way; this one is already out of date
        self._shown_generation = listing.generation
        if self._running_ends_on_read:
            self._running_ends_on_read = False
            self._running_label = None
        if listing.entries is not None:
            # The buttons act on the current row: a rebuild must not take it
            # from under the person (a review saved, a job finished).
            kept = self._current_entry()
            kept_selected = kept is not None and self.list.currentItem().isSelected()
            self.list.clear()
            self._running_item = None
            for entry in listing.entries:
                self._add_entry(entry)
            if kept is not None:
                self._make_current(kept.project, select=kept_selected)
        self._show_running_row()
        self._update_actions()
        self.refreshed.emit()

    def _make_current(self, project: Path, *, select: bool) -> None:
        """Make *project*'s row current again (and selected if *select*), if it is still listed."""
        for index in range(self.list.count()):
            item = self.list.item(index)
            entry = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(entry, JobEntry) and entry.project == project:
                flag = (
                    QItemSelectionModel.SelectionFlag.ClearAndSelect
                    if select
                    else QItemSelectionModel.SelectionFlag.NoUpdate
                )
                self.list.setCurrentItem(item, flag)
                return

    def _on_list_failed(self, generation: int, message: str) -> None:
        """Read number *generation* raised: land it as a read that found nothing new."""
        _log.warning("Reading the job folders failed: %s", message)
        self._on_listed(_Listing(generation, None))

    def _on_read_done(self, generation: int) -> None:
        self._pending.pop(generation, None)

    def _add_entry(self, entry: JobEntry) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, entry)
        # Two jobs can share a name (the same recording matched into two
        # folders); the folder tells them apart.
        folder = str(entry.project.parent)
        item.setToolTip(folder)
        if entry.status == DAMAGED and entry.error:
            item.setStatusTip(entry.error)
        row = _JobRow(entry)
        row.setToolTip(folder)
        item.setSizeHint(row.sizeHint())
        self.list.addItem(item)
        self.list.setItemWidget(item, row)

    def set_running(self, name: str, text: str | None, fraction: float | None = None) -> None:
        """Show (*text* given) or clear (*text* is None) the transient top row.

        Used while a job is being matched, before it has a project file of its
        own to show up from disk, e.g. ``set_running("recitation.m4a", "Aligning… 40%", 0.4)``.
        The row's progress bar shows *fraction*, or a busy indicator while it is None.
        Clearing it after :meth:`end_running` leaves the row to that read.
        """
        if text is None and self._running_ends_on_read:
            return  # it goes when the read end_running started lands
        self._running_ends_on_read = False
        # A template, not a join: in Arabic the file name and the progress are
        # each isolated, so a Latin name does not turn the line left to right.
        self._running_label = (
            None if text is None else t("home.running_row", name=name, progress=text)
        )
        self._running_fraction = fraction
        self._show_running_row()

    def end_running(self) -> None:
        """The running job has ended: read the folders, and let its row go when that lands.

        What the job saved only shows up with the read, so taking the row away
        at once left a gap, and after a first job an empty list saying there
        were no jobs, for as long as the read took.
        """
        self._running_ends_on_read = self._running_label is not None
        self.refresh()

    def _show_running_row(self) -> None:
        """Make the top row match ``_running_label``: added, relabelled or removed."""
        if self._running_label is None:
            if self._running_item is not None:
                row = self.list.row(self._running_item)
                if row >= 0:
                    self.list.takeItem(row)
                self._running_item = None
        else:
            if self._running_item is None:
                # No display text of its own: the row widget draws the words
                # and the bar, and text under it would show through.
                self._running_item = QListWidgetItem()
                self._running_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.list.insertItem(0, self._running_item)
                row = _RunningRow()
                self.list.setItemWidget(self._running_item, row)
            row = self.list.itemWidget(self._running_item)
            row.show_state(self._running_label, self._running_fraction)
            self._running_item.setData(Qt.ItemDataRole.AccessibleTextRole, self._running_label)
            self._running_item.setSizeHint(row.sizeHint())
        self._update_empty_state()

    def _update_empty_state(self) -> None:
        # While a read is out, "your jobs appear here" would be a guess.
        self.empty_label.setText(t("home.reading") if self.reading else t("home.empty"))
        has_rows = self.list.count() > 0
        self.list.setVisible(has_rows)
        self.empty_label.setVisible(not has_rows)

    # -- actions ------------------------------------------------------------------

    def _on_activated(self, item: QListWidgetItem) -> None:
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(entry, JobEntry):
            return  # the transient running row carries no entry
        if entry.status == DAMAGED:
            self.damaged_activated.emit(entry.error or t("home.status.damaged"))
            return
        self.open_requested.emit(entry.project)

    def _current_entry(self) -> JobEntry | None:
        item = self.list.currentItem()
        entry = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return entry if isinstance(entry, JobEntry) else None

    def _show_selected_rows(self) -> None:
        """Tell each row whether it sits on the selection highlight, so it can read there."""
        for index in range(self.list.count()):
            item = self.list.item(index)
            row = self.list.itemWidget(item)
            if isinstance(row, _JobRow):
                row.set_selected(item.isSelected())

    def _update_actions(self) -> None:
        """Offer the buttons only for a job row: the running row has no file to act on."""
        has_job = self._current_entry() is not None
        for button in (self.open_button, self.reveal_button, self.remove_button):
            button.setEnabled(has_job)

    def _open_current(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self._on_activated(item)

    def _reveal_current(self) -> None:
        entry = self._current_entry()
        if entry is not None:
            self.reveal(entry.project)

    def _remove_current(self) -> None:
        entry = self._current_entry()
        if entry is not None:
            self.remove_from_list(entry.project)

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(entry, JobEntry):
            return
        menu = QMenu(self)
        reveal_action = menu.addAction(t("home.show_in_folder"))
        remove_action = menu.addAction(t("home.remove_from_list"))
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is reveal_action:
            self.reveal(entry.project)
        elif chosen is remove_action:
            self.remove_from_list(entry.project)

    def remove_from_list(self, path: Path) -> None:
        """Hide *path* (through ``Prefs``), take its row away now, and read the list again."""
        self._prefs.hide_job(path)
        spellings = {Path(path), Path(path).resolve()}
        for index in range(self.list.count()):
            item = self.list.item(index)
            entry = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(entry, JobEntry) and entry.project in spellings:
                was_current = item is self.list.currentItem()
                self.list.takeItem(index)
                if was_current and self.list.count() > 0:
                    # The next row (the previous one if it was last) takes its place,
                    # so the buttons, and the focus on them, stay where they were.
                    self.list.setCurrentRow(min(index, self.list.count() - 1))
                break
        self.refresh()

    def reveal(self, path: Path) -> None:
        self.reveal_requested.emit(path)


@dataclass(frozen=True, slots=True)
class _Listing:
    """One read of the folders: which refresh asked for it, and what it found.

    *entries* is None when the read failed, so the rows are left as they were.
    """

    generation: int
    entries: tuple[JobEntry, ...] | None


class _Read(QObject):
    """One read's end, heard on the UI thread by a receiver that knows which read it was.

    The worker's ``failed`` signal carries only a message; landing a failure
    under the newest number instead would end the wait for a newer read still
    out. Bound methods of a QObject child of the panel, so Qt queues them onto
    the UI thread and drops them if the panel is gone. It reaches the panel
    through ``parent()`` rather than holding it: a Python reference back would
    put the panel in a cycle, and a cycle is freed by the cyclic collector on
    whichever thread it happens to run.
    """

    def __init__(self, panel: JobListPanel, generation: int) -> None:
        super().__init__(panel)
        self._generation = generation

    def _panel(self) -> JobListPanel | None:
        panel = self.parent()
        return panel if isinstance(panel, JobListPanel) else None

    def failed(self, message: str) -> None:
        if (panel := self._panel()) is not None:
            panel._on_list_failed(self._generation, message)

    def done(self) -> None:
        if (panel := self._panel()) is not None:
            panel._on_read_done(self._generation)
        self.deleteLater()


def _read_jobs(
    generation: int,
    extra: list[Path],
    hidden: frozenset[Path],
    *,
    cancel: CancelToken | None = None,
    **_: object,
) -> _Listing:
    """Read every project under the job folders; runs on a worker thread, so no widgets.

    Takes (and ignores) the ``progress=`` every background job is called with:
    the read is short enough not to report. *cancel* (set by
    :meth:`JobListPanel.stop_reading`) stops it between files.
    """
    try:
        entries = list_jobs(job_dirs_for(extra), hidden=hidden, cancel=cancel)
    except JobCancelled:
        raise  # no one waits for this read any more; the worker reports it cancelled
    except Exception as error:  # noqa: BLE001 - a folder that cannot be read must not empty the list
        _log.warning("Could not read the job folders: %s", error, exc_info=True)
        return _Listing(generation, None)
    return _Listing(generation, tuple(entries))


class _JobRow(QWidget):
    """The two-line label shown for one job: bold name, then mode/scope/status."""

    def __init__(self, entry: JobEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        self.name_label = QLabel(entry.name)
        self.name_label.setAlignment(_leading_edge(self))
        bold_font = self.name_label.font()
        bold_font.setBold(True)
        self.name_label.setFont(bold_font)
        layout.addWidget(self.name_label)

        self.detail_label = QLabel(_detail_text(entry))
        self.detail_label.setAlignment(_leading_edge(self))
        if entry.status in _ATTENTION_STATUSES:
            attention_font = self.detail_label.font()
            attention_font.setBold(True)
            self.detail_label.setFont(attention_font)
        layout.addWidget(self.detail_label)

        self._warning = entry.status in _WARNING_STATUSES
        self._selected = False
        # Inside the list's viewport a label inherits its Base background and
        # so paints with Text, not WindowText; pin the role so the colour set
        # on it is the one drawn, wherever the row ends up.
        for label in (self.name_label, self.detail_label):
            label.setForegroundRole(QPalette.ColorRole.Text)
        self._paint_labels()

    def set_selected(self, selected: bool) -> None:
        """Whether the row sits on the selection highlight (see :meth:`_paint_labels`)."""
        if selected != self._selected:
            self._selected = selected
            self._paint_labels()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        # A theme switched while the app runs: the amber, or the highlighted
        # text, chosen for the old palette may not read on the new one. Setting
        # a label's palette sends PaletteChange to the label, not here.
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and (self._warning or self._selected):
            self._paint_labels()

    def _paint_labels(self) -> None:
        """Colour the two lines for the palette the row paints on, and its selection.

        The amber has no palette role of its own, so its shade is picked for
        the palette the row paints on: one amber was unreadable on a light
        list (see ``gui/colors.py``). On the selection highlight it fell to
        1.5:1, so a selected row draws both lines in HighlightedText; the bold
        status stays as the cue that does not depend on colour. Every other
        role is left to inherit, so it follows a theme switch by itself.
        """
        source = self.palette()
        if self._selected:
            palette = QPalette()
            for group in (
                QPalette.ColorGroup.Active,
                QPalette.ColorGroup.Inactive,
                QPalette.ColorGroup.Disabled,
            ):
                text = source.color(group, QPalette.ColorRole.HighlightedText)
                palette.setColor(group, QPalette.ColorRole.Text, text)
            self.name_label.setPalette(palette)
            self.detail_label.setPalette(palette)
            return
        self.name_label.setPalette(QPalette())
        detail = QPalette()
        if self._warning:
            detail.setColor(QPalette.ColorRole.Text, warning_color(source))
        self.detail_label.setPalette(detail)


class _RunningRow(QWidget):
    """The running job's row: what it is doing, over a thin progress bar (spec §3)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)
        self.label = QLabel()
        self.label.setAlignment(_leading_edge(self))
        layout.addWidget(self.label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        layout.addWidget(self.progress_bar)

    def show_state(self, text: str, fraction: float | None) -> None:
        self.label.setText(text)
        if fraction is None:
            self.progress_bar.setRange(0, 0)  # busy: a stage that does not say how far
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(int(max(0.0, min(1.0, fraction)) * 100))


def _leading_edge(widget: QWidget) -> Qt.AlignmentFlag:
    """The edge a row's lines start from: the layout's, not each line's own script.

    A plain QLabel aligns to its text's direction, so in Arabic a Latin job
    name would start at the left while its Arabic detail line starts at the
    right. AlignAbsolute pins both to the edge the list reads from.
    """
    rtl = widget.layoutDirection() == Qt.LayoutDirection.RightToLeft
    edge = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
    return edge | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter


def _detail_text(entry: JobEntry) -> str:
    if entry.status == DAMAGED:
        return t(_STATUS_KEYS[DAMAGED])
    mode_text = t("home.mode.recitation") if entry.mode == "recitation" else t("home.mode.lecture")
    scope = entry.ayah_range or tn("home.cards", entry.card_count)
    status_text = t(_STATUS_KEYS[entry.status])
    # One template, not a join: in Arabic each part is isolated, so a range
    # such as "25:7–11" keeps its order between the words around it.
    return t("home.row_detail", mode=mode_text, scope=scope, status=status_text)

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
otherwise freeze the whole window while every file is opened and parsed. The
same read makes each job's small picture (``jobs/thumbnails.py``). The folders
are watched, so a job that appears, goes or is renamed shows without Refresh.

With no job yet, the list gives way to :class:`EmptyState`: who the app is
for, and a card for each kind of job that asks the form for it
(``mode_requested``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySide6.QtCore import (
    QDateTime,
    QEvent,
    QFileSystemWatcher,
    QItemSelectionModel,
    QLocale,
    QObject,
    QPoint,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qurantext.config.paths import bundled_asset, user_cache_dir
from qurantext.gui import theme
from qurantext.gui.i18n import t, tn
from qurantext.gui.icons import icon, set_icon
from qurantext.gui.prefs import Prefs
from qurantext.gui.review.background import BackgroundJobs
from qurantext.gui.widgets import Card, SectionHeader, StatusChip
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

__all__ = ["EmptyState", "JobListPanel"]

_log = logging.getLogger(__name__)

_STATUS_KEYS = {
    NEEDS_REVIEW: "home.status.needs_review",
    REVIEWED: "home.status.reviewed",
    RENDERED: "home.status.rendered",
    CHANGED_SINCE_RENDER: "home.status.changed_since_render",
    DAMAGED: "home.status.damaged",
}
#: Each status's chip: its kind (the colour) and its icon (the cue that does
#: not depend on telling amber from the text colour).
_CHIP_FOR_STATUS = {
    NEEDS_REVIEW: ("attention", "circle-alert"),
    CHANGED_SINCE_RENDER: ("attention", "circle-alert"),
    RENDERED: ("accent", "film"),
    REVIEWED: ("neutral", "circle-check"),
    DAMAGED: ("attention", "triangle-alert"),
}
#: The side of a row's picture, in pixels.
_THUMB_PX = 48
#: How long the folders must stay quiet before a change to them is read.
_WATCH_DEBOUNCE_MS = 500


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
    #: A card of the empty state was chosen; carries "recitation" or "lecture",
    #: for the window to select in the form.
    mode_requested = Signal(str)

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

        self.refresh_button = QPushButton(t("home.refresh"))
        self.refresh_button.clicked.connect(self.refresh)
        set_icon(self.refresh_button, "refresh-cw", size=16)
        self.header = SectionHeader(t("home.jobs"), trailing=self.refresh_button)
        self.title_label = self.header.label
        layout.addWidget(self.header)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # A row takes the list's width and elides its name to it (see _JobRow),
        # so a long recording's name never pushes the date out of sight.
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemActivated.connect(self._on_activated)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list)

        self.empty_state = EmptyState()
        self.empty_label = self.empty_state.hint_label  # its words are set by _update_empty_state
        self.empty_state.mode_chosen.connect(self.mode_requested)
        layout.addWidget(self.empty_state, 1)

        # The actions a row offers, where a person can see them: the context
        # menu and double-click stay, but nothing told anyone they were there,
        # and a keyboard user could reach neither.
        self.actions_row = QWidget()
        actions = QHBoxLayout(self.actions_row)
        actions.setContentsMargins(0, 0, 0, 0)
        self.open_button = QPushButton(t("home.open"))
        self.reveal_button = QPushButton(t("home.show_in_folder"))
        self.remove_button = QPushButton(t("home.remove_from_list"))
        set_icon(self.open_button, "folder-open", size=16)
        set_icon(self.reveal_button, "folder", size=16)
        set_icon(self.remove_button, "x", size=16)
        for button in (self.open_button, self.reveal_button, self.remove_button):
            actions.addWidget(button)
        actions.addStretch(1)
        # Hidden under the empty state (see _update_empty_state), but its room is
        # kept: the column must not narrow, then widen again, as the first job lands.
        policy = self.actions_row.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.actions_row.setSizePolicy(policy)
        layout.addWidget(self.actions_row)
        self.open_button.clicked.connect(self._open_current)
        self.reveal_button.clicked.connect(self._reveal_current)
        self.remove_button.clicked.connect(self._remove_current)
        self.list.currentItemChanged.connect(lambda *_: self._update_actions())
        self.list.itemSelectionChanged.connect(self._show_selected_rows)
        self._update_actions()

        # The folders tell the list when a job appears, goes or is renamed; a
        # burst of files (a render writing several) is read once, half a second
        # after the last of them.
        self.watcher = QFileSystemWatcher(self)
        self._watch_timer = QTimer(self)
        self._watch_timer.setSingleShot(True)
        self._watch_timer.setInterval(_WATCH_DEBOUNCE_MS)
        self._watch_timer.timeout.connect(self.refresh)
        self.watcher.directoryChanged.connect(lambda _path: self._watch_timer.start())

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

    def _arm_watcher(self, folders: tuple[Path, ...]) -> None:
        """Watch *folders*, the job folders the worker's read found there.

        Taken from the read, not looked up here: a folder on a drive that hangs
        would otherwise hang the window. One on an unplugged drive is simply
        not in the read, so not watched.
        """
        wanted = [str(folder) for folder in folders]
        current = self.watcher.directories()
        gone = [path for path in current if path not in wanted]
        new = [path for path in wanted if path not in current]
        if gone:
            self.watcher.removePaths(gone)
        if new:
            self.watcher.addPaths(new)  # a path it cannot watch is returned, and left unwatched

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
        self._watch_timer.stop()
        # A change heard after this must not start the timer again on a panel being dropped.
        self.watcher.blockSignals(True)
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
        if listing.folders is not None:
            self._arm_watcher(listing.folders)
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
        self._on_listed(_Listing(generation, None, None))

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
        has_rows = self.list.count() > 0
        # While a read is out, the cards inviting a first job would be a guess.
        self.empty_state.set_reading(self.reading)
        self.list.setVisible(has_rows)
        self.empty_state.setVisible(not has_rows)
        # Three disabled buttons under the invitation would read as broken.
        self.actions_row.setVisible(has_rows)

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
    *folders* are the job folders the read found on disk, for the watcher;
    None when it failed, so the watcher is left as it was.
    """

    generation: int
    entries: tuple[JobEntry, ...] | None
    folders: tuple[Path, ...] | None = None


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
        dirs = job_dirs_for(extra)
        folders = tuple(folder for folder in dirs if folder.is_dir())
        entries = list_jobs(dirs, hidden=hidden, cancel=cancel, thumbnail_cache=user_cache_dir())
    except JobCancelled:
        raise  # no one waits for this read any more; the worker reports it cancelled
    except Exception as error:  # noqa: BLE001 - a folder that cannot be read must not empty the list
        _log.warning("Could not read the job folders: %s", error, exc_info=True)
        return _Listing(generation, None)
    return _Listing(generation, tuple(entries), folders)


#: What a row hears when the theme, or a bare palette, changes under it.
_PALETTE_EVENTS = (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange)


class _JobRow(QWidget):
    """One job as a card: its picture, its name, a status chip, the detail line and the date."""

    def __init__(self, entry: JobEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SP_8, theme.SP_8, theme.SP_8, theme.SP_8)
        row.setSpacing(theme.SP_12)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(_THUMB_PX, _THUMB_PX)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setPixmap(_thumbnail_pixmap(entry))
        row.addWidget(self.thumb_label, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(theme.SP_4)
        #: The whole name; the label shows it elided to its width (see _show_name).
        self._name = entry.name
        self.name_label = QLabel(entry.name)
        self.name_label.setAlignment(_leading_edge(self))
        self.name_label.setToolTip(entry.name)
        bold_font = self.name_label.font()
        bold_font.setBold(True)
        self.name_label.setFont(bold_font)
        # Asks for no width of its own: the row fits the list, the name fits the row.
        self.name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.name_label.setMinimumWidth(0)
        text.addWidget(self.name_label)
        kind, icon_name = _CHIP_FOR_STATUS.get(entry.status, ("neutral", None))
        self.chip = StatusChip(t(_STATUS_KEYS[entry.status]), icon_name=icon_name, kind=kind)
        chip_row = QHBoxLayout()
        chip_row.addWidget(self.chip)
        chip_row.addStretch(1)
        text.addLayout(chip_row)
        self.detail_label = QLabel(_detail_text(entry))
        self.detail_label.setAlignment(_leading_edge(self))
        self.detail_label.setFont(theme.font("secondary"))
        self.detail_label.setVisible(entry.status != DAMAGED)
        self.detail_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.detail_label.setMinimumWidth(0)
        text.addWidget(self.detail_label)
        row.addLayout(text, 1)

        self.date_label = QLabel(_date_text(entry.modified))
        self.date_label.setFont(theme.font("secondary"))
        row.addWidget(self.date_label, 0, Qt.AlignmentFlag.AlignTop)

        self._warning = kind == "attention"
        self._selected = False
        # Inside the list's viewport a label inherits its Base background and
        # so paints with Text, not WindowText; pin the role so the colour set
        # on it is the one drawn, wherever the row ends up. The date is
        # quieter: the secondary colour, which follows a theme switch by itself.
        for label in (self.name_label, self.detail_label, self.date_label):
            label.setForegroundRole(QPalette.ColorRole.Text)
            label.installEventFilter(self)
        self.date_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self._paint_labels()

    def _show_name(self) -> None:
        """The name elided in the middle to the label's width: its start and its end both tell."""
        width = self.name_label.contentsRect().width()
        if width <= 0:
            return
        metrics = self.name_label.fontMetrics()
        self.name_label.setText(metrics.elidedText(self._name, Qt.TextElideMode.ElideMiddle, width))

    def set_selected(self, selected: bool) -> None:
        """Whether the row sits on the selection highlight (see :meth:`_paint_labels`)."""
        if selected != self._selected:
            self._selected = selected
            self._paint_labels()

    def event(self, event: QEvent) -> bool:  # noqa: A003 - Qt override
        # A theme switched while the app runs: the amber, or the highlighted
        # text, chosen for the old palette may not read on the new one. Setting
        # a label's palette sends PaletteChange to the label, not here.
        handled = super().event(event)
        if event.type() in _PALETTE_EVENTS and (self._warning or self._selected):
            self._paint_labels()
        return handled

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        # The switch sets the palette, then the sheet; re-polishing a label for
        # the sheet puts back the palette it had before the switch (the old
        # amber), after the row has painted. So paint again once it has.
        if watched is self.name_label and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._show_name()
        if event.type() == QEvent.Type.StyleChange and (self._warning or self._selected):
            self._paint_labels()
        return False

    def _paint_labels(self) -> None:
        """Colour the lines for the palette the row paints on, and its selection.

        A selected row draws its name, detail and date in HighlightedText; the
        chip keeps its own pill, on whose background its colour reads. The
        amber has no palette role of its own, so the chip picks its shade for
        the palette it paints on (see ``gui/colors.py``), and is asked to pick
        again here after a theme switch. Every other role is left to inherit,
        so it follows a theme switch by itself.
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
                palette.setColor(group, QPalette.ColorRole.PlaceholderText, text)
            for label in (self.name_label, self.detail_label, self.date_label):
                label.setPalette(palette)
        else:
            for label in (self.name_label, self.detail_label, self.date_label):
                label.setPalette(QPalette())
        if self._warning:
            self.chip.set_kind(self.chip.property("kind"))  # re-reads the amber


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


class EmptyState(QWidget):
    """What the list shows before there is a job: who this is for, and the two ways in."""

    #: A card was chosen; carries "recitation" or "lecture".
    mode_chosen = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(theme.SP_16, theme.SP_24, theme.SP_16, theme.SP_24)
        column.setSpacing(theme.SP_12)
        column.addStretch(1)
        self.icon_label = QLabel()
        pixmap = QPixmap(str(bundled_asset("icon/qalun-256.png")))
        self.icon_label.setPixmap(
            pixmap.scaled(
                96,
                96,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.icon_label)
        self.title_label = QLabel(t("home.empty.title"))
        self.title_label.setFont(theme.font("section"))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.title_label)
        self.hint_label = QLabel(t("home.empty.hint"))
        self.hint_label.setWordWrap(True)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.hint_label)
        self.recitation_card = _ModeCard(
            "mic", t("home.mode.recitation"), t("home.mode.recitation.desc")
        )
        self.lecture_card = _ModeCard(
            "book-open", t("home.mode.lecture"), t("home.mode.lecture.desc")
        )
        self.recitation_card.clicked.connect(lambda: self.mode_chosen.emit("recitation"))
        self.lecture_card.clicked.connect(lambda: self.mode_chosen.emit("lecture"))
        column.addWidget(self.recitation_card)
        column.addWidget(self.lecture_card)
        column.addStretch(2)

    def set_reading(self, reading: bool) -> None:
        """While the folders are read, say so and hold the cards back: the emptiness is a guess."""
        self.hint_label.setText(t("home.reading") if reading else t("home.empty.hint"))
        for widget in (self.icon_label, self.title_label, self.recitation_card, self.lecture_card):
            widget.setVisible(not reading)


class _ModeCard(Card):
    """A clickable card naming one kind of job; Enter or Space works too."""

    clicked = Signal()

    def __init__(
        self, icon_name: str, title: str, description: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(title)
        self.setAccessibleDescription(description)
        self.body.setContentsMargins(theme.SP_12, theme.SP_8, theme.SP_12, theme.SP_8)
        row = QHBoxLayout()
        self.icon_label = QLabel()
        self.icon_label.setPixmap(icon(icon_name, "accent").pixmap(QSize(20, 20)))
        row.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        self.title_label = QLabel(title)
        bold = self.title_label.font()
        bold.setBold(True)
        self.title_label.setFont(bold)
        self.description_label = QLabel(description)
        self.description_label.setWordWrap(True)
        self.description_label.setFont(theme.font("secondary"))
        text.addWidget(self.title_label)
        text.addWidget(self.description_label)
        row.addLayout(text, 1)
        self.body.addLayout(row)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        # On release, inside the card, as a button: a press dragged off it chooses nothing.
        inside = self.rect().contains(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and inside:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)

    def click(self) -> None:
        """Choose this card, as a press or a key would."""
        self.clicked.emit()


def _leading_edge(widget: QWidget) -> Qt.AlignmentFlag:
    """The edge a row's lines start from: the layout's, not each line's own script.

    A plain QLabel aligns to its text's direction, so in Arabic a Latin job
    name would start at the left while its Arabic detail line starts at the
    right. AlignAbsolute pins both to the edge the list reads from.
    """
    rtl = widget.layoutDirection() == Qt.LayoutDirection.RightToLeft
    edge = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
    return edge | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter


def _date_text(modified: float) -> str:
    """The day the job was last saved, as ``2026-10-13``; nothing when that is not known.

    A date only, in one unambiguous form with Latin digits: the window's
    locale is C (``gui/language.py``), whose short form is neither readable
    nor short, and a time would only crowd the name out of a narrow row.
    """
    if modified <= 0:
        return ""
    stamp = QDateTime.fromSecsSinceEpoch(int(modified))
    return QLocale.c().toString(stamp.date(), "yyyy-MM-dd")


def _thumbnail_pixmap(entry: JobEntry) -> QPixmap:
    """The cached picture filling the tile; else a tile in the look's colour with the mode's icon.

    The picture is the video's shape, portrait or landscape; it is scaled to
    cover the square and its centre kept, where the card's text sits.
    """
    if entry.thumbnail is not None:
        pixmap = QPixmap(str(entry.thumbnail))
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                _THUMB_PX,
                _THUMB_PX,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            return scaled.copy(
                (scaled.width() - _THUMB_PX) // 2,
                (scaled.height() - _THUMB_PX) // 2,
                _THUMB_PX,
                _THUMB_PX,
            )
    tokens = theme.current_tokens()
    tile = QPixmap(_THUMB_PX, _THUMB_PX)
    background = QColor(*entry.background) if entry.background else QColor(tokens.border)
    tile.fill(background)
    if entry.status == DAMAGED:
        name = "triangle-alert"
    else:
        name = "book-open" if entry.mode == "lecture" else "mic"
    # The glyph is chosen for the tile, not the theme: a light glyph on a dark
    # look, a dark one on a light look. Each theme has one of each: its text,
    # and the colour it draws on the accent.
    wants_light = background.lightness() < 128
    role = "text" if wants_light == (tokens.name == "dark") else "on_accent"
    glyph = icon(name, role).pixmap(QSize(24, 24))
    painter = QPainter(tile)
    painter.drawPixmap((_THUMB_PX - 24) // 2, (_THUMB_PX - 24) // 2, glyph)
    painter.end()
    return tile


def _detail_text(entry: JobEntry) -> str:
    """Mode and scope (the status is the chip's); nothing for a damaged job, whose file says neither."""
    if entry.status == DAMAGED:
        return ""
    mode_text = t("home.mode.recitation") if entry.mode == "recitation" else t("home.mode.lecture")
    scope = entry.ayah_range or tn("home.cards", entry.card_count)
    # One template, not a join: in Arabic each part is isolated, so a range
    # such as "25:7–11" keeps its order between the words around it.
    return t("home.detail", mode=mode_text, scope=scope)

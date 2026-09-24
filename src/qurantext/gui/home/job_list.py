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

from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPalette
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

__all__ = ["JobListPanel"]

#: A fixed amber, not a palette role: it must read as "needs attention" against
#: both a light and a dark window background, and it already does this job for
#: gaps and edited words in the review window (see ``review/waveform_view.py``
#: and ``review/word_strip.py``) — reusing it keeps the two windows consistent.
_WARNING_COLOR = QColor(239, 159, 39)

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
        #: Reads the folders off the UI thread (see :meth:`refresh`).
        self._reads = BackgroundJobs(self)
        #: Bumped by every refresh; a read that lands under an older number is
        #: dropped, so a slow early read can never overwrite a newer one.
        self._generation = 0
        #: The number of the read the rows show now; 0 until the first lands.
        self._shown_generation = 0

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
        self._reads.start(
            partial(
                _read_jobs, self._generation, list(self._prefs.job_dirs), self._prefs.hidden_jobs
            ),
            on_finished=self._on_listed,
            # _read_jobs catches everything, so this is only a backstop; a bound
            # method all the same, so it runs on the UI thread.
            on_failed=self._on_list_failed,
        )
        self._update_empty_state()

    @property
    def reading(self) -> bool:
        """Whether the latest refresh's read has yet to land in the rows."""
        return self._shown_generation != self._generation

    def stop_reading(self) -> None:
        """Let go of any read still running; for whoever is about to drop this panel.

        A read has nothing to lose by being cut short, so this does not wait
        for it: the thread is parked until it ends (see ``review/background.py``).
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
        if listing.entries is not None:
            self.list.clear()
            self._running_item = None
            for entry in listing.entries:
                self._add_entry(entry)
        self._show_running_row()
        self.refreshed.emit()

    def _on_list_failed(self, _message: str) -> None:
        self._on_listed(_Listing(self._generation, None))

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
        """
        # A template, not a join: in Arabic the file name and the progress are
        # each isolated, so a Latin name does not turn the line left to right.
        self._running_label = (
            None if text is None else t("home.running_row", name=name, progress=text)
        )
        self._running_fraction = fraction
        self._show_running_row()

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
        # Until the first read lands, "your jobs appear here" would be a guess.
        self.empty_label.setText(t("home.empty") if self._shown_generation else t("home.reading"))
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
        """Hide *path* (through ``Prefs``) and rebuild the list without it."""
        self._prefs.hide_job(path)
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


def _read_jobs(
    generation: int, extra: list[Path], hidden: frozenset[Path], **_: object
) -> _Listing:
    """Read every project under the job folders; runs on a worker thread, so no widgets.

    Takes (and ignores) the ``progress=``/``cancel=`` every background job is
    called with: the read is short enough not to report, and a cancelled one
    is dropped by generation rather than stopped.
    """
    try:
        entries = list_jobs(job_dirs_for(extra), hidden=hidden)
    except Exception:  # noqa: BLE001 - a folder that cannot be read must not empty the list
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
        if entry.status in _WARNING_STATUSES:
            # Inside the list's viewport a label inherits its Base background
            # and so paints with Text, not WindowText; pin the role so the
            # colour set on it is the one drawn, wherever the row ends up.
            self.detail_label.setForegroundRole(QPalette.ColorRole.Text)
            palette = self.detail_label.palette()
            palette.setColor(QPalette.ColorRole.Text, _WARNING_COLOR)
            self.detail_label.setPalette(palette)
        if entry.status in _ATTENTION_STATUSES:
            attention_font = self.detail_label.font()
            attention_font.setBold(True)
            self.detail_label.setFont(attention_font)
        layout.addWidget(self.detail_label)


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

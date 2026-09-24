"""The home window: every job on the left, a new one on the right.

What this replaces: installing Python, creating a virtual environment,
installing FFmpeg, opening a cloud account, writing a token into a dotfile,
knowing the path to a Quran text file, and choosing among a dozen subcommands
with their flags.

The two panels (``gui/home/``) only collect and show; this window runs the job
Start asks for, keeps the list in step with what is on disk, and owns the
review windows it opens — one per project.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from qurantext.config.paths import DEFAULT_QURAN_PATH, QURAN_INPUT_DIR
from qurantext.gui import i18n
from qurantext.gui.files import show_in_folder
from qurantext.gui.home.job_list import JobListPanel
from qurantext.gui.home.new_job import NewJobPanel
from qurantext.gui.i18n import t, tn
from qurantext.gui.jobs import JobOutcome, JobSpec, match_path_for, run_matching, run_render
from qurantext.gui.language import apply_language
from qurantext.gui.prefs import Prefs
from qurantext.gui.review import ReviewWindow
from qurantext.gui.review.background import BackgroundJobs
from qurantext.jobs.project import Project, load_project, project_path_for
from qurantext.utils.progress import CancelToken, ProgressCallback, ProgressEvent

__all__ = ["MainWindow"]

#: The job list's share of the window; the form takes the rest.
_JOB_LIST_WIDTH = 300
#: The window's size on first opening; a language switch keeps whatever it is now.
_WINDOW_SIZE = (1024, 680)


@dataclass(frozen=True, slots=True)
class _Finished:
    """What Start's job hands back: the project, and the render when one was asked for."""

    project: Project
    outcome: JobOutcome | None = None


def _match_then_render(
    spec: JobSpec,
    *,
    progress: ProgressCallback | None,
    cancel: CancelToken | None,
) -> _Finished:
    """Match, then render only when the job skips the review.

    Runs on the worker thread, so it touches no widget. A Cancel that lands
    between the two stages stops before the render starts.
    """
    project = run_matching(spec, progress=progress, cancel=cancel)
    if not spec.render_right_away:
        return _Finished(project)
    if cancel is not None:
        cancel.raise_if_cancelled("render")
    return _Finished(project, run_render(project, progress=progress, cancel=cancel))


class MainWindow(QMainWindow):
    """The job list beside the new-job form; one job runs at a time."""

    def __init__(self, prefs: Prefs | None = None) -> None:
        super().__init__()
        self._prefs = prefs if prefs is not None else Prefs()
        self.setWindowTitle(t("app.title"))

        self._cancel: CancelToken | None = None
        #: Runs the matching/render job off the UI thread.
        self._jobs = BackgroundJobs(self)
        #: Set once the window was closed while a job ran: the window is hidden,
        #: the job cancelled, and the app quits when the job's thread ends.
        self._closing = False
        #: The job running now, and how it ended (said once the form stops running).
        self._running_spec: JobSpec | None = None
        self._ending = ""
        #: One review window per open project, keyed by its file: reopening the
        #: same project raises what is already there instead of a second window.
        #: A window leaves this once it closes, so the next review reads the file afresh.
        self._reviews: dict[Path, ReviewWindow] = {}

        self.resize(*_WINDOW_SIZE)
        self._build()

    # -- construction ---------------------------------------------------------

    def _build(self) -> None:
        self.job_list = JobListPanel(self._prefs)
        self.job_list.open_requested.connect(self._open_review)
        self.job_list.reveal_requested.connect(self._reveal)
        self.job_list.damaged_activated.connect(self._show_damaged)

        self.new_job = NewJobPanel(self._prefs, quran_default=_default_quran_file())
        self.new_job.start_requested.connect(self._start)
        self.new_job.cancel_requested.connect(self._request_cancel)

        self._splitter = splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.job_list)
        splitter.addWidget(self.new_job)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # Built here, not once in __init__, so a language switch gets a fresh one in its words.
        self.language_combo = QComboBox()
        for code in i18n.LANGUAGES:
            self.language_combo.addItem(i18n.LANGUAGE_NAMES[code], code)
        self._select_language_in_combo(i18n.current_language())
        self.language_combo.activated.connect(self._language_chosen)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(QLabel(t("home.language")))
        footer.addWidget(self.language_combo)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(splitter, 1)
        layout.addLayout(footer)
        self.setCentralWidget(root)

        splitter.setSizes([_JOB_LIST_WIDTH, max(0, self.width() - _JOB_LIST_WIDTH)])

    # -- language ---------------------------------------------------------------

    def _language_chosen(self, index: int) -> None:
        self.set_language(self.language_combo.itemData(index))

    def _select_language_in_combo(self, code: str) -> None:
        self.language_combo.setCurrentIndex(self.language_combo.findData(code))

    def set_language(self, code: str) -> bool:
        """Switch the window's language; refuse while anything could lose its place.

        A review window holds unsaved corrections and a job its progress rows;
        rebuilding under them is where things would go missing, and switching a
        language is rare enough to ask for a quiet moment. Returns whether the
        window is now in *code*.
        """
        if code == i18n.current_language():
            # Picking the language the system already gave is still a choice to keep.
            self._prefs.language = code
            return True
        if self._reviews or self._cancel is not None:
            self._select_language_in_combo(i18n.current_language())
            self.new_job.show_status(t("home.language_busy"))
            return False
        audio = self.new_job.audio_path
        sizes = self._splitter.sizes()
        apply_language(QApplication.instance(), code)
        self._prefs.language = code
        self.setWindowTitle(t("app.title"))
        # setCentralWidget deletes the old panels (later); the new ones read the
        # rest of the form back from prefs, all but the audio, which is not kept there.
        self._build()
        self._splitter.setSizes(sizes)  # where the person left the divider
        if audio is not None:
            self.new_job.set_audio(audio)
        return True

    # -- running --------------------------------------------------------------

    def _start(self, spec: JobSpec) -> None:
        if self._cancel is not None:
            return  # one job at a time; the form is disabled while one runs
        problem = spec.validate()
        if problem is not None:
            self.new_job.show_status(t(problem))
            return
        open_review = self._review_of(project_path_for(match_path_for(spec)))
        if open_review is not None:
            # Re-matching replaces that project on disk, under whatever the
            # person has not saved in its review; saving then would overwrite
            # the new match with the old one. They finish there first.
            self.new_job.show_status(t("home.close_review_first"))
            _raise(open_review)
            return

        self._running_spec = spec
        self._ending = ""
        starting = t("home.progress.starting")
        self.new_job.set_running(True)
        self.new_job.set_progress(None, starting)
        self.job_list.set_running(Path(spec.audio).name, starting)

        # The job may be a closure; every callback is a bound method, so it
        # runs on this (the UI) thread rather than the worker's.
        self._cancel = self._jobs.start(
            partial(_match_then_render, spec),
            on_progress=self._on_progress,
            on_finished=self._on_finished,
            on_failed=self._on_failed,
            on_cancelled=self._on_cancelled,
            on_done=self._on_done,
        )

    def _request_cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.cancel()
            self.new_job.show_status(t("home.progress.stopping"))

    def _on_progress(self, event: ProgressEvent) -> None:
        if event.fraction is None:
            if event.message.strip():
                self.new_job.show_status(event.message.strip())
            return
        text = _progress_text(event)
        self.new_job.set_progress(event.fraction, text)
        if self._running_spec is not None:
            self.job_list.set_running(Path(self._running_spec.audio).name, text, event.fraction)

    def _on_finished(self, finished: _Finished) -> None:
        project = finished.project
        project_path = project.path or project_path_for(project.matches)
        # State, not UI: the list must show this job next launch, closed window or not.
        self._remember_output_dir()
        # Running a job again is asking for it: one removed from the list comes back.
        self._prefs.unhide_job(project_path)
        if self._closing:
            return  # no review, and no list, under a window that is going away
        self.job_list.set_running("", None)
        self.job_list.refresh()

        outcome = finished.outcome
        if outcome is not None and outcome.video is not None:
            # Rendered right away: the person chose to skip the review.
            self._ending = t("home.finished.rendered", path=str(outcome.video))
            return
        problem = self._show_review(project_path)
        self._ending = problem or tn("home.finished.matched", len(project.cards))

    def _on_failed(self, message: str) -> None:
        self._remember_matched_output()
        if self._closing:
            return  # the person closed the window; a dialog now would bring it back
        # The worker's message may be an OS or library detail in English; the
        # sentence around it is in the person's language.
        said = t("home.failed", details=message)
        self._ending = said
        self._list_a_half_done_job()
        QMessageBox.warning(self, t("home.failed.title"), said)

    def _on_cancelled(self) -> None:
        self._remember_matched_output()
        if self._closing:
            return
        self._ending = t("home.cancelled")
        self._list_a_half_done_job()

    def _remember_output_dir(self) -> None:
        """A job saved somewhere unusual must still be listed next time."""
        spec = self._running_spec
        if spec is not None and spec.output_dir:
            self._prefs.job_dirs = [*self._prefs.job_dirs, Path(spec.output_dir)]

    def _remember_matched_output(self) -> None:
        """A render right away that stopped may follow a matching that saved its project.

        State, not UI, so it runs even once the window has closed: the next
        launch must still list that project.
        """
        spec = self._running_spec
        if spec is not None and spec.render_right_away:
            self._remember_output_dir()

    def _list_a_half_done_job(self) -> None:
        """Show the project a stopped render right away's matching saved (see above)."""
        spec = self._running_spec
        if spec is None or not spec.render_right_away:
            return
        self.job_list.set_running("", None)
        self.job_list.refresh()

    def _on_done(self) -> None:
        if self._closing:
            # The job's thread has quit (or is about to): join it, then leave.
            self._cancel = None
            self._running_spec = None
            self._jobs.stop()
            QApplication.quit()
            return
        self._cancel = None
        self._running_spec = None
        self.job_list.set_running("", None)
        self.new_job.set_running(False)
        self.new_job.show_status(self._ending)

    # -- the job list -----------------------------------------------------------

    def _reveal(self, path: Path) -> None:
        show_in_folder(path)

    def _show_damaged(self, error: str) -> None:
        self.new_job.show_status(t("home.damaged", details=error))

    # -- review windows -------------------------------------------------------

    def _open_review(self, project_path: Path) -> None:
        """Open *project_path* for review, or say on the status line why it cannot be.

        The job being matched is refused here rather than in ``_show_review``,
        because ``_on_finished`` opens that same project through
        ``_show_review`` before ``_on_done`` clears ``_running_spec``.
        """
        if self._is_being_matched(project_path):
            # Its file is about to be replaced; a review opened now would show the old
            # match, and saving it would overwrite the new one.
            self.new_job.show_status(t("home.busy_matching"))
            return
        problem = self._show_review(project_path)
        if problem is not None:
            self.new_job.show_status(problem)

    def _is_being_matched(self, project_path: Path) -> bool:
        """Whether the running job will write *project_path*, however either is spelled."""
        spec = self._running_spec
        if spec is None:
            return False
        target = project_path_for(match_path_for(spec))
        return Path(target).resolve() == Path(project_path).resolve()

    def _show_review(self, project_path: Path) -> str | None:
        """Show the review window for *project_path*; return why not, or None.

        Reopening the same project raises the window already open on it rather
        than making a second one, so a correction is only ever made in one
        place at a time. A closed window is not kept: the next review loads the
        project from disk again, so it shows what was saved (never edits that
        were discarded) and anything that changed the file since.
        """
        project_path = Path(project_path)
        existing = self._review_of(project_path)
        if existing is not None:
            _raise(existing)
            return None
        try:
            project = load_project(project_path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            return t("home.review_failed", name=project_path.name, details=str(error))

        window = ReviewWindow(project)
        window.saved.connect(self._review_saved)
        window.closed.connect(partial(self._forget_review, project_path, window))
        window.show()
        # Keep a reference: a window without one is collected and vanishes.
        self._reviews[project_path] = window
        return None

    def _review_of(self, project_path: Path) -> ReviewWindow | None:
        """The review open on *project_path*, however either path was spelled."""
        target = Path(project_path).resolve()
        for path, window in self._reviews.items():
            if Path(path).resolve() == target:
                return window
        return None

    def _review_saved(self, path: Path) -> None:
        self.job_list.refresh()
        if self._cancel is None:  # while a job runs, the status line is its progress
            self.new_job.show_status(t("main.saved", path=path))

    def _forget_review(self, project_path: Path, window: ReviewWindow) -> None:
        """Let a closed review window go, unless another has taken its place."""
        if self._reviews.get(project_path) is window:
            del self._reviews[project_path]
        window.deleteLater()
        self.job_list.refresh()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        """Close every open review window first; a refusal keeps this window open too.

        A review window that refuses to close (the person cancelled its
        unsaved-changes prompt) must not lose that work to the main window
        closing around it. Once every review has agreed, a job still matching
        or rendering is cancelled and the window hides, but the close itself
        waits for the job: a model call can run for minutes without looking
        at its token, and quitting under it destroys a ``QThread`` that is
        still running, which aborts the process. ``_on_done`` quits the app
        once the thread has ended. This window has no unsaved state of its own
        worth keeping it open for.
        """
        for window in list(self._reviews.values()):
            if not window.close():
                event.ignore()
                return
        if self._cancel is not None:
            self._cancel.cancel()
            self._closing = True
            self.hide()
            event.ignore()
            return
        self._jobs.stop()
        super().closeEvent(event)


def _raise(window: QWidget) -> None:
    """Bring *window* to the front, shown and focused."""
    window.show()
    window.raise_()
    window.activateWindow()


def _progress_text(event: ProgressEvent) -> str:
    """``Matching — 40%, about 2m 05s left``: the stage, how far, and how long when known."""
    percent = int(max(0.0, min(1.0, event.fraction or 0.0)) * 100)
    rendering = event.stage == "render"
    if event.eta_seconds is not None and not event.done:
        eta = _minutes(event.eta_seconds)
        if rendering:
            return t("home.progress.rendering_eta", percent=percent, eta=eta)
        return t("home.progress.matching_eta", percent=percent, eta=eta)
    if rendering:
        return t("home.progress.rendering", percent=percent)
    return t("home.progress.matching", percent=percent)


def _minutes(seconds: float) -> str:
    if seconds < 60:
        return t("home.eta.seconds", seconds=int(seconds))
    return t("home.eta.minutes", minutes=int(seconds // 60), seconds=f"{int(seconds % 60):02d}")


def _default_quran_file() -> Path | None:
    """The bundled certified text, unless the user has dropped one in themselves.

    Shipping it means the app works on first launch with nothing to find, and
    that the ayah numbering matches what the rest of the data assumes.
    """
    if QURAN_INPUT_DIR.is_dir():
        candidates = sorted(QURAN_INPUT_DIR.glob("*.txt"))
        if candidates:
            return candidates[0]
    return DEFAULT_QURAN_PATH if DEFAULT_QURAN_PATH.is_file() else None

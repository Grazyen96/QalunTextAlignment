"""The Episode dialog: what plays around a lecture — an intro, a recitation, an outro.

Rendering a lecture with an episode also writes ``<stem> – episode.mp4``, the
parts joined in order around it. This dialog is where the person chooses them:

- the intro and outro are video clips, read (``probe_part``) as soon as they
  are chosen, so a file that is not a video is said here, not minutes into a
  render; the old clip stays chosen then;
- the recitation is one of the recitation jobs in the job list. Each says
  whether its current video can be used as it is, or will be rendered first;
  a damaged job cannot be chosen;
- the total length adds up what is known, and says "?" for a part whose
  length is not.

Nothing is changed until OK. Then the newly chosen clips are copied beside the
project (``import_episode_clip``), the choice becomes one undoable edit of the
session, and the intro and outro become the defaults new lectures start with.
A clip that cannot be copied is said in the dialog, which stays open; a
default that cannot be kept is not a reason to lose the episode, and is said
by the window after it closes (:attr:`EpisodeDialog.default_error`).
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qurantext.core.video_common import get_audio_duration
from qurantext.gui.i18n import ltr, plain_title, t
from qurantext.gui.prefs import Prefs
from qurantext.gui.review.session import ReviewSession
from qurantext.jobs.catalog import (
    DAMAGED,
    RENDERED,
    JobEntry,
    ayah_range,
    job_dirs_for,
    job_status,
    list_jobs,
)
from qurantext.jobs.episode import EpisodeError, probe_part
from qurantext.jobs.episode_assets import EPISODE_SUFFIXES, EpisodeChoice, import_episode_clip
from qurantext.jobs.project import Project, load_project

__all__ = ["EpisodeDialog"]


def _resolved(path: Path | None) -> Path | None:
    return None if path is None else Path(path).expanduser().resolve()


def _length_text(seconds: float) -> str:
    """*seconds* as ``mm:ss``, rounded half up; a lecture's hour reads ``75:10``."""
    minutes, rest = divmod(max(0, math.floor(seconds + 0.5)), 60)
    return f"{minutes:02d}:{rest:02d}"


def _render_length(project: Project) -> float | None:
    """How long the project's recorded video is, when it has one ffprobe can read."""
    video = (project.render or {}).get("video")
    if not video:
        return None
    try:
        return probe_part(Path(video)).duration
    except EpisodeError:
        return None


def _audio_length(project: Project) -> float | None:
    try:
        seconds = float(get_audio_duration(Path(project.audio)))
    except (RuntimeError, OSError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


class _ClipRow:
    """One clip part (intro or outro): its label, Choose… and Remove, and its value."""

    def __init__(self, dialog: EpisodeDialog, part: str, current: Path | None) -> None:
        self.label = QLabel()
        self.choose = QPushButton(t("episode.choose"))
        self.remove = QPushButton(t("episode.remove"))
        self.path: Path | None = None
        self.length: float | None = None
        self._dialog = dialog
        self._part = part
        self.choose.clicked.connect(self._choose)
        self.remove.clicked.connect(lambda: self.set(None, None))
        if current is not None:
            try:
                length: float | None = probe_part(current).duration
            except EpisodeError:
                length = None  # gone or unreadable: said when the episode is rendered
            self.set(current, length)
        else:
            self.set(None, None)

    def layout(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(self.label, 1)
        row.addWidget(self.choose)
        row.addWidget(self.remove)
        return row

    def set(self, path: Path | None, length: float | None) -> None:
        self.path, self.length = path, length
        if path is None:
            self.label.setText(t("episode.none"))
            self.label.setToolTip("")
        else:
            shown = _length_text(length) if length is not None else t("episode.unknown")
            self.label.setText(t("episode.clip", name=path.name, length=ltr(shown)))
            self.label.setToolTip(str(path))
        self.remove.setEnabled(path is not None)
        self._dialog._update_total()

    def _choose(self) -> None:
        start = str(self.path.parent) if self.path is not None else ""
        patterns = " ".join(f"*{suffix}" for suffix in EPISODE_SUFFIXES)
        chosen, _ = QFileDialog.getOpenFileName(
            self._dialog,
            plain_title(t(f"episode.{self._part}")),
            start,
            f"{t('episode.clip_filter')} ({patterns})",
        )
        if not chosen:
            return
        path = Path(chosen)
        try:
            info = probe_part(path)
        except EpisodeError as error:
            self._dialog._show_message(t(error.key, **error.fmt))
            return
        self._dialog._show_message("")
        self.set(path, info.duration)


class EpisodeDialog(QDialog):
    """Choose a lecture's intro, recitation and outro; OK makes it one undoable edit."""

    def __init__(
        self,
        session: ReviewSession,
        *,
        prefs: Prefs,
        job_dirs: list[Path] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._prefs = prefs
        #: Why the choice could not be kept as the default for new lectures, after OK.
        self.default_error: str | None = None
        #: Each recitation's length once read, by project path (None: unknown).
        self._recitation_lengths: dict[Path, float | None] = {}
        self._building = True
        self.setWindowTitle(plain_title(t("episode.title")))

        current = session.episode
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.total_label = QLabel()
        self._intro = _ClipRow(self, "intro", current.intro)
        self.intro_label, self.intro_choose, self.intro_remove = (
            self._intro.label,
            self._intro.choose,
            self._intro.remove,
        )
        form.addRow(t("episode.intro"), self._intro.layout())

        self.recitation_box = QComboBox()
        self._fill_recitations(job_dirs, current.recitation)
        self.recitation_box.currentIndexChanged.connect(self._update_total)
        form.addRow(t("episode.recitation"), self.recitation_box)

        self._outro = _ClipRow(self, "outro", current.outro)
        self.outro_label, self.outro_choose, self.outro_remove = (
            self._outro.label,
            self._outro.choose,
            self._outro.remove,
        )
        form.addRow(t("episode.outro"), self._outro.layout())
        layout.addLayout(form)
        layout.addWidget(self.total_label)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setVisible(False)
        layout.addWidget(self.message_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setDefault(True)
        buttons.rejected.connect(self.reject)
        self.ok_button.clicked.connect(self._keep)
        layout.addWidget(buttons)

        self._building = False
        self._update_total()
        self.setMinimumWidth(480)

    # -- the recitation list -------------------------------------------------------

    def _fill_recitations(self, job_dirs: list[Path] | None, current: Path | None) -> None:
        box = self.recitation_box
        box.addItem(t("episode.none"), None)
        own = _resolved(self._session.project.path)
        dirs = job_dirs if job_dirs is not None else job_dirs_for(self._prefs.job_dirs)
        try:
            entries = list_jobs(dirs, hidden=self._prefs.hidden_jobs)
        except OSError:
            entries = []
        listed: set[Path] = set()
        for entry in entries:
            path = _resolved(entry.project)
            if entry.mode != "recitation" or path == own or path in listed:
                continue
            listed.add(path)
            box.addItem(_entry_text(entry), entry.project)
            if entry.status == DAMAGED:
                box.model().item(box.count() - 1).setEnabled(False)
        if current is not None and _resolved(current) not in listed:
            # Chosen earlier, and no longer in the list (removed from it, or its
            # folder is not scanned): kept, so OK does not drop it unasked.
            box.addItem(_entry_text(_entry_of(current)), current)
        index = 0
        for i in range(1, box.count()):
            if _resolved(box.itemData(i)) == _resolved(current):
                index = i
                break
        box.setCurrentIndex(index)

    def _recitation(self) -> Path | None:
        data = self.recitation_box.currentData()
        return Path(data) if data else None

    def _recitation_length(self, path: Path) -> float | None:
        key = _resolved(path)
        assert key is not None
        if key not in self._recitation_lengths:
            try:
                project = load_project(key)
            except (OSError, ValueError, KeyError, TypeError):
                self._recitation_lengths[key] = None
            else:
                self._recitation_lengths[key] = _render_length(project) or _audio_length(project)
        return self._recitation_lengths[key]

    def _lecture_length(self) -> float | None:
        project = self._session.project
        if project.render is not None and not project.render_is_stale:
            length = _render_length(project)
            if length is not None:
                return length
        if self._session.duration:
            return float(self._session.duration)
        return _audio_length(project)

    # -- the total ------------------------------------------------------------------

    def _update_total(self) -> None:
        if self._building:
            return
        lengths: list[float | None] = [self._lecture_length()]
        for row in (self._intro, self._outro):
            if row.path is not None:
                lengths.append(row.length)
        recitation = self._recitation()
        if recitation is not None:
            lengths.append(self._recitation_length(recitation))
        known = sum(length for length in lengths if length is not None)
        shown = _length_text(known)
        if any(length is None for length in lengths):
            shown = f"{shown} + {t('episode.unknown')}"
        self.total_label.setText(t("episode.total", length=ltr(shown)))

    # -- reading and keeping -----------------------------------------------------------

    def choice(self) -> EpisodeChoice:
        """The parts as chosen in the dialog now (a new clip still at its source)."""
        return EpisodeChoice(self._intro.path, self._recitation(), self._outro.path)

    def _show_message(self, text: str) -> None:
        self.message_label.setText(text)
        self.message_label.setVisible(bool(text))

    def _keep(self) -> None:
        """Copy new clips beside the project, set the episode, keep it as the default."""
        project_path = self._session.project.path
        if project_path is None:
            self._show_message(t("session.no_file"))
            return
        current = self._session.episode
        pending = self.choice()
        try:
            intro = _beside(project_path, pending.intro, current.intro)
            outro = _beside(project_path, pending.outro, current.outro)
        except (ValueError, OSError) as error:
            self._show_message(t("episode.copy_failed", reason=str(error)))
            return
        self._session.set_episode(EpisodeChoice(intro, pending.recitation, outro))
        try:
            # The sources, not the copies: the default is the last choice made.
            self._prefs.save_default_episode(pending.intro, pending.outro)
        except (ValueError, OSError) as error:
            self.default_error = t("episode.default_failed", reason=str(error))
        self.accept()


def _beside(project_path: Path, chosen: Path | None, current: Path | None) -> Path | None:
    """*chosen* as a clip beside the project: copied there unless it is already *current*."""
    if chosen is None:
        return None
    if current is not None and _resolved(chosen) == _resolved(current):
        return current
    return import_episode_clip(project_path, chosen)


def _entry_text(entry: JobEntry) -> str:
    """``fatiha · 1:1-7 · rendered``: which job, which ayat, and whether it renders first."""
    if entry.status == DAMAGED:
        status = t("episode.damaged")
    elif entry.status == RENDERED:
        status = t("episode.rendered")
    else:
        status = t("episode.render_first")
    if entry.ayah_range:
        return t("episode.recitation_entry", name=entry.name, range=entry.ayah_range, status=status)
    return t("episode.recitation_entry_no_range", name=entry.name, status=status)


def _entry_of(path: Path) -> JobEntry:
    """A job-list entry for the recitation at *path*, read here (damaged when it cannot be)."""
    path = Path(path)
    name = path.name.removesuffix(".qalun.json")
    try:
        project = load_project(path)
        return JobEntry(
            path,
            Path(project.audio).stem,
            project.mode,
            job_status(project),
            0.0,
            ayah_range=ayah_range(project.cards),
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return JobEntry(path, name, "recitation", DAMAGED, 0.0)

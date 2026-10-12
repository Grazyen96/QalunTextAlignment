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
project (``import_episode_clip``), with their original names kept beside the
copies (which are named by their content), and the choice becomes one undoable
edit of the session. An intro or outro the person chose or removed here also
becomes the default new lectures start with; a part left alone leaves its
default alone, so setting only a lecture's recitation never clears the
channel's intro. A clip that cannot be copied is said in the dialog, which
stays open; a default that cannot be kept is not a reason to lose the episode,
and is said by the window after it closes (:attr:`EpisodeDialog.default_error`).

The dialog reads on the UI thread: the job folders once (about 0.1 s for 150
local jobs) and each clip with ffprobe (about 10 ms). It is modal, so nothing
else waits on it but the person who opened it.
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
from qurantext.gui.prefs import KEEP_DEFAULT, Prefs
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
from qurantext.jobs.episode import EpisodeError, probe_part, recitation_needs_render
from qurantext.jobs.episode_assets import (
    EPISODE_SUFFIXES,
    EpisodeChoice,
    episode_dir_for,
    import_episode_clip,
)
from qurantext.jobs.project import Project, load_project
from qurantext.jobs.project_render import default_video_path

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
    """One clip part (intro or outro): its label, Choose… and Remove, and its value.

    *touched* says the person chose or removed the clip in this dialog: only
    then does OK make it the default for new lectures.
    """

    def __init__(
        self, dialog: EpisodeDialog, part: str, current: Path | None, name: str | None
    ) -> None:
        self.label = QLabel()
        self.choose = QPushButton(t("episode.choose"))
        self.remove = QPushButton(t("episode.remove"))
        self.path: Path | None = None
        #: The clip's original file name, when known (its copy is named by content).
        self.name: str | None = None
        self.length: float | None = None
        self.touched = False
        #: The clip chosen before the dialog opened is not on disk any more.
        self.missing = False
        self._dialog = dialog
        self.part = part
        self.choose.clicked.connect(self._choose)
        self.remove.clicked.connect(self._remove)
        if current is not None:
            self.missing = not current.is_file()
            try:
                length: float | None = probe_part(current).duration
            except EpisodeError:
                length = None  # gone or unreadable: said under the rows
            self.set(current, length, name)
        else:
            self.set(None, None, None)

    def layout(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(self.label, 1)
        row.addWidget(self.choose)
        row.addWidget(self.remove)
        return row

    def shown_name(self) -> str:
        """The name the person knows the clip by.

        Its original name when kept; a clip stored outside the project by its
        own name; else the part's name ("intro"), never the content hash a
        copy beside the project is named by.
        """
        if self.name:
            return self.name
        assert self.path is not None
        project_path = self._dialog._session.project.path
        if project_path is not None and _resolved(self.path.parent) == _resolved(
            episode_dir_for(project_path)
        ):
            return t(f"episode.part.{self.part}")
        return self.path.name

    def set(self, path: Path | None, length: float | None, name: str | None) -> None:
        self.path, self.length, self.name = path, length, name
        if path is None:
            self.label.setText(t("episode.none"))
            self.label.setToolTip("")
        else:
            shown = _length_text(length) if length is not None else t("episode.unknown")
            self.label.setText(t("episode.clip", name=self.shown_name(), length=ltr(shown)))
            self.label.setToolTip(str(path))
        self.remove.setEnabled(path is not None)
        self._dialog._update_total()

    def _remove(self) -> None:
        self.touched = True
        self.missing = False
        self.set(None, None, None)
        self._dialog._show_missing()

    def _choose(self) -> None:
        start = str(self.path.parent) if self.path is not None else ""
        # Both cases: a native file dialog on Linux may match the case as given,
        # and a phone names its clips IMG_1234.MOV.
        patterns = " ".join(f"*{suffix} *{suffix.upper()}" for suffix in EPISODE_SUFFIXES)
        chosen, _ = QFileDialog.getOpenFileName(
            self._dialog,
            plain_title(t(f"episode.{self.part}")),
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
        self.touched = True
        self.missing = False
        self._dialog._show_message("")
        self.set(path, info.duration, path.name)
        self._dialog._show_missing()


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
        #: Read once: the lecture does not change while the dialog is open.
        self._lecture_seconds = self._lecture_length()
        self._building = True
        #: Whether the line under the rows says a clip is missing (see ``_show_missing``).
        self._missing_shown = False
        self.setWindowTitle(plain_title(t("episode.title")))

        current = session.episode
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.total_label = QLabel()
        self._intro = _ClipRow(self, "intro", current.intro, current.intro_name)
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

        self._outro = _ClipRow(self, "outro", current.outro, current.outro_name)
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
        self._show_missing()
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
        try:
            lecture_video: Path | None = default_video_path(self._session.project)
        except (OSError, ValueError, TypeError):
            lecture_video = None
        listed: set[Path] = set()
        for entry in entries:
            path = _resolved(entry.project)
            if not _is_recitation(entry) or path == own or path in listed:
                continue
            listed.add(path)
            box.addItem(_entry_text(entry, lecture_video), entry.project)
            if entry.status == DAMAGED:
                box.model().item(box.count() - 1).setEnabled(False)
        if current is not None and _resolved(current) not in listed:
            # Chosen earlier, and no longer in the list (removed from it, or its
            # folder is not scanned): kept, so OK does not drop it unasked.
            box.addItem(_entry_text(_entry_of(current), lecture_video), current)
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
        lengths: list[float | None] = [self._lecture_seconds]
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
        """The parts as chosen in the dialog now; after OK, the copies that were stored."""
        return EpisodeChoice(
            self._intro.path,
            self._recitation(),
            self._outro.path,
            intro_name=self._intro.name if self._intro.path is not None else None,
            outro_name=self._outro.name if self._outro.path is not None else None,
        )

    def _show_message(self, text: str) -> None:
        self.message_label.setText(text)
        self.message_label.setVisible(bool(text))

    def _show_missing(self) -> None:
        """Say a clip chosen before is gone, before a render finds out."""
        if self._building:
            return
        gone = [row for row in (self._intro, self._outro) if row.missing]
        text = " ".join(
            t("episode.clip_missing", part=t(f"episode.part.{row.part}")) for row in gone
        )
        if text:
            self._show_message(text)
        elif self._missing_shown:
            self._show_message("")
        self._missing_shown = bool(text)

    def _keep(self) -> None:
        """Copy new clips beside the project, set the episode, keep what changed as default."""
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
        self._session.set_episode(
            EpisodeChoice(
                intro,
                pending.recitation,
                outro,
                intro_name=pending.intro_name,
                outro_name=pending.outro_name,
                # A generated part this dialog does not show yet stays as it is
                # unless the person chose or removed a clip for it here.
                intro_generated=None if self._intro.touched else current.intro_generated,
                outro_generated=None if self._outro.touched else current.outro_generated,
            )
        )
        rows = (self._intro, self._outro)
        # Only a part the person chose or removed here: opening an old lecture
        # to set its recitation must not clear the channel's intro.
        sources = [
            source if row.touched else KEEP_DEFAULT
            for row, source in zip(rows, (pending.intro, pending.outro), strict=True)
        ]
        # The rows now name what was stored, so choice() says what OK did.
        self._intro.path, self._outro.path = intro, outro
        if any(row.touched for row in rows):
            try:
                self._prefs.save_default_episode(
                    *sources, names=(self._intro.name, self._outro.name)
                )
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


def _is_recitation(entry: JobEntry) -> bool:
    """A recitation job, or an unreadable one named like one (its mode is in the file)."""
    if entry.mode == "recitation":
        return True
    return (
        entry.status == DAMAGED
        and not entry.mode
        and Path(entry.project).name.endswith("_recitation.qalun.json")
    )


def _status_text(entry: JobEntry, lecture_video: Path | None) -> str:
    """ "rendered" only when the episode would use the recorded video as it is.

    The rule the render itself follows (``recitation_needs_render``): the job
    list calls it current, its file is there, and it is not the lecture's own
    video. Only entries the job list calls rendered are read again for it.
    """
    if entry.status == DAMAGED:
        return t("episode.damaged")
    if entry.status != RENDERED:
        return t("episode.render_first")
    try:
        project = load_project(Path(entry.project))
        needs = recitation_needs_render(project, avoid=lecture_video)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        needs = True
    return t("episode.render_first") if needs else t("episode.rendered")


def _entry_text(entry: JobEntry, lecture_video: Path | None = None) -> str:
    """``fatiha · 1:1-7 · rendered``: which job, which ayat, and whether it renders first."""
    status = _status_text(entry, lecture_video)
    if entry.ayah_range:
        return t(
            "episode.recitation_entry",
            name=entry.name,
            range=ltr(entry.ayah_range),
            status=status,
        )
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

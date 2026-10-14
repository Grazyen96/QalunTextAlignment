"""The Export subtitles dialog: pick formats and a destination, then write.

Exporting never renders. Unsaved edits are saved first (through
:meth:`ReviewSession.save`), so the files written here and the project file
agree with each other. A bad destination, a recording ffprobe cannot read,
or a project that cannot yield a cue (:func:`export_project_subtitles`
raising ``ValueError``/``OSError``/``RuntimeError``) is shown inline, in
the dialog itself, rather than raised — the review window underneath must
stay up either way.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from qurantext.config.paths import QURAN_DB_PATH, VIDEOS_OUTPUT_DIR
from qurantext.core.subtitles import SUBTITLE_FORMATS
from qurantext.gui import theme
from qurantext.gui.files import show_in_folder
from qurantext.gui.i18n import plain_title, t, tn
from qurantext.gui.review.session import ReviewSession
from qurantext.gui.widgets import StatusChip, make_primary
from qurantext.jobs.episode_assets import EPISODE_SUFFIXES
from qurantext.jobs.project_render import export_project_subtitles

__all__ = ["ExportDialog"]

#: SRT is the format almost everything downstream understands; preselect it.
_DEFAULT_FORMAT = "srt"

#: A format description lines up with its checkbox label: the indicator plus its gap.
_HINT_INDENT = 24


class ExportDialog(QDialog):
    """Write the session's project as subtitle files, without rendering anything."""

    #: The dialog saved the project before exporting; carries the file's path.
    saved = Signal(object)

    def __init__(
        self,
        session: ReviewSession,
        parent: QWidget | None = None,
        *,
        db_path: Path = QURAN_DB_PATH,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._db_path = db_path
        self._written: list[Path] = []
        self.setWindowTitle(plain_title(t("export.title")))

        self._format_boxes: dict[str, QCheckBox] = {}
        self._build()
        self._set_defaults()

    # -- layout -----------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(t("export.formats")))
        self.format_hints: dict[str, QLabel] = {}
        for name in SUBTITLE_FORMATS:
            box = QCheckBox(name.upper())
            self._format_boxes[name] = box
            layout.addWidget(box)
            hint = QLabel(t(f"export.format.{name}"))
            hint.setWordWrap(True)
            hint.setFont(theme.font("secondary"))
            hint.setForegroundRole(QPalette.ColorRole.PlaceholderText)
            hint.setIndent(_HINT_INDENT)  # follows the text direction, unlike a margin
            self.format_hints[name] = hint
            layout.addWidget(hint)

        form = QFormLayout()
        folder_row = QHBoxLayout()
        self._folder_field = QLineEdit()
        # A typed path shows on hover too; _set_folder also puts the cursor at the start.
        self._folder_field.textChanged.connect(self._folder_field.setToolTip)
        self._choose_button = QPushButton(t("export.choose"))
        self._choose_button.clicked.connect(self._choose_folder)
        folder_row.addWidget(self._folder_field, 1)
        folder_row.addWidget(self._choose_button)
        form.addRow(t("export.folder"), folder_row)

        self._name_field = QLineEdit()
        form.addRow(t("export.name"), self._name_field)
        layout.addLayout(form)

        self._video_radio = QRadioButton(t("export.match_video"))
        self._audio_radio = QRadioButton(t("export.match_audio"))
        video_row = QHBoxLayout()
        video_row.addWidget(self._video_radio)
        self.needs_render_chip = StatusChip(t("export.needs_render"), "info", "neutral")
        video_row.addWidget(self.needs_render_chip)
        video_row.addStretch(1)
        layout.addLayout(video_row)
        layout.addWidget(self._audio_radio)

        self._result_label = QLabel()
        self._result_label.setWordWrap(True)
        self._result_label.setVisible(False)
        layout.addWidget(self._result_label)

        # Parented from the start, so setDefault below reaches the dialog: a parentless box
        # leaves the dialog without a main default, and showing it then makes the first
        # auto-default button (Choose…) the default instead.
        self.buttons = QDialogButtonBox(self)
        self._show_button = self.buttons.addButton(
            t("export.show"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self._show_button.setVisible(False)
        self._show_button.clicked.connect(self._show_written)
        self._go_button = self.buttons.addButton(
            t("export.go"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._go_button.setDefault(True)
        make_primary(self._go_button)
        self.close_button = self.buttons.addButton(
            t("export.close"), QDialogButtonBox.ButtonRole.RejectRole
        )
        layout.addWidget(self.buttons)
        # Export writes and stays open to say what it wrote; only Close leaves.
        self._go_button.clicked.connect(self.export)
        self.close_button.clicked.connect(self.accept)

    def _set_defaults(self) -> None:
        self._format_boxes[_DEFAULT_FORMAT].setChecked(True)

        project = self._session.project
        render = project.render or {}
        video = render.get("video")
        folder = Path(video).parent if video else VIDEOS_OUTPUT_DIR
        self._set_folder(str(folder))
        self._name_field.setText(Path(project.audio).stem)

        available = self.video_timeline_available()
        if project.render_is_stale:
            # Still the video's clock, but not the video's content: say so.
            self._video_radio.setText(t("export.match_video_stale"))
        self._video_radio.setEnabled(available)
        self.needs_render_chip.setVisible(not available)
        self._video_radio.setChecked(available)
        self._audio_radio.setChecked(not available)

    # -- reading ------------------------------------------------------------------

    def video_timeline_available(self) -> bool:
        """Whether the project has a rendered video to line subtitles up with."""
        return self._session.project.render is not None

    def timeline(self) -> str:
        return "video" if self._video_radio.isChecked() else "audio"

    def formats(self) -> tuple[str, ...]:
        return tuple(name for name in SUBTITLE_FORMATS if self._format_boxes[name].isChecked())

    def destination(self) -> Path:
        return Path(self._folder_field.text()) / self._name_field.text()

    # -- programmatic control (also used by tests) ---------------------------------

    def set_formats(self, formats: tuple[str, ...]) -> None:
        chosen = set(formats)
        for name, box in self._format_boxes.items():
            box.setChecked(name in chosen)

    def set_destination(self, folder: Path, stem: str) -> None:
        self._set_folder(str(folder))
        self._name_field.setText(stem)

    # -- actions ------------------------------------------------------------------

    def _choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, plain_title(t("export.choose")), self._folder_field.text()
        )
        if chosen:
            self._set_folder(chosen)

    def _set_folder(self, folder: str) -> None:
        """Show the path from its start, with the whole of it on hover."""
        self._folder_field.setText(folder)
        self._folder_field.setCursorPosition(0)
        self._folder_field.setToolTip(folder)

    def export(self) -> list[Path]:
        """Save unsaved edits, then write the chosen formats; ``[]`` on a shown error.

        Saving is inside the same ``try`` as the write itself: a project with
        no file yet (``session.save()`` raising ``ValueError``) or one an
        unwritable folder (``OSError``) must be shown inline like any other
        export failure, not escape the click.
        """
        formats = self.formats()
        if not formats:
            self._show_error(t("export.none_chosen"))
            return []
        if not self._name_field.text().strip():
            self._show_error(t("export.no_name"))
            return []
        try:
            if self._session.dirty:
                self.saved.emit(self._session.save())
            written = export_project_subtitles(
                self._session.project,
                _named_files(self.destination()),
                formats,
                timeline=self.timeline(),
                db_path=self._db_path,
            )
        except (ValueError, OSError, RuntimeError) as error:
            # RuntimeError: ffprobe could not read the recording's length.
            self._show_error(t("export.failed", details=str(error)))
            return []
        self._written = written
        self._show_result(written)
        return written

    def _show_error(self, message: str) -> None:
        self._written = []
        self._result_label.setText(message)
        self._result_label.setVisible(True)
        self._show_button.setVisible(False)

    def _show_result(self, written: list[Path]) -> None:
        names = ", ".join(p.name for p in written)
        self._result_label.setText(tn("export.done", len(written), names=names))
        self._result_label.setVisible(True)
        self._show_button.setVisible(bool(written))

    def _show_written(self) -> None:
        if self._written:
            show_in_folder(self._written[0])


def _named_files(destination: Path) -> Path:
    """A path whose suffix each format replaces, keeping every dot the name has.

    The name is a stem ("Tafsir 25.7-11"), which ``with_suffix`` would cut at
    its last dot; a format suffix the person typed ("talk.srt") is dropped
    rather than doubled, and so is a video's ("talk.mp4", the video's own name
    typed in), which would otherwise give ``talk.mp4.srt``.
    """
    name = destination.name
    suffix = Path(name).suffix.lower()
    if suffix.lstrip(".") in SUBTITLE_FORMATS or suffix in EPISODE_SUFFIXES:
        name = Path(name).stem
    return destination.with_name(f"{name}.subtitles")

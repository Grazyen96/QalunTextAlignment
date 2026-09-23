"""The Export subtitles dialog: pick formats and a destination, then write.

Exporting never renders. Unsaved edits are saved first (through
:meth:`ReviewSession.save`), so the files written here and the project file
agree with each other. A bad destination or a project that cannot yield a
cue (:func:`export_project_subtitles` raising ``ValueError``/``OSError``) is
shown inline, in the dialog itself, rather than raised — the review window
underneath must stay up either way.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
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
from qurantext.gui.files import show_in_folder
from qurantext.gui.i18n import t
from qurantext.gui.review.session import ReviewSession
from qurantext.jobs.project_render import export_project_subtitles

__all__ = ["ExportDialog"]

#: SRT is the format almost everything downstream understands; preselect it.
_DEFAULT_FORMAT = "srt"


class ExportDialog(QDialog):
    """Write the session's project as subtitle files, without rendering anything."""

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
        self.setWindowTitle(t("export.title"))

        self._format_boxes: dict[str, QCheckBox] = {}
        self._build()
        self._set_defaults()

    # -- layout -----------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        formats_row = QHBoxLayout()
        formats_row.addWidget(QLabel(t("export.formats")))
        for name in SUBTITLE_FORMATS:
            box = QCheckBox(name.upper())
            self._format_boxes[name] = box
            formats_row.addWidget(box)
        formats_row.addStretch(1)
        layout.addLayout(formats_row)

        form = QFormLayout()
        folder_row = QHBoxLayout()
        self._folder_field = QLineEdit()
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
        layout.addWidget(self._video_radio)
        layout.addWidget(self._audio_radio)

        self._go_button = QPushButton(t("export.go"))
        self._go_button.clicked.connect(self.export)
        layout.addWidget(self._go_button)

        self._result_label = QLabel()
        self._result_label.setWordWrap(True)
        self._result_label.setVisible(False)
        layout.addWidget(self._result_label)

        self._show_button = QPushButton(t("export.show"))
        self._show_button.setVisible(False)
        self._show_button.clicked.connect(self._show_written)
        layout.addWidget(self._show_button)

    def _set_defaults(self) -> None:
        self._format_boxes[_DEFAULT_FORMAT].setChecked(True)

        project = self._session.project
        render = project.render or {}
        video = render.get("video")
        folder = Path(video).parent if video else VIDEOS_OUTPUT_DIR
        self._folder_field.setText(str(folder))
        self._name_field.setText(Path(project.audio).stem)

        available = self.video_timeline_available()
        self._video_radio.setEnabled(available)
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
        self._folder_field.setText(str(folder))
        self._name_field.setText(stem)

    # -- actions ------------------------------------------------------------------

    def _choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, t("export.choose"), self._folder_field.text()
        )
        if chosen:
            self._folder_field.setText(chosen)

    def export(self) -> list[Path]:
        """Save unsaved edits, then write the chosen formats; ``[]`` on a shown error."""
        formats = self.formats()
        if not formats:
            self._show_error(t("export.none_chosen"))
            return []
        if self._session.dirty:
            self._session.save()
        try:
            written = export_project_subtitles(
                self._session.project,
                self.destination(),
                formats,
                timeline=self.timeline(),
                db_path=self._db_path,
            )
        except (ValueError, OSError) as error:
            self._show_error(str(error))
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
        self._result_label.setText(f"{t('export.done', count=len(written))} {names}")
        self._result_label.setVisible(True)
        self._show_button.setVisible(bool(written))

    def _show_written(self) -> None:
        if self._written:
            show_in_folder(self._written[0])

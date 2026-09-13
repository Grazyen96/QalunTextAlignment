"""The window: drop an audio file, pick what it is, press Start.

What this replaces: installing Python, creating a virtual environment,
installing FFmpeg, opening a cloud account, writing a token into a dotfile,
knowing the path to a Quran text file, and choosing among a dozen subcommands
with their flags.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from qurantext.config.paths import QURAN_DB_PATH, QURAN_INPUT_DIR
from qurantext.config.settings import VIDEO_PRESETS
from qurantext.data.quran_db import ensure_quran_db, list_surahs
from qurantext.gui.jobs import JobOutcome, JobSpec, run_job
from qurantext.gui.worker import run_in_thread
from qurantext.utils.progress import CancelToken, ProgressEvent

__all__ = ["MainWindow"]

AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".mp4", ".mkv"}


class MainWindow(QMainWindow):
    """One window, one job at a time."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Qalun")
        self.setAcceptDrops(True)
        self.setMinimumWidth(560)

        self._audio: Path | None = None
        self._quran: Path | None = _default_quran_file()
        self._cancel: CancelToken | None = None
        self._thread = None
        self._worker = None
        self._outcome: JobOutcome | None = None

        self._build()
        self._refresh_enabled()

    # -- construction ---------------------------------------------------------

    def _build(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        self.drop_label = QLabel("Drop an audio file here, or choose one.")
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setMinimumHeight(84)
        self.drop_label.setStyleSheet(
            "QLabel { border: 2px dashed palette(mid); border-radius: 6px; padding: 18px; }"
        )
        layout.addWidget(self.drop_label)

        choose_row = QHBoxLayout()
        self.choose_button = QPushButton("Choose audio…")
        self.choose_button.clicked.connect(self._choose_audio)
        choose_row.addWidget(self.choose_button)
        self.quran_button = QPushButton("Quran text…")
        self.quran_button.clicked.connect(self._choose_quran)
        choose_row.addWidget(self.quran_button)
        choose_row.addStretch(1)
        layout.addLayout(choose_row)

        self.quran_label = QLabel()
        self.quran_label.setWordWrap(True)
        layout.addWidget(self.quran_label)

        options = QGroupBox("What is this recording?")
        form = QFormLayout(options)

        self.mode_box = QComboBox()
        self.mode_box.addItem("Recitation — I know which ayat", "recitation")
        self.mode_box.addItem("Lecture — find the ayat that are quoted", "lecture")
        self.mode_box.currentIndexChanged.connect(self._mode_changed)
        form.addRow("Recording", self.mode_box)

        self.surah_box = QComboBox()
        self.surah_box.currentIndexChanged.connect(self._surah_changed)
        form.addRow("Surah", self.surah_box)

        range_row = QHBoxLayout()
        self.from_spin = QSpinBox()
        self.from_spin.setMinimum(1)
        self.to_spin = QSpinBox()
        self.to_spin.setMinimum(1)
        self.from_spin.valueChanged.connect(self._range_changed)
        range_row.addWidget(QLabel("from"))
        range_row.addWidget(self.from_spin)
        range_row.addWidget(QLabel("to"))
        range_row.addWidget(self.to_spin)
        range_row.addStretch(1)
        self.range_widget = QWidget()
        self.range_widget.setLayout(range_row)
        form.addRow("Ayat", self.range_widget)

        self.preset_box = QComboBox()
        for name, (width, height, fps) in sorted(VIDEO_PRESETS.items()):
            self.preset_box.addItem(f"{name} — {width}×{height} at {fps} fps", name)
        self.preset_box.setCurrentIndex(max(0, self.preset_box.findData("social")))
        form.addRow("Video size", self.preset_box)

        layout.addWidget(options)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("Ready")
        layout.addWidget(self.progress)

        self.status = QLabel(" ")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self._start)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._request_cancel)
        self.reveal_button = QPushButton("Show the video")
        self.reveal_button.setEnabled(False)
        self.reveal_button.clicked.connect(self._reveal)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        buttons.addWidget(self.reveal_button)
        layout.addLayout(buttons)

        self.setCentralWidget(root)
        self._load_surahs()
        self._update_quran_label()

    def _load_surahs(self) -> None:
        """Populate the picker from the store, so the user names the range."""
        self.surah_box.clear()
        if self._quran is None:
            self.surah_box.addItem("Choose the Quran text file first", None)
            self.surah_box.setEnabled(False)
            return
        try:
            conn = ensure_quran_db(self._quran, QURAN_DB_PATH)
            try:
                surahs = list_surahs(conn)
            finally:
                conn.close()
        except Exception as error:  # noqa: BLE001 — a bad store must not kill the window
            self.surah_box.addItem(f"Could not read the Quran store: {error}", None)
            self.surah_box.setEnabled(False)
            return

        self.surah_box.setEnabled(True)
        for surah in surahs:
            self.surah_box.addItem(
                f"{surah['surah_num']}. {surah['name']}  ({surah['ayah_count']} ayat)", surah
            )
        self._surah_changed()

    # -- input ----------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 — Qt's name
        if _first_audio(event.mimeData().urls()) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 — Qt's name
        path = _first_audio(event.mimeData().urls())
        if path is not None:
            self._set_audio(path)
            event.acceptProposedAction()

    def _choose_audio(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self,
            "Choose an audio file",
            str(Path.home()),
            "Audio and video (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.mp4 *.mkv);;All files (*)",
        )
        if name:
            self._set_audio(Path(name))

    def _choose_quran(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self,
            "Choose the Quran text file",
            str(QURAN_INPUT_DIR),
            "Text files (*.txt);;All files (*)",
        )
        if name:
            self._quran = Path(name)
            self._update_quran_label()
            self._load_surahs()
            self._refresh_enabled()

    def _set_audio(self, path: Path) -> None:
        self._audio = path
        self.drop_label.setText(f"{path.name}\n{path.parent}")
        self._refresh_enabled()

    def _update_quran_label(self) -> None:
        self.quran_label.setText(
            f"Quran text: {self._quran}" if self._quran else "Quran text: not chosen yet"
        )

    def _mode_changed(self) -> None:
        recitation = self.mode_box.currentData() == "recitation"
        self.surah_box.setVisible(recitation)
        self.range_widget.setVisible(recitation)
        form = self.surah_box.parentWidget().layout()
        if isinstance(form, QFormLayout):
            for widget in (self.surah_box, self.range_widget):
                label = form.labelForField(widget)
                if label is not None:
                    label.setVisible(recitation)
        self._refresh_enabled()

    def _surah_changed(self) -> None:
        surah = self.surah_box.currentData()
        count = int(surah["ayah_count"]) if surah else 1
        for spin in (self.from_spin, self.to_spin):
            spin.setMaximum(count)
        self.from_spin.setValue(1)
        self.to_spin.setValue(count)
        self._refresh_enabled()

    def _range_changed(self) -> None:
        if self.to_spin.value() < self.from_spin.value():
            self.to_spin.setValue(self.from_spin.value())

    def current_spec(self) -> JobSpec:
        """The job the window would run right now."""
        surah = self.surah_box.currentData()
        recitation = self.mode_box.currentData() == "recitation"
        return JobSpec(
            audio=self._audio or Path(),
            quran=self._quran or Path(),
            mode=str(self.mode_box.currentData()),
            surah_num=int(surah["surah_num"]) if (recitation and surah) else None,
            from_ayah=self.from_spin.value() if (recitation and surah) else None,
            to_ayah=self.to_spin.value() if (recitation and surah) else None,
            preset=str(self.preset_box.currentData()),
        )

    def _refresh_enabled(self) -> None:
        running = self._cancel is not None
        problem = self.current_spec().validate()
        self.start_button.setEnabled(not running and problem is None)
        self.start_button.setToolTip(problem or "")
        for widget in (
            self.choose_button,
            self.quran_button,
            self.mode_box,
            self.surah_box,
            self.range_widget,
            self.preset_box,
        ):
            widget.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    # -- running --------------------------------------------------------------

    def _start(self) -> None:
        spec = self.current_spec()
        problem = spec.validate()
        if problem is not None:
            QMessageBox.information(self, "Not ready yet", problem)
            return

        self._outcome = None
        self.reveal_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setFormat("Starting…")
        self.status.setText(" ")
        self._cancel = CancelToken()
        self._refresh_enabled()

        self._thread, self._worker = run_in_thread(
            lambda progress, cancel: run_job(spec, progress=progress, cancel=cancel),
            self._cancel,
            on_progress=self._on_progress,
            on_finished=self._on_finished,
            on_failed=self._on_failed,
            on_cancelled=self._on_cancelled,
            on_done=self._on_done,
        )

    def _request_cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.cancel()
            self.cancel_button.setEnabled(False)
            self.progress.setFormat("Stopping…")

    def _on_progress(self, event: ProgressEvent) -> None:
        if event.fraction is None:
            self.status.setText(event.message.strip() or " ")
            return
        self.progress.setValue(int(max(0.0, min(1.0, event.fraction)) * 100))
        stage = "Rendering" if event.stage == "render" else "Matching"
        if event.eta_seconds is not None and not event.done:
            self.progress.setFormat(f"{stage} — %p%, about {_minutes(event.eta_seconds)} left")
        else:
            self.progress.setFormat(f"{stage} — %p%")

    def _on_finished(self, outcome: JobOutcome) -> None:
        self._outcome = outcome
        self.progress.setValue(100)
        self.progress.setFormat("Finished")
        where = outcome.video or outcome.matches
        self.status.setText(f"{outcome.cards} card(s). Saved to {where}")
        self.reveal_button.setEnabled(outcome.video is not None)

    def _on_failed(self, message: str) -> None:
        self.progress.setFormat("Stopped")
        self.status.setText(message)
        QMessageBox.warning(self, "That did not finish", message)

    def _on_cancelled(self) -> None:
        self.progress.setValue(0)
        self.progress.setFormat("Cancelled")
        self.status.setText("Stopped. Nothing was left behind.")

    def _on_done(self) -> None:
        self._cancel = None
        self._refresh_enabled()

    def _reveal(self) -> None:
        if self._outcome is None or self._outcome.video is None:
            return
        _show_in_folder(self._outcome.video)


def _minutes(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    return f"{int(seconds // 60)}m {int(seconds % 60):02d}s"


def _first_audio(urls) -> Path | None:
    for url in urls:
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if path.suffix.lower() in AUDIO_SUFFIXES:
            return path
    return None


def _default_quran_file() -> Path | None:
    if not QURAN_INPUT_DIR.is_dir():
        return None
    candidates = sorted(QURAN_INPUT_DIR.glob("*.txt"))
    return candidates[0] if candidates else None


def _show_in_folder(path: Path) -> None:
    """Reveal the file in the platform's file manager, selected where possible."""
    try:
        if sys.platform == "win32":
            subprocess.run(["explorer", "/select,", str(path)], check=False)
            return
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=False)
            return
    except OSError:
        pass
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

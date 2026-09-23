"""The new-job panel: drop an audio file, say what it is, press Start.

Everything a job needs is collected here — audio, Quran text, mode, range,
video size, and the rarely-changed choices folded under "More options" — so
``spec()`` always answers "the job this panel would run right now" and
``problem()`` always answers "what stops it". The home window listens to
``start_requested``/``cancel_requested`` and drives ``set_running``/
``set_progress``; this panel never runs anything itself.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qurantext.config.paths import QURAN_DB_PATH, QURAN_INPUT_DIR
from qurantext.config.settings import VIDEO_PRESETS
from qurantext.core.subtitles import SUBTITLE_FORMATS
from qurantext.data.quran_db import ensure_quran_db, list_surahs
from qurantext.gui.i18n import t
from qurantext.gui.jobs import JobSpec
from qurantext.gui.prefs import Prefs
from qurantext.jobs.project import SUBTITLE_CHOICES

__all__ = ["AUDIO_SUFFIXES", "NewJobPanel"]

AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".mp4", ".mkv"}

#: Display order for the preset combo: the two most people want, then the rest.
_PRESET_ORDER = ("social", "high", "standard", "fast")
_PRESET_KEYS = {
    "social": "preset.social",
    "high": "preset.high",
    "standard": "preset.standard",
    "fast": "preset.fast",
}
_SUBTITLE_KEYS = {
    "burn": "home.subtitles.burn",
    "sidecar": "home.subtitles.sidecar",
    "both": "home.subtitles.both",
}
#: The drop zone's height: room for the file's name, its folder and "Choose…".
_DROP_ZONE_HEIGHT = 96

#: The Recitation | Lecture toggle. Native checkable buttons barely show which
#: one is down in some styles; the palette's highlight reads as "chosen" in a
#: light and a dark theme alike.
_TOGGLE_STYLE = (
    "QPushButton { border: 1px solid palette(mid); border-radius: 4px; padding: 4px 14px;"
    " background: palette(button); color: palette(button-text); }"
    " QPushButton:checked { background: palette(highlight); color: palette(highlighted-text);"
    " border-color: palette(highlight); }"
    " QPushButton:disabled { color: palette(mid); }"
)

_FORMAT_KEYS = {
    "srt": "format.srt",
    "vtt": "format.vtt",
    "ass": "format.ass",
}


class NewJobPanel(QWidget):
    """Collects one job's worth of choices and starts it."""

    #: Start was pressed and ``problem()`` was None; carries the ``JobSpec``.
    start_requested = Signal(object)
    #: Cancel was pressed while a job was running.
    cancel_requested = Signal()

    def __init__(
        self,
        prefs: Prefs,
        *,
        quran_default: Path | None,
        parent: QWidget | None = None,
        db_path: Path = QURAN_DB_PATH,
    ) -> None:
        super().__init__(parent)
        self._prefs = prefs
        self._quran_default = quran_default
        self._db_path = db_path
        self._audio: Path | None = None
        self._quran_override: Path | None = prefs.quran_override
        self._output_dir: Path | None = prefs.output_dir
        self.setAcceptDrops(True)

        self.format_boxes: dict[str, QCheckBox] = {}
        self.subtitle_buttons: dict[str, QRadioButton] = {}

        self._build()
        self._update_quran_label()
        self._update_output_dir_label()
        self._load_surahs()
        self._apply_prefs()
        self._refresh()

    # -- construction -----------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.heading_label = QLabel(t("home.new_job"))
        heading_font = self.heading_label.font()
        heading_font.setBold(True)
        self.heading_label.setFont(heading_font)
        layout.addWidget(self.heading_label)

        # The drop zone holds its own "Choose…": dropping and choosing are one
        # control, not a box and a stray button under it.
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setFixedHeight(_DROP_ZONE_HEIGHT)
        self.drop_zone.setStyleSheet(
            "QFrame#dropZone { border: 2px dashed palette(mid); border-radius: 6px; }"
        )
        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setContentsMargins(12, 8, 12, 8)
        drop_layout.setSpacing(4)
        self.drop_label = QLabel(t("home.drop"))
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setWordWrap(True)
        # A long folder path must not widen the whole window; it is clipped
        # here and shown in full as the tooltip.
        self.drop_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        drop_layout.addWidget(self.drop_label)
        self.choose_button = QPushButton(t("home.choose"))
        self.choose_button.setFlat(True)
        self.choose_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.choose_button.setStyleSheet(
            "QPushButton { border: none; color: palette(link); text-decoration: underline; }"
            " QPushButton:disabled { color: palette(mid); }"
        )
        self.choose_button.clicked.connect(self._choose_audio)
        drop_layout.addWidget(self.choose_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.drop_zone)

        mode_row = QHBoxLayout()
        self.recitation_button = QPushButton(t("home.mode.recitation"))
        self.recitation_button.setCheckable(True)
        self.lecture_button = QPushButton(t("home.mode.lecture"))
        self.lecture_button.setCheckable(True)
        for button in (self.recitation_button, self.lecture_button):
            button.setStyleSheet(_TOGGLE_STYLE)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.recitation_button)
        self._mode_group.addButton(self.lecture_button)
        mode_row.addWidget(self.recitation_button)
        mode_row.addWidget(self.lecture_button)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)
        self._mode_group.buttonToggled.connect(self._mode_changed)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        self.surah_box = QComboBox()
        self.surah_box.currentIndexChanged.connect(self._surah_changed)
        form.addRow(t("home.surah"), self.surah_box)

        range_row = QHBoxLayout()
        range_row.setContentsMargins(0, 0, 0, 0)
        self.from_spin = QSpinBox()
        self.from_spin.setMinimum(1)
        self.to_spin = QSpinBox()
        self.to_spin.setMinimum(1)
        self.from_spin.valueChanged.connect(self._range_changed)
        self.to_spin.valueChanged.connect(self._range_changed)
        range_row.addWidget(QLabel(t("home.range_from")))
        range_row.addWidget(self.from_spin)
        range_row.addWidget(QLabel(t("home.range_to")))
        range_row.addWidget(self.to_spin)
        range_row.addStretch(1)
        self.range_widget = QWidget()
        self.range_widget.setLayout(range_row)
        form.addRow(t("home.range"), self.range_widget)

        self.preset_box = QComboBox()
        for name in _PRESET_ORDER:
            if name in VIDEO_PRESETS:  # defends against a preset renamed elsewhere
                self.preset_box.addItem(t(_PRESET_KEYS[name]), name)
        self.preset_box.currentIndexChanged.connect(self._preset_changed)
        form.addRow(t("home.video_size"), self.preset_box)
        layout.addWidget(form_widget)

        self.more_button = QToolButton()
        self.more_button.setText(t("home.more"))
        self.more_button.setCheckable(True)
        self.more_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.more_button.setArrowType(Qt.ArrowType.RightArrow)
        self.more_button.toggled.connect(self._toggle_more_options)
        layout.addWidget(self.more_button)

        self.more_group = QWidget()
        more_layout = QVBoxLayout(self.more_group)
        more_layout.setContentsMargins(0, 0, 0, 0)

        quran_row = QHBoxLayout()
        self.quran_label = QLabel()
        self.quran_label.setWordWrap(True)
        quran_row.addWidget(self.quran_label, 1)
        self.quran_choose_button = QPushButton(t("home.choose"))
        self.quran_choose_button.clicked.connect(self._choose_quran_override)
        quran_row.addWidget(self.quran_choose_button)
        self.quran_reset_button = QPushButton(t("home.quran_override.reset"))
        self.quran_reset_button.clicked.connect(lambda: self.set_quran(None))
        quran_row.addWidget(self.quran_reset_button)
        more_layout.addLayout(quran_row)

        output_row = QHBoxLayout()
        self.output_label = QLabel()
        self.output_label.setWordWrap(True)
        output_row.addWidget(self.output_label, 1)
        self.output_choose_button = QPushButton(t("home.choose"))
        self.output_choose_button.clicked.connect(self._choose_output_dir)
        output_row.addWidget(self.output_choose_button)
        self.output_reset_button = QPushButton(t("home.output_dir.reset"))
        self.output_reset_button.clicked.connect(lambda: self.set_output_dir(None))
        output_row.addWidget(self.output_reset_button)
        more_layout.addLayout(output_row)

        subtitles_row = QHBoxLayout()
        self._subtitles_group = QButtonGroup(self)
        self._subtitles_group.setExclusive(True)
        for value in SUBTITLE_CHOICES:
            button = QRadioButton(t(_SUBTITLE_KEYS[value]))
            self.subtitle_buttons[value] = button
            self._subtitles_group.addButton(button)
            subtitles_row.addWidget(button)
        subtitles_row.addStretch(1)
        more_layout.addLayout(subtitles_row)
        self._subtitles_group.buttonToggled.connect(self._subtitles_changed)

        self.formats_widget = QWidget()
        formats_row = QHBoxLayout(self.formats_widget)
        formats_row.setContentsMargins(0, 0, 0, 0)
        for fmt in SUBTITLE_FORMATS:
            box = QCheckBox(t(_FORMAT_KEYS[fmt]))
            box.toggled.connect(self._formats_changed)
            self.format_boxes[fmt] = box
            formats_row.addWidget(box)
        formats_row.addStretch(1)
        more_layout.addWidget(self.formats_widget)

        self.render_right_away_box = QCheckBox(t("home.render_right_away"))
        self.render_right_away_box.toggled.connect(self._render_right_away_changed)
        more_layout.addWidget(self.render_right_away_box)

        layout.addWidget(self.more_group)

        buttons_row = QHBoxLayout()
        self.start_button = QPushButton(t("home.start"))
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(lambda: self.start_requested.emit(self.spec()))
        self.cancel_button = QPushButton(t("home.cancel"))
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.cancel_button.setVisible(False)
        buttons_row.addWidget(self.start_button)
        buttons_row.addWidget(self.cancel_button)
        # What stops Start is said beside it, where the eye already is.
        self.problem_label = QLabel()
        self.problem_label.setWordWrap(True)
        buttons_row.addWidget(self.problem_label, 1)
        # Takes the room the hidden label leaves, so Start keeps its own width.
        buttons_row.addStretch(0)
        layout.addLayout(buttons_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)
        # Spare height goes below the form, so the controls stay together at the top.
        layout.addStretch(1)

    def _apply_prefs(self) -> None:
        """Set every control from ``prefs``, once, after the widgets exist."""
        recitation = self._prefs.mode == "recitation"
        (self.recitation_button if recitation else self.lecture_button).setChecked(True)
        self._set_mode_visibility(recitation)

        index = self.preset_box.findData(self._prefs.preset)
        self.preset_box.setCurrentIndex(max(0, index))

        self.subtitle_buttons[self._prefs.subtitles].setChecked(True)
        self._set_formats_visibility(self._prefs.subtitles)
        chosen = set(self._prefs.formats)
        for fmt, box in self.format_boxes.items():
            box.setChecked(fmt in chosen)

        self.render_right_away_box.setChecked(self._prefs.render_right_away)

        self.more_button.setChecked(self._prefs.more_options_open)
        self._set_more_options_visibility(self._prefs.more_options_open)

    # -- the Quran store ----------------------------------------------------------

    def _usable_override(self) -> Path | None:
        """The override while its file is there, else None.

        The choice itself stays in ``prefs``: a file on a drive that is not
        plugged in right now must not erase it, only step aside for the default.
        """
        if self._quran_override is not None and self._quran_override.is_file():
            return self._quran_override
        return None

    def _effective_quran(self) -> Path | None:
        return self._usable_override() or self._quran_default

    def _load_surahs(self) -> None:
        """Populate the picker from the store, so the user names the range."""
        self.surah_box.clear()
        quran = self._effective_quran()
        if quran is None:
            self.surah_box.addItem(t("home.quran_missing"), None)
            self.surah_box.setEnabled(False)
            self._surah_changed()
            return
        try:
            conn = ensure_quran_db(quran, self._db_path)
            try:
                surahs = list_surahs(conn)
            finally:
                conn.close()
        except Exception as error:  # noqa: BLE001 — a bad store must not kill the window
            self.surah_box.addItem(t("home.quran_store_error", details=str(error)), None)
            self.surah_box.setEnabled(False)
            self._surah_changed()
            return

        self.surah_box.setEnabled(True)
        for surah in surahs:
            self.surah_box.addItem(
                f"{surah['surah_num']}. {surah['name']}  ({surah['ayah_count']} ayat)", surah
            )
        self._surah_changed()

    # -- input --------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 — Qt's name
        if _first_audio(event.mimeData().urls()) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 — Qt's name
        path = _first_audio(event.mimeData().urls())
        if path is not None:
            self.set_audio(path)
            event.acceptProposedAction()

    def _choose_audio(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self,
            t("home.choose_audio.dialog_title"),
            str(Path.home()),
            "Audio and video (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.mp4 *.mkv);;All files (*)",
        )
        if name:
            self.set_audio(Path(name))

    def set_audio(self, path: Path) -> None:
        """Set the chosen audio file; used by the dialog, and by drops."""
        self._audio = path
        self.drop_label.setText(f"{path.name}\n{path.parent}")
        self.drop_label.setToolTip(str(path))
        self._refresh()

    def _choose_quran_override(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self,
            t("home.quran_override.dialog_title"),
            str(QURAN_INPUT_DIR),
            "Text files (*.txt);;All files (*)",
        )
        if name:
            self.set_quran(Path(name))

    def set_quran(self, path: Path | None) -> None:
        """Set (``path``) or clear (``None``) the Quran text override."""
        self._quran_override = path
        self._prefs.quran_override = path
        self._update_quran_label()
        self._load_surahs()
        self._refresh()

    def _choose_output_dir(self) -> None:
        name = QFileDialog.getExistingDirectory(
            self, t("home.output_dir.dialog_title"), str(Path.home())
        )
        if name:
            self.set_output_dir(Path(name))

    def set_output_dir(self, path: Path | None) -> None:
        """Set (``path``) or clear (``None``) the output folder override."""
        self._output_dir = path
        self._prefs.output_dir = path
        self._update_output_dir_label()
        self._refresh()

    def _update_quran_label(self) -> None:
        override = self._usable_override()
        if override is not None:
            self.quran_label.setText(t("home.quran_override.custom", path=str(override)))
        elif self._quran_default is not None:
            self.quran_label.setText(t("home.quran_override.default"))
        else:
            self.quran_label.setText(t("home.quran_missing"))

    def _update_output_dir_label(self) -> None:
        if self._output_dir is not None:
            self.output_label.setText(t("home.output_dir.custom", path=str(self._output_dir)))
        else:
            self.output_label.setText(t("home.output_dir.default"))

    # -- controls -------------------------------------------------------------------

    def _mode_changed(self) -> None:
        recitation = self.recitation_button.isChecked()
        self._prefs.mode = "recitation" if recitation else "lecture"
        self._set_mode_visibility(recitation)
        self._refresh()

    def _set_mode_visibility(self, recitation: bool) -> None:
        self.surah_box.setVisible(recitation)
        self.range_widget.setVisible(recitation)
        form = self.surah_box.parentWidget().layout() if self.surah_box.parentWidget() else None
        if isinstance(form, QFormLayout):
            for widget in (self.surah_box, self.range_widget):
                label = form.labelForField(widget)
                if label is not None:
                    label.setVisible(recitation)

    def _surah_changed(self) -> None:
        surah = self.surah_box.currentData()
        count = int(surah["ayah_count"]) if surah else 1
        for spin in (self.from_spin, self.to_spin):
            spin.setMaximum(count)
        self.from_spin.setValue(1)
        self.to_spin.setValue(count)
        self._refresh()

    def _range_changed(self) -> None:
        if self.to_spin.value() < self.from_spin.value():
            self.to_spin.setValue(self.from_spin.value())
        self._refresh()

    def _preset_changed(self) -> None:
        self._prefs.preset = str(self.preset_box.currentData())
        self._refresh()

    def _toggle_more_options(self, checked: bool) -> None:
        self._prefs.more_options_open = checked
        self._set_more_options_visibility(checked)

    def _set_more_options_visibility(self, open_: bool) -> None:
        self.more_group.setVisible(open_)
        self.more_button.setArrowType(Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)

    def _current_subtitles(self) -> str:
        for value, button in self.subtitle_buttons.items():
            if button.isChecked():
                return value
        return "burn"

    def _subtitles_changed(self) -> None:
        value = self._current_subtitles()
        self._prefs.subtitles = value
        self._set_formats_visibility(value)
        self._refresh()

    def _set_formats_visibility(self, subtitles: str) -> None:
        self.formats_widget.setVisible(subtitles in ("sidecar", "both"))

    def _formats_changed(self) -> None:
        chosen = tuple(fmt for fmt in SUBTITLE_FORMATS if self.format_boxes[fmt].isChecked())
        self._prefs.formats = chosen
        self._refresh()

    def _render_right_away_changed(self, checked: bool) -> None:
        self._prefs.render_right_away = checked
        self._refresh()

    # -- the job ----------------------------------------------------------------------

    def spec(self) -> JobSpec:
        """The job this panel would run right now."""
        recitation = self.recitation_button.isChecked()
        surah = self.surah_box.currentData() if recitation else None
        formats = tuple(fmt for fmt in SUBTITLE_FORMATS if self.format_boxes[fmt].isChecked())
        return JobSpec(
            audio=self._audio or Path(),
            quran=self._effective_quran() or Path(),
            mode="recitation" if recitation else "lecture",
            surah_num=int(surah["surah_num"]) if surah else None,
            from_ayah=self.from_spin.value() if surah else None,
            to_ayah=self.to_spin.value() if surah else None,
            preset=str(self.preset_box.currentData()),
            subtitles=self._current_subtitles(),
            formats=formats,
            render_right_away=self.render_right_away_box.isChecked(),
            output_dir=self._output_dir,
        )

    def problem(self) -> str | None:
        """The i18n key describing what stops the job, or None when it can run."""
        return self.spec().validate()

    def _refresh(self) -> None:
        problem = self.problem()
        self.problem_label.setText(t(problem) if problem else "")
        self.problem_label.setVisible(problem is not None)
        self.start_button.setEnabled(problem is None)

    # -- running --------------------------------------------------------------------

    def set_running(self, running: bool) -> None:
        """Disable every input and swap Start for Cancel while a job runs."""
        for widget in (
            self.choose_button,
            self.recitation_button,
            self.lecture_button,
            self.surah_box,
            self.range_widget,
            self.preset_box,
            self.more_button,
            self.quran_choose_button,
            self.quran_reset_button,
            self.output_choose_button,
            self.output_reset_button,
            *self.subtitle_buttons.values(),
            *self.format_boxes.values(),
            self.render_right_away_box,
        ):
            widget.setEnabled(not running)
        self.setAcceptDrops(not running)
        self.start_button.setVisible(not running)
        self.cancel_button.setVisible(running)
        self.progress_bar.setVisible(running)
        self.status_label.setVisible(running)
        if not running:
            self._refresh()

    def set_progress(self, fraction: float | None, text: str) -> None:
        """Update the progress bar (``None`` for an indeterminate stage) and status line."""
        if fraction is None:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(int(max(0.0, min(1.0, fraction)) * 100))
        self.status_label.setText(text)

    def show_status(self, text: str) -> None:
        """Show *text* on the status line (hidden when empty), running or not.

        How the last job ended, or why a job could not be opened, is said here
        after ``set_running(False)`` has put the progress away.
        """
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))


def _first_audio(urls) -> Path | None:
    for url in urls:
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if path.suffix.lower() in AUDIO_SUFFIXES:
            return path
    return None

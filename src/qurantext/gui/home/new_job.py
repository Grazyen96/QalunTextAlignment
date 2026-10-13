"""The new-job panel: drop an audio file, say what it is, press Start.

The form holds the job's own choices — audio, mode, range, video size, and
the rarely-changed ones folded under "More options" — in one column. The
machine's settings (the Quran text, the output folder, the engine) are the
Settings dialog's; the form reads them from ``prefs`` and is told to read
them again with ``reload_settings``. So ``spec()`` always answers "the job
this panel would run right now" and ``problem()`` always answers "what
stops it". The home window listens to ``start_requested``/
``cancel_requested``/``settings_requested`` and drives ``set_running``/
``set_progress``; this panel never runs anything itself.
"""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QPalette
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
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

from qurantext.config.paths import QURAN_DB_PATH
from qurantext.config.settings import VIDEO_PRESETS, env_dir, get_settings
from qurantext.core.subtitles import SUBTITLE_FORMATS
from qurantext.data.quran_db import ensure_quran_db, list_surahs
from qurantext.gui import theme
from qurantext.gui.i18n import path_text, plain_title, t, tn
from qurantext.gui.icons import icon, set_icon
from qurantext.gui.jobs import JobSpec
from qurantext.gui.prefs import Prefs
from qurantext.gui.surahs import fill_studied_surah_box, select_studied_surah
from qurantext.gui.widgets import Card, SectionHeader, make_primary
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
#: The drop zone's height: room for its icon, the file's name, its folder and "Choose…".
_DROP_ZONE_HEIGHT = 112
#: The form's widest: a column of choices reads down, not across a wide window.
_COLUMN_WIDTH = 560
#: The drop zone's icon, in px.
_DROP_ICON_SIZE = 24

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
    #: The engine note's link was followed: the window opens Settings.
    settings_requested = Signal()

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
        #: True while the surah list is being filled and set back to the
        #: remembered choice, so those steps are not remembered as new choices.
        self._restoring_range = False
        #: True between ``set_running(True)`` and ``set_running(False)``: a
        #: settings reload meanwhile must not wake the inputs or Start's reason.
        self._running = False
        self.setAcceptDrops(True)

        self.format_boxes: dict[str, QCheckBox] = {}
        self.subtitle_buttons: dict[str, QRadioButton] = {}

        self._build()
        self._load_surahs()
        self._apply_prefs()
        self._refresh()

    # -- construction -----------------------------------------------------------

    def _build(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        # One column, no wider than a form reads well; the stretch keeps it at
        # the leading edge (the layout mirrors it in Arabic).
        self.column = QWidget()
        self.column.setMaximumWidth(_COLUMN_WIDTH)
        outer.addWidget(self.column, 1)
        outer.addStretch(0)
        layout = QVBoxLayout(self.column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SP_12)

        self.heading = SectionHeader(t("home.new_job"))
        self.heading_label = self.heading.label
        layout.addWidget(self.heading)

        # The drop zone holds its own "Choose…": dropping and choosing are one
        # control, not a box and a stray button under it.
        # A card with a dashed rule: the sheet knows it by its object name, and
        # lights it while an accepted drag is over it (the ``dragOver`` property).
        self.drop_zone = Card()
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setFixedHeight(_DROP_ZONE_HEIGHT)
        self.drop_zone.setProperty("dragOver", False)
        drop_layout = self.drop_zone.body
        drop_layout.setContentsMargins(12, 6, 12, 6)
        drop_layout.setSpacing(2)
        self.drop_icon = QLabel()
        self.drop_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(self.drop_icon)
        self._show_drop_icon()
        self.drop_label = QLabel(t("home.drop"))
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setWordWrap(True)
        # A long folder path must not widen the whole window, nor wrap past the
        # zone's fixed height: each line is elided to the label's width (again
        # on every resize) and the whole path is the tooltip.
        self.drop_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.drop_label.installEventFilter(self)
        drop_layout.addWidget(self.drop_label)
        self.choose_button = QPushButton(t("home.choose"))
        set_icon(self.choose_button, "folder-open", size=16)
        self.choose_button.clicked.connect(self._choose_audio)
        drop_layout.addWidget(self.choose_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.drop_zone)

        mode_row = QHBoxLayout()
        self.recitation_button = QPushButton(t("home.mode.recitation"))
        self.recitation_button.setCheckable(True)
        self.lecture_button = QPushButton(t("home.mode.lecture"))
        self.lecture_button.setCheckable(True)
        # A segmented choice: the sheet fills the chosen one, and its icon turns on_accent.
        for button, name in ((self.recitation_button, "mic"), (self.lecture_button, "book-open")):
            button.setProperty("segment", True)
            set_icon(button, name, size=16, on_role="on_accent")
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.recitation_button)
        self._mode_group.addButton(self.lecture_button)
        mode_row.addWidget(self.recitation_button)
        mode_row.addWidget(self.lecture_button)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)
        self._mode_group.buttonToggled.connect(self._mode_changed)

        # What the chosen mode does, in a quieter voice under it.
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.description_label.setFont(theme.font("secondary"))
        self.description_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        layout.addWidget(self.description_label)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        self._form = form
        form.setContentsMargins(0, 0, 0, 0)
        self.surah_box = QComboBox()
        self.surah_box.currentIndexChanged.connect(self._surah_changed)
        form.addRow(t("home.surah"), self.surah_box)
        # A lecture's own picker, in the same place: which surah its cards keep
        # to. Separate from the recitation's, which also sets the ayat range.
        self.studied_surah_box = QComboBox()
        self.studied_surah_box.setToolTip(t("home.studied_surah.tip"))
        fill_studied_surah_box(self.studied_surah_box, {})
        self.studied_surah_box.currentIndexChanged.connect(self._studied_surah_changed)
        form.addRow(t("home.surah"), self.studied_surah_box)

        range_row = QHBoxLayout()
        range_row.setContentsMargins(0, 0, 0, 0)
        self.from_spin = QSpinBox()
        self.from_spin.setMinimum(1)
        self.to_spin = QSpinBox()
        self.to_spin.setMinimum(1)
        self.from_spin.valueChanged.connect(self._range_changed)
        self.to_spin.valueChanged.connect(self._range_changed)
        # Buddies, so a screen reader names each spin box by its "from"/"to".
        self.range_from_label = QLabel(t("home.range_from"))
        self.range_from_label.setBuddy(self.from_spin)
        self.range_to_label = QLabel(t("home.range_to"))
        self.range_to_label.setBuddy(self.to_spin)
        range_row.addWidget(self.range_from_label)
        range_row.addWidget(self.from_spin)
        range_row.addWidget(self.range_to_label)
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
        set_icon(self.more_button, "chevron-right", size=16)
        self.more_button.toggled.connect(self._toggle_more_options)
        layout.addWidget(self.more_button)

        # Labelled rows like the form above, so each choice says what it is
        # and its value text need not repeat it.
        self.more_group = QWidget()
        self.more_form = QFormLayout(self.more_group)
        self.more_form.setContentsMargins(0, 0, 0, 0)

        self.subtitles_row = QWidget()
        subtitles_row = QHBoxLayout(self.subtitles_row)
        subtitles_row.setContentsMargins(0, 0, 0, 0)
        self._subtitles_group = QButtonGroup(self)
        self._subtitles_group.setExclusive(True)
        for value in SUBTITLE_CHOICES:
            button = QRadioButton(t(_SUBTITLE_KEYS[value]))
            self.subtitle_buttons[value] = button
            self._subtitles_group.addButton(button)
            subtitles_row.addWidget(button)
        subtitles_row.addStretch(1)
        self.more_form.addRow(t("home.subtitles"), self.subtitles_row)
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
        self.more_form.addRow(t("home.formats"), self.formats_widget)

        self.render_right_away_box = QCheckBox(t("home.render_right_away"))
        self.render_right_away_box.toggled.connect(self._render_right_away_changed)
        self.more_form.addRow(self.render_right_away_box)  # spans both columns

        layout.addWidget(self.more_group)

        # Said here, not chosen here: the engine is a machine setting now.
        self.engine_note = QLabel()
        self.engine_note.setWordWrap(True)
        self.engine_note.setTextFormat(Qt.TextFormat.RichText)
        self.engine_note.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.engine_note.linkActivated.connect(lambda _link: self.settings_requested.emit())
        self.engine_note.setVisible(False)
        layout.addWidget(self.engine_note)

        start_row = QHBoxLayout()
        self.start_button = QPushButton(t("home.start"))
        self.start_button.setDefault(True)
        make_primary(self.start_button)
        self.start_button.clicked.connect(lambda: self.start_requested.emit(self.spec()))
        # While a job runs the bar stands where Start stood, as tall, and says the stage.
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedHeight(max(36, self.start_button.sizeHint().height()))
        self.progress_bar.setVisible(False)
        self.cancel_button = QPushButton(t("home.cancel"))
        set_icon(self.cancel_button, "x", size=16)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.cancel_button.setVisible(False)
        start_row.addWidget(self.start_button, 1)
        start_row.addWidget(self.progress_bar, 1)
        start_row.addWidget(self.cancel_button)
        layout.addLayout(start_row)
        # What stops Start is said under it, in a quieter voice.
        self.problem_label = QLabel()
        self.problem_label.setWordWrap(True)
        self.problem_label.setFont(theme.font("secondary"))
        layout.addWidget(self.problem_label)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)
        # Spare height goes below the form, so the controls stay together at the top.
        layout.addStretch(1)
        self._align_label_columns()

    def _align_label_columns(self) -> None:
        """Give the two forms one label column, so "More options" lines up with the form above.

        Two QFormLayouts size their label columns independently; the wider
        of the two sets the width of every label in both.
        """
        labels = []
        for form in (self._form, self.more_form):
            for row in range(form.rowCount()):
                item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                if item is not None and item.widget() is not None:
                    labels.append(item.widget())
        widest = max((label.sizeHint().width() for label in labels), default=0)
        for label in labels:
            label.setMinimumWidth(widest)

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
        self._show_engine_note()

    def reload_settings(self) -> None:
        """The Settings dialog changed something this form shows or sends: read it again."""
        self._load_surahs()  # refills from the (possibly new) store and puts the remembered surah back
        self._show_engine_note()
        self._refresh()

    def select_mode(self, mode: str) -> None:
        """Choose *mode* for the person (the empty state's cards) and move them to the file."""
        (self.recitation_button if mode == "recitation" else self.lecture_button).setChecked(True)
        self.choose_button.setFocus(Qt.FocusReason.OtherFocusReason)

    # -- the Quran store ----------------------------------------------------------

    def _usable_override(self) -> Path | None:
        """The override while its file is there, else None.

        The choice itself stays in ``prefs``: a file on a drive that is not
        plugged in right now must not erase it, only step aside for the default.
        """
        override = self._prefs.quran_override
        if override is not None and override.is_file():
            return override
        return None

    def _effective_quran(self) -> Path | None:
        return self._usable_override() or self._quran_default

    def _load_surahs(self) -> None:
        """Populate the picker from the store, then put back the last surah and range."""
        self._restoring_range = True
        try:
            self._fill_surahs()
            self._restore_range()
        finally:
            self._restoring_range = False
        self._refresh()

    def _restore_range(self) -> None:
        """Select the remembered surahs (a lecture's and a recitation's) and range.

        The range is clamped to that surah's ayat.
        """
        select_studied_surah(self.studied_surah_box, self._prefs.lecture_surah)
        surah_num = self._prefs.surah_num
        if surah_num is None:
            return
        for index in range(self.surah_box.count()):
            data = self.surah_box.itemData(index)
            if data is not None and int(data["surah_num"]) == surah_num:
                break
        else:
            return
        self.surah_box.setCurrentIndex(index)
        count = int(self.surah_box.itemData(index)["ayah_count"])
        first = min(self._prefs.from_ayah or 1, count)
        last = max(first, min(self._prefs.to_ayah or count, count))
        self.from_spin.setValue(first)
        self.to_spin.setValue(last)

    def _fill_surahs(self) -> None:
        """List every surah from the store, or say in the picker why there are none."""
        self.surah_box.clear()
        # Numbers only until the store is read: a lecture can still choose.
        fill_studied_surah_box(self.studied_surah_box, {})
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

        self.surah_box.setEnabled(not self._running)
        fill_studied_surah_box(
            self.studied_surah_box, {int(s["surah_num"]): str(s["name"]) for s in surahs}
        )
        for surah in surahs:
            self.surah_box.addItem(
                tn(
                    "home.surah_item",
                    surah["ayah_count"],
                    num=surah["surah_num"],
                    name=surah["name"],
                ),
                surah,
            )
        self._surah_changed()

    # -- input --------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 — Qt's name
        if _first_audio(event.mimeData().urls()) is not None:
            event.acceptProposedAction()
            self._set_drag_over(True)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802 — Qt's name
        self._set_drag_over(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 — Qt's name
        self._set_drag_over(False)
        path = _first_audio(event.mimeData().urls())
        if path is not None:
            self.set_audio(path)
            event.acceptProposedAction()

    def _set_drag_over(self, over: bool) -> None:
        """Light the zone while an accepted drag is over it; the stylesheet reads the property."""
        self.drop_zone.setProperty("dragOver", over)
        style = self.drop_zone.style()
        style.unpolish(self.drop_zone)
        style.polish(self.drop_zone)

    def _choose_audio(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self,
            plain_title(t("home.choose_audio.dialog_title")),
            str(Path.home()),
            _file_filter(t("home.filter.audio"), sorted(AUDIO_SUFFIXES)),
        )
        if name:
            self.set_audio(Path(name))

    @property
    def audio_path(self) -> Path | None:
        """The chosen audio file, or None; the one choice prefs do not keep."""
        return self._audio

    def set_audio(self, path: Path) -> None:
        """Set the chosen audio file; used by the dialog, and by drops."""
        self._audio = path
        self.drop_label.setToolTip(path_text(path))
        self._show_audio_lines()
        self._refresh()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 — Qt's name
        if watched is self.drop_label and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._show_audio_lines()
        return super().eventFilter(watched, event)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 — Qt's name
        # A label's pixmap is not a button's icon: ``refresh_icons`` does not
        # reach it, so a theme switch redraws it here.
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self._show_drop_icon()
        super().changeEvent(event)

    def _show_drop_icon(self) -> None:
        """An upload arrow until a file is chosen; then the file, in the text's colour."""
        name, role = ("upload", "secondary") if self._audio is None else ("file-music", "text")
        size = QSize(_DROP_ICON_SIZE, _DROP_ICON_SIZE)
        self.drop_icon.setPixmap(icon(name, role).pixmap(size))

    def _show_audio_lines(self) -> None:
        """The chosen file's name and folder, each elided in the middle to fit the label.

        The plain text is elided and only then wrapped by ``path_text``: an
        ellipsis cut through the direction marks would leave the line
        unisolated. A label not shown yet has no width of its own to fit, so
        it keeps the whole lines until it is shown.
        """
        self._show_drop_icon()
        if self._audio is None:
            return
        name, folder = self._audio.name, str(self._audio.parent)
        if self.drop_label.isVisible():
            metrics = self.drop_label.fontMetrics()
            width = self.drop_label.contentsRect().width()
            name = metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, width)
            folder = metrics.elidedText(folder, Qt.TextElideMode.ElideMiddle, width)
        self.drop_label.setText(f"{name}\n{path_text(folder)}")

    # -- controls -------------------------------------------------------------------

    def _mode_changed(self) -> None:
        recitation = self.recitation_button.isChecked()
        self._prefs.mode = "recitation" if recitation else "lecture"
        self._set_mode_visibility(recitation)
        self._refresh()

    def _set_mode_visibility(self, recitation: bool) -> None:
        key = "home.mode.recitation.desc" if recitation else "home.mode.lecture.desc"
        self.description_label.setText(t(key))
        shown = {
            self.surah_box: recitation,
            self.range_widget: recitation,
            self.studied_surah_box: not recitation,
        }
        form = self.surah_box.parentWidget().layout() if self.surah_box.parentWidget() else None
        for widget, visible in shown.items():
            widget.setVisible(visible)
            if isinstance(form, QFormLayout):
                label = form.labelForField(widget)
                if label is not None:
                    label.setVisible(visible)

    def _studied_surah_changed(self) -> None:
        if self._restoring_range:
            return
        self._prefs.lecture_surah = self.studied_surah_box.currentData()

    def _surah_changed(self) -> None:
        surah = self.surah_box.currentData()
        count = int(surah["ayah_count"]) if surah else 1
        for spin in (self.from_spin, self.to_spin):
            spin.setMaximum(count)
        self.from_spin.setValue(1)
        self.to_spin.setValue(count)
        self._remember_range()
        self._refresh()

    def _range_changed(self) -> None:
        if self.to_spin.value() < self.from_spin.value():
            self.to_spin.setValue(self.from_spin.value())
        self._remember_range()
        self._refresh()

    def _remember_range(self) -> None:
        if self._restoring_range:
            return
        surah = self.surah_box.currentData()
        if not surah:
            return  # no store to pick from: keep the last real choice
        self._prefs.surah_num = int(surah["surah_num"])
        self._prefs.from_ayah = self.from_spin.value()
        self._prefs.to_ayah = self.to_spin.value()

    def _preset_changed(self) -> None:
        self._prefs.preset = str(self.preset_box.currentData())
        self._refresh()

    def _toggle_more_options(self, checked: bool) -> None:
        self._prefs.more_options_open = checked
        self._set_more_options_visibility(checked)

    def _set_more_options_visibility(self, open_: bool) -> None:
        self.more_group.setVisible(open_)
        # Down when the options show; else along the reading direction (the
        # icon module mirrors it in Arabic).
        set_icon(self.more_button, "chevron-down" if open_ else "chevron-right", size=16)

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

    def _show_engine_note(self) -> None:
        """Say before Start, not after an upload, that this job goes online, and how to change it.

        Only for WhisperX: the engine is chosen in Settings, so the form only
        says it, adds that the token is missing when it is, and links there.
        """
        if self._prefs.engine != "whisperx":
            self.engine_note.setVisible(False)
            return
        parts = [html.escape(t("home.engine.note"))]
        if _token_missing():
            parts.append(html.escape(t("home.engine.no_token", folder=path_text(env_dir()))))
        parts.append(f'<a href="settings">{html.escape(t("home.engine.change"))}</a>')
        self.engine_note.setText(" ".join(parts))
        self.engine_note.setVisible(True)

    def _set_formats_visibility(self, subtitles: str) -> None:
        """Show the file formats, and their label, only when there are files to write."""
        shown = subtitles in ("sidecar", "both")
        self.formats_widget.setVisible(shown)
        label = self.more_form.labelForField(self.formats_widget)
        if label is not None:
            label.setVisible(shown)

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
            engine=self._prefs.engine,
            output_dir=self._prefs.output_dir,
            style=self._prefs.default_look_style(),
            studied_surah=None if recitation else self.studied_surah_box.currentData(),
            episode_defaults=(None, None) if recitation else self._episode_defaults(),
            episode_default_names=(
                (None, None) if recitation else self._prefs.default_episode_names
            ),
            episode_generated=(
                (None, None)
                if recitation
                else (self._prefs.default_intro_generated, self._prefs.default_outro_generated)
            ),
        )

    def _episode_defaults(self) -> tuple[str | None, str | None]:
        """The default intro and outro a new lecture starts with, as absolute strings."""
        intro, outro = self._prefs.default_episode
        return (
            str(intro) if intro is not None else None,
            str(outro) if outro is not None else None,
        )

    def problem(self) -> str | None:
        """The i18n key describing what stops the job, or None when it can run."""
        return self.spec().validate()

    def _refresh(self) -> None:
        problem = self.problem()
        self.problem_label.setText(t(problem) if problem else "")
        # Start's reason has no Start to stand under while the bar is there.
        self.problem_label.setVisible(problem is not None and not self._running)
        self.start_button.setEnabled(problem is None)

    # -- running --------------------------------------------------------------------

    def set_running(self, running: bool) -> None:
        """Disable every input and put the bar and Cancel where Start stood while a job runs."""
        self._running = running
        for widget in (
            self.choose_button,
            self.recitation_button,
            self.lecture_button,
            self.surah_box,
            self.studied_surah_box,
            self.range_widget,
            self.preset_box,
            self.more_button,
            *self.subtitle_buttons.values(),
            *self.format_boxes.values(),
            self.render_right_away_box,
        ):
            widget.setEnabled(not running)
        self.setAcceptDrops(not running)
        self.start_button.setVisible(not running)
        self.progress_bar.setVisible(running)
        self.cancel_button.setVisible(running)
        if running:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("")
            self.status_label.setVisible(False)
        # The status line is shown again by ``show_status``, with the outcome.
        self._refresh()

    def set_progress(
        self, fraction: float | None, text: str | None, *, keep_status: bool = False
    ) -> None:
        """Show how far the job is: on the bar when it knows a fraction, on the line when it does not.

        A busy bar draws no text, so a stage without a fraction says its
        sentence on the status line; a stage with one says it on the bar and
        the line goes quiet. *text* None leaves whatever is said as it is.
        *keep_status* leaves the line alone while the bar still says how far:
        the window keeps an answer to the person up there while the bar moves on.
        """
        if fraction is None:
            self.progress_bar.setRange(0, 0)
            if text is not None and not keep_status:
                self.show_status(text)
            return
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(int(max(0.0, min(1.0, fraction)) * 100))
        if text is not None:
            self.progress_bar.setFormat(text)
            if not keep_status:
                self.show_status("")

    def show_status(self, text: str) -> None:
        """Show *text* on the status line (hidden when empty), running or not.

        How the last job ended, or why a job could not be opened, is said here
        after ``set_running(False)`` has put the progress away.
        """
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))


def _token_missing() -> bool:
    """True when no Replicate token is set; False when the settings cannot be read.

    A malformed ``QURANTEXT_*`` value makes reading them raise. The job names it
    when it runs; the window must still open, so the token is taken as unknown.
    """
    try:
        return not get_settings().replicate_api_token
    except ValueError:
        return False


def _file_filter(name: str, suffixes: list[str]) -> str:
    """A file dialog's filter: ``Name (*.a *.b);;All files (*)``, the names translated."""
    patterns = " ".join(f"*{suffix}" for suffix in suffixes)
    return f"{name} ({patterns});;{t('home.filter.all')} (*)"


def _first_audio(urls) -> Path | None:
    for url in urls:
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if path.suffix.lower() in AUDIO_SUFFIXES:
            return path
    return None

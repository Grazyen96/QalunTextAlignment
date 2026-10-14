"""Everything that is about this machine or every job, in one place.

The form keeps only a job's own choices. Each control here writes ``Prefs``
as it changes, as the form always has; the window applies a language or
theme (which touch every window) and, after the dialog closes, tells the
form and the list what to reload when ``changed_files`` is set: by a file or
folder, or by the engine, whose upload note the form shows before Start.
"""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import qurantext
from qurantext.config.links import GITHUB_URL
from qurantext.config.paths import QURAN_INPUT_DIR, notices_path, user_log_dir, user_log_file
from qurantext.config.settings import ENGINES, env_dir, get_settings
from qurantext.core.looks import NIGHT_GOLD
from qurantext.gui import i18n, theme
from qurantext.gui.files import open_folder
from qurantext.gui.i18n import path_text, plain_title, t
from qurantext.gui.icons import set_icon
from qurantext.gui.prefs import KEEP_DEFAULT, Prefs
from qurantext.gui.widgets import SectionHeader

__all__ = ["GITHUB_URL", "TABS", "SettingsDialog"]

TABS = ("general", "transcription", "files", "videos", "about")


def _token_missing() -> bool:
    """True when no Replicate token is set; False when the settings cannot be read."""
    try:
        return not get_settings().replicate_api_token
    except ValueError:
        return False


def _file_filter(name: str, suffixes: list[str]) -> str:
    patterns = " ".join(f"*{suffix}" for suffix in suffixes)
    return f"{name} ({patterns});;{t('home.filter.all')} (*)"


class SettingsDialog(QDialog):
    """Five tabs; see the module docstring for who applies what."""

    language_requested = Signal(str)
    theme_requested = Signal(str)

    def __init__(
        self,
        prefs: Prefs,
        *,
        parent: QWidget | None = None,
        quran_default: Path | None,
        tab: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._prefs = prefs
        self._quran_default = quran_default
        #: Set once the Quran text, the output folder, the job folders or the
        #: engine changed: what the form shows or the list reads.
        self.changed_files = False
        self.setWindowTitle(plain_title(t("settings.title")))
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._general(), t("settings.tab.general"))
        self.tabs.addTab(self._transcription(), t("settings.tab.transcription"))
        self.tabs.addTab(self._files(), t("settings.tab.files"))
        self.tabs.addTab(self._videos(), t("settings.tab.videos"))
        self.tabs.addTab(self._about(), t("settings.tab.about"))
        layout.addWidget(self.tabs, 1)
        buttons = QDialogButtonBox(self)
        self.close_button = buttons.addButton(
            t("settings.close"), QDialogButtonBox.ButtonRole.RejectRole
        )
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(buttons)
        if tab in TABS:
            self.tabs.setCurrentIndex(TABS.index(tab))

    def current_tab(self) -> str:
        return TABS[self.tabs.currentIndex()]

    # -- General ------------------------------------------------------------------

    def _general(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.language_combo = QComboBox()
        for code in i18n.LANGUAGES:
            self.language_combo.addItem(i18n.LANGUAGE_NAMES[code], code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(i18n.current_language()))
        self.language_combo.activated.connect(
            lambda index: self.language_requested.emit(self.language_combo.itemData(index))
        )
        form.addRow(t("home.language"), self.language_combo)
        self.language_note = QLabel()
        self.language_note.setWordWrap(True)
        self.language_note.setVisible(False)
        form.addRow(self.language_note)
        self.theme_combo = QComboBox()
        for code in theme.MODES:
            self.theme_combo.addItem(t(f"home.theme.{code}"), code)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(self._prefs.theme))
        self.theme_combo.activated.connect(self._theme_chosen)
        form.addRow(t("home.theme"), self.theme_combo)
        self.animate_box = QCheckBox(t("settings.animate_panels"))
        self.animate_box.setChecked(self._prefs.animate_panels)
        self.animate_box.toggled.connect(self._animate_chosen)
        form.addRow("", self.animate_box)
        return page

    def _theme_chosen(self, index: int) -> None:
        code = self.theme_combo.itemData(index)
        self._prefs.theme = code
        self.theme_requested.emit(code)

    def _animate_chosen(self, on: bool) -> None:
        self._prefs.animate_panels = on

    def language_refused(self, reason: str) -> None:
        """The window would not switch: put the combo back and say why."""
        self.language_combo.setCurrentIndex(self.language_combo.findData(i18n.current_language()))
        self.language_note.setText(reason)
        self.language_note.setVisible(True)

    # -- Transcription ------------------------------------------------------------

    def _transcription(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        self._engine_group = QButtonGroup(self)
        self._engine_group.setExclusive(True)
        self.engine_buttons: dict[str, QRadioButton] = {}
        for value in ENGINES:
            button = QRadioButton(t(f"home.engine.{value}"))
            self.engine_buttons[value] = button
            self._engine_group.addButton(button)
            column.addWidget(button)
        self.engine_buttons[self._prefs.engine].setChecked(True)
        self.no_token_label = QLabel()
        self.no_token_label.setWordWrap(True)
        column.addWidget(self.no_token_label)
        column.addStretch(1)
        self._engine_group.buttonToggled.connect(self._engine_changed)
        self._show_token_note()
        return page

    def _current_engine(self) -> str:
        for value, button in self.engine_buttons.items():
            if button.isChecked():
                return value
        return "local"

    def _engine_changed(self) -> None:
        self._prefs.engine = self._current_engine()
        # The form says before Start that WhisperX uploads the recording.
        self.changed_files = True
        self._show_token_note()

    def _show_token_note(self) -> None:
        missing = self._current_engine() == "whisperx" and _token_missing()
        self.no_token_label.setText(
            t("home.engine.no_token", folder=path_text(env_dir())) if missing else ""
        )
        self.no_token_label.setVisible(missing)

    # -- Files --------------------------------------------------------------------

    def _files(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.quran_label = QLabel()
        self.quran_label.setWordWrap(True)
        self.quran_choose_button = QPushButton(t("home.choose"))
        self.quran_choose_button.clicked.connect(self._choose_quran)
        self.quran_reset_button = QPushButton(t("home.quran_override.reset"))
        self.quran_reset_button.clicked.connect(lambda: self.set_quran(None))
        form.addRow(
            t("home.quran_text"),
            self._value_row(self.quran_label, self.quran_choose_button, self.quran_reset_button),
        )
        self.output_label = QLabel()
        self.output_label.setWordWrap(True)
        self.output_choose_button = QPushButton(t("home.choose"))
        self.output_choose_button.clicked.connect(self._choose_output_dir)
        self.output_reset_button = QPushButton(t("home.output_dir.reset"))
        self.output_reset_button.clicked.connect(lambda: self.set_output_dir(None))
        form.addRow(
            t("home.output_dir"),
            self._value_row(self.output_label, self.output_choose_button, self.output_reset_button),
        )
        self.job_dirs_list = QListWidget()
        self.job_dirs_list.setMaximumHeight(120)
        dirs = QWidget()
        dirs_column = QVBoxLayout(dirs)
        dirs_column.setContentsMargins(0, 0, 0, 0)
        dirs_column.addWidget(self.job_dirs_list)
        dir_buttons = QHBoxLayout()
        self.add_dir_button = QPushButton(t("settings.add_dir"))
        self.remove_dir_button = QPushButton(t("settings.remove_dir"))
        set_icon(self.add_dir_button, "folder-open", size=16)
        set_icon(self.remove_dir_button, "x", size=16)
        self.add_dir_button.clicked.connect(self._add_dir)
        self.remove_dir_button.clicked.connect(self._remove_dir)
        dir_buttons.addWidget(self.add_dir_button)
        dir_buttons.addWidget(self.remove_dir_button)
        dir_buttons.addStretch(1)
        dirs_column.addLayout(dir_buttons)
        form.addRow(t("settings.job_dirs"), dirs)
        self.job_dirs_list.currentRowChanged.connect(lambda *_: self._update_dir_buttons())
        self._fill_dirs()
        self._update_quran_label()
        self._update_output_label()
        return page

    @staticmethod
    def _value_row(label: QLabel, *buttons: QPushButton) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label, 1)
        for button in buttons:
            layout.addWidget(button)
        return row

    def _usable_override(self) -> Path | None:
        override = self._prefs.quran_override
        return override if override is not None and override.is_file() else None

    def _choose_quran(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self,
            plain_title(t("home.quran_override.dialog_title")),
            str(QURAN_INPUT_DIR),
            _file_filter(t("home.filter.text"), [".txt"]),
        )
        if name:
            self.set_quran(Path(name))

    def set_quran(self, path: Path | None) -> None:
        self._prefs.quran_override = path
        self.changed_files = True
        self._update_quran_label()

    def _update_quran_label(self) -> None:
        override = self._usable_override()
        if override is not None:
            self.quran_label.setText(t("home.quran_override.custom", path=path_text(override)))
        elif self._quran_default is not None:
            self.quran_label.setText(t("home.quran_override.default"))
        else:
            self.quran_label.setText(t("home.quran_missing"))

    def _choose_output_dir(self) -> None:
        name = QFileDialog.getExistingDirectory(
            self, plain_title(t("home.output_dir.dialog_title")), str(Path.home())
        )
        if name:
            self.set_output_dir(Path(name))

    def set_output_dir(self, path: Path | None) -> None:
        self._prefs.output_dir = path  # which also adds it to the job folders
        self.changed_files = True
        self._update_output_label()
        self._fill_dirs()

    def _update_output_label(self) -> None:
        folder = self._prefs.output_dir
        self.output_label.setText(
            t("home.output_dir.custom", path=path_text(folder))
            if folder is not None
            else t("home.output_dir.default")
        )

    def _add_dir(self) -> None:
        name = QFileDialog.getExistingDirectory(
            self, plain_title(t("settings.add_dir.dialog_title")), str(Path.home())
        )
        if not name:
            return
        # Resolved, as Prefs stores it, so the list never shows a row Prefs dropped.
        folder = Path(name).resolve()
        dirs = list(self._prefs.job_dirs)
        if folder not in dirs:
            dirs.append(folder)
            self._prefs.job_dirs = dirs
            self.changed_files = True
        self._fill_dirs(select=folder)

    def _remove_dir(self) -> None:
        """Remove the chosen folder, found by the folder it names, never by its row.

        ``Prefs.job_dirs`` changes behind the dialog (an output folder chosen,
        a job finishing elsewhere); a row number would then name another folder.
        """
        self._fill_dirs()
        item = self.job_dirs_list.currentItem()
        folder = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if folder is None:
            return
        dirs = list(self._prefs.job_dirs)
        if folder in dirs:
            dirs.remove(folder)
            self._prefs.job_dirs = dirs
            self.changed_files = True
        self._fill_dirs()

    def _fill_dirs(self, select: Path | None = None) -> None:
        """List ``Prefs.job_dirs`` as they are now, each row holding its folder.

        The row that was chosen stays chosen while its folder is listed; *select*
        chooses another.
        """
        current = self.job_dirs_list.currentItem()
        if select is None and current is not None:
            select = current.data(Qt.ItemDataRole.UserRole)
        self.job_dirs_list.clear()
        for folder in self._prefs.job_dirs:
            item = QListWidgetItem(path_text(folder))
            item.setData(Qt.ItemDataRole.UserRole, folder)
            item.setToolTip(path_text(folder))
            self.job_dirs_list.addItem(item)
            if folder == select:
                self.job_dirs_list.setCurrentItem(item)
        self._update_dir_buttons()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt override
        self._fill_dirs()  # a job may have added its folder since the dialog was built
        super().showEvent(event)

    def _update_dir_buttons(self) -> None:
        self.remove_dir_button.setEnabled(self.job_dirs_list.currentRow() >= 0)

    # -- Videos -------------------------------------------------------------------

    def _videos(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.look_label = QLabel()
        self.look_reset_button = QPushButton(t("settings.look.reset"))
        set_icon(self.look_reset_button, "refresh-cw", size=16)
        self.look_reset_button.clicked.connect(self._reset_look)
        form.addRow(t("settings.look"), self._value_row(self.look_label, self.look_reset_button))
        self.intro_label = QLabel()
        self.intro_clear_button = QPushButton(t("settings.episode.clear"))
        self.intro_clear_button.clicked.connect(lambda: self._clear_part("intro"))
        self.outro_label = QLabel()
        self.outro_clear_button = QPushButton(t("settings.episode.clear"))
        self.outro_clear_button.clicked.connect(lambda: self._clear_part("outro"))
        form.addRow(SectionHeader(t("settings.episode")))
        form.addRow(
            t("settings.episode.intro"), self._value_row(self.intro_label, self.intro_clear_button)
        )
        form.addRow(
            t("settings.episode.outro"), self._value_row(self.outro_label, self.outro_clear_button)
        )
        self._show_look()
        self._show_episode()
        return page

    def _show_look(self) -> None:
        look = self._prefs.default_look
        name = (
            t(f"look.preset.{look.base_preset}")
            if f"look.preset.{look.base_preset}" in i18n.STRINGS["en"]
            else look.base_preset
        )
        self.look_label.setText(
            name if look.is_preset else t("settings.look.based_on", preset=name)
        )
        self.look_reset_button.setEnabled(look != NIGHT_GOLD)

    def _reset_look(self) -> None:
        self._prefs.save_default_look(NIGHT_GOLD)
        self._show_look()

    def _show_episode(self) -> None:
        kinds = self._prefs.default_episode_kinds
        names = self._prefs.default_episode_names
        for kind, name, label, button in zip(
            kinds,
            names,
            (self.intro_label, self.outro_label),
            (self.intro_clear_button, self.outro_clear_button),
            strict=True,
        ):
            if kind == "generated":
                label.setText(t("settings.episode.generated"))
            elif kind == "clip":
                label.setText(name or t("settings.episode.none"))
            else:
                label.setText(t("settings.episode.none"))
            button.setEnabled(kind != "none")

    def _clear_part(self, part: str) -> None:
        if part == "intro":
            self._prefs.save_default_episode(None, KEEP_DEFAULT, intro_generated=None)
        else:
            self._prefs.save_default_episode(KEEP_DEFAULT, None, outro_generated=None)
        self._show_episode()

    # -- About --------------------------------------------------------------------

    def _about(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        self.version_label = QLabel(t("settings.version", version=qurantext.__version__))
        self.version_label.setFont(theme.font("section"))
        column.addWidget(self.version_label)
        self.log_link = QLabel(f'<a href="logs">{html.escape(t("home.open_log_folder"))}</a>')
        self.log_link.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.log_link.setToolTip(t("home.open_log_folder.tip", path=path_text(user_log_file())))
        self.log_link.linkActivated.connect(lambda _link: self._open_log_folder())
        column.addWidget(self.log_link)
        self.log_failed_label = QLabel()
        self.log_failed_label.setWordWrap(True)
        self.log_failed_label.setVisible(False)
        column.addWidget(self.log_failed_label)
        notices = notices_path()
        self.notices_link = QLabel(f'<a href="notices">{html.escape(t("settings.notices"))}</a>')
        self.notices_link.setTextInteractionFlags(self.log_link.textInteractionFlags())
        if notices.is_file():
            self.notices_link.linkActivated.connect(
                lambda _link: QDesktopServices.openUrl(QUrl.fromLocalFile(str(notices)))
            )
        else:
            self.notices_link.setEnabled(False)
            self.notices_link.setToolTip(t("settings.notices.missing"))
        column.addWidget(self.notices_link)
        # Escaped: the tracked address carries "&" between its parameters.
        self.github_link = QLabel(
            f'<a href="{html.escape(GITHUB_URL)}">{html.escape(t("settings.github"))}</a>'
        )
        self.github_link.setToolTip(GITHUB_URL)
        self.github_link.setTextInteractionFlags(self.log_link.textInteractionFlags())
        self.github_link.setOpenExternalLinks(True)
        column.addWidget(self.github_link)
        column.addStretch(1)
        return page

    def _open_log_folder(self) -> None:
        """Open the logs' folder, or say under the link that it could not be opened."""
        folder = user_log_dir()
        opened = open_folder(folder)
        self.log_failed_label.setText(
            "" if opened else t("home.open_log_failed", path=path_text(folder))
        )
        self.log_failed_label.setVisible(not opened)

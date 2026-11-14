from __future__ import annotations

import logging
import math
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFontMetrics, QGuiApplication, QImage, QPalette, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from qurantext.config.paths import user_cache_dir
from qurantext.config.settings import VIDEO_PRESETS
from qurantext.core.looks import look_from_style
from qurantext.core.title_cards import (
    MAX_SECONDS,
    MIN_SECONDS,
    STYLES,
    IntroSpec,
    OutroSpec,
    missing_glyphs,
    qr_fits,
    render_title_frame,
)
from qurantext.core.tracked_link import PLATFORMS, LinkError, lookalike_host
from qurantext.core.video_common import get_audio_duration
from qurantext.gui import theme
from qurantext.gui.colors import warning_color
from qurantext.gui.i18n import ltr, plain_title, t
from qurantext.gui.prefs import KEEP_DEFAULT, Prefs
from qurantext.gui.review.episode_cards import THUMB_BOX, PartCard, fitted_size
from qurantext.gui.review.session import ReviewSession
from qurantext.gui.surahs import stored_surah_names
from qurantext.gui.widgets import make_primary
from qurantext.jobs.catalog import (
    DAMAGED,
    RENDERED,
    JobEntry,
    ayah_range,
    job_dirs_for,
    job_status,
    list_jobs,
)
from qurantext.jobs.clip_frames import clip_frame
from qurantext.jobs.episode import EpisodeError, probe_part, recitation_needs_render
from qurantext.jobs.episode_assets import (
    DEFAULT_PHRASE,
    EPISODE_SUFFIXES,
    EpisodeChoice,
    GeneratedIntro,
    GeneratedOutro,
    episode_dir_for,
    import_episode_clip,
)
from qurantext.jobs.generated_parts import (
    intro_spec_for,
    outro_spec_for,
    spec_is_empty,
    title_for,
    tracked_link_for,
)
from qurantext.jobs.project import Project, job_settings, load_project
from qurantext.jobs.project_render import default_video_path
from qurantext.jobs.thumbnails import thumbnail_image

__all__ = ["KINDS", "PHRASES", "EpisodeDialog"]

_log = logging.getLogger(__name__)

KINDS = ("none", "clip", "generated")

PHRASES = (
    DEFAULT_PHRASE,
    "بارك الله فيكم",
    "سبحانك اللهم وبحمدك، أشهد أن لا إله إلا أنت، أستغفرك وأتوب إليك",
)

PREVIEW_WIDTH = 320
PREVIEW_BOX = (320, 180)
PREVIEW_DELAY_MS = 300
_FIELDS_INDENT = 16
_SHOWN_ADDRESS = 40
_TRACKED_MIN_WIDTH = 280

_FIELDS = {
    "intro": ("name", "style", "seconds"),
    "outro": ("phrase", "link", "platform", "style", "seconds"),
}

_CODE_CHIPS = {
    "rendered": ("accent", "circle-check"),
    "render_first": ("neutral", "info"),
    "damaged": ("attention", "triangle-alert"),
}

_LINK_MESSAGES = {
    "spaces": "episode.link_invalid.spaces",
    "scheme": "episode.link_invalid",
    "slashes": "episode.link_invalid.slashes",
    "userinfo": "episode.link_invalid.userinfo",
    "host": "episode.link_invalid.host",
    "port": "episode.link_invalid.port",
}


def _resolved(path: Path | None) -> Path | None:
    return None if path is None else Path(path).expanduser().resolve()


def _length_text(seconds: float) -> str:
    minutes, rest = divmod(max(0, math.floor(seconds + 0.5)), 60)
    return f"{minutes:02d}:{rest:02d}"


def _render_length(project: Project) -> float | None:
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
    def __init__(
        self, dialog: EpisodeDialog, part: str, current: Path | None, name: str | None
    ) -> None:
        self.label = QLabel()
        self.choose = QPushButton(t("episode.choose"))
        self.remove = QPushButton(t("episode.remove"))
        self.path: Path | None = None
        self.name: str | None = None
        self.length: float | None = None
        self.frame: Path | None = None
        self.touched = False
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
                length = None
            self.set(current, length, name)
        else:
            self.set(None, None, None)

    def layout(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(theme.SP_4)
        self.label.setWordWrap(True)
        column.addWidget(self.label)
        buttons = QHBoxLayout()
        buttons.addWidget(self.choose)
        buttons.addWidget(self.remove)
        column.addLayout(buttons)
        return column

    def set_visible(self, visible: bool) -> None:
        for widget in (self.label, self.choose, self.remove):
            widget.setVisible(visible)

    def shown_name(self) -> str:
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
            name_shown = QFontMetrics(self.label.font()).elidedText(
                self.shown_name(), Qt.TextElideMode.ElideMiddle, THUMB_BOX[0]
            )
            self.label.setText(t("episode.clip", name=name_shown, length=ltr(shown)))
            self.label.setToolTip(str(path))
        self.remove.setEnabled(path is not None)
        self.frame = (
            clip_frame(path, user_cache_dir(), seconds=length) if path is not None else None
        )
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
        self._dialog._clip_chosen(self.part)
        self._dialog._show_missing()


class EpisodeDialog(QDialog):
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
        self.default_error: str | None = None
        self._recitation_lengths: dict[Path, float | None] = {}
        self._recitation_codes: dict[Path, str] = {}
        self._recitation_projects: dict[Path, Project | None] = {}
        self._card_pixmaps: dict[tuple[str, Path], QPixmap | None] = {}
        self._lecture_pixmap: QPixmap | None = None
        self._lecture_seconds = self._lecture_length()
        self._building = True
        self._missing_shown = False
        self._size = _render_size(session.project)
        self._surah_names = stored_surah_names()
        self._link_error: str | None = None
        self._host_warning: str | None = None
        self._outro_spec: OutroSpec | None = None
        self._description_link = ""
        self._qr_warning = ""
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(PREVIEW_DELAY_MS)
        self._preview_timer.timeout.connect(self.flush_previews)
        self.setWindowTitle(plain_title(t("episode.title")))

        current = session.episode
        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SP_12)
        self.total_label = QLabel()

        self.cards: dict[str, PartCard] = {
            "intro": PartCard(t("episode.intro")),
            "recitation": PartCard(t("episode.recitation")),
            "lecture": PartCard(t("episode.lecture")),
            "outro": PartCard(t("episode.outro")),
        }
        self.cards["lecture"].set_selectable(False)
        self._lecture_pixmap = self._lecture_picture()
        self.cards["recitation"].set_selectable(False)
        strip = QHBoxLayout()
        strip.setSpacing(theme.SP_8)
        for card in self.cards.values():
            strip.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)
        strip.addStretch(1)
        layout.addLayout(strip)
        for part in ("intro", "outro"):
            self.cards[part].select_requested.connect(lambda p=part: self.select_part(p))

        self._intro = _ClipRow(self, "intro", current.intro, current.intro_name)
        self.intro_label, self.intro_choose, self.intro_remove = (
            self._intro.label,
            self._intro.choose,
            self._intro.remove,
        )
        self.intro_kind = self._kind_box(_kind_of(current, "intro"), "intro")
        self.cards["intro"].add_control(self.intro_kind)
        # The Lecture card has no controls: room the height of a kind box keeps its
        # picture level with the others when no part has a clip line showing. A layout
        # of spacing alone counts as empty, so the card's gap before it is not given:
        # the room includes it.
        lecture = self.cards["lecture"]
        lecture.controls.addSpacing(self.intro_kind.sizeHint().height() + lecture.body.spacing())
        self.cards["intro"].add_control_layout(self._intro.layout())
        self._intro_original = current.intro_generated
        self.intro_fields = self._intro_fields(
            current.intro_generated or prefs.remembered_intro_generated or GeneratedIntro()
        )

        self.recitation_box = QComboBox()
        self.recitation_box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.recitation_box.setMinimumContentsLength(10)
        self._fill_recitations(job_dirs, current.recitation)
        self.recitation_box.currentIndexChanged.connect(self._update_total)
        self.cards["recitation"].add_control(self.recitation_box)

        self._outro = _ClipRow(self, "outro", current.outro, current.outro_name)
        self.outro_label, self.outro_choose, self.outro_remove = (
            self._outro.label,
            self._outro.choose,
            self._outro.remove,
        )
        self.outro_kind = self._kind_box(_kind_of(current, "outro"), "outro")
        self.cards["outro"].add_control(self.outro_kind)
        self.cards["outro"].add_control_layout(self._outro.layout())
        self._outro_original = current.outro_generated
        self.outro_fields = self._outro_fields(
            current.outro_generated or prefs.remembered_outro_generated or GeneratedOutro()
        )

        # Tab runs along the strip: a card, then its controls, then the next card (the
        # cards were parented before their controls, so Qt's own order jumps about).
        strip_order = [
            self.cards["intro"],
            self.intro_kind,
            self.intro_choose,
            self.intro_remove,
            self.recitation_box,
            self.cards["outro"],
            self.outro_kind,
            self.outro_choose,
            self.outro_remove,
        ]
        for first, second in zip(strip_order, strip_order[1:], strict=False):
            QWidget.setTabOrder(first, second)

        layout.addWidget(self.total_label)
        self.detail_pane = QWidget()
        pane = QVBoxLayout(self.detail_pane)
        pane.setContentsMargins(0, 0, 0, 0)
        pane.addWidget(self.intro_fields)
        pane.addWidget(self.outro_fields)
        layout.addWidget(self.detail_pane)
        self._selected = next(
            (part for part in ("intro", "outro") if self._kind(part) == "generated"), "intro"
        )
        self.cards[self._selected].set_selected(True)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setVisible(False)
        layout.addWidget(self.message_label)

        self.defaults_hint = QLabel(t("episode.defaults_hint"))
        self.defaults_hint.setWordWrap(True)
        self.defaults_hint.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        layout.addWidget(self.defaults_hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setDefault(True)
        make_primary(self.ok_button)
        buttons.rejected.connect(self.reject)
        self.ok_button.clicked.connect(self._keep)
        layout.addWidget(buttons)

        self._initial = {
            "intro": (self._kind("intro"), self._intro_settings()),
            "outro": (self._kind("outro"), self._outro_settings()),
        }
        self._building = False
        self._show_kinds()
        self._update_link()
        self._update_total()
        self._show_missing()
        self.flush_previews()
        (self.intro_kind if self._selected == "intro" else self.outro_kind).setFocus()

    def done(self, result: int) -> None:
        self._preview_timer.stop()
        super().done(result)

    def _kind_box(self, kind: str, part: str) -> QComboBox:
        box = QComboBox()
        for name in KINDS:
            box.addItem(t(f"episode.kind.{name}"), name)
        box.setCurrentIndex(box.findData(kind))
        box.currentIndexChanged.connect(lambda _index, p=part: self._on_kind(p))
        return box

    def _kind(self, part: str) -> str:
        box = self.intro_kind if part == "intro" else self.outro_kind
        return str(box.currentData())

    def _set_kind(self, part: str, kind: str) -> None:
        box = self.intro_kind if part == "intro" else self.outro_kind
        box.setCurrentIndex(box.findData(kind))

    def _on_kind(self, part: str | None = None) -> None:
        if self._building:
            return
        if part is not None and self._kind(part) == "generated":
            self.select_part(part)
        self._show_kinds()
        self._update_link()
        self._update_total()
        self._show_missing()
        self.flush_previews()

    def selected_part(self) -> str:
        return self._selected

    def select_part(self, part: str) -> None:
        if part not in ("intro", "outro") or part == self._selected:
            return
        self.cards[self._selected].set_selected(False)
        self._selected = part
        self.cards[part].set_selected(True)
        if not self._building:
            self._show_kinds()

    def _show_kinds(self) -> None:
        shown = False
        for part, row, fields in (
            ("intro", self._intro, self.intro_fields),
            ("outro", self._outro, self.outro_fields),
        ):
            kind = self._kind(part)
            row.set_visible(kind == "clip")
            visible = kind == "generated" and part == self._selected
            fields.setVisible(visible)
            shown = shown or visible
        self.detail_pane.setVisible(shown)
        if self.isVisible():
            self.adjustSize()

    def _style_box(self, style: str) -> QComboBox:
        box = QComboBox()
        for name in STYLES:
            box.addItem(t(f"episode.gen.style.{name}"), name)
        box.setCurrentIndex(max(0, box.findData(style)))
        box.currentIndexChanged.connect(self._on_fields)
        return box

    def _seconds_box(self, seconds: float) -> QSpinBox:
        box = QSpinBox()
        box.setRange(int(MIN_SECONDS), int(MAX_SECONDS))
        box.setValue(round(seconds))
        box.valueChanged.connect(self._on_fields)
        return box

    def _preview_label(self) -> QLabel:
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        width, height = _preview_size(self._size)
        label.setFixedSize(*_shown_size(width, height))
        return label

    def _warning_label(self) -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        label.setVisible(False)
        label.setStyleSheet(f"color: {warning_color(self.palette()).name()};")
        return label

    def _intro_fields(self, settings: GeneratedIntro) -> QWidget:
        box = QWidget()
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.intro_name_edit = QLineEdit(settings.name)
        self.intro_name_edit.textChanged.connect(self._on_fields)
        form.addRow(t("episode.gen.name"), self.intro_name_edit)
        title = title_for(self._session.project, self._surah_names)[0]
        self._title_text = title
        self.intro_title = QLabel(title or "—")
        self.intro_title.setWordWrap(True)
        form.addRow(t("episode.gen.title"), self.intro_title)
        self.intro_style = self._style_box(settings.style)
        form.addRow(t("episode.gen.style"), self.intro_style)
        self.intro_seconds = self._seconds_box(settings.seconds)
        form.addRow(t("episode.gen.seconds"), self.intro_seconds)
        self.intro_warning = self._warning_label()
        form.addRow(self.intro_warning)
        self.intro_preview = self._preview_label()
        return _beside_preview(box, form, self.intro_preview)

    def _outro_fields(self, settings: GeneratedOutro) -> QWidget:
        box = QWidget()
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.outro_phrase = QComboBox()
        for phrase in PHRASES:
            self.outro_phrase.addItem(phrase, phrase)
        self.outro_phrase.addItem(t("episode.gen.custom"), None)
        self.outro_phrase_custom = QLineEdit()
        known = self.outro_phrase.findData(settings.phrase)
        if known >= 0:
            self.outro_phrase.setCurrentIndex(known)
        else:
            self.outro_phrase.setCurrentIndex(self.outro_phrase.count() - 1)
            self.outro_phrase_custom.setText(settings.phrase)
        self.outro_phrase_custom.setVisible(known < 0)
        self.outro_phrase.currentIndexChanged.connect(self._on_phrase)
        self.outro_phrase_custom.textChanged.connect(self._on_fields)
        phrase = QVBoxLayout()
        phrase.setContentsMargins(0, 0, 0, 0)
        phrase.addWidget(self.outro_phrase)
        phrase.addWidget(self.outro_phrase_custom)
        form.addRow(t("episode.gen.phrase"), phrase)

        self.outro_link = QLineEdit(settings.link)
        self.outro_link.setPlaceholderText("example.org")
        _left_to_right(self.outro_link)
        self.outro_link.textChanged.connect(self._on_fields)
        form.addRow(t("episode.gen.link"), self.outro_link)
        self.outro_platform = QComboBox()
        for platform in PLATFORMS:
            self.outro_platform.addItem(t(f"platform.{platform}"), platform)
        self.outro_platform.setCurrentIndex(max(0, self.outro_platform.findData(settings.platform)))
        self.outro_platform.currentIndexChanged.connect(self._on_fields)
        form.addRow(t("episode.gen.platform"), self.outro_platform)

        self.outro_tracked = QLineEdit()
        self.outro_tracked.setReadOnly(True)
        _left_to_right(self.outro_tracked)
        self.outro_tracked.setMinimumWidth(_TRACKED_MIN_WIDTH)
        self.outro_tracked.setToolTip(t("episode.gen.tracked.tip"))
        self.outro_copy = QPushButton(t("episode.gen.copy"))
        self.outro_copy.setToolTip(t("episode.gen.copy.tip"))
        self.outro_copy.clicked.connect(self._copy_link)
        tracked = QHBoxLayout()
        tracked.setContentsMargins(0, 0, 0, 0)
        tracked.addWidget(self.outro_tracked, 1)
        tracked.addWidget(self.outro_copy)
        form.addRow(t("episode.gen.tracked"), tracked)
        self.outro_readable = QLabel()
        self.outro_readable.setWordWrap(True)
        self.outro_readable.setToolTip(t("episode.gen.readable.tip"))
        form.addRow(self.outro_readable)

        self.outro_style = self._style_box(settings.style)
        form.addRow(t("episode.gen.style"), self.outro_style)
        self.outro_seconds = self._seconds_box(settings.seconds)
        form.addRow(t("episode.gen.seconds"), self.outro_seconds)
        self.outro_warning = self._warning_label()
        form.addRow(self.outro_warning)
        self.outro_preview = self._preview_label()
        return _beside_preview(box, form, self.outro_preview)

    def _on_phrase(self) -> None:
        self.outro_phrase_custom.setVisible(self.outro_phrase.currentData() is None)
        self._on_fields()

    def _on_fields(self) -> None:
        if self._building:
            return
        self._update_link()
        self._update_total()
        self._preview_timer.start()

    def _intro_settings(self) -> GeneratedIntro:
        return GeneratedIntro(
            name=self.intro_name_edit.text().strip(),
            style=str(self.intro_style.currentData()),
            seconds=float(self.intro_seconds.value()),
        )

    def _outro_settings(self) -> GeneratedOutro:
        phrase = self.outro_phrase.currentData()
        if phrase is None:
            phrase = self.outro_phrase_custom.text().strip()
        return GeneratedOutro(
            phrase=str(phrase),
            link=self.outro_link.text().strip(),
            platform=str(self.outro_platform.currentData()),
            style=str(self.outro_style.currentData()),
            seconds=float(self.outro_seconds.value()),
        )

    def _generated(self, part: str) -> GeneratedIntro | GeneratedOutro | None:
        if self._kind(part) != "generated":
            return None
        settings = self._intro_settings() if part == "intro" else self._outro_settings()
        original = self._intro_original if part == "intro" else self._outro_original
        if original is not None and settings == self._initial[part][1]:
            return original
        return settings

    def _changed_fields(self, part: str) -> dict[str, object]:
        if self._kind(part) != "generated":
            return {}
        now = self._intro_settings() if part == "intro" else self._outro_settings()
        before = self._initial[part][1]
        return {
            name: getattr(now, name)
            for name in _FIELDS[part]
            if getattr(now, name) != getattr(before, name)
        }

    def _default_for(self, part: str, source: Path | None) -> tuple[object, object, object] | None:
        kind, _ = self._initial[part]
        now = self._kind(part)
        fields = self._changed_fields(part)
        remembered = (
            self._prefs.remembered_intro_generated
            if part == "intro"
            else self._prefs.remembered_outro_generated
        )
        base = remembered or (GeneratedIntro() if part == "intro" else GeneratedOutro())
        merged = replace(base, **fields)
        if now != kind:
            if now == "generated":
                return KEEP_DEFAULT, merged, KEEP_DEFAULT
            return (source if now == "clip" else None), KEEP_DEFAULT, KEEP_DEFAULT
        if now == "clip" and (self._intro if part == "intro" else self._outro).touched:
            return source, KEEP_DEFAULT, KEEP_DEFAULT
        if fields:
            return KEEP_DEFAULT, KEEP_DEFAULT, merged
        return None

    def _update_link(self) -> None:
        link = self.outro_link.text().strip()
        tracked = readable = description = ""
        self._link_error = self._host_warning = None
        settings = self._outro_settings()
        project = self._session.project
        try:
            self._outro_spec = outro_spec_for(project, settings, self._surah_names)
            if link:
                description = (
                    tracked_link_for(project, settings, self._surah_names, content="description")
                    or ""
                )
                self._host_warning = lookalike_host(link)
        except LinkError as error:
            self._link_error, self._outro_spec = error.code, None
        else:
            tracked = self._outro_spec.qr_url or ""
            readable = self._outro_spec.link_text or ""
        self._description_link = description
        self.outro_tracked.setText(tracked)
        self.outro_tracked.setCursorPosition(0)
        self.outro_copy.setEnabled(bool(description))
        self.outro_readable.setText(
            t("episode.gen.readable", link=ltr(_shortened(readable))) if readable else ""
        )
        self.outro_readable.setVisible(bool(readable))
        self.ok_button.setEnabled(not self._refused())
        self._show_warnings()

    def _empty(self, part: str) -> bool:
        if self._kind(part) != "generated":
            return False
        if part == "outro":
            return self._outro_spec is not None and spec_is_empty(self._outro_spec)
        return not (self.intro_name_edit.text().strip() or self._title_text)

    def _refused(self) -> bool:
        link_refused = bool(self._link_error) and self._kind("outro") == "generated"
        return link_refused or self._empty("intro") or self._empty("outro")

    def _copy_link(self) -> None:
        if self._description_link:
            QGuiApplication.clipboard().setText(self._description_link)

    def _show_warnings(self) -> None:
        intro_lines = []
        if self._empty("intro"):
            intro_lines.append(t("episode.gen.empty_intro"))
        if glyphs := _glyph_warning(self.intro_name_edit.text()):
            intro_lines.append(glyphs)
        outro_lines = []
        if self._link_error:
            outro_lines.append(t(_LINK_MESSAGES.get(self._link_error, "episode.link_invalid")))
        elif self._empty("outro"):
            outro_lines.append(t("episode.gen.empty_outro"))
        elif self._qr_warning and self.outro_link.text().strip():
            outro_lines.append(self._qr_warning)
        if self._host_warning:
            outro_lines.append(t(f"episode.link_warning.{self._host_warning}"))
        written = (self._outro_spec.link_text or "") if self._outro_spec is not None else ""
        if glyphs := _glyph_warning(self._outro_settings().phrase + written):
            outro_lines.append(glyphs)
        for label, lines in ((self.intro_warning, intro_lines), (self.outro_warning, outro_lines)):
            label.setText(" ".join(lines))
            label.setVisible(bool(lines))
        self._update_cards()

    def flush_previews(self) -> None:
        self._preview_timer.stop()
        look = self._session.look
        width, height = _preview_size(self._size)
        project = self._session.project
        for part, preview in (("intro", self.intro_preview), ("outro", self.outro_preview)):
            if self._kind(part) != "generated":
                continue
            spec: IntroSpec | OutroSpec
            try:
                if part == "intro":
                    spec = intro_spec_for(project, self._intro_settings(), self._surah_names)
                else:
                    spec = self._outro_spec or outro_spec_for(
                        project,
                        replace(self._outro_settings(), link=""),
                        self._surah_names,
                    )
                image = render_title_frame(spec, look, width, height, spec.seconds / 2)
            except (ValueError, OSError):
                _log.warning("The %s preview could not be drawn", part, exc_info=True)
                preview.clear()
                self.cards[part].set_icon_tile("film")
                continue
            preview.setPixmap(_pixmap(image, preview.size()))
            self.cards[part].set_thumbnail(_pixmap(image, QSize(*THUMB_BOX)))
            if part == "outro":
                self._qr_warning = self._qr_fit_warning(spec)
        self._show_warnings()

    def _qr_fit_warning(self, spec: IntroSpec | OutroSpec) -> str:
        width, height = self._size
        try:
            fits = qr_fits(spec, width, height)
        except (ValueError, OSError):
            return ""
        return "" if fits else t("episode.gen.qr_too_big", size=ltr(f"{width}×{height}"))

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
            code = self._recitation_codes[path] = _status_code(entry, lecture_video)
            box.addItem(_entry_text(entry, code), entry.project)
            if entry.status == DAMAGED:
                box.model().item(box.count() - 1).setEnabled(False)
        if current is not None and _resolved(current) not in listed:
            entry = _entry_of(current)
            code = self._recitation_codes[Path(current).expanduser().resolve()] = _status_code(
                entry, lecture_video
            )
            box.addItem(_entry_text(entry, code), current)
        index = 0
        for i in range(1, box.count()):
            if _resolved(box.itemData(i)) == _resolved(current):
                index = i
                break
        box.setCurrentIndex(index)

    def _recitation(self) -> Path | None:
        data = self.recitation_box.currentData()
        return Path(data) if data else None

    def _recitation_project(self, path: Path) -> Project | None:
        key = _resolved(path)
        assert key is not None
        if key not in self._recitation_projects:
            try:
                self._recitation_projects[key] = load_project(key)
            except (OSError, ValueError, KeyError, TypeError):
                self._recitation_projects[key] = None
        return self._recitation_projects[key]

    def _recitation_length(self, path: Path) -> float | None:
        key = _resolved(path)
        assert key is not None
        if key not in self._recitation_lengths:
            project = self._recitation_project(key)
            self._recitation_lengths[key] = (
                None if project is None else _render_length(project) or _audio_length(project)
            )
        return self._recitation_lengths[key]

    def _recitation_picture(self, path: Path) -> QPixmap | None:
        key = ("recitation", path.expanduser().resolve())
        if key not in self._card_pixmaps:
            project = self._recitation_project(path)
            pixmap: QPixmap | None = None
            if project is not None:
                base_dir = project.path.parent if project.path is not None else None
                look = look_from_style(project.style, base_dir=base_dir)
                width, height = VIDEO_PRESETS[job_settings(project).preset][:2]
                image = thumbnail_image(project, look, fitted_size((int(width), int(height))))
                pixmap = None if image is None else _pixmap(image, QSize(*THUMB_BOX))
            self._card_pixmaps[key] = pixmap
        return self._card_pixmaps[key]

    def _clip_picture(self, frame: Path) -> QPixmap | None:
        key = ("clip", frame)
        if key not in self._card_pixmaps:
            pixmap = QPixmap(str(frame))
            self._card_pixmaps[key] = None if pixmap.isNull() else pixmap
        return self._card_pixmaps[key]

    def _lecture_picture(self) -> QPixmap | None:
        image = thumbnail_image(self._session.project, self._session.look, fitted_size(self._size))
        return None if image is None else _pixmap(image, QSize(*THUMB_BOX))

    def _lecture_length(self) -> float | None:
        project = self._session.project
        if project.render is not None and not project.render_is_stale:
            length = _render_length(project)
            if length is not None:
                return length
        if self._session.duration:
            return float(self._session.duration)
        return _audio_length(project)

    def _update_total(self) -> None:
        if self._building:
            return
        lengths: list[float | None] = [self._lecture_seconds]
        for part, row in (("intro", self._intro), ("outro", self._outro)):
            kind = self._kind(part)
            if kind == "clip" and row.path is not None:
                lengths.append(row.length)
            elif kind == "generated":
                box = self.intro_seconds if part == "intro" else self.outro_seconds
                lengths.append(float(box.value()))
        recitation = self._recitation()
        if recitation is not None:
            lengths.append(self._recitation_length(recitation))
        known = sum(length for length in lengths if length is not None)
        shown = _length_text(known)
        if any(length is None for length in lengths):
            shown = f"{shown} + {t('episode.unknown')}"
        self.total_label.setText(t("episode.total", length=ltr(shown)))
        self._update_cards()

    def _update_cards(self) -> None:
        if self._building:
            return
        for part, row in (("intro", self._intro), ("outro", self._outro)):
            card = self.cards[part]
            kind = self._kind(part)
            if kind == "clip" and row.path is not None:
                card.set_length(
                    _length_text(row.length) if row.length is not None else t("episode.unknown")
                )
                frame = self._clip_picture(row.frame) if row.frame is not None else None
                if frame is not None:
                    card.set_thumbnail(frame)
                else:
                    card.set_icon_tile("film")
            elif kind == "generated":
                box = self.intro_seconds if part == "intro" else self.outro_seconds
                card.set_length(_length_text(float(box.value())))
            else:
                card.set_length("—")
                card.set_placeholder()
            if kind == "clip" and row.missing:
                card.set_chip(t("episode.chip.missing"), "attention", "triangle-alert")
            elif kind == "generated" and self._needs_attention(part):
                card.set_chip(t("episode.chip.attention"), "attention", "triangle-alert")
            else:
                card.set_chip(None)

        card = self.cards["recitation"]
        recitation = self._recitation()
        if recitation is None:
            card.set_length("—")
            card.set_placeholder()
            card.set_chip(None)
        else:
            length = self._recitation_length(recitation)
            card.set_length(_length_text(length) if length is not None else t("episode.unknown"))
            picture = self._recitation_picture(recitation)
            if picture is not None:
                card.set_thumbnail(picture)
            elif self._recitation_project(recitation) is None:
                card.set_placeholder()
            else:
                card.set_icon_tile("film")
            code = self._recitation_codes.get(recitation.expanduser().resolve(), "render_first")
            chip_kind, glyph = _CODE_CHIPS[code]
            card.set_chip(t(f"episode.{code}"), chip_kind, glyph)

        card = self.cards["lecture"]
        seconds = self._lecture_seconds
        card.set_length(_length_text(seconds) if seconds is not None else t("episode.unknown"))
        card.set_thumbnail(self._lecture_pixmap)

    def _needs_attention(self, part: str) -> bool:
        label = self.intro_warning if part == "intro" else self.outro_warning
        return bool(label.text()) or (part == "outro" and self._link_error is not None)

    def choice(self) -> EpisodeChoice:
        intro = self._intro.path if self._kind("intro") == "clip" else None
        outro = self._outro.path if self._kind("outro") == "clip" else None
        return EpisodeChoice(
            intro,
            self._recitation(),
            outro,
            intro_name=self._intro.name if intro is not None else None,
            outro_name=self._outro.name if outro is not None else None,
            intro_generated=self._generated("intro"),
            outro_generated=self._generated("outro"),
        )

    def _clip_chosen(self, part: str) -> None:
        if self._kind(part) != "clip":
            self._set_kind(part, "clip")

    def _show_message(self, text: str) -> None:
        self.message_label.setText(text)
        self.message_label.setVisible(bool(text))

    def _show_missing(self) -> None:
        if self._building:
            return
        gone = [
            row
            for row in (self._intro, self._outro)
            if row.missing and self._kind(row.part) == "clip"
        ]
        text = " ".join(
            t("episode.clip_missing", part=t(f"episode.part.{row.part}")) for row in gone
        )
        if text:
            self._show_message(text)
        elif self._missing_shown:
            self._show_message("")
        self._missing_shown = bool(text)
        self._update_cards()

    def _keep(self) -> None:
        project_path = self._session.project.path
        if project_path is None:
            self._show_message(t("session.no_file"))
            return
        if self._refused():
            return
        current = self._session.episode
        pending = self.choice()
        try:
            intro = _beside(project_path, pending.intro, current.intro)
            outro = _beside(project_path, pending.outro, current.outro)
        except (ValueError, OSError) as error:
            self._show_message(t("episode.copy_failed", reason=str(error)))
            return
        defaults = {
            "intro": self._default_for("intro", pending.intro),
            "outro": self._default_for("outro", pending.outro),
        }
        self._session.set_episode(replace(pending, intro=intro, outro=outro))
        for row, stored in ((self._intro, intro), (self._outro, outro)):
            if self._kind(row.part) == "clip":
                row.path = stored
        if any(defaults.values()):
            unchanged = (KEEP_DEFAULT, KEEP_DEFAULT, KEEP_DEFAULT)
            intro_default = defaults["intro"] or unchanged
            outro_default = defaults["outro"] or unchanged
            try:
                self._prefs.save_default_episode(
                    intro_default[0],
                    outro_default[0],
                    names=(self._intro.name, self._outro.name),
                    intro_generated=intro_default[1],
                    outro_generated=outro_default[1],
                    intro_remembered=intro_default[2],
                    outro_remembered=outro_default[2],
                )
            except (ValueError, OSError) as error:
                self.default_error = t("episode.default_failed", reason=str(error))
        self.accept()


def _kind_of(choice: EpisodeChoice, part: str) -> str:
    if choice.is_generated(part):
        return "generated"
    return "clip" if getattr(choice, part) is not None else "none"


def _render_size(project: Project) -> tuple[int, int]:
    width, height = VIDEO_PRESETS[job_settings(project).preset][:2]
    return int(width), int(height)


def _preview_size(size: tuple[int, int]) -> tuple[int, int]:
    width, height = size
    return PREVIEW_WIDTH, max(2, round(PREVIEW_WIDTH * height / width))


def _shown_size(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, PREVIEW_BOX[0] / width, PREVIEW_BOX[1] / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _pixmap(image, size: QSize) -> QPixmap:  # noqa: ANN001 — a PIL image
    rgb = image.convert("RGB")
    width, height = rgb.size
    data = rgb.tobytes()
    qimage = QImage(data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimage).scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _unclipped_labels(form: QFormLayout) -> None:
    for row in range(form.rowCount()):
        item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
        label = item.widget() if item is not None else None
        if isinstance(label, QLabel):
            label.setMinimumWidth(label.sizeHint().width())


def _beside_preview(box: QWidget, form: QFormLayout, preview: QLabel) -> QWidget:
    _unclipped_labels(form)
    row = QHBoxLayout(box)
    row.setContentsMargins(_FIELDS_INDENT, 0, 0, 0)
    row.addLayout(form, 1)
    row.addWidget(preview, 0, Qt.AlignmentFlag.AlignTop)
    return box


def _left_to_right(edit: QLineEdit) -> None:
    edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    edit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute)


def _shortened(text: str) -> str:
    return text if len(text) <= _SHOWN_ADDRESS else text[: _SHOWN_ADDRESS - 1] + "…"


def _glyph_warning(text: str) -> str:
    missing = missing_glyphs(text)
    return t("episode.gen.missing_glyphs", chars=missing) if missing else ""


def _beside(project_path: Path, chosen: Path | None, current: Path | None) -> Path | None:
    if chosen is None:
        return None
    if current is not None and _resolved(chosen) == _resolved(current):
        return current
    return import_episode_clip(project_path, chosen)


def _is_recitation(entry: JobEntry) -> bool:
    if entry.mode == "recitation":
        return True
    return (
        entry.status == DAMAGED
        and not entry.mode
        and Path(entry.project).name.endswith("_recitation.qalun.json")
    )


def _status_code(entry: JobEntry, lecture_video: Path | None) -> str:
    if entry.status == DAMAGED:
        return "damaged"
    if entry.status != RENDERED:
        return "render_first"
    try:
        project = load_project(Path(entry.project))
        needs = recitation_needs_render(project, avoid=lecture_video)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        needs = True
    return "render_first" if needs else "rendered"


def _entry_text(entry: JobEntry, code: str) -> str:
    status = t(f"episode.{code}")
    if entry.ayah_range:
        return t(
            "episode.recitation_entry",
            name=entry.name,
            range=ltr(entry.ayah_range),
            status=status,
        )
    return t("episode.recitation_entry_no_range", name=entry.name, status=status)


def _entry_of(path: Path) -> JobEntry:
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

"""The review window: listen to a job, watch its frame, and correct its timings.

This module is layout and wiring only. What an edit may do lives in
:class:`ReviewSession` (and below it ``core.timing_edit``); how each widget
draws lives in that widget (the small bars included: :class:`Banner`,
:class:`SelectionBar`, :class:`ZoomSlider`, and the :class:`LookPanel`); the slow reads of the recording
run through :class:`BackgroundJobs`. The window turns what the person does — a key, a
click, a drag the strip reports — into session calls, and after every change
brings the widgets, the toolbar and the title back in line with the session.

Keys are bound twice on purpose. ``QShortcut``\\ s make them work whichever
child has focus (a focused table would otherwise swallow ``.`` as a type-ahead
search, a focused button would take Space as a click), and
:meth:`ReviewWindow.keyPressEvent` handles the same keys when they reach the
window as plain key presses — which is how they arrive before the window is
active, as in an offscreen test. A key a shortcut consumes never becomes a key
press, so nothing runs twice.

On a layout that types other letters there (Arabic puts ج on the ``[`` key),
the punctuation keys match no shortcut and arrive as key presses of that
letter; ``keyPressEvent`` then reads which physical key it was from
:data:`SCANCODE_KEYS`, so the shortcuts stay where the person's fingers learned
them. That is only a fallback for a press nothing else took: a focused caption
editor or table still receives the letter as the text it is.
"""

from __future__ import annotations

import copy
import math
import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path

from PySide6.QtCore import QEvent, QKeyCombination, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent, QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from qurantext.config.paths import QURAN_DB_PATH
from qurantext.config.settings import VIDEO_PRESETS
from qurantext.core.coverage import speech_levels, uncovered_from_levels
from qurantext.core.waveform import Peaks, load_or_compute_peaks, peaks_path_for
from qurantext.gui import jobs as jobs_module
from qurantext.gui import theme
from qurantext.gui.files import show_in_folder
from qurantext.gui.i18n import clock, path_text, plain_title, t
from qurantext.gui.icons import set_icon
from qurantext.gui.jobs import JobOutcome
from qurantext.gui.prefs import Prefs
from qurantext.gui.review.ayah_picker import AyahPicker
from qurantext.gui.review.background import BackgroundJobs
from qurantext.gui.review.banner import Banner
from qurantext.gui.review.episode_dialog import EpisodeDialog
from qurantext.gui.review.export_dialog import ExportDialog
from qurantext.gui.review.frame_view import FrameView
from qurantext.gui.review.look_panel import LookPanel, look_warning_text
from qurantext.gui.review.player import RATES, Player, create_player
from qurantext.gui.review.segment_list import SegmentList
from qurantext.gui.review.selection_bar import NUDGE_S, SelectionBar
from qurantext.gui.review.session import ReviewSession, WordRef
from qurantext.gui.review.viewport import Viewport
from qurantext.gui.review.waveform_view import WaveformView
from qurantext.gui.review.word_strip import WordStrip
from qurantext.gui.review.zoom_slider import ZoomSlider
from qurantext.gui.surahs import (
    fill_studied_surah_box,
    select_studied_surah,
    stored_surah_names,
    surah_label,
)
from qurantext.gui.widgets import make_primary
from qurantext.jobs.project import Project, job_settings
from qurantext.utils.progress import CancelToken, ProgressEvent

__all__ = ["SCANCODE_KEYS", "ReviewWindow", "render_finished_text"]

#: The physical key behind each layout-dependent shortcut, by the code Qt reports
#: for it (``nativeScanCode``; on macOS ``nativeVirtualKey``, the scan code is 0).
#: Only the keys whose character moves between layouts: the letters and arrows
#: the other shortcuts use are found by Qt itself (Ctrl+Z, Ctrl+Shift+Z and
#: Ctrl+S through its Latin fallback for keys held with Ctrl).
SCANCODE_KEYS: dict[str, dict[int, Qt.Key]] = {
    # X11 and Wayland report XKB keycodes, which are the Linux evdev codes plus 8
    # (linux/input-event-codes.h: KEY_LEFTBRACE 26, KEY_RIGHTBRACE 27,
    # KEY_COMMA 51, KEY_DOT 52; xkeyboard-config keycodes/evdev: <AD11> = 34,
    # <AD12> = 35, <AB08> = 59, <AB09> = 60).
    "xkb": {
        34: Qt.Key.Key_BracketLeft,
        35: Qt.Key.Key_BracketRight,
        59: Qt.Key.Key_Comma,
        60: Qt.Key.Key_Period,
    },
    # Windows reports the PS/2 scan code set 1 make code (Microsoft's "Keyboard
    # Scan Code Specification"; bits 16-23 of WM_KEYDOWN's lParam): [ 0x1A,
    # ] 0x1B, , 0x33, . 0x34.
    "windows": {
        0x1A: Qt.Key.Key_BracketLeft,
        0x1B: Qt.Key.Key_BracketRight,
        0x33: Qt.Key.Key_Comma,
        0x34: Qt.Key.Key_Period,
    },
    # macOS reports the virtual key code (HIToolbox Events.h: kVK_ANSI_LeftBracket
    # 0x21, kVK_ANSI_RightBracket 0x1E, kVK_ANSI_Comma 0x2B, kVK_ANSI_Period 0x2F).
    "macos": {
        0x21: Qt.Key.Key_BracketLeft,
        0x1E: Qt.Key.Key_BracketRight,
        0x2B: Qt.Key.Key_Comma,
        0x2F: Qt.Key.Key_Period,
    },
}

#: The playhead poll while playing: often enough that the highlight looks continuous.
_TICK_MS = 16
#: How long after the last edit the coverage check re-runs.
_COVERAGE_DEBOUNCE_MS = 1000
#: The nudge step with Shift held, in seconds (the plain step is ``NUDGE_S``).
_FINE_NUDGE_S = 0.01
#: The timeline window shown on open, before the person zooms.
_DEFAULT_SPAN_S = 20.0
#: The least height the segment list keeps, in pixels: its header and a few rows,
#: so a small window shrinks the frame above it instead of the rows away.
_LIST_MIN_HEIGHT = 150
#: The Look panel's width, in pixels: three palette swatches with their names.
_LOOK_PANEL_WIDTH = 260
#: What the render's progress bar says during each of the episode's steps.
_EPISODE_PROGRESS_KEYS = {
    "episode_lecture": "render.running_lecture",
    "episode_intro": "render.running_intro",
    "episode_outro": "render.running_outro",
    "episode_recitation": "render.running_recitation",
    "episode_join": "render.running_join",
}


def _platform_family() -> str:
    """Which of :data:`SCANCODE_KEYS`' tables this machine's key codes come from.

    Every Unix other than macOS runs Qt on X11 or Wayland, both through XKB.
    """
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return "xkb"


def _physical_key(event: QKeyEvent) -> Qt.Key | None:
    """The layout-dependent shortcut key *event*'s physical key is, if it is one."""
    platform = _platform_family()
    code = event.nativeVirtualKey() if platform == "macos" else event.nativeScanCode()
    return SCANCODE_KEYS[platform].get(code)


def _is_portrait(project: Project) -> bool:
    """Whether the job's video is taller than wide: the job's preset, else its last render.

    The preset is what the next render makes, so it wins over the size of a
    render made before the job was re-run with another one. A project that
    never recorded a preset falls back to the size it was last rendered at.
    """
    chosen = project.export.get("preset")
    if isinstance(chosen, str) and chosen in VIDEO_PRESETS:
        width, height = VIDEO_PRESETS[chosen][:2]
        return height >= width
    render = project.render or {}
    width, height = render.get("width"), render.get("height")
    if not (isinstance(width, int) and isinstance(height, int)):
        width, height = VIDEO_PRESETS[job_settings(project).preset][:2]
    return height >= width


def _card_number(card: dict, key: str) -> int | None:
    """A card's surah or ayah number when it has a usable one (a preamble card has none)."""
    value = card.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _content_end(project: Project) -> float:
    """The latest time any card or caption reaches: a timeline length before the audio is read."""
    ends = [float(card.get("end_time") or 0.0) for card in project.cards]
    ends += [float(cue.end) for cue in project.captions]
    return max(ends, default=0.0)


class ReviewWindow(QMainWindow):
    """One project under review: toolbar, warnings, frame, look, timeline, segment list."""

    #: The project file was written; carries its path.
    saved = Signal(object)
    #: The person asked to export subtitles (handled by whoever opened the window).
    export_requested = Signal()
    #: The person asked to render with the corrections.
    render_requested = Signal()
    #: A close was accepted and the window stopped everything it ran; whoever
    #: opened it should let it go (the next review loads the project afresh).
    closed = Signal()

    def __init__(
        self,
        project: Project,
        *,
        player: Player | None = None,
        prefs: Prefs | None = None,
        parent: QWidget | None = None,
        db_path: Path = QURAN_DB_PATH,
    ) -> None:
        super().__init__(parent)
        self.session = ReviewSession(project)
        #: The Quran store a hand-made card's text is read from.
        self._db_path = db_path
        #: Where "Use for new videos" keeps the default look.
        self._prefs = prefs if prefs is not None else Prefs()
        self.player = player if player is not None else create_player(self)
        self.viewport = Viewport(self)
        self._jobs = BackgroundJobs(self)
        self._audio = Path(project.audio)
        #: The recording's speech levels, decoded once; coverage re-checks read these.
        self._levels: tuple[list[float], list[float], float] | None = None
        self._reading_levels = False
        self._reading_peaks = False
        #: A measured recording length has sized the timeline (so the zoom is the person's now).
        self._measured = False
        #: The segment the list last highlighted, so a tick only moves it on a change.
        self._highlighted: tuple[str, int] | None = None
        self._closed = False
        #: The session revision the views last caught up with (see ``_after_caption_edit``).
        self._seen_revision = self.session.revision
        #: How many cards and captions there were when the views last caught up
        #: (see ``_drop_stale_selection``).
        self._seen_counts = self._segment_counts()
        #: Whether a render job is running: gates the editing actions while it is.
        self._rendering = False
        self._render_cancel: CancelToken | None = None
        #: The deep copy handed to the render job; read back into the live
        #: project's ``render`` once the job finishes (see ``_on_render_finished``).
        self._render_project_copy: Project | None = None
        #: The segment list's edit triggers, saved while a render disables them.
        self._segment_list_edit_triggers: QAbstractItemView.EditTrigger | None = None
        #: The progress bar's sentence for the running render's current step.
        self._render_progress_key = "render.running"

        self._build()
        self._wire()
        self._bind_keys()
        self._set_tips()

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._coverage_timer = QTimer(self)
        self._coverage_timer.setSingleShot(True)
        self._coverage_timer.setInterval(_COVERAGE_DEBOUNCE_MS)
        self._coverage_timer.timeout.connect(self._recheck_coverage)

        self._set_duration(_content_end(project), measured=False)
        if not self.player.available:
            # One short line in the strip; the technical reason is on the button.
            self.play_button.setEnabled(False)
            self.play_button.setToolTip(self.player.reason)
            self.warnings.add_notice(t("player.unavailable_short"))
        if self._audio.is_file():
            self.player.load(self._audio)
            self._start_reads()
        else:
            self.waveform.set_missing()
            self.warnings.add_notice(t("review.audio_missing", path=path_text(self._audio)))
        # Connected now: a chosen image that has gone missing is said on opening.
        self.look_panel.announce()
        self._sync_state()
        self._show_time(self.player.position(), force=True)

    # -- layout ---------------------------------------------------------------

    def _build(self) -> None:
        central = QWidget(self)
        column = QVBoxLayout(central)

        toolbar = QHBoxLayout()
        self.save_button = QPushButton(t("review.save"))
        self.undo_button = QPushButton(t("review.undo"))
        self.redo_button = QPushButton(t("review.redo"))
        self.reviewed_button = QPushButton(t("review.mark_reviewed"))
        self.remove_button = QPushButton(t("review.remove"))
        self.export_button = QPushButton(t("review.export"))
        self.render_button = QPushButton(t("review.render"))
        self.render_button.setToolTip(t("review.render.tip"))
        # A lecture's episode: what plays around it, and whether anything does.
        self.episode_button = QPushButton(t("review.episode"))
        self.episode_button.setToolTip(t("review.episode.tip"))
        self.episode_label = QLabel(t("review.episode_on"))
        self.episode_label.setVisible(False)
        self.render_progress = QProgressBar()
        self.render_progress.setRange(0, 100)
        self.render_progress.setFixedWidth(140)
        self.render_progress.setVisible(False)
        self.render_cancel_button = QPushButton(t("render.cancel"))
        self.render_cancel_button.setVisible(False)
        for button, name in (
            (self.save_button, "save"),
            (self.undo_button, "undo-2"),
            (self.redo_button, "redo-2"),
            (self.reviewed_button, "circle-check"),
            (self.remove_button, "trash"),
            (self.export_button, "download"),
            (self.episode_button, "sparkles"),
        ):
            set_icon(button, name)
        # On the accent fill, in the colour the label beside it is drawn in.
        set_icon(self.render_button, "film", role="on_accent")
        make_primary(self.render_button)
        buttons = (
            self.save_button,
            self.undo_button,
            self.redo_button,
            self.reviewed_button,
            self.remove_button,
        )
        for button in buttons:
            toolbar.addWidget(button)
        # A lecture's cards keep to one surah; which one is the person's to say.
        self.studied_surah_label = QLabel(t("review.studied_surah"))
        self.studied_surah_box = QComboBox()
        self.studied_surah_box.setToolTip(t("review.studied_surah.tip"))
        self._surah_names = self._known_surah_names()
        fill_studied_surah_box(self.studied_surah_box, self._surah_names)
        select_studied_surah(self.studied_surah_box, self.session.studied_surah)
        self.studied_surah_label.setBuddy(self.studied_surah_box)
        lecture = str(self.session.project.mode).lower() == "lecture"
        self.studied_surah_label.setVisible(lecture)
        self.studied_surah_box.setVisible(lecture)
        self.episode_button.setVisible(lecture)
        toolbar.addSpacing(12)
        toolbar.addWidget(self.studied_surah_label)
        toolbar.addWidget(self.studied_surah_box)
        toolbar.addStretch(1)
        toolbar.addWidget(self.export_button)
        toolbar.addWidget(self.episode_label)
        toolbar.addWidget(self.episode_button)
        toolbar.addWidget(self.render_button)
        toolbar.addWidget(self.render_progress)
        toolbar.addWidget(self.render_cancel_button)
        column.addLayout(toolbar)

        self.warnings = Banner()
        column.addWidget(self.warnings)

        body = QWidget()
        body_row = QHBoxLayout(body)
        body_row.setContentsMargins(0, 0, 0, 0)
        self.frame_view = FrameView(self.session, portrait=_is_portrait(self.session.project))
        body_row.addWidget(self.frame_view, 0, Qt.AlignmentFlag.AlignTop)
        body_row.addWidget(self._build_look_panel())
        body_row.addLayout(self._build_timeline(), 1)

        self.segment_list = SegmentList(self.session)
        self.segment_list.setMinimumHeight(_LIST_MIN_HEIGHT)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(body)
        splitter.addWidget(self.segment_list)
        # Neither pane can be dragged away, and extra height goes to the list's rows.
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self._splitter = splitter
        column.addWidget(splitter, 1)

        self.hint_label = QLabel()
        self.hint_label.setToolTip(t("review.shortcuts"))
        # Takes whatever width the bar has, and elides to it (see _elide_hint).
        self.hint_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.hint_label.installEventFilter(self)
        self.statusBar().addWidget(self.hint_label, 1)
        self.setCentralWidget(central)

    def _build_look_panel(self) -> QScrollArea:
        """The Look panel beside the frame it changes, scrolling when the window is short."""
        self.look_panel = LookPanel(
            self.session,
            prefs=self._prefs,
            frame_size=(self.frame_view.sizeHint().width(), self.frame_view.sizeHint().height()),
            reserve_caption_band=self.session.frame_inputs(0.0)[2],
        )
        scroll = QScrollArea()
        scroll.setWidget(self.look_panel)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(_LOOK_PANEL_WIDTH)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.look_scroll = scroll
        return scroll

    def _build_timeline(self) -> QVBoxLayout:
        right = QVBoxLayout()

        zoom_row = QHBoxLayout()
        self.zoom_label = QLabel(t("review.zoom"))
        self.zoom_slider = ZoomSlider(self.viewport, self.player.position)
        self.zoom_label.setBuddy(self.zoom_slider)
        zoom_row.addWidget(self.zoom_label)
        zoom_row.addWidget(self.zoom_slider, 1)
        right.addLayout(zoom_row)

        self.waveform = WaveformView(self.viewport)
        self.strip = WordStrip(self.viewport, self.session)
        right.addWidget(self.waveform)
        right.addWidget(self.strip)

        transport = QHBoxLayout()
        self.play_button = QPushButton(t("review.play"))
        set_icon(self.play_button, "play")
        # The transport row mirrors (Play leads on the right in Arabic); the
        # clock is a number and reads left to right, as numbers do here.
        self.time_label = QLabel(clock(0.0))
        self.time_label.setFont(theme.font("clock"))
        self.time_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.rate_combo = QComboBox()
        for rate in RATES:
            self.rate_combo.addItem(t("review.rate", rate=rate), rate)
        # Detection misses the ayah a teacher talks about without reciting it; the
        # person shows it by hand from the playhead on, so the button sits by the
        # playhead's own controls (and off the toolbar, which a render fills).
        self.show_ayah_button = QPushButton(t("review.show_ayah"))
        self.show_ayah_button.setToolTip(t("review.show_ayah.tip"))
        self.show_ayah_button.setVisible(str(self.session.project.mode).lower() == "lecture")
        transport.addWidget(self.play_button)
        transport.addWidget(self.time_label)
        transport.addWidget(self.rate_combo)
        transport.addSpacing(12)
        transport.addWidget(self.show_ayah_button)
        transport.addStretch(1)
        right.addLayout(transport)

        self.selection_bar = SelectionBar()
        right.addWidget(self.selection_bar)
        right.addStretch(1)
        return right

    def _wire(self) -> None:
        self.save_button.clicked.connect(self.save)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.reviewed_button.clicked.connect(self._mark_reviewed)
        self.remove_button.clicked.connect(self._remove_selected)
        self.export_button.clicked.connect(self.export_requested)
        self.render_button.clicked.connect(self.render_requested)
        self.render_cancel_button.clicked.connect(self._cancel_render)
        self.episode_button.clicked.connect(self._open_episode_dialog)
        self.export_requested.connect(self._open_export_dialog)
        self.render_requested.connect(self._start_render)
        self.warnings.jump_requested.connect(self.seek)
        self.waveform.seek_requested.connect(self.seek)
        self.strip.seek_requested.connect(self.seek)
        self.strip.selection_changed.connect(self._show_selection)
        self.strip.edited.connect(self._after_edit)
        self.segment_list.seek_requested.connect(self.seek)
        self.segment_list.card_ayah_requested.connect(self._change_card_ayah)
        self.show_ayah_button.clicked.connect(self._show_ayah_from_here)
        # Remove is offered only while a row is selected. Only the button: a full _sync_state
        # here would mark a removal as seen before _drop_stale_selection could act on it.
        self.segment_list.itemSelectionChanged.connect(self._update_remove_button)
        # Connected after the list's own handler, so the caption text is already in the session.
        self.segment_list.itemChanged.connect(self._after_caption_edit)
        self.play_button.clicked.connect(self.toggle_play)
        self.rate_combo.currentIndexChanged.connect(self._on_rate)
        self.studied_surah_box.currentIndexChanged.connect(self._on_studied_surah)
        self.selection_bar.nudge_requested.connect(self._nudge)
        self.selection_bar.snap_requested.connect(self._snap_to_playhead)
        self.player.playing_changed.connect(self._on_playing_changed)
        self.player.duration_changed.connect(self._set_duration)
        self.player.error.connect(self.warnings.add_notice)
        self.look_panel.look_changed.connect(self._after_look_change)
        self.look_panel.notice.connect(self.warnings.add_notice)
        self.look_panel.look_notices.connect(self.warnings.set_look_notices)
        self.look_panel.message.connect(lambda text: self.statusBar().showMessage(text, 4000))

    def _bind_keys(self) -> None:
        bindings: list[tuple[str, Callable[[], None]]] = [
            ("Space", self.toggle_play),
            # The timeline runs right to left, so the arrows follow it on
            # screen: Left goes to the next (later) word, Right to the previous.
            ("Left", partial(self._step, 1)),
            ("Right", partial(self._step, -1)),
            ("[", self._set_start_at_playhead),
            ("]", self._set_end_at_playhead),
            # The nudges match their keys' < and > to the screen: "," moves the
            # edge left, which on the right-to-left timeline is later, and "."
            # moves it right, earlier.
            (",", partial(self._nudge, NUDGE_S)),
            (".", partial(self._nudge, -NUDGE_S)),
            ("Shift+,", partial(self._nudge, _FINE_NUDGE_S)),
            ("Shift+.", partial(self._nudge, -_FINE_NUDGE_S)),
            ("Ctrl+Z", self.undo),
            ("Ctrl+Shift+Z", self.redo),
            ("Ctrl+S", self.save),
        ]
        self._keys: dict[str, Callable[[], None]] = {}
        for text, action in bindings:
            sequence = QKeySequence(text)
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(action)
            self._keys[sequence.toString()] = action
        # A real Shift+. on a US layout arrives as Key_Greater (Shift+, as Key_Less).
        # The shortcut map already tries the unshifted key, so these are key-press
        # aliases only: registering them as shortcuts too would make the press
        # ambiguous. Other layouts put these characters elsewhere and may differ.
        self._keys["Shift+>"] = self._keys["Shift+."]
        self._keys["Shift+<"] = self._keys["Shift+,"]

    def _set_tips(self) -> None:
        """Say each button's shortcut on the button itself, where a person hovers to learn it."""
        native = QKeySequence.SequenceFormat.NativeText
        tips = (
            (self.save_button, "Ctrl+S"),
            (self.undo_button, "Ctrl+Z"),
            (self.redo_button, "Ctrl+Shift+Z"),
        )
        for button, keys in tips:
            shown = QKeySequence(keys).toString(native)
            button.setToolTip(t("review.tip", action=button.text(), keys=shown))
        self.play_button.setToolTip(self._play_tip())
        bar = self.selection_bar
        bar.minus_button.setToolTip(t("review.tip_fine", action=bar.minus_button.text(), keys="."))
        bar.plus_button.setToolTip(t("review.tip_fine", action=bar.plus_button.text(), keys=","))

    def _play_tip(self) -> str:
        """The play button's tip for its current action.

        Space is named from the table, not by Qt: Qt's own Arabic translation
        leaves that key's name in English.
        """
        return t("review.tip", action=self.play_button.text(), keys=t("review.key_space"))

    def _elide_hint(self) -> None:
        """Fit the shortcut line to the status bar; the tooltip keeps the whole of it."""
        full = t("review.shortcuts")
        metrics = self.hint_label.fontMetrics()
        self.hint_label.setText(
            metrics.elidedText(full, Qt.TextElideMode.ElideRight, self.hint_label.width())
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if watched is self.hint_label and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._elide_hint()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        combination = event.keyCombination()
        modifiers = combination.keyboardModifiers() & ~Qt.KeyboardModifier.KeypadModifier
        text = QKeySequence(QKeyCombination(modifiers, combination.key())).toString()
        action = self._keys.get(text)
        if action is None:
            action = self._layout_action(event, modifiers)
        if action is None:
            super().keyPressEvent(event)
            return
        action()
        event.accept()

    def _layout_action(
        self, event: QKeyEvent, modifiers: Qt.KeyboardModifier
    ) -> Callable[[], None] | None:
        """The shortcut on the physical key of a press that typed a non-Latin letter.

        Only for a press that typed something outside ASCII: an ASCII character a
        Latin layout puts on one of these keys (``;`` on AZERTY's ``,`` key) keeps
        meaning itself, while a non-ASCII one (German ``ü`` on the ``[`` key) is
        read by its place like an Arabic letter. With Ctrl, Alt or Meta held Qt
        already finds the Latin key, so only a plain or shifted press is read.
        """
        typed = event.text()
        if not typed or typed.isascii():
            return None
        if modifiers & ~Qt.KeyboardModifier.ShiftModifier:
            return None
        key = _physical_key(event)
        if key is None:
            return None
        return self._keys.get(QKeySequence(QKeyCombination(modifiers, key)).toString())

    # -- playback -------------------------------------------------------------

    def toggle_play(self) -> None:
        if self.player.available:
            self.player.toggle()

    def seek(self, seconds: float) -> None:
        """Move the playhead to *seconds* and bring every view there at once."""
        self.player.seek(seconds)
        self._show_time(seconds, force=True)

    def _tick(self) -> None:
        self._show_time(self.player.position())

    def _show_time(self, seconds: float, *, force: bool = False) -> None:
        self.waveform.set_playhead(seconds)
        self.strip.set_playhead(seconds)
        self.viewport.follow(seconds)
        self.time_label.setText(clock(seconds))
        self._highlight_segment(seconds, force=force)
        self.frame_view.show_at(seconds, force=force)

    def _highlight_segment(self, seconds: float, *, force: bool) -> None:
        """Move the list's current row to the segment at *seconds*, but only on a change.

        Moving the current cell closes an open editor, so while the person is
        correcting a caption the list is left alone; it catches up on the
        first tick after the edit ends.
        """
        if self.segment_list.state() == QAbstractItemView.State.EditingState:
            return
        segment = self.segment_list.segment_at(seconds)
        if segment == self._highlighted and not force:
            return
        self._highlighted = segment
        self.segment_list.highlight_at(seconds)

    def _on_playing_changed(self, playing: bool) -> None:
        self.play_button.setText(t("review.pause") if playing else t("review.play"))
        set_icon(self.play_button, "pause" if playing else "play")
        if self.player.available:
            # The tip names the button's action, which just changed; without a
            # player the tip is the reason instead, and stays so.
            self.play_button.setToolTip(self._play_tip())
        if playing:
            self._timer.start()
        else:
            self._timer.stop()
            self._show_time(self.player.position(), force=True)

    def _on_rate(self, index: int) -> None:
        self.player.set_rate(float(self.rate_combo.itemData(index)))

    # -- timeline -------------------------------------------------------------

    def _set_duration(self, duration: float, *, measured: bool = True) -> None:
        """Size the timeline to *duration* seconds, keeping the view near the default span.

        Only a *measured* length (the player's, or the decoded peaks') bounds
        a ripple; the content's own extent, used until one arrives, does not.
        """
        duration = float(duration)
        if duration <= 0:
            return
        if measured:
            self.session.duration = duration
        # Once a measured length has sized the view, a later one (peaks after the
        # player, say) only re-clamps it: the zoom is the person's by then.
        choose_span = not self._measured
        self._measured = self._measured or measured
        if math.isclose(duration, self.viewport.duration):
            return
        self.viewport.set_duration(duration)
        if choose_span:
            self.viewport.set_window(self.viewport.start, min(_DEFAULT_SPAN_S, duration))

    # -- editing --------------------------------------------------------------

    def _step(self, direction: int) -> None:
        ref = self.session.step(self.strip.selected, direction)
        if ref is None:
            return
        self.strip.select(ref)
        self.seek(self.session.word(ref).start)

    def _set_start_at_playhead(self) -> None:
        if self._rendering:
            return
        ref = self.strip.selected
        if ref is not None:
            self.session.retime(ref, start=self.player.position())
            self._after_edit()

    def _set_end_at_playhead(self) -> None:
        if self._rendering:
            return
        ref = self.strip.selected
        if ref is not None:
            self.session.retime(ref, end=self.player.position())
            self._after_edit()

    def _nudge(self, delta: float) -> None:
        """Move the selected word's last-grabbed edge (its end, by default) by *delta* seconds."""
        if self._rendering:
            return
        ref = self.strip.selected
        if ref is None:
            return
        word = self.session.word(ref)
        if self.strip.last_edge == "start":
            self.session.retime(ref, start=word.start + delta)
        else:
            self.session.retime(ref, end=word.end + delta)
        self._after_edit()

    def _snap_to_playhead(self) -> None:
        """Move whichever edge of the selected word is nearer the playhead onto it."""
        if self._rendering:
            return
        ref = self.strip.selected
        if ref is None:
            return
        word = self.session.word(ref)
        now = self.player.position()
        if abs(now - word.start) <= abs(now - word.end):
            self.session.retime(ref, start=now)
        else:
            self.session.retime(ref, end=now)
        self._after_edit()

    def _mark_reviewed(self) -> None:
        if self._rendering:
            return
        self.session.mark_reviewed()
        self._after_edit()

    def _remove_selected(self) -> None:
        """Remove the selected row(s); says so in the status bar if none is selected."""
        if self._rendering:
            return
        if not self.segment_list.remove_selected():
            self.statusBar().showMessage(t("review.remove_none"), 4000)
            return
        # The list already rebuilt itself; bring the rest of the window in line.
        self._drop_stale_selection()
        self.strip.refresh()
        self._highlight_segment(self.player.position(), force=True)
        self._sync_state()
        self.frame_view.show_at(self.player.position(), force=True)
        if self._levels is not None:
            self._coverage_timer.start()

    def _show_ayah_from_here(self) -> None:
        """Ask which ayat to show from the playhead on, and place that card.

        The picker opens on the card the frame shows there (its surah and
        range), which is what the person is looking at when they decide it is
        wrong or missing. Before the first card it opens on the lecture's
        studied surah, chosen or else guessed, at its first ayah: the ayah a
        teacher goes back to is most often in the surah being studied. Cancel
        changes nothing.
        """
        if self._rendering:
            return
        at = self.player.position()
        on_screen = self.session.frame_inputs(at)[0] or {}
        surah = _card_number(on_screen, "surah_num")
        first = _card_number(on_screen, "from_ayah") if surah else None
        last = _card_number(on_screen, "to_ayah") if first else None
        choice = self._ask_ayat(surah or self._studied_surah_guess(), first or 1, last)
        if choice is not None:
            self._edit_card(
                t("review.show_ayah"),
                lambda: self.session.insert_manual_card(at, *choice, db_path=self._db_path),
            )

    def _change_card_ayah(self, index: int) -> None:
        """Ask which ayat card *index* shows, keeping its times; Cancel changes nothing."""
        if self._rendering or not 0 <= index < len(self.session.project.cards):
            return
        card = self.session.project.cards[index]
        surah = _card_number(card, "surah_num")
        first = _card_number(card, "from_ayah") if surah else None
        last = _card_number(card, "to_ayah") if first else None
        choice = self._ask_ayat(surah or self._studied_surah_guess(), first or 1, last)
        if choice is not None:
            self._edit_card(
                t("segments.change_ayah"),
                lambda: self._changed_card_index(index, choice),
            )

    def _changed_card_index(self, index: int, choice: tuple[int, int, int]) -> int:
        self.session.change_card_ayah(index, *choice, db_path=self._db_path)
        return index

    def _studied_surah_guess(self) -> int:
        """The surah chosen for the cards, else the one guessed for them, else al-Fatiha."""
        return self.session.studied_surah or self.session.guessed_studied_surah or 1

    def _ask_ayat(self, surah: int, first: int, last: int | None) -> tuple[int, int, int] | None:
        """The ``(surah, from_ayah, to_ayah)`` the person picks, or None when they cancel.

        Playback pauses while the picker is open, so the frame redrawn after
        OK is still the moment the card was placed at, not a later one past it.
        """
        if self.player.is_playing():
            self.player.pause()
        picker = AyahPicker(self, surah=surah, from_ayah=first, to_ayah=last, db_path=self._db_path)
        try:
            if picker.exec() != QDialog.DialogCode.Accepted:
                return None
            return picker.choice()
        finally:
            picker.deleteLater()

    def _edit_card(self, title: str, edit: Callable[[], int | None]) -> None:
        """Run a card edit, then bring every view along and show the card in the list.

        The session raises one ``ValueError``, in the window's language, for a
        reference the store does not have and for a store it cannot read;
        nothing changed then, so there is nothing to redraw, only the reason
        to say.
        """
        try:
            index = edit()
        except ValueError as error:
            QMessageBox.warning(self, plain_title(title), str(error))
            return
        self._after_edit()
        if index is not None:
            # In a lecture the playhead's row is a caption, listed after every card:
            # without this the card just placed or changed may be out of sight.
            self.segment_list.show_card(index)

    def undo(self) -> None:
        if self._rendering:
            return
        if self.session.undo():
            self._after_edit()

    def redo(self) -> None:
        if self._rendering:
            return
        if self.session.redo():
            self._after_edit()

    def _after_caption_edit(self, _item: object) -> None:
        if self.session.revision != self._seen_revision:
            # Not refreshing the list: it is mid-signal for the edited cell.
            self._after_edit(refresh_list=False)

    def _after_edit(self, *, refresh_list: bool = True) -> None:
        """Bring every view back in line with the session after any change."""
        self._drop_stale_selection()
        self.strip.refresh()
        if refresh_list:
            self.segment_list.refresh()
            # The rebuilt rows carry no playhead mark yet.
            self._highlight_segment(self.player.position(), force=True)
        self._sync_state()
        # Undo, redo and discard may have changed the look too; a no-op when not.
        self.look_panel.refresh()
        self.frame_view.show_at(self.player.position(), force=True)
        if self._levels is not None:
            self._coverage_timer.start()

    def _after_look_change(self) -> None:
        """The look changed from its panel: redraw the frame, and bring undo and the title along.

        Lighter than ``_after_edit``: no word, card or caption moved, so the
        strip, the list and the coverage check stay as they are.
        """
        self._sync_state()
        self.frame_view.show_at(self.player.position(), force=True)

    def _known_surah_names(self) -> dict[int, str]:
        """Surah names for the picker: the store's, else whatever the cards carry."""
        names = stored_surah_names()
        for card in self.session.project.cards:
            num, name = card.get("surah_num"), card.get("surah_name")
            if isinstance(num, int) and name:
                names.setdefault(num, str(name))
        return names

    def _on_studied_surah(self) -> None:
        """The surah on the cards changed: one undoable edit, and the frame redrawn."""
        self.session.set_studied_surah(self.studied_surah_box.currentData())
        self._after_look_change()

    def _segment_counts(self) -> tuple[int, int]:
        project = self.session.project
        return len(project.cards), len(project.captions)

    def _drop_stale_selection(self) -> None:
        """Clear the strip's selection when the last change added or removed a segment.

        A :class:`WordRef` is a position. Once a card or caption before it is
        removed (or an undo puts one back) the same position names a
        different word, which the strip would go on showing as selected and
        a nudge would then retime. Only a change in the segment counts can do
        that, so an ordinary retime keeps its selection.
        """
        if self._segment_counts() != self._seen_counts:
            self.strip.select(None)
            self._show_selection(None)

    def _sync_state(self) -> None:
        session = self.session
        self._seen_revision = session.revision
        self._seen_counts = self._segment_counts()
        # A render reads a snapshot taken when it started, but undo, save and the
        # timing edits wait for it to finish all the same. The Look panel stays
        # open (a look changed meanwhile only makes the render stale), so a look
        # change made during a render is undone once the render is done.
        editable = not self._rendering
        self.save_button.setEnabled(session.dirty and editable)
        self.undo_button.setEnabled(session.can_undo and editable)
        self.redo_button.setEnabled(session.can_redo and editable)
        self._update_remove_button()
        self.reviewed_button.setEnabled(
            session.project.review.get("state") != "reviewed" and editable
        )
        self.show_ayah_button.setEnabled(editable)
        title = t("review.title", name=self._audio.stem)
        self.setWindowTitle(plain_title(f"{title} *" if session.dirty else title))
        self._show_selection(self.strip.selected)
        self._show_studied_surah()
        self.episode_label.setVisible(self._is_lecture() and not session.episode.is_empty)

    def _is_lecture(self) -> bool:
        return str(self.session.project.mode).lower() == "lecture"

    def _show_studied_surah(self) -> None:
        """Bring the picker back in line after undo, redo, discard or save, and say
        when the chosen surah has no card (the video then shows only its title card)."""
        blocked = self.studied_surah_box.blockSignals(True)
        try:
            select_studied_surah(self.studied_surah_box, self.session.studied_surah)
        finally:
            self.studied_surah_box.blockSignals(blocked)
        missing = self.session.missing_studied_surah
        self.warnings.set_surah_notice(
            t("review.studied_surah_missing", surah=surah_label(missing, self._surah_names))
            if missing is not None
            else None
        )

    def _update_remove_button(self) -> None:
        """Offer Remove only for a selected row, and never during a render."""
        self.remove_button.setEnabled(
            not self._rendering and bool(self.segment_list.selectedIndexes())
        )

    def _show_selection(self, ref: WordRef | None) -> None:
        self.selection_bar.show_word(self.session.word(ref) if ref is not None else None)

    # -- export and render ------------------------------------------------------

    def _open_export_dialog(self) -> None:
        if self._rendering:
            return
        self._make_export_dialog().exec()
        # The dialog may have saved the session on our behalf; catch up either way.
        self._sync_state()

    def _make_export_dialog(self) -> ExportDialog:
        """The Export dialog for this session; a save it makes is announced as ours."""
        dialog = ExportDialog(self.session, self)
        dialog.saved.connect(self.saved)
        return dialog

    def _open_episode_dialog(self) -> None:
        """Choose the intro, recitation and outro; OK is one undoable edit."""
        if self._rendering or not self._is_lecture():
            return
        dialog = EpisodeDialog(self.session, prefs=self._prefs, parent=self)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            # OK made the edit itself (the clips copied beside the project first).
            if dialog.default_error:
                self.statusBar().showMessage(dialog.default_error, 8000)
            self._sync_state()
        finally:
            # Parented to the window, a closed dialog would live as long as it,
            # with its previews and a hold on the session.
            dialog.deleteLater()

    def show_notices(self, notices: tuple[str, ...] | list[str]) -> None:
        """Keep *notices* (what the job that made this project could not do) in view."""
        for notice in notices:
            self.warnings.add_notice(notice)

    def _start_render(self) -> None:
        """Save, then render a snapshot of the project's cards and captions in a worker.

        The job never sees the live ``Project``: it gets a deep copy, so a
        render running for minutes cannot be mutated by (or itself mutate) a
        project the person is still, in principle, looking at. Timing edits
        are disabled for the duration (see ``_set_render_running``); the look
        is not, so the live project may differ from the copy in its ``style``
        too. Only ``render`` is copied back (in ``_on_render_finished``) once
        the job is done; a look changed meanwhile leaves that render stale.
        """
        if self._rendering:
            return
        if self.session.dirty and not self.save():
            return
        snapshot = copy.deepcopy(self.session.project)
        self._render_project_copy = snapshot
        # With an episode, the bar names each step: the lecture, then the rest.
        has_episode = self._is_lecture() and not self.session.episode.is_empty
        self._render_progress_key = "render.running_lecture" if has_episode else "render.running"
        # The last render's episode error is about that render, not this one.
        self.warnings.set_episode_notice(None)
        self._set_render_running(True)
        # No preset or subtitles here: ``run_render`` reads the job's own, so
        # this renders what the job was started for.
        self._render_cancel = self._jobs.start(
            lambda progress, cancel: jobs_module.run_render(
                snapshot, progress=progress, cancel=cancel
            ),
            on_progress=self._on_render_progress,
            on_finished=self._on_render_finished,
            on_failed=self._on_render_failed,
            on_cancelled=self._on_render_cancelled,
            on_done=self._on_render_done,
        )

    def _on_render_finished(self, outcome: JobOutcome) -> None:
        """Bound so Qt queues it to the UI thread; looks up ``_announce_render`` by
        name each call, which is what lets a test replace it after connecting.

        Says nothing once the window has closed: the queued signal can still
        arrive after that (a render outlives a short close-time cancel wait).
        The project update runs either way, so a render started before close
        and finished after it still lands on the live project once the
        window is shown again.
        """
        self._take_back_render(always=True)
        if self._closed:
            return
        # Said before the announcement, which waits for the person to close it.
        for code in outcome.look_warnings:
            self.warnings.add_look_notice(look_warning_text(code))
        # Why this render's episode was not made, until the next render says otherwise.
        self.warnings.set_episode_notice(outcome.episode_error)
        self._announce_render(outcome)

    def _take_back_render(self, *, always: bool = False) -> None:
        """Copy the job's render record onto the live project, and say the file changed.

        ``render`` is the only field the job changes: it is copied back rather
        than the whole snapshot, so it never overwrites an edit made meanwhile
        (the look stays editable during a render). A render that stopped or
        failed after its video was written and recorded (a lecture whose
        episode step was then cancelled, say) has saved that record too; it
        is taken back as well, or the session's next save would write the
        old record over it. *always* announces the save even when the record
        is unchanged, as a finished render does.
        """
        copied = self._render_project_copy
        if copied is not None and (always or copied.render != self.session.project.render):
            self.session.project.render = copy.deepcopy(copied.render)
            changed = True
        else:
            changed = False
        if (always or changed) and self.session.project.path is not None:
            # The render recorded itself in the project file (``render_project`` saves it).
            self.saved.emit(self.session.project.path)

    def _on_render_done(self) -> None:
        # Runs even after close, so the flags are right if the window reopens.
        self._set_render_running(False)

    def _cancel_render(self) -> None:
        if self._render_cancel is not None:
            self._render_cancel.cancel()
            self.render_cancel_button.setEnabled(False)

    def _set_render_running(self, running: bool) -> None:
        if not running:
            self.render_progress.setToolTip("")
        self._rendering = running
        self.render_button.setEnabled(not running)
        # The progress bar and Cancel take the button's place, so the toolbar keeps
        # its width and the window fits a 1280 px screen while a render runs.
        self.render_button.setVisible(not running)
        # The episode is part of what is rendered: chosen before, not during.
        self.episode_button.setEnabled(not running)
        self.episode_button.setVisible(not running and self._is_lecture())
        self.export_button.setEnabled(not running)
        self.strip.setEnabled(not running)
        self.selection_bar.setEnabled(not running)
        self.segment_list.set_cards_editable(not running)
        if running:
            self._segment_list_edit_triggers = self.segment_list.editTriggers()
            self.segment_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        elif self._segment_list_edit_triggers is not None:
            self.segment_list.setEditTriggers(self._segment_list_edit_triggers)
        self.render_progress.setVisible(running)
        self.render_cancel_button.setVisible(running)
        self.render_cancel_button.setEnabled(running)
        if running:
            self.render_progress.setValue(0)
            self.render_progress.setFormat(t(self._render_progress_key, percent=0))
        else:
            self._render_cancel = None
            self._render_project_copy = None
        self._sync_state()

    def _on_render_progress(self, event: ProgressEvent) -> None:
        step = _EPISODE_PROGRESS_KEYS.get(event.stage)
        if step is not None and step != self._render_progress_key:
            # The lecture is done; the episode's next step starts from nothing.
            self._render_progress_key = step
            self.render_progress.setToolTip(t(f"job.stage.{event.stage}"))
            if event.fraction is None:
                self.render_progress.setValue(0)
                self.render_progress.setFormat(t(step, percent=0))
        if event.fraction is None:
            return
        percent = int(max(0.0, min(1.0, event.fraction)) * 100)
        self.render_progress.setValue(percent)
        self.render_progress.setFormat(t(self._render_progress_key, percent=percent))

    def _announce_render(self, outcome: JobOutcome) -> None:
        """Say the render is ready, with a button to reveal it (the tests replace this)."""
        box = QMessageBox(self)
        # An episode that was not made is a warning, though the lecture is ready.
        failed = bool(outcome.episode_error)
        box.setIcon(QMessageBox.Icon.Warning if failed else QMessageBox.Icon.Information)
        box.setWindowTitle(plain_title(t("review.render")))
        box.setText(render_finished_text(outcome))
        show_button = box.addButton(t("render.show"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is show_button and outcome.video is not None:
            show_in_folder(outcome.video)

    def _say_render(self, kind: str, text: str) -> None:
        """Say something about a render that did not simply finish (tests replace this)."""
        icon = QMessageBox.Icon.Warning if kind == "failed" else QMessageBox.Icon.Information
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(plain_title(t("review.render")))
        box.setText(text)
        box.exec()

    def _on_render_failed(self, message: str) -> None:
        self._take_back_render()
        if self._closed:
            return
        self._say_render("failed", t("render.failed", details=message))

    def _on_render_cancelled(self) -> None:
        self._take_back_render()
        if self._closed:
            return
        self._say_render("cancelled", t("render.cancelled"))

    # -- saving and closing ---------------------------------------------------

    def save(self) -> bool:
        """Write the corrections to the project file; ``False`` (after saying why) if it failed."""
        if self._rendering:
            return False
        try:
            path = self.session.save()
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                plain_title(t("review.save")),
                t("review.save_failed", details=str(error)),
            )
            return False
        self._sync_state()
        self.saved.emit(path)
        return True

    def _confirm_discard(self) -> str:
        """Ask what to do with unsaved changes: ``"save"``, ``"discard"`` or ``"cancel"``."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(plain_title(t("review.discard_title")))
        box.setText(t("review.discard_text"))
        buttons = QMessageBox.StandardButton
        box.setStandardButtons(buttons.Save | buttons.Discard | buttons.Cancel)
        box.setDefaultButton(buttons.Save)
        answer = box.exec()
        if answer == buttons.Save:
            return "save"
        if answer == buttons.Discard:
            return "discard"
        return "cancel"

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt override
        """Shown again after a close: ask about changes next time, and resume what close stopped."""
        super().showEvent(event)
        if not self._closed:
            return
        self._closed = False
        if self.player.is_playing():
            self._timer.start()
        if self._audio.is_file():
            self._start_reads()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        if not self._closed and self.session.dirty:
            answer = self._confirm_discard()
            if answer == "cancel" or (answer == "save" and not self.save()):
                event.ignore()
                return
            if answer == "discard":
                # Discard means the edits are gone, not parked in memory for a re-show.
                self.session.revert()
                self._after_edit()
        self._closed = True
        self._timer.stop()
        self._coverage_timer.stop()
        self.player.pause()
        self._jobs.stop()
        event.accept()
        self.closed.emit()

    # -- background reads -------------------------------------------------------

    def _start_reads(self) -> None:
        """Read what is still missing: the peaks, and the levels coverage is checked from.

        Each is read at most once at a time; a read that close cancelled is
        started again when the window is shown again.
        """
        audio = self._audio
        if self.waveform.peaks is None and not self._reading_peaks:
            self._reading_peaks = True
            project_path = self.session.project.path or audio.with_suffix(".qalun.json")
            cache = peaks_path_for(project_path)
            self._jobs.start(
                lambda progress, cancel: load_or_compute_peaks(audio, cache, cancel=cancel),
                on_finished=self._on_peaks,
                on_failed=self.warnings.add_notice,
                on_done=self._on_peaks_done,
            )
        if self._levels is None and not self._reading_levels:
            self._reading_levels = True
            self.warnings.set_checking(True)
            self._jobs.start(
                lambda progress, cancel: speech_levels(audio),
                on_finished=self._on_levels,
                on_failed=self.warnings.add_notice,
                on_done=self._on_levels_done,
            )

    def _on_peaks(self, peaks: Peaks) -> None:
        self.waveform.set_peaks(peaks)
        if self.player.duration() <= 0:
            self._set_duration(peaks.duration)

    def _on_peaks_done(self) -> None:
        self._reading_peaks = False

    def _on_levels(self, levels: tuple[list[float], list[float], float]) -> None:
        self._levels = levels
        self._recheck_coverage()

    def _on_levels_done(self) -> None:
        self._reading_levels = False
        if self._levels is None:
            # The read failed or was stopped: its notice (if any) says so instead.
            self.warnings.set_checking(False)

    def _recheck_coverage(self) -> None:
        """Find uncovered speech from the cached levels, on the UI thread.

        Only the decode is slow; this part takes about 2.5 ms for an hour of
        audio (14,400 frames) against 5,000 words, so it needs no worker.
        """
        if self._levels is None:
            return
        times, levels, floor = self._levels
        gaps = uncovered_from_levels(times, levels, floor, self.session.coverage_words())
        self.waveform.set_gaps([(gap.start, gap.end) for gap in gaps])
        self.warnings.set_gaps(gaps)


def render_finished_text(outcome: JobOutcome) -> str:
    """What a finished render says: the video, then its episode, written or not."""
    lines = [t("render.done", path=path_text(outcome.video))]
    if outcome.episode_video is not None:
        lines.append(t("review.episode_written", name=Path(outcome.episode_video).name))
    if outcome.episode_error:
        lines.append(outcome.episode_error)
    return "\n\n".join(lines)

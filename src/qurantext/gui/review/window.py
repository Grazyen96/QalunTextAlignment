"""The review window: listen to a job, watch its frame, and correct its timings.

This module is layout and wiring only. What an edit may do lives in
:class:`ReviewSession` (and below it ``core.timing_edit``); how each widget
draws lives in that widget (the small bars included: :class:`WarningsStrip`,
:class:`SelectionBar`, :class:`ZoomSlider`); the slow reads of the recording
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
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable
from functools import partial
from pathlib import Path

from PySide6.QtCore import QKeyCombination, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent, QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from qurantext.config.settings import VIDEO_PRESETS
from qurantext.core.coverage import speech_levels, uncovered_from_levels
from qurantext.core.waveform import Peaks, load_or_compute_peaks, peaks_path_for
from qurantext.gui import jobs as jobs_module
from qurantext.gui.files import show_in_folder
from qurantext.gui.i18n import t
from qurantext.gui.jobs import JobOutcome
from qurantext.gui.review.background import BackgroundJobs
from qurantext.gui.review.export_dialog import ExportDialog
from qurantext.gui.review.frame_view import FrameView
from qurantext.gui.review.player import RATES, Player, create_player
from qurantext.gui.review.segment_list import SegmentList
from qurantext.gui.review.selection_bar import NUDGE_S, SelectionBar
from qurantext.gui.review.session import ReviewSession, WordRef
from qurantext.gui.review.viewport import Viewport
from qurantext.gui.review.warnings_strip import WarningsStrip
from qurantext.gui.review.waveform_view import WaveformView
from qurantext.gui.review.word_strip import WordStrip
from qurantext.gui.review.zoom_slider import ZoomSlider
from qurantext.jobs.project import Project, job_settings
from qurantext.utils.progress import CancelToken, ProgressEvent

__all__ = ["ReviewWindow"]

#: The playhead poll while playing: often enough that the highlight looks continuous.
_TICK_MS = 16
#: How long after the last edit the coverage check re-runs.
_COVERAGE_DEBOUNCE_MS = 1000
#: The nudge step with Shift held, in seconds (the plain step is ``NUDGE_S``).
_FINE_NUDGE_S = 0.01
#: The timeline window shown on open, before the person zooms.
_DEFAULT_SPAN_S = 20.0


def _clock(seconds: float) -> str:
    """*seconds* as ``mm:ss.cc``, rounded once so 59.999 never reads as ``00:60.00``."""
    centis = max(0, int(round(seconds * 100)))
    minutes, rest = divmod(centis, 6000)
    return f"{minutes:02d}:{rest // 100:02d}.{rest % 100:02d}"


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


def _content_end(project: Project) -> float:
    """The latest time any card or caption reaches: a timeline length before the audio is read."""
    ends = [float(card.get("end_time") or 0.0) for card in project.cards]
    ends += [float(cue.end) for cue in project.captions]
    return max(ends, default=0.0)


class ReviewWindow(QMainWindow):
    """One project under review: toolbar, warnings, frame, timeline, segment list."""

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
        self, project: Project, *, player: Player | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.session = ReviewSession(project)
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

        self._build()
        self._wire()
        self._bind_keys()

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
            self.warnings.add_notice(t("review.audio_missing", path=str(self._audio)))
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
        self.render_progress = QProgressBar()
        self.render_progress.setRange(0, 100)
        self.render_progress.setFixedWidth(140)
        self.render_progress.setVisible(False)
        self.render_cancel_button = QPushButton(t("render.cancel"))
        self.render_cancel_button.setVisible(False)
        buttons = (
            self.save_button,
            self.undo_button,
            self.redo_button,
            self.reviewed_button,
            self.remove_button,
        )
        for button in buttons:
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.export_button)
        toolbar.addWidget(self.render_button)
        toolbar.addWidget(self.render_progress)
        toolbar.addWidget(self.render_cancel_button)
        column.addLayout(toolbar)

        self.warnings = WarningsStrip()
        column.addWidget(self.warnings)

        body = QWidget()
        body_row = QHBoxLayout(body)
        body_row.setContentsMargins(0, 0, 0, 0)
        self.frame_view = FrameView(self.session, portrait=_is_portrait(self.session.project))
        body_row.addWidget(self.frame_view, 0, Qt.AlignmentFlag.AlignTop)
        body_row.addLayout(self._build_timeline(), 1)

        self.segment_list = SegmentList(self.session)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(body)
        splitter.addWidget(self.segment_list)
        column.addWidget(splitter, 1)

        self.statusBar().addWidget(QLabel(t("review.shortcuts")))
        self.setCentralWidget(central)

    def _build_timeline(self) -> QVBoxLayout:
        right = QVBoxLayout()

        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel(t("review.zoom")))
        self.zoom_slider = ZoomSlider(self.viewport, self.player.position)
        zoom_row.addWidget(self.zoom_slider, 1)
        right.addLayout(zoom_row)

        self.waveform = WaveformView(self.viewport)
        self.strip = WordStrip(self.viewport, self.session)
        right.addWidget(self.waveform)
        right.addWidget(self.strip)

        transport = QHBoxLayout()
        self.play_button = QPushButton(t("review.play"))
        self.time_label = QLabel(_clock(0.0))
        self.rate_combo = QComboBox()
        for rate in RATES:
            self.rate_combo.addItem(t("review.rate", rate=rate), rate)
        transport.addWidget(self.play_button)
        transport.addWidget(self.time_label)
        transport.addWidget(self.rate_combo)
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
        self.export_requested.connect(self._open_export_dialog)
        self.render_requested.connect(self._start_render)
        self.warnings.jump_requested.connect(self.seek)
        self.waveform.seek_requested.connect(self.seek)
        self.strip.seek_requested.connect(self.seek)
        self.strip.selection_changed.connect(self._show_selection)
        self.strip.edited.connect(self._after_edit)
        self.segment_list.seek_requested.connect(self.seek)
        # Connected after the list's own handler, so the caption text is already in the session.
        self.segment_list.itemChanged.connect(self._after_caption_edit)
        self.play_button.clicked.connect(self.toggle_play)
        self.rate_combo.currentIndexChanged.connect(self._on_rate)
        self.selection_bar.nudge_requested.connect(self._nudge)
        self.selection_bar.snap_requested.connect(self._snap_to_playhead)
        self.player.playing_changed.connect(self._on_playing_changed)
        self.player.duration_changed.connect(self._set_duration)
        self.player.error.connect(self.warnings.add_notice)

    def _bind_keys(self) -> None:
        bindings: list[tuple[str, Callable[[], None]]] = [
            ("Space", self.toggle_play),
            ("Left", partial(self._step, -1)),
            ("Right", partial(self._step, 1)),
            ("[", self._set_start_at_playhead),
            ("]", self._set_end_at_playhead),
            (",", partial(self._nudge, -NUDGE_S)),
            (".", partial(self._nudge, NUDGE_S)),
            ("Shift+,", partial(self._nudge, -_FINE_NUDGE_S)),
            ("Shift+.", partial(self._nudge, _FINE_NUDGE_S)),
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

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        combination = event.keyCombination()
        modifiers = combination.keyboardModifiers() & ~Qt.KeyboardModifier.KeypadModifier
        text = QKeySequence(QKeyCombination(modifiers, combination.key())).toString()
        action = self._keys.get(text)
        if action is None:
            super().keyPressEvent(event)
            return
        action()
        event.accept()

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
        self.time_label.setText(_clock(seconds))
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
        self.frame_view.show_at(self.player.position(), force=True)
        if self._levels is not None:
            self._coverage_timer.start()

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
        # A render reads the project's current content: nothing may edit it meanwhile.
        editable = not self._rendering
        self.save_button.setEnabled(session.dirty and editable)
        self.undo_button.setEnabled(session.can_undo and editable)
        self.redo_button.setEnabled(session.can_redo and editable)
        self.remove_button.setEnabled(editable)
        self.reviewed_button.setEnabled(
            session.project.review.get("state") != "reviewed" and editable
        )
        title = t("review.title", name=self._audio.stem)
        self.setWindowTitle(f"{title} *" if session.dirty else title)
        self._show_selection(self.strip.selected)

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

    def _start_render(self) -> None:
        """Save, then render a snapshot of the project's cards and captions in a worker.

        The job never sees the live ``Project``: it gets a deep copy, so a
        render running for minutes cannot be mutated by (or itself mutate) a
        project the person is still, in principle, looking at. Editing is
        disabled for the duration anyway (see ``_set_render_running``), so the
        copy and the live project can only ever differ in ``render`` — which
        ``_on_render_finished`` copies back once the job is done.
        """
        if self._rendering:
            return
        if self.session.dirty and not self.save():
            return
        snapshot = copy.deepcopy(self.session.project)
        self._render_project_copy = snapshot
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
        if self._render_project_copy is not None:
            # ``render`` is the only field that may have changed underneath the
            # live project (editing was disabled): copy it back rather than the
            # whole snapshot, so it never overwrites an editing that snuck in.
            self.session.project.render = copy.deepcopy(self._render_project_copy.render)
        if self.session.project.path is not None:
            # The render recorded itself in the project file (``render_project`` saves it).
            self.saved.emit(self.session.project.path)
        if self._closed:
            return
        self._announce_render(outcome)

    def _on_render_done(self) -> None:
        # Runs even after close, so the flags are right if the window reopens.
        self._set_render_running(False)

    def _cancel_render(self) -> None:
        if self._render_cancel is not None:
            self._render_cancel.cancel()
            self.render_cancel_button.setEnabled(False)

    def _set_render_running(self, running: bool) -> None:
        self._rendering = running
        self.render_button.setEnabled(not running)
        self.export_button.setEnabled(not running)
        self.strip.setEnabled(not running)
        self.selection_bar.setEnabled(not running)
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
            self.render_progress.setFormat(t("render.running", percent=0))
        else:
            self._render_cancel = None
            self._render_project_copy = None
        self._sync_state()

    def _on_render_progress(self, event: ProgressEvent) -> None:
        if event.fraction is None:
            return
        percent = int(max(0.0, min(1.0, event.fraction)) * 100)
        self.render_progress.setValue(percent)
        self.render_progress.setFormat(t("render.running", percent=percent))

    def _announce_render(self, outcome: JobOutcome) -> None:
        """Say the render is ready, with a button to reveal it (the tests replace this)."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(t("review.render"))
        box.setText(t("render.done", path=outcome.video))
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
        box.setWindowTitle(t("review.render"))
        box.setText(text)
        box.exec()

    def _on_render_failed(self, message: str) -> None:
        if self._closed:
            return
        self._say_render("failed", t("render.failed", details=message))

    def _on_render_cancelled(self) -> None:
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
            QMessageBox.warning(self, t("review.save"), str(error))
            return False
        self._sync_state()
        self.saved.emit(path)
        return True

    def _confirm_discard(self) -> str:
        """Ask what to do with unsaved changes: ``"save"``, ``"discard"`` or ``"cancel"``."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(t("review.discard_title"))
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

# UI review fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the seventeen findings of the 2026-10-07 UI review: readable attention colours in both palettes, visible job actions, labelled form rows, drag-over feedback, shortcut tooltips, a review window that keeps its segment list at laptop sizes, usable word-edge targets, one time format, and an export dialog with a default button.

**Architecture:** Fixed colours move into one small module (`gui/colors.py`) that picks a shade from the palette's lightness; every widget asks it at paint or build time. Everything else is local to the widget it concerns: the job list grows a button row, the new-job form puts its "More options" rows in a labelled form, the review window gains tooltips/eliding/splitter sizing, the word strip gains hover and a bigger grab zone, `i18n` gains `clock()` and `time_span` uses it, the export dialog gets a `QDialogButtonBox`.

**Tech Stack:** Python 3.10+, PySide6 6.11, pytest offscreen (`QT_QPA_PLATFORM=offscreen`), ruff 0.15.13.

**Spec:** `docs/superpowers/specs/2026-10-07-ui-review-fixes.md`

## Global Constraints

- `venv/bin/ruff check src tests` and `venv/bin/ruff format --check src tests` clean (line length 100; `PLE2502` on — write direction marks as `\u` escapes, never as literal characters).
- Run tests with `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest <file> -q`. Never `QTest.qWait` (holds the GIL; deadlocked worker threads) — use `spin`/`wait_for` from `tests/qt_helpers.py`.
- Every user-visible string in `gui/` goes through `t()`/`tn()` from `qurantext.gui.i18n`, with the English and the Arabic entry in `STRINGS` in the same commit (`tests/test_i18n.py` fails on a key Arabic lacks).
- Tests that build a `JobListPanel`/`MainWindow` use the `no_default_job_dirs` fixture and a `Prefs` over a `QSettings` INI under `tmp_path` (see the `prefs` fixture in `tests/test_home_panels.py`). Never touch real settings.
- No `pip install`, no downloads. Do not dispatch subagents.
- Keep the attribute names existing tests use (spec "Constraints"): `detail_label`, `empty_label`, `problem_label`, `drop_zone`, `choose_button`, `remove_button`, `selection_bar`, `minus_button`, `plus_button`, `_go_button`, `close_button`, `_show_button`, `_result_label`, `_video_radio`, `_folder_field`, `_name_field`, `more_button`, `more_group`.
- Colours never hard-coded in a widget: palette roles, or `gui/colors.py` (Task 1) for the amber and the red.
- House style: a why-docstring per module/class/non-trivial function, `from __future__ import annotations`, `__all__`, `# noqa: N802 - Qt override` on Qt event overrides.
- One commit per task, message a plain sentence in the repo's style (e.g. "Let the job list's actions be seen, and its amber be read on a light palette"), ending with the trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Run the whole suite once at the end of each task: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q` (about 860 tests).

## Review Focus

1. The system theme changes while the app runs → rows built afterwards use the other amber (Task 1 test switches `QApplication.setPalette` and restores it).
2. A drag enters the drop zone and leaves without dropping → the zone is back to normal (Task 2 test).
3. The review window is smaller than the frame preview's natural size → the segment list still shows rows and the preview shrinks (Task 3 test at 1000×640).
4. The pointer leaves the word strip while an edge is highlighted → the highlight clears (Task 4 test).
5. A time just under a minute boundary (59.999 s) formats as `00:59.99`/`01:00.00`, never `00:60.00` (Task 5 test on `clock`).

## Files

| File | Responsibility | Task |
|---|---|---|
| `src/qurantext/gui/colors.py` (new), `tests/test_colors.py` (new) | amber and red by palette lightness, with contrast tests | 1 |
| `src/qurantext/gui/home/job_list.py`, `tests/test_home_panels.py` | button row under the list; amber from `colors` | 1 |
| `src/qurantext/gui/home/new_job.py`, `tests/test_home_panels.py` | labelled "More options" form, drag-over state, silent progress bar, range buddies | 2 |
| `src/qurantext/gui/review/window.py`, `gui/review/frame_view.py`, `gui/review/selection_bar.py`, `tests/test_review_window.py` | tooltips, eliding hint, zoom buddy, remove-button state, splitter/frame sizing | 3 |
| `src/qurantext/gui/review/word_strip.py`, `gui/review/waveform_view.py`, `tests/test_review_widgets.py` | 8 px grab zone, 44 px strip, hover highlight, amber top bar, red from `colors` | 4 |
| `src/qurantext/gui/i18n.py`, `gui/review/window.py`, `gui/review/warnings_strip.py`, `tests/test_i18n.py`, `tests/test_review_widgets.py`, `tests/test_review_window.py` | `clock()`, `time_span` in clock form, "Retimed words" | 5 |
| `src/qurantext/gui/review/export_dialog.py`, `tests/test_review_window.py` | button box with Export default, result above, folder field start | 6 |

---

### Task 1: Palette-aware colours and visible job actions

**Files:**
- Create: `src/qurantext/gui/colors.py`, `tests/test_colors.py`
- Modify: `src/qurantext/gui/home/job_list.py` (`_WARNING_COLOR`, `_JobRow.__init__`, `JobListPanel.__init__`, `_on_listed`), `src/qurantext/gui/i18n.py` (`STRINGS["en"]`, `STRINGS["ar"]`)
- Test: `tests/test_home_panels.py` (the test near line 234 that compares to `module._WARNING_COLOR`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces (Task 4 uses these): `qurantext.gui.colors.is_light(palette: QPalette) -> bool`, `warning_color(palette: QPalette) -> QColor`, `playhead_color(palette: QPalette) -> QColor`.

- [ ] **Step 1: Write the failing colour tests** in `tests/test_colors.py`:

```python
"""The two fixed colours must read on whichever palette the system gives."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QPalette  # noqa: E402

from qurantext.gui.colors import is_light, playhead_color, warning_color  # noqa: E402


def _luminance(color: QColor) -> float:
    def channel(value: int) -> float:
        v = value / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(color.red()) + 0.7152 * channel(color.green()) + 0.0722 * channel(color.blue())


def contrast(a: QColor, b: QColor) -> float:
    """WCAG contrast ratio between two colours."""
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _palette(window: QColor, base: QColor) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.Base, base)
    return palette


LIGHT = _palette(QColor(239, 239, 239), QColor(255, 255, 255))
DARK = _palette(QColor(53, 53, 53), QColor(35, 35, 35))


def test_lightness_is_read_from_the_window_colour() -> None:
    assert is_light(LIGHT) and not is_light(DARK)


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_the_amber_reads_as_text_on_the_list_and_the_window(palette) -> None:
    amber = warning_color(palette)
    for role in (QPalette.ColorRole.Base, QPalette.ColorRole.Window):
        assert contrast(amber, palette.color(role)) >= 4.5


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_the_playhead_red_reads_as_a_mark_on_the_window(palette) -> None:
    assert contrast(playhead_color(palette), palette.color(QPalette.ColorRole.Window)) >= 3.0


def test_the_light_palette_gets_a_darker_amber_than_the_dark_one() -> None:
    assert warning_color(LIGHT).lightness() < warning_color(DARK).lightness()
```

- [ ] **Step 2: Run it to see it fail**: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_colors.py -q` → ImportError on `qurantext.gui.colors`.

- [ ] **Step 3: Write `src/qurantext/gui/colors.py`**:

```python
"""The few colours the windows do not take from the palette, in a shade that reads on it.

Amber says "needs attention" (a job row, an edited word) and red marks the
playhead; neither has a palette role. One fixed amber was 2.2:1 on a white
list and unreadable there, so each colour comes in a shade for a light
palette and one for a dark palette, and a widget asks for it with the
palette it paints on — so a theme switched while the app runs gets the right
shade on the next paint. The light shades were measured against Qt's light
window (239) and base (255), the dark ones against Fusion's dark window (53)
and base (35): every amber ≥ 4.5:1 as text, every red ≥ 3:1 as a mark.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

__all__ = ["is_light", "playhead_color", "warning_color"]

_WARNING_ON_LIGHT = QColor(158, 86, 0)
_WARNING_ON_DARK = QColor(239, 159, 39)
_PLAYHEAD_ON_LIGHT = QColor(200, 48, 48)
_PLAYHEAD_ON_DARK = QColor(226, 75, 74)


def is_light(palette: QPalette) -> bool:
    """Whether *palette* is a light theme: its window colour is nearer white than black."""
    return palette.color(QPalette.ColorRole.Window).lightness() >= 128


def warning_color(palette: QPalette) -> QColor:
    """The "needs attention" amber for *palette*, readable as text on its base and window."""
    return QColor(_WARNING_ON_LIGHT if is_light(palette) else _WARNING_ON_DARK)


def playhead_color(palette: QPalette) -> QColor:
    """The playhead red for *palette*, readable as a mark on its window."""
    return QColor(_PLAYHEAD_ON_LIGHT if is_light(palette) else _PLAYHEAD_ON_DARK)
```

- [ ] **Step 4: Run `tests/test_colors.py`** → all pass.

- [ ] **Step 5: Write the failing job-list tests** in `tests/test_home_panels.py` (next to the existing row tests; `_listed`, `_card`, `prefs`, `save_project`, `Project`, `DAMAGED` are already imported there):

```python
def _two_jobs(prefs):
    folder = prefs.job_dirs[0]
    for name in ("first", "second"):
        matches = folder / f"{name}_recitation.json"
        matches.write_text('{"matches": [], "meta": {"mode": "recitation"}}', encoding="utf-8")
        save_project(
            Project(audio=folder / f"{name}.mp3", cards=[_card()], matches=matches),
            folder / f"{name}_recitation.qalun.json",
        )


def test_the_action_buttons_wait_for_a_current_row(qt_app, prefs) -> None:
    _two_jobs(prefs)
    panel = _listed(prefs)
    for button in (panel.open_button, panel.reveal_button, panel.remove_button):
        assert not button.isEnabled()
    panel.list.setCurrentRow(0)
    for button in (panel.open_button, panel.reveal_button, panel.remove_button):
        assert button.isEnabled()


def test_the_open_button_opens_the_current_row(qt_app, prefs) -> None:
    _two_jobs(prefs)
    panel = _listed(prefs)
    opened = []
    panel.open_requested.connect(opened.append)
    panel.list.setCurrentRow(1)
    panel.open_button.click()
    assert opened == [panel.list.item(1).data(Qt.ItemDataRole.UserRole).project]


def test_the_remove_button_hides_the_current_row(qt_app, prefs) -> None:
    _two_jobs(prefs)
    panel = _listed(prefs)
    gone = panel.list.item(0).data(Qt.ItemDataRole.UserRole).project
    panel.list.setCurrentRow(0)
    panel.remove_button.click()
    wait_until_listed(panel)
    assert panel.list.count() == 1
    assert gone.resolve() in prefs.hidden_jobs
    assert not panel.remove_button.isEnabled()


def test_the_reveal_button_asks_to_show_the_current_row(qt_app, prefs) -> None:
    _two_jobs(prefs)
    panel = _listed(prefs)
    shown = []
    panel.reveal_requested.connect(shown.append)
    panel.list.setCurrentRow(0)
    panel.reveal_button.click()
    assert shown == [panel.list.item(0).data(Qt.ItemDataRole.UserRole).project]


def test_the_action_buttons_sit_under_the_list_and_are_named(qt_app, prefs) -> None:
    panel = _listed(prefs)
    layout = panel.layout()
    assert layout.indexOf(panel.actions_row) > layout.indexOf(panel.list)
    assert panel.open_button.text() == t("home.open")
    assert panel.reveal_button.text() == t("home.show_in_folder")
    assert panel.remove_button.text() == t("home.remove_from_list")


def test_a_row_built_on_a_dark_palette_gets_the_dark_amber(qt_app, prefs) -> None:
    from PySide6.QtGui import QColor, QPalette

    from qurantext.gui import colors

    _two_jobs(prefs)
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    dark.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
    before = qt_app.palette()
    qt_app.setPalette(dark)
    try:
        panel = _listed(prefs)
        row = panel.list.itemWidget(panel.list.item(0))
        shown = row.detail_label.palette().color(row.detail_label.foregroundRole())
        assert shown == colors.warning_color(dark)
        assert shown != colors.warning_color(before)
    finally:
        qt_app.setPalette(before)
```

Also change the existing test near line 234 so that
`assert pending.palette().color(pending.foregroundRole()) == module._WARNING_COLOR`
becomes `== warning_color(pending.palette())` (import `warning_color` from `qurantext.gui.colors`), and the `!=` line likewise.

- [ ] **Step 6: Run them to see them fail**: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_home_panels.py -q -k "action or amber or reveal or remove_button"`.

- [ ] **Step 7: Implement in `job_list.py`.**
  - Delete `_WARNING_COLOR`; `from qurantext.gui.colors import warning_color`; in `_JobRow.__init__` use `palette.setColor(QPalette.ColorRole.Text, warning_color(self.palette()))`. Update the comment above (it explained the fixed amber; now say the shade is picked for the palette so a light list stays readable).
  - In `JobListPanel.__init__`, after `self.empty_label` is added, build the button row:

```python
        # The actions a row offers, where a person can see them: the context
        # menu and double-click stay, but nothing told anyone they were there,
        # and a keyboard user could reach neither.
        self.actions_row = QWidget()
        actions = QHBoxLayout(self.actions_row)
        actions.setContentsMargins(0, 0, 0, 0)
        self.open_button = QPushButton(t("home.open"))
        self.reveal_button = QPushButton(t("home.show_in_folder"))
        self.remove_button = QPushButton(t("home.remove_from_list"))
        for button in (self.open_button, self.reveal_button, self.remove_button):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addWidget(self.actions_row)
        self.open_button.clicked.connect(self._open_current)
        self.reveal_button.clicked.connect(self._reveal_current)
        self.remove_button.clicked.connect(self._remove_current)
        self.list.currentItemChanged.connect(lambda *_: self._update_actions())
        self._update_actions()
```

  - Add the methods:

```python
    def _current_entry(self) -> JobEntry | None:
        item = self.list.currentItem()
        entry = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return entry if isinstance(entry, JobEntry) else None

    def _update_actions(self) -> None:
        """Offer the buttons only for a job row: the running row has no file to act on."""
        has_job = self._current_entry() is not None
        for button in (self.open_button, self.reveal_button, self.remove_button):
            button.setEnabled(has_job)

    def _open_current(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self._on_activated(item)

    def _reveal_current(self) -> None:
        entry = self._current_entry()
        if entry is not None:
            self.reveal(entry.project)

    def _remove_current(self) -> None:
        entry = self._current_entry()
        if entry is not None:
            self.remove_from_list(entry.project)
```

  - At the end of `_on_listed` (after `self._show_running_row()`), call `self._update_actions()`: a rebuilt list has no current item.
  - Strings: `"home.open": "Open"` in English; `"home.open": "افتح"` in Arabic, next to `home.show_in_folder` in each table.

- [ ] **Step 8: Run `tests/test_home_panels.py tests/test_colors.py tests/test_i18n.py tests/test_rtl.py`** → pass. Then the whole suite and ruff (check + format).

- [ ] **Step 9: Commit** `src/qurantext/gui/colors.py src/qurantext/gui/home/job_list.py src/qurantext/gui/i18n.py tests/test_colors.py tests/test_home_panels.py`.

---

### Task 2: The new-job form's labelled options, drag-over state, silent bar, range buddies

**Files:**
- Modify: `src/qurantext/gui/home/new_job.py` (`_build`, `dragEnterEvent`, `dropEvent`, `_set_formats_visibility`, `_set_more_options_visibility`, `_update_quran_label`, `_update_output_dir_label`), `src/qurantext/gui/i18n.py`
- Test: `tests/test_home_panels.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: new panel attributes `range_from_label`, `range_to_label`, `more_form` (a `QFormLayout`), and `drop_zone.property("dragOver")`; strings `home.quran_text`, `home.output_dir`, `home.subtitles`, `home.formats`.

- [ ] **Step 1: Write the failing tests** in `tests/test_home_panels.py` (`_panel`, `prefs`, `store`, `QMimeData`, `QPointF`, `QUrl`, `Qt`, `QDropEvent` are already imported there):

```python
def _audio_mime(tmp_path):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "take.mp3"))])
    return mime


def test_the_drop_zone_lights_up_while_a_drag_is_over_it_and_not_after(
    qt_app, prefs, store, tmp_path
) -> None:
    from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent

    panel = _panel(prefs, store)
    enter = QDragEnterEvent(
        QPointF(10, 10).toPoint(),
        Qt.DropAction.CopyAction,
        _audio_mime(tmp_path),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    qt_app.sendEvent(panel, enter)
    assert panel.drop_zone.property("dragOver") is True
    qt_app.sendEvent(panel, QDragLeaveEvent())
    assert panel.drop_zone.property("dragOver") is False


def test_a_drop_puts_the_zone_back_to_normal(qt_app, prefs, store, tmp_path) -> None:
    from PySide6.QtGui import QDragEnterEvent

    panel = _panel(prefs, store)
    mime = _audio_mime(tmp_path)
    qt_app.sendEvent(
        panel,
        QDragEnterEvent(
            QPointF(10, 10).toPoint(),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    qt_app.sendEvent(
        panel,
        QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert panel.audio_path == tmp_path / "take.mp3"
    assert panel.drop_zone.property("dragOver") is False


def test_the_progress_bar_leaves_the_words_to_the_status_line(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    assert not panel.progress_bar.isTextVisible()


def test_the_range_labels_name_their_spin_boxes(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    assert panel.range_from_label.buddy() is panel.from_spin
    assert panel.range_to_label.buddy() is panel.to_spin


def test_the_more_options_are_labelled_rows_that_hide_together(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    form = panel.more_form
    labels = {
        form.labelForField(panel.quran_row).text(): panel.quran_row,
        form.labelForField(panel.output_row).text(): panel.output_row,
        form.labelForField(panel.subtitles_row).text(): panel.subtitles_row,
        form.labelForField(panel.formats_widget).text(): panel.formats_widget,
    }
    assert set(labels) == {
        t("home.quran_text"),
        t("home.output_dir"),
        t("home.subtitles"),
        t("home.formats"),
    }
    panel.subtitle_buttons["burn"].setChecked(True)
    assert panel.formats_widget.isHidden()
    assert form.labelForField(panel.formats_widget).isHidden()
    panel.subtitle_buttons["both"].setChecked(True)
    assert not panel.formats_widget.isHidden()
    assert not form.labelForField(panel.formats_widget).isHidden()


def test_the_value_texts_no_longer_repeat_their_labels(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    assert panel.quran_label.text() == t("home.quran_override.default")
    assert ":" not in t("home.quran_override.default")
    assert ":" not in t("home.output_dir.default")


def test_the_two_forms_share_one_label_column(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    panel.more_button.setChecked(True)
    panel.resize(800, 700)
    panel.show()
    spin(50)
    upper = panel.surah_box.x()
    lower = panel.quran_row.x()
    assert abs(upper - lower) <= 2
```

- [ ] **Step 2: Run them to see them fail** (`-k "drop_zone or drop_puts or progress_bar_leaves or range_labels or more_options_are or value_texts or one_label_column"`).

- [ ] **Step 3: Implement in `new_job.py`.**
  - Drop-zone stylesheet becomes:
    `"QFrame#dropZone { border: 2px dashed palette(mid); border-radius: 6px; }"
    " QFrame#dropZone[dragOver=\"true\"] { border: 2px solid palette(highlight); background: palette(alternate-base); }"`.
    Right after building it: `self.drop_zone.setProperty("dragOver", False)`.
  - Add:

```python
    def _set_drag_over(self, over: bool) -> None:
        """Light the zone while an accepted drag is over it; the stylesheet reads the property."""
        self.drop_zone.setProperty("dragOver", over)
        style = self.drop_zone.style()
        style.unpolish(self.drop_zone)
        style.polish(self.drop_zone)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802 — Qt's name
        self._set_drag_over(False)
        super().dragLeaveEvent(event)
```

    `dragEnterEvent` calls `self._set_drag_over(True)` after accepting; `dropEvent` calls `self._set_drag_over(False)` first thing. Import `QDragLeaveEvent` from `PySide6.QtGui`.
  - Range row: `self.range_from_label = QLabel(t("home.range_from")); self.range_from_label.setBuddy(self.from_spin)` (same for `to`), added to `range_row` instead of the anonymous labels.
  - Progress bar: `self.progress_bar.setTextVisible(False)` right after it is created.
  - "More options": keep `self.more_group = QWidget()`, but its layout is `self.more_form = QFormLayout(self.more_group)` with margins 0. Wrap each row in a widget and add it as a labelled row:

```python
        self.quran_row = QWidget()
        quran_row = QHBoxLayout(self.quran_row)
        quran_row.setContentsMargins(0, 0, 0, 0)
        ...  # the label and the two buttons as before, into quran_row
        self.more_form.addRow(t("home.quran_text"), self.quran_row)

        self.output_row = QWidget()
        ...  # likewise
        self.more_form.addRow(t("home.output_dir"), self.output_row)

        self.subtitles_row = QWidget()
        ...  # the radios into a QHBoxLayout(self.subtitles_row)
        self.more_form.addRow(t("home.subtitles"), self.subtitles_row)

        self.formats_widget = QWidget()   # as before
        self.more_form.addRow(t("home.formats"), self.formats_widget)

        self.render_right_away_box = QCheckBox(t("home.render_right_away"))
        self.more_form.addRow(self.render_right_away_box)  # spans both columns
```

    `_set_formats_visibility` hides the label too:

```python
    def _set_formats_visibility(self, subtitles: str) -> None:
        shown = subtitles in ("sidecar", "both")
        self.formats_widget.setVisible(shown)
        label = self.more_form.labelForField(self.formats_widget)
        if label is not None:
            label.setVisible(shown)
```

  - Both forms share one label column. After both forms are built (end of `_build`), add and call:

```python
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
```

    Keep a reference to the upper form as `self._form = form` where it is built.
  - Strings (English → Arabic):
    - `"home.quran_text": "Quran text"` → `"نص القرآن"`
    - `"home.output_dir": "Output folder"` → `"مجلد الحفظ"`
    - `"home.subtitles": "Subtitles"` → `"الترجمة النصية"`
    - `"home.formats": "Files"` → `"الملفات"`
    - `"home.quran_override.default"` becomes `"The certified text that ships with Qalun"` → `"النص الموثَّق المرفق مع Qalun"`
    - `"home.quran_override.custom"` becomes `"{path}"` in both languages
    - `"home.output_dir.default"` becomes `"The default location"` → `"الموضع الافتراضي"`
    - `"home.output_dir.custom"` becomes `"{path}"` in both languages

- [ ] **Step 4: Run `tests/test_home_panels.py tests/test_i18n.py tests/test_rtl.py tests/test_gui.py`** → pass (fix any test that asserted the old "Quran text: …" wording by asserting through `t()`). Then the whole suite and ruff.

- [ ] **Step 5: Commit** `src/qurantext/gui/home/new_job.py src/qurantext/gui/i18n.py tests/test_home_panels.py`.

---

### Task 3: Review window — tooltips, eliding hint, zoom buddy, remove-button state, room for the list

**Files:**
- Modify: `src/qurantext/gui/review/window.py` (`_build`, `_build_timeline`, `_wire`, `_on_playing_changed`, `_sync_state`, new `_set_tips`, `_elide_hint`, `eventFilter`), `src/qurantext/gui/review/frame_view.py`, `src/qurantext/gui/review/selection_bar.py` (nothing but tooltips, set from the window), `src/qurantext/gui/i18n.py`
- Test: `tests/test_review_window.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: window attributes `hint_label`, `zoom_label`, `_splitter`; `FrameView.minimumSizeHint()` half the preset size; strings `review.tip`, `review.tip_fine`, a longer `review.shortcuts`.

- [ ] **Step 1: Write the failing tests** in `tests/test_review_window.py` (`_window`, `_three_cue_window`, `_spin`, `t` are available there):

```python
def test_the_toolbar_and_transport_say_their_shortcuts(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    assert "Ctrl+S" in window.save_button.toolTip()
    assert "Ctrl+Z" in window.undo_button.toolTip()
    assert "Ctrl+Shift+Z" in window.redo_button.toolTip()
    assert "Space" in window.play_button.toolTip()
    assert "," in window.selection_bar.minus_button.toolTip()
    assert "." in window.selection_bar.plus_button.toolTip()
    assert window.selection_bar.minus_button.toolTip() == t(
        "review.tip_fine", action=t("review.minus"), keys=","
    )


def test_the_shortcut_hint_elides_to_the_window_and_keeps_its_full_text(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    window.resize(window.minimumSizeHint())
    window.show()
    _spin(50)
    label = window.hint_label
    assert label.toolTip() == t("review.shortcuts")
    assert label.fontMetrics().horizontalAdvance(label.text()) <= label.width()
    assert label.text().endswith("…")
    window.resize(2400, 800)
    _spin(50)
    assert window.hint_label.text() == t("review.shortcuts")


def test_zoom_is_the_sliders_buddy(qt_app, tmp_path) -> None:
    window, _, _ = _window(qt_app, tmp_path)
    assert window.zoom_label.buddy() is window.zoom_slider


def test_remove_waits_for_a_selected_row(qt_app, tmp_path) -> None:
    window = _three_cue_window(tmp_path)
    assert not window.remove_button.isEnabled()
    window.segment_list.selectRow(1)
    assert window.remove_button.isEnabled()
    window.segment_list.clearSelection()
    assert not window.remove_button.isEnabled()


def test_a_small_window_keeps_rows_in_the_list_and_shrinks_the_frame(qt_app, tmp_path) -> None:
    window = _three_cue_window(tmp_path)
    window.resize(1000, 640)
    window.show()
    _spin(100)
    assert window.segment_list.height() >= 150
    frame = window.frame_view
    assert frame.height() < 480
    assert frame.pixmap().height() <= frame.height()
    assert frame.pixmap().width() <= frame.width()
```

  Also update these existing tests to the new remove-button behaviour:
  - `test_remove_with_nothing_selected_says_so_without_a_modal` (near line 387) and the "remove only takes what was selected" test's nothing-selected part (near line 868): with nothing selected the button is disabled, so assert `not window.remove_button.isEnabled()` instead of clicking and reading the status message. Keep `_remove_selected`'s status message in the code (it still guards a direct call).
  - `test_render_disables_editing_actions_until_done` (near line 582): select a row (`window.segment_list.selectRow(0)`) before the assertions about `remove_button.isEnabled()`, so the button's enabled state reflects the render, not the selection.

- [ ] **Step 2: Run them to see them fail** (`-k "shortcuts or elides or buddy or waits_for or small_window"`).

- [ ] **Step 3: Implement.**
  - Strings: `"review.tip": "{action} ({keys})"` → ar `"{action} ({keys})"`; `"review.tip_fine": "{action} ({keys}; with Shift: 10 ms)"` → ar `"{action} ({keys}؛ مع Shift: 10 م.ث)"`. Replace `review.shortcuts` with: en `"Space plays · ←/→ step words · [ ] set start/end at the playhead · , . nudge 50 ms (Shift: 10 ms) · Shift-drag ripples the later words · Ctrl-drag an edge to part two words · Ctrl+Z undoes"`; ar `"المسافة للتشغيل · ⁦←/→⁩ للتنقل بين الكلمات · ⁦[ ]⁩ للبداية/النهاية عند مؤشر التشغيل · ⁦, .⁩ للإزاحة 50 م.ث (مع Shift: 10 م.ث) · اسحب مع Shift لإزاحة الكلمات التالية · اسحب حافة مع Ctrl لفصل كلمتين · Ctrl+Z للتراجع"`.
  - In `_build`, after `_bind_keys` would run (call `_set_tips()` at the end of `__init__`, after `_bind_keys()`):

```python
    def _set_tips(self) -> None:
        """Say each button's shortcut on the button itself, where a person hovers to learn it."""
        native = QKeySequence.SequenceFormat.NativeText
        tips = (
            (self.save_button, "Ctrl+S"),
            (self.undo_button, "Ctrl+Z"),
            (self.redo_button, "Ctrl+Shift+Z"),
            (self.play_button, "Space"),
        )
        for button, keys in tips:
            shown = QKeySequence(keys).toString(native)
            button.setToolTip(t("review.tip", action=button.text(), keys=shown))
        bar = self.selection_bar
        bar.minus_button.setToolTip(t("review.tip_fine", action=bar.minus_button.text(), keys=","))
        bar.plus_button.setToolTip(t("review.tip_fine", action=bar.plus_button.text(), keys="."))
```

    In `_on_playing_changed`, after setting the play button's text, reset its tooltip the same way (`t("review.tip", action=self.play_button.text(), keys=QKeySequence("Space").toString(native))`).
  - Status hint: replace `self.statusBar().addWidget(QLabel(t("review.shortcuts")))` with:

```python
        self.hint_label = QLabel()
        self.hint_label.setToolTip(t("review.shortcuts"))
        # Takes whatever width the bar has, and elides to it (see _elide_hint).
        self.hint_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.hint_label.installEventFilter(self)
        self.statusBar().addWidget(self.hint_label, 1)
```

    with

```python
    def _elide_hint(self) -> None:
        full = t("review.shortcuts")
        metrics = self.hint_label.fontMetrics()
        self.hint_label.setText(
            metrics.elidedText(full, Qt.TextElideMode.ElideRight, self.hint_label.width())
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if watched is self.hint_label and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._elide_hint()
        return super().eventFilter(watched, event)
```

    (import `QEvent`, `QObject` from `QtCore`, `QSizePolicy` from `QtWidgets`).
  - Zoom: `self.zoom_label = QLabel(t("review.zoom"))`, `self.zoom_label.setBuddy(self.zoom_slider)` after the slider exists, add the label to `zoom_row` instead of the anonymous one.
  - Remove button: in `_wire`, `self.segment_list.itemSelectionChanged.connect(self._sync_state)`; in `_sync_state`:
    `self.remove_button.setEnabled(editable and bool(self.segment_list.selectedIndexes()))`.
  - Splitter: keep `self._splitter = splitter`; `splitter.setChildrenCollapsible(False)`; `splitter.setStretchFactor(0, 0)`; `splitter.setStretchFactor(1, 1)`.
  - `FrameView` shrinks with its window: in `frame_view.py`

```python
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setMinimumSize(self._width // 2, self._height // 2)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._last_t = 0.0
```

    `sizeHint` stays the preset size; add `minimumSizeHint` returning `QSize(self._width // 2, self._height // 2)`. In `show_at`, remember `self._last_t = t` and render at the fitted size:

```python
    def _render_size(self) -> tuple[int, int]:
        """The largest frame of the preset's shape that fits the widget, never above the preset size."""
        width = min(self._width, max(1, self.width()))
        height = min(self._height, max(1, self.height()))
        scale = min(width / self._width, height / self._height)
        return max(1, int(self._width * scale)), max(1, int(self._height * scale))

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self.show_at(self._last_t, force=True)
```

    and pass `*self._render_size()` to `render_frame_pillow` instead of `self._width, self._height`. (`QResizeEvent` from `QtGui`, `QSizePolicy` from `QtWidgets`.) The body row in the window keeps `Qt.AlignmentFlag.AlignTop` for the frame.

- [ ] **Step 4: Run `tests/test_review_window.py tests/test_review_widgets.py tests/test_rtl.py tests/test_i18n.py`** → pass. Then the whole suite and ruff.

- [ ] **Step 5: Commit** `src/qurantext/gui/review/window.py src/qurantext/gui/review/frame_view.py src/qurantext/gui/i18n.py tests/test_review_window.py`.

---

### Task 4: Word strip — bigger grab zone, taller strip, hover highlight, amber bar, palette red

**Files:**
- Modify: `src/qurantext/gui/review/word_strip.py` (`EDGE_PX`, `sizeHint`, `__init__`, `mouseMoveEvent`, new `leaveEvent`, `paintEvent`, `_paint_word`), `src/qurantext/gui/review/waveform_view.py` (`_PLAYHEAD_COLOR`, `paintEvent`)
- Test: `tests/test_review_widgets.py`

**Interfaces:**
- Consumes: `qurantext.gui.colors.warning_color(palette)`, `playhead_color(palette)` (Task 1).
- Produces: `WordStrip.EDGE_PX == 8`, `WordStrip.sizeHint().height() == 44`, `WordStrip.hovered_edge` property (`tuple[str, WordRef] | None`).

- [ ] **Step 1: Write the failing tests** in `tests/test_review_widgets.py` using the module's `_strip(qt_app)` helper (read it first: it returns a strip with words whose edges are at known x positions; derive `x_of_edge` from `strip._viewport.x_for(word.start, strip.width())`):

```python
def test_an_edge_is_grabbed_from_eight_pixels_away(qt_app) -> None:
    strip, session, *_ = _strip(qt_app)
    first = session.words()[0]
    x_end = strip._viewport.x_for(first.end, strip.width())
    assert strip._hit_test(x_end - 7) == ("end", first.ref)
    assert strip._hit_test(x_end + 7)[0] in ("end", "start")
    assert strip.EDGE_PX == 8


def test_the_strip_is_tall_enough_to_hit(qt_app) -> None:
    strip, *_ = _strip(qt_app)
    assert strip.sizeHint().height() == 44


def test_the_edge_under_the_pointer_is_highlighted_until_the_pointer_leaves(qt_app) -> None:
    from PySide6.QtCore import QEvent

    strip, session, *_ = _strip(qt_app)
    strip.show()
    first = session.words()[0]
    x_end = strip._viewport.x_for(first.end, strip.width())
    QTest.mouseMove(strip, QPoint(int(x_end), strip.height() // 2))
    assert strip.hovered_edge == ("end", first.ref)
    QTest.mouseMove(strip, QPoint(int(x_end) + 40, strip.height() // 2))
    assert strip.hovered_edge is None
    QTest.mouseMove(strip, QPoint(int(x_end), strip.height() // 2))
    qt_app.sendEvent(strip, QEvent(QEvent.Type.Leave))
    assert strip.hovered_edge is None


def test_the_playhead_red_comes_from_the_palette(qt_app) -> None:
    from qurantext.gui.review import waveform_view, word_strip

    assert not hasattr(waveform_view, "_PLAYHEAD_COLOR")
    assert not hasattr(word_strip, "_PLAYHEAD_OUTLINE")
    assert not hasattr(word_strip, "_EDITED_DOT")
```

  If `_strip` returns a different tuple shape, unpack accordingly — the helper is the truth; adapt the test, not the helper.

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement.**
  - `word_strip.py`: `EDGE_PX = 8`; `sizeHint` → `QSize(600, 44)`; delete `_PLAYHEAD_OUTLINE` and `_EDITED_DOT`; `from qurantext.gui.colors import playhead_color, warning_color`; `self._hover: tuple[str, WordRef] | None = None` in `__init__` with the property:

```python
    @property
    def hovered_edge(self) -> tuple[str, WordRef] | None:
        """The edge under the pointer (``("start"|"end", ref)``), drawn as a handle; None otherwise."""
        return self._hover
```

    In `mouseMoveEvent`'s no-drag branch, after the cursor logic:

```python
            hover = hit if hit is not None and hit[0] in ("start", "end") else None
            if hover != self._hover:
                self._hover = hover
                self.update()
```

    Add:

```python
    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if self._hover is not None:
            self._hover = None
            self.update()
        super().leaveEvent(event)
```

    (`QEvent` from `QtCore`.) In `_paint_word`, the border pen uses `playhead_color(palette)`; replace the dot with a bar:

```python
        if tw.edited:
            bar = QRectF(rect.left() + 1, rect.top() + 1, max(1.0, rect.width() - 2), 3.0)
            painter.fillRect(bar, warning_color(palette))
```

    After the loop in `paintEvent`, draw the handle for the hovered edge (or the edge being dragged, `self._drag` when it is an `_EdgeDrag`):

```python
            handle = self._hover
            if isinstance(self._drag, _EdgeDrag):
                handle = (self._drag.edge, self._drag.ref)
            if handle is not None:
                self._paint_handle(painter, handle, width, height, palette)
```

```python
    def _paint_handle(self, painter, handle, width, height, palette) -> None:
        """A 3 px bar on the edge the pointer can grab, so the target is seen before it is felt."""
        edge, ref = handle
        try:
            tw = self._session.word(ref)
        except IndexError:
            return
        x = self._viewport.x_for(tw.start if edge == "start" else tw.end, width)
        painter.fillRect(QRectF(x - 1.5, 0.0, 3.0, float(height)), palette.highlight())
```

  - `waveform_view.py`: delete `_PLAYHEAD_COLOR`; `painter.setPen(playhead_color(palette))` in `paintEvent` (import from `qurantext.gui.colors`). Update the module docstring line in `job_list.py` that mentions the amber being reused if it references these constants.

- [ ] **Step 4: Run `tests/test_review_widgets.py tests/test_review_window.py tests/test_rtl.py`** → pass (an existing drag test that pressed exactly `EDGE_PX + 1` past an edge to miss it must move to `EDGE_PX + 1` with the new value — read it). Then the whole suite and ruff.

- [ ] **Step 5: Commit** `src/qurantext/gui/review/word_strip.py src/qurantext/gui/review/waveform_view.py tests/test_review_widgets.py`.

---

### Task 5: One time format

**Files:**
- Modify: `src/qurantext/gui/i18n.py` (new `clock`, `time_span`, strings `review.selected`, `review.gap`, `segments.retimed`), `src/qurantext/gui/review/window.py` (`_clock`)
- Test: `tests/test_i18n.py`, `tests/test_review_widgets.py`, `tests/test_review_window.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `qurantext.gui.i18n.clock(seconds: float, *, digits: int = 2) -> str` (`"mm:ss.cc"`, `digits=1` → `"mm:ss.c"`); `time_span(start, end, *, digits=2, sep="–")` returns two clocks joined by *sep*.

- [ ] **Step 1: Write the failing tests** in `tests/test_i18n.py`:

```python
def test_clock_formats_minutes_seconds_and_hundredths() -> None:
    from qurantext.gui.i18n import clock

    assert clock(0.0) == "00:00.00"
    assert clock(96.57) == "01:36.57"
    assert clock(59.999) == "01:00.00"
    assert clock(59.994) == "00:59.99"
    assert clock(16.8, digits=1) == "00:16.8"
    assert clock(-1.0) == "00:00.00"


def test_time_span_joins_two_clocks() -> None:
    from qurantext.gui.i18n import time_span

    assert time_span(0.11, 96.57) == "00:00.11–01:36.57"
    assert time_span(16.8, 23.0, digits=1) == "00:16.8–00:23.0"
    assert time_span(0.11, 1.42, sep=" → ") == "00:00.11 → 00:01.42"
```

  Update the existing expectations that asserted plain seconds (`"0.11–1.42"`-style) in `tests/test_i18n.py`, `tests/test_review_widgets.py` (the selection-bar, segment-list and warnings-strip span tests) and `tests/test_review_window.py` (gap tests) to the clock form, via `time_span(...)` where the test already imports it.

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement.**
  - In `i18n.py` (no Qt imports — the module must stay Qt-free):

```python
def clock(seconds: float, *, digits: int = 2) -> str:
    """*seconds* as ``mm:ss.cc`` (``digits`` fraction digits), rounded once.

    One rounding of the whole value, so 59.999 reads ``01:00.00`` and never
    ``00:60.00``; a negative time reads as zero.
    """
    scale = 10**digits
    units = max(0, int(round(seconds * scale)))
    minutes, rest = divmod(units, 60 * scale)
    whole, fraction = divmod(rest, scale)
    return f"{minutes:02d}:{whole:02d}.{fraction:0{digits}d}"


def time_span(start: float, end: float, *, digits: int = 2, sep: str = "–") -> str:
    """Two times as one value, so a sentence in any language keeps them in order."""
    return f"{clock(start, digits=digits)}{sep}{clock(end, digits=digits)}"
```

    Add `clock` to `__all__` if the module has one.
  - `window.py`: delete the module's `_clock` and use `from qurantext.gui.i18n import clock`; `self.time_label = QLabel(clock(0.0))`, `self.time_label.setText(clock(seconds))`. If a test imports `_clock` from the window module, keep `_clock = clock` with a one-line comment.
  - Strings: `"review.selected"` en `"⁨{word}⁩  {span}"`, ar `"{word}  {span}"`; `"review.gap"` en `"{duration:.1f} s at {span}"`, ar `"{duration:.1f} ث عند {span}"`; `"segments.retimed"` en `"Retimed words"`, ar `"كلمات أُعيد توقيتها"`.

- [ ] **Step 4: Run `tests/test_i18n.py tests/test_review_widgets.py tests/test_review_window.py tests/test_rtl.py`** → pass. Then the whole suite and ruff.

- [ ] **Step 5: Commit** `src/qurantext/gui/i18n.py src/qurantext/gui/review/window.py tests/test_i18n.py tests/test_review_widgets.py tests/test_review_window.py`.

---

### Task 6: Export dialog — default button, button box, readable folder field

**Files:**
- Modify: `src/qurantext/gui/review/export_dialog.py` (`_build`, `_set_defaults`, `_choose_folder`, `set_destination`, `_show_result`, `_show_error`)
- Test: `tests/test_review_window.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `ExportDialog.buttons` (a `QDialogButtonBox`); the existing `_go_button`, `close_button`, `_show_button`, `_result_label` names stay.

- [ ] **Step 1: Write the failing tests** in `tests/test_review_window.py` (the module already builds `ExportDialog(session)` in its export tests; copy that construction):

```python
def test_export_is_the_dialogs_default_button(qt_app, tmp_path) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.session import ReviewSession

    dialog = ExportDialog(ReviewSession(_project(tmp_path)))
    assert dialog._go_button.isDefault()
    assert isinstance(dialog.buttons, QDialogButtonBox)
    assert dialog.buttons.buttonRole(dialog._go_button) == QDialogButtonBox.ButtonRole.AcceptRole
    assert dialog.buttons.buttonRole(dialog.close_button) == QDialogButtonBox.ButtonRole.RejectRole
    assert dialog._show_button.isHidden()
    layout = dialog.layout()
    assert layout.indexOf(dialog._result_label) < layout.indexOf(dialog.buttons)


def test_the_folder_field_shows_the_start_of_the_path(qt_app, tmp_path) -> None:
    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.session import ReviewSession

    dialog = ExportDialog(ReviewSession(_project(tmp_path)))
    deep = tmp_path / ("a-rather-long-folder-name-" * 6)
    dialog.set_destination(deep, "take")
    assert dialog._folder_field.cursorPosition() == 0
    assert dialog._folder_field.toolTip() == str(deep)
```

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement.** In `_build`, replace the three stacked buttons with:

```python
        self._result_label = QLabel()
        self._result_label.setWordWrap(True)
        self._result_label.setVisible(False)
        layout.addWidget(self._result_label)

        self.buttons = QDialogButtonBox()
        self._show_button = self.buttons.addButton(
            t("export.show"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self._show_button.setVisible(False)
        self._show_button.clicked.connect(self._show_written)
        self._go_button = self.buttons.addButton(t("export.go"), QDialogButtonBox.ButtonRole.AcceptRole)
        self._go_button.setDefault(True)
        self.close_button = self.buttons.addButton(
            t("export.close"), QDialogButtonBox.ButtonRole.RejectRole
        )
        layout.addWidget(self.buttons)
        # Export writes and stays open to say what it wrote; only Close leaves.
        self._go_button.clicked.connect(self.export)
        self.close_button.clicked.connect(self.accept)
```

    Do not connect `self.buttons.accepted`/`rejected` (Export must not close the dialog; Escape still rejects as before). Folder field: add

```python
    def _set_folder(self, folder: str) -> None:
        """Show the path from its start, with the whole of it on hover."""
        self._folder_field.setText(folder)
        self._folder_field.setCursorPosition(0)
        self._folder_field.setToolTip(folder)
```

    and use it in `_set_defaults`, `_choose_folder` and `set_destination`. `_show_result`/`_show_error` keep toggling `_show_button`'s visibility. Import `QDialogButtonBox`.

- [ ] **Step 4: Run `tests/test_review_window.py tests/test_rtl.py`** → pass (a test that read `dialog.close_button` or `dialog._go_button` keeps working). Then the whole suite and ruff.

- [ ] **Step 5: Commit** `src/qurantext/gui/review/export_dialog.py tests/test_review_window.py`.

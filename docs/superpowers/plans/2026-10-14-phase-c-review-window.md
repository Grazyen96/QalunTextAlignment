# Phase C: Review Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Relay out the review window into two columns, add a time ruler and an iconed transport, group the toolbar, replace the warnings strip and the success dialog with a banner, add a shortcut sheet, style the segment table, and give the preview a fit / actual toggle and a full-size view.

**Architecture:** Four new widgets (`TimeRuler`, `Banner`, `Transport`, `ShortcutSheet`) and a `FullFrameView`, each small and tested on its own; the window's `_build` assembles them into a horizontal splitter (left: preview + Look; right: timeline + table). The `Banner` keeps the `WarningsStrip` API, including `text()`, so the window's wiring and the existing tests keep working; the nudge buttons move into the transport while `selection_bar.minus_button` and friends keep resolving through properties. Session, viewport, timing edits and key bindings are untouched.

**Tech Stack:** Python 3.12, PySide6 6.11 (QtWidgets `QSplitter`, `QStyledItemDelegate`, `QScrollArea`; QtGui `QPainter`, `QDesktopServices`), pytest, ruff 0.15.13. Phase A's `gui/theme.py`, `gui/icons.py`, `gui/widgets.py`.

**Spec:** `docs/superpowers/specs/2026-10-14-phase-c-review-window-design.md`

## Global Constraints

- Run every command with `venv/bin/python` from the worktree root; GUI tests with `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest <files> -q`. Lint before each commit: `venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools`.
- Never wait on the event loop with `QTest.qWait`; use `tests.qt_helpers.spin` / `wait_for`. Worker `QObject`s are deleted on the UI thread.
- Every `t("…")` key exists in both `STRINGS["en"]` and `STRINGS["ar"]`; an Arabic line that starts with a value needs a leading `‏`; literal direction marks in source are written as `\u` escapes (ruff PLE2502).
- Widget attribute names the tests reach keep their names and classes: `frame_view`, `look_panel`, `look_scroll`, `waveform`, `strip`, `segment_list`, `zoom_slider`, `zoom_label`, `play_button`, `time_label`, `show_ayah_button`, `selection_bar` (with `label`, `minus_button`, `plus_button`, `snap_button`), `warnings` (with `text()`, `add_notice`, `add_look_notice`, `set_look_notices`, `set_surah_notice`, `set_episode_notice`, `set_gaps`, `set_checking`, `jump_requested`), `hint_label`, `save_button` … `render_button`, `render_progress`, `render_cancel_button`, `episode_button`, `episode_label`, `studied_surah_box`, `_announce_render(outcome)`, `_say_render(kind, text)`. Removed on purpose: `rate_combo` (→ `transport.rate_buttons`), `_splitter` (the vertical one; a horizontal `_splitter` takes the name), `_LOOK_PANEL_WIDTH` (the look scroll follows the left column).
- The timeline runs right to left in both languages (`Viewport.x_for`); the ruler, waveform and strip set `LayoutDirection.LeftToRight` on themselves as the strip does today; the nudge chevrons are registered with `mirror=False`.
- Keyboard bindings are unchanged; `?` is added. `ReviewSession`, `Viewport`, `core.timing_edit`, `core.coverage` are not modified.
- Lucide names at tag 1.56.0; the new ones are `zoom-in`, `zoom-out`, `crosshair`, `maximize-2`, `keyboard`, `info`.
- The existing fit tests `test_a_lecture_window_fits_a_1280_px_screen_while_rendering[*]` stay green; the new layout test needs ≥ 8 table rows at 1280×800 in a lecture.
- Commit messages: one sentence for a reader of `git log` (see `git log --oneline -12`), ending with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **A one-hour lecture zoomed fully out**: the ruler must label at 5-minute steps without overlapping and the readout must say minutes, not "3600 s shown". Test in Task 2.
2. **A render finishing while the banner already shows coverage gaps**: the success line joins the gap lines; dismissing clears the success line but the gaps stay. Test in Task 3.
3. **Pressing `?` while a caption cell is being edited**: the editor must receive the character, not the sheet (the existing `keyPressEvent` fallback rule). Test in Task 8.
4. **Double-clicking the preview while playing**: the full-frame view shows the frame at the moment of the click and playback keeps running; closing it returns focus to the window. Test in Task 7.
5. **A window too short for the preview in Actual size**: the left column scrolls the preview rather than clipping it; the Look panel stays reachable. Test in Task 7.

---

### Task 1: Icons, strings, `mirror=`, and `Prefs.preview_fit`

**Files:**
- Modify: `tools/fetch_icons.py` (`ICON_NAMES`), `src/qurantext/gui/icons.py` (`NAMES`, `icon`, `set_icon`, `refresh_icons`), `src/qurantext/assets/icons/` (6 new SVGs via the tool)
- Modify: `src/qurantext/gui/i18n.py` (`en` block after `"review.key_space"` ≈ line 316; `ar` block after its `"review.key_space"`)
- Modify: `src/qurantext/gui/prefs.py` (after `theme`), `tests/test_prefs.py`, `tests/test_icons.py`, `tests/test_packaging_spec.py` (35 → 41)

**Interfaces:**
- Produces: `icon(name, role="text", on_role=None, *, mirror=True)`; `set_icon(button, name, role="text", size=20, on_role=None, *, mirror=True)` recording `(name, role, size, on_role, mirror)` only when `mirror` is False (so existing 3/4-tuples keep meaning `mirror=True`); `refresh_icons` reads the 5-tuple; `Prefs.preview_fit: bool` (default True); the i18n keys below.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_icons.py`:

```python
def test_mirror_false_keeps_a_directional_icon_as_drawn_under_rtl(qt_app) -> None:
    from PySide6.QtCore import QSize, Qt

    ltr = icons.icon("chevron-right").pixmap(QSize(16, 16)).toImage()
    qt_app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    try:
        icons.clear_cache()
        kept = icons.icon("chevron-right", mirror=False).pixmap(QSize(16, 16)).toImage()
        flipped = icons.icon("chevron-right").pixmap(QSize(16, 16)).toImage()
        assert kept == ltr and flipped != ltr
        button = QPushButton()
        icons.set_icon(button, "chevron-right", size=16, mirror=False)
        assert button.property("qalun.icon") == ("chevron-right", "text", 16, None, False)
        assert icons.refresh_icons(button) == 1
        assert button.icon().pixmap(QSize(16, 16)).toImage() == ltr
    finally:
        qt_app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        icons.clear_cache()
```

(`QPushButton` is already imported there.) In `tests/test_prefs.py::test_defaults_on_an_empty_ini` add `assert prefs.preview_fit is True`, and append:

```python
def test_preview_fit_round_trips(tmp_path) -> None:
    from PySide6.QtCore import QSettings

    ini = tmp_path / "prefs.ini"
    prefs = Prefs(QSettings(str(ini), QSettings.Format.IniFormat))
    prefs.preview_fit = False
    assert Prefs(QSettings(str(ini), QSettings.Format.IniFormat)).preview_fit is False
```

In `tests/test_packaging_spec.py` change the icon count assertion to `== 41`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_icons.py tests/test_prefs.py tests/test_packaging_spec.py -q`
Expected: FAIL (`TypeError: icon() got an unexpected keyword argument 'mirror'`, `AttributeError: preview_fit`, `assert 35 == 41`)

- [ ] **Step 3: Icons**

Append `"zoom-in", "zoom-out", "crosshair", "maximize-2", "keyboard", "info"` to `ICON_NAMES` and `NAMES`; run `venv/bin/python tools/fetch_icons.py`. In `icons.py`:

```python
def icon(name: str, role: str = "text", on_role: str | None = None, *, mirror: bool = True) -> QIcon:
    ...
    rtl = _rtl() and mirror
    key = (name, role, on_role, tokens.name, rtl)
```

(the rest unchanged: `drawn_name = MIRRORED.get(name, name) if rtl else name`). `set_icon` gains `*, mirror: bool = True`, passes it to `icon`, and records `(name, role, size, on_role, mirror)` when `mirror` is False, else the record as today. `refresh_icons` accepts records of length 3, 4 or 5: `mirror = bool(recorded[4]) if len(recorded) == 5 else True`; `on_role = recorded[3] if len(recorded) >= 4 and recorded[3] else None`.

- [ ] **Step 4: `Prefs.preview_fit`**

After the `theme` property in `prefs.py`:

```python
    # -- the review preview ------------------------------------------------------

    @property
    def preview_fit(self) -> bool:
        """Whether the review's preview fits its column (True) or shows the preset's size."""
        value = self._settings.value("preview_fit", True)
        return value not in (False, "false", "0", 0)

    @preview_fit.setter
    def preview_fit(self, value: bool) -> None:
        self._settings.setValue("preview_fit", bool(value))
        self._settings.sync()
```

- [ ] **Step 5: Strings**

`STRINGS["en"]`, after `"review.key_space": "Space",`:

```python
        "review.span": {"one": "{count} s shown", "other": "{count} s shown"},
        "review.span_minutes": "{minutes}:{seconds} shown",
        "review.zoom_in": "Zoom in",
        "review.zoom_out": "Zoom out",
        "review.fit": "Fit",
        "review.actual_size": "Actual size",
        "review.prev_word": "Previous word",
        "review.next_word": "Next word",
        "review.rate_label": "Speed",
        "review.help": "Shortcuts (?)",
        "review.hint": "Space plays · ← → words · [ ] set start/end · <a href=\"shortcuts\">? all shortcuts</a>",
        "review.shortcuts.title": "Shortcuts",
        "review.shortcuts.playback": "Playback",
        "review.shortcuts.editing": "Editing",
        "review.shortcuts.file": "File",
        "review.key.play": "Play or pause",
        "review.key.next_word": "Next word (later)",
        "review.key.prev_word": "Previous word (earlier)",
        "review.key.scrub": "Seek: click or drag the waveform or the ruler",
        "review.key.set_start": "Set the selected word's start at the playhead",
        "review.key.set_end": "Set the selected word's end at the playhead",
        "review.key.nudge_later": "Nudge the edge later by 50 ms",
        "review.key.nudge_earlier": "Nudge the edge earlier by 50 ms",
        "review.key.nudge_fine": "With Shift: 10 ms",
        "review.key.ripple": "Shift-drag a word: ripple the later words",
        "review.key.detach": "Ctrl-drag an edge: part two words",
        "review.key.change_ayah": "Double-click an Ayah cell: change the ayah",
        "review.key.undo": "Undo",
        "review.key.redo": "Redo",
        "review.key.save": "Save",
        "review.key.sheet": "This sheet",
        "review.gaps_toggle": {
            "one": "{count} stretch of speech has no word",
            "other": "{count} stretches of speech have no word",
        },
        "review.full_frame": "Show the frame full size (double-click)",
        "render.done_banner": "Rendered ⁨{name}⁩",
        "render.done_banner_timed": "Rendered ⁨{name}⁩ · {duration}",
        "render.play": "Play",
        "render.play_failed": "Could not open the video with your player.",
        "banner.dismiss": "Dismiss",
```

`STRINGS["ar"]`, after its `"review.key_space"`:

```python
        "review.span": {
            "zero": "‏{count} ث معروضة",
            "one": "‏{count} ث معروضة",
            "two": "‏{count} ث معروضة",
            "few": "‏{count} ث معروضة",
            "many": "‏{count} ث معروضة",
            "other": "‏{count} ث معروضة",
        },
        "review.span_minutes": "‏{minutes}:{seconds} معروضة",
        "review.zoom_in": "كبِّر",
        "review.zoom_out": "صغِّر",
        "review.fit": "ملاءمة",
        "review.actual_size": "الحجم الفعلي",
        "review.prev_word": "الكلمة السابقة",
        "review.next_word": "الكلمة التالية",
        "review.rate_label": "السرعة",
        "review.help": "الاختصارات (?)",
        "review.hint": "المسافة للتشغيل · ← → للكلمات · [ ] للبداية/النهاية · <a href=\"shortcuts\">? كل الاختصارات</a>",
        "review.shortcuts.title": "الاختصارات",
        "review.shortcuts.playback": "التشغيل",
        "review.shortcuts.editing": "التحرير",
        "review.shortcuts.file": "الملف",
        "review.key.play": "تشغيل أو إيقاف مؤقت",
        "review.key.next_word": "الكلمة التالية (لاحقًا)",
        "review.key.prev_word": "الكلمة السابقة (سابقًا)",
        "review.key.scrub": "الانتقال: انقر أو اسحب على الموجة أو المسطرة",
        "review.key.set_start": "اضبط بداية الكلمة المحددة عند مؤشر التشغيل",
        "review.key.set_end": "اضبط نهاية الكلمة المحددة عند مؤشر التشغيل",
        "review.key.nudge_later": "أزح الحافة لاحقًا بمقدار 50 م.ث",
        "review.key.nudge_earlier": "أزح الحافة سابقًا بمقدار 50 م.ث",
        "review.key.nudge_fine": "مع Shift: 10 م.ث",
        "review.key.ripple": "اسحب كلمة مع Shift: إزاحة الكلمات التالية",
        "review.key.detach": "اسحب حافة مع Ctrl: فصل كلمتين",
        "review.key.change_ayah": "انقر نقرًا مزدوجًا على خلية الآية: غيِّر الآية",
        "review.key.undo": "تراجع",
        "review.key.redo": "إعادة",
        "review.key.save": "حفظ",
        "review.key.sheet": "هذه اللوحة",
        "review.gaps_toggle": {
            "zero": "لا مقاطع كلام بلا كلمة",
            "one": "مقطع كلام واحد بلا كلمة",
            "two": "مقطعا كلام بلا كلمة",
            "few": "‏{count} مقاطع كلام بلا كلمة",
            "many": "‏{count} مقطع كلام بلا كلمة",
            "other": "‏{count} مقطع كلام بلا كلمة",
        },
        "review.full_frame": "اعرض الإطار بالحجم الكامل (نقر مزدوج)",
        "render.done_banner": "أُخرج ⁨{name}⁩",
        "render.done_banner_timed": "أُخرج ⁨{name}⁩ · {duration}",
        "render.play": "شغِّل",
        "render.play_failed": "تعذّر فتح الفيديو بمشغّلك.",
        "banner.dismiss": "أخفِ",
```

Check the Arabic plural categories the module uses (`plural_category`): give `review.span` and `review.gaps_toggle` every category `tn` can ask for. Remove `"review.shortcuts"` (the long line) from both languages only in Task 8, when its last use goes.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_icons.py tests/test_prefs.py tests/test_packaging_spec.py tests/test_i18n.py -q`
Expected: PASS

- [ ] **Step 7: Lint and commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add tools/fetch_icons.py src/qurantext/gui/icons.py src/qurantext/assets/icons src/qurantext/gui/i18n.py src/qurantext/gui/prefs.py tests/test_icons.py tests/test_prefs.py tests/test_packaging_spec.py
git commit -m "Add the six icons, every string and the preview preference the review window's redesign needs, and let an icon keep its direction under Arabic

The Arabic strings await a native speaker's review, with the rest.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: The time ruler

**Files:**
- Create: `src/qurantext/gui/review/time_ruler.py`
- Create: `tests/test_time_ruler.py`

**Interfaces:**
- Consumes: `Viewport` (`start`, `span`, `duration`, `x_for(t, width)`, `t_for(x, width)`, `changed`), `theme.font("clock")`, `theme.current_tokens()`, `i18n.clock`.
- Produces: `TimeRuler(viewport, parent=None)` with `seek_requested = Signal(float)`, `set_playhead(t)`, `HEIGHT = 24`; module function `tick_step(span_s: float, width_px: float, label_px: float) -> tuple[float, float]` returning `(major_s, minor_s)`; `STEPS = (1, 2, 5, 10, 30, 60, 120, 300, 600)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_time_ruler.py
"""The ruler over the waveform: ticks and times that never overlap, right to left."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402

from qurantext.gui.review import time_ruler  # noqa: E402
from qurantext.gui.review.time_ruler import TimeRuler, tick_step  # noqa: E402
from qurantext.gui.review.viewport import Viewport  # noqa: E402


@pytest.mark.parametrize(
    ("span", "width", "expected"),
    [
        (10.0, 1200.0, 1.0),
        (120.0, 600.0, 10.0),
        (3600.0, 600.0, 300.0),  # Review Focus 1: an hour on a narrow ruler labels every 5 min
        (20.0, 600.0, 2.0),
    ],
)
def test_the_major_step_keeps_labels_apart(span, width, expected) -> None:
    major, minor = tick_step(span, width, label_px=48.0)
    assert major == expected
    assert minor < major and major % minor == 0


def test_a_degenerate_span_or_width_returns_the_largest_step() -> None:
    assert tick_step(0.0, 600.0, 48.0)[0] == time_ruler.STEPS[-1]
    assert tick_step(10.0, 0.0, 48.0)[0] == time_ruler.STEPS[-1]


def _ruler(qt_app, span=10.0, duration=60.0, width=600):
    viewport = Viewport()
    viewport.set_duration(duration)
    viewport.set_window(0.0, span)
    ruler = TimeRuler(viewport)
    ruler.resize(width, TimeRuler.HEIGHT)
    return ruler, viewport


def test_labels_run_right_to_left_with_the_first_at_the_right(qt_app) -> None:
    ruler, _ = _ruler(qt_app)
    labels = ruler.labels()  # [(x, text), ...] as they would be painted
    assert labels[0][1] == "00:00" and labels[0][0] > labels[-1][0]
    assert all(b[0] + 48 <= a[0] for a, b in zip(labels, labels[1:], strict=False))


def test_a_click_seeks_and_a_hover_names_the_time(qt_app) -> None:
    ruler, viewport = _ruler(qt_app)
    sought = []
    ruler.seek_requested.connect(sought.append)
    x = viewport.x_for(2.5, ruler.width())
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPoint(int(x), 10), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    ruler.mousePressEvent(press)
    assert sought and abs(sought[0] - 2.5) < 0.05
    assert ruler.time_at(x).startswith("00:02")


def test_the_playhead_mark_sits_at_its_time(qt_app) -> None:
    ruler, viewport = _ruler(qt_app)
    ruler.set_playhead(5.0)
    assert abs(ruler.playhead_x() - viewport.x_for(5.0, ruler.width())) < 1.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_time_ruler.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'qurantext.gui.review.time_ruler'`

- [ ] **Step 3: Write `time_ruler.py`**

```python
# src/qurantext/gui/review/time_ruler.py
"""The time ruler over the waveform: ticks and ``mm:ss`` labels, right to left.

The major step is the smallest of :data:`STEPS` whose labels, at their
measured width, do not touch at the current span and width; the minor step
is a fifth of it (a half for 1 and 2 s). The ruler shares the
:class:`Viewport` with the waveform and the strip, so a tick and the bar
under it mean the same moment.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QMouseEvent, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from qurantext.gui import theme
from qurantext.gui.colors import playhead_color
from qurantext.gui.i18n import clock
from qurantext.gui.review.viewport import Viewport

__all__ = ["STEPS", "TimeRuler", "tick_step"]

STEPS = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0)
_LABEL_GAP_PX = 8.0


def tick_step(span_s: float, width_px: float, label_px: float) -> tuple[float, float]:
    """``(major, minor)`` seconds so that labels *label_px* wide never touch; the largest step when degenerate."""
    if span_s <= 0 or width_px <= 0:
        return STEPS[-1], STEPS[-1] / 5
    px_per_s = width_px / span_s
    for step in STEPS:
        if step * px_per_s >= label_px + _LABEL_GAP_PX:
            return step, (step / 2 if step <= 2 else step / 5)
    return STEPS[-1], STEPS[-1] / 5


def _label(t: float) -> str:
    return clock(t, digits=0).rstrip(".")  # clock(digits=0) ends in a dot


class TimeRuler(QWidget):
    """Ticks, labels, a playhead triangle; a click or drag asks to seek."""

    HEIGHT = 24
    seek_requested = Signal(float)

    def __init__(self, viewport: Viewport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setFont(theme.font("clock"))
        self._viewport = viewport
        self._playhead = 0.0
        self._dragging = False
        viewport.changed.connect(self.update)

    def set_playhead(self, t: float) -> None:
        self._playhead = float(t)
        self.update()

    def playhead_x(self) -> float:
        return self._viewport.x_for(self._playhead, self.width())

    def time_at(self, x: float) -> str:
        return clock(max(0.0, self._viewport.t_for(x, self.width())), digits=1)

    def _steps(self) -> tuple[float, float]:
        label_px = QFontMetrics(self.font()).horizontalAdvance("00:00")
        return tick_step(self._viewport.span, self.width(), label_px)

    def labels(self) -> list[tuple[float, str]]:
        """``(x, text)`` for each major tick in the window, in time order (so x descends)."""
        major, _ = self._steps()
        start, span = self._viewport.start, self._viewport.span
        first = (start // major) * major
        out = []
        t = first
        while t <= start + span + 1e-9:
            if t >= start - 1e-9:
                out.append((self._viewport.x_for(t, self.width()), _label(t)))
            t += major
        return out

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.seek_requested.emit(self._viewport.t_for(event.position().x(), self.width()))
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if self._dragging:
            self.seek_requested.emit(self._viewport.t_for(event.position().x(), self.width()))
            self.setToolTip("")
            return
        self.setToolTip(self.time_at(event.position().x()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        try:
            tokens = theme.current_tokens()
            palette = self.palette()
            painter.fillRect(self.rect(), palette.window())
            width, height = self.width(), self.height()
            major, minor = self._steps()
            start, span = self._viewport.start, self._viewport.span
            pen_minor = QPen(QColor(tokens.border), 1)
            pen_major = QPen(QColor(tokens.secondary), 1)
            t = (start // minor) * minor
            while t <= start + span + 1e-9:
                x = int(self._viewport.x_for(t, width))
                is_major = abs(t / major - round(t / major)) < 1e-6
                painter.setPen(pen_major if is_major else pen_minor)
                painter.drawLine(x, height - (10 if is_major else 5), x, height - 1)
                t += minor
            painter.setPen(QColor(tokens.secondary))
            metrics = QFontMetrics(self.font())
            for x, text in self.labels():
                w = metrics.horizontalAdvance(text)
                # The label sits to the left of its tick (the past lies to the right here).
                painter.drawText(QRectF(x - w - 3, 0, w, height - 10), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), text)
            px = self.playhead_x()
            if 0 <= px <= width:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(playhead_color(palette))
                painter.drawPolygon(QPolygonF([QPointF(px - 5, 0), QPointF(px + 5, 0), QPointF(px, 7)]))
            painter.setPen(QPen(QColor(tokens.border), 1))
            painter.drawLine(0, height - 1, width, height - 1)
        finally:
            painter.end()
```

(`i18n.clock(t, digits=0)` yields "00:05." with a trailing dot; `_label` strips it.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_time_ruler.py -q`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/review/time_ruler.py tests/test_time_ruler.py
git commit -m "Add a time ruler over the waveform: ticks and times that never overlap, a playhead mark, a hover time, a click to seek

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: The banner

**Files:**
- Create: `src/qurantext/gui/review/banner.py`
- Delete: `src/qurantext/gui/review/warnings_strip.py`
- Create: `tests/test_banner.py`
- Modify: `tests/test_review_widgets.py:750-810` (the three warnings-strip tests move to `test_banner.py` against `Banner`)
- Modify: `src/qurantext/gui/review/window.py:77,360` (import and construction only, so the branch stays green between tasks)

**Interfaces:**
- Consumes: `widgets.Card`, `icons.icon`, `colors.warning_color`, `theme`, `i18n.t/tn/time_span/clock`, `core.coverage.UncoveredSpeech`, `gui.jobs.JobOutcome`.
- Produces: `Banner(parent=None)` with `jump_requested(float)`, `play_requested(object)` (a `Path`), `reveal_requested(object)`, `dismissed`; the `WarningsStrip` methods unchanged in signature (`add_notice`, `set_look_notices`, `add_look_notice`, `set_surah_notice`, `set_episode_notice`, `set_gaps`, `set_checking`); `set_render_done(outcome, duration_s: float | None)`, `clear_render()`, `text() -> str` (the lines joined by `<br>`, escaped as before), `lines() -> list[str]` (plain text), `kind() -> str` (`""`, `info`, `attention`, `success`), `EMPTY_HEIGHT = 4`, `gaps_expanded` property.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_banner.py
"""The banner under the toolbar: notices, coverage gaps and a finished render, never moving the body."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from qurantext.core.coverage import UncoveredSpeech  # noqa: E402
from qurantext.gui import theme  # noqa: E402
from qurantext.gui.i18n import t, tn  # noqa: E402
from qurantext.gui.jobs import JobOutcome  # noqa: E402
from qurantext.gui.review.banner import Banner  # noqa: E402


@pytest.fixture()
def banner(qt_app):
    theme.apply_theme(qt_app, "light")
    made = Banner()
    made.show()
    yield made
    made.deleteLater()


def _gap(start: float, end: float) -> UncoveredSpeech:
    return UncoveredSpeech(start=start, end=end, mean_db=-20.0)


def test_empty_it_keeps_a_four_pixel_rule(banner) -> None:
    assert banner.kind() == ""
    assert banner.lines() == []
    assert banner.sizeHint().height() == Banner.EMPTY_HEIGHT
    assert banner.isVisibleTo(banner.parentWidget() or banner)


def test_notices_are_lines_once_each_and_make_it_info(banner) -> None:
    banner.add_notice("FFmpeg failed")
    banner.add_notice("FFmpeg failed")
    assert banner.lines() == ["FFmpeg failed"]
    assert banner.text().count("FFmpeg failed") == 1
    assert banner.kind() == "info"


def test_gaps_collapse_behind_a_count_and_expand(banner) -> None:
    banner.set_gaps([_gap(4.0, 6.0), _gap(10.0, 11.0)])
    assert banner.kind() == "attention"
    assert tn("review.gaps_toggle", 2) in banner.text()
    assert not banner.gaps_expanded
    assert "Jump" not in banner.text()
    banner.toggle_gaps()
    assert banner.gaps_expanded and "2.0 s at 00:04.0–00:06.0" in banner.text()
    seen = []
    banner.jump_requested.connect(seen.append)
    banner.jump_to("4.000")
    assert seen == [4.0]


def test_five_gaps_are_listed_then_the_rest_counted(banner) -> None:
    banner.set_gaps([_gap(i, i + 1) for i in range(7)])
    banner.toggle_gaps()
    assert banner.text().count("Jump") == 5
    assert tn("review.more_gaps", 2) in banner.text()


def test_checking_shows_until_the_first_result(banner) -> None:
    banner.set_checking(True)
    assert t("review.checking") in banner.text()
    banner.set_gaps([])
    assert t("review.checking") not in banner.text() and t("review.covered") in banner.text()


def test_a_finished_render_adds_a_success_line_with_two_actions(banner, tmp_path) -> None:
    video = tmp_path / "a.mp4"
    outcome = JobOutcome(matches=tmp_path / "m.json", video=video, cards=1)
    played, revealed = [], []
    banner.play_requested.connect(played.append)
    banner.reveal_requested.connect(revealed.append)
    banner.set_render_done(outcome, 96.0)
    assert banner.kind() == "success"
    assert t("render.done_banner_timed", name="a.mp4", duration="01:36") in banner.text()
    banner.play_button.click()
    banner.reveal_button.click()
    assert played == [video] and revealed == [video]
    banner.set_render_done(outcome, None)
    assert t("render.done_banner", name="a.mp4") in banner.text()
    banner.clear_render()
    assert "a.mp4" not in banner.text() and not banner.play_button.isVisibleTo(banner)


def test_dismiss_clears_news_but_keeps_state(banner, tmp_path) -> None:
    """Review Focus 2: a render finishing over coverage gaps; dismiss keeps the gaps."""
    banner.set_gaps([_gap(4.0, 6.0)])
    banner.set_surah_notice("no card")
    banner.add_notice("plain news")
    outcome = JobOutcome(matches=tmp_path / "m.json", video=tmp_path / "a.mp4", cards=1)
    banner.set_render_done(outcome, 10.0)
    assert banner.kind() == "success"
    banner.dismiss_button.click()
    assert "a.mp4" not in banner.text() and "plain news" not in banner.text()
    assert "no card" in banner.text() and tn("review.gaps_toggle", 1) in banner.text()
    assert banner.kind() == "attention"


def test_look_surah_and_episode_notices_come_and_go(banner) -> None:
    banner.set_look_notices(["image gone"])
    banner.set_surah_notice("no card")
    banner.set_episode_notice("no intro")
    assert banner.lines() == ["image gone", "no card", "no intro"]
    banner.set_look_notices([])
    banner.set_surah_notice(None)
    banner.set_episode_notice(None)
    assert banner.lines() == []
```

Move `test_the_warnings_strip_lists_five_gaps_then_counts_the_rest`, `test_the_warnings_strip_counts_a_single_gap_in_the_singular`, `test_the_warnings_strip_says_it_is_checking_until_the_first_result` out of `tests/test_review_widgets.py` (the tests above cover them; delete them).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_banner.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'qurantext.gui.review.banner'`

- [ ] **Step 3: Write `banner.py`**

```python
# src/qurantext/gui/review/banner.py
"""What needs a person's attention, under the toolbar, in a card that never moves the body.

Three kinds of thing: notices (the recording is missing, playback is off, a
read failed, the chosen surah has no card, the episode was not made), the
coverage check's result (stretches of speech no word covers, folded behind
a count), and a finished render, with Play and Show in folder. Empty, the
card collapses to a 4 px rule, so the body under it stays where it is.
Dismiss clears news — the render line and the plain notices — never state:
coverage, look, surah and episode notices come back from their checks.
"""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from qurantext.core.coverage import UncoveredSpeech
from qurantext.gui import theme
from qurantext.gui.i18n import clock, t, time_span, tn
from qurantext.gui.icons import icon, set_icon
from qurantext.gui.jobs import JobOutcome
from qurantext.gui.widgets import Card

__all__ = ["Banner"]

_MAX_GAP_LINES = 5
_KIND_ICON = {"info": "info", "attention": "circle-alert", "success": "film"}


class Banner(Card):
    """See the module docstring."""

    EMPTY_HEIGHT = 4
    jump_requested = Signal(float)
    play_requested = Signal(object)
    reveal_requested = Signal(object)
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.body.setContentsMargins(theme.SP_12, theme.SP_8, theme.SP_12, theme.SP_8)
        row = QHBoxLayout()
        row.setSpacing(theme.SP_8)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(QSize(20, 20))
        row.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)
        self.text_label = QLabel()
        self.text_label.setWordWrap(True)
        self.text_label.setTextFormat(Qt.TextFormat.RichText)
        self.text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.text_label.linkActivated.connect(self._on_link)
        row.addWidget(self.text_label, 1)
        self.play_button = QPushButton(t("render.play"))
        set_icon(self.play_button, "play", size=16)
        self.reveal_button = QPushButton(t("render.show"))
        set_icon(self.reveal_button, "folder", size=16)
        self.dismiss_button = QToolButton()
        self.dismiss_button.setAutoRaise(True)
        self.dismiss_button.setToolTip(t("banner.dismiss"))
        self.dismiss_button.setAccessibleName(t("banner.dismiss"))
        set_icon(self.dismiss_button, "x", size=16)
        for button in (self.play_button, self.reveal_button, self.dismiss_button):
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(row)
        self.play_button.clicked.connect(self._play)
        self.reveal_button.clicked.connect(self._reveal)
        self.dismiss_button.clicked.connect(self.dismiss)

        self._notices: list[str] = []
        self._look_notices: list[str] = []
        self._surah_notice: str | None = None
        self._episode_notice: str | None = None
        self._gaps: list[UncoveredSpeech] | None = None
        self._checking = False
        self._gaps_expanded = False
        self._render_line: str | None = None
        self._render_video: Path | None = None
        self._render_more: list[str] = []
        self._render()

    # -- the strip's old API ----------------------------------------------------------

    def add_notice(self, text: str) -> None:
        if text not in self._notices:
            self._notices.append(text)
            self._render()

    def set_look_notices(self, texts: list[str]) -> None:
        self._look_notices = list(dict.fromkeys(texts))
        self._render()

    def add_look_notice(self, text: str) -> None:
        if text not in self._look_notices:
            self._look_notices.append(text)
            self._render()

    def set_surah_notice(self, text: str | None) -> None:
        if text != self._surah_notice:
            self._surah_notice = text
            self._render()

    def set_episode_notice(self, text: str | None) -> None:
        text = text or None
        if text != self._episode_notice:
            self._episode_notice = text
            self._render()

    def set_gaps(self, gaps: list[UncoveredSpeech]) -> None:
        self._gaps = list(gaps)
        self._checking = False
        self._render()

    def set_checking(self, checking: bool) -> None:
        self._checking = checking
        self._render()

    # -- the render ----------------------------------------------------------------

    def set_render_done(self, outcome: JobOutcome, duration_s: float | None) -> None:
        """Say the video is ready, with Play and Show in folder; the episode line joins it."""
        name = outcome.video.name if outcome.video is not None else ""
        if duration_s is not None and duration_s > 0:
            self._render_line = t("render.done_banner_timed", name=name, duration=clock(duration_s, digits=0).rstrip("."))
        else:
            self._render_line = t("render.done_banner", name=name)
        self._render_video = outcome.video
        self._render_more = []
        if outcome.episode_video is not None:
            self._render_more.append(t("review.episode_written", name=outcome.episode_video.name))
        self._render()

    def clear_render(self) -> None:
        self._render_line, self._render_video, self._render_more = None, None, []
        self._render()

    def dismiss(self) -> None:
        """Clear the news; the state (coverage, look, surah, episode) stays."""
        self._notices = []
        self.clear_render()
        self.dismissed.emit()

    # -- gaps ----------------------------------------------------------------------

    @property
    def gaps_expanded(self) -> bool:
        return self._gaps_expanded

    def toggle_gaps(self) -> None:
        self._gaps_expanded = not self._gaps_expanded
        self._render()

    def jump_to(self, target: str) -> None:
        try:
            self.jump_requested.emit(float(target))
        except ValueError:
            pass

    # -- what it says --------------------------------------------------------------

    def lines(self) -> list[str]:
        """Every line as plain text, in the order shown."""
        lines = list(self._notices) + [n for n in self._look_notices if n not in self._notices]
        for extra in (self._surah_notice, self._episode_notice):
            if extra and extra not in lines:
                lines.append(extra)
        if self._render_line:
            lines.append(self._render_line)
            lines.extend(self._render_more)
        return lines

    def kind(self) -> str:
        if self._gaps or self._surah_notice or self._episode_notice or self._look_notices:
            return "attention"
        if self._render_line:
            return "success"
        if self._notices or self._checking or self._gaps is not None:
            return "info"
        return ""

    def text(self) -> str:
        return self.text_label.text()

    def _html(self) -> str:
        parts = [html.escape(line) for line in self.lines()]
        if self._gaps:
            count = len(self._gaps)
            arrow = "▾" if self._gaps_expanded else "▸"
            parts.append(f'<a href="gaps">{html.escape(tn("review.gaps_toggle", count))} {arrow}</a>')
            if self._gaps_expanded:
                jump = html.escape(t("review.jump"))
                for gap in self._gaps[:_MAX_GAP_LINES]:
                    span = time_span(gap.start, gap.end, digits=1)
                    text = t("review.gap", duration=gap.duration, span=span)
                    parts.append(f'&nbsp;&nbsp;{html.escape(text)} <a href="{gap.start:.3f}">{jump}</a>')
                hidden = count - _MAX_GAP_LINES
                if hidden > 0:
                    parts.append(f"&nbsp;&nbsp;{html.escape(tn('review.more_gaps', hidden))}")
        elif self._gaps is not None:
            parts.append(html.escape(t("review.covered")))
        elif self._checking:
            parts.append(html.escape(t("review.checking")))
        return "<br>".join(parts)

    def _render(self) -> None:
        content = self._html()
        self.text_label.setText(content)
        kind = self.kind()
        empty = not content
        self.icon_label.setVisible(not empty)
        if not empty:
            role = "accent" if kind in ("info", "success") else "text"
            pixmap = icon(_KIND_ICON.get(kind, "info"), role).pixmap(QSize(20, 20))
            if kind == "attention":
                from PySide6.QtGui import QPainter

                from qurantext.gui.colors import warning_color

                tinted = pixmap.copy()
                painter = QPainter(tinted)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(tinted.rect(), warning_color(self.palette()))
                painter.end()
                pixmap = tinted
            self.icon_label.setPixmap(pixmap)
        has_render = self._render_line is not None and self._render_video is not None
        self.play_button.setVisible(has_render)
        self.reveal_button.setVisible(has_render)
        self.dismiss_button.setVisible(bool(self._notices) or self._render_line is not None)
        self.text_label.setVisible(not empty)
        self.setProperty("empty", empty)
        self.setFixedHeight(self.EMPTY_HEIGHT) if empty else self.setMinimumHeight(0)
        if not empty:
            self.setMaximumHeight(16777215)
        self.updateGeometry()

    def _on_link(self, target: str) -> None:
        if target == "gaps":
            self.toggle_gaps()
        else:
            self.jump_to(target)

    def _play(self) -> None:
        if self._render_video is not None:
            self.play_requested.emit(self._render_video)

    def _reveal(self) -> None:
        if self._render_video is not None:
            self.reveal_requested.emit(self._render_video)
```

`setFixedHeight` then `setMinimumHeight(0)` plus the max reset: the empty state is a fixed 4 px rule; the non-empty state frees the height. The stylesheet (phase A) already draws `QFrame[card="true"]`; add in `theme.stylesheet` a rule `QFrame[card="true"][empty="true"] {{ border: none; background: {t.border}; border-radius: 2px; }}` so the empty banner reads as a hairline (one line in `theme.py`; add the assertion to `tests/test_theme.py::test_the_sheet_styles_what_fusion_cannot`).

- [ ] **Step 4: Swap it into the window, delete the strip**

In `window.py`: `from qurantext.gui.review.banner import Banner`; `self.warnings = Banner()`; fix the module docstring's mention of `WarningsStrip`. Delete `src/qurantext/gui/review/warnings_strip.py`. Nothing else in the window changes in this task (the window's `_announce_render` still shows the dialog until Task 8).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_banner.py tests/test_theme.py tests/test_review_widgets.py tests/test_review_window.py -q`
Expected: PASS. If a `test_review_window` test asserts a text the banner now folds behind the gaps count (`"2.0 s at 00:04.0–00:06.0" in window.warnings.text()` at lines ≈304, 349, 1135), add `window.warnings.toggle_gaps()` before the assertion.

- [ ] **Step 6: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/review/banner.py src/qurantext/gui/review/window.py src/qurantext/gui/theme.py tests/test_banner.py tests/test_theme.py tests/test_review_widgets.py tests/test_review_window.py
git rm -q src/qurantext/gui/review/warnings_strip.py
git commit -m "Replace the warnings strip with a banner that folds the coverage gaps, announces a finished render, and never moves the body

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: The shortcut sheet

**Files:**
- Create: `src/qurantext/gui/review/shortcut_sheet.py`
- Create: `tests/test_shortcut_sheet.py`

**Interfaces:**
- Consumes: `theme.font`, `i18n.t`.
- Produces: `BINDINGS: tuple[tuple[str, str, str], ...]` of `(group, keys, i18n_key)` with groups `playback | editing | file`; `ShortcutSheet(parent=None)` (a non-modal `QDialog`) with `rows() -> list[tuple[str, str]]`; `hint_html() -> str` (the status bar's short line, `t("review.hint")`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_shortcut_sheet.py
"""Every binding, in a sheet a person can open with ?."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from qurantext.gui.i18n import t  # noqa: E402
from qurantext.gui.language import apply_language  # noqa: E402
from qurantext.gui.review.shortcut_sheet import BINDINGS, ShortcutSheet, hint_html  # noqa: E402


def test_the_sheet_lists_every_binding_in_three_groups(qt_app) -> None:
    sheet = ShortcutSheet()
    rows = sheet.rows()
    assert len(rows) == len(BINDINGS)
    keys = [row[0] for row in rows]
    for expected in ("Space", "←", "→", "[", "]", ",", ".", "Ctrl+Z", "Ctrl+Shift+Z", "Ctrl+S", "?"):
        assert any(expected in key for key in keys), expected
    assert {group for group, _, _ in BINDINGS} == {"playback", "editing", "file"}
    assert sheet.windowTitle().strip("‎‏") == t("review.shortcuts.title")
    assert not sheet.isModal()
    sheet.deleteLater()


def test_every_binding_reads_in_arabic_too(qt_app) -> None:
    apply_language(qt_app, "ar")
    try:
        sheet = ShortcutSheet()
        assert all(action for _, action in sheet.rows())
        sheet.deleteLater()
    finally:
        apply_language(qt_app, "en")


def test_the_hint_is_short_and_links_to_the_sheet() -> None:
    assert 'href="shortcuts"' in hint_html()
    assert len(hint_html()) < len(t("review.hint")) + 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_shortcut_sheet.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `shortcut_sheet.py`**

```python
# src/qurantext/gui/review/shortcut_sheet.py
"""Every key the review window answers to, on one sheet, opened with ?."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QGridLayout, QLabel, QVBoxLayout, QWidget

from qurantext.gui import theme
from qurantext.gui.i18n import t
from qurantext.gui.widgets import SectionHeader

__all__ = ["BINDINGS", "ShortcutSheet", "hint_html"]

#: ``(group, keys as shown, i18n key of the action)``; the window's bindings are checked against it.
BINDINGS: tuple[tuple[str, str, str], ...] = (
    ("playback", "Space", "review.key.play"),
    ("playback", "←", "review.key.next_word"),
    ("playback", "→", "review.key.prev_word"),
    ("playback", "", "review.key.scrub"),
    ("editing", "[", "review.key.set_start"),
    ("editing", "]", "review.key.set_end"),
    ("editing", ",", "review.key.nudge_later"),
    ("editing", ".", "review.key.nudge_earlier"),
    ("editing", "Shift+, / Shift+.", "review.key.nudge_fine"),
    ("editing", "Shift+drag", "review.key.ripple"),
    ("editing", "Ctrl+drag", "review.key.detach"),
    ("editing", "", "review.key.change_ayah"),
    ("editing", "Ctrl+Z", "review.key.undo"),
    ("editing", "Ctrl+Shift+Z", "review.key.redo"),
    ("file", "Ctrl+S", "review.key.save"),
    ("file", "?", "review.key.sheet"),
)


def hint_html() -> str:
    """The status bar's short line, with a link that opens the sheet."""
    return t("review.hint")


class ShortcutSheet(QDialog):
    """Three groups in a two-column grid: the keys, then what they do."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("review.shortcuts.title"))
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        column = QVBoxLayout(self)
        column.setSpacing(theme.SP_12)
        self._rows: list[tuple[str, str]] = []
        for group in ("playback", "editing", "file"):
            column.addWidget(SectionHeader(t(f"review.shortcuts.{group}")))
            grid = QGridLayout()
            grid.setHorizontalSpacing(theme.SP_16)
            grid.setVerticalSpacing(theme.SP_4)
            row = 0
            for own_group, keys, key in BINDINGS:
                if own_group != group:
                    continue
                keys_label = QLabel(keys)
                keys_label.setFont(theme.font("clock"))
                keys_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
                action = QLabel(t(key))
                action.setWordWrap(True)
                grid.addWidget(keys_label, row, 0, Qt.AlignmentFlag.AlignTop)
                grid.addWidget(action, row, 1)
                self._rows.append((keys, t(key)))
                row += 1
            grid.setColumnStretch(1, 1)
            column.addLayout(grid)
        column.addStretch(1)

    def rows(self) -> list[tuple[str, str]]:
        return list(self._rows)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_shortcut_sheet.py -q`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/review/shortcut_sheet.py tests/test_shortcut_sheet.py
git commit -m "Add a sheet that lists every review shortcut, opened with ?

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: The transport, and the selection bar as a label

**Files:**
- Create: `src/qurantext/gui/review/transport.py`
- Modify: `src/qurantext/gui/review/selection_bar.py`
- Create: `tests/test_transport.py`
- Modify: `tests/test_review_widgets.py:774` (the selection-bar test keeps `label`; drop button assertions there if any)

**Interfaces:**
- Consumes: `icons.set_icon(…, mirror=False)`, `theme.font("clock")`, `i18n.clock/t`, `player.RATES`, `selection_bar.NUDGE_S`.
- Produces: `Transport(rates: tuple[float, ...], parent=None)` with `prev_word_button`, `play_button`, `next_word_button`, `time_label`, `rate_buttons: dict[float, QPushButton]`, `minus_button`, `snap_button`, `plus_button`, `show_ayah_button`; signals `play_toggled`, `step_requested(int)`, `rate_changed(float)`, `nudge_requested(float)`, `snap_requested`, `show_ayah_requested`; `set_playing(bool)`, `set_time(seconds: float)`, `set_rate(rate: float)`, `set_selection(has: bool)`, `set_lecture(bool)`. `SelectionBar(transport)` keeps `label`, `show_word(word)`, and properties `minus_button`, `plus_button`, `snap_button` returning the transport's; its `nudge_requested` / `snap_requested` signals are removed (the window listens to the transport).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_transport.py
"""The transport row: every playback and nudge action as an icon button, the rate in one click."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import QSize, Qt  # noqa: E402

from qurantext.gui import icons, theme  # noqa: E402
from qurantext.gui.i18n import clock, t  # noqa: E402
from qurantext.gui.review.player import RATES  # noqa: E402
from qurantext.gui.review.selection_bar import NUDGE_S, SelectionBar  # noqa: E402
from qurantext.gui.review.transport import Transport  # noqa: E402


@pytest.fixture()
def transport(qt_app):
    theme.apply_theme(qt_app, "light")
    made = Transport(RATES)
    yield made
    made.deleteLater()


def test_the_buttons_carry_icons_and_fire_their_signals(transport) -> None:
    seen = []
    transport.step_requested.connect(lambda d: seen.append(("step", d)))
    transport.play_toggled.connect(lambda: seen.append("play"))
    transport.nudge_requested.connect(lambda d: seen.append(("nudge", round(d, 3))))
    transport.snap_requested.connect(lambda: seen.append("snap"))
    for button, name in (
        (transport.prev_word_button, "skip-back"),
        (transport.play_button, "play"),
        (transport.next_word_button, "skip-forward"),
        (transport.minus_button, "chevron-right"),
        (transport.snap_button, "crosshair"),
        (transport.plus_button, "chevron-left"),
    ):
        assert button.property("qalun.icon")[0] == name, name
    transport.set_selection(True)
    transport.prev_word_button.click()
    transport.play_button.click()
    transport.next_word_button.click()
    transport.minus_button.click()
    transport.snap_button.click()
    transport.plus_button.click()
    assert seen == [("step", -1), "play", ("step", 1), ("nudge", -NUDGE_S), "snap", ("nudge", NUDGE_S)]


def test_the_rate_is_a_segmented_choice(transport) -> None:
    seen = []
    transport.rate_changed.connect(seen.append)
    assert list(transport.rate_buttons) == list(RATES)
    assert transport.rate_buttons[1.0].isChecked()
    transport.rate_buttons[0.5].click()
    assert seen == [0.5] and not transport.rate_buttons[1.0].isChecked()
    transport.set_rate(0.75)
    assert transport.rate_buttons[0.75].isChecked() and seen == [0.5]


def test_playing_and_time_and_selection_show(transport) -> None:
    transport.set_playing(True)
    assert transport.play_button.property("qalun.icon")[0] == "pause"
    assert transport.play_button.toolTip().startswith(t("review.pause"))
    transport.set_time(96.5)
    assert transport.time_label.text() == clock(96.5)
    transport.set_selection(False)
    assert not transport.minus_button.isEnabled() and not transport.snap_button.isEnabled()


def test_the_nudge_chevrons_keep_their_direction_in_arabic(qt_app) -> None:
    ltr = Transport(RATES)
    minus_ltr = ltr.minus_button.icon().pixmap(QSize(16, 16)).toImage()
    qt_app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    try:
        icons.clear_cache()
        rtl = Transport(RATES)
        assert rtl.minus_button.icon().pixmap(QSize(16, 16)).toImage() == minus_ltr
        assert rtl.prev_word_button.icon().pixmap(QSize(16, 16)).toImage() != ltr.prev_word_button.icon().pixmap(QSize(16, 16)).toImage()
        rtl.deleteLater()
    finally:
        qt_app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        icons.clear_cache()
    ltr.deleteLater()


def test_the_selection_bar_delegates_its_buttons_to_the_transport(transport) -> None:
    bar = SelectionBar(transport)
    assert bar.minus_button is transport.minus_button
    assert bar.snap_button is transport.snap_button
    bar.show_word(None)
    assert bar.label.text() == t("review.no_selection")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_transport.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `transport.py`**

```python
# src/qurantext/gui/review/transport.py
"""The row under the timeline: play, step, the clock, the rate, and the nudges.

The buttons only ask; the window turns each signal into a session call. The
nudge chevrons point the way the edge moves on the always-right-to-left
timeline, so they are not mirrored with the language.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QWidget

from qurantext.gui import theme
from qurantext.gui.i18n import clock, t
from qurantext.gui.icons import set_icon
from qurantext.gui.review.selection_bar import NUDGE_S

__all__ = ["Transport"]


class Transport(QWidget):
    """See the module docstring."""

    play_toggled = Signal()
    step_requested = Signal(int)
    rate_changed = Signal(float)
    nudge_requested = Signal(float)
    snap_requested = Signal()
    show_ayah_requested = Signal()

    def __init__(self, rates: tuple[float, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SP_8)

        self.prev_word_button = self._button("", "skip-back", t("review.prev_word"))
        self.play_button = self._button(t("review.play"), "play", t("review.play"))
        self.next_word_button = self._button("", "skip-forward", t("review.next_word"))
        self.time_label = QLabel(clock(0.0))
        self.time_label.setFont(theme.font("clock"))
        self.time_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        for widget in (self.prev_word_button, self.play_button, self.next_word_button, self.time_label):
            row.addWidget(widget)

        row.addSpacing(theme.SP_8)
        self._rate_group = QButtonGroup(self)
        self._rate_group.setExclusive(True)
        self.rate_buttons: dict[float, QPushButton] = {}
        for rate in rates:
            button = QPushButton(t("review.rate", rate=rate))
            button.setCheckable(True)
            button.setProperty("segment", True)
            button.setToolTip(t("review.rate_label"))
            self._rate_group.addButton(button)
            self.rate_buttons[rate] = button
            row.addWidget(button)
        self.rate_buttons[rates[0]].setChecked(True)
        self._rate_group.buttonClicked.connect(self._on_rate_clicked)

        row.addSpacing(theme.SP_8)
        nudges = QWidget()
        nudges.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        nudge_row = QHBoxLayout(nudges)
        nudge_row.setContentsMargins(0, 0, 0, 0)
        nudge_row.setSpacing(theme.SP_4)
        self.plus_button = QPushButton(t("review.plus"))
        set_icon(self.plus_button, "chevron-left", size=16, mirror=False)
        self.snap_button = QPushButton(t("review.snap"))
        set_icon(self.snap_button, "crosshair", size=16)
        self.minus_button = QPushButton(t("review.minus"))
        set_icon(self.minus_button, "chevron-right", size=16, mirror=False)
        # Left to right on screen: +50 (later, moves left) · snap · −50 (earlier, moves right).
        for button in (self.plus_button, self.snap_button, self.minus_button):
            nudge_row.addWidget(button)
        row.addWidget(nudges)

        self.show_ayah_button = QPushButton(t("review.show_ayah"))
        self.show_ayah_button.setToolTip(t("review.show_ayah.tip"))
        set_icon(self.show_ayah_button, "book-open", size=16)
        row.addSpacing(theme.SP_8)
        row.addWidget(self.show_ayah_button)
        row.addStretch(1)

        self.prev_word_button.clicked.connect(lambda: self.step_requested.emit(-1))
        self.next_word_button.clicked.connect(lambda: self.step_requested.emit(1))
        self.play_button.clicked.connect(self.play_toggled)
        self.minus_button.clicked.connect(lambda: self.nudge_requested.emit(-NUDGE_S))
        self.plus_button.clicked.connect(lambda: self.nudge_requested.emit(NUDGE_S))
        self.snap_button.clicked.connect(self.snap_requested)
        self.show_ayah_button.clicked.connect(self.show_ayah_requested)
        self.set_selection(False)
        self.set_lecture(False)

    @staticmethod
    def _button(text: str, icon_name: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        set_icon(button, icon_name)
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        return button

    def _on_rate_clicked(self, button: QPushButton) -> None:
        for rate, own in self.rate_buttons.items():
            if own is button:
                self.rate_changed.emit(rate)
                return

    def set_playing(self, playing: bool) -> None:
        set_icon(self.play_button, "pause" if playing else "play")
        self.play_button.setText(t("review.pause") if playing else t("review.play"))
        self.play_button.setToolTip(t("review.tip", action=self.play_button.text(), keys=t("review.key_space")))

    def set_time(self, seconds: float) -> None:
        self.time_label.setText(clock(seconds))

    def set_rate(self, rate: float) -> None:
        button = self.rate_buttons.get(rate)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def set_selection(self, has: bool) -> None:
        for button in (self.minus_button, self.plus_button, self.snap_button):
            button.setEnabled(has)

    def set_lecture(self, lecture: bool) -> None:
        self.show_ayah_button.setVisible(lecture)
```

`selection_bar.py` becomes:

```python
class SelectionBar(QWidget):
    """The selected word and its times; the nudge buttons live on the transport now."""

    def __init__(self, transport: Transport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._transport = transport
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setFont(theme.font("section"))
        row.addWidget(self.label, 1)
        self.show_word(None)

    @property
    def minus_button(self) -> QPushButton:
        return self._transport.minus_button

    @property
    def plus_button(self) -> QPushButton:
        return self._transport.plus_button

    @property
    def snap_button(self) -> QPushButton:
        return self._transport.snap_button

    def show_word(self, word: TimelineWord | None) -> None:
        self._transport.set_selection(word is not None)
        if word is None:
            self.label.setText(t("review.no_selection"))
            return
        self.label.setText(t("review.selected", word=word.text, span=time_span(word.start, word.end, sep=" → ")))
```

(`NUDGE_S` stays in `selection_bar.py`; `transport.py` imports it from there, so there is no cycle: `selection_bar` imports `Transport` only under `TYPE_CHECKING`.) The existing `test_the_selection_bar_shows_the_span_as_one_value` in `tests/test_review_widgets.py` builds `SelectionBar()` with no transport: give it `SelectionBar(Transport(RATES))`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_transport.py tests/test_review_widgets.py -q`
Expected: PASS (`test_review_window` and `test_rtl` break until Task 8 rewires the window; do not run them here)

- [ ] **Step 5: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/review/transport.py src/qurantext/gui/review/selection_bar.py tests/test_transport.py tests/test_review_widgets.py
git commit -m "Add the transport row with icon buttons, a one-click rate and the nudges, and leave the selection bar the word and its times

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Waveform, word strip and segment table styling

**Files:**
- Modify: `src/qurantext/gui/review/waveform_view.py` (`paintEvent`, `_paint_bars`, `_GAP_COLOR`), `src/qurantext/gui/review/word_strip.py` (`_paint_word`, `_paint_handle`, `sizeHint`, `minimumSizeHint`, `EDGE_PX`/`HANDLE_PX`), `src/qurantext/gui/review/segment_list.py` (`__init__`, `_fill_row`, `highlight_at`, `_paint_row`; add `_PlayheadRuleDelegate`)
- Modify: `tests/test_review_widgets.py` (the playhead-row test at ≈680 and new ones)

**Interfaces:**
- Consumes: `theme.current_tokens()`, `colors.warning_color/playhead_color`, `icons.icon`.
- Produces: `WaveformView.set_current_word(start: float | None, end: float | None)` (the window calls it from `_show_time`); `WordStrip.HANDLE_PX = 6`; `SegmentList.playhead_row() -> int | None`; `SegmentList.ROW_HEIGHT = 32`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_review_widgets.py` (its helpers build a session and a table; reuse `_session`/`_table` or whatever the file names them):

```python
def test_the_strip_fills_the_selected_word_with_the_accent(qt_app) -> None:
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter

    from qurantext.gui import theme

    theme.apply_theme(qt_app, "light")
    strip, session = _strip(qt_app)  # the module's helper at line ≈232; check what it returns and unpack accordingly
    strip.resize(600, 44)
    words = session.words()
    strip.select(words[0].ref)
    image = strip.grab().toImage()
    x = int((strip._viewport.x_for(words[0].start, 600) + strip._viewport.x_for(words[0].end, 600)) / 2)
    assert image.pixelColor(x, 22).name().upper() == theme.LIGHT.accent.upper()
    assert strip.minimumSizeHint().height() >= 40 and strip.HANDLE_PX == 6


def test_the_waveform_draws_the_current_word_stronger(qt_app) -> None:
    from qurantext.gui import theme
    from qurantext.gui.review.viewport import Viewport
    from qurantext.gui.review.waveform_view import WaveformView
    from qurantext.core.waveform import Peaks
    import numpy as np

    theme.apply_theme(qt_app, "light")
    viewport = Viewport()
    viewport.set_duration(10.0)
    viewport.set_window(0.0, 10.0)
    view = WaveformView(viewport)
    view.resize(100, 50)
    view.set_peaks(Peaks(mins=np.full(100, -0.9), maxs=np.full(100, 0.9), rate=10.0))
    view.set_current_word(2.0, 3.0)
    image = view.grab().toImage()
    inside = image.pixelColor(int(viewport.x_for(2.5, 100)), 25)
    outside = image.pixelColor(int(viewport.x_for(7.5, 100)), 25)
    assert inside.alpha() == 255 and inside != outside
    assert outside.name().upper() != theme.LIGHT.panel.upper()  # bars are drawn there too, fainter


def test_the_table_marks_the_playhead_row_with_a_rule_and_shows_icons(qt_app) -> None:
    from PySide6.QtCore import Qt

    table = _table(qt_app)  # build one: a SegmentList over the lecture session the module's other table tests use (grep "SegmentList(" there)
    assert table.ROW_HEIGHT == 32 and table.alternatingRowColors()
    assert not table.item(0, 0).icon().isNull() and not table.item(table.rowCount() - 1, 0).icon().isNull()
    table.highlight_at(2.5)
    assert table.playhead_row() == 1
    assert table.item(1, 2).background().style() == Qt.BrushStyle.NoBrush  # a rule, not a tint
    retimed = [table.item(r, 3).text() for r in range(table.rowCount())]
    assert "0" not in retimed
```

Update `test_the_playhead_row_is_marked_without_being_selected` (≈680) to assert `table.playhead_row() == 1` instead of a brush. Check which helpers the module really has (`grep -n "^def _" tests/test_review_widgets.py`) and use those names.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py -q -k "accent or stronger or rule_and_shows"`
Expected: FAIL (`AttributeError: HANDLE_PX` / `set_current_word` / `ROW_HEIGHT`)

- [ ] **Step 3: Waveform**

In `waveform_view.py`: add `self._current: tuple[float, float] | None = None` and

```python
    def set_current_word(self, start: float | None, end: float | None) -> None:
        """The word under the playhead, drawn at full strength; None for none."""
        self._current = (float(start), float(end)) if start is not None and end is not None else None
        self.update()
```

In `paintEvent`: fill with `palette.base()` (the panel) instead of `window()`; draw placeholders in `QColor(tokens.secondary)`; call `self._paint_bars(painter, peaks, width, height)` which now paints each column in `QColor(tokens.accent)` with alpha 140 outside the current word and 255 inside (`t = self._viewport.t_for(x + 0.5, width)`; inside when `start <= t < end`); gaps as `attention` (from `warning_color(palette)`) at alpha 64 with a 1 px outline of the same colour at alpha 255; playhead pen width 2. Delete `_GAP_COLOR`.

- [ ] **Step 4: Word strip**

In `word_strip.py`: `HANDLE_PX = 6`; `sizeHint` → `QSize(600, 44)`, add `minimumSizeHint` → `QSize(200, 40)`; in `_paint_word` draw `painter.drawRoundedRect(rect, 4, 4)` with pen `QColor(tokens.border)` (1 px) and, when selected, `painter.setBrush(QColor(tokens.accent))` before the rect and text colour `tokens.on_accent`; the under-playhead outline becomes a 2 px `accent` pen (not red: the ruler and waveform carry the red playhead); the edited bar stays amber; `_paint_handle` uses `HANDLE_PX` for its width. Keep `EDGE_PX = 8` for hit-testing.

- [ ] **Step 5: Segment table**

In `segment_list.py`: `ROW_HEIGHT = 32`; in `__init__`: `self.verticalHeader().setDefaultSectionSize(self.ROW_HEIGHT)`, `self.setAlternatingRowColors(True)`, `self.setItemDelegateForColumn(_COLUMN_REF, _PlayheadRuleDelegate(self))`; in `_fill_row`: `ref_item.setIcon(icon("book-open" if kind == CARD else "mic", "secondary"))` and the retimed text `str(count) if count else ""`; `highlight_at` keeps `_playhead_row` and the scroll but calls `self.viewport().update()` instead of `_paint_row` (delete `_paint_row` and the tint); add `def playhead_row(self) -> int | None: return self._playhead_row`. The delegate:

```python
class _PlayheadRuleDelegate(QStyledItemDelegate):
    """A 3 px accent rule on the leading edge of the playhead row's first cell."""

    def paint(self, painter, option, index) -> None:  # noqa: D102 - Qt override
        super().paint(painter, option, index)
        table = self.parent()
        if not isinstance(table, SegmentList) or index.row() != table.playhead_row():
            return
        rect = option.rect
        x = rect.right() - 2 if table.isRightToLeft() else rect.left()
        painter.fillRect(x, rect.top(), 3, rect.height(), QColor(theme.current_tokens().accent))
```

(`from PySide6.QtWidgets import QStyledItemDelegate`; `from qurantext.gui import theme`; `from qurantext.gui.icons import icon`.) Any test in `tests/test_review_window.py` reading the retimed column as `"0"` reads `""` now.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py tests/test_time_ruler.py -q`
Expected: PASS

- [ ] **Step 7: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/review/waveform_view.py src/qurantext/gui/review/word_strip.py src/qurantext/gui/review/segment_list.py tests/test_review_widgets.py
git commit -m "Draw the waveform in the accent with the current word stronger, round the word boxes, and mark the table's playhead row with a rule and its rows with icons

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: The preview's fit / actual toggle and the full-frame view

**Files:**
- Modify: `src/qurantext/gui/review/frame_view.py` (add `set_fit`, `fit`, `full_frame_requested`, `mouseDoubleClickEvent`; add `FullFrameView`)
- Create: `tests/test_frame_view.py`

**Interfaces:**
- Consumes: `render_frame_pillow`, `session.frame_inputs`, `theme`, `Prefs.preview_fit`.
- Produces: `FrameView.set_fit(fit: bool)`, `FrameView.fit -> bool`, `FrameView.full_frame_requested = Signal(float)` (the time shown), `FrameView.preset_size -> QSize`; `FullFrameView(session, t, portrait, parent=None)` (a frameless top-level `QWidget`) with `close_requested`, `shown_size() -> QSize`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_frame_view.py
"""The preview: fit or actual size, and the frame full size on a double-click."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import QEvent, QPoint, QSize, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402

from qurantext.gui.review.frame_view import FrameView, FullFrameView  # noqa: E402
from tests.qt_helpers import spin  # noqa: E402


def test_fit_follows_the_widget_and_actual_pins_the_preset_size(qt_app, review_session) -> None:
    view = FrameView(review_session, portrait=True)
    assert view.fit is True and view.preset_size == QSize(270, 480)
    view.set_fit(False)
    assert view.fit is False
    assert view.minimumSize() == QSize(270, 480) and view.maximumSize() == QSize(270, 480)
    view.set_fit(True)
    assert view.minimumSize() == QSize(135, 240)
    view.deleteLater()


def test_a_double_click_asks_for_the_full_frame_at_the_shown_time(qt_app, review_session) -> None:
    view = FrameView(review_session, portrait=True)
    view.show_at(3.0, force=True)
    asked = []
    view.full_frame_requested.connect(asked.append)
    event = QMouseEvent(
        QEvent.Type.MouseButtonDblClick, QPoint(10, 10), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    view.mouseDoubleClickEvent(event)
    assert asked == [3.0]
    view.deleteLater()


def test_the_full_frame_view_fits_the_screen_keeps_the_shape_and_closes_on_escape(qt_app, review_session) -> None:
    """Review Focus 4: opened at the clicked time, closed by Escape."""
    full = FullFrameView(review_session, 3.0, portrait=True)
    full.show()
    spin(100)
    shown = full.shown_size()
    screen = qt_app.primaryScreen().availableGeometry()
    assert shown.height() <= screen.height() and shown.width() <= screen.width()
    assert abs(shown.width() / shown.height() - 270 / 480) < 0.02
    closed = []
    full.close_requested.connect(lambda: closed.append(1))
    full.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert closed == [1] and not full.isVisible()
    full.deleteLater()


def test_the_full_frame_view_closes_on_a_click_too(qt_app, review_session) -> None:
    full = FullFrameView(review_session, 0.0, portrait=False)
    full.show()
    spin(50)
    full.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPoint(5, 5), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert not full.isVisible()
    full.deleteLater()
```

`review_session` is a fixture to add to this module: a `ReviewSession` over the one-card project the other test modules build (`tests/test_review_window.py::_project`); copy that helper.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_frame_view.py -q`
Expected: FAIL with `ImportError: cannot import name 'FullFrameView'`

- [ ] **Step 3: `FrameView` changes**

```python
    full_frame_requested = Signal(float)

    @property
    def preset_size(self) -> QSize:
        return QSize(self._width, self._height)

    @property
    def fit(self) -> bool:
        return self._fit

    def set_fit(self, fit: bool) -> None:
        """Fit: scale down to the widget. Actual: the preset's preview size, exactly."""
        self._fit = bool(fit)
        if self._fit:
            self.setMinimumSize(self._width // 2, self._height // 2)
            self.setMaximumSize(16777215, 16777215)
        else:
            self.setMinimumSize(self._width, self._height)
            self.setMaximumSize(self._width, self._height)
        self.updateGeometry()
        self.show_at(self._last_t, force=True)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.full_frame_requested.emit(self._last_t)
            return
        super().mouseDoubleClickEvent(event)
```

(`self._fit = True` in `__init__` before the existing `setMinimumSize`; `Signal` from QtCore; `FrameView` must be a `QLabel` subclass that inherits `QObject` signals — it is.) `self.setToolTip(i18n.t("review.full_frame"))` in `__init__`.

- [ ] **Step 4: `FullFrameView`**

```python
class FullFrameView(QWidget):
    """The frame at one moment, as large as the screen allows; Escape, a click or losing focus closes it."""

    close_requested = Signal()

    def __init__(self, session: ReviewSession, t: float, *, portrait: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
        self.setPalette(palette)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        screen = (parent.screen() if parent is not None else QGuiApplication.primaryScreen()).availableGeometry()
        self.setGeometry(screen)
        preset_w, preset_h = (_PORTRAIT_SIZE if portrait else _LANDSCAPE_SIZE)
        scale = min(screen.width() / preset_w, screen.height() / preset_h)
        self._shown = QSize(max(1, int(preset_w * scale)), max(1, int(preset_h * scale)))
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        self._render(session, t)

    def shown_size(self) -> QSize:
        return self._shown

    def _render(self, session: ReviewSession, t: float) -> None:
        card, caption, reserve_band = session.frame_inputs(t)
        try:
            frame = render_frame_pillow(
                t, card, self._shown.width(), self._shown.height(), DEFAULT_FONT_PATH,
                caption_text=caption["text"] if caption else "",
                caption_word_timings=caption["word_timings"] if caption else None,
                reserve_caption_band=reserve_band, look=session.look,
            )
        except Exception as error:  # noqa: BLE001 - shown, not raised
            self._label.setText(i18n.t("frame.error", details=str(error)))
            return
        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        height, width, _ = rgb.shape
        image = QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888)
        self._label.setPixmap(QPixmap.fromImage(image.copy()))

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            self._leave()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._leave()

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().focusOutEvent(event)
        self._leave()

    def _leave(self) -> None:
        if self.isVisible():
            self.hide()
            self.close_requested.emit()
```

(Imports: `QGuiApplication, QImage, QPalette, QPixmap, QColor` from QtGui, `QVBoxLayout, QWidget` from QtWidgets, `Signal` from QtCore; `_PORTRAIT_SIZE`/`_LANDSCAPE_SIZE` are the module's constants; `np` is already imported.) Review Focus 5's scrolling of the preview in Actual size is the window's job (Task 8 wraps the preview in a scroll area).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_frame_view.py -q`
Expected: PASS

- [ ] **Step 6: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/review/frame_view.py tests/test_frame_view.py
git commit -m "Let the preview fit its column or show the preset's size, and open the frame full size on a double-click

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: The window: two columns, grouped toolbar, everything wired

**Files:**
- Modify: `src/qurantext/gui/review/window.py` (`_build`, `_build_look_panel`, `_build_timeline`, `_wire`, `_bind_keys`, `_set_tips`, `_elide_hint`/`eventFilter`, `_show_time`, `_on_playing_changed`, `_on_rate`, `_show_selection`, `_set_render_running`, `_start_render`, `_announce_render`, `_sync_state`; add `show_shortcuts`, `_show_full_frame`, `_set_preview_fit`, `_play_video`)
- Modify: `src/qurantext/gui/i18n.py` (remove `review.shortcuts` in both languages)
- Modify: `tests/test_review_window.py`, `tests/test_rtl.py`, `tests/test_gui.py` (adaptations named below)

**Interfaces:**
- Consumes: Tasks 2–7.
- Produces: `ReviewWindow.ruler: TimeRuler`, `transport: Transport`, `fit_button`, `actual_button` (checkable `QToolButton`s), `frame_scroll: QScrollArea`, `help_button: QToolButton`, `shortcut_sheet: ShortcutSheet | None`, `zoom_readout: QLabel`, `zoom_in_button`, `zoom_out_button`, `_splitter: QSplitter` (horizontal), `left_column: QWidget`, `right_column: QWidget`, `show_shortcuts()`, `_show_full_frame(t)`, `_full_frame: FullFrameView | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_review_window.py` (use its `_window(qt_app, tmp_path)` and its lecture helper):

```python
def test_two_columns_preview_and_look_left_timeline_and_table_right(qt_app, tmp_path) -> None:
    from PySide6.QtWidgets import QSplitter

    window = _window(qt_app, tmp_path)
    try:
        window.resize(1280, 800)
        window.show()
        spin(100)
        assert isinstance(window._splitter, QSplitter) and window._splitter.orientation() == Qt.Orientation.Horizontal
        assert window.frame_scroll.isAncestorOf(window.frame_view) and window.left_column.isAncestorOf(window.look_scroll)
        assert window.right_column.isAncestorOf(window.ruler) and window.right_column.isAncestorOf(window.segment_list)
        look_top = window.look_scroll.mapTo(window, window.look_scroll.rect().topLeft()).y()
        frame_bottom = window.frame_scroll.mapTo(window, window.frame_scroll.rect().bottomLeft()).y()
        assert look_top >= frame_bottom
        table_bottom = window.segment_list.mapTo(window, window.segment_list.rect().bottomLeft()).y()
        assert window.height() - table_bottom < 60  # the table reaches the status bar
    finally:
        window.close()
        window.deleteLater()


def test_a_lecture_at_1280_by_800_shows_eight_rows(qt_app, tmp_path) -> None:
    window = _lecture_window(qt_app, tmp_path)  # the module's helper at line ≈1519; give it ≥ 12 captions if it has fewer
    window.resize(1280, 800)
    window.show()
    spin(100)
    visible = window.segment_list.viewport().height() // window.segment_list.ROW_HEIGHT
    assert visible >= 8


def test_the_transport_drives_steps_rate_and_nudges(qt_app, tmp_path) -> None:
    window = _window(qt_app, tmp_path)
    try:
        words = window.session.words()
        window.strip.select(words[0].ref)
        window.transport.next_word_button.click()
        assert window.strip.selected == words[1].ref
        window.transport.rate_buttons[0.5].click()
        assert window.player.rate() == 0.5
        end_before = window.session.word(window.strip.selected).end
        window.selection_bar.plus_button.click()  # the old name still reaches the transport's button
        assert window.session.word(window.strip.selected).end == pytest.approx(end_before + 0.05)
        window.player.play()
        assert window.transport.play_button.property("qalun.icon")[0] == "pause"
        assert window.play_button is window.transport.play_button and window.time_label is window.transport.time_label
    finally:
        window.close()
        window.deleteLater()


def test_a_finished_render_goes_on_the_banner_not_a_dialog(qt_app, tmp_path, monkeypatch) -> None:
    from qurantext.gui.jobs import JobOutcome

    window = _window(qt_app, tmp_path)
    try:
        boxes = []
        monkeypatch.setattr("qurantext.gui.review.window.QMessageBox.exec", lambda self: boxes.append(1) or 0)
        outcome = JobOutcome(matches=tmp_path / "m.json", video=tmp_path / "a.mp4", cards=1)
        window._announce_render(outcome)
        assert boxes == [] and "a.mp4" in window.warnings.text()
        assert window.warnings.play_button.isVisibleTo(window)
        window._say_render("failed", "boom")
        assert boxes == [1]
    finally:
        window.close()
        window.deleteLater()


def test_question_mark_opens_the_sheet_once_and_leaves_an_editor_alone(qt_app, tmp_path) -> None:
    """Review Focus 3: ? inside a caption editor types a ?."""
    from PySide6.QtWidgets import QAbstractItemView

    window = _lecture_window(qt_app, tmp_path)
    window.show_shortcuts()
    sheet = window.shortcut_sheet
    assert sheet is not None and sheet.isVisible()
    window.show_shortcuts()
    assert window.shortcut_sheet is sheet
    sheet.hide()
    table = window.segment_list
    row = table.rowCount() - 1
    table.setCurrentCell(row, 2)
    table.edit(table.model().index(row, 2))
    assert table.state() == QAbstractItemView.State.EditingState
    editor = qt_app.focusWidget()
    QTest.keyClick(editor, "?")
    assert not sheet.isVisible() and "?" in editor.text()
    table.closePersistentEditor(table.item(row, 2))


def test_the_fit_toggle_round_trips_through_prefs(qt_app, tmp_path, prefs) -> None:
    from qurantext.gui.review.window import ReviewWindow
    from qurantext.gui.review.player import FakePlayer

    window = ReviewWindow(_project(tmp_path), player=FakePlayer(10.0), prefs=prefs)
    try:
        assert window.fit_button.isChecked() and window.frame_view.fit
        window.actual_button.click()
        assert prefs.preview_fit is False and not window.frame_view.fit
        assert not window.frame_scroll.widgetResizable()
    finally:
        window.close()
        window.deleteLater()


def test_a_double_click_opens_the_full_frame_and_escape_closes_it(qt_app, tmp_path) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    window = _window(qt_app, tmp_path)
    try:
        window.show()
        window.player.play()
        window.frame_view.full_frame_requested.emit(1.0)
        full = window._full_frame
        assert full is not None and full.isVisible() and window.player.is_playing()
        full.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        assert not full.isVisible()
    finally:
        window.close()
        window.deleteLater()


def test_the_zoom_readout_says_the_span_and_the_buttons_step(qt_app, tmp_path) -> None:
    from qurantext.gui.i18n import tn

    window = _window(qt_app, tmp_path)
    try:
        window._set_duration(120.0)
        window.viewport.set_window(0.0, 20.0)
        assert window.zoom_readout.text() == tn("review.span", 20)
        before = window.zoom_slider.value()
        window.zoom_in_button.click()
        assert window.zoom_slider.value() == min(100, before + 10)
    finally:
        window.close()
        window.deleteLater()
```

(`QTest` from `PySide6.QtTest` — `keyClick` is fine; it is `qWait` that is banned.) Adapt existing tests: `window.rate_combo` → `window.transport.rate_buttons`; `window.hint_label.text() == t("review.shortcuts")` → `== hint_html()`; `test_the_shortcut_hint_elides…` reads the tooltip no more (the hint is short) → assert the hint's link text; tests that `monkeypatch _announce_render` keep working; `test_rtl` additions:

```python
def test_the_ruler_runs_right_to_left_and_the_transport_mirrors(qt_app, review_window) -> None:
    labels = review_window.ruler.labels()
    assert labels[0][1] == "00:00" and labels[0][0] > labels[-1][0]
    t = review_window.transport
    assert t.play_button.x() > t.rate_buttons[1.0].x()  # Play leads on the right in Arabic
    assert review_window.warnings.icon_label.x() > review_window.warnings.text_label.x()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_window.py -q -k "two_columns or eight_rows or transport_drives or banner_not_a_dialog or question_mark or fit_toggle or full_frame or zoom_readout"`
Expected: FAIL (`AttributeError: 'ReviewWindow' object has no attribute '_splitter'`/`frame_scroll`…)

- [ ] **Step 3: Rebuild `_build`**

Replace the toolbar's `for button in buttons: toolbar.addWidget(button)` through `column.addLayout(toolbar)` with the grouped order, using a helper:

```python
def _separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFixedHeight(20)
    line.setProperty("separator", True)
    return line
```

order: save, undo, redo, `_separator()`, reviewed, remove, `_separator()`, stretch, studied label + box, episode_label, episode_button, export_button, render_button, render_progress, render_cancel_button, `_separator()`, `self.help_button` (a `QToolButton`, auto-raise, `set_icon(…, "keyboard")`, tooltip `t("review.help")`). Then:

```python
        self.warnings = Banner()
        column.addWidget(self.warnings)

        self.frame_view = FrameView(self.session, portrait=_is_portrait(self.session.project))
        self.frame_scroll = QScrollArea()
        self.frame_scroll.setWidget(self.frame_view)
        self.frame_scroll.setWidgetResizable(True)
        self.frame_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.frame_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fit_row = QHBoxLayout()
        self.fit_button = QToolButton(); self.actual_button = QToolButton()
        for button, name, key in ((self.fit_button, "zoom-out", "review.fit"), (self.actual_button, "zoom-in", "review.actual_size")):
            button.setCheckable(True); button.setAutoRaise(True); button.setToolTip(t(key)); button.setAccessibleName(t(key))
            set_icon(button, name, size=16)
        group = QButtonGroup(self); group.setExclusive(True); group.addButton(self.fit_button); group.addButton(self.actual_button)
        fit_row.addStretch(1); fit_row.addWidget(self.fit_button); fit_row.addWidget(self.actual_button)
        self.left_column = QWidget()
        left = QVBoxLayout(self.left_column)
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.frame_scroll, 1)
        left.addLayout(fit_row)
        left.addWidget(self._build_look_panel(), 2)
        self.left_column.setFixedWidth(self.frame_view.preset_size.width() + 2 * theme.SP_12)

        self.right_column = QWidget()
        right = QVBoxLayout(self.right_column)
        right.setContentsMargins(0, 0, 0, 0)
        right.addLayout(self._build_timeline())
        self.segment_list = SegmentList(self.session)
        right.addWidget(self.segment_list, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.left_column)
        splitter.addWidget(self.right_column)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self._splitter = splitter
        column.addWidget(splitter, 1)

        self.hint_label = QLabel(hint_html())
        self.hint_label.setTextFormat(Qt.TextFormat.RichText)
        self.hint_label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.hint_label.linkActivated.connect(lambda _link: self.show_shortcuts())
        self.statusBar().addWidget(self.hint_label, 1)
        self.setCentralWidget(central)
        self._set_preview_fit(self._prefs.preview_fit, remember=False)
```

`_build_look_panel`: drop `setFixedWidth(_LOOK_PANEL_WIDTH)`; delete the constant and `_LIST_MIN_HEIGHT`. `_build_timeline`:

```python
        zoom_row = QHBoxLayout()
        self.zoom_label = QLabel(t("review.zoom"))
        self.zoom_slider = ZoomSlider(self.viewport, self.player.position)
        self.zoom_label.setBuddy(self.zoom_slider)
        self.zoom_out_button = QToolButton(); self.zoom_in_button = QToolButton()
        for button, name, key, step in ((self.zoom_out_button, "zoom-out", "review.zoom_out", -10), (self.zoom_in_button, "zoom-in", "review.zoom_in", 10)):
            button.setAutoRaise(True); button.setToolTip(t(key)); button.setAccessibleName(t(key)); set_icon(button, name, size=16)
            button.clicked.connect(partial(self._zoom_step, step))
        self.zoom_readout = QLabel()
        self.zoom_readout.setFont(theme.font("secondary"))
        for widget in (self.zoom_label, self.zoom_out_button, self.zoom_slider, self.zoom_in_button, self.zoom_readout):
            zoom_row.addWidget(widget, 1 if widget is self.zoom_slider else 0)
        right.addLayout(zoom_row)
        self.ruler = TimeRuler(self.viewport)
        self.waveform = WaveformView(self.viewport)
        self.strip = WordStrip(self.viewport, self.session)
        right.addWidget(self.ruler); right.addWidget(self.waveform); right.addWidget(self.strip)
        self.transport = Transport(RATES)
        self.transport.set_lecture(self._is_lecture())
        self.play_button = self.transport.play_button
        self.time_label = self.transport.time_label
        self.show_ayah_button = self.transport.show_ayah_button
        right.addWidget(self.transport)
        self.selection_bar = SelectionBar(self.transport)
        right.addWidget(self.selection_bar)
        return right
```

(no trailing `addStretch`). New methods:

```python
    def _zoom_step(self, delta: int) -> None:
        self.zoom_slider.setValue(max(0, min(100, self.zoom_slider.value() + delta)))

    def _show_span(self) -> None:
        span = self.viewport.span
        if span >= 60:
            self.zoom_readout.setText(t("review.span_minutes", minutes=int(span // 60), seconds=f"{int(span % 60):02d}"))
        else:
            self.zoom_readout.setText(tn("review.span", int(round(span))))

    def show_shortcuts(self) -> None:
        if self.shortcut_sheet is None:
            self.shortcut_sheet = ShortcutSheet(self)
        self.shortcut_sheet.show()
        self.shortcut_sheet.raise_()
        self.shortcut_sheet.activateWindow()

    def _set_preview_fit(self, fit: bool, *, remember: bool = True) -> None:
        self.frame_view.set_fit(fit)
        self.frame_scroll.setWidgetResizable(fit)
        (self.fit_button if fit else self.actual_button).setChecked(True)
        if remember:
            self._prefs.preview_fit = fit

    def _show_full_frame(self, t: float) -> None:
        if self._full_frame is not None:
            self._full_frame.deleteLater()
        self._full_frame = FullFrameView(self.session, t, portrait=_is_portrait(self.session.project), parent=self)
        self._full_frame.close_requested.connect(self.activateWindow)
        self._full_frame.show()
        self._full_frame.setFocus()

    def _play_video(self, path: Path) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.warnings.add_notice(t("render.play_failed"))
```

`_wire` additions/changes: `self.viewport.changed.connect(self._show_span)`; `self.ruler.seek_requested.connect(self.seek)`; `self.transport.play_toggled.connect(self.toggle_play)`; `self.transport.step_requested.connect(self._step)`; `self.transport.rate_changed.connect(self.player.set_rate)`; `self.transport.nudge_requested.connect(self._nudge)`; `self.transport.snap_requested.connect(self._snap_to_playhead)`; `self.transport.show_ayah_requested.connect(self._show_ayah_from_here)`; `self.warnings.play_requested.connect(self._play_video)`; `self.warnings.reveal_requested.connect(show_in_folder)`; `self.help_button.clicked.connect(self.show_shortcuts)`; `self.fit_button.clicked.connect(lambda: self._set_preview_fit(True))`; `self.actual_button.clicked.connect(lambda: self._set_preview_fit(False))`; `self.frame_view.full_frame_requested.connect(self._show_full_frame)`. Remove the `play_button.clicked`, `rate_combo`, `selection_bar.nudge_requested/snap_requested`, `show_ayah_button.clicked` lines. `_bind_keys`: add `("?", self.show_shortcuts)` and `("Shift+/", self.show_shortcuts)`; `keyPressEvent` is unchanged (a focused editor still receives the character first, which is Review Focus 3). `_show_time`: add `self.ruler.set_playhead(seconds)`, `self.transport.set_time(seconds)`, and `ref = self.session.word_at(seconds); word = self.session.word(ref) if ref is not None else None; self.waveform.set_current_word(word.start if word else None, word.end if word else None)`. `_on_playing_changed`: `self.transport.set_playing(playing)` replaces the setText/tooltip lines. Delete `_on_rate`, `_elide_hint` and the `eventFilter` branch for `hint_label`. `_set_tips`: nudge tips move to `self.transport.minus_button` / `plus_button`. `_set_render_running`: `self.transport.setEnabled(not running)` replaces `self.selection_bar.setEnabled(...)`; on `running` call `self.warnings.clear_render()`. `_announce_render`:

```python
    def _announce_render(self, outcome: JobOutcome) -> None:
        """Say the render is ready on the banner; the episode's failure, if any, still asks for a look."""
        duration = self.session.duration if self._measured else None
        self.warnings.set_render_done(outcome, duration)
        if outcome.episode_error:
            self._say_render("failed", outcome.episode_error)
```

`__init__`: `self.shortcut_sheet = None`, `self._full_frame = None` before `_build()`; after `_wire()`, `self._show_span()`. Imports: `QFrame, QScrollArea, QButtonGroup, QToolButton` (QtWidgets), `QDesktopServices` (QtGui), `QUrl` (QtCore), `TimeRuler`, `Transport`, `ShortcutSheet, hint_html`, `FullFrameView`, `Banner`; drop `QComboBox` if unused and `WarningsStrip`. Remove `"review.shortcuts"` from both i18n blocks. `theme.stylesheet` gains `QFrame[separator="true"] {{ color: {t.border}; }}` (one line, assert in `test_theme`).

- [ ] **Step 4: Run the tests, adapt the named existing ones, verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_window.py tests/test_review_widgets.py tests/test_rtl.py tests/test_gui.py tests/test_i18n.py tests/test_theme.py -q`
Expected: PASS, including `test_a_lecture_window_fits_a_1280_px_screen_while_rendering[*]`. If the English toolbar overflows 1280 px with the help button and separators, drop the separators' margins to 4 px before shortening any copy, and report the measured minimum.

- [ ] **Step 5: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/review/window.py src/qurantext/gui/i18n.py src/qurantext/gui/theme.py tests/test_review_window.py tests/test_review_widgets.py tests/test_rtl.py tests/test_gui.py tests/test_theme.py
git commit -m "Lay the review window out in two columns, group its toolbar, and wire the ruler, the transport, the banner, the shortcut sheet and the preview's full-size view

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Screenshots, README, the whole suite

**Files:**
- Modify: `tools/screenshots.py`, `tests/test_screenshots_tool.py`, `README.md` (the review-window paragraph), `docs/release-checklist.md`

- [ ] **Step 1: Extend the tool's test**

Add `"shortcuts-en-light.png"` and `"review-full-frame-en-light.png"` to the expected names in `tests/test_screenshots_tool.py`; run it; expect FAIL.

- [ ] **Step 2: Extend `shoot`**

After the recitation review image: `review.show_shortcuts(); written.append(_grab(review.shortcut_sheet, out_dir / f"shortcuts-{tag}.png")); review.shortcut_sheet.hide()` and `review._show_full_frame(1.2); _spin(300); written.append(_grab(review._full_frame, out_dir / f"review-full-frame-{tag}.png")); review._full_frame.hide()`.

- [ ] **Step 3: Run the tool and look**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python tools/screenshots.py output/shots-phase-c`
Open `review-lecture-en-light.png`, `review-recitation-ar-dark.png`, `shortcuts-en-light.png`, `review-full-frame-en-light.png` with the Read tool and confirm: two columns, the table reaching the status bar, the ruler with labels, the transport with icons, the banner (if any notices) as a card, Arabic mirrored with the timeline still right-to-left, the sheet's three groups, the full frame on black. Record what you see.

- [ ] **Step 4: README and checklist**

In `README.md`'s review-window paragraph, mention the time ruler, the transport, the banner, `?` for shortcuts, and the double-click full-size preview. In `docs/release-checklist.md`, add "the review window's shortcut sheet and full-size preview" to the screenshot item.

- [ ] **Step 5: Whole suite and linters**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q --ignore=tests/test_local_engine_slow.py -p no:cacheprovider` → every test passes. Then `venv/bin/ruff check src tests tools && venv/bin/ruff format --check src tests tools` → clean.

- [ ] **Step 6: Commit**

```bash
git add tools/screenshots.py tests/test_screenshots_tool.py README.md docs/release-checklist.md
git commit -m "Photograph the shortcut sheet and the full-size preview too, and describe the review window as it is now

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

- Spec §2.1 layout → Task 8; §2.2 ruler → Task 2, zoom row → Task 8, waveform/strip → Task 6, transport → Task 5 (+8 wiring), selection bar → Task 5, keyboard `?` → Task 8; §2.3 toolbar → Task 8, banner → Task 3 (+8 wiring and `_announce_render`); §2.4 sheet → Task 4 (+8); §2.5 table → Task 6; §2.6 preview → Task 7 (+8 wiring, prefs in Task 1); §3 icons/strings/`mirror`/prefs → Task 1; §5 errors: play failure (Task 8 `_play_video`), no duration (Task 3), full-frame render error (Task 7), degenerate ruler (Task 2), hover suppressed while dragging (Task 2); §6 tests → each task; screenshots → Task 9.
- Names: `Banner.text/lines/kind/set_render_done/clear_render/toggle_gaps/jump_to/play_button/reveal_button/dismiss_button/icon_label/text_label`; `Transport.rate_buttons/set_playing/set_time/set_rate/set_selection/set_lecture`; `SelectionBar(transport)`; `TimeRuler.labels/time_at/playhead_x/set_playhead/HEIGHT`; `FrameView.set_fit/fit/preset_size/full_frame_requested`; `FullFrameView.shown_size/close_requested`; window: `ruler transport frame_scroll fit_button actual_button help_button shortcut_sheet zoom_readout zoom_in_button zoom_out_button left_column right_column _splitter _full_frame show_shortcuts _show_full_frame _set_preview_fit _play_video _zoom_step _show_span` — consistent across tasks.
- Review Focus 1 → Task 2; 2 → Task 3; 3 → Task 8; 4 → Task 7 (+8); 5 → Task 8 (`frame_scroll` not resizable in Actual mode; the test `test_the_fit_toggle_round_trips_through_prefs` asserts it).
- Known soft spots for implementers: `_strip(qt_app)`'s return shape in `tests/test_review_widgets.py` (Task 6); `_lecture_window(qt_app, tmp_path)` in `tests/test_review_window.py` and whether it has ≥ 12 captions (Task 8); the Arabic plural categories are zero/one/two/few/many/other (Task 1 lists them all).

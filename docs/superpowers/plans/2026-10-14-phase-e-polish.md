# Phase E: polish — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Animate the two disclosures, paint the focus ring for keyboard focus only, give cards hover and focus states, outline the dark theme's indicators and fields through a proxy style, bundle Noto Sans Arabic as the interface fallback, pass every colour added since phase A through one contrast test, and close the small leftovers from phases B to D.

**Architecture:** Three small new modules (`gui/disclosure.py`, `gui/focus.py`, `gui/style.py`) each own one behaviour and are wired in by `apply_theme` or by the two toggles. The stylesheet stays palette-first and never names Fusion's widgets: focus moves from the `:focus` pseudo-class to a `kbdfocus` property an app-wide filter sets, and the dark outlines are drawn by a `QProxyStyle` from palette roles. Fonts, contrast and leftovers are each one task with their own tests.

**Tech Stack:** PySide6 6.11 (Fusion + proxy style, `QPropertyAnimation`), Pillow, pytest offscreen, a pinned notofonts release.

**Spec:** `docs/superpowers/specs/2026-10-14-phase-e-polish-design.md`

**One deviation from the spec, decided while planning:** §2.7's "the ruler's label width is measured ×1.15 instead of a 0 px gap" is not done. With the 48 px label width the tests use, ×1.15 moves the 120 s / 600 px case from 10 s to 30 s labels, which is sparser than the ruler reads today, and `tests/test_time_ruler.py::test_no_label_leaves_the_ruler_or_touches_another` already guards labels touching. The executor records this as a ruling in the ledger.

## Global Constraints

- Interpreter `venv/bin/python`; tests `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest …`; lint `venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools` before every commit. In a worktree, ad-hoc scripts need `PYTHONPATH=src`.
- Commit messages are one sentence in the repository's style (what and why) and end with the trailer line the harness gives.
- The stylesheet never names `QComboBox`, `QSpinBox`, `QSlider`, `QScrollBar`, `QCheckBox`, `QRadioButton`, `QTabWidget`, `QTabBar`, `QProgressBar`; after Task 1 it contains no `:focus` pseudo-class at all.
- Every widget attribute the tests reach keeps its name.
- Every `t()` key exists in both languages with the same placeholders; Arabic values-only lines start with `‏`; direction marks as `\u` escapes.
- Never `QTest.qWait`; pump with `qt_app.processEvents()` or `tests.qt_helpers.wait_for`.
- `QWIDGETSIZE_MAX` is not exported by PySide6: the literal `16777215` is used, named `_NO_LIMIT`.
- The disclosure animation lasts 150 ms with `QEasingCurve.Type.OutCubic`; it runs only when `Prefs.animate_panels` is True, the style's `SH_Widget_Animate` hint is non-zero, and the widget's window is visible.
- Keyboard focus reasons: `TabFocusReason`, `BacktabFocusReason`, `ShortcutFocusReason`; the property is named `kbdfocus`.
- `LIGHT.gold` becomes `#A67C11` (3.43:1 on the window, 3.81:1 on white); `DARK.gold` stays `#D9B45B`.
- Noto Sans Arabic release `NotoSansArabic-v2.013`, files `NotoSansArabic/unhinted/ttf/NotoSansArabic-Regular.ttf` (sha256 `bd86ca02f087d7f3c3788ba458fb6b73744c7639ed276b8d870dba6def6c40d0`), `NotoSansArabic/unhinted/ttf/NotoSansArabic-Bold.ttf` (sha256 `f4cb79f842a07d1bcf597879574358fb7010f73761396d1d0f2445dfedb4d2ca`) and `OFL.txt` from `https://github.com/notofonts/arabic/releases/download/NotoSansArabic-v2.013/NotoSansArabic-v2.013.zip`.

## Review Focus

1. Tab onto a card, then click a field elsewhere: the card's ring must clear on focus out, not linger. → Task 1 test `test_focus_out_clears_the_mark`.
2. Toggling a disclosure twice before 150 ms have passed: it must reverse from where it is and never stay capped at a partial height. → Task 3 test `test_a_toggle_mid_animation_reverses_and_frees_the_height`.
3. A disabled checkbox in the dark theme must still show its outline, since it is the only way to see there is a box. → Task 2 test `test_a_disabled_checkbox_keeps_its_outline`.
4. A frozen build that lost Noto Bold but kept Regular: the interface must still get Noto, and the doctor must say what is missing. → Task 4 tests `test_one_missing_noto_file_still_registers_the_other` and `test_the_interface_font_check_names_the_missing_file`.
5. Hovering the selected Episode card must not replace its selection border with the thinner hover border. → Task 1 test `test_a_selected_card_keeps_its_border_when_hovered`.

---

### Task 1: Keyboard-only focus ring, card hover and focus

**Files:**
- Create: `src/qurantext/gui/focus.py`
- Modify: `src/qurantext/gui/theme.py` (every `:focus` rule; two card rules; `apply_theme`), `src/qurantext/gui/home/job_list.py` (`_ModeCard.__init__`), `src/qurantext/gui/review/episode_cards.py` (`PartCard.__init__`)
- Test: create `tests/test_focus.py`; modify `tests/test_theme.py`

**Interfaces:**
- Produces: `focus.KBDFOCUS = "kbdfocus"`, `focus.KeyboardFocusMarker(QObject)`, `focus.install(app) -> KeyboardFocusMarker` (idempotent, guarded by the app property `qalun.focus_marker`); stylesheet selectors `[kbdfocus="true"]` in place of `:focus`; `QFrame[card="true"]:hover`, `QFrame[card="true"][kbdfocus="true"]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_focus.py`:

```python
# tests/test_focus.py
"""The focus ring paints for keyboard focus only: Tab marks a widget, a click does not."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget  # noqa: E402

from qurantext.gui import focus  # noqa: E402


@pytest.fixture()
def pair(qt_app):
    focus.install(qt_app)
    window = QWidget()
    row = QHBoxLayout(window)
    button, field = QPushButton("b"), QLineEdit()
    row.addWidget(button)
    row.addWidget(field)
    window.show()
    qt_app.processEvents()
    yield button, field
    window.close()


def test_tab_marks_a_widget_and_a_click_does_not(qt_app, pair) -> None:
    button, field = pair
    button.setFocus(Qt.FocusReason.TabFocusReason)
    qt_app.processEvents()
    assert button.property(focus.KBDFOCUS) is True
    field.setFocus(Qt.FocusReason.MouseFocusReason)
    qt_app.processEvents()
    assert not field.property(focus.KBDFOCUS)
    button.setFocus(Qt.FocusReason.BacktabFocusReason)
    assert button.property(focus.KBDFOCUS) is True
    field.setFocus(Qt.FocusReason.ShortcutFocusReason)
    assert field.property(focus.KBDFOCUS) is True


def test_focus_out_clears_the_mark(qt_app, pair) -> None:
    button, field = pair
    button.setFocus(Qt.FocusReason.TabFocusReason)
    assert button.property(focus.KBDFOCUS) is True
    field.setFocus(Qt.FocusReason.MouseFocusReason)  # a click elsewhere
    qt_app.processEvents()
    assert button.property(focus.KBDFOCUS) is False


def test_other_reasons_do_not_mark(qt_app, pair) -> None:
    button, _field = pair
    for reason in (Qt.FocusReason.OtherFocusReason, Qt.FocusReason.ActiveWindowFocusReason):
        button.clearFocus()
        button.setFocus(reason)
        qt_app.processEvents()
        assert not button.property(focus.KBDFOCUS), reason


def test_install_is_idempotent(qt_app) -> None:
    first = focus.install(qt_app)
    assert focus.install(qt_app) is first
    assert qt_app.property("qalun.focus_marker") is first
```

In `tests/test_theme.py`:

- In `test_quiet_buttons_and_the_chosen_tile_keep_focus_disabled_and_pressed_looks` replace `'QPushButton[quiet="true"]:focus'` with `'QPushButton[quiet="true"][kbdfocus="true"]'`, the loop's `":focus"` with `'[kbdfocus="true"]'`, and `'QToolButton[swatch="true"]:checked:focus'` with `'QToolButton[swatch="true"]:checked[kbdfocus="true"]'`.
- In `test_a_focused_quiet_button_and_a_focused_chosen_tile_show_the_accent_ring`, every `setFocus()` that should show the ring becomes `setFocus(Qt.FocusReason.TabFocusReason)` (the filter must be installed: `apply_theme` does it), and add at its end: focus the quiet button with `Qt.FocusReason.MouseFocusReason`, process events, and `assert not _edge_has(quiet, accent)`.
- Add:

```python
@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_focus_is_a_property_not_a_pseudo_class(tokens) -> None:
    """A click or a dialog's first focus paints no ring; Tab does (gui.focus marks it)."""
    sheet = theme.stylesheet(tokens)
    assert ":focus" not in sheet
    ring = _rule(sheet, 'QPushButton[kbdfocus="true"], QToolButton[kbdfocus="true"]')
    assert ring["border"] == f"2px solid {tokens.accent}"
    assert _rule(sheet, 'QPushButton[primary="true"][kbdfocus="true"]')["border"] == (
        f"2px solid {tokens.text}"
    )


@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_cards_hover_and_focus_like_buttons(tokens) -> None:
    sheet = theme.stylesheet(tokens)
    assert _rule(sheet, 'QFrame[card="true"]:hover')["border-color"] == tokens.accent
    assert _rule(sheet, 'QFrame[card="true"][kbdfocus="true"]')["border"] == (
        f"2px solid {tokens.accent}"
    )
    # The selected Episode card's border wins over hover: its rule comes later.
    assert sheet.index('QFrame[card="true"][selected="true"]') > sheet.index(
        'QFrame[card="true"]:hover'
    )


def test_apply_theme_installs_the_focus_marker(qt_app) -> None:
    from qurantext.gui import focus

    theme.apply_theme(qt_app, "light")
    assert isinstance(qt_app.property("qalun.focus_marker"), focus.KeyboardFocusMarker)


def test_a_selected_card_keeps_its_border_when_hovered(qt_app) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QEnterEvent

    from qurantext.gui.review.episode_cards import PartCard

    tokens = theme.apply_theme(qt_app, "light")
    card = PartCard("Intro")
    card.set_selected(True)
    card.show()
    qt_app.processEvents()
    assert card.testAttribute(Qt.WidgetAttribute.WA_Hover)
    centre = QPointF(card.rect().center())
    qt_app.sendEvent(card, QEnterEvent(centre, centre, card.mapToGlobal(centre.toPoint())))
    qt_app.processEvents()
    image = card.grab().toImage()
    accent = QColor(tokens.accent)
    # Two accent pixels deep on the left edge: the 2 px selection border, not a 1 px hover one.
    y = image.height() // 2
    assert _near(image.pixelColor(0, y), accent) and _near(image.pixelColor(1, y), accent)
    card.close()
```

(`QColor`, `Qt` and `_near` already exist in that module.)

- [ ] **Step 2: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_focus.py tests/test_theme.py -q`
Expected: `tests/test_focus.py` fails with `ModuleNotFoundError`; the new and changed theme tests fail on the old selectors.

- [ ] **Step 3: Write `focus.py`**

```python
"""Mark keyboard focus, so the focus ring paints after Tab and not after a click.

Qt's ``:focus`` is every focus: a click, a dialog's first widget, the window
coming back to the front. The ring is for the person who cannot see the
pointer, so it follows the keyboard only: an application-wide filter sets
the dynamic property ``kbdfocus`` on a widget whose focus came by Tab,
Backtab or a shortcut, clears it when the focus leaves, and the sheet's
``[kbdfocus="true"]`` rules do the rest. Fusion's own frame on a line edit
is not touched.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QWidget

__all__ = ["KBDFOCUS", "KeyboardFocusMarker", "install"]

#: The dynamic property the sheet reads.
KBDFOCUS = "kbdfocus"
#: The application property that holds the one installed marker.
_INSTALLED = "qalun.focus_marker"
_KEYBOARD = (
    Qt.FocusReason.TabFocusReason,
    Qt.FocusReason.BacktabFocusReason,
    Qt.FocusReason.ShortcutFocusReason,
)


class KeyboardFocusMarker(QObject):
    """The filter: marks a widget on a keyboard focus-in, unmarks it on focus-out."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if not isinstance(watched, QWidget):
            return False
        kind = event.type()
        if kind == QEvent.Type.FocusIn:
            keyboard = event.reason() in _KEYBOARD
            if bool(watched.property(KBDFOCUS)) != keyboard:
                _mark(watched, keyboard)
        elif kind == QEvent.Type.FocusOut and watched.property(KBDFOCUS):
            _mark(watched, False)
        return False


def _mark(widget: QWidget, on: bool) -> None:
    widget.setProperty(KBDFOCUS, on)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def install(app) -> KeyboardFocusMarker:  # noqa: ANN001 - a QApplication
    """Install the marker on *app* once; later calls return the one already there."""
    marker = app.property(_INSTALLED)
    if isinstance(marker, KeyboardFocusMarker):
        return marker
    marker = KeyboardFocusMarker(app)
    app.installEventFilter(marker)
    app.setProperty(_INSTALLED, marker)
    return marker
```

- [ ] **Step 4: Change the sheet and `apply_theme`**

In `theme.py`'s `stylesheet`, change every selector that uses `:focus`:

| Before | After |
|---|---|
| `QPushButton:focus, QToolButton:focus` | `QPushButton[kbdfocus="true"], QToolButton[kbdfocus="true"]` |
| `QToolButton[autoRaise="true"]:focus` | `QToolButton[autoRaise="true"][kbdfocus="true"]` |
| `QPushButton[primary="true"]:focus` | `QPushButton[primary="true"][kbdfocus="true"]` |
| `QPushButton[row="true"]:focus` | `QPushButton[row="true"][kbdfocus="true"]` |
| `QPushButton[quiet="true"]:focus` | `QPushButton[quiet="true"][kbdfocus="true"]` |
| `QToolButton[swatch="true"]:checked:focus` | `QToolButton[swatch="true"]:checked[kbdfocus="true"]` |

Keep each rule's declarations as they are. After the `QFrame[card="true"][part="true"]` rule and before `QFrame[card="true"][selected="true"]` add:

```
QFrame[card="true"]:hover {{ border-color: {t.accent}; }}
QFrame[card="true"][kbdfocus="true"] {{ border: 2px solid {t.accent}; }}
```

Check that the selected rule indeed comes after; move it if not. In `apply_theme`, after the Fusion guard block:

```python
    from qurantext.gui import focus

    focus.install(app)
```

(an in-function import: `focus` must not import `theme`, and it does not, but the app module's import order is kept simple this way).

Add `self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)` in `_ModeCard.__init__` (after `setCursor`) and in `PartCard.__init__` (after `setFocusPolicy`).

- [ ] **Step 5: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_focus.py tests/test_theme.py tests/test_widgets.py tests/test_episode_cards.py tests/test_home_panels.py tests/test_review_widgets.py -q`
Expected: all PASS. If a review-widget test asserted a ring after a plain `setFocus()`, give it `Qt.FocusReason.TabFocusReason`.

- [ ] **Step 6: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/gui/focus.py src/qurantext/gui/theme.py src/qurantext/gui/home/job_list.py src/qurantext/gui/review/episode_cards.py tests/test_focus.py tests/test_theme.py
git commit -m "Paint the focus ring for keyboard focus only, through a filter that marks Tab and shortcut focus, and give cards a hover border and the ring"
```

---

### Task 2: The proxy style for the dark outlines

**Files:**
- Create: `src/qurantext/gui/style.py`
- Modify: `src/qurantext/gui/theme.py` (`apply_theme`'s Fusion block)
- Test: create `tests/test_style.py`

**Interfaces:**
- Produces: `style.QalunStyle(QProxyStyle)`; `theme.apply_theme` sets `QalunStyle(QStyleFactory.create("Fusion"))` once.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_style.py
"""The proxy over Fusion: indicators and fields keep a visible outline in both themes."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QCheckBox,
    QLineEdit,
    QProxyStyle,
    QRadioButton,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from qurantext.gui import theme  # noqa: E402
from qurantext.gui.style import QalunStyle  # noqa: E402


def _near(colour: QColor, target: QColor, slack: int = 28) -> bool:
    return all(
        abs(a - b) <= slack for a, b in zip(colour.getRgb()[:3], target.getRgb()[:3], strict=True)
    )


def _indicator_left(box) -> tuple[int, int]:
    option = QStyleOptionButton()
    box.initStyleOption(option)
    element = (
        QStyle.SubElement.SE_RadioButtonIndicator
        if isinstance(box, QRadioButton)
        else QStyle.SubElement.SE_CheckBoxIndicator
    )
    rect = box.style().subElementRect(element, option, box)
    return rect.left(), rect.center().y()


def _column_has(widget, x: int, y: int, target: QColor) -> bool:
    image = widget.grab().toImage()
    return any(_near(image.pixelColor(x + dx, y), target) for dx in range(3))


def test_the_application_style_is_the_proxy_over_fusion(qt_app) -> None:
    theme.apply_theme(qt_app, "light")
    style = qt_app.style()
    assert isinstance(style, QalunStyle) and isinstance(style, QProxyStyle)
    assert style.baseStyle().objectName().lower() == "fusion"
    theme.apply_theme(qt_app, "dark")
    assert qt_app.style() is style, "set once, as Fusion was"


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_checkbox_and_radio_indicators_are_outlined_in_the_secondary_colour(qt_app, mode) -> None:
    tokens = theme.apply_theme(qt_app, mode)
    window = QWidget()
    column = QVBoxLayout(window)
    box, radio = QCheckBox("x"), QRadioButton("y")
    column.addWidget(box)
    column.addWidget(radio)
    window.show()
    qt_app.processEvents()
    outline = QColor(tokens.secondary)
    for widget in (box, radio):
        x, y = _indicator_left(widget)
        assert _column_has(widget, x, y, outline), (mode, type(widget).__name__)
    window.close()


def test_a_disabled_checkbox_keeps_its_outline(qt_app) -> None:
    tokens = theme.apply_theme(qt_app, "dark")
    box = QCheckBox("x")
    box.setEnabled(False)
    box.show()
    qt_app.processEvents()
    x, y = _indicator_left(box)
    assert _column_has(box, x, y, QColor(tokens.secondary))
    box.close()


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_an_unfocused_field_has_the_border_frame_and_a_focused_one_the_accent(qt_app, mode) -> None:
    tokens = theme.apply_theme(qt_app, mode)
    window = QWidget()
    column = QVBoxLayout(window)
    field, other = QLineEdit(), QLineEdit()
    column.addWidget(field)
    column.addWidget(other)
    window.show()
    other.setFocus(Qt.FocusReason.TabFocusReason)
    qt_app.processEvents()
    y = field.height() // 2
    assert _column_has(field, 0, y, QColor(tokens.border)), mode
    field.setFocus(Qt.FocusReason.TabFocusReason)
    qt_app.processEvents()
    assert _column_has(field, 0, y, QColor(tokens.accent)), mode
    window.close()


def test_the_sheet_still_names_none_of_fusions_widgets(qt_app) -> None:
    sheet = theme.stylesheet(theme.DARK)
    for name in ("QCheckBox", "QRadioButton", "QComboBox", "QSpinBox"):
        assert name not in sheet
```

- [ ] **Step 2: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_style.py -q`
Expected: `ModuleNotFoundError: qurantext.gui.style`.

- [ ] **Step 3: Write `style.py`**

```python
"""A thin style over Fusion that keeps outlines visible in the dark theme.

Fusion draws a checkbox's box, a radio's circle and a field's frame in a
shade it derives from the window colour: about 1.1:1 in the dark theme,
which no palette role moves. The sheet cannot help without naming those
widgets, which breaks Fusion's sub-controls. So a proxy draws after Fusion:
a 1 px outline in the palette's placeholder-text colour (the secondary
token) around each indicator, and a 1 px frame in the Mid colour (the
border token) around a field that does not have focus; a focused field
keeps Fusion's highlight frame. Both colours come from the palette at draw
time, so a theme switch needs nothing here.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter, QPalette, QPen
from PySide6.QtWidgets import QProxyStyle, QStyle

__all__ = ["QalunStyle"]

_INDICATORS = (
    QStyle.PrimitiveElement.PE_IndicatorCheckBox,
    QStyle.PrimitiveElement.PE_IndicatorRadioButton,
)
_FIELDS = (QStyle.ComplexControl.CC_ComboBox, QStyle.ComplexControl.CC_SpinBox)
#: Fusion's corner radius on its boxes and frames.
_RADIUS = 2.0


class QalunStyle(QProxyStyle):
    """Fusion, with outlines the dark theme can show."""

    def drawPrimitive(self, element, option, painter, widget=None) -> None:  # noqa: N802, ANN001 - Qt override
        super().drawPrimitive(element, option, painter, widget)
        if element in _INDICATORS:
            colour = option.palette.color(QPalette.ColorRole.PlaceholderText)
            rect = QRectF(option.rect).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(colour, 1))
            painter.setBrush(Qt_NoBrush())
            if element == QStyle.PrimitiveElement.PE_IndicatorCheckBox:
                painter.drawRoundedRect(rect, _RADIUS, _RADIUS)
            else:
                painter.drawEllipse(rect)
            painter.restore()
        elif element == QStyle.PrimitiveElement.PE_FrameLineEdit and not _focused(option):
            _frame(painter, option)

    def drawComplexControl(self, control, option, painter, widget=None) -> None:  # noqa: N802, ANN001 - Qt override
        super().drawComplexControl(control, option, painter, widget)
        if control in _FIELDS and not _focused(option):
            _frame(painter, option)


def _focused(option) -> bool:  # noqa: ANN001 - a QStyleOption
    return bool(option.state & QStyle.StateFlag.State_HasFocus)


def _frame(painter: QPainter, option) -> None:  # noqa: ANN001 - a QStyleOption
    """A 1 px frame in the border colour along the control's rounded edge."""
    colour = option.palette.color(QPalette.ColorRole.Mid)
    rect = QRectF(option.rect).adjusted(0.5, 0.5, -0.5, -0.5)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(colour, 1))
    painter.setBrush(Qt_NoBrush())
    painter.drawRoundedRect(rect, _RADIUS, _RADIUS)
    painter.restore()
```

Replace `Qt_NoBrush()` with `Qt.BrushStyle.NoBrush` and import `Qt` from `PySide6.QtCore` (written out here so the placeholder is not missed: the two `setBrush` calls read `painter.setBrush(Qt.BrushStyle.NoBrush)`).

In `theme.py`'s `apply_theme` replace `app.setStyle("Fusion")` with:

```python
        from PySide6.QtWidgets import QStyleFactory

        from qurantext.gui.style import QalunStyle

        base = QStyleFactory.create("Fusion")
        # A Qt built without Fusion: the proxy wraps whatever style is in force.
        app.setStyle(QalunStyle(base) if base is not None else QalunStyle(app.style()))
```

Keep the guard property as it is. Check `tests/conftest.py::_theme_does_not_leak`: it restores the style only when `app.style().objectName()` changed and is non-empty; the proxy's object name is empty, so it leaves it, which is what the "set once" test expects.

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_style.py tests/test_theme.py tests/test_settings_dialog.py tests/test_home_panels.py -q`
Expected: all PASS. If the indicator test misses the colour by a few pixels, print the grabbed column around `x` once to see where Fusion put its edge, and sample `range(-1, 3)`.

- [ ] **Step 5: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/gui/style.py src/qurantext/gui/theme.py tests/test_style.py
git commit -m "Wrap Fusion in a proxy style that outlines checkbox and radio indicators in the secondary colour and unfocused fields in the border colour, so the dark theme shows them"
```

---

### Task 3: Disclosure animation, the setting and the two toggles

**Files:**
- Create: `src/qurantext/gui/disclosure.py`
- Modify: `src/qurantext/gui/prefs.py`, `src/qurantext/gui/home/settings_dialog.py` (`_general`), `src/qurantext/gui/i18n.py`, `src/qurantext/gui/home/new_job.py` (`_set_more_options_visibility`), `src/qurantext/gui/review/look_panel.py` (`_toggle_customise`), `tests/conftest.py`
- Test: create `tests/test_disclosure.py`; modify `tests/test_settings_dialog.py`

**Interfaces:**
- Produces: `disclosure.DURATION_MS = 150`, `disclosure.animations_enabled(prefs) -> bool`, `disclosure.reveal(widget, open_, *, animate: bool, duration_ms: int = DURATION_MS) -> None`; `Prefs.animate_panels: bool`; `SettingsDialog.animate_box: QCheckBox`; string `settings.animate_panels`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_disclosure.py
"""A panel opens by growing over 150 ms, or at once when animation is off."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtWidgets import QLabel, QStyle, QVBoxLayout, QWidget  # noqa: E402

from qurantext.gui import disclosure  # noqa: E402
from tests.qt_helpers import wait_for  # noqa: E402

_NO_LIMIT = 16777215


@pytest.fixture()
def panel(qt_app):
    window = QWidget()
    column = QVBoxLayout(window)
    header = QLabel("header")
    body = QWidget()
    inner = QVBoxLayout(body)
    for i in range(6):
        inner.addWidget(QLabel(f"line {i}"))
    column.addWidget(header)
    column.addWidget(body)
    body.hide()
    window.show()
    qt_app.processEvents()
    yield body
    window.close()


def test_without_animation_it_shows_and_hides_at_once(qt_app, panel) -> None:
    disclosure.reveal(panel, True, animate=False)
    assert panel.isVisible() and panel.maximumHeight() == _NO_LIMIT
    disclosure.reveal(panel, False, animate=False)
    assert not panel.isVisible()


def test_with_animation_it_grows_then_frees_its_height(qt_app, panel) -> None:
    full = panel.sizeHint().height()
    disclosure.reveal(panel, True, animate=True)
    assert panel.isVisible() and panel.maximumHeight() < full
    assert wait_for(lambda: panel.maximumHeight() == _NO_LIMIT, 2000)
    assert panel.height() >= full
    disclosure.reveal(panel, False, animate=True)
    assert panel.isVisible(), "still on screen while it shrinks"
    assert wait_for(lambda: not panel.isVisible(), 2000)
    assert panel.maximumHeight() == _NO_LIMIT


def test_a_toggle_mid_animation_reverses_and_frees_the_height(qt_app, panel) -> None:
    disclosure.reveal(panel, True, animate=True)
    qt_app.processEvents()
    disclosure.reveal(panel, False, animate=True)  # before the 150 ms are over
    assert wait_for(lambda: not panel.isVisible(), 2000)
    assert panel.maximumHeight() == _NO_LIMIT
    disclosure.reveal(panel, True, animate=True)
    assert wait_for(lambda: panel.maximumHeight() == _NO_LIMIT, 2000)
    assert panel.isVisible()


def test_a_hidden_window_gets_no_animation(qt_app) -> None:
    window = QWidget()
    body = QWidget(window)
    body.hide()
    disclosure.reveal(body, True, animate=True)
    assert body.maximumHeight() == _NO_LIMIT and not body.isHidden()


def test_animations_follow_the_setting_and_the_style_hint(qt_app, prefs, monkeypatch) -> None:
    assert prefs.animate_panels is True
    hint = qt_app.style().styleHint(QStyle.StyleHint.SH_Widget_Animate)
    assert disclosure.animations_enabled(prefs) is bool(hint)
    prefs.animate_panels = False
    assert disclosure.animations_enabled(prefs) is False
    prefs.animate_panels = True
    monkeypatch.setattr(type(qt_app.style()), "styleHint", lambda self, *a, **k: 0)
    assert disclosure.animations_enabled(prefs) is False
```

In `tests/test_settings_dialog.py` add:

```python
def test_general_has_an_animate_panels_box_that_writes_the_pref(dialog, prefs) -> None:
    assert dialog.animate_box.text() == t("settings.animate_panels")
    assert dialog.animate_box.isChecked() is True
    dialog.animate_box.setChecked(False)
    assert prefs.animate_panels is False
    dialog.animate_box.setChecked(True)
    assert prefs.animate_panels is True
```

- [ ] **Step 2: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_disclosure.py tests/test_settings_dialog.py -q`
Expected: `ModuleNotFoundError` / `AttributeError: animate_panels`.

- [ ] **Step 3: Write `disclosure.py`**

```python
"""Open and close a panel by height, in 150 ms, or at once.

More options and Customise are disclosures: a button with a chevron and a
panel under it. Shown and hidden with ``setVisible`` the panel jumps; here
it grows from nothing to its own height with an ease-out, and shrinks back
the same way, driving its maximum height meanwhile and releasing it after.
A toggle during the motion restarts from where the panel is.

The motion is off when the person turned "Animate panels" off, when the
style says widgets should not animate (``SH_Widget_Animate``), and when the
panel's window is not on screen yet (a panel opened at start-up by a saved
setting appears as the window does).
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QApplication, QStyle, QWidget

from qurantext.gui.prefs import Prefs

__all__ = ["DURATION_MS", "animations_enabled", "reveal"]

#: How long a panel takes to open or close.
DURATION_MS = 150
#: ``QWIDGETSIZE_MAX``, which PySide6 does not export: no height limit.
_NO_LIMIT = 16777215
#: The running animation, kept on the widget so a second toggle can stop it.
_ANIMATION = "qalun.disclosure"


def animations_enabled(prefs: Prefs) -> bool:
    """Whether panels animate: the setting is on and the style animates widgets."""
    app = QApplication.instance()
    if app is None or not prefs.animate_panels:
        return False
    return app.style().styleHint(QStyle.StyleHint.SH_Widget_Animate) != 0


def reveal(widget: QWidget, open_: bool, *, animate: bool, duration_ms: int = DURATION_MS) -> None:
    """Show (*open_*) or hide *widget*, growing or shrinking it when *animate* and on screen."""
    running = widget.property(_ANIMATION)
    if isinstance(running, QPropertyAnimation):
        widget.setProperty(_ANIMATION, None)  # its finished slot then does nothing
        running.stop()
        running.deleteLater()
    window = widget.window()
    if not animate or window is None or not window.isVisible():
        widget.setMaximumHeight(_NO_LIMIT)
        widget.setVisible(open_)
        return
    start = widget.height() if widget.isVisible() else 0
    end = widget.sizeHint().height() if open_ else 0
    widget.setMaximumHeight(start)
    widget.setVisible(True)
    animation = QPropertyAnimation(widget, b"maximumHeight", widget)
    animation.setDuration(duration_ms)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.setStartValue(start)
    animation.setEndValue(end)

    def finished() -> None:
        if widget.property(_ANIMATION) is not animation:
            return  # stopped by a later toggle
        widget.setProperty(_ANIMATION, None)
        widget.setMaximumHeight(_NO_LIMIT)
        if not open_:
            widget.setVisible(False)

    animation.finished.connect(finished)
    widget.setProperty(_ANIMATION, animation)
    animation.start()
```

- [ ] **Step 4: The pref, the setting and the string**

`prefs.py`, after `preview_fit`:

```python
    # -- motion ------------------------------------------------------------------

    @property
    def animate_panels(self) -> bool:
        """Whether More options and Customise open with a 150 ms motion (True) or at once."""
        value = self._settings.value("animate_panels", True)
        return value not in (False, "false", "0", 0)

    @animate_panels.setter
    def animate_panels(self, value: bool) -> None:
        self._settings.setValue("animate_panels", bool(value))
        self._settings.sync()
```

`settings_dialog.py`, in `_general` after the theme row (import `QCheckBox`):

```python
        self.animate_box = QCheckBox(t("settings.animate_panels"))
        self.animate_box.setChecked(self._prefs.animate_panels)
        self.animate_box.toggled.connect(self._animate_chosen)
        form.addRow("", self.animate_box)
```

```python
    def _animate_chosen(self, on: bool) -> None:
        self._prefs.animate_panels = on
```

`i18n.py`: `"settings.animate_panels": "Animate panels"` next to `settings.tab.general` in English, `"settings.animate_panels": "تحريك اللوحات"` in Arabic.

- [ ] **Step 5: Wire the two toggles and keep the suite still**

`new_job.py`: `from qurantext.gui import disclosure`; in `_set_more_options_visibility` replace `self.more_group.setVisible(open_)` with `disclosure.reveal(self.more_group, open_, animate=disclosure.animations_enabled(self._prefs))`.

`look_panel.py`: same import; in `_toggle_customise` replace `self.customise_box.setVisible(open_)` with `disclosure.reveal(self.customise_box, open_, animate=disclosure.animations_enabled(self._prefs))`.

Both call the function through the module, so a test can replace it. In `tests/conftest.py` add an autouse fixture (near `_theme_does_not_leak`):

```python
@pytest.fixture(autouse=True)
def _panels_do_not_animate(monkeypatch):
    """Every disclosure opens at once under test; tests/test_disclosure.py drives the motion itself."""
    try:
        from qurantext.gui import disclosure
    except ImportError:
        return
    monkeypatch.setattr(disclosure, "animations_enabled", lambda prefs: False)
```

(`tests/test_disclosure.py::test_animations_follow_the_setting_and_the_style_hint` must call the real function: have it `monkeypatch.undo()`-free by importing the function fresh — simplest is to assert through `disclosure.__dict__`? No: give that test `from qurantext.gui.disclosure import animations_enabled as real` at module top, before the fixture patches the module attribute, and call `real(prefs)`.)

- [ ] **Step 6: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_disclosure.py tests/test_settings_dialog.py tests/test_home_panels.py tests/test_review_widgets.py tests/test_review_window.py tests/test_i18n.py -q`
Expected: all PASS (the More options and Customise tests see immediate visibility).

- [ ] **Step 7: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/gui/disclosure.py src/qurantext/gui/prefs.py src/qurantext/gui/home/settings_dialog.py src/qurantext/gui/i18n.py src/qurantext/gui/home/new_job.py src/qurantext/gui/review/look_panel.py tests/conftest.py tests/test_disclosure.py tests/test_settings_dialog.py
git commit -m "Open More options and Customise by growing over 150 ms, off when the person or the style says so, with an Animate panels setting"
```

---

### Task 4: Noto Sans Arabic as the interface fallback

**Files:**
- Create: `tools/fetch_fonts.py`, `src/qurantext/assets/fonts/NotoSansArabic-Regular.ttf`, `src/qurantext/assets/fonts/NotoSansArabic-Bold.ttf`, `src/qurantext/assets/fonts/NotoSansArabic-OFL.txt`, `packaging/licenses/NotoSansArabic-OFL.txt`
- Modify: `src/qurantext/config/paths.py`, `src/qurantext/gui/language.py`, `src/qurantext/config/preflight.py`, `THIRD_PARTY_NOTICES.md`, `README.md`
- Test: `tests/test_language.py`, `tests/test_paths.py`, `tests/test_preflight.py`

**Interfaces:**
- Produces: `paths.NOTO_FONT_PATHS: tuple[Path, Path]`; `preflight._interface_font() -> CheckResult` listed after `_bundled_font()`; `language.ensure_arabic_font` registering Noto.

- [ ] **Step 1: Write the failing tests**

In `tests/test_language.py`, change `test_without_a_system_arabic_font_the_bundled_one_is_the_fallback`: after `assert family`, add `assert family == "Noto Sans Arabic"` and replace the comment `# registered from DEFAULT_FONT_PATH` with `# registered from NOTO_FONT_PATHS`. Add:

```python
def test_one_missing_noto_file_still_registers_the_other(
    qt_app, monkeypatch, tmp_path, _forget_the_fallback
) -> None:
    from qurantext.config.paths import NOTO_FONT_PATHS
    from qurantext.gui import language

    monkeypatch.setattr(language, "arabic_ui_families", lambda: [])
    monkeypatch.setattr(
        language, "NOTO_FONT_PATHS", (NOTO_FONT_PATHS[0], tmp_path / "gone-Bold.ttf")
    )
    assert language.ensure_arabic_font(QApplication.instance()) == "Noto Sans Arabic"


def test_no_noto_file_registers_nothing(qt_app, monkeypatch, tmp_path, _forget_the_fallback) -> None:
    from qurantext.gui import language

    monkeypatch.setattr(language, "arabic_ui_families", lambda: [])
    monkeypatch.setattr(language, "NOTO_FONT_PATHS", (tmp_path / "a.ttf", tmp_path / "b.ttf"))
    assert language.ensure_arabic_font(QApplication.instance()) is None
```

In `tests/test_paths.py` add:

```python
def test_the_interface_font_travels_with_the_package() -> None:
    from qurantext.config.paths import NOTO_FONT_PATHS

    for path in NOTO_FONT_PATHS:
        assert path.is_file() and path.stat().st_size > 100_000, path
    assert NOTO_FONT_PATHS[0].with_name("NotoSansArabic-OFL.txt").is_file()
```

In `tests/test_preflight.py` add:

```python
def test_the_interface_font_check_names_the_missing_file(monkeypatch, tmp_path) -> None:
    from qurantext.config import preflight
    from qurantext.config.paths import NOTO_FONT_PATHS

    ok = preflight._interface_font()
    assert ok.status == Status.OK and "NotoSansArabic-Regular.ttf" in ok.detail
    monkeypatch.setattr(preflight, "NOTO_FONT_PATHS", (NOTO_FONT_PATHS[0], tmp_path / "x-Bold.ttf"))
    bad = preflight._interface_font()
    assert bad.status == Status.FAIL and "x-Bold.ttf" in bad.detail and bad.remedy


def test_the_interface_font_is_checked_beside_the_bundled_font() -> None:
    names = [r.name for r in run_checks()]
    assert names.index("Interface font") == names.index("Bundled font") + 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_language.py tests/test_paths.py tests/test_preflight.py -q`
Expected: FAIL with `ImportError: NOTO_FONT_PATHS` and the family assertion.

- [ ] **Step 3: Fetch the fonts**

Write `tools/fetch_fonts.py` in the style of `tools/fetch_icons.py`:

```python
"""Fetch the interface's Arabic fallback font from its pinned release.

Noto Sans Arabic is the face the window falls back to for Arabic letters
on a machine with none of its own. The files are not generated: run this
once to (re)place them, then record the printed sha256 sums in
THIRD_PARTY_NOTICES.md.

    venv/bin/python tools/fetch_fonts.py
"""

from __future__ import annotations

import hashlib
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

TAG = "NotoSansArabic-v2.013"
URL = f"https://github.com/notofonts/arabic/releases/download/{TAG}/{TAG}.zip"
#: What is taken from the archive, and the name it gets beside the other fonts.
FILES = {
    "NotoSansArabic/unhinted/ttf/NotoSansArabic-Regular.ttf": "NotoSansArabic-Regular.ttf",
    "NotoSansArabic/unhinted/ttf/NotoSansArabic-Bold.ttf": "NotoSansArabic-Bold.ttf",
    "OFL.txt": "NotoSansArabic-OFL.txt",
}
ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "src" / "qurantext" / "assets" / "fonts"
LICENSES = ROOT / "packaging" / "licenses"


def main() -> int:
    with urllib.request.urlopen(URL, timeout=120) as response:  # noqa: S310 - a pinned https release
        archive = zipfile.ZipFile(io.BytesIO(response.read()))
    FONTS.mkdir(parents=True, exist_ok=True)
    for member, name in FILES.items():
        data = archive.read(member)
        target = FONTS / name
        target.write_bytes(data)
        print(f"{hashlib.sha256(data).hexdigest()}  {target.relative_to(ROOT)}")
    shutil.copyfile(FONTS / "NotoSansArabic-OFL.txt", LICENSES / "NotoSansArabic-OFL.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run it: `venv/bin/python tools/fetch_fonts.py`. Check the printed sums equal the two in Global Constraints; if they differ, stop and report (the release changed under its tag).

- [ ] **Step 4: Paths, language, doctor, notices**

`config/paths.py`, after `DEFAULT_FONT_PATH`:

```python
#: The interface's Arabic fallback: Noto Sans Arabic, Regular then Bold (SIL OFL 1.1).
NOTO_FONT_PATHS = (
    bundled_asset("fonts/NotoSansArabic-Regular.ttf"),
    bundled_asset("fonts/NotoSansArabic-Bold.ttf"),
)
```

`language.py`: import `NOTO_FONT_PATHS` instead of `DEFAULT_FONT_PATH`; in `ensure_arabic_font` replace the registration block with:

```python
    if _fallback is None:
        ids = [QFontDatabase.addApplicationFont(str(path)) for path in NOTO_FONT_PATHS]
        families = [
            family
            for font_id in ids
            if font_id != -1
            for family in QFontDatabase.applicationFontFamilies(font_id)
        ]
        if not families:
            return None  # the files are missing or unreadable; the doctor reports it
        _fallback = (ids[0] if ids[0] != -1 else ids[1], families[0])
```

and rewrite the docstring's middle paragraph: the bundled Noto Sans Arabic has Arabic letters only (no Latin), so it is a substitute of the application font's family; Qt draws Arabic with it and the rest with the system font; the Quran face is no longer used for the interface. Keep `_fallback` as `(font_id, family)`; `tests/test_language.py::_forget_the_fallback` removes by that id — read it and, if it removes one id, make it remove both by storing `(ids, family)` and adjusting the fixture to loop.

`preflight.py`, after `_bundled_font`:

```python
def _interface_font() -> CheckResult:
    """The Arabic fallback for the window's own text: both Noto Sans Arabic files."""
    missing = [path.name for path in NOTO_FONT_PATHS if not path.is_file()]
    if not missing:
        detail = ", ".join(f"{p.name} ({p.stat().st_size // 1024} KB)" for p in NOTO_FONT_PATHS)
        return CheckResult("Interface font", Status.OK, detail)
    return CheckResult(
        "Interface font",
        Status.FAIL,
        f"missing {', '.join(missing)} under {NOTO_FONT_PATHS[0].parent}",
        "Noto Sans Arabic ships inside the package (tools/fetch_fonts.py puts it there); "
        "a build missing it shows Arabic as boxes on a machine with no Arabic font.",
    )
```

and `_interface_font()` right after `_bundled_font()` in the list. Import `NOTO_FONT_PATHS` beside `DEFAULT_FONT_PATH`.

`THIRD_PARTY_NOTICES.md`: a `## Noto Sans Arabic` section after Amiri's, in its form: release `NotoSansArabic-v2.013`, copyright "2022 The Noto Project Authors (https://github.com/notofonts/arabic)", SIL Open Font License 1.1, the two files with their sha256, the licence at `qurantext/assets/fonts/NotoSansArabic-OFL.txt` and `packaging/licenses/NotoSansArabic-OFL.txt`, and that it is the interface's Arabic fallback. If `tests/` has a notices test that lists every asset (grep `THIRD_PARTY` in `tests/`), run it. `README.md`: where the bundled fonts are named, add Noto Sans Arabic as the interface fallback.

- [ ] **Step 5: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_language.py tests/test_paths.py tests/test_preflight.py tests/test_rtl.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add tools/fetch_fonts.py src/qurantext/assets/fonts/NotoSansArabic-Regular.ttf src/qurantext/assets/fonts/NotoSansArabic-Bold.ttf src/qurantext/assets/fonts/NotoSansArabic-OFL.txt packaging/licenses/NotoSansArabic-OFL.txt src/qurantext/config/paths.py src/qurantext/gui/language.py src/qurantext/config/preflight.py THIRD_PARTY_NOTICES.md README.md tests/test_language.py tests/test_paths.py tests/test_preflight.py
git commit -m "Bundle Noto Sans Arabic as the interface's Arabic fallback in place of the Quran face, with a doctor check that both files travel"
```

---

### Task 5: The contrast pass

**Files:**
- Modify: `src/qurantext/gui/theme.py` (`LIGHT.gold`)
- Test: `tests/test_theme.py`

**Interfaces:**
- Produces: `LIGHT.gold == "#A67C11"`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.parametrize("tokens", THEMES, ids=IDS)
def test_every_colour_added_since_phase_a_reads_on_its_surfaces(tokens) -> None:
    """One table for the ring, the amber, the playhead, the quiet accent and the hex labels."""
    pal = theme.palette(tokens)
    surfaces = {"window": tokens.window, "panel": tokens.panel, "raised": tokens.raised}
    checks = [
        ("gold", tokens.gold, {**surfaces, "white": "#FFFFFF"}, 3.0),
        ("amber", warning_color(pal).name(), surfaces, 4.5),
        ("playhead", playhead_color(pal).name(), {"window": tokens.window, "panel": tokens.panel}, 3.0),
        ("accent", tokens.accent, {"raised": tokens.raised, "window": tokens.window}, 4.5),
        ("secondary", tokens.secondary, {"raised": tokens.raised, "window": tokens.window}, 4.5),
        ("on_accent", tokens.on_accent, {"accent": tokens.accent}, 4.5),
    ]
    for name, colour, on, floor in checks:
        for surface, value in on.items():
            assert contrast(_c(colour), _c(value)) >= floor, (tokens.name, name, surface)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_theme.py -q -k since_phase_a`
Expected: the light case FAILS on `gold` / `window` (2.85).

- [ ] **Step 3: Move the light gold**

In `theme.py`'s `LIGHT` tokens set `gold="#A67C11"`. Grep `B8891C` across `src tests tools docs` and update any mention (the audit doc may name it; `tools/make_app_icon.py` must not read the token — if it does, leave the generated icon files as they are and say so in the report).

- [ ] **Step 4: Run the theme and panel tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_theme.py tests/test_review_widgets.py -q -k "theme or tile or ring or gold"`
Expected: all PASS (the ring test reads the token).

- [ ] **Step 5: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/gui/theme.py tests/test_theme.py
git commit -m "Check every colour added since phase A on every surface it sits on, and deepen the light theme's gold so the ring clears 3:1"
```

---

### Task 6: Phase C leftovers — the column sizing, the playhead rect, a docstring

**Files:**
- Modify: `src/qurantext/gui/review/window.py` (`_size_columns`, `_TIMELINE_ROOM`), `src/qurantext/gui/review/waveform_view.py` (the playhead), `tests/test_review_window.py` (the docstring at the test near line 2846)
- Test: `tests/test_review_window.py`, `tests/test_review_widgets.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_review_window.py`, beside the 1280 px fit tests:

```python
@pytest.mark.parametrize(
    ("width", "opens_wide"),
    [(1280, True), (1150, False)],  # 1280 − (480 + 24) = 776 ≥ 700; 1150 − 504 = 646 < 700
)
def test_a_landscape_window_opens_its_left_column_wide_only_with_timeline_room(
    qt_app, tmp_path, width, opens_wide
) -> None:
    from qurantext.gui import theme
    from qurantext.gui.review import window as module

    theme.apply_theme(qt_app, "light")
    window = _lecture_window(qt_app, tmp_path, preset="high")
    window.resize(width, 800)
    window.show()
    qt_app.processEvents()
    wide = window.frame_view.preset_size.width() + 2 * theme.SP_12
    assert window.width() - wide >= module._TIMELINE_ROOM if opens_wide else True
    left = window._splitter.sizes()[0]
    assert (left == wide) if opens_wide else (left == window.left_column.minimumWidth())
    window.close()
```

Read `_lecture_window` for how a preset is passed (`preset="high"` is the 1920×1080 preset; `frame_view.preset_size` is then 480 wide in fit mode — check `FrameView.preset_size` and use the value it reports). If both cases pass before any change, the branch was reachable all along: keep the code, keep the test, and say so in the report. If the wide case fails, read `_size_columns` and `showEvent` and make the first show size the columns after the window has its final width (`QTimer.singleShot(0, self._size_columns)` from `showEvent`), then rerun.

In `tests/test_review_widgets.py`, beside the waveform tests:

```python
def test_the_playhead_is_a_two_pixel_rect_ending_at_its_column(qt_app) -> None:
    from PySide6.QtGui import QColor

    from qurantext.gui.colors import playhead_color
    from qurantext.gui.review.viewport import Viewport
    from qurantext.gui.review.waveform_view import WaveformView

    viewport = Viewport(duration=10.0)
    view = WaveformView(viewport)
    view.resize(200, 60)
    view.show()
    _spin_briefly(qt_app)
    view.set_playhead(5.0)
    x = view._playhead_column(view.width())
    image = view.grab().toImage()
    red = playhead_color(view.palette())
    hits = [dx for dx in range(-3, 4) if image.pixelColor(x + dx, 30) == QColor(red)]
    assert hits == [-1, 0], hits
    view.close()
```

Check `WaveformView`'s constructor signature and `Viewport`'s in the module before writing; adapt the two constructor lines to them.

- [ ] **Step 2: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_window.py tests/test_review_widgets.py -q -k "timeline_room or two_pixel_rect"`
Expected: the playhead test FAILS (a 2 px pen line lands on columns `x` and `x+1`, or antialiased); the column test may pass or fail, see Step 1.

- [ ] **Step 3: Implement**

`waveform_view.py`: replace

```python
                painter.setPen(QPen(playhead_color(palette), 2))
                painter.drawLine(playhead_x, 0, playhead_x, height)
```

with

```python
                # A filled rect, not a 2 px pen: the pen's two columns depend on
                # antialiasing and the line's direction; the rect always ends at x.
                painter.fillRect(playhead_x - 1, 0, 2, height, playhead_color(palette))
```

and drop `QPen` from the imports if nothing else uses it. In `_playhead_column`'s docstring say the rect covers columns `x − 1` and `x`, so column 0 draws one column and the right edge two.

`tests/test_review_window.py`, the docstring of `test_a_window_shown_at_its_own_size_keeps_the_preview_at_its_preset_height`: replace "which is what ``show()`` gives on a screen of 1080 px and up" with "as a screen tall enough to hold the size hint would show it".

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_window.py tests/test_review_widgets.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/gui/review/window.py src/qurantext/gui/review/waveform_view.py tests/test_review_window.py tests/test_review_widgets.py
git commit -m "Pin when the review's left column opens wide, draw the playhead as a two-pixel rect ending at its column, and say what the size-hint test checks"
```

---

### Task 7: Phase B/D leftovers — sharp pictures, indent, descriptions, caches, HiDPI, the test cache

**Files:**
- Modify: `src/qurantext/gui/review/episode_dialog.py`, `src/qurantext/gui/review/export_dialog.py`, `src/qurantext/gui/review/look_panel.py`, `src/qurantext/gui/widgets.py`, `src/qurantext/jobs/clip_frames.py`, `tests/conftest.py`, `tests/test_review_widgets.py`, `tests/test_review_window.py`
- Test: `tests/test_review_widgets.py`, `tests/test_review_window.py`, `tests/test_widgets.py`, `tests/test_clip_frames.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_review_widgets.py` (Episode section):

```python
def test_the_recitation_card_is_drawn_sharp_at_its_box_and_cached(
    qt_app, episode_lecture, prefs, tmp_path, monkeypatch
) -> None:
    from PIL import Image

    from qurantext.gui.review import episode_dialog
    from qurantext.gui.review.episode_dialog import EpisodeDialog

    paths = _recitation_jobs(monkeypatch, tmp_path, episode_lecture.project.path)
    _fake_probe(monkeypatch, {"fatiha.mp4": 7.0})
    drawn = []

    def picture(project, look, size):
        drawn.append(size)
        return Image.new("RGB", size, (10, 200, 10))

    monkeypatch.setattr(episode_dialog, "thumbnail_image", picture)
    dialog = EpisodeDialog(episode_lecture, prefs=prefs, job_dirs=[tmp_path])
    box = dialog.recitation_box
    box.setCurrentIndex(box.findData(paths["rendered"]))
    card = dialog.cards["recitation"]
    assert card.thumb_label.pixmap().size().toTuple()[1] == 99 or (
        card.thumb_label.pixmap().size().toTuple()[0] == 176
    )
    assert drawn and max(drawn[-1]) == 176, "drawn for the card, not upscaled from 96 px"
    first = card.thumb_label.pixmap().cacheKey()
    dialog.outro_link.setText("example.org")  # any edit: _update_cards runs again
    assert card.thumb_label.pixmap().cacheKey() == first and len(drawn) == 1, "cached"
```

Read `_recitation_jobs` for the key of its rendered job (the dict it returns) and the lecture's own picture call: `drawn` must count only the recitation's draws, so compare `size` against `fitted_size` of the recitation's preset (the lecture card draws once at open with the lecture's size; count calls after `setCurrentIndex` instead if sizes coincide).

```python
def test_a_colour_row_tells_a_screen_reader_its_hex(qt_app, session, prefs) -> None:
    panel = _panel(session, prefs)
    row = panel.colour_buttons["card"]
    assert row.accessibleDescription() == row.hex_label.text()
```

In `tests/test_review_window.py` (Export section):

```python
def test_the_format_hint_lines_up_with_the_checkbox_text(qt_app, tmp_path) -> None:
    from PySide6.QtWidgets import QStyle, QStyleOptionButton

    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.session import ReviewSession

    dialog = ExportDialog(ReviewSession(_project(tmp_path)))
    box = dialog._format_boxes["srt"]
    option = QStyleOptionButton()
    box.initStyleOption(option)
    contents = box.style().subElementRect(QStyle.SubElement.SE_CheckBoxContents, option, box)
    assert dialog.format_hints["srt"].indent() == contents.left()
```

In `tests/test_widgets.py`:

```python
def test_chip_and_tile_pixmaps_carry_the_widgets_device_pixel_ratio(qt_app) -> None:
    from PySide6.QtCore import QSize

    from qurantext.core.looks import NIGHT_GOLD
    from qurantext.gui.review.look_panel import _chip_icon, _swatch_icon
    from qurantext.gui.widgets import StatusChip

    chip = StatusChip("x", "info", "neutral")
    assert chip.icon_label.pixmap().devicePixelRatio() == chip.icon_label.devicePixelRatioF()
    for ratio in (1.0, 2.0):
        pixmap = _swatch_icon(NIGHT_GOLD, ratio=ratio).pixmap(QSize(56, 36), ratio)
        assert pixmap.devicePixelRatio() == ratio and pixmap.size() == QSize(56 * ratio, 36 * ratio)
        chip_pixmap = _chip_icon(NIGHT_GOLD.card, ratio=ratio).pixmap(QSize(24, 24), ratio)
        assert chip_pixmap.devicePixelRatio() == ratio
```

In `tests/test_clip_frames.py` nothing new; in `tests/conftest.py` the autouse fixture is pinned by a test in `tests/test_thumbnails.py`:

```python
def test_every_test_has_a_private_cache_dir() -> None:
    import os

    from qurantext.config.paths import user_cache_dir

    assert os.environ.get("QURANTEXT_CACHE_DIR"), "conftest points the cache at tmp_path"
    assert "pytest" in str(user_cache_dir()) or "tmp" in str(user_cache_dir())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py tests/test_review_window.py tests/test_widgets.py tests/test_thumbnails.py -q -k "sharp or screen_reader or lines_up or device_pixel or private_cache"`
Expected: all five FAIL.

- [ ] **Step 3: Implement**

`episode_dialog.py`:
- Import `fitted_size` (already) and `thumbnail_image` (already); drop `thumbnail_for` from the import and its use. Add `from qurantext.core.looks import look_from_style` if not imported.
- `self._card_pixmaps: dict[tuple[str, Path], QPixmap] = {}` in `__init__` beside `_recitation_projects`.
- A method:

```python
    def _recitation_picture(self, path: Path) -> QPixmap | None:
        """The recitation's first card at its own look, drawn once per job for the card's box."""
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
```

- In `_update_cards`' recitation branch replace the `thumbnail_for` lines with `picture = self._recitation_picture(recitation)` and `card.set_thumbnail(picture)` when not None, else the existing placeholder/film branches (`project is None` → placeholder, else film icon).
- Clip frames: in the clip branch, cache `QPixmap(str(row.frame))` under `("clip", row.frame)` the same way (a helper `_clip_picture(frame: Path) -> QPixmap | None` returning None for a null pixmap).
- The clip-name comment near `_ClipRow.set`: say "any name wider than the card's inner width is elided in the middle".

`clip_frames.py`: in the module docstring and `clip_frame`'s, add that when ffmpeg writes an empty file (the seek landed past the picture) the frame at 0 s is taken instead, and only then does the result give up.

`export_dialog.py`: replace the `_HINT_INDENT` constant with a per-box measurement:

```python
            option = QStyleOptionButton()
            box.initStyleOption(option)
            contents = box.style().subElementRect(QStyle.SubElement.SE_CheckBoxContents, option, box)
            hint.setIndent(contents.left())  # under the box's text, on every platform style
```

(imports `QStyle`, `QStyleOptionButton` from `PySide6.QtWidgets`).

`look_panel.py`:
- `_ColourRow.set_colour`: after setting the hex text, `self.setAccessibleDescription(self.hex_label.text())`.
- Give `_swatch_icon(look, ratio: float = 1.0)`, `_chip_icon(colour, ratio: float = 1.0)`, `_icon_tile(colour, name, ratio: float = 1.0)`, `_ringed(pixmap)` and `_pil_pixmap(image, ratio: float = 1.0)` device-pixel awareness: each creates its `QPixmap` at `size * ratio`, calls `pixmap.setDevicePixelRatio(ratio)`, and paints in logical coordinates (Qt scales a painter on a pixmap with a ratio). `_ringed` keeps the pixmap's ratio (`QPixmap(pixmap)` copies it) and paints at logical size (`pixmap.width() / ratio`). `_paint_tiles` asks `tile_image` for `_SWATCH.width() * ratio` by `_SWATCH.height() * ratio` and passes `ratio` to `_pil_pixmap`. The panel reads `ratio = self.devicePixelRatioF()` once per `_show` and passes it everywhere; `_two_state_icon` stays as it is.

`widgets.py`, `StatusChip._draw_icon`: `ratio = self.icon_label.devicePixelRatioF()`; `pixmap = icon(self._icon_name, role).pixmap(QSize(16, 16), ratio)`; the amber tint path copies and fills as today (the copy keeps the ratio).

`tests/conftest.py`: an autouse fixture

```python
@pytest.fixture(autouse=True)
def _private_cache_dir(monkeypatch, tmp_path):
    """No test writes thumbnails or clip frames into the person's real cache."""
    monkeypatch.setenv("QURANTEXT_CACHE_DIR", str(tmp_path / "cache"))
```

Then remove the now-redundant `monkeypatch.setenv("QURANTEXT_CACHE_DIR", …)` lines in `tests/test_review_widgets.py` (two) and `tests/test_review_window.py` (one); leave `tests/test_model_store.py`, `tests/test_gate_script.py` and `tests/test_screenshots_tool.py` alone (they set or read it for their own reasons; run `tests/test_screenshots_tool.py` to be sure the fixture does not break its before/after check, and if it does, read that test and adapt the fixture to it).

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_review_widgets.py tests/test_review_window.py tests/test_widgets.py tests/test_thumbnails.py tests/test_clip_frames.py tests/test_screenshots_tool.py tests/test_home_panels.py tests/test_rtl.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add src/qurantext/gui/review/episode_dialog.py src/qurantext/gui/review/export_dialog.py src/qurantext/gui/review/look_panel.py src/qurantext/gui/widgets.py src/qurantext/jobs/clip_frames.py tests/conftest.py tests/test_review_widgets.py tests/test_review_window.py tests/test_widgets.py tests/test_thumbnails.py
git commit -m "Draw the recitation card sharp and cache card pictures, take the Export hint's indent from the style, tell screen readers a colour row's hex, draw chips and tiles at the screen's pixel ratio, and keep every test out of the real cache"
```

---

### Task 8: Docs, screenshots and the whole suite

**Files:**
- Modify: `docs/release-checklist.md`, `README.md` (if a fonts or settings line needs it)

- [ ] **Step 1: Docs**

In `docs/release-checklist.md`: add `settings.animate_panels` to the Arabic strings awaiting native review; add a line under the release's visual checks to look at `settings-general-ar-dark.png` and `review-recitation-en-dark.png` for the checkbox, radio and field outlines; note that the focus ring now paints for keyboard focus only.

- [ ] **Step 2: Screenshots**

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src venv/bin/python tools/screenshots.py /tmp/phase-e-shots
```

Look (Read tool) at `settings-general-en-light.png`, `settings-general-ar-dark.png`, `settings-videos-en-dark.png` (checkboxes and combos outlined), `review-recitation-en-dark.png`, `review-customise-en-light.png` (the deeper gold ring), `episode-en-light.png`, `home-en-dark.png`. Fix in the source anything visibly wrong (an outline drawn off its box, a ring that vanished) and say what you changed.

- [ ] **Step 3: Lint and the whole suite**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q
```

Expected: everything passes (master was 2436 passed, 2 skipped; this phase adds about thirty tests).

- [ ] **Step 4: Commit**

```bash
git add docs/release-checklist.md README.md
git commit -m "List the phase E string for Arabic review and the dark-theme images to check for outlines"
```

(Leave `README.md` out of the `git add` if it did not change.)

---

## Self-review

- **Spec coverage.** §2.1 motion → Task 3; §2.2 focus → Task 1; §2.3 cards → Task 1; §2.4 outlines → Task 2; §2.5 font → Task 4; §2.6 contrast → Task 5; §2.7 leftovers → Tasks 6 and 7, except the ruler ×1.15 (deviation stated at the top); §3 modules → each task; §5 error handling: destroyed widget (animation parented to it, Task 3), hidden window (Task 3 test), missing Noto file (Task 4 tests), no Fusion (Task 2 comment), non-widget focus (Task 1 `isinstance` guard); §6 testing: each bullet has its task.
- **Placeholders.** The `Qt_NoBrush()` placeholder in Task 2 is called out and resolved in the text under it; no other placeholder.
- **Type consistency.** `reveal(widget, open_, *, animate, duration_ms)` is the only signature, used by Tasks 3's two toggles; `animations_enabled(prefs)` is replaced by the conftest with a one-argument lambda; `KBDFOCUS` is a module constant used by the tests; `_interface_font` returns `CheckResult` like its neighbour; `_swatch_icon(look, ratio=1.0)` / `_chip_icon(colour, ratio=1.0)` match the Task 7 test.
- **Review Focus.** Each of the five lines names its test and task.

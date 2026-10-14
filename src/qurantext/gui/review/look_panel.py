"""The Look panel: a video's palette, colours and background, beside its frame.

Every change goes through the session (:meth:`ReviewSession.set_look`), so a
look is undone, saved and marked unsaved like any timing edit; a slider drag
is one gesture and undoes as one step. The panel only asks and shows: it
emits :attr:`LookPanel.look_changed` after each change it made, and the window
redraws the preview. After a change the panel did not make (undo, redo,
discard) the window calls :meth:`LookPanel.refresh`, which reads the look back
into the controls without emitting anything.

The readability check measures the text colours against the card as it sits
on this background (its average colour, from the same cached layer the
preview draws on), and the same layer says when a chosen image has gone
missing or cannot be read.

The panel sits in a scroll area, so its sliders take the mouse wheel only
once they have focus, and the background tiles never take it: scrolling past
them moves the panel, never the look.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QHideEvent,
    QIcon,
    QImage,
    QMouseEvent,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qurantext.core.backgrounds import tile_image
from qurantext.core.frame_renderer import frame_base_layer
from qurantext.core.looks import (
    BACKGROUND_KINDS,
    EDITABLE_COLOURS,
    IMAGE_SUFFIXES,
    MAX_BLUR,
    MAX_DIM,
    NIGHT_GOLD,
    PRESETS,
    RGBA,
    Background,
    Look,
    readability_warnings,
)
from qurantext.gui import disclosure, theme
from qurantext.gui.colors import warning_color
from qurantext.gui.i18n import is_rtl, plain_title, t
from qurantext.gui.icons import icon, set_icon
from qurantext.gui.prefs import Prefs
from qurantext.gui.review.session import ReviewSession
from qurantext.gui.widgets import SectionHeader
from qurantext.jobs.look_assets import import_look_image

__all__ = ["LOOK_WARNING_KEYS", "LookPanel", "look_warning_key", "look_warning_text"]

#: The sentence for each code the renderer reports about a look's image.
LOOK_WARNING_KEYS = {
    "image_missing": "look.image_missing",
    "image_unreadable": "look.image_unreadable",
}

#: A palette or background tile, in pixels.
_SWATCH = QSize(56, 36)
#: A colour row's chip.
_CHIP = QSize(24, 24)
#: Tiles per row; three fit the panel's width with their names under them.
_SWATCH_COLUMNS = 3
#: The ring a chosen tile wears, in pixels.
_RING = 2
#: The ring's gold on a pale tile: 3.03:1 on Ink on paper's frame (#E8E2D4), the palest
#: preset, and 3.52:1 and 4.40:1 on the light and dark windows beside it. The light
#: theme's gold token (#A67C11) is 2.95:1 on that frame, so the ring takes its own.
_PALE_RING = "#A47A10"
#: A slider's value readout, wide enough for "100%".
_READOUT_WIDTH = 44
#: What an image starts dimmed by, so the text on the card still reads.
_IMAGE_DIM = 0.35
#: How far a second colour sits from the first when a look has only one
#: (a gradient or pattern chosen over a solid colour).
_SHADE_STEP = 22


def look_warning_text(code: str) -> str:
    """The person's sentence for a renderer's look warning code."""
    return t(look_warning_key(code))


def look_warning_key(code: str) -> str:
    """The key of that sentence; a code this build does not know reads as unreadable."""
    return LOOK_WARNING_KEYS.get(code, "look.image_unreadable")


def _preset_name(name: str) -> str:
    keys = {
        "night_gold": t("look.preset.night_gold"),
        "emerald": t("look.preset.emerald"),
        "sand": t("look.preset.sand"),
        "ink_on_paper": t("look.preset.ink_on_paper"),
        "ocean": t("look.preset.ocean"),
        "rose": t("look.preset.rose"),
    }
    return keys.get(name, name)


def _colour_name(name: str) -> str:
    keys = {
        "body_text": t("look.colour.body_text"),
        "highlight_word": t("look.colour.highlight_word"),
        "header_text": t("look.colour.header_text"),
        "card": t("look.colour.card"),
        "caption_text": t("look.colour.caption_text"),
        "caption_active": t("look.colour.caption_active"),
        "placeholder_text": t("look.colour.placeholder_text"),
    }
    return keys.get(name, name)


def _background_name(kind: str) -> str:
    keys = {
        "solid": t("look.bg.solid"),
        "gradient": t("look.bg.gradient"),
        "pattern_stars": t("look.bg.pattern_stars"),
        "pattern_lattice": t("look.bg.pattern_lattice"),
        "pattern_arches": t("look.bg.pattern_arches"),
        "image": t("look.bg.image"),
    }
    return keys.get(kind, kind)


def _qcolor(colour: tuple[int, ...]) -> QColor:
    return QColor(*colour)


def _ring_gold(pixmap: QPixmap) -> QColor:
    """The gold that reads on *pixmap*'s edge, whatever the theme.

    The dark theme's gold is 1.53:1 on the palest preset tile, so a pale tile (its
    pixel at 2, 2 has a lightness of 128 or more) wears the deeper ``_PALE_RING``,
    and a dark one the dark theme's gold.
    """
    ratio = pixmap.devicePixelRatio()
    at = int(2 * ratio)  # logical (2, 2) in the pixmap's own pixels
    corner = pixmap.toImage().pixelColor(at, at)
    return QColor(_PALE_RING if corner.lightness() >= 128 else theme.DARK.gold)


def _ringed(pixmap: QPixmap) -> QPixmap:
    """*pixmap* with a gold ring on its edge, in the gold that reads on it: the chosen tile.

    The copy keeps *pixmap*'s pixel ratio, so the ring is painted in its logical pixels.
    """
    ratio = pixmap.devicePixelRatio()
    ringed = QPixmap(pixmap)
    painter = QPainter(ringed)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(_ring_gold(pixmap), _RING))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    half = _RING / 2
    width, height = pixmap.width() / ratio, pixmap.height() / ratio
    painter.drawRoundedRect(QRectF(half, half, width - _RING, height - _RING), 3, 3)
    painter.end()
    return ringed


def _two_state_icon(pixmap: QPixmap) -> QIcon:
    """*pixmap* plain when not chosen, ringed when chosen (``QIcon.State.On``)."""
    result = QIcon()
    result.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
    result.addPixmap(_ringed(pixmap), QIcon.Mode.Normal, QIcon.State.On)
    return result


def _canvas(size: QSize, ratio: float) -> QPixmap:
    """A pixmap *size* logical pixels big at *ratio*: sharp on a HiDPI screen.

    A painter on it works in logical pixels (Qt scales it by the ratio).
    """
    pixmap = QPixmap(size * ratio)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def _swatch_icon(look: Look, ratio: float = 1.0) -> QIcon:
    """The preset in miniature: its card on its background, a line of text and a highlight."""
    pixmap = _canvas(_SWATCH, ratio)
    pixmap.fill(_qcolor(look.frame_bg))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_qcolor(look.card))
    painter.drawRoundedRect(QRectF(4, 4, _SWATCH.width() - 8, _SWATCH.height() - 8), 4, 4)
    painter.setBrush(_qcolor(look.body_text))
    painter.drawRoundedRect(QRectF(10, 11, 36, 3), 1.5, 1.5)
    painter.drawRoundedRect(QRectF(10, 20, 14, 3), 1.5, 1.5)
    painter.setBrush(_qcolor(look.highlight_word))
    painter.drawRoundedRect(QRectF(27, 20, 19, 3), 1.5, 1.5)
    painter.end()
    return _two_state_icon(pixmap)


def _chip_icon(colour: RGBA, ratio: float = 1.0) -> QIcon:
    """A colour as a small square, over a checkerboard so a see-through colour shows as one."""
    pixmap = _canvas(_CHIP, ratio)
    pixmap.fill(QColor(255, 255, 255))
    painter = QPainter(pixmap)
    painter.setPen(Qt.PenStyle.NoPen)
    half = _CHIP.width() // 2
    painter.setBrush(QColor(200, 200, 200))
    painter.drawRect(0, 0, half, half)
    painter.drawRect(half, half, half, half)
    painter.setBrush(_qcolor(colour))
    painter.drawRect(0, 0, _CHIP.width(), _CHIP.height())
    painter.setPen(QColor(128, 128, 128))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(0, 0, _CHIP.width() - 1, _CHIP.height() - 1)
    painter.end()
    return QIcon(pixmap)


def _shade(colour: RGBA) -> RGBA:
    """A second colour near *colour*: lighter on a dark one, darker on a light one."""
    r, g, b, a = colour
    step = _SHADE_STEP if (r * 299 + g * 587 + b * 114) / 1000 < 128 else -_SHADE_STEP
    return (*(max(0, min(255, c + step)) for c in (r, g, b)), a)  # type: ignore[return-value]


def _second_colour(look: Look, colour: RGBA) -> RGBA:
    """The preset's own second colour when it has one, else a shade of *colour*."""
    preset = PRESETS.get(look.base_preset, NIGHT_GOLD).background
    if preset.colour == colour and preset.colour2 != colour:
        return preset.colour2
    return _shade(colour)


def _background_for_kind(look: Look, kind: str) -> Background:
    """The background choosing *kind* gives *look*: a solid one is the frame's colour,
    the rest keep the colours and derive a second when there is none; dim and blur start over."""
    if kind == "solid":
        return Background("solid", look.frame_bg, look.frame_bg)
    colour = look.background.colour
    colour2 = look.background.colour2
    if colour2 == colour:
        colour2 = _second_colour(look, colour)
    return Background(kind, colour, colour2)


def _pil_pixmap(image, ratio: float = 1.0) -> QPixmap:  # noqa: ANN001 — a PIL image
    """*image* (drawn at *ratio* times the logical size) as a pixmap at *ratio*."""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    qimage = QImage(rgba.tobytes(), width, height, 4 * width, QImage.Format.Format_RGBA8888)
    pixmap = QPixmap.fromImage(qimage.copy())
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def _icon_tile(colour: RGBA, name: str, ratio: float = 1.0) -> QPixmap:
    """*name*'s icon centred on *colour*: the image tile while the look has no image."""
    pixmap = _canvas(_SWATCH, ratio)
    pixmap.fill(_qcolor(colour))
    glyph = icon(name, "secondary").pixmap(QSize(20, 20), ratio)
    painter = QPainter(pixmap)
    painter.drawPixmap((_SWATCH.width() - 20) // 2, (_SWATCH.height() - 20) // 2, glyph)
    painter.end()
    return pixmap


def _alpha_percent(alpha: int) -> int:
    return round(alpha * 100 / 255)


def _rgba(colour: QColor) -> RGBA:
    return (colour.red(), colour.green(), colour.blue(), colour.alpha())


class _ColourRow(QPushButton):
    """One editable colour: its chip, its name, and its hex at the trailing end.

    The sheet's ``text-align: left`` is the start of the line: Qt mirrors it in a
    right-to-left window, so an Arabic row starts at the right with no rule of its own.
    """

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(name, parent)
        self.setProperty("row", True)
        self.setIconSize(_CHIP)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        trailing = QHBoxLayout(self)
        trailing.setContentsMargins(0, 0, theme.SP_8, 0)
        trailing.addStretch(1)
        self.hex_label = QLabel()
        self.hex_label.setFont(theme.font("secondary"))
        self.hex_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        # A hex is a code, not a sentence: it reads left to right in both languages.
        self.hex_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        # A click on the hex is a click on the row.
        self.hex_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        trailing.addWidget(self.hex_label)

    def set_colour(self, colour: RGBA, ratio: float = 1.0) -> None:
        """Show *colour* as the chip (drawn at *ratio*) and as its hex.

        The hex is also the row's accessible description: a screen reader says the
        row's name and then its colour, which the chip alone does not.
        """
        self.setIcon(_chip_icon(colour, ratio))
        self.hex_label.setText("#{:02X}{:02X}{:02X}".format(*colour[:3]))
        self.setAccessibleDescription(self.hex_label.text())


class _GestureSlider(QSlider):
    """A slider whose drag is one gesture however it ends, and that leaves the wheel alone.

    Qt hands a slider the wheel whether or not it has focus, so scrolling the
    panel would edit each slider passing under the pointer. Until a click or
    Tab gives it focus, the wheel goes on to the scroll area instead.

    A drag can lose its mouse grab with no release ever arriving: focus moves
    away, a modal dialog opens (a render's "ready" box), the panel is hidden
    or disabled. Left down, the session's gesture stays open and every later
    edit merges into its undo step (as ``WordStrip._finish_drag`` explains), so
    each of those paths lets the slider go: ``sliderReleased`` closes the
    gesture, and the rest of that drag is ignored.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def let_go(self) -> None:
        """End a drag as a release would; nothing when the slider is not held."""
        if not self.isSliderDown():
            return
        # A release with no button held: QSlider forgets the grabbed handle
        # (later moves of that drag are then ignored) and says it was released.
        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(0, 0),
            QPointF(self.mapToGlobal(QPointF(0, 0))),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        super().mouseReleaseEvent(release)
        if self.isSliderDown():  # held without the mouse (setSliderDown)
            self.setSliderDown(False)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt override
        if not self.hasFocus():
            event.ignore()  # on to the scroll area
            return
        super().wheelEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt override
        self.let_go()
        super().focusOutEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 - Qt override
        self.let_go()
        super().hideEvent(event)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self.let_go()
        super().changeEvent(event)


class LookPanel(QWidget):
    """Palette swatches, Customise, Background, and the default; edits go through the session."""

    #: The panel changed the session's look (the window redraws the preview).
    look_changed = Signal()
    #: A problem to show in the warnings strip, already in the person's words.
    notice = Signal(str)
    #: Every problem the current look has (its image), in the person's words;
    #: replaces the last list, so a problem that went away leaves the strip.
    look_notices = Signal(list)
    #: A short confirmation for the status bar, already in the person's words.
    message = Signal(str)

    def __init__(
        self,
        session: ReviewSession,
        *,
        prefs: Prefs,
        frame_size: tuple[int, int],
        reserve_caption_band: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._prefs = prefs
        self._frame_size = frame_size
        self._reserve_caption_band = reserve_caption_band
        #: The look the controls show; refresh skips the work when it has not changed.
        self._shown: Look | None = None
        self._build()
        self._wire()
        self.refresh()

    # -- layout -----------------------------------------------------------------

    def _build(self) -> None:
        column = QVBoxLayout(self)
        column.setContentsMargins(4, 0, 4, 0)

        self.header = SectionHeader(t("look.title"))
        column.addWidget(self.header)

        palette_row = QHBoxLayout()
        palette_row.addWidget(QLabel(t("look.palette")))
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        palette_row.addWidget(self.status_label, 1)
        column.addLayout(palette_row)

        # The swatches are a row of samples, not a sentence: they keep one order
        # in both languages, as the frame they describe does.
        swatches = QWidget()
        swatches.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        grid = QGridLayout(swatches)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        self.palette_buttons: dict[str, QToolButton] = {}
        for index, (name, look) in enumerate(PRESETS.items()):
            button = QToolButton()
            button.setCheckable(True)
            button.setAutoRaise(True)
            # The chosen tile wears a gold ring (its On pixmap); the sheet gives it
            # the accent text (``swatch`` marks it).
            button.setProperty("swatch", True)
            button.setIcon(_swatch_icon(look, self.devicePixelRatioF()))
            button.setIconSize(_SWATCH)
            button.setText(_preset_name(name))
            button.setToolTip(_preset_name(name))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            # Equal columns, whatever length each name has in this language.
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.palette_buttons[name] = button
            grid.addWidget(button, index // _SWATCH_COLUMNS, index % _SWATCH_COLUMNS)
        for column_index in range(_SWATCH_COLUMNS):
            grid.setColumnStretch(column_index, 1)
        column.addWidget(swatches)

        self.customise_toggle = QToolButton()
        self.customise_toggle.setText(t("look.customise"))
        self.customise_toggle.setCheckable(True)
        self.customise_toggle.setAutoRaise(True)
        self.customise_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        set_icon(self.customise_toggle, "chevron-right", size=16)
        column.addWidget(self.customise_toggle)

        self.customise_box = QWidget()
        custom = QVBoxLayout(self.customise_box)
        custom.setContentsMargins(0, 0, 0, 0)
        self.colour_buttons: dict[str, _ColourRow] = {}
        for name in EDITABLE_COLOURS:
            button = _ColourRow(_colour_name(name))
            self.colour_buttons[name] = button
            custom.addWidget(button)
            if name == "card":
                self.opacity_label = QLabel(t("look.card_opacity"))
                self.opacity_slider = _GestureSlider()
                self.opacity_slider.setRange(0, 100)
                self.opacity_label.setBuddy(self.opacity_slider)
                self.opacity_readout = self._readout()
                custom.addWidget(self.opacity_label)
                opacity_row = QHBoxLayout()
                opacity_row.addWidget(self.opacity_slider, 1)
                opacity_row.addWidget(self.opacity_readout)
                custom.addLayout(opacity_row)
        # The colour a built-in background is drawn in; an image has none to pick.
        self.background_colour_button = _ColourRow(t("look.colour.background"))
        custom.addWidget(self.background_colour_button)
        self.customise_box.setVisible(False)
        column.addWidget(self.customise_box)

        self.contrast_label = QLabel()
        self.contrast_label.setWordWrap(True)
        self.contrast_label.setVisible(False)
        column.addWidget(self.contrast_label)

        background_label = QLabel(t("look.background"))
        column.addWidget(background_label)
        # A row of samples like the palette's: one order in both languages.
        tiles = QWidget()
        tiles.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        tile_grid = QGridLayout(tiles)
        tile_grid.setContentsMargins(0, 0, 0, 0)
        tile_grid.setSpacing(2)
        self.background_tiles: dict[str, QToolButton] = {}
        for index, kind in enumerate(BACKGROUND_KINDS):
            tile = QToolButton()
            tile.setCheckable(True)
            tile.setAutoRaise(True)
            tile.setProperty("swatch", True)
            tile.setIconSize(_SWATCH)
            tile.setText(_background_name(kind))
            tile.setToolTip(_background_name(kind))
            tile.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.background_tiles[kind] = tile
            tile_grid.addWidget(tile, index // _SWATCH_COLUMNS, index % _SWATCH_COLUMNS)
        for column_index in range(_SWATCH_COLUMNS):
            tile_grid.setColumnStretch(column_index, 1)
        column.addWidget(tiles)
        #: What the tiles were last painted for; they are rebuilt when it changes.
        self._tiles_key: tuple | None = None

        self.image_button = QPushButton(t("look.choose_image"))
        self.image_button.setProperty("quiet", True)
        set_icon(self.image_button, "image", size=16)
        column.addWidget(self.image_button)
        if self._session.project.path is None:
            # The image is copied beside the project file; without one there is nowhere.
            self.image_button.setEnabled(False)
            self.image_button.setToolTip(t("session.no_file"))
            self.background_tiles["image"].setEnabled(False)
            self.background_tiles["image"].setToolTip(t("session.no_file"))

        self.dim_label = QLabel(t("look.dim"))
        self.dim_slider = _GestureSlider()
        self.dim_slider.setRange(0, round(MAX_DIM * 100))
        self.dim_label.setBuddy(self.dim_slider)
        self.blur_label = QLabel(t("look.blur"))
        self.blur_slider = _GestureSlider()
        self.blur_slider.setRange(0, round(MAX_BLUR))
        self.blur_label.setBuddy(self.blur_slider)
        self.dim_readout = self._readout()
        self.blur_readout = self._readout()
        sliders = QGridLayout()
        sliders.addWidget(self.dim_label, 0, 0)
        sliders.addWidget(self.dim_slider, 0, 1)
        sliders.addWidget(self.dim_readout, 0, 2)
        sliders.addWidget(self.blur_label, 1, 0)
        sliders.addWidget(self.blur_slider, 1, 1)
        sliders.addWidget(self.blur_readout, 1, 2)
        sliders.setColumnStretch(1, 1)
        column.addLayout(sliders)

        self.default_button = QPushButton(t("look.use_for_new"))
        set_icon(self.default_button, "circle-check", size=16)
        self.reset_button = QPushButton(t("look.reset"))
        self.reset_button.setProperty("quiet", True)
        set_icon(self.reset_button, "refresh-cw", size=16)
        column.addWidget(self.default_button)
        column.addWidget(self.reset_button)
        column.addStretch(1)

    @staticmethod
    def _readout() -> QLabel:
        """A slider's value beside it; a number reads left to right in both languages."""
        label = QLabel()
        label.setFixedWidth(_READOUT_WIDTH)
        label.setFont(theme.font("secondary"))
        label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return label

    def _wire(self) -> None:
        for name, button in self.palette_buttons.items():
            button.clicked.connect(lambda _checked=False, n=name: self._choose_preset(n))
        self.customise_toggle.toggled.connect(self._toggle_customise)
        for name, button in self.colour_buttons.items():
            button.clicked.connect(lambda _checked=False, n=name: self._pick_colour(n))
        self.background_colour_button.clicked.connect(self._pick_background_colour)
        self.opacity_slider.valueChanged.connect(
            lambda v: self.opacity_readout.setText(t("look.percent", value=v))
        )
        self.dim_slider.valueChanged.connect(
            lambda v: self.dim_readout.setText(t("look.percent", value=v))
        )
        self.blur_slider.valueChanged.connect(lambda v: self.blur_readout.setText(str(v)))
        for slider, on_value in (
            (self.opacity_slider, self._on_opacity),
            (self.dim_slider, self._on_dim),
            (self.blur_slider, self._on_blur),
        ):
            slider.sliderPressed.connect(self._session.begin_gesture)
            slider.sliderReleased.connect(self._end_gesture)
            slider.valueChanged.connect(on_value)
        for kind, tile in self.background_tiles.items():
            tile.clicked.connect(lambda _checked=False, k=kind: self._choose_background(k))
        self.image_button.clicked.connect(self._choose_image)
        self.default_button.clicked.connect(self._use_for_new_videos)
        self.reset_button.clicked.connect(lambda: self._apply(NIGHT_GOLD))

    def _toggle_customise(self, open_: bool) -> None:
        disclosure.reveal(
            self.customise_box, open_, animate=disclosure.animations_enabled(self._prefs)
        )
        set_icon(self.customise_toggle, "chevron-down" if open_ else "chevron-right", size=16)

    # -- reading the look back --------------------------------------------------

    def refresh(self) -> None:
        """Show the session's look in the controls; emits no ``look_changed``.

        A problem with the look's image is said again through ``notice``
        whenever the look changed (the warnings strip keeps each line once).
        """
        look = self._session.look
        if look == self._shown:
            return
        self._shown = look
        self._show(look)
        self._check(look)

    def announce(self) -> None:
        """Say the current look's image problems again (once the window has connected)."""
        self._check(self._session.look)

    def _show(self, look: Look) -> None:
        # Every chip and tile is drawn at the screen's pixel ratio, so it is sharp on HiDPI.
        ratio = self.devicePixelRatioF()
        current = look.base_preset if look.is_preset else None
        for name, button in self.palette_buttons.items():
            with QSignalBlocker(button):
                button.setChecked(name == current)
        if current is not None:
            self.status_label.setText(_preset_name(current))
        else:
            self.status_label.setText(t("look.custom_from", name=_preset_name(look.base_preset)))
        for name, button in self.colour_buttons.items():
            button.set_colour(getattr(look, name), ratio)
        bg = look.background
        self.background_colour_button.set_colour(bg.colour, ratio)
        self.background_colour_button.setVisible(bg.kind != "image")
        self._set_slider(self.opacity_slider, _alpha_percent(look.card[3]))
        self._set_slider(self.dim_slider, round(bg.dim * 100))
        self._set_slider(self.blur_slider, round(bg.blur))
        # A blocked setValue says nothing, so the readouts are set here as well.
        self.opacity_readout.setText(t("look.percent", value=self.opacity_slider.value()))
        self.dim_readout.setText(t("look.percent", value=self.dim_slider.value()))
        self.blur_readout.setText(str(self.blur_slider.value()))
        self._paint_tiles(look, ratio)
        for kind, tile in self.background_tiles.items():
            with QSignalBlocker(tile):
                tile.setChecked(kind == bg.kind)

    def _paint_tiles(self, look: Look, ratio: float) -> None:
        """Each kind in *look*'s colours at *ratio*; only when those colours (or the preset a
        second colour comes from), the image or the pixel ratio changed."""
        bg = look.background
        image = bg.image if bg.kind == "image" else None
        try:
            stamp = image.stat().st_mtime_ns if image is not None else None
        except OSError:
            stamp = None
        key = (look.base_preset, look.frame_bg, bg.colour, bg.colour2, image, stamp, ratio)
        if key == self._tiles_key:
            return
        self._tiles_key = key
        for kind, tile in self.background_tiles.items():
            if kind == "image":
                background = bg if bg.kind == "image" else None
            else:
                background = _background_for_kind(look, kind)
            pixmap = None
            if background is not None:
                try:
                    drawn = tile_image(
                        background, round(_SWATCH.width() * ratio), round(_SWATCH.height() * ratio)
                    )
                    pixmap = _pil_pixmap(drawn, ratio)
                except (ValueError, OSError):
                    pixmap = None  # a missing or unreadable image: the icon tile below
            if pixmap is None:
                pixmap = _icon_tile(look.frame_bg, "image", ratio)
            tile.setIcon(_two_state_icon(pixmap))

    @staticmethod
    def _set_slider(slider: QSlider, value: int) -> None:
        if slider.isSliderDown():
            return  # the hand on it decides where it is
        with QSignalBlocker(slider):
            slider.setValue(value)

    def _check(self, look: Look) -> None:
        """The readability warning, and the image's problems, for *look*."""
        width, height = self._frame_size
        layer = frame_base_layer(
            look, width, height, reserve_caption_band=self._reserve_caption_band
        )
        names = readability_warnings(look, layer.mean)
        if names:
            separator = "، " if is_rtl() else ", "
            parts = separator.join(_colour_name(name) for name in names)
            self.contrast_label.setText(t("look.low_contrast", parts=parts))
            self._colour_contrast_label()
        self.contrast_label.setVisible(bool(names))
        self.look_notices.emit([look_warning_text(code) for code in layer.warnings])

    def _colour_contrast_label(self) -> None:
        """The warning in the amber that reads on the palette the panel paints on now."""
        colour = warning_color(self.palette()).name()
        self.contrast_label.setStyleSheet(f"color: {colour};")

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        # A theme switch: the amber picked for the old palette may not read on the new one,
        # and the image tile's glyph was drawn in the old theme's secondary colour. (A
        # ring's gold follows the tile it sits on, not the theme: see ``_ring_gold``.)
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self._colour_contrast_label()
            self._tiles_key = None
            self._paint_tiles(self._session.look, self.devicePixelRatioF())

    def event(self, event: QEvent) -> bool:  # noqa: A003 - Qt override
        handled = super().event(event)
        if event.type() == QEvent.Type.DevicePixelRatioChange and hasattr(self, "palette_buttons"):
            # Moved to a screen of another pixel ratio: every chip and tile again, sharp there.
            ratio = self.devicePixelRatioF()
            for name, button in self.palette_buttons.items():
                button.setIcon(_swatch_icon(PRESETS[name], ratio))
            self._show(self._session.look)
        return handled

    # -- changes ----------------------------------------------------------------

    def _apply(self, look: Look) -> None:
        """Give the session *look*; say so only when it changed anything."""
        before = self._session.revision
        self._session.set_look(look)
        self._after_change(before)

    def _after_change(self, before: int) -> None:
        if self._session.revision == before:
            # Nothing changed, but a clicked swatch toggled itself: put it back.
            self._shown = None
            self.refresh()
            return
        self.refresh()
        self.look_changed.emit()

    def _end_gesture(self) -> None:
        """Close a slider's gesture; always said, as undo's state may change even when the look did not."""
        self._session.end_gesture()
        self._shown = None
        self.refresh()
        self.look_changed.emit()

    def _choose_preset(self, name: str) -> None:
        self._apply(PRESETS[name])

    def _pick_colour(self, name: str) -> None:
        look = self._session.look
        self._ask_colour(
            getattr(look, name),
            _colour_name(name),
            lambda start, rgba: replace(start, **{name: rgba}),
            alpha=True,
        )

    def _pick_background_colour(self) -> None:
        """The colour a built-in background is drawn in.

        A solid background is that colour, and the frame's own colour follows
        it. A gradient or a pattern derives its second colour from the new one
        as choosing it in the list does.
        """
        look = self._session.look

        def with_colour(start: Look, rgba: RGBA) -> Look:
            bg = start.background
            if bg.kind == "solid":
                return replace(
                    start, frame_bg=rgba, background=replace(bg, colour=rgba, colour2=rgba)
                )
            colour2 = _second_colour(start, rgba)
            return replace(start, background=replace(bg, colour=rgba, colour2=colour2))

        self._ask_colour(
            look.background.colour, t("look.colour.background"), with_colour, alpha=False
        )

    def _ask_colour(
        self,
        initial: RGBA,
        title: str,
        with_colour: Callable[[Look, RGBA], Look],
        *,
        alpha: bool,
    ) -> None:
        """Ask for a colour, showing each one in the preview while the dialog is open.

        The dialog is one gesture: whatever was tried while it was open, OK is
        one undo step and Cancel leaves no edit at all.
        """
        session = self._session
        start = session.look
        before = session.revision
        dialog = QColorDialog(_qcolor(initial), self)
        dialog.setWindowTitle(plain_title(title))
        dialog.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, alpha)

        def look_with(colour: QColor) -> Look:
            rgba = _rgba(colour)
            return with_colour(start, rgba if alpha else (*rgba[:3], 255))

        def try_colour(colour: QColor) -> None:
            if colour.isValid():
                session.set_look(look_with(colour))
                self.refresh()
                self.look_changed.emit()

        session.begin_gesture()
        try:
            dialog.currentColorChanged.connect(try_colour)
            accepted = bool(dialog.exec())
            dialog.currentColorChanged.disconnect(try_colour)
            chosen = dialog.currentColor()
            session.set_look(look_with(chosen) if accepted and chosen.isValid() else start)
        finally:
            session.end_gesture()
            dialog.deleteLater()
        if session.revision != before:
            self._shown = None
            self.refresh()
            self.look_changed.emit()

    def _on_opacity(self, value: int) -> None:
        look = self._session.look
        alpha = round(value * 255 / 100)
        self._apply(replace(look, card=(*look.card[:3], alpha)))

    def _on_dim(self, value: int) -> None:
        look = self._session.look
        self._apply(replace(look, background=replace(look.background, dim=value / 100)))

    def _on_blur(self, value: int) -> None:
        look = self._session.look
        self._apply(replace(look, background=replace(look.background, blur=float(value))))

    def _choose_background(self, kind: str) -> None:
        if kind == "image":
            if not self._choose_image():
                self._shown = None
                self.refresh()  # the tiles go back to the background the look has
            return
        look = self._session.look
        if kind == look.background.kind:
            # The chosen tile again: keep the look (dim and blur too); Qt's toggle just
            # unchecked the tile, so put it back.
            self._shown = None
            self.refresh()
            return
        self._apply(replace(look, background=_background_for_kind(look, kind)))

    def _choose_image(self) -> bool:
        """Ask for an image, copy it beside the project, and show it; whether it did."""
        project_path = self._session.project.path
        if project_path is None:
            return False
        patterns = " ".join(f"*{suffix}" for suffix in IMAGE_SUFFIXES)
        chosen, _filter = QFileDialog.getOpenFileName(
            self, plain_title(t("look.choose_image")), "", f"{t('look.bg.image')} ({patterns})"
        )
        if not chosen:
            return False
        try:
            copied = import_look_image(project_path, Path(chosen))
        except (ValueError, OSError):
            self.notice.emit(t("look.image_failed", name=Path(chosen).name))
            return False
        look = self._session.look
        background = Background(
            "image",
            look.frame_bg,
            look.frame_bg,
            copied,
            dim=_IMAGE_DIM,
            blur=look.background.blur,
        )
        self._apply(replace(look, background=background))
        return True

    def _use_for_new_videos(self) -> None:
        look = self._session.look
        try:
            self._prefs.save_default_look(look)
        except (ValueError, OSError):
            image = look.background.image
            name = image.name if image is not None else t("look.bg.image")
            self.notice.emit(t("look.image_failed", name=name))
            return
        self.message.emit(t("look.default_saved"))

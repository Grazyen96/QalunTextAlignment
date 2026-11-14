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

LOOK_WARNING_KEYS = {
    "image_missing": "look.image_missing",
    "image_unreadable": "look.image_unreadable",
}

_SWATCH = QSize(56, 36)
_CHIP = QSize(24, 24)
_SWATCH_COLUMNS = 3
_RING = 2
_PALE_RING = "#A47A10"
_READOUT_WIDTH = 44
_IMAGE_DIM = 0.35
_SHADE_STEP = 22


def look_warning_text(code: str) -> str:
    return t(look_warning_key(code))


def look_warning_key(code: str) -> str:
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
    ratio = pixmap.devicePixelRatio()
    at = int(2 * ratio)
    corner = pixmap.toImage().pixelColor(at, at)
    return QColor(_PALE_RING if corner.lightness() >= 128 else theme.DARK.gold)


def _ringed(pixmap: QPixmap) -> QPixmap:
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
    r, g, b, a = colour
    step = _SHADE_STEP if (r * 299 + g * 587 + b * 114) / 1000 < 128 else -_SHADE_STEP
    return (*(max(0, min(255, c + step)) for c in (r, g, b)), a)


def _second_colour(look: Look, colour: RGBA) -> RGBA:
    preset = PRESETS.get(look.base_preset, NIGHT_GOLD).background
    if preset.colour == colour and preset.colour2 != colour:
        return preset.colour2
    return _shade(colour)


def _background_for_kind(look: Look, kind: str) -> Background:
    if kind == "solid":
        return Background("solid", look.frame_bg, look.frame_bg)
    colour = look.background.colour
    colour2 = look.background.colour2
    if colour2 == colour:
        colour2 = _second_colour(look, colour)
    return Background(kind, colour, colour2)


def _pil_pixmap(image, ratio: float = 1.0) -> QPixmap:  # noqa: ANN001 — a PIL image
    rgba = image.convert("RGBA")
    width, height = rgba.size
    qimage = QImage(rgba.tobytes(), width, height, 4 * width, QImage.Format.Format_RGBA8888)
    pixmap = QPixmap.fromImage(qimage.copy())
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def _icon_tile(colour: RGBA, name: str, ratio: float = 1.0) -> QPixmap:
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
        self.hex_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.hex_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        trailing.addWidget(self.hex_label)

    def set_colour(self, colour: RGBA, ratio: float = 1.0) -> None:
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
            event.ignore()
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
    look_changed = Signal()
    notice = Signal(str)
    look_notices = Signal(list)
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
        self._shown: Look | None = None
        self._build()
        self._wire()
        self.refresh()

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
            button.setProperty("swatch", True)
            button.setIcon(_swatch_icon(look, self.devicePixelRatioF()))
            button.setIconSize(_SWATCH)
            button.setText(_preset_name(name))
            button.setToolTip(_preset_name(name))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
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
        self._tiles_key: tuple | None = None

        self.image_button = QPushButton(t("look.choose_image"))
        self.image_button.setProperty("quiet", True)
        set_icon(self.image_button, "image", size=16)
        column.addWidget(self.image_button)
        if self._session.project.path is None:
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

    def refresh(self) -> None:
        look = self._session.look
        if look == self._shown:
            return
        self._shown = look
        self._show(look)
        self._check(look)

    def announce(self) -> None:
        self._check(self._session.look)

    def _show(self, look: Look) -> None:
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
        self.opacity_readout.setText(t("look.percent", value=self.opacity_slider.value()))
        self.dim_readout.setText(t("look.percent", value=self.dim_slider.value()))
        self.blur_readout.setText(str(self.blur_slider.value()))
        self._paint_tiles(look, ratio)
        for kind, tile in self.background_tiles.items():
            with QSignalBlocker(tile):
                tile.setChecked(kind == bg.kind)

    def _paint_tiles(self, look: Look, ratio: float) -> None:
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
                    pixmap = None
            if pixmap is None:
                pixmap = _icon_tile(look.frame_bg, "image", ratio)
            tile.setIcon(_two_state_icon(pixmap))

    @staticmethod
    def _set_slider(slider: QSlider, value: int) -> None:
        if slider.isSliderDown():
            return
        with QSignalBlocker(slider):
            slider.setValue(value)

    def _check(self, look: Look) -> None:
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
        colour = warning_color(self.palette()).name()
        self.contrast_label.setStyleSheet(f"color: {colour};")

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self._colour_contrast_label()
            self._tiles_key = None
            self._paint_tiles(self._session.look, self.devicePixelRatioF())

    def event(self, event: QEvent) -> bool:  # noqa: A003 - Qt override
        handled = super().event(event)
        if event.type() == QEvent.Type.DevicePixelRatioChange and hasattr(self, "palette_buttons"):
            ratio = self.devicePixelRatioF()
            for name, button in self.palette_buttons.items():
                button.setIcon(_swatch_icon(PRESETS[name], ratio))
            self._show(self._session.look)
        return handled

    def _apply(self, look: Look) -> None:
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
                self.refresh()
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

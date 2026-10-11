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
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QRectF, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QStandardItemModel
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
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
from qurantext.gui.colors import warning_color
from qurantext.gui.i18n import is_rtl, plain_title, t
from qurantext.gui.prefs import Prefs
from qurantext.gui.review.session import ReviewSession
from qurantext.jobs.look_assets import import_look_image

__all__ = ["LOOK_WARNING_KEYS", "LookPanel", "look_warning_key", "look_warning_text"]

#: The sentence for each code the renderer reports about a look's image.
LOOK_WARNING_KEYS = {
    "image_missing": "look.image_missing",
    "image_unreadable": "look.image_unreadable",
}

#: The palette swatch, in pixels.
_SWATCH = QSize(48, 28)
#: A colour button's swatch.
_CHIP = QSize(18, 18)
#: Swatches per row; three fit the panel's width with their names under them.
_SWATCH_COLUMNS = 3
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


def _swatch_icon(look: Look) -> QIcon:
    """The preset in miniature: its card on its background, a line of text and a highlight."""
    pixmap = QPixmap(_SWATCH)
    pixmap.fill(_qcolor(look.frame_bg))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_qcolor(look.card))
    painter.drawRoundedRect(QRectF(3, 3, _SWATCH.width() - 6, _SWATCH.height() - 6), 4, 4)
    painter.setBrush(_qcolor(look.body_text))
    painter.drawRoundedRect(QRectF(8, 9, 32, 3), 1.5, 1.5)
    painter.drawRoundedRect(QRectF(8, 16, 12, 3), 1.5, 1.5)
    painter.setBrush(_qcolor(look.highlight_word))
    painter.drawRoundedRect(QRectF(23, 16, 17, 3), 1.5, 1.5)
    painter.end()
    return QIcon(pixmap)


def _chip_icon(colour: RGBA) -> QIcon:
    """A colour as a small square, over a checkerboard so a see-through colour shows as one."""
    pixmap = QPixmap(_CHIP)
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


def _alpha_percent(alpha: int) -> int:
    return round(alpha * 100 / 255)


class LookPanel(QWidget):
    """Palette swatches, Customise, Background, and the default; edits go through the session."""

    #: The panel changed the session's look (the window redraws the preview).
    look_changed = Signal()
    #: A problem to show in the warnings strip, already in the person's words.
    notice = Signal(str)
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

        title = QLabel(t("look.title"))
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        column.addWidget(title)

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
            button.setIcon(_swatch_icon(look))
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
        self.customise_toggle.setArrowType(self._customise_arrow(open_=False))
        column.addWidget(self.customise_toggle)

        self.customise_box = QWidget()
        custom = QVBoxLayout(self.customise_box)
        custom.setContentsMargins(0, 0, 0, 0)
        self.colour_buttons: dict[str, QPushButton] = {}
        for name in EDITABLE_COLOURS:
            button = QPushButton(_colour_name(name))
            button.setIconSize(_CHIP)
            self.colour_buttons[name] = button
            custom.addWidget(button)
            if name == "card":
                self.opacity_label = QLabel(t("look.card_opacity"))
                self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
                self.opacity_slider.setRange(0, 100)
                self.opacity_label.setBuddy(self.opacity_slider)
                custom.addWidget(self.opacity_label)
                custom.addWidget(self.opacity_slider)
        self.customise_box.setVisible(False)
        column.addWidget(self.customise_box)

        self.contrast_label = QLabel()
        self.contrast_label.setWordWrap(True)
        self.contrast_label.setVisible(False)
        column.addWidget(self.contrast_label)

        background_label = QLabel(t("look.background"))
        column.addWidget(background_label)
        self.background_combo = QComboBox()
        for kind in BACKGROUND_KINDS:
            self.background_combo.addItem(_background_name(kind), kind)
        background_label.setBuddy(self.background_combo)
        column.addWidget(self.background_combo)

        self.image_button = QPushButton(t("look.choose_image"))
        column.addWidget(self.image_button)
        if self._session.project.path is None:
            # The image is copied beside the project file; without one there is nowhere.
            self.image_button.setEnabled(False)
            self.image_button.setToolTip(t("session.no_file"))
            model = self.background_combo.model()
            if isinstance(model, QStandardItemModel):
                item = model.item(self.background_combo.findData("image"))
                item.setEnabled(False)
                item.setToolTip(t("session.no_file"))

        self.dim_label = QLabel(t("look.dim"))
        self.dim_slider = QSlider(Qt.Orientation.Horizontal)
        self.dim_slider.setRange(0, round(MAX_DIM * 100))
        self.dim_label.setBuddy(self.dim_slider)
        self.blur_label = QLabel(t("look.blur"))
        self.blur_slider = QSlider(Qt.Orientation.Horizontal)
        self.blur_slider.setRange(0, round(MAX_BLUR))
        self.blur_label.setBuddy(self.blur_slider)
        sliders = QGridLayout()
        sliders.addWidget(self.dim_label, 0, 0)
        sliders.addWidget(self.dim_slider, 0, 1)
        sliders.addWidget(self.blur_label, 1, 0)
        sliders.addWidget(self.blur_slider, 1, 1)
        sliders.setColumnStretch(1, 1)
        column.addLayout(sliders)

        self.default_button = QPushButton(t("look.use_for_new"))
        self.reset_button = QPushButton(t("look.reset"))
        column.addWidget(self.default_button)
        column.addWidget(self.reset_button)
        column.addStretch(1)

    def _wire(self) -> None:
        for name, button in self.palette_buttons.items():
            button.clicked.connect(lambda _checked=False, n=name: self._choose_preset(n))
        self.customise_toggle.toggled.connect(self._toggle_customise)
        for name, button in self.colour_buttons.items():
            button.clicked.connect(lambda _checked=False, n=name: self._pick_colour(n))
        for slider, on_value in (
            (self.opacity_slider, self._on_opacity),
            (self.dim_slider, self._on_dim),
            (self.blur_slider, self._on_blur),
        ):
            slider.sliderPressed.connect(self._session.begin_gesture)
            slider.sliderReleased.connect(self._end_gesture)
            slider.valueChanged.connect(on_value)
        self.background_combo.currentIndexChanged.connect(self._on_background_kind)
        self.image_button.clicked.connect(self._choose_image)
        self.default_button.clicked.connect(self._use_for_new_videos)
        self.reset_button.clicked.connect(lambda: self._apply(NIGHT_GOLD))

    def _customise_arrow(self, *, open_: bool) -> Qt.ArrowType:
        """Down when open; else toward where the line reads on (left in Arabic)."""
        if open_:
            return Qt.ArrowType.DownArrow
        if is_rtl():
            return Qt.ArrowType.LeftArrow
        return Qt.ArrowType.RightArrow

    def _toggle_customise(self, open_: bool) -> None:
        self.customise_box.setVisible(open_)
        self.customise_toggle.setArrowType(self._customise_arrow(open_=open_))

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
        current = look.base_preset if look.is_preset else None
        for name, button in self.palette_buttons.items():
            with QSignalBlocker(button):
                button.setChecked(name == current)
        if current is not None:
            self.status_label.setText(_preset_name(current))
        else:
            self.status_label.setText(t("look.custom_from", name=_preset_name(look.base_preset)))
        for name, button in self.colour_buttons.items():
            button.setIcon(_chip_icon(getattr(look, name)))
        bg = look.background
        self._set_slider(self.opacity_slider, _alpha_percent(look.card[3]))
        self._set_slider(self.dim_slider, round(bg.dim * 100))
        self._set_slider(self.blur_slider, round(bg.blur))
        with QSignalBlocker(self.background_combo):
            self.background_combo.setCurrentIndex(self.background_combo.findData(bg.kind))

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
            colour = warning_color(self.palette()).name()
            self.contrast_label.setStyleSheet(f"color: {colour};")
        self.contrast_label.setVisible(bool(names))
        for code in layer.warnings:
            self.notice.emit(look_warning_text(code))

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
        chosen = QColorDialog.getColor(
            _qcolor(getattr(look, name)),
            self,
            plain_title(_colour_name(name)),
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if not chosen.isValid():
            return
        rgba = (chosen.red(), chosen.green(), chosen.blue(), chosen.alpha())
        self._apply(replace(self._session.look, **{name: rgba}))

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

    def _on_background_kind(self, index: int) -> None:
        kind = self.background_combo.itemData(index)
        if kind == "image":
            if not self._choose_image():
                self._shown = None
                self.refresh()  # the list goes back to the background the look has
            return
        look = self._session.look
        if kind == "solid":
            colour = colour2 = look.frame_bg
        else:
            colour = look.background.colour
            colour2 = look.background.colour2
            if colour2 == colour:
                colour2 = self._second_colour(look, colour)
        background = Background(kind, colour, colour2)
        self._apply(replace(look, background=background))

    @staticmethod
    def _second_colour(look: Look, colour: RGBA) -> RGBA:
        """The preset's own second colour when it has one, else a shade of *colour*."""
        preset = PRESETS.get(look.base_preset, NIGHT_GOLD).background
        if preset.colour == colour and preset.colour2 != colour:
            return preset.colour2
        return _shade(colour)

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

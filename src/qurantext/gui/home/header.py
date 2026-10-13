"""The strip across the top of the home window: who this is, and the three things that are not a job."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from qurantext.config.paths import bundled_asset
from qurantext.gui import theme
from qurantext.gui.i18n import t
from qurantext.gui.icons import set_icon

__all__ = ["HeaderBar"]

_ICON_PX = 24
_HEIGHT = 48


class HeaderBar(QWidget):
    """App icon and name at the leading edge; theme, Settings and Help at the trailing one."""

    theme_toggle_requested = Signal()
    settings_requested = Signal()
    help_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_HEIGHT)
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SP_12, 0, theme.SP_12, 0)
        row.setSpacing(theme.SP_8)

        self.icon_label = QLabel()
        pixmap = QPixmap(str(bundled_asset("icon/qalun-256.png")))
        self.icon_label.setPixmap(
            pixmap.scaled(
                _ICON_PX,
                _ICON_PX,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.icon_label.setFixedSize(QSize(_ICON_PX, _ICON_PX))
        row.addWidget(self.icon_label)

        self.title_label = QLabel("Qalun")  # the product's name, never translated
        self.title_label.setFont(theme.font("title"))
        row.addWidget(self.title_label)
        row.addStretch(1)

        self.theme_button = self._tool("moon", t("home.header.theme_to_dark"))
        self.settings_button = self._tool("settings", t("home.header.settings"))
        self.help_button = self._tool("circle-question-mark", t("home.header.help"))
        for button in (self.theme_button, self.settings_button, self.help_button):
            row.addWidget(button)
        self.theme_button.clicked.connect(self.theme_toggle_requested)
        self.settings_button.clicked.connect(self.settings_requested)
        self.help_button.clicked.connect(self.help_requested)

    @staticmethod
    def _tool(icon_name: str, tip: str) -> QToolButton:
        button = QToolButton()
        button.setAutoRaise(True)
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        set_icon(button, icon_name, size=20)
        return button

    def show_theme(self, tokens_name: str) -> None:
        """Offer the opposite of the theme in force: a sun on dark, a moon on light."""
        dark = tokens_name == "dark"
        set_icon(self.theme_button, "sun" if dark else "moon", size=20)
        tip = t("home.header.theme_to_light" if dark else "home.header.theme_to_dark")
        self.theme_button.setToolTip(tip)
        self.theme_button.setAccessibleName(tip)

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

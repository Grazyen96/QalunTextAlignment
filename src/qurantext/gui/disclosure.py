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

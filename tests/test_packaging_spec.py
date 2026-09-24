"""The PyInstaller spec has to name Qt Multimedia, and must never exclude it.

The review window imports ``PySide6.QtMultimedia`` inside a function, behind a
try. PyInstaller's analysis does follow that import today (Task 3 found every
build since 57fc739 already bundled it), but a release must not depend on it:
without Multimedia the app quietly opens with playback disabled. So the spec
names it, and is read as text here so the rule lives in a test rather than
only in a comment.
"""

from __future__ import annotations

from pathlib import Path

SPEC = Path(__file__).resolve().parents[1] / "packaging" / "qalun.spec"


def test_the_spec_names_qt_multimedia_and_excludes_none_of_it() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert '"PySide6.QtMultimedia"' in text
    excludes = text.split("excludes=[", 1)[1].split("]", 1)[0]
    assert "Multimedia" not in excludes

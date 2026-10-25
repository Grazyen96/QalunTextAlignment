"""The words a user reads before and while using the app: the guide, the README
and the release notes.

They must offer only what the app does and state what a computer needs: a
recitation form has no *Detect automatically*, the macOS build is Apple silicon
only, the Linux build needs glibc 2.38, and neither unsigned build opens on the
first try without the steps that get past the warning.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "USER_GUIDE.md"
README = ROOT / "README.md"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"

#: A line that starts a list item: "- …", "* …" or "3. …".
_LIST_ITEM = re.compile(r"^\s*(?:[-*]|\d+\.)\s")


def _paragraphs(text: str) -> list[str]:
    """Each paragraph, and each list item on its own, with its line breaks folded."""
    pieces: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if not line.strip() or _LIST_ITEM.match(line):
            if current:
                pieces.append(current)
            current = [line] if line.strip() else []
        else:
            current.append(line)
    if current:
        pieces.append(current)
    return [" ".join(" ".join(piece).split()) for piece in pieces]


def _folded(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_the_guide_offers_detect_automatically_for_lectures_only():
    """The recitation form has no *Detect automatically*: a recitation states its
    surah and its first and last ayah. Only a lecture's studied-surah picker has it."""
    offers = [
        p for p in _paragraphs(GUIDE.read_text(encoding="utf-8")) if "Detect automatically" in p
    ]
    assert offers, "the guide no longer explains the lecture's Detect automatically"
    for paragraph in offers:
        assert "Lecture" in paragraph or "lecture" in paragraph, paragraph


def test_the_guide_names_what_each_system_needs():
    guide = _folded(GUIDE)
    for words in ("Apple silicon", "glibc 2.38", "Open Anyway", "Run anyway"):
        assert words in guide, words


def test_the_readme_names_what_each_system_needs():
    readme = _folded(README)
    for words in ("Apple silicon", "glibc 2.38", "Windows 10 or 11"):
        assert words in readme, words


def test_the_release_notes_give_macos_open_anyway_and_the_requirements():
    notes = _folded(RELEASE)
    for words in ("Privacy & Security", "Open Anyway", "Apple silicon", "glibc 2.38"):
        assert words in notes, words


def test_the_guide_does_not_promise_300_mb():
    """The Linux app folder alone is about 490 MB unpacked, before the listening model."""
    assert "300 MB" not in _folded(GUIDE)

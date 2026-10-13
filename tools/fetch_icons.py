"""Download the interface icons from Lucide at a pinned tag, with the licence beside them.

Run once, and again only to change the set or the tag; the files are
committed. Lucide renames icons between versions, so the tag is pinned and
every name below is checked against it.

    venv/bin/python tools/fetch_icons.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

LUCIDE_TAG = "1.56.0"
_RAW = f"https://raw.githubusercontent.com/lucide-icons/lucide/{LUCIDE_TAG}"
ICON_DIR = Path(__file__).resolve().parents[1] / "src" / "qurantext" / "assets" / "icons"
LICENCE_COPY = Path(__file__).resolve().parents[1] / "packaging" / "licenses" / "Lucide-LICENSE.txt"

#: Every icon the windows use. Add here, re-run, and name the new one in
#: ``qurantext.gui.icons.NAMES`` too (its test keeps the two lists equal).
ICON_NAMES: tuple[str, ...] = (
    "play",
    "pause",
    "skip-back",
    "skip-forward",
    "undo-2",
    "redo-2",
    "circle-check",
    "trash",
    "save",
    "download",
    "film",
    "sparkles",
    "palette",
    "image",
    "sun",
    "moon",
    "monitor",
    "refresh-cw",
    "folder-open",
    "folder",
    "x",
    "chevron-right",
    "chevron-down",
    "chevron-left",
    "mic",
    "book-open",
    "pencil",
    "link",
    "qr-code",
    "settings",
    "circle-question-mark",
    "upload",
    "file-music",
    "circle-alert",
    "triangle-alert",
    "zoom-in",
    "zoom-out",
    "crosshair",
    "maximize-2",
    "keyboard",
    "info",
)


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - a pinned GitHub URL
        return response.read()


def main() -> int:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for name in ICON_NAMES:
        data = _fetch(f"{_RAW}/icons/{name}.svg")
        if b'stroke="currentColor"' not in data:
            print(f"{name}: not a stroke icon, cannot be tinted", file=sys.stderr)
            return 1
        (ICON_DIR / f"{name}.svg").write_bytes(data)
    licence = _fetch(f"{_RAW}/LICENSE")
    (ICON_DIR / "LICENSE").write_bytes(licence)
    LICENCE_COPY.parent.mkdir(parents=True, exist_ok=True)
    LICENCE_COPY.write_bytes(licence)
    print(f"{len(ICON_NAMES)} icons from Lucide {LUCIDE_TAG} in {ICON_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

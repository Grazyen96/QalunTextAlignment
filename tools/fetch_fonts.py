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

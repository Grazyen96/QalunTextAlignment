"""Fetch the interface's Arabic fallback font from its pinned release.

Noto Sans Arabic is the face the window falls back to for Arabic letters
on a machine with none of its own. The files are not generated: run this
once to (re)place them. Each file taken from the archive must match its
sha256 in ``SHA256``, the sums THIRD_PARTY_NOTICES.md and the assets README
record; on any mismatch nothing is written and the tool exits 1, printing
the expected and the downloaded sums. Moving to another release means
updating those sums in all three places (tests/test_packaging_spec.py
checks the files against the notice and the README).

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
#: The sha256 of each file as the pinned release ships it.
SHA256 = {
    "NotoSansArabic-Regular.ttf": "bd86ca02f087d7f3c3788ba458fb6b73744c7639ed276b8d870dba6def6c40d0",
    "NotoSansArabic-Bold.ttf": "f4cb79f842a07d1bcf597879574358fb7010f73761396d1d0f2445dfedb4d2ca",
    "NotoSansArabic-OFL.txt": "a7a5a25eb188bf1cd96982030d53e23c33485c69b1044a562254226857ee13af",
}
ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "src" / "qurantext" / "assets" / "fonts"
LICENSES = ROOT / "packaging" / "licenses"


def _download() -> zipfile.ZipFile:
    with urllib.request.urlopen(URL, timeout=120) as response:  # noqa: S310 - a pinned https release
        return zipfile.ZipFile(io.BytesIO(response.read()))


def main() -> int:
    archive = _download()
    taken = {name: archive.read(member) for member, name in FILES.items()}
    wrong = {
        name: hashlib.sha256(data).hexdigest()
        for name, data in taken.items()
        if hashlib.sha256(data).hexdigest() != SHA256[name]
    }
    if wrong:
        print(f"{URL} does not hold the pinned files; nothing was written.", file=sys.stderr)
        for name, digest in wrong.items():
            print(f"  {name}: expected {SHA256[name]}, got {digest}", file=sys.stderr)
        return 1
    FONTS.mkdir(parents=True, exist_ok=True)
    for name, data in taken.items():
        target = FONTS / name
        target.write_bytes(data)
        print(f"{SHA256[name]}  {target.relative_to(ROOT)}")
    shutil.copyfile(FONTS / "NotoSansArabic-OFL.txt", LICENSES / "NotoSansArabic-OFL.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())

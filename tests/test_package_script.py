"""The release zip for Linux has to keep the bundle's symlinks as symlinks.

PyInstaller links the Qt and FFmpeg libraries into ``_internal/``; a zip that
follows those links stores each library twice and the app unpacks to 446 MB
instead of 275 MB. ``packaging/ci/package.sh`` is what the release workflow
runs to make the zip, so it is run here on a tiny stand-in bundle.
"""

from __future__ import annotations

import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "ci" / "package.sh"

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or shutil.which("zip") is None,
    reason="the symlink-keeping zip is the Linux path and needs the zip tool",
)


def test_the_linux_zip_stores_links_as_links_under_a_qalun_folder(tmp_path: Path) -> None:
    lib = tmp_path / "dist" / "qalun" / "_internal" / "PySide6" / "Qt" / "lib"
    lib.mkdir(parents=True)
    (lib / "libQt6Core.so.6").write_bytes(b"\0" * 4096)
    (tmp_path / "dist" / "qalun" / "_internal" / "libQt6Core.so.6").symlink_to(
        "PySide6/Qt/lib/libQt6Core.so.6"
    )

    subprocess.run(["bash", str(SCRIPT), "qalun-linux"], cwd=tmp_path, check=True)

    with zipfile.ZipFile(tmp_path / "out" / "qalun-linux.zip") as archive:
        names = archive.namelist()
        link = archive.getinfo("qalun/_internal/libQt6Core.so.6")
        target = archive.read(link)
    assert all(name.startswith("qalun/") for name in names)
    assert stat.S_ISLNK(link.external_attr >> 16)
    assert target == b"PySide6/Qt/lib/libQt6Core.so.6"


def test_it_refuses_when_there_is_nothing_to_zip(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "qalun-linux"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "run the build first" in result.stderr
    assert not (tmp_path / "out").exists()

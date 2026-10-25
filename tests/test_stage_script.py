"""``packaging/ci/stage.sh``, which copies FFmpeg and FriBiDi in beside the built app.

On macOS PyInstaller ad-hoc signs ``Qalun.app`` before staging, and every file
added under ``Contents/MacOS`` afterwards lies outside the bundle's seal: a
strict ``codesign --verify`` reports it as added, and a downloaded app may be
called damaged. So the script signs the bundle again once the copy is done. There
is no Mac here, so a stand-in ``codesign`` on PATH records how it is called.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "ci" / "stage.sh"

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="the stand-in codesign is a shell script"
)


def _stage(tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run stage.sh in *tmp_path* with a stand-in FFmpeg in vendor/ and a codesign
    that logs its arguments, and on the next line whether FFmpeg was already staged."""
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "ffmpeg").write_bytes(b"ffmpeg")
    tools = tmp_path / "tools"
    tools.mkdir()
    log = tmp_path / "codesign-calls"
    codesign = tools / "codesign"
    codesign.write_text(
        f'#!/bin/sh\necho "$*" >> {log}\n'
        f"if [ -e dist/Qalun.app/Contents/MacOS/ffmpeg ]; then echo staged >> {log};"
        f" else echo not-staged >> {log}; fi\n",
        encoding="utf-8",
    )
    codesign.chmod(0o755)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{tools}:{os.environ.get('PATH', '')}"},
        timeout=60,
    )
    return result, log


def test_a_mac_build_is_signed_again_after_staging(tmp_path: Path) -> None:
    macos = tmp_path / "dist" / "Qalun.app" / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (macos / "qalun").write_bytes(b"app")
    result, log = _stage(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (macos / "ffmpeg").exists()
    assert log.read_text(encoding="utf-8").splitlines() == [
        "--force --deep --sign - dist/Qalun.app",
        "staged",
    ]


def test_a_linux_build_is_not_signed(tmp_path: Path) -> None:
    bundle = tmp_path / "dist" / "qalun"
    bundle.mkdir(parents=True)
    (bundle / "qalun").write_bytes(b"app")
    result, log = _stage(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (bundle / "ffmpeg").exists()
    assert not log.exists()

"""The CI gate, ``packaging/ci/check.sh``, run on stand-in bundles.

It is the one thing between a broken build and a release, so it must fail
loudly in minutes, not hang the job for its six hours, and on Linux it must
catch the library the window needs on X11 that the doctor itself cannot see.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "ci" / "check.sh"

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="the stand-in bundle is the Linux layout"
)


def _bundle(tmp_path: Path, body: str, *, xcb_cursor: bool = True) -> None:
    """A dist/qalun whose "app" runs *body* under /bin/sh (with no PATH, so absolute)."""
    app = tmp_path / "dist" / "qalun" / "qalun"
    internal = tmp_path / "dist" / "qalun" / "_internal"
    internal.mkdir(parents=True)
    app.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    app.chmod(0o755)
    if xcb_cursor:
        (internal / "lib").mkdir()
        (internal / "lib" / "libxcb-cursor.so.0").write_bytes(b"\0")


def _gate(tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "QALUN_GATE_TIMEOUT_S": "2", **env},
        timeout=60,
    )


def test_a_bundle_that_reports_ready_passes(tmp_path: Path) -> None:
    _bundle(tmp_path, 'echo "Ready to render."')
    result = _gate(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Ready to render." in result.stdout


def test_the_app_is_run_as_the_release_gate_with_no_path(tmp_path: Path) -> None:
    _bundle(tmp_path, 'echo "args: $*"; echo "path: $PATH"')
    result = _gate(tmp_path)
    assert "args: --doctor --release" in result.stdout
    assert "path: /nonexistent" in result.stdout


def test_a_doctor_that_finds_a_problem_fails_the_gate(tmp_path: Path) -> None:
    _bundle(tmp_path, "exit 1")
    result = _gate(tmp_path)
    assert result.returncode == 1
    assert "reported a problem (exit code 1" in result.stderr


def test_a_hung_doctor_fails_the_gate_within_its_bound(tmp_path: Path) -> None:
    _bundle(tmp_path, f"exec {shutil.which('sleep')} 30")
    started = time.monotonic()
    result = _gate(tmp_path)
    assert time.monotonic() - started < 15
    assert result.returncode == 1
    assert "did not finish within 2 s" in result.stderr


def test_without_timeout_the_bound_is_kept_through_perl(tmp_path: Path) -> None:
    """What macOS runs: it has no timeout(1)."""
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("bash", "perl", "find", "uname"):
        (tools / name).symlink_to(shutil.which(name))
    _bundle(tmp_path, f"exec {shutil.which('sleep')} 30")
    started = time.monotonic()
    result = _gate(tmp_path, PATH=str(tools))
    assert time.monotonic() - started < 15
    assert result.returncode == 1
    assert "did not finish within 2 s" in result.stderr


def test_a_linux_bundle_without_libxcb_cursor_fails_the_gate(tmp_path: Path) -> None:
    """The doctor draws offscreen, so only the bundle itself shows the X11 window
    would not open."""
    _bundle(tmp_path, 'echo "Ready to render."', xcb_cursor=False)
    result = _gate(tmp_path)
    assert result.returncode == 1
    assert "libxcb-cursor.so.0" in result.stderr

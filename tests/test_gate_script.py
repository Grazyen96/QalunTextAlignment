"""The CI gate, ``packaging/ci/check.sh``, run on stand-in bundles.

It is the one thing between a broken build and a release, so it must fail
loudly in minutes, not hang the job for its six hours, and on Linux it must
catch the library the window needs on X11 that the doctor itself cannot see.
Once the doctor passes it hands over to ``check-transcription.sh``, which runs
a real local transcription inside the app.
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


#: What the stand-in app does when asked to transcribe: write a transcript with
#: segments to the path after --output, using only shell builtins (PATH is stripped).
WRITES_A_TRANSCRIPT = """
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output" ]; then out="$2"; fi
  shift
done
echo '{"segments": [{"start": 0.0, "end": 1.0, "text": ""}]}' > "$out"
"""


def _bundle(
    tmp_path: Path,
    body: str,
    *,
    xcb_cursor: bool = True,
    transcribe: str = WRITES_A_TRANSCRIPT,
) -> None:
    """A dist/qalun whose "app" runs *body* under /bin/sh (with no PATH, so absolute)
    for the doctor, and *transcribe* for ``--cli``; with a stand-in FFmpeg beside
    it that only creates the file it is asked for."""
    app = tmp_path / "dist" / "qalun" / "qalun"
    internal = tmp_path / "dist" / "qalun" / "_internal"
    internal.mkdir(parents=True)
    app.write_text(
        f'#!/bin/sh\nif [ "$1" = "--cli" ]; then\n{transcribe}\nexit\nfi\n{body}\n',
        encoding="utf-8",
    )
    app.chmod(0o755)
    ffmpeg = tmp_path / "dist" / "qalun" / "ffmpeg"
    ffmpeg.write_text('#!/bin/sh\nfor last; do :; done\n: > "$last"\n', encoding="utf-8")
    ffmpeg.chmod(0o755)
    if xcb_cursor:
        (internal / "lib").mkdir()
        (internal / "lib" / "libxcb-cursor.so.0").write_bytes(b"\0")


def _gate(tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    inherited = {
        k: v
        for k, v in os.environ.items()
        if k not in ("QURANTEXT_CACHE_DIR", "GITHUB_ACTIONS", "QURANTEXT_TRANSCRIBE_ENGINE")
    }
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={
            **inherited,
            "QALUN_GATE_TIMEOUT_S": "2",
            "QALUN_TRANSCRIPTION_GATE_TIMEOUT_S": "2",
            **env,
        },
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


def test_the_doctor_checks_the_local_engine_whatever_the_machine_chose(tmp_path: Path) -> None:
    """The local engine is what a person gets by default, so its runtime must block."""
    _bundle(tmp_path, 'echo "engine: $QURANTEXT_TRANSCRIBE_ENGINE"')
    result = _gate(tmp_path, QURANTEXT_TRANSCRIBE_ENGINE="whisperx")
    assert "engine: local" in result.stdout


def test_after_the_doctor_passes_the_app_transcribes_a_tone_locally(tmp_path: Path) -> None:
    _bundle(
        tmp_path,
        'echo "Ready to render."',
        transcribe='echo "args: $*"; echo "path: $PATH"; echo "engine: $QURANTEXT_TRANSCRIBE_ENGINE"'
        + WRITES_A_TRANSCRIPT,
    )
    result = _gate(tmp_path)
    assert result.returncode == 0, result.stderr
    work = "build/transcription-gate"
    assert (
        f"args: --cli transcribe --engine local --no-cache --audio {work}/tone.wav"
        f" --output {work}/tone.json"
    ) in result.stdout
    assert "path: /nonexistent" in result.stdout
    assert "engine: local" in result.stdout
    assert (tmp_path / work / "tone.wav").exists()
    assert "1 segment(s) for a 5 s tone" in result.stdout


def test_a_doctor_that_fails_never_downloads_the_model(tmp_path: Path) -> None:
    """A build that will not ship must not add to the model's download count."""
    marker = tmp_path / "transcribed"
    _bundle(tmp_path, "exit 1", transcribe=f": > {marker}")
    result = _gate(tmp_path)
    assert result.returncode == 1
    assert not marker.exists()


def test_a_transcription_that_fails_fails_the_gate(tmp_path: Path) -> None:
    _bundle(tmp_path, 'echo "Ready to render."', transcribe="exit 3")
    result = _gate(tmp_path)
    assert result.returncode == 3
    assert "could not transcribe (exit code 3" in result.stderr
    assert "qalun-models" in result.stderr


def test_a_transcript_without_segments_fails_the_gate(tmp_path: Path) -> None:
    transcribe = WRITES_A_TRANSCRIPT.replace('{"segments": [{', '{"text": [{')
    _bundle(tmp_path, 'echo "Ready to render."', transcribe=transcribe)
    result = _gate(tmp_path)
    assert result.returncode == 1
    assert 'no "segments" list' in result.stderr
    assert "its transcript is not valid" in result.stderr


def test_a_hung_transcription_fails_the_gate_within_its_bound(tmp_path: Path) -> None:
    _bundle(tmp_path, 'echo "Ready to render."', transcribe=f"exec {shutil.which('sleep')} 30")
    started = time.monotonic()
    result = _gate(tmp_path)
    assert time.monotonic() - started < 15
    assert result.returncode == 1
    assert "did not finish within 2 s" in result.stderr


def test_on_github_actions_the_model_goes_to_the_folder_the_workflow_caches(
    tmp_path: Path,
) -> None:
    _bundle(
        tmp_path,
        'echo "Ready to render."',
        transcribe='echo "cache: $QURANTEXT_CACHE_DIR"' + WRITES_A_TRANSCRIPT,
    )
    result = _gate(tmp_path, GITHUB_ACTIONS="true")
    assert result.returncode == 0, result.stderr
    assert f"cache: {tmp_path}/.ci-cache/qalun\n" in result.stdout


def test_a_cache_folder_that_is_set_is_the_one_used(tmp_path: Path) -> None:
    _bundle(
        tmp_path,
        'echo "Ready to render."',
        transcribe='echo "cache: $QURANTEXT_CACHE_DIR"' + WRITES_A_TRANSCRIPT,
    )
    chosen = tmp_path / "elsewhere"
    result = _gate(tmp_path, GITHUB_ACTIONS="true", QURANTEXT_CACHE_DIR=str(chosen))
    assert result.returncode == 0, result.stderr
    assert f"cache: {chosen}\n" in result.stdout


def test_the_workflow_caches_that_folder_under_the_pinned_models_checksum() -> None:
    """The cache step lives in release.yml and the model's checksum in code. A new
    model must change the key, or the old cache is restored for ever and every
    build downloads the new model again."""
    from qurantext.services.model_store import LOCAL_MODEL

    workflow = (SCRIPT.parents[2] / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    step = workflow.split("uses: actions/cache@", 1)[1].split("\n\n", 1)[0]
    assert "path: .ci-cache/qalun/models" in step
    assert LOCAL_MODEL.archive_sha256 in step

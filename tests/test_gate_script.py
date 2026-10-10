"""The CI gate, ``packaging/ci/check.sh``, run on stand-in bundles.

It is the one thing between a broken build and a release, so it must fail
loudly in minutes, not hang the job for its six hours, and on Linux it must
catch the library the window needs on X11 that the doctor itself cannot see.
Once the doctor passes it hands over to ``check-transcription.sh``, which runs
a real local transcription inside the app.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "ci" / "check.sh"
TRANSCRIPTION_SCRIPT = SCRIPT.parent / "check-transcription.sh"

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


def _published(**changes: object) -> dict[str, object]:
    """What GitHub's API says about the pinned release, as model_store.py pins it,
    with *changes* applied to the model's asset (a value of None drops the key)."""
    from qurantext.services.model_store import LOCAL_MODEL

    asset: dict[str, object] = {
        "name": LOCAL_MODEL.url.rsplit("/", 1)[1],
        "size": LOCAL_MODEL.archive_size,
        "digest": f"sha256:{LOCAL_MODEL.archive_sha256}",
        "state": "uploaded",
    }
    for key, value in changes.items():
        if value is None:
            asset.pop(key, None)
        else:
            asset[key] = value
    other = {"name": "something-else.tar.bz2", "size": 1, "digest": "sha256:00"}
    return {"tag_name": "model-v1", "assets": [other, asset]}


def _fake_curl(tmp_path: Path, release: dict[str, object] | None, status: int = 200) -> Path:
    """A folder holding a curl that answers with *release* and HTTP *status* (or
    cannot connect, for None) and records the URL it was asked for, using only bash
    builtins, so no test reaches the network."""
    tools = tmp_path / "fake-curl"
    tools.mkdir(exist_ok=True)
    answer = tmp_path / "release-answer.json"
    calls = tmp_path / "curl-calls"
    if release is not None:
        answer.write_text(json.dumps(release), encoding="utf-8")
    curl = tools / "curl"
    curl.write_text(
        f"""#!{shutil.which("bash")}
out=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift ;;
    -w) shift ;;
    -H) echo "header: $2" >> {calls}; shift ;;
    *) url="$1" ;;
  esac
  shift
done
echo "url: $url" >> {calls}
if [ ! -f {answer} ]; then printf 000; exit 7; fi
printf '%s' "$(<{answer})" > "$out"
printf {status}
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return tools


def _gate(
    tmp_path: Path,
    *,
    release: dict[str, object] | None = None,
    api_fails: bool = False,
    api_status: int = 200,
    script: Path = SCRIPT,
    **env: str,
) -> subprocess.CompletedProcess[str]:
    inherited = {
        k: v
        for k, v in os.environ.items()
        if k
        not in (
            "QURANTEXT_CACHE_DIR",
            "GITHUB_ACTIONS",
            "QURANTEXT_TRANSCRIBE_ENGINE",
            "GITHUB_TOKEN",
            "GH_TOKEN",
        )
    }
    curl = _fake_curl(tmp_path, None if api_fails else (release or _published()), api_status)
    path = env.pop("PATH", inherited.get("PATH", ""))
    return subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={
            **inherited,
            # Where the app's model folder is when QURANTEXT_CACHE_DIR is not set.
            "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
            "QALUN_GATE_TIMEOUT_S": "2",
            "QALUN_TRANSCRIPTION_GATE_TIMEOUT_S": "2",
            **env,
            "PATH": f"{curl}:{path}",
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


# --- The published model, checked against the pin on every run (cache or not) ---


def _transcription_gate(tmp_path: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
    """check-transcription.sh on its own, with a marker the stand-in app leaves
    when it is asked to transcribe."""
    _bundle(
        tmp_path,
        'echo "Ready to render."',
        transcribe=f": > {tmp_path / 'transcribed'}" + WRITES_A_TRANSCRIPT,
    )
    return _gate(tmp_path, script=TRANSCRIPTION_SCRIPT, **kwargs)  # type: ignore[arg-type]


def test_the_published_model_is_checked_against_the_pin_in_model_store(tmp_path: Path) -> None:
    from qurantext.services.model_store import LOCAL_MODEL

    result = _transcription_gate(tmp_path)
    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "curl-calls").read_text(encoding="utf-8")
    assert "url: https://api.github.com/repos/Grazyen96/qalun-models/releases/tags/model-v1\n" in (
        calls
    )
    assert "Authorization" not in calls
    assert f"{LOCAL_MODEL.archive_size} bytes, sha256 {LOCAL_MODEL.archive_sha256}" in result.stdout
    assert (tmp_path / "transcribed").exists()


def test_the_script_does_not_write_the_pin_down_a_second_time() -> None:
    """model_store.py is the one place the pin lives; the gate reads it from there."""
    from qurantext.services.model_store import LOCAL_MODEL

    text = TRANSCRIPTION_SCRIPT.read_text(encoding="utf-8")
    assert LOCAL_MODEL.archive_sha256 not in text
    assert str(LOCAL_MODEL.archive_size) not in text
    assert LOCAL_MODEL.url.rsplit("/", 1)[1] not in text
    assert "from qurantext.services.model_store import LOCAL_MODEL" in text


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"size": 108151681}, "the pin says 108151682"),
        ({"digest": "sha256:" + "0" * 64}, "has digest sha256:000"),
        ({"name": "renamed.tar.bz2"}, "has no asset named"),
    ],
)
def test_a_published_model_that_no_longer_matches_fails_before_any_download(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    result = _transcription_gate(tmp_path, release=_published(**changes))
    assert result.returncode == 1
    assert message in result.stderr
    assert "no longer matches model_store.py" in result.stderr
    assert not (tmp_path / "transcribed").exists()


def test_without_a_digest_from_github_the_size_is_still_checked(tmp_path: Path) -> None:
    result = _transcription_gate(tmp_path, release=_published(digest=None))
    assert result.returncode == 0, result.stderr
    assert "matches the pin by size" in result.stdout
    result = _transcription_gate(tmp_path / "again", release=_published(digest=None, size=5))
    assert result.returncode == 1


def test_a_release_that_cannot_be_read_fails_the_gate(tmp_path: Path) -> None:
    result = _transcription_gate(tmp_path, api_fails=True)
    assert result.returncode == 1
    assert "could not read release model-v1" in result.stderr
    assert "(HTTP 000)" in result.stderr and "could not be reached" in result.stderr
    assert not (tmp_path / "transcribed").exists()


@pytest.mark.parametrize(
    ("status", "cause"),
    [
        (403, "usually its API rate limit"),
        (429, "usually its API rate limit"),
        (404, "gone, renamed or private"),
        (500, "(HTTP 500)"),
    ],
)
def test_a_refused_call_names_its_cause(tmp_path: Path, status: int, cause: str) -> None:
    """A rate limit (403/429) is not a missing release (404): the message says which,
    so nobody goes looking for a deleted model when GitHub only throttled the call."""
    result = _transcription_gate(tmp_path, api_status=status)
    assert result.returncode == 1
    assert "could not read release model-v1 from" in result.stderr
    assert cause in result.stderr
    assert ("rate limit" in result.stderr) == (status in (403, 429))
    assert not (tmp_path / "transcribed").exists()


def test_the_workflow_gives_both_gate_steps_its_token() -> None:
    """Anonymous calls share 60 an hour with every job on the runner's address."""
    workflow = (SCRIPT.parents[2] / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    steps = workflow.split("- name: Check the built app can render")[1:]
    assert len(steps) == 2
    for step in steps:
        step = step.split("\n      - ", 1)[0]
        assert "GITHUB_TOKEN: ${{ github.token }}" in step


def test_a_github_token_is_used_when_there_is_one_and_never_printed(tmp_path: Path) -> None:
    result = _transcription_gate(tmp_path, GITHUB_TOKEN="secret-token-value")
    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "curl-calls").read_text(encoding="utf-8")
    assert "header: Authorization: Bearer secret-token-value" in calls
    assert "secret-token-value" not in result.stdout + result.stderr


def test_a_cache_miss_leaves_one_greppable_line_and_a_hit_none(tmp_path: Path) -> None:
    """CI's share of the asset's download count, countable from the Actions logs."""
    from qurantext.services.model_store import LOCAL_MODEL

    cache = tmp_path / "cache"
    miss = _transcription_gate(tmp_path / "miss", QURANTEXT_CACHE_DIR=str(cache))
    assert miss.returncode == 0, miss.stderr
    lines = [
        line for line in miss.stdout.splitlines() if line.startswith("QALUN-CI-MODEL-DOWNLOAD ")
    ]
    assert lines == [
        f"QALUN-CI-MODEL-DOWNLOAD model-v1 {LOCAL_MODEL.url.rsplit('/', 1)[1]}:"
        " not in the cache, so this run downloads it once."
    ]
    (cache / "models" / LOCAL_MODEL.folder_name).mkdir(parents=True)
    hit = _transcription_gate(tmp_path / "hit", QURANTEXT_CACHE_DIR=str(cache))
    assert hit.returncode == 0, hit.stderr
    assert "QALUN-CI-MODEL-DOWNLOAD" not in hit.stdout
    assert "already in the cache" in hit.stdout


# --- The transcription's own bound on macOS (perl) and Windows (timeout.exe) ---


def _tools_without_timeout(tmp_path: Path) -> Path:
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("bash", "perl", "uname", "dirname", "mkdir", "rm", "tr"):
        (tools / name).symlink_to(shutil.which(name))
    (tools / "python3").symlink_to(shutil.which("python3") or sys.executable)
    return tools


def test_a_hung_transcription_is_bounded_through_perl_without_timeout(tmp_path: Path) -> None:
    """What macOS runs: it has no timeout(1)."""
    tools = _tools_without_timeout(tmp_path)
    _bundle(tmp_path, 'echo "Ready to render."', transcribe=f"exec {shutil.which('sleep')} 30")
    started = time.monotonic()
    result = _gate(tmp_path, script=TRANSCRIPTION_SCRIPT, PATH=str(tools))
    assert time.monotonic() - started < 15
    assert result.returncode == 1, result.stderr
    assert "did not finish within 2 s" in result.stderr


def test_a_timeout_that_does_not_answer_version_is_passed_over_for_perl(tmp_path: Path) -> None:
    """Windows' own timeout.exe only waits: it must not be taken for GNU's."""
    fake = tmp_path / "windows-timeout"
    fake.mkdir()
    (fake / "timeout").write_text(
        '#!/bin/sh\nif [ "$1" = "--version" ]; then exit 1; fi\nexit 99\n', encoding="utf-8"
    )
    (fake / "timeout").chmod(0o755)
    _bundle(tmp_path, 'echo "Ready to render."', transcribe=f"exec {shutil.which('sleep')} 30")
    started = time.monotonic()
    result = _gate(
        tmp_path, script=TRANSCRIPTION_SCRIPT, PATH=f"{fake}:{os.environ.get('PATH', '')}"
    )
    assert time.monotonic() - started < 15
    assert result.returncode == 1, result.stderr
    assert "did not finish within 2 s" in result.stderr

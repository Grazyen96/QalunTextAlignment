"""The release zip for Linux has to keep the bundle's symlinks as symlinks.

PyInstaller links the Qt and FFmpeg libraries into ``_internal/``; a zip that
follows those links stores each library twice and the app unpacks to 446 MB
instead of 275 MB. ``packaging/ci/package.sh`` is what the release workflow
runs to make the zip, so it is run here on a tiny stand-in bundle.

The same script, on Linux, writes the source archive each release carries (Qalun
is GPL-3.0-only), so it is run inside a tiny git checkout.
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
    not sys.platform.startswith("linux") or not (shutil.which("zip") and shutil.which("git")),
    reason="the symlink-keeping zip is the Linux path and needs zip, and git for the source",
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _checkout(tmp_path: Path) -> Path:
    """A tiny git checkout carrying the real package.sh, its notice and LICENSE.

    The script archives the checkout it sits in, so it runs from a copy here: run
    from this repository it would archive whatever this repository's HEAD is, and
    fail in a copy unpacked from a source archive, which is no git checkout.
    """
    repo = tmp_path / "repo"
    (repo / "packaging" / "ci").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "packaging" / "ci" / "package.sh")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy(SCRIPT.parents[2] / name, repo / name)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('qalun')\n", encoding="utf-8")
    (repo / ".gitignore").write_text("dist/\nout/\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _package(repo: Path) -> None:
    script = repo / "packaging" / "ci" / "package.sh"
    subprocess.run(["bash", str(script), "qalun-linux"], cwd=repo, check=True)


def _checkout_with_a_build(tmp_path: Path) -> Path:
    """The checkout with a built app in dist/ and an uncommitted file beside it."""
    repo = _checkout(tmp_path)
    (repo / "dist" / "qalun" / "_internal").mkdir(parents=True)
    (repo / "dist" / "qalun" / "qalun").write_bytes(b"\0")
    (repo / "notes.txt").write_text("not committed\n", encoding="utf-8")
    return repo


def _without_github_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GITHUB_REF_TYPE", "GITHUB_REF_NAME"):
        monkeypatch.delenv(name, raising=False)


def test_the_linux_zip_stores_links_as_links_under_a_qalun_folder(tmp_path: Path) -> None:
    repo = _checkout(tmp_path)
    lib = repo / "dist" / "qalun" / "_internal" / "PySide6" / "Qt" / "lib"
    lib.mkdir(parents=True)
    (lib / "libQt6Core.so.6").write_bytes(b"\0" * 4096)
    (repo / "dist" / "qalun" / "_internal" / "libQt6Core.so.6").symlink_to(
        "PySide6/Qt/lib/libQt6Core.so.6"
    )

    _package(repo)

    with zipfile.ZipFile(repo / "out" / "qalun-linux.zip") as archive:
        names = archive.namelist()
        link = archive.getinfo("qalun/_internal/libQt6Core.so.6")
        target = archive.read(link)
    assert all(name.startswith("qalun/") for name in names)
    assert stat.S_ISLNK(link.external_attr >> 16)
    assert target == b"PySide6/Qt/lib/libQt6Core.so.6"


def test_the_notice_and_the_licence_sit_beside_the_executable(tmp_path: Path) -> None:
    """Someone who unzips the app sees the credits the model's licence asks for, and
    the GPL-3.0 that Qalun is under."""
    repo = _checkout_with_a_build(tmp_path)

    _package(repo)

    root = SCRIPT.parents[2]
    with zipfile.ZipFile(repo / "out" / "qalun-linux.zip") as archive:
        notices = archive.read("qalun/THIRD_PARTY_NOTICES.md")
        licence = archive.read("qalun/LICENSE")
    assert notices == (root / "THIRD_PARTY_NOTICES.md").read_bytes()
    assert licence == (root / "LICENSE").read_bytes()


def test_it_refuses_when_there_is_nothing_to_zip(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "qalun-linux"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "run the build first" in result.stderr
    assert not (tmp_path / "out").exists()


def test_the_linux_package_writes_the_source_archive_beside_the_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Qalun is GPL-3.0-only, so each release carries the complete source of the
    commit it was built from. The release attaches every zip in out/, so the Linux
    job (the one job that runs this branch) writes it there."""
    _without_github_ref(monkeypatch)
    repo = _checkout_with_a_build(tmp_path)
    commit = _git(repo, "rev-parse", "--short=12", "HEAD")

    _package(repo)

    source = repo / "out" / f"qalun-source-{commit}.zip"
    with zipfile.ZipFile(source) as archive:
        names = set(archive.namelist())
        assert archive.read("qalun-source/LICENSE") == (repo / "LICENSE").read_bytes()
    assert all(name.startswith("qalun-source/") for name in names)
    assert {
        "qalun-source/packaging/ci/package.sh",
        "qalun-source/src/app.py",
        "qalun-source/THIRD_PARTY_NOTICES.md",
    } <= names
    # The committed tree only: neither the build nor anything uncommitted.
    assert not any(name.startswith("qalun-source/dist/") for name in names)
    assert "qalun-source/notes.txt" not in names
    assert (repo / "out" / "qalun-linux.zip").exists()


def test_a_tagged_build_names_the_source_archive_after_its_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _checkout_with_a_build(tmp_path)
    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_REF_NAME", "v0.2.0")

    _package(repo)

    assert (repo / "out" / "qalun-source-v0.2.0.zip").exists()


def test_the_source_archive_cannot_be_skipped_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outside a git checkout there is no tagged commit to archive; the Linux
    package step fails rather than ship a release without its source."""
    _without_github_ref(monkeypatch)
    root = tmp_path / "plain"
    (root / "packaging" / "ci").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "packaging" / "ci" / "package.sh")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy(SCRIPT.parents[2] / name, root / name)
    (root / "dist" / "qalun" / "_internal").mkdir(parents=True)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))

    result = subprocess.run(
        ["bash", str(root / "packaging" / "ci" / "package.sh"), "qalun-linux"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "source archive" in result.stderr

"""The release zip for Linux has to keep the bundle's symlinks as symlinks.

PyInstaller links the Qt and FFmpeg libraries into ``_internal/``; a zip that
follows those links stores each library twice and the app unpacks to 446 MB
instead of 275 MB. ``packaging/ci/package.sh`` is what the release workflow
runs to make the zip, so it is run here on a tiny stand-in bundle.

The same script puts in every app zip what a GPL-3.0-only release must carry
with it: Qalun's own source (``qalun-source.zip``, ``git archive`` of the commit
built) and the corresponding sources of the GPL and LGPL code the bundle contains
(``third-party-sources/``, pinned by URL and sha256). So it runs inside a tiny git
checkout, whose pin list points at local files, so no test reaches the network.
"""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "ci" / "package.sh"
PINS = ROOT / "packaging" / "third-party-sources.txt"

on_linux_with_zip_and_git = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not (shutil.which("zip") and shutil.which("git")),
    reason="the symlink-keeping zip is the Linux path and needs zip, and git for the source",
)


@pytest.fixture(autouse=True)
def _no_github_ref_and_a_private_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GITHUB_REF_TYPE", "GITHUB_REF_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("QALUN_SOURCES_CACHE", str(tmp_path / "sources-cache"))


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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _upstream(tmp_path: Path) -> dict[str, bytes]:
    """Stand-in source archives, one per platform column, served as file:// URLs."""
    sources = {
        "espeak-ng-fake.zip": b"espeak-ng source",
        "alsa-lib-fake.tar.bz2": b"alsa-lib source",
        "macos-only.tar.gz": b"not for linux",
    }
    upstream = tmp_path / "upstream"
    upstream.mkdir(exist_ok=True)
    for name, data in sources.items():
        (upstream / name).write_bytes(data)
    return sources


def _write_pins(repo: Path, tmp_path: Path, *, wrong: str | None = None) -> None:
    """The checkout's pin list: *wrong* names a file pinned to another sha256."""
    sources = _upstream(tmp_path)
    platforms = {
        "espeak-ng-fake.zip": "all",
        "alsa-lib-fake.tar.bz2": "linux",
        "macos-only.tar.gz": "macos",
    }
    lines = ["# platform  file  sha256  url", ""]
    for name, data in sources.items():
        sha = "0" * 64 if name == wrong else _sha256(data)
        url = (tmp_path / "upstream" / name).as_uri()
        lines.append(f"{platforms[name]}\t{name}\t{sha}\t{url}")
    (repo / "packaging" / "third-party-sources.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _checkout(tmp_path: Path, *, version: str = "0.2.0") -> Path:
    """A tiny git checkout carrying the real package.sh, its notice and LICENSE.

    The script archives the checkout it sits in, so it runs from a copy here: run
    from this repository it would archive whatever this repository's HEAD is, and
    fail in a copy unpacked from a source archive, which is no git checkout.
    """
    repo = tmp_path / "repo"
    (repo / "packaging" / "ci").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "packaging" / "ci" / "package.sh")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy(ROOT / name, repo / name)
    _write_pins(repo, tmp_path)
    (repo / "src" / "qurantext").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("print('qalun')\n", encoding="utf-8")
    (repo / "src" / "qurantext" / "__init__.py").write_text(
        f'__version__ = "{version}"\n', encoding="utf-8"
    )
    (repo / ".gitignore").write_text("dist/\nout/\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _package(repo: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    script = repo / "packaging" / "ci" / "package.sh"
    result = subprocess.run(
        ["bash", str(script), "qalun-linux"], cwd=repo, capture_output=True, text=True
    )
    if check:
        assert result.returncode == 0, result.stderr
    return result


def _checkout_with_a_build(tmp_path: Path, **kwargs: str) -> Path:
    """The checkout with a built app in dist/ and an uncommitted file beside it."""
    repo = _checkout(tmp_path, **kwargs)
    (repo / "dist" / "qalun" / "_internal").mkdir(parents=True)
    (repo / "dist" / "qalun" / "qalun").write_bytes(b"\0")
    (repo / "notes.txt").write_text("not committed\n", encoding="utf-8")
    return repo


def _app_zip(repo: Path) -> zipfile.ZipFile:
    return zipfile.ZipFile(repo / "out" / "qalun-linux.zip")


@on_linux_with_zip_and_git
def test_the_linux_zip_stores_links_as_links_under_a_qalun_folder(tmp_path: Path) -> None:
    repo = _checkout(tmp_path)
    lib = repo / "dist" / "qalun" / "_internal" / "PySide6" / "Qt" / "lib"
    lib.mkdir(parents=True)
    (lib / "libQt6Core.so.6").write_bytes(b"\0" * 4096)
    (repo / "dist" / "qalun" / "_internal" / "libQt6Core.so.6").symlink_to(
        "PySide6/Qt/lib/libQt6Core.so.6"
    )

    _package(repo)

    with _app_zip(repo) as archive:
        names = archive.namelist()
        link = archive.getinfo("qalun/_internal/libQt6Core.so.6")
        target = archive.read(link)
    assert all(name.startswith("qalun/") for name in names)
    assert stat.S_ISLNK(link.external_attr >> 16)
    assert target == b"PySide6/Qt/lib/libQt6Core.so.6"


@on_linux_with_zip_and_git
def test_the_notice_and_the_licence_sit_beside_the_executable(tmp_path: Path) -> None:
    """Someone who unzips the app sees the credits the model's licence asks for, and
    the GPL-3.0 that Qalun is under."""
    repo = _checkout_with_a_build(tmp_path)

    _package(repo)

    with _app_zip(repo) as archive:
        notices = archive.read("qalun/THIRD_PARTY_NOTICES.md")
        licence = archive.read("qalun/LICENSE")
    assert notices == (ROOT / "THIRD_PARTY_NOTICES.md").read_bytes()
    assert licence == (ROOT / "LICENSE").read_bytes()


def test_it_refuses_when_there_is_nothing_to_zip(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "qalun-linux"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "run the build first" in result.stderr
    assert not (tmp_path / "out").exists()


@on_linux_with_zip_and_git
def test_every_app_zip_carries_the_source_of_the_commit_built(tmp_path: Path) -> None:
    """Qalun is GPL-3.0-only and its repository is private, so the source travels
    inside the app zip itself, beside the executable: whoever has the app has it."""
    repo = _checkout_with_a_build(tmp_path)

    _package(repo)

    with _app_zip(repo) as archive:
        inner = archive.read("qalun/qalun-source.zip")
    with zipfile.ZipFile(io.BytesIO(inner)) as source:
        names = set(source.namelist())
        assert source.read("qalun-source/LICENSE") == (repo / "LICENSE").read_bytes()
    assert all(name.startswith("qalun-source/") for name in names)
    assert {
        "qalun-source/packaging/ci/package.sh",
        "qalun-source/packaging/third-party-sources.txt",
        "qalun-source/src/app.py",
        "qalun-source/THIRD_PARTY_NOTICES.md",
    } <= names
    # The committed tree only: neither the build nor anything uncommitted.
    assert not any(name.startswith("qalun-source/dist/") for name in names)
    assert "qalun-source/notes.txt" not in names
    # Inside the app zip is where it goes; there is no separate source zip to forget.
    assert sorted(p.name for p in (repo / "out").iterdir()) == ["qalun-linux.zip"]


@on_linux_with_zip_and_git
def test_the_source_archive_cannot_be_skipped_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outside a git checkout there is no commit to archive; the package step fails
    rather than ship an app zip without its source."""
    root = tmp_path / "plain"
    (root / "packaging" / "ci").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "packaging" / "ci" / "package.sh")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy(ROOT / name, root / name)
    _write_pins(root, tmp_path)
    (root / "dist" / "qalun" / "_internal").mkdir(parents=True)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))

    result = _package(root, check=False)

    assert result.returncode != 0
    assert "source archive" in result.stderr
    assert not (root / "out" / "qalun-linux.zip").exists()


@on_linux_with_zip_and_git
def test_the_gpl_and_lgpl_sources_for_this_platform_are_inside_the_zip(tmp_path: Path) -> None:
    """espeak-ng in every zip, alsa-lib in the Linux one only, each byte for byte
    the pinned archive, with a list saying where each came from."""
    repo = _checkout_with_a_build(tmp_path)
    sources = _upstream(tmp_path)

    result = _package(repo)

    with _app_zip(repo) as archive:
        names = set(archive.namelist())
        listed = archive.read("qalun/third-party-sources/SOURCES.txt").decode("utf-8")
        for name in ("espeak-ng-fake.zip", "alsa-lib-fake.tar.bz2"):
            assert archive.read(f"qalun/third-party-sources/{name}") == sources[name]
            assert name in listed and _sha256(sources[name]) in listed
            assert (tmp_path / "upstream" / name).as_uri() in listed
    assert "qalun/third-party-sources/macos-only.tar.gz" not in names
    assert "qalun-source.zip" in listed
    assert "matches the pin" in result.stdout


@on_linux_with_zip_and_git
def test_a_source_whose_sha256_is_not_the_pin_fails_the_build(tmp_path: Path) -> None:
    repo = _checkout_with_a_build(tmp_path)
    _write_pins(repo, tmp_path, wrong="alsa-lib-fake.tar.bz2")

    result = _package(repo, check=False)

    assert result.returncode != 0
    assert "alsa-lib-fake.tar.bz2" in result.stderr and "Not shipping it" in result.stderr
    assert not (repo / "out" / "qalun-linux.zip").exists()
    assert not (tmp_path / "sources-cache" / "alsa-lib-fake.tar.bz2").exists()


@on_linux_with_zip_and_git
def test_a_source_that_cannot_be_downloaded_fails_the_build(tmp_path: Path) -> None:
    repo = _checkout_with_a_build(tmp_path)
    (tmp_path / "upstream" / "espeak-ng-fake.zip").unlink()

    result = _package(repo, check=False)

    assert result.returncode != 0
    assert "could not download the source espeak-ng-fake.zip" in result.stderr
    assert not (repo / "out" / "qalun-linux.zip").exists()


@on_linux_with_zip_and_git
def test_a_kept_download_is_reused_only_while_its_sha256_still_matches(tmp_path: Path) -> None:
    repo = _checkout_with_a_build(tmp_path)
    _package(repo)
    kept = tmp_path / "sources-cache" / "espeak-ng-fake.zip"
    assert kept.read_bytes() == b"espeak-ng source"

    # Gone upstream, still kept: no download needed.
    (tmp_path / "upstream" / "espeak-ng-fake.zip").unlink()
    assert "already downloaded" in _package(repo).stdout

    # Kept but damaged, and gone upstream: refused, not shipped.
    kept.write_bytes(b"damaged")
    assert _package(repo, check=False).returncode != 0


@on_linux_with_zip_and_git
def test_a_tagged_build_needs_the_tag_to_be_the_packages_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`qalun --version` and the doctor report say __version__; a tag that disagrees
    would ship an app naming another version."""
    repo = _checkout_with_a_build(tmp_path, version="0.2.0")
    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")

    monkeypatch.setenv("GITHUB_REF_NAME", "v0.3.0")
    refused = _package(repo, check=False)
    assert refused.returncode != 0
    assert 'v0.3.0 but src/qurantext/__init__.py says __version__ = "0.2.0"' in refused.stderr
    assert not (repo / "out").exists()

    monkeypatch.setenv("GITHUB_REF_NAME", "v0.2.0")
    _package(repo)
    assert (repo / "out" / "qalun-linux.zip").exists()


# --- The real pin list -------------------------------------------------------------


def _pins() -> list[tuple[str, str, str, str]]:
    rows = []
    for line in PINS.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            platform, name, sha, url = line.split("\t")
            rows.append((platform, name, sha, url))
    return rows


def test_the_pinned_sources_are_espeak_ng_everywhere_and_alsa_lib_on_linux() -> None:
    rows = {name: (platform, sha, url) for platform, name, sha, url in _pins()}
    espeak = "espeak-ng-ed530aa113046142eb5115cf2fc9157854d0ffe1.zip"
    assert rows[espeak] == (
        "all",
        "e4e262cbe34f7fe21f91f1ba3397f2728e1f30eafbae7853f2b753a9ed13f0dd",
        "https://github.com/csukuangfj/espeak-ng/archive/ed530aa113046142eb5115cf2fc9157854d0ffe1.zip",
    )
    assert rows["alsa-lib-1.2.12.tar.bz2"][0] == "linux"
    for platform, sha, url in rows.values():
        assert platform in {"all", "linux", "macos", "windows"}
        assert re.fullmatch(r"[0-9a-f]{64}", sha)
        assert url.startswith("https://")


def test_the_notice_names_each_pinned_source_and_where_it_is_in_the_zip() -> None:
    """The notice is what a recipient reads; it must point at the very archives the
    zip carries, by the same commit, version and sha256 as the pin list."""
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "third-party-sources/" in notice and "qalun-source.zip" in notice
    for _platform, name, sha, _url in _pins():
        assert name in notice, name
        assert sha in notice, name

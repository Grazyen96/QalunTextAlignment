"""The PyInstaller spec has to name Qt Multimedia, and must never exclude it.

The review window imports ``PySide6.QtMultimedia`` inside a function, behind a
try. PyInstaller's analysis does follow that import today (Task 3 found every
build since 57fc739 already bundled it), but a release must not depend on it:
without Multimedia the app quietly opens with playback disabled. So the spec
names it, and is read as text here so the rule lives in a test rather than
only in a comment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SPEC = Path(__file__).resolve().parents[1] / "packaging" / "qalun.spec"


def test_the_spec_names_qt_multimedia_and_excludes_none_of_it() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert '"PySide6.QtMultimedia"' in text
    excludes = text.split("excludes=[", 1)[1].split("]", 1)[0]
    assert "Multimedia" not in excludes


COLLECT_LINUX = SPEC.parent / "ci" / "collect-linux.sh"


def test_the_linux_build_machine_gets_the_libraries_qt_links() -> None:
    """GitHub's Linux runner is a bare machine: no sound or graphics stack.

    PyInstaller bundles only what it finds on the build machine, so without
    libpulse the bundle has no sound library and playback cannot load; EGL is
    never bundled (it belongs to the graphics driver, which every desktop has),
    but the gate cannot load Qt's drawing library on the runner without it. The
    first real CI run failed on exactly these two.
    """
    text = COLLECT_LINUX.read_text(encoding="utf-8")
    for package in ("libpulse0", "libegl1", "libxcb-cursor0", "libxkbcommon-x11-0"):
        assert package in text, package


def test_the_third_party_notice_credits_the_speech_model() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "THIRD_PARTY_NOTICES.md").read_text(
        encoding="utf-8"
    )
    assert "stt_ar_fastconformer_hybrid_large_pcd_v1.0" in text
    assert "CC BY 4.0" in text
    assert "sherpa-onnx" in text and "Apache" in text
    assert "without warranties" in text


def test_requirements_txt_carries_every_core_dependency() -> None:
    """The README installs from requirements.txt; pyproject is what CI installs.

    sherpa-onnx was once missing from requirements.txt, so an install that
    followed the README could not transcribe on the default engine, and nothing
    in CI noticed. Same name and same version range in both, or they drift again.
    """
    tomllib = pytest.importorskip("tomllib")  # Python 3.11+; the project allows 3.10
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as handle:
        core = tomllib.load(handle)["project"]["dependencies"]
    lines = (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
    pinned = {line.strip() for line in lines if line.strip() and not line.startswith("#")}
    assert set(core) == pinned


def test_the_spec_collects_sherpa_onnx() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert 'collect_dynamic_libs("sherpa_onnx")' in text
    assert 'collect_submodules("sherpa_onnx")' in text


def test_the_spec_ships_the_third_party_notice() -> None:
    assert "THIRD_PARTY_NOTICES.md" in SPEC.read_text(encoding="utf-8")


def test_the_spec_ships_certifis_certificates() -> None:
    """The model downloads over HTTPS, and a frozen app's OpenSSL looks for the
    build machine's certificates, which a Mac or another Linux does not have.
    certifi's bundle is the fallback, so its cacert.pem has to travel too."""
    assert 'collect_data_files("certifi")' in SPEC.read_text(encoding="utf-8")


def test_the_spec_ships_certifis_licence_in_its_own_right() -> None:
    """certifi is MPL-2.0 and its licence is in its metadata. It once travelled only
    because replicate's metadata is copied recursively, so dropping replicate would
    have dropped it silently; the notice names it, and the spec asks for it."""
    assert 'copy_metadata("certifi")' in SPEC.read_text(encoding="utf-8")
    notice = (SPEC.parents[1] / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "certifi" in notice and "Mozilla Public License 2.0" in notice


def test_the_notice_says_the_sherpa_onnx_build_contains_gpl_code() -> None:
    """The PyPI sherpa-onnx links espeak-ng (GPL-3.0-or-later) statically into the
    extension the app loads. The notice must not present the build as Apache/MIT only."""
    notice = (SPEC.parents[1] / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    section = notice.split("## sherpa-onnx", 1)[1].split("\n## ", 1)[0]
    assert "espeak-ng" in section and "GPL-3.0-or-later" in section
    for component in (
        "ONNX Runtime",
        "ThirdPartyNotices.txt",
        "kaldi-native-fbank",
        "kaldi-decoder",
        "kaldifst",
        "OpenFst",
        "pybind11",
        "piper-phonemize",
        "cppjieba",
    ):
        assert component in section, component


def test_the_spec_ships_the_engine_licences_beside_its_binaries() -> None:
    """sherpa-onnx (Apache 2.0) and the ONNX Runtime inside it (MIT) both ask for
    their licence text to go wherever the binaries go. sherpa-onnx's wheel carries
    its own; ONNX Runtime's does not reach the wheel, so the repository keeps it."""
    text = SPEC.read_text(encoding="utf-8")
    assert 'distribution("sherpa_onnx")' in text
    assert "onnxruntime-LICENSE" in text
    licence = SPEC.parent / "licenses" / "onnxruntime-LICENSE"
    body = licence.read_text(encoding="utf-8")
    assert "MIT License" in body and "Copyright (c) Microsoft Corporation" in body


def test_the_spec_ships_the_libasound_licence_where_the_wheel_vendors_it() -> None:
    """sherpa-onnx's Linux wheel vendors ALSA's libasound (LGPL-2.1) without its
    licence. The text goes beside it, and the notice names it, for Linux builds."""
    text = SPEC.read_text(encoding="utf-8")
    assert '"libasound-LGPL-2.1.txt"), "sherpa_onnx.libs"' in text
    assert 'f.name.startswith("libasound")' in text
    body = (SPEC.parent / "licenses" / "libasound-LGPL-2.1.txt").read_text(encoding="utf-8")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in body and "Version 2.1, February 1999" in body
    assert "END OF TERMS AND CONDITIONS" in body
    readme = (SPEC.parent / "licenses" / "README.md").read_text(encoding="utf-8")
    assert "https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt" in readme
    notice = (SPEC.parents[1] / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "libasound" in notice and "Linux builds only" in notice
    assert "Lesser General Public License" in notice


ROOT = SPEC.parents[1]


def test_qalun_is_licensed_gpl_3_0_only() -> None:
    """The bundled sherpa-onnx links espeak-ng (GPL-3.0-or-later) into the app's own
    process, so Qalun is released under GPL-3.0-only: the full, unmodified text at the
    root, the licence in the package metadata, and the statement first in the notice."""
    licence = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert licence.split("\n", 2)[:2] == [
        " " * 20 + "GNU GENERAL PUBLIC LICENSE",
        " " * 23 + "Version 3, 29 June 2007",
    ]
    assert "END OF TERMS AND CONDITIONS" in licence
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    own = notice.split("\n## ", 2)[1]
    assert own.startswith("Qalun")
    for phrase in ("GPL-3.0-only", "Copyright (C) 2026 Khalil", "WITHOUT ANY WARRANTY"):
        assert phrase in own, phrase
    assert "qalun-source.zip" in own and "third-party-sources/" in own
    section = notice.split("## sherpa-onnx", 1)[1].split("\n## ", 1)[0]
    assert "compatible" in section
    tomllib = pytest.importorskip("tomllib")
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["license"] == "GPL-3.0-only"
    assert "LICENSE" in project["license-files"]


def test_the_spec_ships_qaluns_licence() -> None:
    assert '(str(ROOT / "LICENSE"), ".")' in SPEC.read_text(encoding="utf-8")


def test_the_spec_ships_onnx_runtimes_third_party_notices() -> None:
    """ONNX Runtime embeds protobuf, abseil, flatbuffers, ONNX, Eigen and more, whose
    licences want their notices reproduced with the binary. ONNX Runtime collects them
    in ThirdPartyNotices.txt, which the sherpa-onnx wheel does not carry."""
    text = SPEC.read_text(encoding="utf-8")
    assert '"onnxruntime-ThirdPartyNotices.txt"), "sherpa_onnx/lib"' in text
    body = (SPEC.parent / "licenses" / "onnxruntime-ThirdPartyNotices.txt").read_text(
        encoding="utf-8"
    )
    assert body.startswith("THIRD PARTY SOFTWARE NOTICES AND INFORMATION")
    assert "protobuf" in body.lower() and "abseil" in body.lower()
    readme = (SPEC.parent / "licenses" / "README.md").read_text(encoding="utf-8")
    url = "https://github.com/microsoft/onnxruntime/blob/v1.28.2/ThirdPartyNotices.txt"
    assert url in readme
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "_internal/sherpa_onnx/lib/onnxruntime-ThirdPartyNotices.txt" in notice


def test_the_release_checklist_checks_for_the_source_and_the_licence() -> None:
    """The GPL question is settled; what a release must now carry is checked by hand."""
    checklist = (ROOT / "docs" / "release-checklist.md").read_text(encoding="utf-8")
    assert "Do not tag\n      a release" not in checklist
    assert "qalun-source.zip" in checklist and "third-party-sources/" in checklist
    assert "LICENSE" in checklist


def _sherpa_onnx_pin() -> str:
    """The one sherpa-onnx version the build may use, read from pyproject.toml."""
    tomllib = pytest.importorskip("tomllib")
    with (ROOT / "pyproject.toml").open("rb") as handle:
        core = tomllib.load(handle)["project"]["dependencies"]
    pins = [dep for dep in core if dep.startswith("sherpa-onnx")]
    assert len(pins) == 1 and pins[0].startswith("sherpa-onnx=="), pins
    return pins[0].removeprefix("sherpa-onnx==")


def test_the_installed_sherpa_onnx_is_the_build_the_notices_describe() -> None:
    """The notice, the shipped licence files and the pinned third-party sources all
    describe one sherpa-onnx build. An open range let a new release slip in under
    them unnoticed, so the pin is exact, and this fails the moment the installed
    version, the pin and the texts disagree."""
    from importlib.metadata import version

    pin = _sherpa_onnx_pin()
    assert f"sherpa-onnx=={pin}" in (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert version("sherpa_onnx") == pin, (
        f"sherpa-onnx {version('sherpa_onnx')} is installed but the pin and the notices say "
        f"{pin}: reinstall with `pip install -e .`, or move the pin and update "
        "THIRD_PARTY_NOTICES.md, packaging/licenses/ and packaging/third-party-sources.txt"
    )
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    section = notice.split("## sherpa-onnx", 1)[1].split("\n## ", 1)[0]
    assert f"version {pin} as published on PyPI" in section
    assert f"sherpa-onnx\n  v{pin} builds espeak-ng" in section
    assert f"/sherpa-onnx/tree/v{pin}" in section
    readme = (SPEC.parent / "licenses" / "README.md").read_text(encoding="utf-8")
    assert f"sherpa-onnx {pin}" in readme
    sources = (SPEC.parent / "third-party-sources.txt").read_text(encoding="utf-8")
    assert f"sherpa-onnx v{pin}" in sources and f"sherpa-onnx {pin}" in sources


def test_the_version_is_written_down_once() -> None:
    """pyproject.toml reads the version from the package, which `qalun --version` and
    the doctor report say; package.sh holds a tag build to it."""
    tomllib = pytest.importorskip("tomllib")
    with (ROOT / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)
    assert "version" not in config["project"]
    assert "version" in config["project"]["dynamic"]
    assert config["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "qurantext.__version__"}
    package = (SPEC.parent / "ci" / "package.sh").read_text(encoding="utf-8")
    assert "src/qurantext/__init__.py" in package and "GITHUB_REF_NAME" in package


def test_the_quran_font_and_text_are_kept_out_of_the_gpl_statement() -> None:
    """Their provenance and terms are not known yet, so nothing may present them as
    Qalun's own GPL-3.0 code, and the release waits until the owner confirms them."""
    files = ("qaloon.10.ttf", "qaloon.10.woff2", "UthmanicQaloon1-v10.txt")
    phrase = "to be confirmed by the owner"
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    section = " ".join(notice.split("## Quran text and font", 1)[1].split("\n## ", 1)[0].split())
    assert "**not** licensed under the GPL" in section and phrase in section
    for path in (
        ROOT / "README.md",
        ROOT / "src" / "qurantext" / "assets" / "README.md",
        ROOT / "pyproject.toml",
    ):
        text = " ".join(path.read_text(encoding="utf-8").split())
        assert phrase in text, path
        for name in files:
            assert name in text, (path, name)
    for name in files:
        assert name in section
    checklist = (ROOT / "docs" / "release-checklist.md").read_text(encoding="utf-8")
    assert "UthmanicQaloon1-v10.txt" in checklist and "qaloon.10" in checklist


def test_the_release_checklist_holds_the_first_tag_on_what_code_cannot_settle() -> None:
    """The owner's open decisions, and the checks only a person on a real machine can
    make, are written where the person releasing works through them."""
    checklist = (ROOT / "docs" / "release-checklist.md").read_text(encoding="utf-8")
    flat = " ".join(checklist.split())
    blocking = flat.split("## Before the first release: blocking", 1)[1].split(" ## ", 1)[0]
    assert "confirm their source and terms before the first tag" in blocking
    assert (
        "Licence review: source obligations for Qt (LGPL), FriBiDi (LGPL) and the GPL "
        "FFmpeg build" in blocking
    )
    assert "must not point at the private repository's release page" in blocking
    assert "Arabic letters" in blocking
    assert "## By ear, on Windows, macOS and Linux" in checklist
    assert "Check the words appear" in flat
    assert "__version__" in flat


AMIRI_RELEASE = "1.003"
AMIRI_SHA256 = {
    "Amiri-Regular.ttf": "cd2550c0f4c05eb341bf97958211aaa39382bca96577ba3a67d4a3b4912c43c0",
    "Amiri-Bold.ttf": "8cfed49b66de57e360ac61631d882dddfa23095d3ddb39fc2133eaf93892e79a",
}


def test_the_title_font_is_the_pinned_amiri_release() -> None:
    """The generated intro and outro write their titles in Amiri (SIL OFL 1.1). The
    files are the release's own, byte for byte, and the notice and the assets README
    name that release and those hashes, so a swapped file fails here."""
    import hashlib

    fonts = ROOT / "src" / "qurantext" / "assets" / "fonts"
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    section = notice.split("## Amiri", 1)[1].split("\n## ", 1)[0]
    readme = (ROOT / "src" / "qurantext" / "assets" / "README.md").read_text(encoding="utf-8")
    for name, digest in AMIRI_SHA256.items():
        assert hashlib.sha256((fonts / name).read_bytes()).hexdigest() == digest, name
        assert name in section and digest in section, name
        assert name in readme and digest in readme, name
    for text in (section, readme):
        assert f"aliftype/amiri/releases/tag/{AMIRI_RELEASE}" in text
        assert "SIL Open Font License" in text and "Amiri-OFL.txt" in text


def test_amiris_licence_travels_with_the_font() -> None:
    """The OFL asks for its text to go with every copy of the font. The font ships in
    the wheel and in the app (the spec copies assets/ whole), so the licence sits
    beside it in assets/fonts/; packaging/licenses/ keeps the same text."""
    kept = SPEC.parent / "licenses" / "Amiri-OFL.txt"
    beside = ROOT / "src" / "qurantext" / "assets" / "fonts" / "Amiri-OFL.txt"
    body = kept.read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in body
    assert "The Amiri Project Authors" in body
    assert beside.read_bytes() == kept.read_bytes()
    assert '(str(ROOT / "src" / "qurantext" / "assets"), "qurantext/assets")' in (
        SPEC.read_text(encoding="utf-8")
    )
    readme = (SPEC.parent / "licenses" / "README.md").read_text(encoding="utf-8")
    assert "Amiri-OFL.txt" in readme


NOTO_RELEASE = "NotoSansArabic-v2.013"
NOTO_SHA256 = {
    "NotoSansArabic-Regular.ttf": "bd86ca02f087d7f3c3788ba458fb6b73744c7639ed276b8d870dba6def6c40d0",
    "NotoSansArabic-Bold.ttf": "f4cb79f842a07d1bcf597879574358fb7010f73761396d1d0f2445dfedb4d2ca",
}


def test_the_interface_font_is_the_pinned_noto_release() -> None:
    """The window draws Arabic letters in Noto Sans Arabic (SIL OFL 1.1) on a machine
    with no Arabic font. The files are the release's own, byte for byte, and the
    notice, the assets README and the fetch tool name that release and those hashes,
    so a swapped file fails here."""
    import hashlib

    fonts = ROOT / "src" / "qurantext" / "assets" / "fonts"
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    section = notice.split("## Noto Sans Arabic", 1)[1].split("\n## ", 1)[0]
    readme = (ROOT / "src" / "qurantext" / "assets" / "README.md").read_text(encoding="utf-8")
    readme_section = readme.split("## Noto Sans Arabic", 1)[1].split("\n## ", 1)[0]
    tool = (ROOT / "tools" / "fetch_fonts.py").read_text(encoding="utf-8")
    for name, digest in NOTO_SHA256.items():
        assert hashlib.sha256((fonts / name).read_bytes()).hexdigest() == digest, name
        assert name in section and digest in section, name
        assert name in readme_section and digest in readme_section, name
        assert f'"{name}": "{digest}"' in tool, name
    for text in (section, readme_section):
        assert f"notofonts/arabic/releases/tag/{NOTO_RELEASE}" in text
        assert "SIL Open Font License" in text and "NotoSansArabic-OFL.txt" in text
    assert f'TAG = "{NOTO_RELEASE}"' in tool


def test_notos_licence_travels_with_the_font() -> None:
    """As with Amiri: the licence sits beside the fonts in assets/fonts/, and
    packaging/licenses/ keeps the same text, listed in its README."""
    kept = SPEC.parent / "licenses" / "NotoSansArabic-OFL.txt"
    beside = ROOT / "src" / "qurantext" / "assets" / "fonts" / "NotoSansArabic-OFL.txt"
    body = kept.read_text(encoding="utf-8")
    assert "SIL Open Font License, Version 1.1" in body
    assert "The Noto Project Authors" in body
    assert beside.read_bytes() == kept.read_bytes()
    readme = (SPEC.parent / "licenses" / "README.md").read_text(encoding="utf-8")
    assert "NotoSansArabic-OFL.txt" in readme
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "NotoSansArabic-Regular.ttf" in pyproject and "NotoSansArabic-OFL.txt" in pyproject


def _load_fetch_fonts():
    import importlib.util

    spec = importlib.util.spec_from_file_location("fetch_fonts", ROOT / "tools" / "fetch_fonts.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


def _fetch_fonts_tool(monkeypatch, tmp_path, members: dict[str, bytes]):
    """tools/fetch_fonts.py, writing under *tmp_path*, its download an archive of *members*."""
    import io
    import zipfile

    tool = _load_fetch_fonts()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for member, data in members.items():
            archive.writestr(member, data)
    monkeypatch.setattr(tool, "_download", lambda: zipfile.ZipFile(io.BytesIO(buffer.getvalue())))
    monkeypatch.setattr(tool, "ROOT", tmp_path)
    monkeypatch.setattr(tool, "FONTS", tmp_path / "fonts")
    monkeypatch.setattr(tool, "LICENSES", tmp_path / "licenses")
    (tmp_path / "licenses").mkdir(parents=True)
    return tool


def test_the_font_fetcher_writes_nothing_when_a_file_is_not_the_pinned_one(
    monkeypatch, tmp_path, capsys
) -> None:
    fonts = ROOT / "src" / "qurantext" / "assets" / "fonts"
    members = _load_fetch_fonts().FILES
    shipped = {member: (fonts / name).read_bytes() for member, name in members.items()}
    swapped = dict(shipped)
    bold = "NotoSansArabic/unhinted/ttf/NotoSansArabic-Bold.ttf"
    swapped[bold] = b"not the release's bold"
    tool = _fetch_fonts_tool(monkeypatch, tmp_path, swapped)
    assert tool.main() == 1
    assert not (tmp_path / "fonts").exists()
    err = capsys.readouterr().err
    assert NOTO_SHA256["NotoSansArabic-Bold.ttf"] in err and "nothing was written" in err
    # The release's own files are written, with their sums.
    tool = _fetch_fonts_tool(monkeypatch, tmp_path / "ok", shipped)
    assert tool.main() == 0
    for name in NOTO_SHA256:
        assert (tmp_path / "ok" / "fonts" / name).read_bytes() == (fonts / name).read_bytes()
    assert (tmp_path / "ok" / "licenses" / "NotoSansArabic-OFL.txt").is_file()


def _segno_pin() -> str:
    tomllib = pytest.importorskip("tomllib")
    with (ROOT / "pyproject.toml").open("rb") as handle:
        core = tomllib.load(handle)["project"]["dependencies"]
    pins = [dep for dep in core if dep.startswith("segno")]
    assert len(pins) == 1 and pins[0].startswith("segno=="), pins
    return pins[0].removeprefix("segno==")


def test_segno_is_pinned_credited_and_its_licence_shipped() -> None:
    """segno (BSD 3-Clause) draws the outro's QR code. It is pure Python, so the app
    carries it inside its archive, where its own licence file does not go; the
    repository keeps that licence and the spec ships it beside the notice."""
    from importlib.metadata import distribution

    pin = _segno_pin()
    assert f"segno=={pin}" in (ROOT / "requirements.txt").read_text(encoding="utf-8")
    installed = distribution("segno")
    assert installed.version == pin, (
        f"segno {installed.version} is installed but the pin says {pin}: reinstall with "
        "`pip install -e .`, or move the pin and update THIRD_PARTY_NOTICES.md and "
        "packaging/licenses/segno-LICENSE.txt"
    )
    kept = SPEC.parent / "licenses" / "segno-LICENSE.txt"
    wheel = next(f for f in installed.files or () if f.name == "LICENSE")
    assert kept.read_text(encoding="utf-8") == wheel.read_text(encoding="utf-8")
    assert '"segno-LICENSE.txt"), ".")' in SPEC.read_text(encoding="utf-8")
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    section = notice.split("## segno", 1)[1].split("\n## ", 1)[0]
    assert f"version {pin}" in section and "BSD 3-Clause" in section
    assert "_internal/segno-LICENSE.txt" in section
    readme = (SPEC.parent / "licenses" / "README.md").read_text(encoding="utf-8")
    assert "segno-LICENSE.txt" in readme and f"segno {pin}" in readme


def test_idna_is_pinned_credited_and_its_licence_shipped() -> None:
    """idna (BSD 3-Clause) turns the outro link's international host into the QR
    code's ASCII form with the rules browsers use. Qalun now uses it directly, so it
    is a pinned dependency of its own, credited by name, its licence copied with its
    metadata, rather than riding on replicate's."""
    from importlib.metadata import distribution

    tomllib = pytest.importorskip("tomllib")
    with (ROOT / "pyproject.toml").open("rb") as handle:
        core = tomllib.load(handle)["project"]["dependencies"]
    pins = [dep for dep in core if dep.startswith("idna")]
    assert len(pins) == 1 and pins[0].startswith("idna=="), pins
    pin = pins[0].removeprefix("idna==")
    assert f"idna=={pin}" in (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert distribution("idna").version == pin
    assert 'copy_metadata("idna")' in SPEC.read_text(encoding="utf-8")
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    section = notice.split("## idna", 1)[1].split("\n## ", 1)[0]
    assert f"version {pin}" in section and "BSD 3-Clause" in section
    assert f"_internal/idna-{pin}.dist-info/licenses/LICENSE.md" in section
    assert any(f.name == "LICENSE.md" for f in distribution("idna").files or ())


ICON_DIR = Path(__file__).resolve().parents[1] / "src" / "qurantext" / "assets" / "icons"


def test_every_interface_icon_ships_with_lucides_licence() -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from fetch_icons import ICON_NAMES

    assert len(ICON_NAMES) == 41
    for name in ICON_NAMES:
        svg = ICON_DIR / f"{name}.svg"
        assert svg.is_file(), name
        assert 'stroke="currentColor"' in svg.read_text(encoding="utf-8"), name
    assert "ISC License" in (ICON_DIR / "LICENSE").read_text(encoding="utf-8")


def test_the_third_party_notice_credits_lucide() -> None:
    text = (Path(__file__).resolve().parents[1] / "THIRD_PARTY_NOTICES.md").read_text(
        encoding="utf-8"
    )
    assert "## Lucide icons" in text
    assert "1.56.0" in text and "ISC" in text
    # Lucide's LICENSE also carries Feather's MIT licence, for the icons derived from it.
    section = text.split("## Lucide icons", 1)[1].split("\n## ", 1)[0]
    assert "MIT" in section and "Feather" in section and "Cole Bemis" in section
    assert "qurantext/assets/icons/LICENSE" in text


def _call(text: str, name: str) -> str:
    """The source of the first ``name(...)`` call in *text*, up to its closing bracket."""
    start = text.index(f"{name}(")
    depth = 0
    for index in range(start + len(name), len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError(f"{name}( is never closed")


def test_the_spec_names_the_app_icon_for_windows_and_mac() -> None:
    """The executable carries the .ico, the macOS bundle the .icns, and both files exist."""
    text = SPEC.read_text(encoding="utf-8")
    icon_dir = Path(__file__).resolve().parents[1] / "src" / "qurantext" / "assets" / "icon"
    assert 'ICON_DIR = ROOT / "src" / "qurantext" / "assets" / "icon"' in text
    exe_icon_line = next(line for line in text.splitlines() if line.startswith("EXE_ICON ="))
    assert '"qalun.ico"' in exe_icon_line
    assert "icon=EXE_ICON" in _call(text, "EXE")
    assert '"qalun.icns"' in _call(text, "BUNDLE")
    assert (icon_dir / "qalun.ico").is_file()
    assert (icon_dir / "qalun.icns").is_file()

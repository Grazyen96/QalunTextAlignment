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
    assert "qalun-source-" in own
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
    assert "qalun-source-*.zip" in checklist and "LICENSE" in checklist

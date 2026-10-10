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

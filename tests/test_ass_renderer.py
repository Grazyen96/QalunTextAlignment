"""The ASS document the command line's burned-in renderer writes."""

from __future__ import annotations

from qurantext.core.ass_renderer import build_ass

# Dammatan as the shipped text writes it (U+065E); only its own font draws that open.
JANNATUN = "جَنَّةٞ"


def _card() -> dict:
    return {"start_time": 0.0, "end_time": 2.0, "full_text": JANNATUN}


def test_build_ass_writes_standard_tanween() -> None:
    document = build_ass([_card()], "Amiri", 1280, 720)
    assert "ࣱ" in document
    assert "ٞ" not in document


def test_build_ass_keeps_the_marks_for_the_qaloon_face() -> None:
    """That face draws the mushaf's code points and has no U+08F0-08F2."""
    document = build_ass([_card()], "KFGQPC QALOON Uthmanic Script", 1280, 720)
    assert "ٞ" in document
    assert "ࣱ" not in document

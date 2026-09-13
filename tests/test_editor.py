"""The subtitle editor.

Two things are edited and the difference is the point: recognised speech is
fully editable, and Quran text is not. These pin both, plus the behaviour that
makes a correction survive.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6", reason="the editor needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qurantext.gui.editor import SubtitleEditor  # noqa: E402
from qurantext.jobs.project import CaptionCue, Project, load_project, save_project  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture()
def project(tmp_path):
    audio = tmp_path / "dars.mp3"
    audio.touch()
    p = Project(
        audio=audio,
        mode="lecture",
        cards=[
            {
                "surah_num": 25,
                "surah_name": "سُورَةُ الفُرقَانِ",
                "from_ayah": 7,
                "to_ayah": 7,
                "full_text": "وَقَالُواْ مَالِ هَٰذَا اَ۬لرَّسُولِ",
                "confidence": 0.9,
                "start_time": 1.0,
                "end_time": 4.0,
            },
            {
                "surah_num": 25,
                "surah_name": "سُورَةُ الفُرقَانِ",
                "from_ayah": 8,
                "to_ayah": 8,
                "full_text": "أَوْ يُلْقَيٰ إِلَيْهِ كَنزٌ",
                "confidence": 0.4,
                "start_time": 4.0,
                "end_time": 7.0,
            },
        ],
        captions=[
            CaptionCue(
                0.0, 2.0, "misheard line", words=[{"word": "misheard", "start": 0.0, "end": 1.0}]
            ),
            CaptionCue(2.0, 4.0, "second line"),
        ],
    )
    save_project(p, tmp_path / "job.qalun.json")
    return p


def test_both_panes_are_populated(qt_app, project) -> None:
    editor = SubtitleEditor(project)
    assert editor.captions_table.rowCount() == 2
    assert editor.cards_table.rowCount() == 2
    assert editor.cards_table.item(0, 2).text() == "25:7"


def test_quran_text_cannot_be_edited(qt_app, project) -> None:
    """The canonical text comes from the store. This is a lock, not an oversight."""
    editor = SubtitleEditor(project)
    text_cell = editor.cards_table.item(0, 3)
    assert not (text_cell.flags() & Qt.ItemFlag.ItemIsEditable)
    ref_cell = editor.cards_table.item(0, 2)
    assert not (ref_cell.flags() & Qt.ItemFlag.ItemIsEditable)


def test_recognised_speech_is_editable(qt_app, project) -> None:
    editor = SubtitleEditor(project)
    assert editor.captions_table.item(0, 2).flags() & Qt.ItemFlag.ItemIsEditable


def test_editing_a_caption_updates_the_project_and_drops_stale_word_timings(
    qt_app, project
) -> None:
    editor = SubtitleEditor(project)
    assert project.captions[0].words, "precondition: the cue starts with word timings"

    editor.captions_table.item(0, 2).setText("corrected by hand")

    assert project.captions[0].text == "corrected by hand"
    assert project.captions[0].words == [], "timings describe the words that were replaced"


def test_editing_a_time_updates_the_project(qt_app, project) -> None:
    editor = SubtitleEditor(project)
    editor.captions_table.cellWidget(0, 1).setValue(3.5)
    assert project.captions[0].end == pytest.approx(3.5)

    editor.cards_table.cellWidget(1, 0).setValue(5.25)
    assert project.cards[1]["start_time"] == pytest.approx(5.25)


def test_an_end_cannot_be_dragged_before_its_start(qt_app, project) -> None:
    editor = SubtitleEditor(project)
    editor.captions_table.cellWidget(1, 0).setValue(3.0)
    editor.captions_table.cellWidget(1, 1).setValue(1.0)
    cue = project.captions[1]
    assert cue.end >= cue.start, "a backwards cue is a broken line in every player"


def test_removing_a_false_positive_drops_the_card(qt_app, project) -> None:
    editor = SubtitleEditor(project)
    editor.tabs.setCurrentIndex(1)
    editor.cards_table.selectRow(1)
    editor._remove_selected()

    assert len(project.cards) == 1
    assert project.cards[0]["from_ayah"] == 7
    assert editor.cards_table.rowCount() == 1


def test_saving_writes_the_corrections_back(qt_app, project, tmp_path) -> None:
    """The whole point: the next render reads these, not the raw transcript."""
    editor = SubtitleEditor(project)
    editor.captions_table.item(0, 2).setText("corrected")
    saved: list[object] = []
    editor.saved.connect(saved.append)

    path = editor.save()

    assert path is not None and saved
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["captions"][0]["text"] == "corrected"
    assert load_project(path).captions[0].text == "corrected"


def test_check_reports_when_there_is_nothing_to_check_against(qt_app, project) -> None:
    """Cards without word timings cannot be checked, and it says so."""
    editor = SubtitleEditor(project)
    messages = editor.check_coverage()
    assert messages == []
    assert not editor.warnings.isHidden()
    assert "no word timings" in editor.warnings.text()


def test_check_reports_a_missing_audio_file_plainly(qt_app, tmp_path) -> None:
    p = Project(audio=tmp_path / "gone.mp3", mode="recitation")
    save_project(p, tmp_path / "j.qalun.json")
    editor = SubtitleEditor(p)
    editor.check_coverage()
    assert "not found" in editor.warnings.text()

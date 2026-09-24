"""The Arabic window: laid out right to left, except where time runs.

Every test here switches to Arabic itself, before building anything (a widget
takes the application's direction when it is made); the autouse fixture in
``conftest.py`` puts the next test back into English.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterator

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import QEvent, QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QTableWidget,
    QWidget,
)

from qurantext.gui import i18n  # noqa: E402
from qurantext.gui.home.job_list import JobListPanel  # noqa: E402
from qurantext.gui.home.new_job import NewJobPanel  # noqa: E402
from qurantext.gui.language import apply_language  # noqa: E402
from qurantext.gui.prefs import Prefs  # noqa: E402
from qurantext.gui.review.player import FakePlayer  # noqa: E402
from qurantext.jobs.project import CaptionCue, Project, save_project  # noqa: E402
from tests.media_helpers import QURAN_FILE  # noqa: E402
from tests.qt_helpers import wait_until_listed  # noqa: E402

LTR = Qt.LayoutDirection.LeftToRight
RTL = Qt.LayoutDirection.RightToLeft

#: The first words of Al-Furqan 25:7, so the card's text is Arabic as a real one is.
_AYAH_WORDS = ("وَقَالُوا", "مَالِ")


@pytest.fixture(autouse=True)
def _arabic(qt_app) -> Iterator[None]:
    """Arabic for the whole test, and no window left behind for the next one."""
    apply_language(QApplication.instance(), "ar")
    yield
    for widget in qt_app.topLevelWidgets():
        widget.hide()
        widget.deleteLater()
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class _Now:
    t = 0.0

    def __call__(self) -> float:
        return self.t


def _prefs(tmp_path) -> Prefs:
    return Prefs(QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat))


def _recitation_project(tmp_path) -> Project:
    cards = [
        {
            "surah_num": 25,
            "from_ayah": 7,
            "to_ayah": 7,
            "full_text": " ".join(_AYAH_WORDS),
            "confidence": 1.0,
            "start_time": 0.0,
            "end_time": 10.0,
            "word_timings": [
                {"word": _AYAH_WORDS[0], "start": 1.0, "end": 2.0},
                {"word": _AYAH_WORDS[1], "start": 2.0, "end": 3.0},
            ],
        }
    ]
    matches = tmp_path / "m.json"
    matches.write_text(
        json.dumps({"matches": cards, "meta": {"mode": "recitation"}}), encoding="utf-8"
    )
    project = Project(audio=tmp_path / "missing.mp3", cards=cards, matches=matches)
    save_project(project, tmp_path / "m.qalun.json")
    return project


@pytest.fixture()
def review_window(qt_app, tmp_path):
    from qurantext.gui.review.window import ReviewWindow

    window = ReviewWindow(
        _recitation_project(tmp_path), player=FakePlayer(duration=10.0, now=_Now())
    )
    window.resize(1100, 800)
    return window


@pytest.fixture()
def lecture_review_window(qt_app, tmp_path):
    from qurantext.gui.review.window import ReviewWindow

    words = [{"word": "Hello", "start": 0.0, "end": 1.0}]
    project = Project(
        audio=tmp_path / "missing.mp3",
        mode="lecture",
        captions=[CaptionCue(0.0, 1.0, "Hello", words=words)],
    )
    window = ReviewWindow(project, player=FakePlayer(duration=4.0, now=_Now()))
    window.resize(1100, 800)
    return window


def _texts(root: QWidget) -> Iterator[str]:
    """Every word *root* shows a person: titles, labels, buttons, tips, items, headers."""
    yield root.windowTitle()
    for widget in [root, *root.findChildren(QWidget)]:
        yield widget.toolTip()
        if isinstance(widget, QLabel):
            yield widget.text()
        if isinstance(widget, QAbstractButton):
            yield widget.text()
        if isinstance(widget, QGroupBox):
            yield widget.title()
        if isinstance(widget, QLineEdit):
            yield widget.placeholderText()
        if isinstance(widget, QComboBox):
            yield from (widget.itemText(i) for i in range(widget.count()))
        if isinstance(widget, QTableWidget):
            for i in range(widget.columnCount()):
                header = widget.horizontalHeaderItem(i)
                if header is not None:
                    yield header.text()


def test_time_widgets_keep_left_to_right_and_the_rest_mirrors(qt_app, review_window) -> None:
    w = review_window
    pinned = (
        w.waveform,
        w.strip,
        w.zoom_slider,
        w.frame_view,
        w.time_label,
        w.selection_bar.nudge_row,
    )
    for widget in pinned:
        assert widget.layoutDirection() == LTR, widget
    for widget in (w, w.segment_list, w.warnings, w.save_button):
        assert widget.layoutDirection() == RTL, widget


def test_arrow_keys_step_time_the_same_way_in_arabic(qt_app, review_window) -> None:
    w = review_window
    w.seek(5.0)
    QTest.keyClick(w, Qt.Key.Key_Left)
    assert w.player.position() < 5.0  # Left is earlier on a left-to-right time axis


def test_the_minus_button_sits_left_of_plus(qt_app, review_window) -> None:
    bar = review_window.selection_bar
    # The whole window, not the bar alone: a child of a hidden window stays
    # hidden, and the buttons' own row is only laid out once it shows.
    review_window.show()
    qt_app.processEvents()
    assert bar.minus_button.x() < bar.plus_button.x()
    assert bar.plus_button.x() < bar.snap_button.x()


def test_segment_times_are_isolated_and_text_aligns_to_its_script(qt_app, review_window) -> None:
    table = review_window.segment_list
    time_text = table.item(0, 1).text()
    assert time_text.startswith("\u2066") and time_text.endswith("\u2069")
    alignment = table.item(0, 2).textAlignment()
    assert alignment & Qt.AlignmentFlag.AlignAbsolute
    assert alignment & Qt.AlignmentFlag.AlignRight  # Quran text is Arabic: its right edge


def test_a_latin_caption_aligns_left(qt_app, lecture_review_window) -> None:
    table = lecture_review_window.segment_list
    assert table.item(0, 2).text() == "Hello"
    alignment = table.item(0, 2).textAlignment()
    assert alignment & Qt.AlignmentFlag.AlignAbsolute
    assert alignment & Qt.AlignmentFlag.AlignLeft
    assert not alignment & Qt.AlignmentFlag.AlignRight


def test_the_job_list_mirrors(qt_app, tmp_path, no_default_job_dirs) -> None:
    panel = JobListPanel(_prefs(tmp_path))
    assert panel.list.layoutDirection() == RTL


def test_more_options_points_the_way_arabic_reads(
    qt_app, tmp_path, store, no_default_job_dirs
) -> None:
    panel = NewJobPanel(_prefs(tmp_path), quran_default=QURAN_FILE, db_path=store)
    panel.more_button.setChecked(False)
    assert panel.more_button.arrowType() == Qt.ArrowType.LeftArrow
    panel.more_button.setChecked(True)
    assert panel.more_button.arrowType() == Qt.ArrowType.DownArrow
    panel.more_button.setChecked(False)
    assert panel.more_button.arrowType() == Qt.ArrowType.LeftArrow


#: The Latin words the Arabic table itself keeps: the app's name, subtitle
#: formats, a key name, the package to install, and "English" in the language menu.
_LATIN_THE_TABLE_KEEPS = {"Qalun", "SRT", "VTT", "ASS", "Ctrl", "Z", "PySide6", "Addons", "English"}
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def _latin_words_of_the_arabic_table() -> set[str]:
    words: set[str] = set()
    for value in i18n.STRINGS["ar"].values():
        for variant in value.values() if isinstance(value, dict) else [value]:
            words |= set(_LATIN_WORD.findall(re.sub(r"\{[^}]*\}", "", variant)))
    return words


def test_the_allowed_latin_words_are_what_the_table_really_keeps() -> None:
    """The allow-list below may not grow past the table: each word must be in it."""
    assert _latin_words_of_the_arabic_table() | {"English"} == _LATIN_THE_TABLE_KEEPS


def _shown(root: QWidget) -> Iterator[str]:
    """What _texts reads, plus list items and table cells."""
    yield from _texts(root)
    for widget in [root, *root.findChildren(QWidget)]:
        if isinstance(widget, QListWidget):
            yield from (widget.item(i).text() for i in range(widget.count()))
        if isinstance(widget, QTableWidget):
            for row in range(widget.rowCount()):
                for column in range(widget.columnCount()):
                    item = widget.item(row, column)
                    if item is not None:
                        yield item.text()


def test_no_english_is_left_in_the_arabic_windows(
    qt_app, tmp_path, store, no_default_job_dirs, review_window, lecture_review_window, monkeypatch
) -> None:
    """Every Latin word a person reads is one the table keeps, or the fixture's own names.

    Not a comparison with the English table: a hard-coded literal or a message
    from the pipeline would pass that. The windows are busy ones: a job row, a
    running job, its progress, the job's context menu and a lecture review.
    """
    from qurantext.gui.home import job_list as job_list_module
    from qurantext.gui.main_window import MainWindow
    from qurantext.utils.progress import ProgressEvent

    prefs = _prefs(tmp_path)
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    prefs.job_dirs = [jobs_dir]
    card = {"surah_num": 25, "from_ayah": 7, "to_ayah": 11, "start_time": 0.0, "end_time": 5.0}
    project = Project(audio=jobs_dir / "lesson.m4a", mode="recitation", cards=[card])
    save_project(project, jobs_dir / "lesson_recitation.qalun.json")

    main = MainWindow(prefs=prefs)
    main.resize(1024, 680)
    main.show()
    wait_until_listed(main.job_list)
    main.job_list.set_running("recitation.m4a", i18n.t("home.progress.starting"))
    main.new_job.set_running(True)
    main._on_progress(ProgressEvent("render", "Building ASS subtitles..."))
    main._on_progress(ProgressEvent("render", "  Segments 4/10", fraction=0.4, eta_seconds=125))
    main._on_progress(ProgressEvent("export", "Writing subtitle files..."))

    menus: list[list[str]] = []

    class RecordingMenu(job_list_module.QMenu):
        def exec(self, *args):  # noqa: A003 - Qt's name
            menus.append([action.text() for action in self.actions()])
            return None

    monkeypatch.setattr(job_list_module, "QMenu", RecordingMenu)
    listing = main.job_list.list
    job_row = next(
        listing.item(i)
        for i in range(listing.count())
        if listing.item(i).data(Qt.ItemDataRole.UserRole) is not None
    )
    main.job_list._on_context_menu(listing.visualItemRect(job_row).center())
    assert menus and len(menus[0]) == 2, "the job's context menu was not shown"

    fixture_words = set(_LATIN_WORD.findall(str(tmp_path)))
    fixture_words |= {"jobs", "lesson", "m4a", "recitation", "missing", "mp3", "m", "Hello"}
    allowed = _LATIN_THE_TABLE_KEEPS | fixture_words
    roots = (main, review_window, review_window._make_export_dialog(), lecture_review_window)
    for root in roots:
        shown = [*_shown(root), *(text for menu in menus for text in menu)]
        latin = {word for text in shown for word in _LATIN_WORD.findall(text)} - allowed
        assert not latin, (root, sorted(latin))


@pytest.mark.parametrize(
    ("stage", "message"),
    [
        ("render", "Building ASS subtitles..."),
        ("detect", "[1/3] Parsing Quran text: /home/k/quran.txt"),
        ("export", "Writing subtitle files..."),
        ("match", "Scanning 12,345 transcript words for Quran citations..."),
    ],
)
def test_the_pipeline_s_english_never_reaches_the_arabic_status_line(
    qt_app, tmp_path, no_default_job_dirs, stage, message
) -> None:
    """Spec §4: every word a person reads comes from the table, progress included."""
    import re

    from qurantext.gui.main_window import MainWindow
    from qurantext.utils.progress import ProgressEvent

    main = MainWindow(prefs=_prefs(tmp_path))
    main._on_progress(ProgressEvent(stage=stage, message=message, fraction=None))
    text = main.new_job.status_label.text()
    assert text == i18n.t(f"job.stage.{stage}")
    assert not re.search("[A-Za-z]", text), text


@pytest.mark.parametrize("language", ["en", "ar"])
def test_a_path_s_folders_read_left_to_right_in_either_language(qt_app, language) -> None:
    """Two Arabic folder names must not swap places, in an English or an Arabic sentence."""
    from tests.bidi_helpers import left_to_right

    i18n.set_language(language)
    path = "/home/k/دروس/تلاوة.mp4"
    parts = ["home", "k/", "دروس", "تلاوة", "mp4"]
    for key in (
        "main.saved",
        "home.finished.rendered",
        "render.done",
        "home.output_dir.custom",
        "home.quran_override.custom",
        "review.audio_missing",
    ):
        line = i18n.t(key, path=i18n.path_text(path))
        assert left_to_right(line, parts, rtl=language == "ar") == parts, (key, line)


def test_the_windows_show_every_path_through_path_text(
    qt_app, tmp_path, store, no_default_job_dirs, review_window
) -> None:
    """The call sites use the helper, not ``str(path)``."""
    from qurantext.gui.main_window import MainWindow

    folder = tmp_path / "فيديو"
    folder.mkdir()
    quran = folder / "quran.txt"
    shutil.copyfile(QURAN_FILE, quran)
    prefs = _prefs(tmp_path)
    prefs.quran_override = quran
    panel = NewJobPanel(prefs, quran_default=QURAN_FILE, db_path=store)
    assert i18n.path_text(quran.resolve()) in panel.quran_label.text()
    panel.set_output_dir(folder)
    assert i18n.path_text(folder) in panel.output_label.text()
    audio = folder / "تلاوة.mp3"
    audio.touch()
    panel.set_audio(audio)
    assert panel.drop_label.text().splitlines()[1] == i18n.path_text(folder)

    main = MainWindow(prefs=_prefs(tmp_path))
    main._review_saved(audio)
    assert i18n.path_text(audio) in main.new_job.status_label.text()

    missing = review_window._audio
    assert any(i18n.path_text(missing) in notice for notice in review_window.warnings._notices)


def test_a_job_row_isolates_each_part_of_its_detail_line(
    qt_app, tmp_path, no_default_job_dirs
) -> None:
    """Mode, scope and status are each their own run, so "25:7–8" is not reordered."""
    prefs = _prefs(tmp_path)
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    prefs.job_dirs = [jobs_dir]
    card = {"surah_num": 25, "from_ayah": 7, "to_ayah": 8, "start_time": 0.0, "end_time": 5.0}
    project = Project(audio=jobs_dir / "one.m4a", mode="recitation", cards=[card])
    save_project(project, jobs_dir / "one_recitation.qalun.json")

    panel = JobListPanel(prefs)
    wait_until_listed(panel)
    detail = panel.list.itemWidget(panel.list.item(0)).detail_label.text()
    assert detail == i18n.t(
        "home.row_detail",
        mode=i18n.t("home.mode.recitation"),
        scope="25:7\u20138",
        status=i18n.t("home.status.needs_review"),
    )
    assert detail.count("\u2068") == 3


def test_a_job_row_starts_from_the_right_whatever_its_name_is_written_in(
    qt_app, tmp_path, no_default_job_dirs
) -> None:
    """A Latin job name lines up with its Arabic detail line, at the list's right edge."""
    prefs = _prefs(tmp_path)
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    prefs.job_dirs = [jobs_dir]
    project = Project(audio=jobs_dir / "lesson.m4a", mode="recitation", cards=[])
    save_project(project, jobs_dir / "lesson_recitation.qalun.json")

    panel = JobListPanel(prefs)
    wait_until_listed(panel)
    panel.set_running("recitation.m4a", i18n.t("home.progress.starting"))
    rows = [panel.list.itemWidget(panel.list.item(i)) for i in range(2)]
    for label in (rows[0].label, rows[1].name_label, rows[1].detail_label):
        alignment = label.alignment()
        assert alignment & Qt.AlignmentFlag.AlignAbsolute, label.text()
        assert alignment & Qt.AlignmentFlag.AlignRight, label.text()


def test_the_running_row_isolates_the_file_name(qt_app, tmp_path, no_default_job_dirs) -> None:
    """A Latin file name first would otherwise lay the whole Arabic line out left to right."""
    panel = JobListPanel(_prefs(tmp_path))
    starting = i18n.t("home.progress.starting")
    panel.set_running("recitation.m4a", starting)
    text = panel.list.itemWidget(panel.list.item(0)).label.text()
    assert text == i18n.t("home.running_row", name="recitation.m4a", progress=starting)
    assert "\u2068recitation.m4a\u2069" in text


# --- what the reader sees: the order Qt draws each part in ------------------------
# Each line is laid out in the direction a label takes from its own text, so a
# table edit that drops an isolate or the leading RLM changes the order and fails.


def test_a_job_detail_line_reads_mode_scope_status_from_the_right(
    qt_app, tmp_path, no_default_job_dirs
) -> None:
    from tests.bidi_helpers import left_to_right

    prefs = _prefs(tmp_path)
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    prefs.job_dirs = [jobs_dir]
    card = {"surah_num": 25, "from_ayah": 7, "to_ayah": 11, "start_time": 0.0, "end_time": 5.0}
    project = Project(audio=jobs_dir / "one.m4a", mode="recitation", cards=[card])
    save_project(project, jobs_dir / "one_recitation.qalun.json")

    panel = JobListPanel(prefs)
    wait_until_listed(panel)
    line = panel.list.itemWidget(panel.list.item(0)).detail_label.text()
    mode, status = i18n.t("home.mode.recitation"), i18n.t("home.status.needs_review")
    # From the left: the status, then 25:7–11 left to right, then the mode at the right edge.
    assert left_to_right(line, [mode, "25", "11", status]) == [status, "25", "11", mode]


def test_the_selection_line_reads_word_then_times_in_order(qt_app) -> None:
    from qurantext.gui.i18n import time_span
    from tests.bidi_helpers import left_to_right

    word = _AYAH_WORDS[0]
    line = i18n.t("review.selected", word=word, span=time_span(2.81, 4.03, sep=" \u2192 "))
    assert left_to_right(line, [word, "2.81", "4.03", "ث"]) == [
        "ث",
        "2.81",
        "4.03",
        word,
    ]


def test_a_gap_line_keeps_its_start_before_its_end(qt_app) -> None:
    from qurantext.gui.i18n import time_span
    from tests.bidi_helpers import left_to_right

    line = i18n.t("review.gap", duration=0.5, span=time_span(16.8, 23.0, digits=1))
    # Read from the right: 0.5 s at 16.8–23.0 s; the range itself runs left to right.
    assert left_to_right(line, ["0.5", "عند", "16.8", "23.0"]) == [
        "16.8",
        "23.0",
        "عند",
        "0.5",
    ]


def test_a_preset_keeps_width_before_height(qt_app) -> None:
    """A combo item is laid out in the combo's direction, right to left here."""
    from tests.bidi_helpers import left_to_right

    line = i18n.t("preset.social")
    assert left_to_right(line, ["عمودي", "1080", "1920", "30", "إطارًا"], rtl=True) == [
        "إطارًا",
        "30",
        "1080",
        "1920",
        "عمودي",
    ]


def test_the_rate_reads_number_then_times_sign(qt_app) -> None:
    """A combo item too: without its isolate an RTL combo draws "×1.5"."""
    from tests.bidi_helpers import left_to_right

    assert left_to_right(i18n.t("review.rate", rate=1.5), ["×", "1.5"], rtl=True) == ["1.5", "×"]


def test_the_arabic_review_title_keeps_the_name_in_place_without_isolates(
    qt_app, review_window
) -> None:
    """Some title bars draw isolate controls as boxes; an LRM keeps the Latin name in place."""
    title = review_window.windowTitle()
    assert not any(c in title for c in "\u2066\u2067\u2068\u2069")
    assert title == "مراجعة — \u200emissing\u200e"

"""The home window's remembered choices, over an injectable QSettings."""

from __future__ import annotations

from pathlib import Path

import pytest

from qurantext.gui.prefs import Prefs


@pytest.fixture()
def settings(tmp_path):
    from PySide6.QtCore import QSettings

    return QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)


def test_defaults_on_an_empty_ini(settings) -> None:
    prefs = Prefs(settings)
    assert prefs.mode == "recitation"
    assert prefs.preset == "social"
    assert prefs.subtitles == "burn"
    assert prefs.formats == ("srt",)
    assert prefs.render_right_away is False
    assert prefs.output_dir is None
    assert prefs.quran_override is None
    assert prefs.more_options_open is False
    assert prefs.hidden_jobs == set()
    assert prefs.job_dirs == []
    assert (prefs.surah_num, prefs.from_ayah, prefs.to_ayah) == (None, None, None)


def test_every_key_round_trips(tmp_path) -> None:
    from PySide6.QtCore import QSettings

    path = str(tmp_path / "prefs.ini")
    written = Prefs(QSettings(path, QSettings.Format.IniFormat))
    written.mode = "lecture"
    written.preset = "high"
    written.subtitles = "both"
    written.formats = ("srt", "vtt", "ass")
    written.render_right_away = True
    written.output_dir = tmp_path / "out"
    written.quran_override = tmp_path / "quran.txt"
    written.more_options_open = True
    written.hide_job(tmp_path / "a.qalun.json")
    written.hide_job(tmp_path / "b.qalun.json")
    written.job_dirs = [tmp_path / "extra1", tmp_path / "extra2"]
    written.surah_num, written.from_ayah, written.to_ayah = 25, 7, 11

    reread = Prefs(QSettings(path, QSettings.Format.IniFormat))
    assert reread.mode == "lecture"
    assert reread.preset == "high"
    assert reread.subtitles == "both"
    assert reread.formats == ("srt", "vtt", "ass")
    assert reread.render_right_away is True
    assert reread.output_dir == (tmp_path / "out").resolve()
    assert reread.quran_override == (tmp_path / "quran.txt").resolve()
    assert reread.more_options_open is True
    assert reread.hidden_jobs == {
        (tmp_path / "a.qalun.json").resolve(),
        (tmp_path / "b.qalun.json").resolve(),
    }
    # Setting job_dirs directly replaces the list — including what setting
    # output_dir added earlier — so only the two set last are there.
    assert reread.job_dirs == [(tmp_path / "extra1").resolve(), (tmp_path / "extra2").resolve()]
    assert (reread.surah_num, reread.from_ayah, reread.to_ayah) == (25, 7, 11)


@pytest.mark.parametrize(
    ("key", "raw_ini", "expected"),
    [
        ("mode", "mode=sideways\n", "recitation"),
        ("preset", "preset=cinema\n", "social"),
        ("subtitles", "subtitles=karaoke\n", "burn"),
        ("formats", "formats=docx\n", ("srt",)),
        ("render_right_away", "render_right_away=maybe\n", False),
        ("more_options_open", "more_options_open=maybe\n", False),
        ("output_dir", "output_dir=\n", None),
        ("surah_num", "surah_num=abc\n", None),
        ("surah_num", "surah_num=115\n", None),
        ("from_ayah", "from_ayah=0\n", None),
        ("to_ayah", "to_ayah=-3\n", None),
    ],
)
def test_invalid_stored_values_read_back_as_defaults(tmp_path, key, raw_ini, expected) -> None:
    from PySide6.QtCore import QSettings

    path = tmp_path / "prefs.ini"
    path.write_text(f"[General]\n{raw_ini}")
    prefs = Prefs(QSettings(str(path), QSettings.Format.IniFormat))
    assert getattr(prefs, key) == expected


def test_a_single_stored_format_still_reads_as_a_tuple(tmp_path) -> None:
    """A one-item list round-trips through a plain INI file as a bare string."""
    from PySide6.QtCore import QSettings

    path = tmp_path / "prefs.ini"
    path.write_text("[General]\nformats=srt\n")
    prefs = Prefs(QSettings(str(path), QSettings.Format.IniFormat))
    assert prefs.formats == ("srt",)


def test_a_single_hidden_job_still_reads_as_a_set(tmp_path) -> None:
    path = tmp_path / "prefs.ini"
    target = tmp_path / "a.qalun.json"
    path.write_text(f"[General]\nhidden_jobs={target}\n")
    from PySide6.QtCore import QSettings

    prefs = Prefs(QSettings(str(path), QSettings.Format.IniFormat))
    assert prefs.hidden_jobs == {target.resolve()}


def test_a_single_job_dir_still_reads_as_a_list(tmp_path) -> None:
    path = tmp_path / "prefs.ini"
    target = tmp_path / "extra"
    path.write_text(f"[General]\njob_dirs={target}\n")
    from PySide6.QtCore import QSettings

    prefs = Prefs(QSettings(str(path), QSettings.Format.IniFormat))
    assert prefs.job_dirs == [target.resolve()]


def test_setting_the_output_folder_adds_it_to_job_dirs_once(settings) -> None:
    prefs = Prefs(settings)
    folder = Path("/tmp/does-not-need-to-exist")
    prefs.output_dir = folder
    assert prefs.job_dirs.count(folder.resolve()) == 1
    prefs.output_dir = folder
    assert prefs.job_dirs.count(folder.resolve()) == 1


def test_clearing_the_output_folder_leaves_job_dirs_alone(settings) -> None:
    prefs = Prefs(settings)
    folder = Path("/tmp/does-not-need-to-exist")
    prefs.output_dir = folder
    prefs.output_dir = None
    assert prefs.output_dir is None
    assert folder.resolve() in prefs.job_dirs


def test_hide_and_unhide_a_job(settings) -> None:
    prefs = Prefs(settings)
    job = Path("/tmp/some/job.qalun.json")
    prefs.hide_job(job)
    assert job.resolve() in prefs.hidden_jobs
    prefs.unhide_job(job)
    assert job.resolve() not in prefs.hidden_jobs


def test_unhiding_a_job_that_was_never_hidden_is_fine(settings) -> None:
    prefs = Prefs(settings)
    prefs.unhide_job(Path("/tmp/never/hidden.qalun.json"))
    assert prefs.hidden_jobs == set()


def test_the_language_follows_the_system_until_one_is_chosen(tmp_path) -> None:
    from PySide6.QtCore import QSettings

    path = str(tmp_path / "prefs.ini")
    assert Prefs(QSettings(path, QSettings.Format.IniFormat)).language is None

    Prefs(QSettings(path, QSettings.Format.IniFormat)).language = "ar"
    assert Prefs(QSettings(path, QSettings.Format.IniFormat)).language == "ar"

    Prefs(QSettings(path, QSettings.Format.IniFormat)).language = None
    assert Prefs(QSettings(path, QSettings.Format.IniFormat)).language is None


def test_an_unknown_stored_language_follows_the_system(tmp_path) -> None:
    from PySide6.QtCore import QSettings

    path = tmp_path / "prefs.ini"
    path.write_text("[General]\nlanguage=klingon\n")
    assert Prefs(QSettings(str(path), QSettings.Format.IniFormat)).language is None


def test_only_a_known_language_can_be_chosen(settings) -> None:
    with pytest.raises(ValueError):
        Prefs(settings).language = "klingon"

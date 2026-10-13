"""The Settings dialog: five tabs, every control writes prefs as it changes."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from qurantext.gui import theme  # noqa: E402
from qurantext.gui.home.settings_dialog import TABS, SettingsDialog  # noqa: E402
from qurantext.gui.i18n import path_text, t  # noqa: E402
from tests.media_helpers import QURAN_FILE  # noqa: E402


@pytest.fixture()
def dialog(qt_app, prefs, tmp_path):
    theme.apply_theme(qt_app, "light")
    made = SettingsDialog(prefs, quran_default=QURAN_FILE)
    yield made
    made.deleteLater()


def test_it_has_five_tabs_and_opens_on_the_one_asked_for(qt_app, prefs) -> None:
    dialog = SettingsDialog(prefs, quran_default=QURAN_FILE, tab="transcription")
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == [
        t(f"settings.tab.{name}") for name in TABS
    ]
    assert dialog.current_tab() == "transcription"
    assert dialog.windowTitle().strip("\u200e\u200f") == t("settings.title")
    dialog.deleteLater()


def test_general_asks_for_language_and_theme_through_signals(dialog, prefs) -> None:
    languages, themes = [], []
    dialog.language_requested.connect(languages.append)
    dialog.theme_requested.connect(themes.append)
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("ar"))
    dialog.language_combo.activated.emit(dialog.language_combo.currentIndex())
    assert languages == ["ar"]
    dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData("dark"))
    dialog.theme_combo.activated.emit(dialog.theme_combo.currentIndex())
    assert themes == ["dark"]
    assert prefs.theme == "dark"  # the dialog writes it; the window applies it


def test_a_refused_language_snaps_back_and_says_why(dialog) -> None:
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("ar"))
    dialog.language_refused("busy")
    assert dialog.language_combo.currentData() == "en"
    assert dialog.language_note.text() == "busy"


def test_transcription_engine_round_trips_and_notes_a_missing_token(
    dialog, prefs, monkeypatch
) -> None:
    from qurantext.gui.home import settings_dialog as module

    monkeypatch.setattr(module, "_token_missing", lambda: True)
    assert dialog.engine_buttons["local"].isChecked()
    dialog.engine_buttons["whisperx"].setChecked(True)
    assert prefs.engine == "whisperx"
    # isHidden, not isVisibleTo: a tab that is not the current one is hidden as a whole.
    assert not dialog.no_token_label.isHidden()
    assert ".env" in dialog.no_token_label.text()
    assert path_text(module.env_dir()) in dialog.no_token_label.text()
    dialog.engine_buttons["local"].setChecked(True)
    assert dialog.no_token_label.isHidden()


def test_files_quran_and_output_round_trip_and_flag_the_change(dialog, prefs, tmp_path) -> None:
    assert dialog.changed_files is False
    custom = tmp_path / "my.txt"
    custom.write_text("x", encoding="utf-8")
    dialog.set_quran(custom)
    assert prefs.quran_override == custom and dialog.changed_files
    assert path_text(custom) in dialog.quran_label.text()
    dialog.set_quran(None)
    assert prefs.quran_override is None
    assert dialog.quran_label.text() == t("home.quran_override.default")
    dialog.set_output_dir(tmp_path)
    assert prefs.output_dir == tmp_path
    dialog.set_output_dir(None)
    assert dialog.output_label.text() == t("home.output_dir.default")


def test_a_quran_override_that_is_gone_falls_back_to_the_default(dialog, prefs, tmp_path) -> None:
    prefs.quran_override = tmp_path / "gone.txt"
    again = SettingsDialog(prefs, quran_default=QURAN_FILE)
    assert again.quran_label.text() == t("home.quran_override.default")
    assert prefs.quran_override == tmp_path / "gone.txt"  # kept for when the drive is back
    again.deleteLater()


def test_job_folders_list_add_and_remove(dialog, prefs, tmp_path, monkeypatch) -> None:
    """Review Focus 1: a folder that is not there is still listed, with Remove."""
    gone = tmp_path / "unplugged"
    prefs.job_dirs = [gone]
    again = SettingsDialog(prefs, quran_default=QURAN_FILE)
    assert (
        again.job_dirs_list.count() == 1 and path_text(gone) in again.job_dirs_list.item(0).text()
    )
    from qurantext.gui.home import settings_dialog as module

    monkeypatch.setattr(module.QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    again.add_dir_button.click()
    assert prefs.job_dirs == [gone, tmp_path] and again.changed_files
    again.job_dirs_list.setCurrentRow(0)
    again.remove_dir_button.click()
    assert prefs.job_dirs == [tmp_path]
    again.deleteLater()


def test_videos_shows_and_resets_the_default_look_and_clears_the_episode(dialog, prefs) -> None:
    from qurantext.core.looks import NIGHT_GOLD, PRESETS

    assert t("look.preset.night_gold") in dialog.look_label.text()
    prefs.save_default_look(PRESETS["sand"])
    again = SettingsDialog(prefs, quran_default=QURAN_FILE)
    assert t("look.preset.sand") in again.look_label.text()
    again.look_reset_button.click()
    assert prefs.default_look == NIGHT_GOLD
    assert again.intro_label.text() == t("settings.episode.none")
    assert not again.intro_clear_button.isEnabled()
    again.deleteLater()


def test_about_names_the_version_and_links_the_log_folder(dialog, monkeypatch, tmp_path) -> None:
    import qurantext
    from qurantext.gui.home import settings_dialog as module

    assert qurantext.__version__ in dialog.version_label.text()
    opened = []
    monkeypatch.setattr(module, "open_folder", lambda folder: opened.append(folder) or True)
    dialog.log_link.linkActivated.emit("logs")
    assert opened and opened[0].name == "logs"
    assert dialog.github_link.text().count("github.com") == 1


def test_clearing_a_generated_intro_keeps_the_outro(qt_app, prefs) -> None:
    from qurantext.gui.prefs import KEEP_DEFAULT
    from qurantext.jobs.episode_assets import GeneratedIntro, GeneratedOutro

    prefs.save_default_episode(
        KEEP_DEFAULT,
        KEEP_DEFAULT,
        intro_generated=GeneratedIntro(name="Channel"),
        outro_generated=GeneratedOutro(),
    )
    dialog = SettingsDialog(prefs, quran_default=QURAN_FILE)
    assert dialog.intro_label.text() == t("settings.episode.generated")
    assert dialog.intro_clear_button.isEnabled()
    dialog.intro_clear_button.click()
    assert prefs.default_episode_kinds == ("none", "generated")
    assert dialog.intro_label.text() == t("settings.episode.none")
    assert not dialog.intro_clear_button.isEnabled()
    assert dialog.outro_label.text() == t("settings.episode.generated")
    dialog.deleteLater()

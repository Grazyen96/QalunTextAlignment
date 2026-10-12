"""The home window's remembered choices, over an injectable QSettings."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from qurantext.gui.prefs import Prefs


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


def test_engine_defaults_to_local_and_round_trips(settings) -> None:
    prefs = Prefs(settings)
    assert prefs.engine == "local"
    prefs.engine = "whisperx"
    assert Prefs(settings).engine == "whisperx"


def test_an_unknown_stored_engine_reads_as_local(settings) -> None:
    settings.setValue("engine", "cohere")
    assert Prefs(settings).engine == "local"


def test_a_saved_choice_of_the_retired_bundled_text_reads_as_the_default(
    settings, tmp_path
) -> None:
    """An older version bundled Ver05; choosing it saved its absolute path.

    After the update that file is gone, so the saved choice reads as no
    override and the bundled v10 text is used. A choice of any other missing
    file is kept, as before (it may be on a drive that is not plugged in).
    """
    gone = tmp_path / "Qalun" / "_internal" / "qurantext" / "assets" / "quran"
    gone = gone / "UthmanicQaloon1-Ver05.txt"
    settings.setValue("quran_override", str(gone))
    assert Prefs(settings).quran_override is None

    elsewhere = tmp_path / "usb" / "UthmanicQaloon1-Ver05.txt"
    settings.setValue("quran_override", str(elsewhere))
    assert Prefs(settings).quran_override == elsewhere.resolve()


# -- the default look -----------------------------------------------------------


def test_default_look_starts_as_night_gold(settings) -> None:
    from qurantext.core.looks import NIGHT_GOLD

    prefs = Prefs(settings)
    assert prefs.default_look == NIGHT_GOLD
    assert prefs.default_look_style() == {}


def test_default_look_round_trips(tmp_path) -> None:
    from PySide6.QtCore import QSettings

    from qurantext.core.looks import PRESETS

    path = str(tmp_path / "prefs.ini")
    stored = Prefs(QSettings(path, QSettings.Format.IniFormat)).save_default_look(PRESETS["ocean"])
    assert stored == PRESETS["ocean"]
    read = Prefs(QSettings(path, QSettings.Format.IniFormat))
    assert read.default_look == PRESETS["ocean"]
    assert read.default_look_style() == PRESETS["ocean"].to_dict()


def test_the_default_look_setter_saves_it(settings) -> None:
    from qurantext.core.looks import PRESETS

    prefs = Prefs(settings)
    prefs.default_look = PRESETS["sand"]
    assert prefs.default_look == PRESETS["sand"]


def test_choosing_night_gold_again_gives_new_jobs_no_style(settings) -> None:
    from qurantext.core.looks import NIGHT_GOLD, PRESETS

    prefs = Prefs(settings)
    prefs.save_default_look(PRESETS["sand"])
    prefs.save_default_look(NIGHT_GOLD)
    assert prefs.default_look == NIGHT_GOLD
    assert prefs.default_look_style() == {}


def test_a_default_image_is_copied_into_the_app_data(settings, tmp_path, monkeypatch) -> None:
    from dataclasses import replace

    from PIL import Image

    from qurantext.core.looks import NIGHT_GOLD, Background

    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    src = tmp_path / "bg.png"
    Image.new("RGB", (4, 4)).save(src)
    look = replace(
        NIGHT_GOLD,
        background=Background("image", (0, 0, 0, 255), (0, 0, 0, 255), src, 0.35, 0),
    )
    prefs = Prefs(settings)
    stored = prefs.save_default_look(look)
    assert stored.background.image.parent == (tmp_path / "data" / "looks").resolve()
    assert stored.background.image.read_bytes() == src.read_bytes()
    src.unlink()  # the person's original photo going away does not lose the default
    assert prefs.default_look.background.image == stored.background.image
    assert prefs.default_look.background.image.is_file()
    assert Path(prefs.default_look_style()["background"]["image"]).is_absolute()


def test_junk_in_settings_is_night_gold(settings) -> None:
    from qurantext.core.looks import NIGHT_GOLD

    prefs = Prefs(settings)
    for junk in ("{not json", "[1, 2]", "7", "null"):
        settings.setValue("default_look", junk)
        assert prefs.default_look == NIGHT_GOLD, junk


def test_default_episode_round_trips_and_copies_into_app_data(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    prefs = Prefs(settings)
    clip = tmp_path / "intro.mp4"
    clip.write_bytes(b"x" * 10)
    prefs.save_default_episode(clip, None)
    intro, outro = prefs.default_episode
    assert intro.parent == (tmp_path / "data" / "episode").resolve() and outro is None
    prefs.save_default_episode(None, None)
    assert prefs.default_episode == (None, None)


def test_junk_default_episode_is_none(settings):
    settings.setValue("default_episode", "{not json")
    assert Prefs(settings).default_episode == (None, None)


@pytest.mark.parametrize(
    "stored",
    [
        "[1, 2]",
        '{"intro": 3, "outro": null}',
        '{"intro": "relative/intro.mp4"}',
        '{"intro": "/abs/not-a-clip.txt"}',
    ],
)
def test_a_default_episode_of_the_wrong_shape_is_none(settings, stored):
    settings.setValue("default_episode", stored)
    assert Prefs(settings).default_episode == (None, None)


def test_a_default_episode_that_cannot_be_copied_stores_nothing(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    prefs = Prefs(settings)
    kept = tmp_path / "outro.mov"
    kept.write_bytes(b"outro")
    prefs.save_default_episode(None, kept)
    before = prefs.default_episode

    with pytest.raises(FileNotFoundError):
        prefs.save_default_episode(tmp_path / "gone.mp4", None)
    with pytest.raises(ValueError):
        prefs.save_default_episode(tmp_path / "notes.txt", None)
    assert prefs.default_episode == before and before[1] is not None
    assert before[1].read_bytes() == b"outro"


def test_a_replaced_default_clip_is_removed_from_app_data(settings, tmp_path, monkeypatch):
    """Intros can be large; trying a few must not leave every one behind."""
    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    prefs = Prefs(settings)
    first, second, outro = (tmp_path / n for n in ("one.mp4", "two.mp4", "end.mov"))
    first.write_bytes(b"first intro")
    second.write_bytes(b"second intro")
    outro.write_bytes(b"outro")
    folder = tmp_path / "data" / "episode"

    prefs.save_default_episode(first, outro)
    prefs.save_default_episode(second, prefs.default_episode[1])
    intro, kept_outro = prefs.default_episode
    assert sorted(p.read_bytes() for p in folder.iterdir()) == [b"outro", b"second intro"]
    assert intro.read_bytes() == b"second intro" and kept_outro.read_bytes() == b"outro"

    prefs.save_default_episode(None, None)
    assert list(folder.iterdir()) == []


def test_a_default_clip_a_running_job_holds_is_kept_until_it_ends(settings, tmp_path, monkeypatch):
    """A new lecture's matching copies the default intro beside it only when it ends.

    Choosing another default meanwhile must not delete the one that job was
    started with; it goes once the job lets go of it.
    """
    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    prefs = Prefs(settings)
    first, second = tmp_path / "one.mp4", tmp_path / "two.mp4"
    first.write_bytes(b"first intro")
    second.write_bytes(b"second intro")
    prefs.save_default_episode(first, None)
    held = prefs.default_episode

    release = prefs.hold_default_clips(held)
    prefs.save_default_episode(second, None)
    assert held[0].read_bytes() == b"first intro", "deleted under the running job"
    assert prefs.default_episode[0].read_bytes() == b"second intro"

    release()
    assert not held[0].exists(), "let go once the job ended"
    assert prefs.default_episode[0].read_bytes() == b"second intro"
    release()  # a second release changes nothing


def test_a_held_clip_that_is_still_the_default_stays(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    prefs = Prefs(settings)
    clip = tmp_path / "one.mp4"
    clip.write_bytes(b"intro")
    prefs.save_default_episode(clip, None)
    release = prefs.hold_default_clips(prefs.default_episode)
    release()
    assert prefs.default_episode[0].read_bytes() == b"intro"
    folder = tmp_path / "data" / "episode"
    before = sorted(folder.iterdir())
    prefs.hold_default_clips((None, None))()  # holding nothing lets go of nothing
    assert sorted(folder.iterdir()) == before


def test_a_default_part_can_be_kept_while_the_other_changes(settings, tmp_path, monkeypatch):
    """The Episode dialog changes only the part the person changed."""
    from qurantext.gui.prefs import KEEP_DEFAULT

    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    prefs = Prefs(settings)
    intro, outro = tmp_path / "Channel intro.mp4", tmp_path / "end.mov"
    intro.write_bytes(b"intro")
    outro.write_bytes(b"outro")
    prefs.save_default_episode(intro, None)
    kept = prefs.default_episode[0]
    intro.unlink()  # the original going away does not matter: the copy is kept

    prefs.save_default_episode(KEEP_DEFAULT, outro, names=(None, "Outro 2024.mov"))
    assert prefs.default_episode[0] == kept and kept.read_bytes() == b"intro"
    assert prefs.default_episode_names == ("Channel intro.mp4", "Outro 2024.mov")
    prefs.save_default_episode(None, KEEP_DEFAULT)
    assert prefs.default_episode[0] is None and prefs.default_episode_names[0] is None
    assert prefs.default_episode_names[1] == "Outro 2024.mov"


@pytest.mark.parametrize("name", [3, "", "  ", None])
def test_a_default_name_of_the_wrong_shape_is_unknown(settings, name):
    import json

    settings.setValue(
        "default_episode", json.dumps({"intro": "/abs/intro.mp4", "intro_name": name})
    )
    prefs = Prefs(settings)
    assert prefs.default_episode[0] == Path("/abs/intro.mp4")
    assert prefs.default_episode_names == (None, None)


# --- generated intro and outro defaults -------------------------------------------


def test_generated_defaults_round_trip(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    from qurantext.jobs.episode_assets import GeneratedIntro, GeneratedOutro

    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    path = str(tmp_path / "prefs.ini")
    intro = GeneratedIntro(name="دروس الشيخ أحمد", style="rise", seconds=4.5)
    outro = GeneratedOutro(phrase="بارك الله فيكم", link="example.org/dars", platform="whatsapp")
    written = Prefs(QSettings(path, QSettings.Format.IniFormat))
    assert written.default_intro_generated is None and written.default_outro_generated is None
    assert written.default_episode_kinds == ("none", "none")
    written.save_default_episode(None, None, intro_generated=intro, outro_generated=outro)

    prefs = Prefs(QSettings(path, QSettings.Format.IniFormat))  # a fresh process reads it back
    assert prefs.default_intro_generated == intro
    assert prefs.default_outro_generated == outro
    assert prefs.default_episode == (None, None)
    assert prefs.default_episode_kinds == ("generated", "generated")

    prefs.save_default_episode(None, None, intro_generated=None, outro_generated=None)
    assert prefs.default_intro_generated is None and prefs.default_outro_generated is None


def test_keep_default_leaves_generated_settings(settings, tmp_path, monkeypatch):
    from qurantext.gui.prefs import KEEP_DEFAULT
    from qurantext.jobs.episode_assets import GeneratedIntro, GeneratedOutro

    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    prefs = Prefs(settings)
    intro = GeneratedIntro(name="دروس")
    outro = GeneratedOutro(link="example.org", platform="telegram")
    prefs.save_default_episode(None, None, intro_generated=intro, outro_generated=outro)

    # Only the outro changed in the dialog: the intro's settings are left as they are.
    newer = GeneratedOutro(link="example.org/new", platform="facebook")
    prefs.save_default_episode(KEEP_DEFAULT, KEEP_DEFAULT, outro_generated=newer)
    assert prefs.default_intro_generated == intro
    assert prefs.default_outro_generated == newer

    # A change to neither part's settings, as the clip-only dialog makes, keeps both.
    prefs.save_default_episode(KEEP_DEFAULT, KEEP_DEFAULT)
    assert (prefs.default_intro_generated, prefs.default_outro_generated) == (intro, newer)

    # None for one part's settings removes them, and only them.
    prefs.save_default_episode(KEEP_DEFAULT, KEEP_DEFAULT, intro_generated=None)
    assert prefs.default_intro_generated is None
    assert prefs.default_outro_generated == newer


def test_a_generated_default_replaces_a_clip_default_for_that_part(settings, tmp_path, monkeypatch):
    from qurantext.gui.prefs import KEEP_DEFAULT
    from qurantext.jobs.episode_assets import GeneratedIntro, GeneratedOutro

    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    prefs = Prefs(settings)
    intro, outro = tmp_path / "intro.mp4", tmp_path / "outro.mov"
    intro.write_bytes(b"intro")
    outro.write_bytes(b"outro")
    prefs.save_default_episode(intro, outro, names=("Channel.mp4", None))
    copy = prefs.default_episode[0]
    assert copy.is_file()

    # Generated for the intro: its clip goes (from the settings and the app's folder);
    # the outro, not changed, keeps its clip.
    generated = GeneratedIntro(name="دروس")
    prefs.save_default_episode(KEEP_DEFAULT, KEEP_DEFAULT, intro_generated=generated)
    assert prefs.default_intro_generated == generated
    assert prefs.default_episode[0] is None and prefs.default_episode_names[0] is None
    assert prefs.default_episode[1] is not None
    assert prefs.default_episode_kinds == ("generated", "clip")
    assert not copy.exists(), "a clip no default names any more is removed"

    # And the reverse: a clip for the intro removes its generated settings.
    prefs.save_default_episode(intro, KEEP_DEFAULT)
    assert prefs.default_intro_generated is None and prefs.default_episode[0] is not None
    assert prefs.default_episode_kinds == ("clip", "clip")

    # None for a part's clip ends the part, generated settings and all.
    prefs.save_default_episode(KEEP_DEFAULT, KEEP_DEFAULT, outro_generated=GeneratedOutro())
    assert prefs.default_episode_kinds == ("clip", "generated")
    prefs.save_default_episode(KEEP_DEFAULT, None)
    assert prefs.default_episode_kinds == ("clip", "none")

    # A hand-edited file holding both for one part reads as generated, with no clip.
    import json

    stored = json.loads(settings.value("default_episode"))
    stored["intro_generated"] = {"name": "x"}
    settings.setValue("default_episode", json.dumps(stored))
    assert prefs.default_episode[0] is None
    assert prefs.default_intro_generated == GeneratedIntro(name="x")


@pytest.mark.parametrize("junk", ["fade", 3, ["x"], None])
def test_junk_generated_defaults_are_none(settings, junk):
    import json

    settings.setValue(
        "default_episode", json.dumps({"intro_generated": junk, "outro_generated": junk})
    )
    prefs = Prefs(settings)
    assert prefs.default_intro_generated is None and prefs.default_outro_generated is None
    assert prefs.default_episode_kinds == ("none", "none")


def test_settings_of_the_other_part_are_refused(settings, tmp_path, monkeypatch):
    from qurantext.gui.prefs import KEEP_DEFAULT
    from qurantext.jobs.episode_assets import GeneratedIntro, GeneratedOutro

    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    prefs = Prefs(settings)
    with pytest.raises(TypeError):
        prefs.save_default_episode(KEEP_DEFAULT, KEEP_DEFAULT, intro_generated=GeneratedOutro())
    with pytest.raises(TypeError):
        prefs.save_default_episode(KEEP_DEFAULT, KEEP_DEFAULT, outro_generated=GeneratedIntro())
    assert prefs.default_episode_kinds == ("none", "none"), "nothing was stored"


def test_generated_settings_are_remembered_apart_from_the_kind(settings, tmp_path, monkeypatch):
    """A part set to None or a clip keeps its name, phrase and link for Generated again."""
    from qurantext.gui.prefs import KEEP_DEFAULT
    from qurantext.jobs.episode_assets import GeneratedIntro, GeneratedOutro

    monkeypatch.setenv("QURANTEXT_DATA_DIR", str(tmp_path / "data"))
    prefs = Prefs(settings)
    assert prefs.remembered_outro_generated is None
    outro = GeneratedOutro(link="example.org/dars", platform="telegram")
    prefs.save_default_episode(KEEP_DEFAULT, KEEP_DEFAULT, outro_generated=outro)
    clip = tmp_path / "outro.mp4"
    clip.write_bytes(b"outro")
    prefs.save_default_episode(KEEP_DEFAULT, clip)
    assert prefs.default_episode_kinds == ("none", "clip")
    assert prefs.default_outro_generated is None and prefs.remembered_outro_generated == outro
    prefs.save_default_episode(KEEP_DEFAULT, None)
    assert prefs.default_episode_kinds == ("none", "none")
    assert prefs.remembered_outro_generated == outro

    # Remembered settings change without changing the kind…
    newer = GeneratedOutro(link="example.org/new", platform="telegram")
    prefs.save_default_episode(KEEP_DEFAULT, KEEP_DEFAULT, outro_remembered=newer)
    assert prefs.default_episode_kinds == ("none", "none")
    assert prefs.remembered_outro_generated == newer
    # …and a generated default follows them.
    intro = GeneratedIntro(name="دروس")
    prefs.save_default_episode(KEEP_DEFAULT, KEEP_DEFAULT, intro_generated=intro)
    prefs.save_default_episode(
        KEEP_DEFAULT, KEEP_DEFAULT, intro_remembered=GeneratedIntro(name="دروس", style="rise")
    )
    assert prefs.default_intro_generated == GeneratedIntro(name="دروس", style="rise")
    assert prefs.default_episode_kinds == ("generated", "none")
    with pytest.raises(TypeError):
        prefs.save_default_episode(KEEP_DEFAULT, KEEP_DEFAULT, intro_remembered=newer)

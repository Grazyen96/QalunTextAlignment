"""A lecture's generated intro and outro: the title read from its cards, the tracked
link, and the clip made once and reused until something it is made from changes."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from qurantext.core.looks import NIGHT_GOLD, PRESETS
from qurantext.jobs.episode import EpisodeError
from qurantext.jobs.episode_assets import GeneratedIntro, GeneratedOutro, episode_dir_for
from qurantext.jobs.generated_parts import (
    ensure_generated_part,
    intro_spec_for,
    outro_spec_for,
    title_for,
)
from qurantext.jobs.project import (
    JobSettings,
    Project,
    job_settings,
    save_project,
    set_job_settings,
)
from qurantext.utils.progress import CancelToken, JobCancelled


def _card(surah: int, first: int, last: int, start: float, **extra) -> dict:
    return {
        "surah_num": surah,
        "surah_name": "سُورَةُ الفُرقَانِ" if surah == 25 else f"سورة {surah}",
        "from_ayah": first,
        "to_ayah": last,
        "full_text": "وَقَالُواْ",
        "confidence": 0.9,
        "start_time": start,
        "end_time": start + 4.0,
        **extra,
    }


@pytest.fixture()
def lecture_project(tmp_path: Path) -> Project:
    """A saved lecture with cards 25:44 and 25:49, studying surah 25."""
    project = Project(
        audio=tmp_path / "dars.mp3",
        mode="lecture",
        cards=[_card(25, 44, 44, 0.0), _card(25, 49, 49, 10.0)],
    )
    set_job_settings(project, JobSettings(studied_surah=25))
    save_project(project, tmp_path / "dars.qalun.json")
    return project


def _studying(project: Project, surah: int | None) -> Project:
    set_job_settings(project, JobSettings(studied_surah=surah))
    return project


def _fake_render(monkeypatch) -> list[Path]:
    """Replace the clip maker with one that writes a byte and records where."""
    calls: list[Path] = []

    def render(spec, look, out, **kwargs):
        calls.append(out)
        out.write_bytes(b"x")
        return out

    monkeypatch.setattr("qurantext.jobs.generated_parts.render_title_clip", render)
    return calls


# --- the title --------------------------------------------------------------------


def test_title_reads_the_lectures_surah_and_range(lecture_project):
    text, surah, a, b = title_for(lecture_project, {25: "الفرقان"})
    assert (surah, a, b) == (25, 44, 49) and text == "سورة الفرقان، الآيات ٤٤–٤٩"


def test_the_stores_name_reads_plain_and_is_not_said_twice(lecture_project):
    text, *_ = title_for(lecture_project, {25: "سُورَةُ الفُرقَانِ"})
    assert text == "سورة الفرقان، الآيات ٤٤–٤٩"
    # Without the store, the cards' own surah name.
    assert title_for(lecture_project, {})[0] == "سورة الفرقان، الآيات ٤٤–٤٩"


def test_one_ayah_is_said_in_the_singular(lecture_project):
    lecture_project.cards = [_card(25, 7, 7, 0.0)]
    assert title_for(lecture_project, {25: "الفرقان"}) == ("سورة الفرقان، الآية ٧", 25, 7, 7)


def test_a_card_spanning_ayat_widens_the_range(lecture_project):
    lecture_project.cards = [_card(25, 63, 77, 0.0), _card(25, 61, 61, 9.0)]
    assert title_for(lecture_project, {25: "الفرقان"})[1:] == (25, 61, 77)


def test_without_ayat_the_title_is_the_surah_and_without_a_surah_nothing(lecture_project):
    # The studied surah has no card: its name alone.
    _studying(lecture_project, 25)
    lecture_project.cards = [_card(2, 255, 255, 0.0)]
    assert title_for(lecture_project, {25: "الفرقان"}) == ("سورة الفرقان", 25, None, None)
    # No name known at all: the surah by its number.
    assert title_for(lecture_project, {})[0] == "سورة ٢٥"
    # No surah chosen and no card: nothing.
    _studying(lecture_project, None)
    lecture_project.cards = []
    assert title_for(lecture_project, {}) == ("", None, None, None)


def _opening_card(project: Project) -> tuple[str, str] | None:
    """The lecture's own opening card, as the renderer draws it from these cards."""
    from qurantext.core.video_common import (
        cards_on_screen,
        lecture_intro_lines,
        validated_matches,
    )

    studied = job_settings(project).studied_surah
    shown = cards_on_screen(validated_matches(project.cards, bridge_gaps=False), "lecture", studied)
    return lecture_intro_lines(shown, studied)


def test_hand_made_cross_references_do_not_choose_the_surah(lecture_project):
    """Detected 25:44 and 25:49, and three hand-made cards of 2:255–257: the lecture is
    al-Furqan, as its opening card says, and so are the intro and the link's campaign."""
    _studying(lecture_project, None)
    lecture_project.cards = [
        _card(25, 44, 44, 0.0),
        _card(25, 49, 49, 10.0),
        _card(2, 255, 255, 20.0, manual=True),
        _card(2, 256, 256, 30.0, manual=True),
        _card(2, 257, 257, 40.0, manual=True),
    ]
    names = {2: "البقرة", 25: "الفرقان"}
    assert title_for(lecture_project, names) == ("سورة الفرقان، الآيات ٤٤–٤٩", 25, 44, 49)
    assert _opening_card(lecture_project) == (
        "سُورَةُ الفُرقَانِ",
        "تدبر الآيات من الآية 44 إلى الآية 49",
    )
    outro = outro_spec_for(lecture_project, GeneratedOutro(link="example.org/dars"), names)
    assert "utm_campaign=qalun-025-044-049" in outro.qr_url


def test_the_surah_heard_longest_is_the_lectures_when_none_is_chosen(lecture_project):
    """More cards of another surah do not outvote the one heard longest."""
    _studying(lecture_project, None)
    long = {"end_time": 60.0}
    lecture_project.cards = [
        _card(2, 255, 255, 0.0),
        _card(2, 256, 256, 5.0),
        _card(25, 63, 63, 10.0, **long),
        _card(2, 257, 257, 70.0),
    ]
    assert title_for(lecture_project, {})[1:] == (25, 63, 63)
    assert _opening_card(lecture_project)[1] == "تدبر الآية 63"


def test_when_every_card_is_hand_made_the_first_names_the_surah(lecture_project):
    """No detected card to guess from: the first hand-made card by time, as the opening card."""
    _studying(lecture_project, None)
    lecture_project.cards = [
        _card(2, 286, 286, 30.0, manual=True),
        _card(25, 63, 63, 10.0, manual=True),
        _card(25, 70, 70, 20.0, manual=True),
    ]
    assert title_for(lecture_project, {})[1:] == (25, 63, 70)
    assert _opening_card(lecture_project) == (
        "سُورَةُ الفُرقَانِ",
        "تدبر الآيات من الآية 63 إلى الآية 70",
    )


def test_a_card_the_video_cannot_draw_does_not_widen_the_range(lecture_project):
    lecture_project.cards = [*lecture_project.cards, _card(25, 77, 77, 30.0, end_time=30.0)]
    assert title_for(lecture_project, {})[1:] == (25, 44, 49)


def test_a_hand_made_card_of_the_studied_surah_widens_the_range(lecture_project):
    lecture_project.cards = [*lecture_project.cards, _card(25, 52, 52, 30.0, manual=True)]
    assert title_for(lecture_project, {})[1:] == (25, 44, 52)


# --- the specs --------------------------------------------------------------------


def test_the_intro_spec_carries_the_name_title_and_settings(lecture_project):
    settings = GeneratedIntro(name="  دروس   الشيخ أحمد ", style="reveal", seconds=7)
    spec = intro_spec_for(lecture_project, settings, {25: "الفرقان"})
    assert spec.name == "دروس الشيخ أحمد"
    assert spec.title == "سورة الفرقان، الآيات ٤٤–٤٩"
    assert (spec.style, spec.seconds, spec.rtl) == ("reveal", 7.0, True)


def test_the_reveal_edge_follows_the_texts_direction(lecture_project):
    latin = intro_spec_for(lecture_project, GeneratedIntro(name="Dars of Sheikh Ahmad"), {})
    assert latin.rtl is False, "a Latin name uncovers from the left"
    # A name with no letters leaves it to the title, which is Arabic.
    assert intro_spec_for(lecture_project, GeneratedIntro(name="2026"), {}).rtl is True
    assert outro_spec_for(lecture_project, GeneratedOutro(phrase="Thank you"), {}).rtl is False
    assert outro_spec_for(lecture_project, GeneratedOutro(), {}).rtl is True
    # A caller may say otherwise.
    assert intro_spec_for(lecture_project, GeneratedIntro(name="دروس"), {}, rtl=False).rtl is False


def test_outro_spec_carries_the_tracked_link(lecture_project):
    spec = outro_spec_for(
        lecture_project, GeneratedOutro(link="example.org/dars", platform="tiktok"), {}
    )
    assert spec.link_text == "example.org/dars"
    assert "utm_source=tiktok" in spec.qr_url and "utm_campaign=qalun-025-044-049" in spec.qr_url
    query = {k: v[0] for k, v in parse_qs(urlsplit(spec.qr_url).query).items()}
    assert query == {
        "utm_source": "tiktok",
        "utm_medium": "video",
        "utm_campaign": "qalun-025-044-049",
        "utm_content": "outro-qr",
    }
    assert spec.qr_url.startswith("https://example.org/dars?")
    assert spec.phrase == "جزاكم الله خيرًا"


def test_an_empty_link_means_no_qr(lecture_project):
    spec = outro_spec_for(lecture_project, GeneratedOutro(link=""), {})
    assert spec.qr_url is None and spec.link_text is None
    spec = outro_spec_for(lecture_project, GeneratedOutro(link="   "), {})
    assert spec.qr_url is None and spec.link_text is None


def test_a_malformed_link_is_refused(lecture_project):
    from qurantext.core.tracked_link import LinkError

    with pytest.raises(LinkError):
        outro_spec_for(lecture_project, GeneratedOutro(link="ftp://example.org"), {})


# --- the clip ---------------------------------------------------------------------


def test_the_part_is_reused_until_something_changes(lecture_project, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        "qurantext.jobs.generated_parts.render_title_clip",
        lambda spec, look, out, **k: (calls.append(out), out.write_bytes(b"x"))[1] or out,
    )
    spec = intro_spec_for(lecture_project, GeneratedIntro(name="دروس"), {})
    a = ensure_generated_part(
        lecture_project, "intro", spec, NIGHT_GOLD, width=640, height=360, fps=25
    )
    b = ensure_generated_part(
        lecture_project, "intro", spec, NIGHT_GOLD, width=640, height=360, fps=25
    )
    assert a == b and len(calls) == 1
    assert a.parent == episode_dir_for(lecture_project.path)
    assert a.name.startswith("generated-intro-") and len(a.stem) == len("generated-intro-") + 12
    ensure_generated_part(
        lecture_project, "intro", spec, PRESETS["sand"], width=640, height=360, fps=25
    )
    assert len(calls) == 2 and len(list(a.parent.glob("generated-intro-*.mp4"))) == 1


def test_a_platform_change_remakes_the_outro(lecture_project, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "qurantext.jobs.generated_parts.render_title_clip",
        lambda spec, look, out, **k: (calls.append((spec, out)), out.write_bytes(b"x"))[1] or out,
    )
    size = {"width": 1280, "height": 720, "fps": 30}
    youtube = outro_spec_for(
        lecture_project, GeneratedOutro(link="example.org/dars", platform="youtube"), {}
    )
    first = ensure_generated_part(lecture_project, "outro", youtube, NIGHT_GOLD, **size)
    again = ensure_generated_part(lecture_project, "outro", youtube, NIGHT_GOLD, **size)
    assert first == again and len(calls) == 1, "the same platform reuses the clip"

    telegram = outro_spec_for(
        lecture_project, GeneratedOutro(link="example.org/dars", platform="telegram"), {}
    )
    second = ensure_generated_part(lecture_project, "outro", telegram, NIGHT_GOLD, **size)
    assert len(calls) == 2 and second != first
    assert "utm_source=telegram" in calls[1][0].qr_url, "the new clip's code carries it"
    assert second.is_file() and not first.exists(), "the clip for the old platform is gone"
    assert list(second.parent.glob("generated-outro-*.mp4")) == [second]


def test_the_name_is_stable_across_runs_and_covers_size_and_rate(lecture_project, monkeypatch):
    from qurantext.jobs.generated_parts import generated_part_path

    spec = intro_spec_for(lecture_project, GeneratedIntro(name="دروس"), {})

    def path(**size):
        return generated_part_path(lecture_project.path, "intro", spec, NIGHT_GOLD, **size)

    base = path(width=1280, height=720, fps=30)
    # A sha256, so the name is the same in every run of the app (hash() is not).
    import hashlib

    from qurantext.jobs.generated_parts import _look_key

    made_from = spec.cache_key() + _look_key(NIGHT_GOLD) + "1280x720@30"
    assert base.stem == "generated-intro-" + hashlib.sha256(made_from.encode()).hexdigest()[:12]
    assert "PosixPath" not in made_from and "WindowsPath" not in made_from
    assert path(width=1280, height=720, fps=25) != base
    assert path(width=720, height=1280, fps=30) != base
    # A colour the clip does not draw (the captions') does not remake it; one it draws does.
    from dataclasses import replace

    captions = replace(NIGHT_GOLD, caption_text=(1, 2, 3, 255))
    assert (
        generated_part_path(
            lecture_project.path, "intro", spec, captions, width=1280, height=720, fps=30
        )
        == base
    )
    header = replace(NIGHT_GOLD, header_text=(1, 2, 3, 255))
    assert (
        generated_part_path(
            lecture_project.path, "intro", spec, header, width=1280, height=720, fps=30
        )
        != base
    )


def _photo_look(image: Path):
    from dataclasses import replace

    from qurantext.core.looks import Background

    background = Background("image", (0, 0, 0, 255), (0, 0, 0, 255), image=image)
    return replace(NIGHT_GOLD, background=background)


def test_the_background_photo_counts_by_its_content_not_its_path(lecture_project, tmp_path):
    """A photo missing when the clip was made, and back now, makes a new clip; the same
    photo in a moved project folder keeps the clip."""
    from PIL import Image

    from qurantext.jobs.generated_parts import generated_part_path

    spec = intro_spec_for(lecture_project, GeneratedIntro(name="دروس"), {})
    size = {"width": 640, "height": 360, "fps": 25}
    photo = tmp_path / "dars.qalun.look" / "3f2a9c1b2d4e.png"
    photo.parent.mkdir()

    def path(project_path, image):
        return generated_part_path(project_path, "intro", spec, _photo_look(image), **size)

    missing = path(lecture_project.path, photo)
    Image.new("RGB", (8, 8), (200, 30, 30)).save(photo)
    present = path(lecture_project.path, photo)
    assert present != missing, "the photo is back: the clip is made again with it"

    moved = tmp_path / "moved"
    moved.mkdir()
    (moved / "dars.qalun.look").mkdir()
    copy = moved / "dars.qalun.look" / photo.name
    copy.write_bytes(photo.read_bytes())
    again = path(moved / "dars.qalun.json", copy)
    assert again.name == present.name, "the same photo in a moved folder: the same clip"

    Image.new("RGB", (8, 8), (30, 200, 30)).save(copy)
    assert path(moved / "dars.qalun.json", copy).name != present.name, "another photo"


def test_parts_of_the_other_kind_are_left_alone(lecture_project, monkeypatch):
    _fake_render(monkeypatch)
    intro = intro_spec_for(lecture_project, GeneratedIntro(name="دروس"), {})
    outro = outro_spec_for(lecture_project, GeneratedOutro(), {})
    kept = ensure_generated_part(
        lecture_project, "outro", outro, NIGHT_GOLD, width=640, height=360, fps=25
    )
    ensure_generated_part(
        lecture_project, "intro", intro, NIGHT_GOLD, width=640, height=360, fps=25
    )
    ensure_generated_part(
        lecture_project, "intro", intro, NIGHT_GOLD, width=640, height=360, fps=30
    )
    assert kept.is_file()


def test_a_link_too_long_for_the_videos_size_is_said(lecture_project, monkeypatch):
    calls = _fake_render(monkeypatch)
    long_link = "example.org/" + "d" * 600
    spec = outro_spec_for(lecture_project, GeneratedOutro(link=long_link), {})
    with pytest.raises(EpisodeError) as raised:
        ensure_generated_part(
            lecture_project, "outro", spec, NIGHT_GOLD, width=640, height=360, fps=25
        )
    assert raised.value.key == "episode.error.qr_too_big"
    assert raised.value.fmt == {"size": "640×360"}
    assert calls == []


def test_a_failed_clip_is_an_episode_error_naming_the_part(lecture_project, monkeypatch):
    from qurantext.core.title_cards import TitleClipError

    def broken(spec, look, out, **kwargs):
        raise TitleClipError("FFmpeg could not write the title clip: no space left")

    monkeypatch.setattr("qurantext.jobs.generated_parts.render_title_clip", broken)
    spec = intro_spec_for(lecture_project, GeneratedIntro(name="دروس"), {})
    with pytest.raises(EpisodeError) as raised:
        ensure_generated_part(
            lecture_project, "intro", spec, NIGHT_GOLD, width=640, height=360, fps=25
        )
    assert raised.value.key == "episode.error.generate"
    assert raised.value.fmt == {"part": "episode.part.intro"}
    assert not list(episode_dir_for(lecture_project.path).glob("generated-intro-*.mp4"))


def test_a_cancel_is_a_cancel(lecture_project, monkeypatch):
    def cancelled(spec, look, out, *, cancel=None, **kwargs):
        cancel.raise_if_cancelled("title_clip")

    monkeypatch.setattr("qurantext.jobs.generated_parts.render_title_clip", cancelled)
    token = CancelToken()
    token.cancel()
    spec = intro_spec_for(lecture_project, GeneratedIntro(name="دروس"), {})
    with pytest.raises(JobCancelled):
        ensure_generated_part(
            lecture_project, "intro", spec, NIGHT_GOLD, width=640, height=360, fps=25, cancel=token
        )


def test_an_unknown_kind_is_refused(lecture_project):
    spec = intro_spec_for(lecture_project, GeneratedIntro(), {})
    with pytest.raises(ValueError):
        ensure_generated_part(
            lecture_project, "middle", spec, NIGHT_GOLD, width=640, height=360, fps=25
        )


def test_a_change_of_ayat_remakes_the_intro(lecture_project, monkeypatch):
    """A corrected card changes the title, so the next render makes the intro again."""
    calls = _fake_render(monkeypatch)
    size = {"width": 640, "height": 360, "fps": 25}
    settings = GeneratedIntro(name="دروس")
    first = ensure_generated_part(
        lecture_project, "intro", intro_spec_for(lecture_project, settings, {}), NIGHT_GOLD, **size
    )
    lecture_project.cards = [*lecture_project.cards, _card(25, 52, 52, 30.0)]
    spec = intro_spec_for(lecture_project, settings, {})
    assert spec.title == "سورة الفرقان، الآيات ٤٤–٥٢"
    second = ensure_generated_part(lecture_project, "intro", spec, NIGHT_GOLD, **size)
    assert second != first and len(calls) == 2 and not first.exists()


@pytest.mark.parametrize(
    ("kind", "spec"),
    [
        ("intro", lambda project: intro_spec_for(project, GeneratedIntro(name=" "), {})),
        ("outro", lambda project: outro_spec_for(project, GeneratedOutro(phrase=""), {})),
    ],
)
def test_a_part_with_nothing_to_show_is_refused(lecture_project, monkeypatch, kind, spec):
    calls = _fake_render(monkeypatch)
    _studying(lecture_project, None)
    lecture_project.cards = []  # no surah: the intro's title is empty too
    with pytest.raises(EpisodeError) as raised:
        ensure_generated_part(
            lecture_project, kind, spec(lecture_project), NIGHT_GOLD, width=640, height=360, fps=25
        )
    assert raised.value.key == "episode.error.generate_empty"
    assert raised.value.fmt == {"part": f"episode.part.{kind}"}
    assert calls == []
    # A link alone is something to show.
    link_only = outro_spec_for(lecture_project, GeneratedOutro(phrase="", link="example.org"), {})
    ensure_generated_part(
        lecture_project, "outro", link_only, NIGHT_GOLD, width=1280, height=720, fps=25
    )


def test_removing_a_kinds_clips_keeps_the_other_kind_and_the_persons_clips(lecture_project):
    from qurantext.jobs.generated_parts import remove_generated_parts

    folder = episode_dir_for(lecture_project.path)
    folder.mkdir()
    for name in ("generated-intro-aaa.mp4", "generated-intro-bbb.mp4", "generated-outro-ccc.mp4",
                 "3f2a9c1b2d4e.mp4", ".generated-intro-aaa.1234.part.mp4"):  # fmt: skip
        (folder / name).write_bytes(b"x")
    remove_generated_parts(lecture_project.path, "intro", keep=folder / "generated-intro-bbb.mp4")
    assert sorted(p.name for p in folder.iterdir()) == [
        ".generated-intro-aaa.1234.part.mp4",
        "3f2a9c1b2d4e.mp4",
        "generated-intro-bbb.mp4",
        "generated-outro-ccc.mp4",
    ]
    remove_generated_parts(lecture_project.path, "intro")
    assert not (folder / "generated-intro-bbb.mp4").exists()
    remove_generated_parts(lecture_project.path.with_name("never.qalun.json"), "intro")  # no folder

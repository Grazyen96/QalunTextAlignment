"""Drawing one frame, so a style can be judged without rendering the video.

Checking how a video looked meant rendering the whole thing. The renderer
already draws exactly one frame at an arbitrary time, which is what makes this
nearly free.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from qurantext.config.paths import DEFAULT_FONT_PATH
from qurantext.jobs.preview import PreviewRequest, render_preview

pytest.importorskip("PIL", reason="the preview needs Pillow")

pytestmark = pytest.mark.skipif(not DEFAULT_FONT_PATH.exists(), reason="bundled font not present")


def _matches(tmp_path, *, mode="recitation"):
    path = tmp_path / "m.json"
    path.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "surah_num": 25,
                        "surah_name": "سُورَةُ الفُرقَانِ",
                        "from_ayah": 7,
                        "to_ayah": 7,
                        "full_text": "وَقَالُواْ مَالِ هَٰذَا اَ۬لرَّسُولِ",
                        "confidence": 1.0,
                        "start_time": 2.0,
                        "end_time": 6.0,
                    },
                    {
                        "surah_num": 25,
                        "surah_name": "سُورَةُ الفُرقَانِ",
                        "from_ayah": 8,
                        "to_ayah": 8,
                        "full_text": "أَوْ يُلْقَيٰ إِلَيْهِ كَنزٌ",
                        "confidence": 1.0,
                        "start_time": 6.0,
                        "end_time": 10.0,
                    },
                ],
                "meta": {"mode": mode},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_a_frame_is_written_at_the_requested_moment(tmp_path) -> None:
    result = render_preview(
        PreviewRequest(
            matches=_matches(tmp_path),
            output=tmp_path / "p.png",
            at=7.0,
            width=320,
            height=240,
            font_file=DEFAULT_FONT_PATH,
        )
    )
    assert result.output.exists() and result.output.stat().st_size > 0
    assert result.at == 7.0
    assert (result.width, result.height) == (320, 240)
    assert result.card == "25:8", "the second card is the one showing at 7s"


def test_the_default_moment_skips_the_opening_placeholder(tmp_path) -> None:
    """Previewing the placeholder tells you nothing about the style."""
    result = render_preview(
        PreviewRequest(
            matches=_matches(tmp_path),
            output=tmp_path / "p.png",
            width=320,
            height=240,
            font_file=DEFAULT_FONT_PATH,
        )
    )
    assert result.card == "25:7"
    assert 2.0 < result.at < 6.0


def test_the_png_has_the_requested_size_and_is_readable(tmp_path) -> None:
    from PIL import Image

    result = render_preview(
        PreviewRequest(
            matches=_matches(tmp_path),
            output=tmp_path / "p.png",
            at=3.0,
            width=240,
            height=426,
            font_file=DEFAULT_FONT_PATH,
        )
    )
    with Image.open(result.output) as image:
        assert image.size == (240, 426)
        assert image.mode in ("RGB", "RGBA")


def test_a_preset_sets_the_size(tmp_path) -> None:
    result = render_preview(
        PreviewRequest(
            matches=_matches(tmp_path),
            output=tmp_path / "p.png",
            at=3.0,
            preset="social",
            font_file=DEFAULT_FONT_PATH,
        )
    )
    assert (result.width, result.height) == (1080, 1920)


def test_a_moment_before_any_card_shows_the_placeholder(tmp_path) -> None:
    result = render_preview(
        PreviewRequest(
            matches=_matches(tmp_path),
            output=tmp_path / "p.png",
            at=0.5,
            width=240,
            height=180,
            font_file=DEFAULT_FONT_PATH,
        )
    )
    assert result.card is None
    assert result.output.exists()


def test_a_missing_match_file_says_so(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        render_preview(PreviewRequest(matches=tmp_path / "nope.json", output=tmp_path / "p.png"))


def _highlight_matches(tmp_path):
    """One card whose middle word is highlighted at 1.5s."""
    matches = tmp_path / "m.json"
    matches.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "surah_num": 25,
                        "surah_name": "س",
                        "from_ayah": 7,
                        "to_ayah": 7,
                        "full_text": "وَقَالُواْ مَالِ هَٰذَا",
                        "confidence": 1.0,
                        "start_time": 0.0,
                        "end_time": 3.0,
                        "word_timings": [
                            {"word": "وَقَالُواْ", "start": 0.0, "end": 1.0},
                            {"word": "مَالِ", "start": 1.0, "end": 2.0},
                            {"word": "هَٰذَا", "start": 2.0, "end": 3.0},
                        ],
                    }
                ],
                "meta": {"mode": "recitation"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return matches


def _pixels(path):
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        return np.array(image.convert("RGB")).reshape(-1, 3).astype(int)


def test_the_preview_colours_match_the_renderer(tmp_path) -> None:
    """The PNG must not come out with its channels swapped.

    render_frame_pillow hands back BGR for the encoder; a PNG wants RGB. The
    card is a light grey on a near-black ground, so a swap would be invisible
    there — check against the gold highlight instead, which is strongly warm.
    """
    import numpy as np

    from qurantext.core.frame_renderer import COLOUR_HIGHLIGHT_WORD

    result = render_preview(
        PreviewRequest(
            matches=_highlight_matches(tmp_path),
            output=tmp_path / "p.png",
            at=1.5,
            width=480,
            height=320,
            font_file=DEFAULT_FONT_PATH,
        )
    )
    pixels = _pixels(result.output)

    gold = np.array(COLOUR_HIGHLIGHT_WORD[:3])
    distance = np.abs(pixels - gold).sum(axis=1)
    assert (distance < 40).any(), "the gold highlight is missing or its channels are swapped"


def test_preview_uses_the_requested_look(tmp_path) -> None:
    import numpy as np

    from qurantext.core.frame_renderer import COLOUR_HIGHLIGHT_WORD
    from qurantext.core.looks import NIGHT_GOLD

    look = replace(NIGHT_GOLD, highlight_word=(255, 0, 255, 255))
    result = render_preview(
        PreviewRequest(
            matches=_highlight_matches(tmp_path),
            output=tmp_path / "p.png",
            at=1.5,
            width=480,
            height=320,
            font_file=DEFAULT_FONT_PATH,
            look=look,
        )
    )
    pixels = _pixels(result.output)

    magenta = np.abs(pixels - np.array([255, 0, 255])).sum(axis=1)
    gold = np.abs(pixels - np.array(COLOUR_HIGHLIGHT_WORD[:3])).sum(axis=1)
    assert (magenta < 40).any(), "the requested highlight colour is missing"
    assert not (gold < 40).any(), "the default gold highlight was drawn instead"
    assert result.look_warnings == ()


def test_preview_reports_a_missing_background_image(tmp_path) -> None:
    from qurantext.core.looks import NIGHT_GOLD, Background

    background = Background(
        "image",
        NIGHT_GOLD.background.colour,
        NIGHT_GOLD.background.colour2,
        image=tmp_path / "gone.png",
    )
    result = render_preview(
        PreviewRequest(
            matches=_matches(tmp_path),
            output=tmp_path / "p.png",
            at=3.0,
            width=240,
            height=180,
            font_file=DEFAULT_FONT_PATH,
            look=replace(NIGHT_GOLD, background=background),
        )
    )
    assert result.look_warnings == ("image_missing",)
    assert result.output.exists() and result.output.stat().st_size > 0


def test_a_lecture_keeps_the_studied_ayah_up_through_a_quote_from_another_surah(tmp_path) -> None:
    path = _matches(tmp_path, mode="lecture")
    payload = json.loads(path.read_text(encoding="utf-8"))
    quote = dict(
        payload["matches"][0], surah_num=17, surah_name="الإسراء", from_ayah=48, to_ayah=48
    )
    quote.update(start_time=6.5, end_time=7.5)
    payload["matches"].insert(1, quote)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = render_preview(
        PreviewRequest(
            matches=path,
            output=tmp_path / "p.png",
            at=7.0,
            width=240,
            height=180,
            font_file=DEFAULT_FONT_PATH,
        )
    )
    assert result.card == "25:8", "the quote from al-Isra stays in the captions, not on the card"


def _lecture_quoting_al_isra(tmp_path):
    path = _matches(tmp_path, mode="lecture")
    payload = json.loads(path.read_text(encoding="utf-8"))
    quote = dict(
        payload["matches"][0], surah_num=17, surah_name="الإسراء", from_ayah=48, to_ayah=48
    )
    quote.update(start_time=6.5, end_time=7.5)
    payload["matches"].insert(1, quote)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_the_preview_draws_the_chosen_surah(tmp_path) -> None:
    """At 7s the guess holds al-Furqan up; the person chose al-Isra, so its quote shows."""
    result = render_preview(
        PreviewRequest(
            matches=_lecture_quoting_al_isra(tmp_path),
            output=tmp_path / "p.png",
            at=7.0,
            width=240,
            height=180,
            font_file=DEFAULT_FONT_PATH,
            studied_surah=17,
        )
    )
    assert result.card == "17:48"


def test_the_preview_cli_passes_the_studied_surah(tmp_path, capsys) -> None:
    from qurantext.cli.main import build_parser

    args = build_parser().parse_args(
        [
            "preview",
            "--matches",
            str(_lecture_quoting_al_isra(tmp_path)),
            "--output",
            str(tmp_path / "p.png"),
            "--at",
            "7",
            "--width",
            "240",
            "--height",
            "180",
            "--font-file",
            str(DEFAULT_FONT_PATH),
            "--studied-surah",
            "17",
        ]
    )
    assert args.handler(args) == 0
    assert "showing 17:48" in capsys.readouterr().out


def _project_beside(matches, *, mode="lecture", studied_surah=None):
    from qurantext.jobs.project import (
        JobSettings,
        Project,
        project_path_for,
        save_project,
        set_job_settings,
    )

    project = Project(audio=matches.with_suffix(".mp3"), mode=mode, matches=matches)
    set_job_settings(project, JobSettings(studied_surah=studied_surah))
    save_project(project, project_path_for(matches))


def _cli_preview(matches, tmp_path, *flags):
    from qurantext.cli.main import build_parser

    args = build_parser().parse_args(
        [
            "preview",
            "--matches",
            str(matches),
            "--output",
            str(tmp_path / "p.png"),
            "--at",
            "7",
            "--width",
            "240",
            "--height",
            "180",
            "--font-file",
            str(DEFAULT_FONT_PATH),
            *flags,
        ]
    )
    assert args.handler(args) == 0


def test_the_preview_cli_follows_the_surah_of_the_project_beside_the_matches(
    tmp_path, capsys
) -> None:
    """Chosen in the review and saved: the preview shows what the export will."""
    matches = _lecture_quoting_al_isra(tmp_path)
    _project_beside(matches, studied_surah=17)
    _cli_preview(matches, tmp_path)
    assert "showing 17:48" in capsys.readouterr().out

    _cli_preview(matches, tmp_path, "--studied-surah", "25")
    captured = capsys.readouterr()
    assert "showing 17:48" in captured.out, "the project's own choice wins"
    assert "Ignoring --studied-surah" in captured.err


def test_the_preview_cli_flag_applies_when_the_project_beside_has_no_choice(
    tmp_path, capsys
) -> None:
    matches = _lecture_quoting_al_isra(tmp_path)
    _project_beside(matches)
    _cli_preview(matches, tmp_path)
    assert "showing 25:8" in capsys.readouterr().out, "no choice: the guess"
    _cli_preview(matches, tmp_path, "--studied-surah", "17")
    assert "showing 17:48" in capsys.readouterr().out

"""Producing the deliverables: a video, subtitle files, or both.

This is what replaces the Premiere branch, so what matters is that the sidecar
files actually line up with the video they accompany.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from qurantext.config.paths import DEFAULT_FONT_PATH
from qurantext.jobs.export import SUBTITLE_MODES, ExportRequest, build_cues, export_job
from tests.media_helpers import (
    FFPROBE,
    MEDIA_AVAILABLE,
    MEDIA_REASON,
    QURAN_FILE,
    build_job,
)

pytestmark = pytest.mark.skipif(not MEDIA_AVAILABLE, reason=MEDIA_REASON)


def test_burn_writes_only_a_video(tmp_path, store, no_basmala) -> None:
    audio, matches = build_job(tmp_path)
    result = export_job(
        ExportRequest(
            audio=audio,
            matches=matches,
            output=tmp_path / "out.mp4",
            subtitles="burn",
            width=160,
            height=120,
            fps=8,
            font_file=DEFAULT_FONT_PATH,
            db_path=store,
        )
    )
    assert result.video is not None and result.video.exists()
    assert result.subtitles == []
    assert list(tmp_path.glob("*.srt")) == []


def test_both_writes_a_video_and_the_requested_formats(tmp_path, store, no_basmala) -> None:
    audio, matches = build_job(tmp_path)
    result = export_job(
        ExportRequest(
            audio=audio,
            matches=matches,
            output=tmp_path / "out.mp4",
            subtitles="both",
            formats=("srt", "vtt"),
            width=160,
            height=120,
            fps=8,
            font_file=DEFAULT_FONT_PATH,
            db_path=store,
        )
    )
    assert result.video is not None and result.video.exists()
    assert [p.suffix for p in result.subtitles] == [".srt", ".vtt"]
    assert result.cues == 2, "one cue per ayah"


def test_the_sidecar_carries_canonical_text_not_the_recogniser_version(
    tmp_path, store, no_basmala
) -> None:
    """The Quran in a subtitle file must come from the store."""
    from qurantext.core.quran_parser import parse_ayat

    audio, matches = build_job(tmp_path)
    export_job(
        ExportRequest(
            audio=audio,
            matches=matches,
            output=tmp_path / "out.mp4",
            subtitles="sidecar",
            width=160,
            height=120,
            fps=8,
            font_file=DEFAULT_FONT_PATH,
            db_path=store,
        )
    )
    text = (tmp_path / "out.srt").read_text(encoding="utf-8-sig")
    for ayah in parse_ayat(QURAN_FILE):
        if ayah["surah_num"] == 25 and ayah["ayah_num"] == 7:
            first_words = " ".join(str(ayah["text_raw"]).split()[:3])
            assert first_words in text
            break
    else:  # pragma: no cover - the shipped file always has 25:7
        pytest.fail("25:7 not found in the shipped Quran text")


def test_cues_end_with_the_video_when_a_basmala_is_spliced(tmp_path, store, monkeypatch) -> None:
    """Regression: the splice offset was applied twice to the last cue.

    The last cue holds to the end of the audio. Building the windows against the
    post-splice duration and then shifting them added the offset a second time,
    so the subtitle ran past the end of the video it accompanied.
    """
    from qurantext.jobs import export as export_module

    audio, matches = build_job(tmp_path)
    offset = 4.0
    real_render = export_module.render_video

    def shifted_render(request, **kwargs):
        result = real_render(request, **kwargs)
        return type(result)(
            output=result.output,
            width=result.width,
            height=result.height,
            fps=result.fps,
            duration_seconds=result.duration_seconds + offset,
            basmala_offset_seconds=offset,
            caption_segments=result.caption_segments,
            ass_path=result.ass_path,
        )

    monkeypatch.setattr(export_module, "render_video", shifted_render)
    monkeypatch.setenv("QURANTEXT_VIDEO_PREPEND_BASMALA", "false")
    from qurantext.config.settings import get_settings

    get_settings.cache_clear()

    result = export_job(
        ExportRequest(
            audio=audio,
            matches=matches,
            output=tmp_path / "out.mp4",
            subtitles="sidecar",
            width=160,
            height=120,
            fps=8,
            font_file=DEFAULT_FONT_PATH,
            db_path=store,
        )
    )
    get_settings.cache_clear()

    duration = float(
        subprocess.run(
            [
                FFPROBE,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(result.video),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )

    import re

    text = (tmp_path / "out.srt").read_text(encoding="utf-8-sig")
    stamps = re.findall(r"--> (\d\d):(\d\d):(\d\d),(\d\d\d)", text)
    last_end = max(int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000 for h, m, s, ms in stamps)
    # The video is the un-shifted render here; the cues were shifted by `offset`.
    assert last_end <= duration + offset + 0.1, (
        f"the last cue ends at {last_end:.2f}s, past the {duration + offset:.2f}s video"
    )
    first_start = min(
        int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
        for h, m, s, ms in re.findall(r"(\d\d):(\d\d):(\d\d),(\d\d\d) -->", text)
    )
    assert first_start == pytest.approx(offset, abs=0.1), "the splice must push cues later"


@pytest.mark.parametrize("mode", SUBTITLE_MODES)
def test_every_mode_is_accepted(tmp_path, store, no_basmala, mode) -> None:
    audio, matches = build_job(tmp_path)
    result = export_job(
        ExportRequest(
            audio=audio,
            matches=matches,
            output=tmp_path / f"{mode}.mp4",
            subtitles=mode,
            width=160,
            height=120,
            fps=8,
            font_file=DEFAULT_FONT_PATH,
            db_path=store,
        )
    )
    assert result.video is not None and result.video.exists()
    assert bool(result.subtitles) == (mode != "burn")


def test_an_unknown_mode_is_refused_at_construction(tmp_path) -> None:
    with pytest.raises(ValueError, match="subtitles must be one of"):
        ExportRequest(
            audio=tmp_path / "a.m4a",
            matches=tmp_path / "m.json",
            output=tmp_path / "o.mp4",
            subtitles="engrave",
        )


def test_cues_tile_with_no_gaps(tmp_path, store) -> None:
    audio, matches = build_job(tmp_path)
    cues = build_cues(matches, duration=20.0, mode="recitation", db_path=store)
    assert len(cues) == 2
    assert cues[0].end == cues[1].start, "a gap would blank the subtitle mid-card"
    assert cues[-1].end == 20.0, "the last cue holds to the end of the audio"
    assert [c.ref for c in cues] == ["25:7", "25:8"]


def test_a_missing_store_is_built_from_the_bundled_text(tmp_path, no_basmala) -> None:
    """The app ships the certified text, so a new machine needs nothing from the user.

    Found by running the packaged app on a machine that had never built a store:
    it produced the video and then gave up on the subtitles.
    """
    audio, matches = build_job(tmp_path)
    store = tmp_path / "fresh.sqlite"
    assert not store.exists()

    result = export_job(
        ExportRequest(
            audio=audio,
            matches=matches,
            output=tmp_path / "out.mp4",
            subtitles="both",
            width=160,
            height=120,
            fps=8,
            font_file=DEFAULT_FONT_PATH,
            db_path=store,
        )
    )
    assert store.exists(), "the store should have been built from the bundled text"
    assert result.video is not None and result.video.exists()
    assert result.subtitles, "subtitles must be written once the store exists"
    assert result.cues == 2


def test_build_cues_uses_the_cards_it_is_given(tmp_path, store) -> None:
    _, matches = build_job(tmp_path)
    card = json.loads(matches.read_text(encoding="utf-8"))["matches"][0]
    moved = dict(card, start_time=1.5)

    from_file = build_cues(matches, 20.0, mode="recitation", db_path=store)
    from_project = build_cues(matches, 20.0, mode="recitation", db_path=store, cards=(moved,))
    assert from_file[0].start == pytest.approx(0.0)
    assert from_project[0].start == pytest.approx(1.5)


def test_render_uses_the_cards_it_is_given(tmp_path, store, no_basmala, monkeypatch) -> None:
    from qurantext.jobs import render as render_module
    from qurantext.jobs.render import RenderRequest, render_video

    audio, matches = build_job(tmp_path)
    seen = {}

    def capture(audio_path, matches_list, output_path, *args, **kwargs):
        seen["cards"] = matches_list
        output_path.write_bytes(b"")
        return 1.0

    monkeypatch.setattr(render_module, "render_frame_video", capture)
    replacement = {
        "surah_num": 25,
        "from_ayah": 9,
        "to_ayah": 9,
        "start_time": 2.0,
        "end_time": 3.0,
        "full_text": "x",
        "confidence": 1.0,
    }
    render_video(
        RenderRequest(
            audio=audio,
            matches=matches,
            output=tmp_path / "v.mp4",
            width=160,
            height=120,
            fps=8,
            font_file=DEFAULT_FONT_PATH,
            cards=(replacement,),
        )
    )
    assert [c["from_ayah"] for c in seen["cards"]] == [9]


def test_a_store_that_cannot_be_built_costs_the_subtitles_not_the_video(
    tmp_path, no_basmala, monkeypatch
) -> None:
    """The video is already rendered by the time the subtitles are built."""
    from qurantext.data import quran_db

    def refuse(*_args, **_kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(quran_db, "ensure_quran_db", refuse)
    audio, matches = build_job(tmp_path)
    result = export_job(
        ExportRequest(
            audio=audio,
            matches=matches,
            output=tmp_path / "out.mp4",
            subtitles="both",
            width=160,
            height=120,
            fps=8,
            font_file=DEFAULT_FONT_PATH,
            db_path=tmp_path / "nope.sqlite",
        )
    )
    assert result.video is not None and result.video.exists()
    assert result.subtitles == []


def test_the_export_renders_with_its_look(tmp_path, no_basmala, monkeypatch) -> None:
    """The look reaches the frame renderer, and its warnings come back on the result."""
    from qurantext.core.looks import PRESETS
    from qurantext.jobs import render as render_module

    audio, matches = build_job(tmp_path)
    seen = {}

    def capture(audio_path, matches_list, output_path, *args, look, look_warnings, **kwargs):
        seen["look"] = look
        look_warnings.append("image_unreadable")
        output_path.write_bytes(b"")
        return 1.0

    monkeypatch.setattr(render_module, "render_frame_video", capture)
    result = export_job(
        ExportRequest(
            audio=audio,
            matches=matches,
            output=tmp_path / "v.mp4",
            width=160,
            height=120,
            fps=8,
            font_file=DEFAULT_FONT_PATH,
            look=PRESETS["emerald"],
        )
    )
    assert seen["look"] == PRESETS["emerald"]
    assert result.render.look_warnings == ("image_unreadable",)

"""The lecture's opening card: the preview, the review's frame and the export agree.

Each of the three draws the card before the first ayah through
``core.frame_renderer.placeholder_lines``, and each must hand it the surah the
person chose. The case that tells them apart: a chosen surah (25) whose only
cards are hand-made cards of another surah (2). With the choice, the card
names no surah of those cards; a path that forgot it would guess surah 2 from
them and announce «البقرة».
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from qurantext.config.paths import DEFAULT_FONT_PATH

pytestmark = [
    pytest.mark.skipif(not DEFAULT_FONT_PATH.exists(), reason="bundled font not present"),
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="the export needs FFmpeg"),
]

STUDIED = 25
_CARD = {
    "surah_num": 2,
    "surah_name": "البقرة",
    "full_text": "الم",
    "confidence": 1.0,
    "manual": True,
}
CARDS = [
    dict(_CARD, from_ayah=1, to_ayah=1, start_time=2.0, end_time=4.0),
    dict(_CARD, from_ayah=5, to_ayah=5, start_time=4.0, end_time=6.0),
]
CAPTION = {"start": 0.2, "end": 1.5, "text": "بسم الله"}


@pytest.fixture
def spy(monkeypatch):
    """Every ``placeholder_lines`` call, from any of the three: (studied surah, lines)."""
    from qurantext.core import frame_renderer
    from qurantext.gui.review import frame_view

    real = frame_renderer.placeholder_lines
    calls: list[tuple[int | None, tuple[str, str]]] = []

    def recorded(matches, **kwargs):
        lines = real(matches, **kwargs)
        calls.append((kwargs.get("studied_surah"), lines))
        return lines

    monkeypatch.setattr(frame_renderer, "placeholder_lines", recorded)
    monkeypatch.setattr(frame_view, "placeholder_lines", recorded)
    return calls


def _matches_file(tmp_path):
    transcript = tmp_path / "raw.json"
    transcript.write_text(json.dumps({"segments": [CAPTION]}, ensure_ascii=False), "utf-8")
    path = tmp_path / "m.json"
    payload = {
        "matches": CARDS,
        "meta": {"mode": "lecture", "whisperx_raw_output_path": str(transcript)},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _preview(tmp_path):
    from qurantext.jobs.preview import PreviewRequest, render_preview

    render_preview(
        PreviewRequest(
            matches=_matches_file(tmp_path),
            output=tmp_path / "p.png",
            at=0.5,
            width=320,
            height=180,
            font_file=DEFAULT_FONT_PATH,
            studied_surah=STUDIED,
        )
    )


def _review_frame(tmp_path):
    from qurantext.gui.review.frame_view import FrameView
    from qurantext.gui.review.session import ReviewSession
    from qurantext.jobs.project import CaptionCue, JobSettings, Project, set_job_settings

    project = Project(
        audio=tmp_path / "dars.wav",
        mode="lecture",
        cards=[dict(card) for card in CARDS],
        captions=[CaptionCue(CAPTION["start"], CAPTION["end"], CAPTION["text"])],
    )
    set_job_settings(project, JobSettings(subtitles="burn", studied_surah=STUDIED))
    session = ReviewSession(project, duration=6.0)
    assert session.studied_surah == STUDIED
    view = FrameView(session)
    view.show_at(0.5, force=True)


def _export(tmp_path):
    from qurantext.jobs.render import RenderRequest, render_video

    audio = tmp_path / "dars.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono"]
        + ["-t", "6", str(audio)],
        check=True,
    )
    render_video(
        RenderRequest(
            audio=audio,
            matches=_matches_file(tmp_path),
            output=tmp_path / "out.mp4",
            width=160,
            height=90,
            fps=2,
            font_file=DEFAULT_FONT_PATH,
            cards=tuple(dict(card) for card in CARDS),
            captions=({**CAPTION, "word_timings": []},),
            studied_surah=STUDIED,
        )
    )
    assert (tmp_path / "out.mp4").is_file()


def test_the_opening_card_names_the_studied_surah_in_preview_review_and_export(
    qt_app, tmp_path, spy
) -> None:
    seen = {}
    for name, draw in (("preview", _preview), ("review", _review_frame), ("export", _export)):
        spy.clear()
        draw(tmp_path)
        assert spy, f"the {name} drew no opening card"
        studied = {surah for surah, _ in spy}
        assert studied == {STUDIED}, f"the {name} did not pass the studied surah: {studied}"
        seen[name] = spy[-1][1]
    assert seen["preview"] == seen["review"] == seen["export"]
    assert "البقرة" not in " ".join(seen["export"]), "not the hand-made cards' surah"

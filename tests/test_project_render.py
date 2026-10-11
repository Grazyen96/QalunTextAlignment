"""A project is what gets rendered and exported, so corrections reach the output."""

from __future__ import annotations

import pytest

from qurantext.config.paths import DEFAULT_FONT_PATH
from qurantext.jobs.project import Project, load_project, save_project
from qurantext.jobs.project_render import export_project_subtitles, render_project
from tests.media_helpers import MEDIA_AVAILABLE, MEDIA_REASON, build_job

pytestmark = pytest.mark.skipif(not MEDIA_AVAILABLE, reason=MEDIA_REASON)


def _project(tmp_path):
    audio, matches = build_job(tmp_path)
    project = Project.from_match_file(matches, audio)
    save_project(project, tmp_path / "job.qalun.json")
    return project


def test_render_project_records_the_render_and_saves(tmp_path, store, no_basmala) -> None:
    project = _project(tmp_path)
    result = render_project(
        project,
        tmp_path / "v.mp4",
        width=160,
        height=120,
        fps=8,
        font_file=DEFAULT_FONT_PATH,
        db_path=store,
    )
    assert result.video.exists()
    reloaded = load_project(project.path)
    assert reloaded.render["video"] == result.video
    assert reloaded.render_is_stale is False


def test_render_project_follows_the_projects_cards(tmp_path, store, no_basmala) -> None:
    project = _project(tmp_path)
    project.cards[0]["start_time"] = 1.0
    result = render_project(
        project,
        tmp_path / "v.mp4",
        subtitles="sidecar",
        formats=("srt",),
        width=160,
        height=120,
        fps=8,
        font_file=DEFAULT_FONT_PATH,
        db_path=store,
    )
    srt = result.subtitles[0].read_text(encoding="utf-8-sig")
    assert "00:00:01,000 -->" in srt


def test_export_writes_the_chosen_formats_without_rendering(tmp_path, store) -> None:
    project = _project(tmp_path)
    written = export_project_subtitles(
        project, tmp_path / "out" / "clip", ("srt", "vtt", "ass"), db_path=store
    )
    assert sorted(p.suffix for p in written) == [".ass", ".srt", ".vtt"]
    assert not list(tmp_path.glob("**/*.mp4"))


def test_export_on_the_video_timeline_applies_the_basmala_offset(tmp_path, store) -> None:
    project = _project(tmp_path)
    with pytest.raises(ValueError, match="rendered"):
        export_project_subtitles(project, tmp_path / "a", ("srt",), timeline="video", db_path=store)

    project.record_render(tmp_path / "v.mp4", preset="social", basmala_offset_s=2.0)
    (path,) = export_project_subtitles(
        project, tmp_path / "b", ("srt",), timeline="video", db_path=store
    )
    assert "00:00:02,000 -->" in path.read_text(encoding="utf-8-sig")


def test_the_render_records_the_content_it_started_from(tmp_path, monkeypatch) -> None:
    """An edit made while a render runs must leave that render looking stale."""
    from qurantext.jobs import project_render
    from qurantext.jobs.export import ExportResult
    from qurantext.jobs.render import RenderResult

    words = [{"word": "w", "start": 0.5, "end": 1.0}]
    project = Project(
        audio=tmp_path / "a.mp3",
        matches=tmp_path / "m.json",
        cards=[
            {
                "surah_num": 25,
                "from_ayah": 7,
                "to_ayah": 7,
                "start_time": 0.5,
                "end_time": 2.0,
                "word_timings": words,
            }
        ],
    )
    seen = {}

    def fake_export_job(request, *, progress=None, cancel=None):
        project.cards[0]["word_timings"][0]["start"] = 0.7  # the user keeps editing
        project.cards[0]["start_time"] = 0.7
        seen["cards"] = request.cards
        video = tmp_path / "v.mp4"
        return ExportResult(
            video=video,
            render=RenderResult(output=video, width=160, height=120, fps=8, duration_seconds=2.0),
        )

    monkeypatch.setattr(project_render, "export_job", fake_export_job)
    render_project(project, tmp_path / "v.mp4", preset="social", subtitles="both")

    assert seen["cards"][0]["start_time"] == 0.5, "rendered from the snapshot"
    assert seen["cards"][0]["word_timings"][0]["start"] == 0.5
    assert project.render_is_stale is True
    assert (project.render["width"], project.render["height"], project.render["fps"]) == (
        160,
        120,
        8,
    )
    assert project.render["preset"] == "social"
    assert project.render["subtitles"] == "both"


def test_ass_export_uses_the_recorded_render_size(tmp_path, store) -> None:
    project = _project(tmp_path)
    project.record_render(
        tmp_path / "v.mp4", preset="social", basmala_offset_s=0.0, width=720, height=404, fps=25
    )
    (path,) = export_project_subtitles(project, tmp_path / "c", ("ass",), db_path=store)
    text = path.read_text(encoding="utf-8-sig")
    assert "PlayResX: 720" in text and "PlayResY: 404" in text


def _first_cue(srt_text: str) -> str:
    """The first cue block of an SRT (index, times, text), without its trailing blank line."""
    return srt_text.strip().split("\n\n")[0]


def test_export_on_the_video_timeline_matches_a_render_with_a_real_basmala(
    tmp_path, store, monkeypatch
) -> None:
    """Spec §6: exported subtitles line up with the video that was actually rendered.

    The earlier test above feeds a made-up offset; this one renders with the
    real basmala splice and compares against the sidecar that render wrote.
    """
    from qurantext.config.paths import BASMALA_AUDIO_PATH
    from qurantext.config.settings import get_settings

    if not BASMALA_AUDIO_PATH.is_file():
        pytest.skip(f"needs the user's basmala recording at {BASMALA_AUDIO_PATH}")
    monkeypatch.setenv("QURANTEXT_VIDEO_PREPEND_BASMALA", "true")
    get_settings.cache_clear()
    try:
        project = _project(tmp_path)
        result = render_project(
            project,
            tmp_path / "v.mp4",
            subtitles="sidecar",
            formats=("srt",),
            width=160,
            height=120,
            fps=8,
            font_file=DEFAULT_FONT_PATH,
            db_path=store,
        )
    finally:
        get_settings.cache_clear()
    assert float(project.render["basmala_offset_s"]) > 0, "the basmala was spliced in"
    sidecar = result.subtitles[0].read_text(encoding="utf-8-sig")

    (exported,) = export_project_subtitles(
        project, tmp_path / "out" / "clip", ("srt",), timeline="video", db_path=store
    )
    assert _first_cue(exported.read_text(encoding="utf-8-sig")) == _first_cue(sidecar)


def _fake_project(tmp_path):
    """The one-card project the snapshot test above builds."""
    words = [{"word": "w", "start": 0.5, "end": 1.0}]
    return Project(
        audio=tmp_path / "a.mp3",
        matches=tmp_path / "m.json",
        cards=[
            {
                "surah_num": 25,
                "from_ayah": 7,
                "to_ayah": 7,
                "start_time": 0.5,
                "end_time": 2.0,
                "word_timings": words,
            }
        ],
    )


def _fake_result(tmp_path):
    from qurantext.jobs.export import ExportResult
    from qurantext.jobs.render import RenderResult

    video = tmp_path / "v.mp4"
    return ExportResult(
        video=video,
        render=RenderResult(output=video, width=160, height=120, fps=8, duration_seconds=2.0),
    )


def test_project_render_passes_the_project_look(monkeypatch, tmp_path) -> None:
    """The export receives exactly the look the review window shows."""
    from qurantext.core.looks import PRESETS
    from qurantext.jobs import project_render
    from qurantext.jobs.look_assets import set_project_look

    captured = {}

    def fake_export_job(request, *, progress=None, cancel=None):
        captured["look"] = request.look
        return _fake_result(tmp_path)

    monkeypatch.setattr(project_render, "export_job", fake_export_job)
    project = _fake_project(tmp_path)
    set_project_look(project, PRESETS["sand"])
    project_render.render_project(project, tmp_path / "v.mp4", preset="social")
    assert captured["look"] == PRESETS["sand"]


def test_a_look_change_during_a_render_leaves_it_stale(monkeypatch, tmp_path) -> None:
    """The look is snapshotted with the cards, so it behaves like them."""
    from qurantext.core.looks import PRESETS
    from qurantext.jobs import project_render
    from qurantext.jobs.look_assets import set_project_look

    project = _fake_project(tmp_path)
    set_project_look(project, PRESETS["sand"])
    captured = {}

    def fake_export_job(request, *, progress=None, cancel=None):
        set_project_look(project, PRESETS["ocean"])  # the user picks another look
        captured["look"] = request.look
        return _fake_result(tmp_path)

    monkeypatch.setattr(project_render, "export_job", fake_export_job)
    project_render.render_project(project, tmp_path / "v.mp4", preset="social")
    assert captured["look"] == PRESETS["sand"], "rendered from the snapshot"
    assert project.render_is_stale is True


def test_an_explicit_look_is_rendered_and_named_in_the_recorded_hash(monkeypatch, tmp_path) -> None:
    """A look the project does not hold makes the render stale against the project."""
    from qurantext.core.looks import PRESETS
    from qurantext.jobs import project_render

    project = _fake_project(tmp_path)
    captured = {}

    def fake_export_job(request, *, progress=None, cancel=None):
        captured["look"] = request.look
        return _fake_result(tmp_path)

    monkeypatch.setattr(project_render, "export_job", fake_export_job)
    project_render.render_project(
        project, tmp_path / "v.mp4", preset="social", look=PRESETS["ocean"]
    )
    assert captured["look"] == PRESETS["ocean"]
    assert project.style == {}, "the project itself is not changed"
    assert project.render_is_stale is True


def test_rendering_the_projects_own_look_explicitly_keeps_its_hash(monkeypatch, tmp_path) -> None:
    """A hand-edited style is not rewritten into canonical form by an explicit equal look."""
    from qurantext.jobs import project_render
    from qurantext.jobs.look_assets import project_look

    project = _fake_project(tmp_path)
    project.style = {"preset": "emerald", "colours": {"highlight_word": "#f0f"}}
    monkeypatch.setattr(project_render, "export_job", lambda *a, **k: _fake_result(tmp_path))
    project_render.render_project(
        project, tmp_path / "v.mp4", preset="social", look=project_look(project)
    )
    assert project.style == {"preset": "emerald", "colours": {"highlight_word": "#f0f"}}
    assert project.render_is_stale is False

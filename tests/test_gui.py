"""The window and the job it runs.

Qt is an optional dependency, so these skip when it is absent. They run
offscreen, which needs no display, and they exercise the parts that decide
behaviour: what the window would ask for, and what the worker thread does with
progress, results, failures and Cancel.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import QCoreApplication, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qurantext.config.paths import DEFAULT_FONT_PATH, DEFAULT_QURAN_PATH  # noqa: E402
from qurantext.gui.jobs import JobSpec, run_matching, run_render  # noqa: E402
from qurantext.gui.prefs import Prefs  # noqa: E402
from qurantext.gui.worker import JobWorker, run_in_thread  # noqa: E402
from qurantext.utils.progress import CancelToken, JobCancelled, ProgressEvent  # noqa: E402
from tests.qt_helpers import blocking_list_jobs, wait_until_listed  # noqa: E402

QURAN_FILE = DEFAULT_QURAN_PATH
_FFMPEG = shutil.which("ffmpeg")


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


# --- what the window would ask for -------------------------------------------


def _spec(tmp_path, **overrides) -> JobSpec:
    audio = tmp_path / "a.mp3"
    audio.touch()
    defaults = dict(
        audio=audio,
        quran=QURAN_FILE,
        mode="recitation",
        surah_num=25,
        from_ayah=7,
        to_ayah=11,
    )
    defaults.update(overrides)
    return JobSpec(**defaults)


def test_a_complete_recitation_spec_is_ready_to_run(tmp_path) -> None:
    spec = _spec(tmp_path)
    assert spec.validate() is None
    assert spec.has_stated_range is True


@pytest.mark.parametrize(
    ("overrides", "key"),
    [
        ({"audio": Path("/nope/missing.mp3")}, "job.need_audio"),
        ({"quran": Path("/nope/missing.txt")}, "job.need_quran"),
        ({"surah_num": None}, "job.need_range"),
        ({"from_ayah": 11, "to_ayah": 7}, "job.bad_range"),
        ({"subtitles": "sidecar", "formats": ()}, "job.need_format"),
        ({"subtitles": "both", "formats": ()}, "job.need_format"),
    ],
)
def test_an_incomplete_spec_says_what_is_missing(tmp_path, overrides, key) -> None:
    """The panel shows ``t(problem)`` under the Start button, so this is an i18n key."""
    problem = _spec(tmp_path, **overrides).validate()
    assert problem == key


def test_subtitles_in_the_picture_need_no_file_format(tmp_path) -> None:
    from qurantext.gui.i18n import t

    assert _spec(tmp_path, subtitles="burn", formats=()).validate() is None
    assert t("job.need_format") == "Choose at least one subtitle format."


def test_a_lecture_needs_no_range(tmp_path) -> None:
    spec = _spec(tmp_path, mode="lecture", surah_num=None, from_ayah=None, to_ayah=None)
    assert spec.validate() is None
    assert spec.has_stated_range is False


# --- the worker thread --------------------------------------------------------


def test_worker_reports_progress_then_the_result(qt_app) -> None:
    seen: list[ProgressEvent] = []
    results: list[object] = []

    def job(*, progress, cancel):
        progress(ProgressEvent("render", "half", fraction=0.5))
        return "done"

    worker = JobWorker(job, CancelToken())
    worker.progressed.connect(seen.append)
    worker.finished.connect(results.append)
    worker.run()

    assert [e.message for e in seen] == ["half"]
    assert results == ["done"]


def test_worker_turns_a_failure_into_a_sentence(qt_app) -> None:
    """A window must show a message, never die on a traceback."""
    messages: list[str] = []

    def job(*, progress, cancel):
        raise FileNotFoundError("/some/where.mp3")

    worker = JobWorker(job, CancelToken())
    worker.failed.connect(messages.append)
    worker.run()

    assert messages and "File not found" in messages[0]


def test_worker_separates_cancelling_from_failing(qt_app) -> None:
    """Pressing Cancel is not an error and must not be shown as one."""
    events: list[str] = []

    def job(*, progress, cancel):
        raise JobCancelled("render was cancelled")

    worker = JobWorker(job, CancelToken())
    worker.cancelled.connect(lambda: events.append("cancelled"))
    worker.failed.connect(lambda _m: events.append("failed"))
    worker.done.connect(lambda: events.append("done"))
    worker.run()

    assert events == ["cancelled", "done"]


def test_worker_always_signals_done(qt_app) -> None:
    """The window re-enables its controls on `done`, whatever happened."""
    for job in (
        lambda **_: "ok",
        lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
    ):
        events: list[str] = []
        worker = JobWorker(job, CancelToken())
        worker.done.connect(lambda sink=events: sink.append("done"))
        worker.failed.connect(lambda _m: None)
        worker.run()
        assert events == ["done"]


def test_run_in_thread_runs_off_the_calling_thread(qt_app) -> None:
    import threading

    ran_on: list[int] = []
    finished: list[object] = []

    def job(*, progress, cancel):
        ran_on.append(threading.get_ident())
        return "value"

    thread, _worker = run_in_thread(job, CancelToken(), on_finished=finished.append)
    try:
        assert thread.wait(10_000), "the worker thread did not finish"
        QCoreApplication.processEvents()
    finally:
        thread.quit()
        thread.wait(5_000)

    assert ran_on and ran_on[0] != threading.get_ident()
    assert finished == ["value"]


def test_a_worker_outlives_its_thread_until_the_caller_drops_it(qt_app) -> None:
    """Deleting the worker as its thread ends deadlocked the UI thread (see ``run_in_thread``).

    It must still exist once the thread has finished and the posted deletes
    have run, so it is the caller, on the UI thread, that lets it go.
    """
    import shiboken6
    from PySide6.QtCore import QEvent

    thread, worker = run_in_thread(lambda *, progress, cancel: None, CancelToken())
    assert thread.wait(10_000), "the worker thread did not finish"
    QCoreApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert shiboken6.isValid(worker)


# --- the whole job ------------------------------------------------------------


@pytest.mark.skipif(
    not (_FFMPEG and QURAN_FILE.exists() and DEFAULT_FONT_PATH.exists()),
    reason="needs ffmpeg, the shipped Quran file and the bundled font",
)
def test_matching_then_rendering_makes_the_video(tmp_path, monkeypatch) -> None:
    """Start to finished video, with transcription stubbed out.

    Recognition is the one stage that needs the network, so it is replaced here
    by the canonical words at a steady pace. Everything after it is real.
    """
    from qurantext.core.quran_parser import parse_ayat
    from qurantext.pipelines import detection
    from qurantext.services.transcription import WhisperXResult

    chosen = [a for a in parse_ayat(QURAN_FILE) if a["surah_num"] == 25 and 7 <= a["ayah_num"] <= 8]
    words, t = [], 0.0
    for ayah in chosen:
        for token in str(ayah["text_raw"]).split():
            words.append({"word": token, "start": t, "end": t + 0.4})
            t += 0.5
    payload = {"segments": [{"words": words}]}

    def fake_transcribe(audio_path, save_raw_to=None, **_kwargs):
        if save_raw_to is not None:
            Path(save_raw_to).parent.mkdir(parents=True, exist_ok=True)
            Path(save_raw_to).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return WhisperXResult(
            output=payload,
            audio_path=str(audio_path),
            raw_output_path=str(save_raw_to),
            model_ref="stub",
            segment_count=1,
            word_count=len(words),
            engine="local",  # explicit, and not the field's default: the meta must carry it
        )

    monkeypatch.setattr(detection, "transcribe_audio", fake_transcribe)
    monkeypatch.setenv("QURANTEXT_VIDEO_PREPEND_BASMALA", "false")
    from qurantext.config.settings import get_settings

    get_settings.cache_clear()

    audio = tmp_path / "recitation.m4a"
    subprocess.run(
        [
            _FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            str(max(2.0, t)),
            "-c:a",
            "aac",
            str(audio),
        ],
        check=True,
    )

    events: list[ProgressEvent] = []
    project = run_matching(
        JobSpec(
            audio=audio,
            quran=QURAN_FILE,
            mode="recitation",
            surah_num=25,
            from_ayah=7,
            to_ayah=8,
            preset="fast",
            render_right_away=True,
            output_dir=tmp_path / "out",
        ),
        progress=events.append,
    )
    outcome = run_render(project, progress=events.append)
    get_settings.cache_clear()

    assert outcome.matches.exists()
    meta = json.loads(outcome.matches.read_text(encoding="utf-8"))["meta"]
    assert meta["transcription_engine"] == "local"
    assert outcome.video is not None and outcome.video.exists()
    assert outcome.cards >= 1
    # The user watches both stages, not just the slow one.
    assert {e.stage for e in events} >= {"detect", "render"}
    assert outcome.project is not None and outcome.project.exists()
    from qurantext.jobs.project import load_project

    saved = load_project(outcome.project)
    assert saved.render is not None and saved.render["video"] == outcome.video


def test_rematching_keeps_the_earlier_project_as_a_backup(tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.jobs.project import Project

    match_path = tmp_path / "clip_recitation.json"
    match_path.write_text(
        json.dumps({"matches": [], "meta": {"mode": "recitation"}}), encoding="utf-8"
    )
    old = jobs_module.project_path_for(match_path)
    old.write_text(
        '{"project_version": "2", "audio": "a.mp3", "cards": [{"start_time": 1.5}]}',
        encoding="utf-8",
    )

    def fake_range(**kwargs):
        return {"matches": []}

    monkeypatch.setattr(jobs_module, "run_recitation_range", fake_range)
    audio = tmp_path / "clip.m4a"
    audio.write_bytes(b"")
    spec = JobSpec(
        audio=audio, quran=QURAN_FILE, surah_num=1, from_ayah=1, to_ayah=7, output_dir=tmp_path
    )
    project = jobs_module.run_matching(spec)

    assert isinstance(project, Project) and project.path == old
    backups = list(tmp_path.glob("clip_recitation.*.qalun-backup.json"))
    assert len(backups) == 1
    assert '"audio": "a.mp3"' in backups[0].read_text(encoding="utf-8")


def test_two_rematches_in_the_same_second_keep_both_backups(tmp_path, monkeypatch) -> None:
    """Two backups computed in the same second must not overwrite each other."""
    import datetime as datetime_module

    from qurantext.gui import jobs as jobs_module

    class _FrozenDatetime(datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 23, 12, 0, 0)

    monkeypatch.setattr(jobs_module, "datetime", _FrozenDatetime)

    project_path = tmp_path / "clip_recitation.qalun.json"
    project_path.write_text("first", encoding="utf-8")
    jobs_module._set_aside(project_path)

    project_path.write_text("second", encoding="utf-8")
    jobs_module._set_aside(project_path)

    backups = sorted(tmp_path.glob("clip_recitation.*.qalun-backup.json"))
    assert len(backups) == 2
    contents = {p.read_text(encoding="utf-8") for p in backups}
    assert contents == {"first", "second"}
    assert all(p.name.endswith(".qalun-backup.json") for p in backups)


def _rematch_setup(tmp_path, monkeypatch):
    from qurantext.gui import jobs as jobs_module

    match_path = tmp_path / "clip_recitation.json"
    match_path.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "surah_num": 1,
                        "from_ayah": 1,
                        "to_ayah": 7,
                        "full_text": "x",
                        "start_time": 0.0,
                        "end_time": 2.0,
                    }
                ],
                "meta": {"mode": "recitation"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(jobs_module, "run_recitation_range", lambda **kwargs: {"matches": []})
    audio = tmp_path / "clip.m4a"
    audio.write_bytes(b"")
    spec = JobSpec(
        audio=audio,
        quran=QURAN_FILE,
        surah_num=1,
        from_ayah=1,
        to_ayah=7,
        output_dir=tmp_path,
    )
    return jobs_module, spec


def test_an_identical_rematch_makes_no_backup(tmp_path, monkeypatch) -> None:
    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    jobs_module.run_matching(spec)
    events: list[ProgressEvent] = []
    run_matching(spec, progress=events.append)

    assert not list(tmp_path.glob("*.qalun-backup.json"))
    assert not any("Kept your earlier corrections" in e.message for e in events)


def test_a_changed_rematch_keeps_a_backup_and_says_so(tmp_path, monkeypatch) -> None:
    from qurantext.jobs.project import load_project, save_project

    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    first = jobs_module.run_matching(spec)
    corrected = load_project(first.path)
    corrected.cards[0]["start_time"] = 0.25
    save_project(corrected, first.path)

    events: list[ProgressEvent] = []
    run_matching(spec, progress=events.append)

    from qurantext.gui.i18n import t

    (backup,) = tmp_path.glob("clip_recitation.*.qalun-backup.json")
    assert load_project(backup).cards[0]["start_time"] == 0.25
    kept = t("job.progress.kept", name=backup.name)
    assert kept == f"Kept your earlier corrections in {backup.name}"
    assert any(e.stage == "detect" and e.message == kept and e.translated for e in events)


def test_an_unreadable_earlier_project_is_always_kept(tmp_path, monkeypatch) -> None:
    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    jobs_module.project_path_for(tmp_path / "clip_recitation.json").write_text("{not json")
    run_matching(spec)
    (backup,) = tmp_path.glob("clip_recitation.*.qalun-backup.json")
    assert backup.read_text() == "{not json"


def test_set_aside_returns_the_backup_path(tmp_path) -> None:
    from qurantext.gui import jobs as jobs_module

    project_path = tmp_path / "clip_recitation.qalun.json"
    assert jobs_module._set_aside(project_path) is None
    project_path.write_text("x", encoding="utf-8")
    backup = jobs_module._set_aside(project_path)
    assert backup is not None and backup.read_text(encoding="utf-8") == "x"
    assert not project_path.exists()


def test_an_identical_rematch_leaves_the_project_file_untouched(tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.jobs.project import (
        JobSettings,
        Project,
        load_project,
        project_path_for,
        save_project,
        set_job_settings,
    )

    match_path = tmp_path / "clip_recitation.json"
    match_path.write_text(
        json.dumps({"matches": [], "meta": {"mode": "recitation"}}), encoding="utf-8"
    )
    audio = tmp_path / "clip.m4a"
    audio.write_bytes(b"")
    existing = Project.from_match_file(match_path, audio, mode="recitation")
    existing.mark_reviewed()
    existing.style = {"theme": "night"}
    # The same choices the re-run makes, so only the content could differ.
    set_job_settings(existing, JobSettings(output_dir=tmp_path))
    destination = save_project(existing, project_path_for(match_path))
    before = destination.read_bytes()

    monkeypatch.setattr(jobs_module, "run_recitation_range", lambda **kwargs: {"matches": []})
    spec = JobSpec(
        audio=audio, quran=QURAN_FILE, surah_num=1, from_ayah=1, to_ayah=7, output_dir=tmp_path
    )
    project = jobs_module.run_matching(spec)

    assert destination.read_bytes() == before
    assert project.review["state"] == "reviewed" and project.style == {"theme": "night"}
    assert not list(tmp_path.glob("*.qalun-backup.json"))
    assert load_project(destination).review["state"] == "reviewed"


# --- the job's choices, kept with the job -----------------------------------


def test_matching_records_the_jobs_choices(tmp_path, monkeypatch) -> None:
    from qurantext.jobs.project import JobSettings, job_settings, load_project

    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    spec = replace(spec, preset="fast", subtitles="both", formats=("srt", "vtt"))
    project = jobs_module.run_matching(spec)

    expected = JobSettings("fast", "both", ("srt", "vtt"), tmp_path.resolve())
    assert job_settings(project) == expected
    assert job_settings(load_project(project.path)) == expected


def test_an_unchanged_rematch_with_new_choices_updates_only_the_choices(
    tmp_path, monkeypatch
) -> None:
    from qurantext.jobs.project import job_settings, load_project, save_project

    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    first = jobs_module.run_matching(spec)
    reviewed = load_project(first.path)
    reviewed.mark_reviewed()
    reviewed.style = {"theme": "night"}
    save_project(reviewed, first.path)
    before = json.loads(first.path.read_text(encoding="utf-8"))

    events: list[ProgressEvent] = []
    run_matching(replace(spec, preset="high"), progress=events.append)

    after = json.loads(first.path.read_text(encoding="utf-8"))
    assert after["export"]["preset"] == "high"
    assert {k: v for k, v in after.items() if k != "export"} == {
        k: v for k, v in before.items() if k != "export"
    }, "cards, captions, review and style are left as they were"
    assert job_settings(load_project(first.path)).preset == "high"
    assert not list(tmp_path.glob("*.qalun-backup.json"))


def _capture_render_project(jobs_module, monkeypatch, tmp_path):
    from qurantext.jobs.export import ExportResult

    seen: dict = {}

    def fake_render_project(project, output, **kwargs):
        seen.update(kwargs, output=output)
        return ExportResult(video=output, subtitles=[], cues=0, render=None)

    monkeypatch.setattr(jobs_module, "render_project", fake_render_project)
    return seen


def test_render_uses_the_recorded_choices(tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.jobs.project import JobSettings, Project, set_job_settings

    seen = _capture_render_project(jobs_module, monkeypatch, tmp_path)
    project = Project(audio=tmp_path / "clip.m4a", matches=tmp_path / "clip_recitation.json")
    set_job_settings(
        project,
        JobSettings("fast", "sidecar", ("vtt",), tmp_path / "videos"),
    )
    jobs_module.run_render(project)

    assert seen["preset"] == "fast"
    assert seen["subtitles"] == "sidecar"
    assert seen["formats"] == ("vtt",)
    assert seen["output"] == (tmp_path / "videos").resolve() / "clip.mp4"


def test_render_without_recorded_choices_uses_the_defaults(tmp_path, monkeypatch) -> None:
    from qurantext.config.paths import VIDEOS_OUTPUT_DIR
    from qurantext.gui import jobs as jobs_module
    from qurantext.jobs.project import Project

    seen = _capture_render_project(jobs_module, monkeypatch, tmp_path)
    project = Project(audio=tmp_path / "clip.m4a", matches=tmp_path / "clip_recitation.json")
    jobs_module.run_render(project)

    assert (seen["preset"], seen["subtitles"], seen["formats"]) == ("social", "burn", ("srt",))
    assert seen["output"] == Path(VIDEOS_OUTPUT_DIR) / "clip.mp4"


def test_render_overrides_win_over_the_recorded_choices(tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.jobs.project import JobSettings, Project, set_job_settings

    seen = _capture_render_project(jobs_module, monkeypatch, tmp_path)
    project = Project(audio=tmp_path / "clip.m4a", matches=tmp_path / "clip_recitation.json")
    set_job_settings(project, JobSettings("fast", "sidecar", ("vtt",), tmp_path / "videos"))
    jobs_module.run_render(
        project, preset="high", subtitles="both", formats=("ass",), output_dir=tmp_path / "x"
    )

    assert (seen["preset"], seen["subtitles"], seen["formats"]) == ("high", "both", ("ass",))
    assert seen["output"] == tmp_path / "x" / "clip.mp4"


def test_render_carries_the_looks_warnings_to_the_outcome(tmp_path, monkeypatch) -> None:
    """Spec §4: a missing or unreadable image at export reaches the window, not stderr only."""
    from qurantext.gui import jobs as jobs_module
    from qurantext.jobs.export import ExportResult
    from qurantext.jobs.project import Project
    from qurantext.jobs.render import RenderResult

    def fake_render_project(project, output, **kwargs):
        render = RenderResult(
            output=output,
            width=8,
            height=8,
            fps=1,
            duration_seconds=1.0,
            look_warnings=("image_missing",),
        )
        return ExportResult(video=output, render=render)

    monkeypatch.setattr(jobs_module, "render_project", fake_render_project)
    project = Project(audio=tmp_path / "clip.m4a", matches=tmp_path / "clip_recitation.json")
    assert jobs_module.run_render(project).look_warnings == ("image_missing",)


def test_a_render_without_a_render_result_has_no_look_warnings(tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.jobs.project import Project

    _capture_render_project(jobs_module, monkeypatch, tmp_path)
    project = Project(audio=tmp_path / "clip.m4a", matches=tmp_path / "clip_recitation.json")
    assert jobs_module.run_render(project).look_warnings == ()


def test_a_changed_rematch_keeps_the_videos_look(tmp_path, monkeypatch) -> None:
    """The look is the person's choice for the video; matching cannot have changed it."""
    from qurantext.core.looks import PRESETS
    from qurantext.jobs.look_assets import project_look, set_project_look
    from qurantext.jobs.project import load_project, save_project

    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    first = jobs_module.run_matching(spec)
    corrected = load_project(first.path)
    corrected.cards[0]["start_time"] = 0.25
    set_project_look(corrected, PRESETS["rose"])
    corrected.style["note"] = "kept too"
    save_project(corrected, first.path)
    style = load_project(first.path).style

    project = run_matching(spec)

    assert list(tmp_path.glob("clip_recitation.*.qalun-backup.json")), "content changed"
    assert project.cards[0]["start_time"] != 0.25
    assert project.style == style
    saved = load_project(first.path)
    assert saved.style == style and project_look(saved) == PRESETS["rose"]


def test_a_rematch_compares_without_the_look_on_both_sides(tmp_path, monkeypatch) -> None:
    """Even a derived project that already carries a look counts as unchanged."""
    from qurantext.core.looks import PRESETS
    from qurantext.jobs.look_assets import set_project_look
    from qurantext.jobs.project import Project, load_project

    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    first = jobs_module.run_matching(spec)
    derived = Project.from_match_file(tmp_path / "clip_recitation.json", spec.audio)
    derived.mode = load_project(first.path).mode
    set_project_look(derived, PRESETS["ocean"])
    assert jobs_module._keep_earlier(first.path, derived) == jobs_module._UNCHANGED


# --- the default look a new job starts with ------------------------------------


def _image_look(image: Path, preset: str = "sand"):
    from qurantext.core.looks import PRESETS, Background

    return replace(
        PRESETS[preset],
        background=Background("image", (0, 0, 0, 255), (0, 0, 0, 255), image, 0.35, 0),
    )


def test_a_new_job_is_seeded_with_the_default_look(tmp_path, monkeypatch) -> None:
    from qurantext.core.looks import PRESETS
    from qurantext.jobs.look_assets import project_look
    from qurantext.jobs.project import load_project

    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    project = jobs_module.run_matching(replace(spec, style=PRESETS["sand"].to_dict()))

    assert project_look(project) == PRESETS["sand"]
    assert project_look(load_project(project.path)) == PRESETS["sand"]


def test_a_new_job_without_a_default_look_has_no_style(tmp_path, monkeypatch) -> None:
    from qurantext.jobs.project import load_project

    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    project = jobs_module.run_matching(spec)
    assert spec.style == {}
    assert load_project(project.path).style == {}


def test_a_default_image_is_copied_beside_the_new_project(tmp_path, monkeypatch) -> None:
    from PIL import Image

    from qurantext.jobs.look_assets import look_dir_for, project_look
    from qurantext.jobs.project import load_project

    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    (tmp_path / "app").mkdir()
    image = tmp_path / "app" / "bg.png"
    Image.new("RGB", (4, 4), (7, 8, 9)).save(image)
    look = _image_look(image)

    project = jobs_module.run_matching(replace(spec, style=look.to_dict()))

    stored = project.style["background"]["image"]
    assert not Path(stored).is_absolute()  # moves with the project folder
    copied = project_look(load_project(project.path)).background.image
    assert copied.parent == look_dir_for(project.path)
    assert copied.read_bytes() == image.read_bytes()
    assert project_look(load_project(project.path)) == replace(
        look, background=replace(look.background, image=copied)
    )


def test_seeding_with_a_missing_default_image_still_creates_the_project(
    qt_app, tmp_path, monkeypatch
) -> None:
    """Spec §4: the job is made, and the review window says the image is gone."""
    import html

    from qurantext.gui.i18n import t
    from qurantext.gui.review.player import FakePlayer
    from qurantext.gui.review.window import ReviewWindow
    from qurantext.jobs.look_assets import project_look
    from qurantext.jobs.project import load_project

    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    gone = (tmp_path / "gone.png").resolve()
    look = _image_look(gone)

    project = jobs_module.run_matching(replace(spec, style=look.to_dict()))

    saved = load_project(project.path)
    assert project_look(saved) == look, "the look still names the image it could not copy"
    spec.audio.unlink()  # no recording to read in the background
    window = ReviewWindow(
        saved,
        player=FakePlayer(duration=2.0, now=lambda: 0.0),
        prefs=Prefs(QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)),
    )
    try:
        assert html.escape(t("look.image_missing")) in window.warnings.text()
    finally:
        window.deleteLater()


def test_a_rerun_with_unchanged_content_keeps_the_videos_own_look(tmp_path, monkeypatch) -> None:
    from qurantext.core.looks import PRESETS
    from qurantext.jobs.look_assets import project_look, set_project_look
    from qurantext.jobs.project import load_project, save_project

    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    first = jobs_module.run_matching(spec)
    own = load_project(first.path)
    set_project_look(own, PRESETS["emerald"])
    save_project(own, first.path)

    project = jobs_module.run_matching(replace(spec, style=PRESETS["sand"].to_dict()))

    assert not list(tmp_path.glob("*.qalun-backup.json")), "content unchanged"
    assert project_look(project) == PRESETS["emerald"]
    assert project_look(load_project(first.path)) == PRESETS["emerald"]


def test_a_rerun_with_changed_content_keeps_the_earlier_look_not_the_default(
    tmp_path, monkeypatch
) -> None:
    from qurantext.core.looks import NIGHT_GOLD, PRESETS
    from qurantext.jobs.look_assets import project_look
    from qurantext.jobs.project import load_project, save_project

    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    first = jobs_module.run_matching(spec)  # made before any default look: Night gold
    corrected = load_project(first.path)
    corrected.cards[0]["start_time"] = 0.25
    save_project(corrected, first.path)

    project = jobs_module.run_matching(replace(spec, style=PRESETS["sand"].to_dict()))

    assert list(tmp_path.glob("clip_recitation.*.qalun-backup.json")), "content changed"
    assert project_look(project) == NIGHT_GOLD
    assert load_project(first.path).style == {}


def test_start_renders_only_when_asked_to_right_away(tmp_path, monkeypatch) -> None:
    """The job Start runs: match, then render only when the job skips the review."""
    from qurantext.gui.main_window import _match_then_render

    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    seen = _capture_render_project(jobs_module, monkeypatch, tmp_path)

    result = _match_then_render(spec, progress=None, cancel=CancelToken())
    assert result.outcome is None and not seen
    assert result.project.path == jobs_module.project_path_for(tmp_path / "clip_recitation.json")

    result = _match_then_render(
        replace(spec, preset="fast", render_right_away=True), progress=None, cancel=CancelToken()
    )
    assert seen["preset"] == "fast"
    assert result.outcome is not None and result.outcome.video == tmp_path.resolve() / "clip.mp4"
    assert not hasattr(spec, "render"), "render_right_away is the one switch"


def test_a_cancel_between_matching_and_rendering_stops_before_the_render(
    tmp_path, monkeypatch
) -> None:
    from qurantext.gui import main_window as module

    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    seen = _capture_render_project(jobs_module, monkeypatch, tmp_path)
    cancel = CancelToken()
    real_matching = module.run_matching

    def matching_then_cancel(spec, **kwargs):
        project = real_matching(spec, **kwargs)
        cancel.cancel()
        return project

    monkeypatch.setattr(module, "run_matching", matching_then_cancel)
    with pytest.raises(JobCancelled):
        module._match_then_render(
            replace(spec, render_right_away=True), progress=None, cancel=cancel
        )
    assert not seen


# --- the home window ---------------------------------------------------------


def _card() -> dict:
    return {
        "surah_num": 25,
        "from_ayah": 7,
        "to_ayah": 7,
        "full_text": "a b",
        "confidence": 1.0,
        "start_time": 0.0,
        "end_time": 10.0,
        "word_timings": [
            {"word": "a", "start": 1.0, "end": 2.0},
            {"word": "b", "start": 2.0, "end": 3.0},
        ],
    }


def _saved_job(folder: Path, name: str = "clip") -> Path:
    """A matched job on disk: its match file and the project beside it."""
    from qurantext.jobs.project import Project, save_project

    folder.mkdir(parents=True, exist_ok=True)
    matches = folder / f"{name}_recitation.json"
    matches.write_text(
        json.dumps({"matches": [_card()], "meta": {"mode": "recitation"}}), encoding="utf-8"
    )
    return save_project(
        Project(audio=folder / f"{name}.mp3", cards=[_card()], matches=matches),
        folder / f"{name}_recitation.qalun.json",
    )


@pytest.fixture()
def prefs(tmp_path, no_default_job_dirs):
    """``Prefs`` on a throwaway INI; the job list sees only folders under tmp_path."""
    result = Prefs(QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat))
    result.job_dirs = [tmp_path / "jobs"]
    return result


def _fake_review_class(created: list, *, refuse_close: bool = False):
    """A stand-in for ``ReviewWindow`` with its two signals, recording each one made."""
    from PySide6.QtCore import QObject, Signal

    class FakeReview(QObject):
        saved = Signal(object)
        closed = Signal()

        def __init__(self, project, **kw):
            super().__init__()
            self.project = project
            self.shown = self.raised = self.activated = 0
            created.append(self)

        def show(self):
            self.shown += 1

        def raise_(self):
            self.raised += 1

        def activateWindow(self):  # noqa: N802 — Qt's name
            self.activated += 1

        def close(self):
            if refuse_close:
                return False
            self.closed.emit()
            return True

    return FakeReview


@pytest.fixture()
def reviews(monkeypatch):
    """Every review window the main window opens, as fakes."""
    from qurantext.gui import main_window as module

    created: list = []
    monkeypatch.setattr(module, "ReviewWindow", _fake_review_class(created))
    return created


@pytest.fixture()
def home(qt_app, prefs):
    from PySide6.QtCore import QEvent

    from qurantext.gui.main_window import MainWindow

    window = MainWindow(prefs=prefs)
    wait_until_listed(window.job_list)
    yield window
    window._jobs.stop()  # cancel and join anything a test left running
    window.job_list.stop_reading()
    window.deleteLater()
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _spin_until(qt_app, condition, timeout: float = 10.0) -> None:
    """Run the event loop until *condition* holds, so worker signals arrive."""
    import time

    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting"
        qt_app.processEvents()
        time.sleep(0.005)


def _run_start(qt_app, window, spec: JobSpec) -> None:
    """Press Start with *spec* and wait until the job has fully ended."""
    window.new_job.start_requested.emit(spec)
    _spin_until(qt_app, lambda: window._cancel is None)
    _spin_until(qt_app, lambda: window._jobs.active == 0)
    wait_until_listed(window.job_list)  # the refresh the job's end asked for
    qt_app.processEvents()


def _fake_matching(monkeypatch, calls: list | None = None, *, before=None):
    """Make ``run_matching`` write a project into the job's folder and return it."""
    from qurantext.gui import main_window as module
    from qurantext.jobs.project import load_project

    def fake(spec, *, progress=None, cancel=None, notices=None):
        if calls is not None:
            calls.append(spec)
        if before is not None:
            before(progress, cancel)
        return load_project(_saved_job(Path(spec.output_dir), Path(spec.audio).stem))

    monkeypatch.setattr(module, "run_matching", fake)


def _running_rows(window) -> list[str]:
    from PySide6.QtCore import Qt

    items = [window.job_list.list.item(i) for i in range(window.job_list.list.count())]
    return [
        window.job_list.list.itemWidget(i).label.text()
        for i in items
        if i.data(Qt.ItemDataRole.UserRole) is None
    ]


def test_the_home_window_is_the_job_list_beside_the_new_job_form(qt_app, home) -> None:
    from PySide6.QtWidgets import QSplitter

    from qurantext.gui.home.job_list import JobListPanel
    from qurantext.gui.home.new_job import NewJobPanel

    assert home.windowTitle() == "Qalun"
    splitter = home.centralWidget().findChild(QSplitter)
    assert isinstance(splitter.widget(0), JobListPanel)
    assert isinstance(splitter.widget(1), NewJobPanel)
    assert splitter.widget(0) is home.job_list and splitter.widget(1) is home.new_job

    # The fullest the form gets: every option open, and a job running.
    home.new_job.more_button.setChecked(True)
    home.new_job.subtitle_buttons["both"].setChecked(True)
    home.new_job.set_running(True)
    for size in (home.minimumSize(), home.minimumSizeHint()):
        assert size.width() <= 1024 and size.height() <= 680
    home.new_job.set_running(False)


def test_start_runs_matching_and_opens_its_review(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    from qurantext.gui import main_window as module

    calls: list = []
    _fake_matching(monkeypatch, calls)
    monkeypatch.setattr(module, "run_render", lambda *a, **k: pytest.fail("no render asked"))
    spec = _spec(tmp_path, output_dir=tmp_path / "jobs")

    _run_start(qt_app, home, spec)

    assert calls == [spec]
    assert [r.project.path for r in reviews] == [tmp_path / "jobs" / "a_recitation.qalun.json"]
    assert home.new_job.status_label.text() == "Matched 1 card. The review is open."


def test_a_finished_job_keeps_its_row_until_the_list_is_read(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    """The job's own row only comes with the read; until it lands the list must not
    lose the job, or (after a first job) say there are none."""
    from qurantext.gui.i18n import t

    _fake_matching(monkeypatch)
    release, _calls = blocking_list_jobs(monkeypatch)
    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=tmp_path / "jobs"))
    _spin_until(qt_app, lambda: home._cancel is None)
    _spin_until(qt_app, lambda: home._jobs.active == 0)
    qt_app.processEvents()

    panel = home.job_list
    assert panel.reading
    assert len(_running_rows(home)) == 1 and panel.list.count() == 1
    assert panel.empty_label.isHidden() and panel.empty_label.text() != t("home.empty")

    release.set()
    wait_until_listed(panel)
    assert _running_rows(home) == []
    assert panel.list.count() == 1, "the job's own row took its place"


def test_a_finished_job_whose_review_cannot_open_says_why(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    """The reason must outlive the job's ending message, not be replaced by it."""
    from qurantext.gui import main_window as module
    from qurantext.jobs.project import Project

    def gone(spec, *, progress=None, cancel=None, notices=None):
        project = Project(audio=Path(spec.audio), cards=[_card()])
        project.path = tmp_path / "gone.qalun.json"
        return project

    monkeypatch.setattr(module, "run_matching", gone)

    _run_start(qt_app, home, _spec(tmp_path, output_dir=tmp_path / "jobs"))

    assert reviews == []
    assert "gone.qalun.json" in home.new_job.status_label.text()


def test_render_right_away_also_renders_and_skips_the_review(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    from qurantext.gui import main_window as module
    from qurantext.gui.jobs import JobOutcome

    _fake_matching(monkeypatch)
    rendered: list = []

    def fake_render(project, *, progress=None, cancel=None):
        rendered.append(project.path)
        video = tmp_path / "a.mp4"
        return JobOutcome(matches=project.matches, video=video, cards=1)

    monkeypatch.setattr(module, "run_render", fake_render)

    _run_start(qt_app, home, _spec(tmp_path, output_dir=tmp_path / "jobs", render_right_away=True))

    assert rendered == [tmp_path / "jobs" / "a_recitation.qalun.json"]
    assert reviews == [], "render right away skips the review"
    assert home.new_job.status_label.text() == module.t(
        "home.finished.rendered", path=module.path_text(tmp_path / "a.mp4")
    )


def test_a_custom_output_folder_is_remembered_and_its_job_listed(
    qt_app, home, prefs, reviews, tmp_path, monkeypatch
) -> None:
    from PySide6.QtCore import Qt

    _fake_matching(monkeypatch)
    custom = tmp_path / "elsewhere"
    assert custom.resolve() not in prefs.job_dirs

    _run_start(qt_app, home, _spec(tmp_path, output_dir=custom))

    assert custom.resolve() in prefs.job_dirs
    listed = [
        home.job_list.list.item(i).data(Qt.ItemDataRole.UserRole).project
        for i in range(home.job_list.list.count())
    ]
    assert listed == [custom / "a_recitation.qalun.json"]


def test_the_running_row_shows_during_the_job_and_goes_after(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    import threading

    release = threading.Event()

    def report_then_wait(progress, cancel):
        progress(ProgressEvent("align", "Aligning", fraction=0.4))
        assert release.wait(10)

    _fake_matching(monkeypatch, before=report_then_wait)
    _saved_job(tmp_path / "jobs", "earlier")
    home.job_list.refresh()
    wait_until_listed(home.job_list)
    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=tmp_path / "jobs"))

    _spin_until(qt_app, lambda: any("40%" in text for text in _running_rows(home)))
    assert _running_rows(home)[0].startswith("\u2068a.mp3\u2069")  # the name, isolated
    assert "40%" in home.new_job.status_label.text()

    release.set()
    _spin_until(qt_app, lambda: home._cancel is None)
    _spin_until(qt_app, lambda: home._jobs.active == 0)
    wait_until_listed(home.job_list)
    assert _running_rows(home) == []
    assert home.job_list.list.count() == 2, "the earlier job, and the new one from disk"


def test_the_status_line_says_each_stage_in_the_window_s_words(qt_app, home) -> None:
    """The pipeline's log lines are English and never shown; the window names the stage."""
    from qurantext.gui import main_window as module

    status = home.new_job.status_label
    home._on_progress(ProgressEvent("detect", "[1/3] Parsing Quran text: /x/quran.txt"))
    assert status.text() == module.t("job.stage.detect")
    home._on_progress(ProgressEvent("render", "Building ASS subtitles..."))
    assert status.text() == module.t("job.stage.render")
    home._on_progress(ProgressEvent("export", "Writing subtitle files..."))
    assert status.text() == module.t("job.stage.export")
    home._on_progress(ProgressEvent("tuning", "Something new..."))
    assert status.text() == module.t("job.stage.working")
    # With a fraction the line is the table's percentage sentence, as before.
    home._on_progress(ProgressEvent("render", "  Segments 4/10", fraction=0.4))
    assert status.text() == module.t("home.progress.rendering", percent=40)


@pytest.mark.parametrize("language", ["en", "ar"])
def test_the_model_download_says_its_own_stage_not_matching(qt_app, home, language) -> None:
    """The first local job downloads the model inside the matching stage; it says so."""
    from qurantext.gui import i18n
    from qurantext.gui import main_window as module

    i18n.set_language(language)
    try:
        status = home.new_job.status_label
        matching = module.t("home.progress.matching", percent=12)
        home._on_progress(
            ProgressEvent("detect", module.t("job.progress.detecting"), translated=True)
        )
        # The store's first event carries no fraction, so the stage's sentence shows.
        home._on_progress(ProgressEvent("download", "Downloading the speech model, once..."))
        assert status.text() == module.t("job.stage.download")
        home._on_progress(
            ProgressEvent("download", "12 MB of 108 MB", fraction=0.12, eta_seconds=95)
        )
        assert status.text() == module.t(
            "home.progress.downloading_eta", percent=12, eta=module._minutes(95)
        )
        assert matching.split("—")[0].strip() not in status.text()
        home._on_progress(ProgressEvent("download", "Downloaded.", fraction=1.0, done=True))
        assert status.text() == module.t("home.progress.downloading", percent=100)
        home._on_progress(ProgressEvent("unpack", "Unpacking and checking the speech model..."))
        assert status.text() == module.t("job.stage.unpack")
        # Back to matching: its own sentence again, then its own percentage.
        home._on_progress(ProgressEvent("detect", "[2/3] Aligning 12 ayat..."))
        assert status.text() == module.t("job.stage.detect")
        home._on_progress(ProgressEvent("detect", "x", fraction=0.12))
        assert status.text() == matching
    finally:
        i18n.set_language("en")


@pytest.mark.parametrize("language", ["en", "ar"])
def test_local_transcription_says_its_own_stage_not_matching(qt_app, home, language) -> None:
    """Recognising on this computer is the long step of a local job; it says so, with its ETA."""
    from qurantext.gui import i18n
    from qurantext.gui import main_window as module

    i18n.set_language(language)
    try:
        status = home.new_job.status_label
        matching = module.t("home.progress.matching", percent=40)
        # The events engine_local.transcribe_local sends: first the stage, before the model loads.
        home._on_progress(ProgressEvent("transcribe", "Transcribing on this computer..."))
        assert status.text() == module.t("job.stage.transcribe")
        home._on_progress(
            ProgressEvent(
                "transcribe",
                "Transcribing on this computer: 4:00 of 10:00",
                fraction=0.4,
                eta_seconds=95,
            )
        )
        assert status.text() == module.t(
            "home.progress.transcribing_eta", percent=40, eta=module._minutes(95)
        )
        assert matching.split("—")[0].strip() not in status.text()
        home._on_progress(
            ProgressEvent("transcribe", "Transcribed on this computer.", fraction=1.0, done=True)
        )
        assert status.text() == module.t("home.progress.transcribing", percent=100)
    finally:
        i18n.set_language("en")


def test_the_download_sentence_says_the_pinned_size_rounded() -> None:
    from qurantext.gui import i18n
    from qurantext.services.model_store import LOCAL_MODEL

    assert LOCAL_MODEL.download_mb == 110
    assert "(about 110 MB)" in i18n.STRINGS["en"]["job.stage.download"]
    assert "(نحو 110 ميغابايت)" in i18n.STRINGS["ar"]["job.stage.download"]


def test_the_window_s_own_progress_sentences_are_shown_as_they_are(qt_app, home) -> None:
    """``gui/jobs.py`` marks what it already said in the window's language, and it stays up."""
    from qurantext.gui import main_window as module

    status = home.new_job.status_label
    aligning = module.t("job.progress.aligning")
    home._on_progress(ProgressEvent("detect", aligning, translated=True))
    assert status.text() == aligning
    home._on_progress(ProgressEvent("detect", "[2/3] Aligning 12 ayat..."))
    assert status.text() == aligning, "a log line of the same stage does not replace it"


def test_every_stage_the_pipeline_reports_has_its_own_sentence() -> None:
    """A stage added to the pipeline without a sentence would only ever say "Working…"."""
    import re

    from qurantext.gui import main_window as module
    from qurantext.jobs import export as export_job
    from qurantext.jobs import render as render_job

    source = Path(module.__file__).resolve().parents[1]
    reported = {export_job.STAGE, render_job.STAGE}
    for path in source.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        reported |= set(re.findall(r"""report\(\s*progress,\s*["']([a-z_]+)["']""", text))
    assert reported, "the scan found no stage"
    assert reported <= module._KNOWN_STAGES, sorted(reported - module._KNOWN_STAGES)


def test_cancel_says_so_in_the_status_line_without_a_dialog(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    from qurantext.gui import main_window as module

    started = []

    def wait_for_cancel(progress, cancel):
        started.append(True)
        for _ in range(1000):
            cancel.raise_if_cancelled("detect")
            __import__("time").sleep(0.01)

    _fake_matching(monkeypatch, before=wait_for_cancel)
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *a: pytest.fail("no dialog"))
    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=tmp_path / "jobs"))
    _spin_until(qt_app, lambda: started)

    home.new_job.cancel_requested.emit()
    _spin_until(qt_app, lambda: home._cancel is None)
    _spin_until(qt_app, lambda: home._jobs.active == 0)

    assert home.new_job.status_label.text() == module.t("home.cancelled")
    assert not home.new_job.start_button.isHidden() and home.new_job.cancel_button.isHidden()
    assert reviews == [] and _running_rows(home) == []


def test_a_failure_says_what_went_wrong(qt_app, home, reviews, tmp_path, monkeypatch) -> None:
    from qurantext.gui import main_window as module
    from qurantext.gui.i18n import t

    def fail(progress, cancel):
        raise RuntimeError("the recogniser is unreachable")

    _fake_matching(monkeypatch, before=fail)
    warned: list = []
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *a: warned.append(a))

    _run_start(qt_app, home, _spec(tmp_path, output_dir=tmp_path / "jobs"))

    assert "the recogniser is unreachable" in home.new_job.status_label.text()
    assert warned and reviews == [] and _running_rows(home) == []
    # The box frames the worker's words in a sentence of the window's language.
    _parent, title, body = warned[0]
    assert title == t("home.failed.title")
    assert body == t("home.failed", details="the recogniser is unreachable")


class _NoOpThread:
    """Stands in for the ``QThread`` a real job would return, so the fixture's
    teardown (``BackgroundJobs.stop()``) has something harmless to join."""

    def quit(self) -> None:
        pass

    def wait(self, _ms: int = 0) -> bool:
        return True

    def isFinished(self) -> bool:
        return True


def test_every_worker_callback_is_a_method_of_the_window(qt_app, home, monkeypatch) -> None:
    """A bare lambda connected to a worker signal would run on the worker thread."""
    import inspect

    from qurantext.gui.review import background as background_module

    seen: dict = {}
    monkeypatch.setattr(
        background_module,
        "run_in_thread",
        lambda job, cancel, **callbacks: seen.update(callbacks) or (_NoOpThread(), None),
    )
    home._start(JobSpec(audio=Path(__file__), quran=QURAN_FILE, mode="lecture"))

    assert set(seen) == {"on_progress", "on_finished", "on_failed", "on_cancelled", "on_done"}
    for callback in seen.values():
        assert inspect.ismethod(callback) and callback.__self__ is home


def test_double_clicking_a_job_opens_its_review(qt_app, prefs, reviews, tmp_path) -> None:
    from qurantext.gui.main_window import MainWindow

    project_path = _saved_job(tmp_path / "jobs")
    window = MainWindow(prefs=prefs)
    wait_until_listed(window.job_list)

    window.job_list.list.itemActivated.emit(window.job_list.list.item(0))

    assert [r.project.path for r in reviews] == [project_path]


def test_double_clicking_a_damaged_job_shows_its_error(qt_app, prefs, reviews, tmp_path) -> None:
    from qurantext.gui.main_window import MainWindow

    (tmp_path / "jobs").mkdir()
    (tmp_path / "jobs" / "broken.qalun.json").write_text("{not json", encoding="utf-8")
    window = MainWindow(prefs=prefs)
    window.show()
    wait_until_listed(window.job_list)

    item = window.job_list.list.item(0)
    window.job_list.list.itemActivated.emit(item)

    assert reviews == []
    assert window.new_job.status_label.isVisible()
    assert item.statusTip() in window.new_job.status_label.text()
    window.close()


def test_show_in_folder_reveals_the_project(qt_app, home, monkeypatch, tmp_path) -> None:
    from qurantext.gui import main_window as module

    revealed: list = []
    monkeypatch.setattr(module, "show_in_folder", revealed.append)
    home.job_list.reveal(tmp_path / "x.qalun.json")
    assert revealed == [tmp_path / "x.qalun.json"]


def test_a_review_that_saves_or_closes_refreshes_the_list(qt_app, home, reviews, tmp_path) -> None:
    first = _saved_job(tmp_path / "jobs", "first")
    home.job_list.refresh()
    wait_until_listed(home.job_list)
    home._open_review(first)
    assert home.job_list.list.count() == 1

    _saved_job(tmp_path / "jobs", "second")
    reviews[0].saved.emit(first)
    wait_until_listed(home.job_list)
    assert home.job_list.list.count() == 2

    _saved_job(tmp_path / "jobs", "third")
    reviews[0].close()
    wait_until_listed(home.job_list)
    assert home.job_list.list.count() == 3


# --- the review windows the home window opens ------------------------------


def test_review_opens_the_jobs_project(qt_app, home, reviews, tmp_path) -> None:
    project_path = _saved_job(tmp_path / "jobs")
    home._open_review(project_path)
    assert [r.project.path for r in reviews] == [project_path]


def test_reopening_the_same_project_raises_the_existing_window(
    qt_app, home, reviews, tmp_path
) -> None:
    project_path = _saved_job(tmp_path / "jobs")
    home._open_review(project_path)
    home._open_review(project_path)

    assert len(reviews) == 1
    # Opened once, then re-shown, raised and activated on the second call.
    assert reviews[0].shown == 2
    assert reviews[0].raised == 1
    assert reviews[0].activated == 1


def test_a_project_that_cannot_be_read_says_so_without_a_review(
    qt_app, home, reviews, tmp_path
) -> None:
    home._open_review(tmp_path / "gone.qalun.json")
    assert reviews == []
    assert "gone.qalun.json" in home.new_job.status_label.text()


def test_a_review_window_that_refuses_to_close_keeps_the_main_window_open(
    qt_app, prefs, tmp_path, monkeypatch
) -> None:
    from qurantext.gui import main_window as module

    monkeypatch.setattr(module, "ReviewWindow", _fake_review_class([], refuse_close=True))
    window = module.MainWindow(prefs=prefs)
    window._open_review(_saved_job(tmp_path / "jobs"))
    window.show()

    window.close()

    assert window.isVisible()


def _blocked_until(release, seen: list | None = None, *, finish=None):
    """A matching job that waits for *release*, then stops on its cancel token.

    With *finish* given it ignores the token and returns *finish(spec)* instead,
    like a model call that never looks at it.
    """

    def blocked(spec, *, progress=None, cancel=None, notices=None):
        assert release.wait(timeout=10), "the test forgot to release the job"
        if seen is not None:
            seen.append(cancel.cancelled)
        if finish is not None:
            return finish(spec)
        cancel.raise_if_cancelled("detect")
        pytest.fail("the job should have been cancelled, not left to finish")

    return blocked


def _record_quits(monkeypatch) -> list:
    from qurantext.gui import main_window as module

    quits: list = []
    monkeypatch.setattr(module.QApplication, "quit", staticmethod(lambda: quits.append(True)))
    return quits


def test_closing_the_window_while_a_job_runs_hides_it_and_quits_once_the_job_ends(
    qt_app, home, tmp_path, monkeypatch
) -> None:
    """The job is cancelled and the window goes, but the app waits for the thread.

    Quitting at once would destroy a ``QThread`` still running a model call
    that never checks its token, which aborts the process on exit.
    """
    import threading

    from qurantext.gui import main_window as module

    release = threading.Event()
    seen: list = []
    monkeypatch.setattr(module, "run_matching", _blocked_until(release, seen))
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *a: pytest.fail("no dialog"))
    quits = _record_quits(monkeypatch)

    home.show()
    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=tmp_path / "jobs"))
    _spin_until(qt_app, lambda: home._cancel is not None)

    assert not home.close(), "the close waits for the job"
    assert not home.isVisible()
    qt_app.processEvents()
    assert quits == [], "not while the job still runs"

    release.set()
    _spin_until(qt_app, lambda: quits)
    assert seen == [True], "the job was told to stop"
    assert home._jobs.active == 0, "its thread was joined before quitting"


def test_a_job_that_finishes_during_the_close_opens_no_review(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    import threading

    from qurantext.gui import main_window as module
    from qurantext.jobs.project import load_project

    release = threading.Event()
    finish = _blocked_until(
        release,
        finish=lambda spec: module._Finished(
            load_project(_saved_job(Path(spec.output_dir), Path(spec.audio).stem))
        ),
    )
    monkeypatch.setattr(module, "_match_then_render", finish)
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *a: pytest.fail("no dialog"))
    quits = _record_quits(monkeypatch)

    home.show()
    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=tmp_path / "jobs"))
    _spin_until(qt_app, lambda: home._cancel is not None)
    home.close()
    release.set()
    _spin_until(qt_app, lambda: quits)

    assert reviews == [], "no review opens under a window that is closing"


def test_a_job_that_fails_during_the_close_shows_no_dialog(
    qt_app, home, tmp_path, monkeypatch
) -> None:
    import threading

    from qurantext.gui import main_window as module

    release = threading.Event()

    def fail(spec):
        raise RuntimeError("finished late")

    monkeypatch.setattr(module, "run_matching", _blocked_until(release, finish=fail))
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *a: pytest.fail("no dialog"))
    quits = _record_quits(monkeypatch)

    home.show()
    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=tmp_path / "jobs"))
    _spin_until(qt_app, lambda: home._cancel is not None)
    home.close()
    release.set()
    _spin_until(qt_app, lambda: quits)


def test_a_job_finishing_after_close_still_lists_its_folder_and_unhides_it(
    qt_app, home, prefs, reviews, tmp_path, monkeypatch
) -> None:
    """The window is going, but the next launch must still list the job it ran."""
    import threading

    from qurantext.gui import main_window as module
    from qurantext.jobs.project import load_project

    out = tmp_path / "out"
    project_path = _saved_job(out, "a")
    prefs.hide_job(project_path)
    release = threading.Event()
    finish = _blocked_until(
        release,
        finish=lambda spec: module._Finished(
            load_project(_saved_job(Path(spec.output_dir), Path(spec.audio).stem))
        ),
    )
    monkeypatch.setattr(module, "_match_then_render", finish)
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *a: pytest.fail("no dialog"))
    quits = _record_quits(monkeypatch)

    home.show()
    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=out))
    _spin_until(qt_app, lambda: home._cancel is not None)
    home.close()
    release.set()
    _spin_until(qt_app, lambda: quits)

    assert out.resolve() in prefs.job_dirs
    assert project_path.resolve() not in prefs.hidden_jobs
    assert home._reviews == {} and reviews == [], "still no review under a closed window"


@pytest.mark.parametrize("ending", ["fails", "is cancelled"])
def test_a_render_right_away_stopping_after_close_still_lists_its_folder(
    qt_app, home, prefs, reviews, tmp_path, monkeypatch, ending
) -> None:
    """Matching saved the project before the render stopped; closing must not lose its folder."""
    import threading

    from qurantext.gui import main_window as module

    release = threading.Event()
    _fake_matching(monkeypatch)

    def render(project, *, progress=None, cancel=None):
        assert release.wait(timeout=10), "the test forgot to release the render"
        if ending == "fails":
            raise RuntimeError("the encoder gave up")
        raise JobCancelled("render")

    monkeypatch.setattr(module, "run_render", render)
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *a: pytest.fail("no dialog"))
    quits = _record_quits(monkeypatch)
    custom = tmp_path / "elsewhere"

    home.show()
    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=custom, render_right_away=True))
    _spin_until(qt_app, lambda: home._cancel is not None)
    home.close()
    release.set()
    _spin_until(qt_app, lambda: quits)

    assert custom.resolve() in prefs.job_dirs


def test_opening_the_review_of_a_job_being_matched_again_is_refused(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    """Its file is about to be replaced: a review now would show, and save over, the old match."""
    import threading

    from qurantext.gui import main_window as module

    release = threading.Event()
    project_path = _saved_job(tmp_path / "jobs", "a")

    def wait_for_release(progress, cancel):
        assert release.wait(timeout=10), "the test forgot to release the job"

    _fake_matching(monkeypatch, before=wait_for_release)
    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=tmp_path / "jobs"))
    _spin_until(qt_app, lambda: home._cancel is not None)

    home._open_review(project_path)

    assert home._reviews == {} and reviews == []
    assert home.new_job.status_label.text() == module.t("home.busy_matching")

    release.set()
    _spin_until(qt_app, lambda: home._cancel is None)
    _spin_until(qt_app, lambda: home._jobs.active == 0)
    assert home._review_of(project_path) is not None, "once matched, its review opens as usual"


@pytest.fixture()
def real_reviews(qt_app, prefs, monkeypatch):
    """The main window's real review window, with a fake player; closed after the test."""
    from PySide6.QtCore import QEvent

    from qurantext.gui import main_window as module
    from qurantext.gui.review.player import FakePlayer

    real = module.ReviewWindow
    monkeypatch.setattr(
        module,
        "ReviewWindow",
        lambda project, **kw: real(project, player=FakePlayer(duration=10.0), **kw),
    )
    main = module.MainWindow(prefs=prefs)
    yield main
    for window in list(main._reviews.values()):
        window._confirm_discard = lambda: "discard"
        window.close()
    main.deleteLater()
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _edit_first_word(review) -> None:
    from qurantext.gui.review.session import CARD, WordRef

    review.session.retime(WordRef(CARD, 0, 0), end=2.5)
    review._after_edit()


def test_discard_then_reopen_shows_the_saved_state(qt_app, tmp_path, real_reviews) -> None:
    from PySide6.QtCore import QEvent

    project_path = _saved_job(tmp_path / "jobs")
    real_reviews._open_review(project_path)
    first = real_reviews._reviews[project_path]
    _edit_first_word(first)
    first._confirm_discard = lambda: "discard"
    assert first.close()
    assert project_path not in real_reviews._reviews
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    real_reviews._open_review(project_path)
    second = real_reviews._reviews[project_path]
    assert not second.session.dirty
    assert not second.windowTitle().endswith("*")
    assert second.session.words()[0].end == 2.0


def test_a_change_on_disk_between_close_and_reopen_is_shown(qt_app, tmp_path, real_reviews) -> None:
    from qurantext.jobs.project import load_project, save_project

    project_path = _saved_job(tmp_path / "jobs")
    real_reviews._open_review(project_path)
    assert real_reviews._reviews[project_path].close()

    on_disk = load_project(project_path)
    on_disk.review = {"state": "reviewed", "reviewed_at": "2026-09-23T00:00:00"}
    save_project(on_disk, project_path)

    real_reviews._open_review(project_path)
    assert real_reviews._reviews[project_path].session.project.review["state"] == "reviewed"


def test_opening_twice_while_open_keeps_one_window(qt_app, tmp_path, real_reviews) -> None:
    project_path = _saved_job(tmp_path / "jobs")
    real_reviews._open_review(project_path)
    first = real_reviews._reviews[project_path]
    real_reviews._open_review(project_path)
    assert real_reviews._reviews[project_path] is first
    assert len(real_reviews._reviews) == 1


def test_the_project_path_a_spec_will_write_is_beside_its_match_file(tmp_path) -> None:
    from qurantext.gui.jobs import match_path_for
    from qurantext.jobs.project import project_path_for

    spec = _spec(tmp_path, output_dir=tmp_path / "jobs")
    assert match_path_for(spec) == tmp_path / "jobs" / "a_recitation.json"
    assert project_path_for(match_path_for(spec)) == tmp_path / "jobs" / "a_recitation.qalun.json"


def test_a_job_whose_review_is_open_is_not_run_again(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    """Re-matching would replace the project under unsaved corrections in its review."""
    calls: list = []
    _fake_matching(monkeypatch, calls)
    project_path = _saved_job(tmp_path / "jobs", "a")
    home._open_review(project_path)

    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=tmp_path / "jobs"))
    qt_app.processEvents()

    assert calls == [] and home._cancel is None
    assert (
        home.new_job.status_label.text() == "Close the review of this job before running it again."
    )
    assert reviews[0].raised == 1 and reviews[0].activated == 1

    reviews[0].close()
    _run_start(qt_app, home, _spec(tmp_path, output_dir=tmp_path / "jobs"))
    assert len(calls) == 1, "once its review is closed, the job runs"


def test_rerunning_a_removed_job_lists_it_again(
    qt_app, home, prefs, reviews, tmp_path, monkeypatch
) -> None:
    from PySide6.QtCore import Qt

    _fake_matching(monkeypatch)
    project_path = _saved_job(tmp_path / "jobs", "a")
    home.job_list.refresh()
    home.job_list.remove_from_list(project_path)
    wait_until_listed(home.job_list)
    assert home.job_list.list.count() == 0

    _run_start(qt_app, home, _spec(tmp_path, output_dir=tmp_path / "jobs"))

    listed = [
        home.job_list.list.item(i).data(Qt.ItemDataRole.UserRole).project
        for i in range(home.job_list.list.count())
    ]
    assert listed == [project_path]
    assert project_path.resolve() not in prefs.hidden_jobs


@pytest.mark.parametrize("ending", ["fails", "is cancelled"])
def test_a_render_right_away_that_does_not_finish_still_lists_the_matched_job(
    qt_app, home, prefs, reviews, tmp_path, monkeypatch, ending
) -> None:
    """Matching wrote the project before the render stopped; the list must show it."""
    from PySide6.QtCore import Qt

    from qurantext.gui import main_window as module
    from qurantext.utils.progress import JobCancelled

    _fake_matching(monkeypatch)

    def render(project, *, progress=None, cancel=None):
        if ending == "fails":
            raise RuntimeError("the encoder gave up")
        raise JobCancelled("render")

    monkeypatch.setattr(module, "run_render", render)
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *a: None)
    custom = tmp_path / "elsewhere"

    _run_start(qt_app, home, _spec(tmp_path, output_dir=custom, render_right_away=True))

    listed = [
        home.job_list.list.item(i).data(Qt.ItemDataRole.UserRole).project
        for i in range(home.job_list.list.count())
    ]
    assert listed == [custom / "a_recitation.qalun.json"]
    assert custom.resolve() in prefs.job_dirs


def test_the_app_names_itself_before_any_settings_are_read(qt_app) -> None:
    """``Prefs()`` uses a default ``QSettings``, whose file is named after these."""
    from qurantext.gui import app as app_module

    before = (QCoreApplication.organizationName(), QCoreApplication.applicationName())
    try:
        app_module._name_the_app()
        assert QCoreApplication.organizationName() == "Qalun"
        assert QCoreApplication.applicationName() == "Qalun"
    finally:
        QCoreApplication.setOrganizationName(before[0])
        QCoreApplication.setApplicationName(before[1])


# --- the window's language -----------------------------------------------------


def test_switching_to_arabic_rebuilds_the_home_window(
    qt_app, home, prefs, tmp_path, monkeypatch
) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QLabel

    from qurantext.gui import i18n
    from qurantext.gui.home.new_job import NewJobPanel
    from qurantext.gui.main_window import MainWindow

    audio = tmp_path / "a.mp3"
    audio.touch()
    home.new_job.set_audio(audio)
    home.new_job.surah_box.setCurrentIndex(24)  # Al-Furqan
    home.new_job.from_spin.setValue(7)
    home.new_job.to_spin.setValue(11)
    surah = home.new_job.surah_box.currentData()
    started: list = []
    # Patched before the rebuild, so the new panel's connection is the one counted.
    monkeypatch.setattr(MainWindow, "_start", lambda self, spec: started.append(spec))

    assert home.set_language("ar")
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert prefs.language == "ar"
    assert home.job_list.findChild(QLabel).text() == i18n.STRINGS["ar"]["home.jobs"]  # rebuilt
    assert home.new_job.audio_path == audio  # the half-filled form survives
    assert home.new_job.surah_box.currentData() == surah
    assert (home.new_job.from_spin.value(), home.new_job.to_spin.value()) == (7, 11)
    assert home.language_combo.currentData() == "ar"
    assert len(home.findChildren(NewJobPanel)) == 1, "the old panel is gone"
    spec = _spec(tmp_path)
    home.new_job.start_requested.emit(spec)
    assert started == [spec], "the new panel is wired once"

    assert home.set_language("en")
    assert prefs.language == "en"
    assert home.job_list.findChild(QLabel).text() == i18n.STRINGS["en"]["home.jobs"]
    assert home.language_combo.currentData() == "en"


def test_choosing_a_language_in_the_combo_switches_to_it(qt_app, home, prefs) -> None:
    from qurantext.gui import i18n

    index = home.language_combo.findData("ar")
    home.language_combo.setCurrentIndex(index)
    home.language_combo.activated.emit(index)

    assert i18n.current_language() == "ar"
    assert prefs.language == "ar"


def test_choosing_the_language_already_shown_is_remembered(qt_app, home, prefs) -> None:
    assert prefs.language is None  # following the system
    assert home.set_language("en")
    assert prefs.language == "en"


def test_a_rebuild_keeps_the_window_size(qt_app, home) -> None:
    home.resize(900, 600)
    home.set_language("ar")
    assert (home.width(), home.height()) == (900, 600)


def test_the_language_does_not_change_while_a_review_is_open(
    qt_app, home, prefs, reviews, tmp_path
) -> None:
    from qurantext.gui import i18n
    from qurantext.gui import main_window as module

    home._open_review(_saved_job(tmp_path / "jobs"))
    assert reviews, "the review should have opened"

    index = home.language_combo.findData("ar")
    home.language_combo.setCurrentIndex(index)  # what the person picked
    assert not home.set_language("ar")

    assert i18n.current_language() == "en"
    assert prefs.language is None
    assert home.new_job.status_label.text() == module.t("home.language_busy")
    assert home.language_combo.currentData() == "en"  # the combo snaps back


def test_the_language_does_not_change_while_a_job_runs(
    qt_app, home, prefs, reviews, tmp_path, monkeypatch
) -> None:
    import threading

    from qurantext.gui import i18n
    from qurantext.gui import main_window as module

    release = threading.Event()

    def wait_for_release(progress, cancel):
        assert release.wait(timeout=10), "the test forgot to release the job"

    _fake_matching(monkeypatch, before=wait_for_release)
    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=tmp_path / "jobs"))
    _spin_until(qt_app, lambda: home._cancel is not None)
    try:
        home.language_combo.setCurrentIndex(home.language_combo.findData("ar"))
        assert not home.set_language("ar")

        assert i18n.current_language() == "en"
        assert home.new_job.status_label.text() == module.t("home.language_busy")
        assert home.language_combo.currentData() == "en"
    finally:
        release.set()
        _spin_until(qt_app, lambda: home._cancel is None)
        _spin_until(qt_app, lambda: home._jobs.active == 0)


def test_the_language_combo_is_off_while_a_review_is_open(qt_app, home, reviews, tmp_path) -> None:
    """Offered only when a switch would be allowed; the tooltip says why not."""
    from qurantext.gui import main_window as module

    assert home.language_combo.isEnabled() and home.language_combo.toolTip() == ""
    home._open_review(_saved_job(tmp_path / "jobs"))
    assert not home.language_combo.isEnabled()
    assert home.language_combo.toolTip() == module.t("home.language_busy")

    reviews[0].close()
    assert home.language_combo.isEnabled() and home.language_combo.toolTip() == ""


def test_the_language_combo_is_off_while_a_job_runs(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    import threading

    release = threading.Event()

    def wait_for_release(progress, cancel):
        assert release.wait(timeout=10), "the test forgot to release the job"

    _fake_matching(monkeypatch, before=wait_for_release)
    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=tmp_path / "jobs"))
    _spin_until(qt_app, lambda: home._cancel is not None)
    try:
        assert not home.language_combo.isEnabled()
    finally:
        release.set()
        _spin_until(qt_app, lambda: home._cancel is None)
        _spin_until(qt_app, lambda: home._jobs.active == 0)
    for review in list(reviews):  # the finished job opened its review
        review.close()
    assert home.language_combo.isEnabled()


def test_a_refusal_stays_up_until_the_job_s_stage_changes(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    """Progress of the same stage moves the bar, but does not wipe the refusal."""
    import threading

    from qurantext.gui import main_window as module

    release = threading.Event()
    project_path = _saved_job(tmp_path / "jobs", "a")

    def wait_for_release(progress, cancel):
        assert release.wait(timeout=10), "the test forgot to release the job"

    _fake_matching(monkeypatch, before=wait_for_release)
    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=tmp_path / "jobs"))
    _spin_until(qt_app, lambda: home._cancel is not None)
    status = home.new_job.status_label
    try:
        home._on_progress(ProgressEvent("match", "Scanning..."))
        home._open_review(project_path)
        refused = module.t("home.busy_matching")
        assert status.text() == refused

        home._on_progress(ProgressEvent("match", "  Matching word 10/40", fraction=0.25))
        assert status.text() == refused
        assert home.new_job.progress_bar.value() == 25, "the bar still moves"
        assert any("25%" in row for row in _running_rows(home)), "and so does the job's row"
        home._on_progress(ProgressEvent("match", "a log line"))
        home._on_progress(ProgressEvent("match", "kept", translated=True))
        assert status.text() == refused

        home._on_progress(ProgressEvent("render", "Building ASS subtitles..."))
        assert status.text() == module.t("job.stage.render")
    finally:
        release.set()
        _spin_until(qt_app, lambda: home._cancel is None)
        _spin_until(qt_app, lambda: home._jobs.active == 0)


def test_a_language_switch_says_the_last_status_again_and_keeps_the_focus(
    qt_app, home, tmp_path
) -> None:
    from qurantext.gui import i18n

    saved = tmp_path / "jobs" / "a_recitation.qalun.json"
    home._review_saved(saved)
    home.language_combo.setFocus()

    assert home.set_language("ar")

    status = home.new_job.status_label
    assert status.text() == i18n.t("main.saved", path=i18n.path_text(saved))  # in Arabic
    assert not status.isHidden()
    assert home.focusWidget() is home.language_combo


def test_a_status_said_from_raw_text_is_cleared_by_a_language_switch(qt_app, home) -> None:
    """Only a sentence kept as its key can be said again; anything else would stay English."""
    home._on_progress(ProgressEvent("detect", "Already in English", translated=True))
    assert home.new_job.status_label.text() == "Already in English"

    assert home.set_language("ar")

    assert home.new_job.status_label.text() == ""
    assert home.new_job.status_label.isHidden()


def test_a_refusal_made_before_the_first_progress_event_stays_up(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    """The job's first event is not a change of stage: nothing had been reported yet."""
    import threading

    from qurantext.gui import main_window as module

    release = threading.Event()
    project_path = _saved_job(tmp_path / "jobs", "a")

    def wait_for_release(progress, cancel):
        assert release.wait(timeout=10), "the test forgot to release the job"

    _fake_matching(monkeypatch, before=wait_for_release)
    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=tmp_path / "jobs"))
    _spin_until(qt_app, lambda: home._cancel is not None)
    status = home.new_job.status_label
    try:
        home._open_review(project_path)
        refused = module.t("home.busy_matching")
        assert status.text() == refused

        home._on_progress(ProgressEvent("detect", "Scanning..."))
        assert status.text() == refused

        home._on_progress(ProgressEvent("render", "Building ASS subtitles..."))
        assert status.text() == module.t("job.stage.render"), "a later stage still replaces it"
    finally:
        release.set()
        _spin_until(qt_app, lambda: home._cancel is None)
        _spin_until(qt_app, lambda: home._jobs.active == 0)


def test_the_running_row_names_the_stage_before_any_percentage(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    """Not "Starting…" for the whole of a stage that reports no fraction."""
    import threading

    from qurantext.gui import main_window as module

    release = threading.Event()

    def wait_for_release(progress, cancel):
        assert release.wait(timeout=10), "the test forgot to release the job"

    _fake_matching(monkeypatch, before=wait_for_release)
    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=tmp_path / "jobs"))
    _spin_until(qt_app, lambda: home._cancel is not None)
    try:
        home._on_progress(ProgressEvent("detect", "Scanning...", fraction=None))
        assert module.t("job.stage.detect") in _running_rows(home)[0]

        home._on_progress(ProgressEvent("detect", "  word 10/40", fraction=0.25))
        assert "25%" in _running_rows(home)[0], "a percentage still shows as before"
    finally:
        release.set()
        _spin_until(qt_app, lambda: home._cancel is None)
        _spin_until(qt_app, lambda: home._jobs.active == 0)


def test_the_engine_choice_reaches_the_pipeline(tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module

    seen = {}

    def fake_range(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop")

    monkeypatch.setattr(jobs_module, "run_recitation_range", fake_range)
    with pytest.raises(RuntimeError, match="stop"):
        jobs_module.run_matching(_spec(tmp_path, engine="whisperx"))
    assert seen["engine"] == "whisperx"


def test_the_engine_choice_reaches_detection_too(tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module

    seen = {}

    def fake_detection(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop")

    monkeypatch.setattr(jobs_module, "run_detection", fake_detection)
    spec = _spec(tmp_path, mode="lecture", surah_num=None, from_ayah=None, to_ayah=None)
    with pytest.raises(RuntimeError, match="stop"):
        jobs_module.run_matching(replace(spec, engine="whisperx"))
    assert seen["engine"] == "whisperx"


def test_a_spec_transcribes_locally_unless_told_otherwise(tmp_path) -> None:
    assert _spec(tmp_path).engine == "local"


def test_render_right_away_says_what_the_look_could_not_do(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    from qurantext.gui import main_window as module
    from qurantext.gui.jobs import JobOutcome

    _fake_matching(monkeypatch)

    def fake_render(project, *, progress=None, cancel=None):
        return JobOutcome(
            matches=project.matches,
            video=tmp_path / "a.mp4",
            cards=1,
            look_warnings=("image_missing",),
        )

    monkeypatch.setattr(module, "run_render", fake_render)

    _run_start(qt_app, home, _spec(tmp_path, output_dir=tmp_path / "jobs", render_right_away=True))

    rendered = module.t("home.finished.rendered", path=module.path_text(tmp_path / "a.mp4"))
    said = home.new_job.status_label.text()
    assert said == f"{rendered} {module.t('look.image_missing')}"


def test_the_review_window_gets_the_main_window_s_prefs(real_reviews, prefs, tmp_path) -> None:
    """ "Use for new videos" writes where the home window reads its settings."""
    from qurantext.jobs.project import Project, save_project

    path = save_project(
        Project(audio=tmp_path / "a.mp3", cards=[_card()]), tmp_path / "a.qalun.json"
    )
    real_reviews._open_review(path)
    review = real_reviews._review_of(path)
    assert review is not None and review._prefs is prefs


# --- a lecture's studied surah ------------------------------------------------


def _lecture_setup(tmp_path, monkeypatch):
    from qurantext.gui import jobs as jobs_module

    (tmp_path / "dars_lecture.json").write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "surah_num": 25,
                        "from_ayah": 7,
                        "to_ayah": 7,
                        "full_text": "x",
                        "start_time": 0.0,
                        "end_time": 2.0,
                    }
                ],
                "meta": {"mode": "lecture"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(jobs_module, "run_detection", lambda **kwargs: {"matches": []})
    audio = tmp_path / "dars.m4a"
    audio.write_bytes(b"")
    return jobs_module, JobSpec(
        audio=audio, quran=QURAN_FILE, mode="lecture", output_dir=tmp_path, studied_surah=25
    )


def test_the_chosen_studied_surah_reaches_the_jobs_project(tmp_path, monkeypatch) -> None:
    from qurantext.jobs.project import job_settings, load_project

    jobs_module, spec = _lecture_setup(tmp_path, monkeypatch)
    assert spec.settings.studied_surah == 25
    project = jobs_module.run_matching(spec)
    assert job_settings(load_project(project.path)).studied_surah == 25


def test_an_unchanged_rematch_keeps_the_surah_unless_another_is_picked(
    tmp_path, monkeypatch
) -> None:
    """ "Detect automatically" leaves the project's surah; a picked one replaces only it."""
    from qurantext.jobs.project import job_settings, load_project, save_project

    jobs_module, spec = _lecture_setup(tmp_path, monkeypatch)
    first = jobs_module.run_matching(spec)
    reviewed = load_project(first.path)
    reviewed.mark_reviewed()
    save_project(reviewed, first.path)
    before = first.path.read_bytes()

    project = jobs_module.run_matching(replace(spec, studied_surah=None))
    assert job_settings(project).studied_surah == 25
    assert first.path.read_bytes() == before, "nothing changed, so nothing is written"

    project = jobs_module.run_matching(replace(spec, studied_surah=17))
    saved = load_project(first.path)
    assert job_settings(project).studied_surah == job_settings(saved).studied_surah == 17
    assert saved.review["state"] == "reviewed", "the choice is an output choice, not content"
    assert not list(tmp_path.glob("*.qalun-backup.json"))


def test_a_changed_rematch_keeps_the_surah_unless_another_is_picked(tmp_path, monkeypatch) -> None:
    from qurantext.jobs.project import job_settings, load_project

    jobs_module, spec = _lecture_setup(tmp_path, monkeypatch)
    first = jobs_module.run_matching(spec)
    match_path = tmp_path / "dars_lecture.json"

    def new_content(end_time: float) -> None:
        payload = json.loads(match_path.read_text(encoding="utf-8"))
        payload["matches"][0]["end_time"] = end_time
        match_path.write_text(json.dumps(payload), encoding="utf-8")

    new_content(3.0)
    project = jobs_module.run_matching(replace(spec, studied_surah=None))
    assert len(list(tmp_path.glob("*.qalun-backup.json"))) == 1, "the content did change"
    assert job_settings(project).studied_surah == 25
    assert job_settings(load_project(first.path)).studied_surah == 25

    new_content(4.0)
    project = jobs_module.run_matching(replace(spec, studied_surah=17))
    assert job_settings(load_project(first.path)).studied_surah == 17


def test_a_rematch_of_a_project_that_never_chose_still_detects(tmp_path, monkeypatch) -> None:
    from qurantext.jobs.project import job_settings

    jobs_module, spec = _lecture_setup(tmp_path, monkeypatch)
    jobs_module.run_matching(replace(spec, studied_surah=None))
    project = jobs_module.run_matching(replace(spec, studied_surah=None))
    assert job_settings(project).studied_surah is None
    assert "studied_surah" not in project.export


def test_surah_names_come_from_a_built_store_and_nothing_breaks_without_one(
    tmp_path, store
) -> None:
    from qurantext.gui.surahs import stored_surah_names

    names = stored_surah_names(store)
    assert len(names) == 114 and names[1]
    assert stored_surah_names(tmp_path / "never-built.sqlite") == {}


def test_run_render_hands_on_a_missing_studied_surah(tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module
    from qurantext.jobs.export import ExportResult
    from qurantext.jobs.project import Project
    from qurantext.jobs.render import RenderResult

    video = tmp_path / "v.mp4"
    monkeypatch.setattr(
        jobs_module,
        "render_project",
        lambda project, output, **kwargs: ExportResult(
            video=video,
            render=RenderResult(
                output=video,
                width=1,
                height=1,
                fps=1,
                duration_seconds=1.0,
                studied_surah_missing=114,
            ),
        ),
    )
    project = Project(audio=tmp_path / "a.mp3", mode="lecture", matches=tmp_path / "m.json")
    assert jobs_module.run_render(project).studied_surah_missing == 114


def test_render_right_away_says_the_chosen_surah_has_no_card(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    """The review would have said it; a job that skips the review says it on the status line."""
    from qurantext.gui import main_window as module
    from qurantext.gui.jobs import JobOutcome

    _fake_matching(monkeypatch)
    monkeypatch.setattr(module, "stored_surah_names", lambda: {114: "الناس"})

    def fake_render(project, *, progress=None, cancel=None):
        return JobOutcome(
            matches=project.matches,
            video=tmp_path / "a.mp4",
            cards=1,
            look_warnings=("image_missing",),
            studied_surah_missing=114,
        )

    monkeypatch.setattr(module, "run_render", fake_render)

    _run_start(qt_app, home, _spec(tmp_path, output_dir=tmp_path / "jobs", render_right_away=True))

    rendered = module.t("home.finished.rendered", path=module.path_text(tmp_path / "a.mp4"))
    missing = module.t(
        "review.studied_surah_missing", surah=module.t("surah.item", num=114, name="الناس")
    )
    said = home.new_job.status_label.text()
    assert said == f"{rendered} {module.t('look.image_missing')} {missing}"


# --- the episode, joined after a lecture's render -------------------------------


def _episode_job(tmp_path, monkeypatch, *, mode="lecture", subtitles="both", episode=None):
    """A saved project whose render, recitation, join and subtitle export are faked.

    *episode* None chooses an intro clip and a recitation job; otherwise it is
    stored as the project's episode as it is. Returns the project, the jobs
    module and what each fake saw.
    """
    from qurantext.gui import jobs as jobs_module
    from qurantext.jobs.episode import EpisodeResult
    from qurantext.jobs.episode_assets import EpisodeChoice, set_project_episode
    from qurantext.jobs.export import ExportResult
    from qurantext.jobs.project import JobSettings, Project, save_project, set_job_settings

    seen: dict = {"assembled": [], "exported": [], "recitations": []}
    intro = tmp_path / "intro.mp4"
    intro.write_bytes(b"intro")
    recitation_project = tmp_path / "rec_recitation.qalun.json"
    rec_video = tmp_path / "rec.mp4"

    def fake_render_project(project, output, **kwargs):
        seen["render"] = dict(kwargs, output=output)
        project.record_render(
            output,
            preset=kwargs.get("preset"),
            basmala_offset_s=0.0,
            width=1280,
            height=720,
            fps=30,
            subtitles=kwargs.get("subtitles"),
        )
        if project.path is not None:
            save_project(project, project.path)
        return ExportResult(video=output, subtitles=[], cues=0, render=None)

    def fake_recitation_video(path, *, avoid=None, progress=None, cancel=None):
        seen["recitations"].append((path, avoid))
        return rec_video

    def fake_assemble(parts, output, **kwargs):
        seen["assembled"].append(dict(kwargs, parts=list(parts), output=output))
        return EpisodeResult(output=output, durations=(2.0, 3.0, 10.0), lecture_offset=5.0)

    def fake_export(project, stem, formats, **kwargs):
        seen["exported"].append(dict(kwargs, stem=stem, formats=formats))
        return [stem.with_name(f"{stem.name}.{fmt}") for fmt in formats]

    monkeypatch.setattr(jobs_module, "render_project", fake_render_project)
    monkeypatch.setattr(jobs_module, "recitation_video", fake_recitation_video)
    monkeypatch.setattr(jobs_module, "assemble_episode", fake_assemble)
    monkeypatch.setattr(jobs_module, "export_project_subtitles", fake_export)

    project = Project(audio=tmp_path / "lec.m4a", mode=mode, matches=tmp_path / f"lec_{mode}.json")
    set_job_settings(project, JobSettings("social", subtitles, ("srt",), tmp_path / "videos"))
    if episode is None:
        set_project_episode(
            project,
            EpisodeChoice(intro=intro, recitation=recitation_project),
            project_dir=tmp_path,
        )
    else:
        project.episode = dict(episode)
    save_project(project, tmp_path / f"lec_{mode}.qalun.json")
    seen.update(intro=intro.resolve(), recitation_project=recitation_project.resolve())
    seen["rec_video"] = rec_video
    return project, jobs_module, seen


def test_run_render_writes_the_episode_and_shifted_subtitles(tmp_path, monkeypatch) -> None:
    from qurantext.gui.i18n import t
    from qurantext.jobs.project import load_project

    project, jobs_module, seen = _episode_job(tmp_path, monkeypatch)
    events: list[ProgressEvent] = []
    outcome = jobs_module.run_render(project, progress=events.append)

    lecture = (tmp_path / "videos").resolve() / "lec.mp4"
    episode = lecture.with_name("lec – episode.mp4")
    assert outcome.video == lecture
    assert outcome.episode_video == episode and outcome.episode_error is None
    assert seen["recitations"] == [(seen["recitation_project"], lecture)]
    (joined,) = seen["assembled"]
    assert joined["parts"] == [seen["intro"], seen["rec_video"], lecture]
    assert joined["lecture_index"] == 2 and joined["output"] == episode
    assert (joined["width"], joined["height"], joined["fps"]) == (1280, 720, 30)
    (exported,) = seen["exported"]
    assert exported["offset"] == 5.0 and exported["timeline"] == "video"
    assert exported["formats"] == ("srt",)
    # The episode's own path, whose ".mp4" each format replaces (a dotted name stays whole).
    assert exported["stem"] == episode
    assert project.render["episode"] == {
        "video": str(episode),
        "lecture_offset": 5.0,
        "durations": [2.0, 3.0, 10.0],
    }
    saved = load_project(project.path)
    assert saved.render["episode"]["lecture_offset"] == 5.0
    assert saved.render["video"] == lecture, "the lecture's own record is kept"
    said = [(e.stage, e.message) for e in events if e.translated]
    assert said == [
        ("episode_recitation", t("job.stage.episode_recitation")),
        ("episode_join", t("job.stage.episode_join")),
    ]


def test_a_failed_episode_keeps_the_lecture(tmp_path, monkeypatch) -> None:
    from qurantext.gui.i18n import t
    from qurantext.jobs.episode import EpisodeError
    from qurantext.jobs.project import load_project

    project, jobs_module, seen = _episode_job(tmp_path, monkeypatch)

    def missing(parts, output, **kwargs):
        raise EpisodeError("episode.error.missing", name="rec.mp4")

    monkeypatch.setattr(jobs_module, "assemble_episode", missing)
    outcome = jobs_module.run_render(project)

    lecture = (tmp_path / "videos").resolve() / "lec.mp4"
    assert outcome.video == lecture
    assert outcome.episode_video is None
    assert outcome.episode_error == t("episode.error.missing", name="rec.mp4")
    assert seen["exported"] == [], "no subtitle files for an episode that was not made"
    saved = load_project(project.path)
    assert saved.render["video"] == lecture and "episode" not in saved.render


def test_a_recitation_that_cannot_be_used_keeps_the_lecture(tmp_path, monkeypatch) -> None:
    from qurantext.gui.i18n import t
    from qurantext.jobs.episode import EpisodeError

    project, jobs_module, seen = _episode_job(tmp_path, monkeypatch)

    def broken(path, **kwargs):
        raise EpisodeError("episode.error.recitation", reason="gone")

    monkeypatch.setattr(jobs_module, "recitation_video", broken)
    outcome = jobs_module.run_render(project)

    assert outcome.video is not None and outcome.episode_video is None
    assert outcome.episode_error == t("episode.error.recitation", reason="gone")
    assert seen["assembled"] == []


@pytest.mark.parametrize("step", ["recitation_video", "assemble_episode"])
def test_a_cancel_during_the_episode_keeps_the_lecture(tmp_path, monkeypatch, step) -> None:
    """The lecture is complete and recorded: the job finishes with it, and says so."""
    from qurantext.gui.i18n import t
    from qurantext.jobs.project import load_project

    project, jobs_module, _seen = _episode_job(tmp_path, monkeypatch)

    def cancelled(*args, **kwargs):
        raise JobCancelled("episode")

    monkeypatch.setattr(jobs_module, step, cancelled)
    outcome = jobs_module.run_render(project)

    lecture = (tmp_path / "videos").resolve() / "lec.mp4"
    assert outcome.video == lecture and outcome.episode_video is None
    assert outcome.episode_error == t("episode.error.cancelled")
    assert t("episode.error.cancelled") == "The episode was cancelled; the lecture video is kept."
    assert load_project(project.path).render["video"] == lecture


@pytest.mark.parametrize("episode", [{}, {"future": 1}])
def test_only_the_lecture_set_means_no_episode(tmp_path, monkeypatch, episode) -> None:
    project, jobs_module, seen = _episode_job(tmp_path, monkeypatch, episode=episode)
    outcome = jobs_module.run_render(project)

    assert seen["assembled"] == [] and seen["recitations"] == [] and seen["exported"] == []
    assert outcome.video is not None
    assert outcome.episode_video is None and outcome.episode_error is None
    assert "episode" not in project.render


def test_recitation_projects_never_make_an_episode(tmp_path, monkeypatch) -> None:
    intro = tmp_path / "hand.mp4"
    intro.write_bytes(b"x")
    project, jobs_module, seen = _episode_job(
        tmp_path, monkeypatch, mode="recitation", episode={"intro": str(intro)}
    )
    outcome = jobs_module.run_render(project)

    assert seen["assembled"] == [] and seen["recitations"] == []
    assert outcome.episode_video is None and outcome.episode_error is None


def test_an_episode_without_subtitle_files_writes_none(tmp_path, monkeypatch) -> None:
    """Subtitles burnt into the picture only: the episode carries them in its lecture part."""
    project, jobs_module, seen = _episode_job(tmp_path, monkeypatch, subtitles="burn")
    outcome = jobs_module.run_render(project)

    assert outcome.episode_video is not None and seen["exported"] == []


def test_an_outro_alone_puts_the_lecture_first(tmp_path, monkeypatch) -> None:
    intro = tmp_path / "only.mp4"
    intro.write_bytes(b"x")
    project, jobs_module, seen = _episode_job(
        tmp_path, monkeypatch, episode={"outro": str(intro.resolve())}
    )
    jobs_module.run_render(project)

    (joined,) = seen["assembled"]
    lecture = (tmp_path / "videos").resolve() / "lec.mp4"
    assert joined["parts"] == [lecture, intro.resolve()] and joined["lecture_index"] == 0
    assert seen["recitations"] == []


def test_episode_subtitles_that_cannot_be_written_keep_the_episode(tmp_path, monkeypatch) -> None:
    from qurantext.gui.i18n import t

    project, jobs_module, _seen = _episode_job(tmp_path, monkeypatch)

    def full_disk(project, stem, formats, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(jobs_module, "export_project_subtitles", full_disk)
    outcome = jobs_module.run_render(project)

    assert outcome.episode_video is not None
    assert outcome.episode_error == t("episode.error.subtitles", reason="No space left on device")
    assert project.render["episode"]["lecture_offset"] == 5.0


# --- the default episode a new lecture starts with -------------------------------


def _default_clips(tmp_path) -> tuple[Path, Path]:
    folder = tmp_path / "app-data" / "episode"
    folder.mkdir(parents=True)
    intro, outro = folder / "intro.mp4", folder / "outro.mov"
    intro.write_bytes(b"intro clip")
    outro.write_bytes(b"outro clip")
    return intro, outro


def test_a_new_lecture_job_is_seeded_with_the_default_episode(tmp_path, monkeypatch) -> None:
    from qurantext.jobs.episode_assets import episode_dir_for, project_episode
    from qurantext.jobs.project import load_project

    intro, outro = _default_clips(tmp_path)
    jobs_module, spec = _lecture_setup(tmp_path, monkeypatch)
    spec = replace(spec, episode_defaults=(str(intro), str(outro)))
    events: list[ProgressEvent] = []
    project = jobs_module.run_matching(spec, progress=events.append)

    saved = project_episode(load_project(project.path))
    assert saved.intro.parent == episode_dir_for(project.path)
    assert saved.intro.read_bytes() == b"intro clip" and saved.intro != intro
    assert saved.outro.parent == episode_dir_for(project.path)
    assert saved.outro.read_bytes() == b"outro clip" and saved.outro.suffix == ".mov"
    assert saved.recitation is None
    assert not Path(project.episode["intro"]).is_absolute(), "moves with the project folder"
    assert not [e for e in events if e.translated and e.stage == "detect" and "clip" in e.message]


def test_a_missing_default_clip_is_skipped_with_a_notice(tmp_path, monkeypatch) -> None:
    from qurantext.gui.i18n import t
    from qurantext.jobs.episode_assets import project_episode
    from qurantext.jobs.project import load_project

    gone = tmp_path / "app-data" / "episode" / "gone.mp4"
    jobs_module, spec = _lecture_setup(tmp_path, monkeypatch)
    spec = replace(spec, episode_defaults=(str(gone), None))
    events: list[ProgressEvent] = []
    project = jobs_module.run_matching(spec, progress=events.append)

    assert project.path is not None and project.path.exists(), "the job is still created"
    assert load_project(project.path).episode == {}
    assert project_episode(project).is_empty
    notice = t("episode.seed.missing", part=t("episode.part.intro"))
    assert notice == "The default intro clip is missing, so this lecture starts without it."
    assert any(e.stage == "detect" and e.message == notice and e.translated for e in events)


def test_a_default_clip_that_cannot_be_copied_is_skipped_with_a_notice(
    tmp_path, monkeypatch
) -> None:
    from qurantext.gui.i18n import t
    from qurantext.jobs.project import load_project

    intro, outro = _default_clips(tmp_path)
    wrong = intro.with_name("intro.txt")
    wrong.write_bytes(b"not a clip")
    jobs_module, spec = _lecture_setup(tmp_path, monkeypatch)
    spec = replace(spec, episode_defaults=(str(wrong), str(outro)))
    events: list[ProgressEvent] = []
    project = jobs_module.run_matching(spec, progress=events.append)

    episode = load_project(project.path).episode
    assert "intro" not in episode and episode["outro"], "the clip that copied is kept"
    notice = t("episode.seed.failed", part=t("episode.part.intro"))
    assert any(e.message == notice and e.translated for e in events)


def test_recitation_jobs_are_not_seeded(tmp_path, monkeypatch) -> None:
    from qurantext.jobs.episode_assets import episode_dir_for
    from qurantext.jobs.project import load_project

    intro, outro = _default_clips(tmp_path)
    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    project = jobs_module.run_matching(replace(spec, episode_defaults=(str(intro), str(outro))))

    assert load_project(project.path).episode == {}
    assert not episode_dir_for(project.path).exists()


def _choose_an_episode(project_path: Path, tmp_path: Path) -> dict:
    """Give the saved lecture at *project_path* an intro and a recitation; return its episode."""
    from qurantext.jobs.episode_assets import (
        EpisodeChoice,
        import_episode_clip,
        set_project_episode,
    )
    from qurantext.jobs.project import load_project, save_project

    clip = tmp_path / "chosen.mp4"
    clip.write_bytes(b"chosen intro")
    project = load_project(project_path)
    set_project_episode(
        project,
        EpisodeChoice(
            intro=import_episode_clip(project_path, clip),
            recitation=tmp_path / "rec_recitation.qalun.json",
        ),
    )
    save_project(project, project_path)
    return load_project(project_path).episode


def test_a_rematch_keeps_the_earlier_episode(tmp_path, monkeypatch) -> None:
    from qurantext.jobs.episode_assets import project_episode
    from qurantext.jobs.project import load_project, save_project

    intro, outro = _default_clips(tmp_path)
    jobs_module, spec = _lecture_setup(tmp_path, monkeypatch)
    first = jobs_module.run_matching(spec)
    chosen = _choose_an_episode(first.path, tmp_path)

    # Unchanged content: no backup, the file is left as it was, episode and all,
    # and the defaults are not seeded over the person's choice.
    before = first.path.read_bytes()
    again = jobs_module.run_matching(replace(spec, episode_defaults=(str(intro), str(outro))))
    assert not list(tmp_path.glob("*.qalun-backup.json")), "the episode is not content"
    assert first.path.read_bytes() == before
    assert again.episode == chosen

    # Changed content: a backup is kept, and the new project carries the episode.
    corrected = load_project(first.path)
    corrected.cards[0]["start_time"] = 0.25
    save_project(corrected, first.path)
    project = jobs_module.run_matching(replace(spec, episode_defaults=(str(intro), str(outro))))

    assert list(tmp_path.glob("dars_lecture.*.qalun-backup.json")), "content changed"
    assert project.cards[0]["start_time"] != 0.25
    assert project.episode == chosen
    kept = project_episode(load_project(first.path))
    assert kept.intro is not None and kept.intro.read_bytes() == b"chosen intro"
    assert kept.recitation == (tmp_path / "rec_recitation.qalun.json").resolve()
    assert kept.outro is None, "no default outro was added"


def _real_lecture_render(tmp_path, monkeypatch, name: str, *, offset: float = 30.0):
    """A lecture named *name* with an intro, rendered by the real ``render_project``.

    Only the picture is faked (``render_video`` writes a stand-in file) and so
    is the join (``assemble_episode`` reports *offset* seconds before the
    lecture); the subtitle files, their names and the records are the real ones.
    """
    from qurantext.gui import jobs as jobs_module
    from qurantext.jobs import export as export_module
    from qurantext.jobs import project_render
    from qurantext.jobs.episode import EpisodeResult
    from qurantext.jobs.episode_assets import EpisodeChoice, set_project_episode
    from qurantext.jobs.project import (
        CaptionCue,
        JobSettings,
        Project,
        save_project,
        set_job_settings,
    )
    from qurantext.jobs.render import RenderResult

    def fake_render_video(request, progress=None, cancel=None):
        request.output.parent.mkdir(parents=True, exist_ok=True)
        request.output.write_bytes(b"lecture")
        return RenderResult(
            output=request.output, width=1280, height=720, fps=30, duration_seconds=10.0
        )

    def fake_assemble(parts, output, **kwargs):
        output.write_bytes(b"episode")
        return EpisodeResult(output=output, durations=(offset, 10.0), lecture_offset=offset)

    monkeypatch.setattr(export_module, "render_video", fake_render_video)
    monkeypatch.setattr(project_render, "get_audio_duration", lambda path: 10.0)
    monkeypatch.setattr(jobs_module, "assemble_episode", fake_assemble)

    matches = tmp_path / f"{name}_lecture.json"
    matches.write_text(json.dumps({"matches": [], "meta": {"mode": "lecture"}}), encoding="utf-8")
    intro = tmp_path / "intro.mp4"
    intro.write_bytes(b"intro")
    project = Project(
        audio=tmp_path / f"{name}.m4a",
        mode="lecture",
        matches=matches,
        captions=[CaptionCue(1.0, 2.0, "first line")],
    )
    set_job_settings(project, JobSettings("social", "both", ("srt",), tmp_path / "videos"))
    set_project_episode(project, EpisodeChoice(intro=intro), project_dir=tmp_path)
    save_project(project, tmp_path / f"{name}_lecture.qalun.json")
    return project, jobs_module.run_render(project)


def _first_cue_start(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").splitlines()[1].split(" --> ")[0]


@pytest.mark.parametrize("name", ["Tafsir 25.7-11", "Dars 12.10.2024"])
def test_a_dotted_name_keeps_the_lecture_and_episode_subtitles_apart(
    tmp_path, monkeypatch, name
) -> None:
    """The episode's shifted cues must never land in the lecture's own subtitle file."""
    _project, outcome = _real_lecture_render(tmp_path, monkeypatch, name)

    videos = (tmp_path / "videos").resolve()
    assert outcome.episode_error is None
    assert outcome.episode_video == videos / f"{name} – episode.mp4"
    assert sorted(p.name for p in videos.iterdir()) == sorted(
        [f"{name}.mp4", f"{name}.srt", f"{name} – episode.mp4", f"{name} – episode.srt"]
    )
    assert _first_cue_start(videos / f"{name}.srt") == "00:00:01,000"
    assert _first_cue_start(videos / f"{name} – episode.srt") == "00:00:31,000"


def test_the_job_list_calls_a_lecture_rendered_after_its_episode(tmp_path, monkeypatch) -> None:
    from qurantext.jobs.catalog import RENDERED, job_status
    from qurantext.jobs.project import load_project

    project, outcome = _real_lecture_render(tmp_path, monkeypatch, "talk")

    assert outcome.episode_video is not None
    saved = load_project(project.path)
    assert saved.render["episode"]["lecture_offset"] == 30.0
    assert job_status(saved) == RENDERED and job_status(project) == RENDERED


def test_an_unexpected_error_in_the_episode_keeps_the_lecture_and_logs_it(
    tmp_path, monkeypatch, caplog
) -> None:
    """The person reads a sentence; the log keeps the traceback a bug report needs."""
    import logging

    from qurantext.gui.i18n import t

    project, jobs_module, _seen = _episode_job(tmp_path, monkeypatch)

    def boom(parts, output, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(jobs_module, "assemble_episode", boom)
    with caplog.at_level(logging.ERROR, logger="qurantext.gui.jobs"):
        outcome = jobs_module.run_render(project)

    assert outcome.video == (tmp_path / "videos").resolve() / "lec.mp4"
    assert outcome.episode_video is None
    assert outcome.episode_error == t("episode.error.ffmpeg", reason="boom")
    (record,) = [r for r in caplog.records if r.name == "qurantext.gui.jobs"]
    assert record.levelno == logging.ERROR and record.exc_info is not None
    assert record.exc_info[0] is RuntimeError
    assert "Traceback" in caplog.text and "in boom" in caplog.text


def test_a_foreseen_episode_failure_is_not_logged_as_a_bug(tmp_path, monkeypatch, caplog) -> None:
    import logging

    from qurantext.jobs.episode import EpisodeError

    project, jobs_module, _seen = _episode_job(tmp_path, monkeypatch)

    def missing(parts, output, **kwargs):
        raise EpisodeError("episode.error.missing", name="rec.mp4")

    monkeypatch.setattr(jobs_module, "assemble_episode", missing)
    with caplog.at_level(logging.ERROR, logger="qurantext.gui.jobs"):
        outcome = jobs_module.run_render(project)
    assert outcome.episode_error is not None
    assert not [r for r in caplog.records if r.name == "qurantext.gui.jobs"]


def test_an_episode_record_that_cannot_be_saved_keeps_the_episode(tmp_path, monkeypatch) -> None:
    project, jobs_module, _seen = _episode_job(tmp_path, monkeypatch)
    real_save = jobs_module.save_project

    def full_disk(project, path):
        if project.render and "episode" in project.render:
            raise OSError("No space left on device")
        return real_save(project, path)

    monkeypatch.setattr(jobs_module, "save_project", full_disk)
    outcome = jobs_module.run_render(project)

    assert outcome.episode_video is not None and outcome.episode_error is None
    assert project.render["episode"]["lecture_offset"] == 5.0, "the review copies it back"


def test_episode_subtitles_that_ffprobe_cannot_time_keep_the_episode(
    tmp_path, monkeypatch, caplog
) -> None:
    import logging

    from qurantext.gui.i18n import t

    project, jobs_module, _seen = _episode_job(tmp_path, monkeypatch)

    def unreadable(project, stem, formats, **kwargs):
        raise RuntimeError("ffprobe could not read the recording")

    monkeypatch.setattr(jobs_module, "export_project_subtitles", unreadable)
    with caplog.at_level(logging.ERROR, logger="qurantext.gui.jobs"):
        outcome = jobs_module.run_render(project)

    assert outcome.episode_video is not None
    assert outcome.episode_error == t(
        "episode.error.subtitles", reason="ffprobe could not read the recording"
    )
    (record,) = [r for r in caplog.records if r.name == "qurantext.gui.jobs"]
    assert record.exc_info is not None and "in unreadable" in caplog.text


def test_a_missing_intro_is_named_before_the_recitation_is_rendered(tmp_path, monkeypatch) -> None:
    from qurantext.gui.i18n import t

    project, jobs_module, seen = _episode_job(tmp_path, monkeypatch)
    seen["intro"].unlink()
    outcome = jobs_module.run_render(project)

    assert seen["recitations"] == [] and seen["assembled"] == []
    assert outcome.episode_error == t("episode.error.part_missing", part=t("episode.part.intro"))
    assert outcome.episode_error == "The intro clip is missing, so the episode was not made."


def test_an_intro_that_is_not_a_video_is_named_as_the_intro(tmp_path, monkeypatch) -> None:
    """The copy beside the project is named by its content, which tells the person nothing."""
    from qurantext.gui.i18n import t
    from qurantext.jobs.episode import EpisodeError

    project, jobs_module, seen = _episode_job(tmp_path, monkeypatch)

    def unreadable(parts, output, **kwargs):
        raise EpisodeError("episode.error.not_video", name=seen["intro"].name)

    monkeypatch.setattr(jobs_module, "assemble_episode", unreadable)
    outcome = jobs_module.run_render(project)

    assert outcome.episode_error == t("episode.error.part_not_video", part=t("episode.part.intro"))


def test_start_hands_the_seed_notices_on_with_the_job(tmp_path, monkeypatch) -> None:
    """The status line says them in passing; the finished job keeps them for the window."""
    from qurantext.gui.i18n import t
    from qurantext.gui.main_window import _match_then_render

    jobs_module, spec = _lecture_setup(tmp_path, monkeypatch)
    gone = tmp_path / "app-data" / "episode" / "gone.mp4"
    finished = _match_then_render(
        replace(spec, episode_defaults=(None, str(gone))), progress=None, cancel=CancelToken()
    )

    assert finished.notices == (t("episode.seed.missing", part=t("episode.part.outro")),)

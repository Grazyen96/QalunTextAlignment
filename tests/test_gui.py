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

    def fake_transcribe(audio_path, *, save_raw_to=None, model_ref=None):
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
    yield window
    window._jobs.stop()  # cancel and join anything a test left running
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
    qt_app.processEvents()


def _fake_matching(monkeypatch, calls: list | None = None, *, before=None):
    """Make ``run_matching`` write a project into the job's folder and return it."""
    from qurantext.gui import main_window as module
    from qurantext.jobs.project import load_project

    def fake(spec, *, progress=None, cancel=None):
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


def test_a_finished_job_whose_review_cannot_open_says_why(
    qt_app, home, reviews, tmp_path, monkeypatch
) -> None:
    """The reason must outlive the job's ending message, not be replaced by it."""
    from qurantext.gui import main_window as module
    from qurantext.jobs.project import Project

    def gone(spec, *, progress=None, cancel=None):
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
    home.new_job.start_requested.emit(_spec(tmp_path, output_dir=tmp_path / "jobs"))

    _spin_until(qt_app, lambda: any("40%" in text for text in _running_rows(home)))
    assert _running_rows(home)[0].startswith("\u2068a.mp3\u2069")  # the name, isolated
    assert "40%" in home.new_job.status_label.text()

    release.set()
    _spin_until(qt_app, lambda: home._cancel is None)
    _spin_until(qt_app, lambda: home._jobs.active == 0)
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

    window.job_list.list.itemActivated.emit(window.job_list.list.item(0))

    assert [r.project.path for r in reviews] == [project_path]


def test_double_clicking_a_damaged_job_shows_its_error(qt_app, prefs, reviews, tmp_path) -> None:
    from qurantext.gui.main_window import MainWindow

    (tmp_path / "jobs").mkdir()
    (tmp_path / "jobs" / "broken.qalun.json").write_text("{not json", encoding="utf-8")
    window = MainWindow(prefs=prefs)
    window.show()

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
    home._open_review(first)
    assert home.job_list.list.count() == 1

    _saved_job(tmp_path / "jobs", "second")
    reviews[0].saved.emit(first)
    assert home.job_list.list.count() == 2

    _saved_job(tmp_path / "jobs", "third")
    reviews[0].close()
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

    def blocked(spec, *, progress=None, cancel=None):
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
        module, "ReviewWindow", lambda project: real(project, player=FakePlayer(duration=10.0))
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


def test_switching_to_arabic_rebuilds_the_home_window(qt_app, home, prefs, tmp_path) -> None:
    from PySide6.QtWidgets import QLabel

    from qurantext.gui import i18n

    audio = tmp_path / "a.mp3"
    audio.touch()
    home.new_job.set_audio(audio)

    assert home.set_language("ar")

    assert prefs.language == "ar"
    assert home.windowTitle() == i18n.STRINGS["ar"]["app.title"]
    assert home.job_list.findChild(QLabel).text() != i18n.STRINGS["en"]["home.jobs"]  # rebuilt
    assert home.new_job.audio_path == audio  # the half-filled form survives
    assert home.language_combo.currentData() == "ar"

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

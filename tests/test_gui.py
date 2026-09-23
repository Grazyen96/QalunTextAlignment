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

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qurantext.config.paths import DEFAULT_FONT_PATH, DEFAULT_QURAN_PATH  # noqa: E402
from qurantext.gui.jobs import JobSpec, run_job  # noqa: E402
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
    ],
)
def test_an_incomplete_spec_says_what_is_missing(tmp_path, overrides, key) -> None:
    """The panel shows ``t(problem)`` under the Start button, so this is an i18n key."""
    problem = _spec(tmp_path, **overrides).validate()
    assert problem == key


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
def test_run_job_matches_then_renders(tmp_path, monkeypatch) -> None:
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
    outcome = run_job(
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
    outcome = run_job(spec, progress=events.append)

    assert outcome.backup is None
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
    outcome = run_job(spec, progress=events.append)

    (backup,) = tmp_path.glob("clip_recitation.*.qalun-backup.json")
    assert outcome.backup == backup
    assert load_project(backup).cards[0]["start_time"] == 0.25
    assert any(
        e.stage == "detect" and e.message == f"Kept your earlier corrections in {backup.name}"
        for e in events
    )


def test_an_unreadable_earlier_project_is_always_kept(tmp_path, monkeypatch) -> None:
    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    jobs_module.project_path_for(tmp_path / "clip_recitation.json").write_text("{not json")
    outcome = run_job(spec)
    assert outcome.backup is not None and outcome.backup.read_text() == "{not json"


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
    outcome = run_job(replace(spec, preset="high"), progress=events.append)

    after = json.loads(first.path.read_text(encoding="utf-8"))
    assert after["export"]["preset"] == "high"
    assert {k: v for k, v in after.items() if k != "export"} == {
        k: v for k, v in before.items() if k != "export"
    }, "cards, captions, review and style are left as they were"
    assert job_settings(load_project(first.path)).preset == "high"
    assert outcome.backup is None and not list(tmp_path.glob("*.qalun-backup.json"))


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


def test_run_job_renders_only_when_asked_to_right_away(tmp_path, monkeypatch) -> None:
    jobs_module, spec = _rematch_setup(tmp_path, monkeypatch)
    seen = _capture_render_project(jobs_module, monkeypatch, tmp_path)

    outcome = run_job(spec)
    assert outcome.video is None and not seen

    outcome = run_job(replace(spec, preset="fast", render_right_away=True))
    assert seen["preset"] == "fast"
    assert outcome.video == tmp_path.resolve() / "clip.mp4"
    assert not hasattr(spec, "render"), "render_right_away is the one switch"


# --- opening the review ---------------------------------------------------


def test_review_opens_the_jobs_project(qt_app, tmp_path, monkeypatch) -> None:
    from qurantext.gui import main_window as module
    from qurantext.gui.jobs import JobOutcome
    from qurantext.jobs.project import Project, save_project

    matches = tmp_path / "clip_recitation.json"
    matches.write_text(
        json.dumps({"matches": [], "meta": {"mode": "recitation"}}), encoding="utf-8"
    )
    project_path = save_project(
        Project(audio=tmp_path / "clip.mp3", matches=matches),
        tmp_path / "clip_recitation.qalun.json",
    )
    opened = []
    monkeypatch.setattr(
        module,
        "ReviewWindow",
        lambda project, **kw: (
            opened.append(project)
            or type(
                "W",
                (),
                {
                    "show": lambda self: None,
                    "saved": type("S", (), {"connect": lambda self, f: None})(),
                    "closed": type("S", (), {"connect": lambda self, f: None})(),
                },
            )()
        ),
    )
    window = module.MainWindow()
    window._outcome = JobOutcome(
        matches=matches, video=None, cards=0, mode="recitation", project=project_path
    )
    window._open_editor()
    assert opened and opened[0].path == project_path


def test_reopening_the_same_project_raises_the_existing_window(
    qt_app, tmp_path, monkeypatch
) -> None:
    from qurantext.gui import main_window as module
    from qurantext.gui.jobs import JobOutcome
    from qurantext.jobs.project import Project, save_project

    matches = tmp_path / "clip_recitation.json"
    matches.write_text(
        json.dumps({"matches": [], "meta": {"mode": "recitation"}}), encoding="utf-8"
    )
    project_path = save_project(
        Project(audio=tmp_path / "clip.mp3", matches=matches),
        tmp_path / "clip_recitation.qalun.json",
    )
    created = []

    class FakeReview:
        def __init__(self, project, **kw):
            created.append(self)
            self.project = project
            self.saved = type("S", (), {"connect": lambda self, f: None})()
            self.closed = type("S", (), {"connect": lambda self, f: None})()
            self.shown = 0
            self.raised = 0
            self.activated = 0

        def show(self):
            self.shown += 1

        def raise_(self):
            self.raised += 1

        def activateWindow(self):
            self.activated += 1

    monkeypatch.setattr(module, "ReviewWindow", FakeReview)
    window = module.MainWindow()
    window._outcome = JobOutcome(
        matches=matches, video=None, cards=0, mode="recitation", project=project_path
    )
    window._open_editor()
    window._open_editor()

    assert len(created) == 1
    # Opened once, then re-shown, raised and activated on the second call.
    assert created[0].shown == 2
    assert created[0].raised == 1
    assert created[0].activated == 1


def test_a_review_window_that_refuses_to_close_keeps_the_main_window_open(
    qt_app, tmp_path, monkeypatch
) -> None:
    from qurantext.gui import main_window as module
    from qurantext.gui.jobs import JobOutcome
    from qurantext.jobs.project import Project, save_project

    matches = tmp_path / "clip_recitation.json"
    matches.write_text(
        json.dumps({"matches": [], "meta": {"mode": "recitation"}}), encoding="utf-8"
    )
    project_path = save_project(
        Project(audio=tmp_path / "clip.mp3", matches=matches),
        tmp_path / "clip_recitation.qalun.json",
    )

    class RefusingReview:
        def __init__(self, project, **kw):
            self.saved = type("S", (), {"connect": lambda self, f: None})()
            self.closed = type("S", (), {"connect": lambda self, f: None})()

        def show(self):
            pass

        def close(self):
            return False

    monkeypatch.setattr(module, "ReviewWindow", RefusingReview)
    window = module.MainWindow()
    window._outcome = JobOutcome(
        matches=matches, video=None, cards=0, mode="recitation", project=project_path
    )
    window._open_editor()
    window.show()

    window.close()

    assert window.isVisible()


def _review_job(tmp_path):
    from qurantext.gui.jobs import JobOutcome
    from qurantext.jobs.project import Project, save_project

    cards = [
        {
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
    ]
    matches = tmp_path / "clip_recitation.json"
    matches.write_text(
        json.dumps({"matches": cards, "meta": {"mode": "recitation"}}), encoding="utf-8"
    )
    project_path = save_project(
        Project(audio=tmp_path / "clip.mp3", cards=cards, matches=matches),
        tmp_path / "clip_recitation.qalun.json",
    )
    outcome = JobOutcome(
        matches=matches, video=None, cards=1, mode="recitation", project=project_path
    )
    return outcome, project_path


@pytest.fixture()
def real_reviews(qt_app, monkeypatch):
    """The main window's real review window, with a fake player; closed after the test."""
    from PySide6.QtCore import QEvent

    from qurantext.gui import main_window as module
    from qurantext.gui.review.player import FakePlayer

    real = module.ReviewWindow
    monkeypatch.setattr(
        module, "ReviewWindow", lambda project: real(project, player=FakePlayer(duration=10.0))
    )
    main = module.MainWindow()
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

    outcome, project_path = _review_job(tmp_path)
    real_reviews._outcome = outcome
    real_reviews._open_editor()
    first = real_reviews._reviews[project_path]
    _edit_first_word(first)
    first._confirm_discard = lambda: "discard"
    assert first.close()
    assert project_path not in real_reviews._reviews
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    real_reviews._open_editor()
    second = real_reviews._reviews[project_path]
    assert not second.session.dirty
    assert not second.windowTitle().endswith("*")
    assert second.session.words()[0].end == 2.0


def test_a_change_on_disk_between_close_and_reopen_is_shown(qt_app, tmp_path, real_reviews) -> None:
    from qurantext.jobs.project import load_project, save_project

    outcome, project_path = _review_job(tmp_path)
    real_reviews._outcome = outcome
    real_reviews._open_editor()
    assert real_reviews._reviews[project_path].close()

    on_disk = load_project(project_path)
    on_disk.review = {"state": "reviewed", "reviewed_at": "2026-09-23T00:00:00"}
    save_project(on_disk, project_path)

    real_reviews._open_editor()
    assert real_reviews._reviews[project_path].session.project.review["state"] == "reviewed"


def test_opening_twice_while_open_keeps_one_window(qt_app, tmp_path, real_reviews) -> None:
    outcome, project_path = _review_job(tmp_path)
    real_reviews._outcome = outcome
    real_reviews._open_editor()
    first = real_reviews._reviews[project_path]
    real_reviews._open_editor()
    assert real_reviews._reviews[project_path] is first
    assert len(real_reviews._reviews) == 1

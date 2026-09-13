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
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qurantext.config.paths import DEFAULT_FONT_PATH, QURAN_INPUT_DIR  # noqa: E402
from qurantext.gui.jobs import JobSpec, run_job  # noqa: E402
from qurantext.gui.worker import JobWorker, run_in_thread  # noqa: E402
from qurantext.utils.progress import CancelToken, JobCancelled, ProgressEvent  # noqa: E402

QURAN_FILE = QURAN_INPUT_DIR / "UthmanicQaloon1-Ver05.txt"
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
    ("overrides", "message"),
    [
        ({"audio": Path("/nope/missing.mp3")}, "Choose an audio file"),
        ({"quran": Path("/nope/missing.txt")}, "Choose the Quran text file"),
        ({"surah_num": None}, "Choose the surah"),
        ({"from_ayah": 11, "to_ayah": 7}, "cannot come before"),
    ],
)
def test_an_incomplete_spec_says_what_is_missing(tmp_path, overrides, message) -> None:
    """The Start button's tooltip is this text, so it has to read as a sentence."""
    problem = _spec(tmp_path, **overrides).validate()
    assert problem is not None and message in problem


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

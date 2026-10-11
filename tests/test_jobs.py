"""The callable job layer: typed requests, progress events, cancellation.

Rendering used to be reachable only through an argparse round-trip that
returned an exit code. These pin the replacement contract a user interface
depends on: a result object, observable progress, and a Cancel that lands.
"""

from __future__ import annotations

import shutil
import subprocess
import threading

import pytest

from qurantext.config.paths import BASMALA_AUDIO_PATH, DEFAULT_FONT_PATH
from qurantext.jobs import (
    CancelToken,
    ConsoleProgress,
    JobCancelled,
    ProgressEvent,
    RenderRequest,
    render_video,
)
from qurantext.utils.progress import report

_BUNDLED_FONT = DEFAULT_FONT_PATH
_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


_SAMPLE_MATCH = {
    "surah_num": 25,
    "surah_name": "سُورَةُ الفُرقَانِ",
    "from_ayah": 7,
    "to_ayah": 7,
    "full_text": "وَقَالُواْ مَالِ هَٰذَا اَ۬لرَّسُولِ يَأْكُلُ اُ۬لطَّعَامَ",
    "confidence": 0.9,
    "start_time": 0.0,
    "end_time": 2.0,
}

# A card with per-word timings re-renders on every word, so the frame loop has
# many events and reports progress as it goes.
_HIGHLIGHTED_MATCH = {
    **_SAMPLE_MATCH,
    "end_time": 6.0,
    "word_timings": [
        {"word": word, "start": i * 0.6, "end": (i + 1) * 0.6}
        for i, word in enumerate(str(_SAMPLE_MATCH["full_text"]).split())
    ],
}


def _silent_audio(tmp_path, seconds: float = 2.0):
    audio = tmp_path / "silence.m4a"
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
            str(seconds),
            "-c:a",
            "aac",
            str(audio),
        ],
        check=True,
    )
    return audio


def _matches_file(tmp_path, match=None, name="matches.json"):
    import json

    path = tmp_path / name
    path.write_text(
        json.dumps(
            {"matches": [match or _SAMPLE_MATCH], "meta": {"mode": "recitation"}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


# --- progress plumbing -------------------------------------------------------


def test_report_is_a_no_op_without_a_callback() -> None:
    """Library and test callers must not be forced to supply a reporter."""
    report(None, "render", "ignored", fraction=0.5)


def test_report_delivers_a_structured_event() -> None:
    seen: list[ProgressEvent] = []
    report(seen.append, "match", "scanning", fraction=0.25, eta_seconds=8.0)
    assert seen == [
        ProgressEvent(stage="match", message="scanning", fraction=0.25, eta_seconds=8.0, done=False)
    ]


def test_console_progress_redraws_only_on_a_terminal() -> None:
    """A log file gets one closing line, not thousands of carriage returns."""

    class _Sink:
        def __init__(self, tty: bool) -> None:
            self.text = ""
            self._tty = tty

        def isatty(self) -> bool:
            return self._tty

        def write(self, chunk: str) -> int:
            self.text += chunk
            return len(chunk)

        def flush(self) -> None:
            return None

    sink = _Sink(tty=False)
    reporter = ConsoleProgress(sink)
    for fraction in (0.2, 0.4, 0.6):
        reporter(ProgressEvent("render", "working", fraction=fraction))
    reporter(ProgressEvent("render", "finished", fraction=1.0, done=True))

    assert "\r" not in sink.text
    assert "finished" in sink.text
    assert "working" not in sink.text


# --- cancellation ------------------------------------------------------------


def test_cancel_token_raises_only_once_set() -> None:
    token = CancelToken()
    assert token.cancelled is False
    token.raise_if_cancelled("render")

    token.cancel()
    assert token.cancelled is True
    with pytest.raises(JobCancelled, match="render"):
        token.raise_if_cancelled("render")


def test_cancel_token_is_settable_from_another_thread() -> None:
    """The Cancel button will live on a different thread from the job."""
    token = CancelToken()
    threading.Thread(target=token.cancel).start()
    for _ in range(1000):
        if token.cancelled:
            break
    assert token.cancelled is True


@pytest.mark.skipif(
    not (_FFMPEG and _FFPROBE and _BUNDLED_FONT.exists()),
    reason="needs ffmpeg, ffprobe and the bundled font",
)
def test_render_stops_when_cancelled_before_it_starts(tmp_path, no_basmala) -> None:
    request = RenderRequest(
        audio=_silent_audio(tmp_path),
        matches=_matches_file(tmp_path),
        output=tmp_path / "out.mp4",
        width=160,
        height=120,
        fps=5,
        font_file=_BUNDLED_FONT,
    )
    token = CancelToken()
    token.cancel()

    with pytest.raises(JobCancelled):
        render_video(request, cancel=token)
    assert not (tmp_path / "out.mp4").exists()


@pytest.mark.skipif(
    not (_FFMPEG and _FFPROBE and _BUNDLED_FONT.exists()),
    reason="needs ffmpeg, ffprobe and the bundled font",
)
def test_render_stops_partway_when_cancelled_mid_flight(tmp_path, no_basmala) -> None:
    """Cancelling during the frame loop must abort, not run to completion."""
    request = RenderRequest(
        audio=_silent_audio(tmp_path, seconds=6.0),
        matches=_matches_file(tmp_path, _HIGHLIGHTED_MATCH),
        output=tmp_path / "out.mp4",
        width=320,
        height=240,
        fps=25,
        font_file=_BUNDLED_FONT,
    )
    token = CancelToken()
    events: list[ProgressEvent] = []

    def watch(event: ProgressEvent) -> None:
        events.append(event)
        if event.stage == "render" and event.fraction is not None:
            token.cancel()

    with pytest.raises(JobCancelled):
        render_video(request, progress=watch, cancel=token)

    assert any(e.fraction is not None for e in events), "no measurable progress was reported"


# --- the result object -------------------------------------------------------


@pytest.mark.skipif(
    not (_FFMPEG and _FFPROBE and _BUNDLED_FONT.exists()),
    reason="needs ffmpeg, ffprobe and the bundled font",
)
def test_render_returns_what_it_wrote(tmp_path, no_basmala) -> None:
    """The caller gets a described result, not an exit code."""
    request = RenderRequest(
        audio=_silent_audio(tmp_path),
        matches=_matches_file(tmp_path),
        output=tmp_path / "out.mp4",
        width=320,
        height=240,
        fps=10,
        font_file=_BUNDLED_FONT,
    )
    events: list[ProgressEvent] = []
    result = render_video(request, progress=events.append)

    assert result.output == (tmp_path / "out.mp4").resolve()
    assert result.output.exists()
    assert (result.width, result.height, result.fps) == (320, 240, 10)
    assert result.basmala_offset_seconds == 0.0
    assert result.duration_seconds == pytest.approx(2.0, abs=0.3)
    assert {e.stage for e in events} == {"render"}
    assert events[-1].done is True


def test_request_resolves_a_preset_over_explicit_geometry() -> None:
    request = RenderRequest(
        audio="a.mp3",
        matches="m.json",
        output="o.mp4",
        preset="social",
        width=99,
        height=99,
        fps=1,
    )
    assert request.resolved_format() == (1080, 1920, 30)


def test_request_falls_back_to_configured_defaults() -> None:
    from qurantext.config.settings import get_settings

    video = get_settings().video
    request = RenderRequest(audio="a.mp3", matches="m.json", output="o.mp4")
    assert request.resolved_format() == (video.width, video.height, video.fps)


@pytest.mark.skipif(
    not (_FFMPEG and _FFPROBE and _BUNDLED_FONT.exists()),
    reason="needs ffmpeg, ffprobe and the bundled font",
)
def test_render_cancels_inside_one_long_static_event(tmp_path, no_basmala) -> None:
    """A latched card with no highlight is a single event covering every frame.

    Polling cancellation once per rendered event is not enough there: the frame
    write loop has to be interruptible too, or a long static card runs to
    completion no matter how often the outer loop checks.

    The token cancels itself on a later poll rather than on a timer, so the test
    proves the in-loop check exists instead of racing the encoder.
    """
    request = RenderRequest(
        audio=_silent_audio(tmp_path, seconds=20.0),
        matches=_matches_file(tmp_path),
        output=tmp_path / "out.mp4",
        width=160,
        height=120,
        fps=25,
        font_file=_BUNDLED_FONT,
    )

    class _CancelsOnLaterPoll(CancelToken):
        """Fires only after the write loop has polled a few times."""

        def __init__(self, after: int) -> None:
            super().__init__()
            self.polls = 0
            self._after = after

        def raise_if_cancelled(self, stage: str = "job") -> None:
            self.polls += 1
            if self.polls > self._after:
                self.cancel()
            super().raise_if_cancelled(stage)

    # Poll 1 is render_video's own pre-flight check and poll 2 is the one after
    # the basmala step, so anything beyond those has to come from inside the
    # single event's frame-write loop.
    token = _CancelsOnLaterPoll(after=3)
    with pytest.raises(JobCancelled):
        render_video(request, cancel=token)

    assert token.polls > 3, "the frame write loop never polled for cancellation"

    # Aborted, so the encoder never finalised a playable file.
    assert not (tmp_path / "out.mp4").exists() or (tmp_path / "out.mp4").stat().st_size == 0


@pytest.mark.skipif(
    not (_FFMPEG and _FFPROBE and _BUNDLED_FONT.exists() and BASMALA_AUDIO_PATH.exists()),
    reason="needs ffmpeg, ffprobe, the bundled font and the user's basmala audio",
)
def test_render_reports_the_basmala_offset_when_it_splices_one(tmp_path) -> None:
    """A recitation with no basmala of its own gets the shipped one in front.

    The result says by how much the timeline moved, which is the point of
    returning an object rather than an exit code.
    """
    request = RenderRequest(
        audio=_silent_audio(tmp_path),
        matches=_matches_file(tmp_path),
        output=tmp_path / "out.mp4",
        width=160,
        height=120,
        fps=10,
        font_file=_BUNDLED_FONT,
    )
    result = render_video(request)

    assert result.basmala_offset_seconds > 0
    assert result.duration_seconds == pytest.approx(2.0 + result.basmala_offset_seconds, abs=0.3)


# --- the look -----------------------------------------------------------------


@pytest.mark.skipif(
    not (_FFMPEG and _FFPROBE and _BUNDLED_FONT.exists()),
    reason="needs ffmpeg, ffprobe and the bundled font",
)
def test_render_warns_and_reports_a_missing_background_image(tmp_path, no_basmala, capsys) -> None:
    """A lost photo costs the background, not the render, and the person is told."""
    from dataclasses import replace

    from qurantext.core.looks import NIGHT_GOLD, Background

    background = Background(
        "image",
        NIGHT_GOLD.background.colour,
        NIGHT_GOLD.background.colour2,
        image=tmp_path / "gone.png",
    )
    request = RenderRequest(
        audio=_silent_audio(tmp_path),
        matches=_matches_file(tmp_path),
        output=tmp_path / "out.mp4",
        width=320,
        height=240,
        fps=10,
        font_file=_BUNDLED_FONT,
        look=replace(NIGHT_GOLD, background=background),
    )
    result = render_video(request)

    assert result.output.exists()
    assert result.look_warnings == ("image_missing",)
    assert "The background image is missing; the preset's background was used." in (
        capsys.readouterr().err
    )


def test_the_ass_renderer_says_it_ignores_a_chosen_look(tmp_path, capsys) -> None:
    from qurantext.core.looks import NIGHT_GOLD, PRESETS
    from qurantext.jobs.render import _warn_ignored_for_ass

    base = {
        "audio": tmp_path / "a.m4a",
        "matches": tmp_path / "m.json",
        "output": tmp_path / "o.mp4",
        "renderer": "ass",
    }
    _warn_ignored_for_ass(RenderRequest(**base, look=NIGHT_GOLD), None)
    assert "look" not in capsys.readouterr().err
    _warn_ignored_for_ass(RenderRequest(**base, look=PRESETS["ocean"]), None)
    assert capsys.readouterr().err.count("Ignoring the look") == 1

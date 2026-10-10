from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from qurantext.io.readers import extract_alignment_words  # the reader pipelines/recitation.py uses
from qurantext.services import engine_local
from qurantext.services.errors import LocalEngineError, ModelLoadError
from qurantext.utils.progress import CancelToken, JobCancelled

FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="needs ffmpeg")


def _tone(path, seconds=3.0, *, rate=16000, channels=1, extra=()):
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate={rate}:duration={seconds}",
            "-ac",
            str(channels),
            *extra,
            str(path),
        ],
        check=True,
    )
    return path


class FakeRecognizer:
    """Returns two words per window, at fixed times, and records what it was given."""

    def __init__(self, *, tokens=(" قال", " رب"), times=(0.1, 0.5)):
        self.windows: list[np.ndarray] = []
        self._tokens, self._times = list(tokens), list(times)

    def create_stream(self):
        rec = self

        class Stream:
            def accept_waveform(self, rate, samples):
                assert rate == 16000
                rec.windows.append(np.asarray(samples))
                self.result = SimpleNamespace(tokens=rec._tokens, timestamps=rec._times)

        return Stream()

    def decode_streams(self, streams):
        pass


def test_produces_the_whisperx_shape(tmp_path) -> None:
    audio = _tone(tmp_path / "a.wav")
    fake = FakeRecognizer()
    out = engine_local.transcribe_local(audio, tmp_path, recognizer_factory=lambda *_: fake)
    assert out["detected_language"] == "ar"
    seg = out["segments"][0]
    assert set(seg) == {"start", "end", "text", "words"}
    assert [w["word"] for w in seg["words"]] == ["قال", "رب"]
    assert seg["text"] == "قال رب"
    assert len(extract_alignment_words(out)) == 2  # the pipeline's own reader accepts it


def test_window_offsets_place_words_in_the_recording(tmp_path) -> None:
    audio = _tone(tmp_path / "long.wav", seconds=60)
    fake = FakeRecognizer()
    out = engine_local.transcribe_local(audio, tmp_path, recognizer_factory=lambda *_: fake)
    starts = [s["words"][0]["start"] for s in out["segments"]]
    assert len(starts) >= 3 and starts[0] == pytest.approx(0.1)
    assert all(b > a for a, b in zip(starts, starts[1:], strict=False))
    assert all(len(w) <= 28 * 16000 for w in fake.windows)


def test_windows_without_tokens_add_no_segment(tmp_path) -> None:
    audio = _tone(tmp_path / "a.wav")
    fake = FakeRecognizer(tokens=(), times=())
    out = engine_local.transcribe_local(audio, tmp_path, recognizer_factory=lambda *_: fake)
    assert out["segments"] == []


def test_decodes_stereo_44k_m4a_to_16k_mono(tmp_path) -> None:
    audio = _tone(tmp_path / "a.m4a", seconds=2.0, rate=44100, channels=2, extra=("-c:a", "aac"))
    samples = np.concatenate(list(engine_local.decode_pcm(audio)))
    assert samples.dtype == np.float32
    assert abs(len(samples) - 2.0 * 16000) < 0.05 * 16000


def test_reads_an_arabic_path_with_spaces(tmp_path) -> None:
    audio = _tone(tmp_path / "الفرقان 71 77.wav")
    fake = FakeRecognizer()
    out = engine_local.transcribe_local(audio, tmp_path, recognizer_factory=lambda *_: fake)
    assert out["segments"]


def test_unreadable_audio_names_the_file(tmp_path) -> None:
    bad = tmp_path / "broken.mp3"
    bad.write_bytes(b"not audio")
    with pytest.raises(LocalEngineError, match="broken.mp3"):
        engine_local.transcribe_local(bad, tmp_path, recognizer_factory=lambda *_: FakeRecognizer())


def test_cancel_stops_between_blocks(tmp_path) -> None:
    audio = _tone(tmp_path / "a.wav", seconds=30)
    token = CancelToken()
    token.cancel()
    with pytest.raises(JobCancelled):
        engine_local.transcribe_local(
            audio, tmp_path, cancel=token, recognizer_factory=lambda *_: FakeRecognizer()
        )


def _record_popen(monkeypatch) -> list:
    made: list = []
    real = subprocess.Popen

    def spy(*args, **kwargs):
        process = real(*args, **kwargs)
        if "-nostdin" in args[0]:  # only the decoder, not the tone maker or ffprobe
            made.append(process)
        return process

    monkeypatch.setattr(engine_local.subprocess, "Popen", spy)
    return made


def test_no_ffmpeg_child_remains_after_a_cancelled_run(tmp_path, monkeypatch) -> None:
    audio = _tone(tmp_path / "a.wav", seconds=30)
    made = _record_popen(monkeypatch)
    token = CancelToken()
    token.cancel()
    with pytest.raises(JobCancelled):
        engine_local.transcribe_local(
            audio, tmp_path, cancel=token, recognizer_factory=lambda *_: FakeRecognizer()
        )
    assert len(made) == 1 and made[0].poll() is not None


def test_no_ffmpeg_child_remains_after_an_error_in_the_loop(tmp_path, monkeypatch) -> None:
    audio = _tone(tmp_path / "a.wav", seconds=30)
    made = _record_popen(monkeypatch)

    class Broken(FakeRecognizer):
        def decode_streams(self, streams):
            raise RuntimeError("boom")

    with pytest.raises(LocalEngineError, match="boom"):
        engine_local.transcribe_local(audio, tmp_path, recognizer_factory=lambda *_: Broken())
    assert len(made) == 1 and made[0].poll() is not None


def test_no_ffmpeg_child_remains_after_success_and_decode_failure(tmp_path, monkeypatch) -> None:
    made = _record_popen(monkeypatch)
    engine_local.transcribe_local(
        _tone(tmp_path / "a.wav"), tmp_path, recognizer_factory=lambda *_: FakeRecognizer()
    )
    bad = tmp_path / "broken.mp3"
    bad.write_bytes(b"not audio")
    with pytest.raises(LocalEngineError):
        engine_local.transcribe_local(bad, tmp_path, recognizer_factory=lambda *_: FakeRecognizer())
    assert len(made) == 2 and all(p.poll() is not None for p in made)


def test_progress_reports_the_transcribe_stage(tmp_path) -> None:
    audio = _tone(tmp_path / "a.wav", seconds=30)
    events = []
    seen_at_load: list[int] = []

    def factory(*_a):
        seen_at_load.append(len(events))
        return FakeRecognizer()

    engine_local.transcribe_local(
        audio, tmp_path, progress=events.append, recognizer_factory=factory
    )
    assert events and {e.stage for e in events} == {"transcribe"}
    # The stage is named before the model loads, without a percentage yet.
    assert seen_at_load == [1] and events[0].fraction is None
    assert all(e.fraction is None or e.fraction <= 0.99 for e in events[:-1])
    assert events[-1].done is True and events[-1].fraction == 1.0


def test_a_model_that_will_not_load_raises_model_load_error(tmp_path) -> None:
    pytest.importorskip("sherpa_onnx")
    (tmp_path / "encoder.onnx").write_bytes(b"garbage")
    with pytest.raises(ModelLoadError):
        engine_local.make_recognizer(tmp_path, 1)


def _fake_ffmpeg(tmp_path, *, samples: int, exit_code: int = 0):
    """A stand-in "ffmpeg" that floods stderr (about 256 KB) before writing any audio."""
    script = tmp_path / f"fake_ffmpeg_{exit_code}.py"
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "for n in range(4096):\n"
        "    sys.stderr.write(f'[mp3 @ 0x55] Header missing, frame {n:06d} skipped....\\n')\n"
        "sys.stderr.write('LAST ERROR LINE\\n')\n"
        "sys.stderr.flush()\n"
        f"sys.stdout.buffer.write(bytes(4 * {samples}))\n"
        "sys.stdout.flush()\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return str(script)


def _decode_in_thread(audio, deadline: float = 20.0) -> dict:
    outcome: dict = {}

    def run() -> None:
        try:
            outcome["samples"] = sum(len(b) for b in engine_local.decode_pcm(audio))
        except Exception as error:  # noqa: BLE001 — the test inspects whatever it was
            outcome["error"] = error

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(deadline)
    assert not thread.is_alive(), "decode_pcm hung on FFmpeg's error output"
    return outcome


@pytest.mark.skipif(os.name == "nt", reason="the fake ffmpeg is a script with a shebang")
def test_a_flood_of_ffmpeg_errors_does_not_hang_the_decoder(tmp_path, monkeypatch) -> None:
    fake = _fake_ffmpeg(tmp_path, samples=3 * 16000)
    monkeypatch.setattr(engine_local, "require_binary", lambda *_a, **_k: fake)
    outcome = _decode_in_thread(tmp_path / "glitchy.mp3")
    assert outcome == {"samples": 3 * 16000}


@pytest.mark.skipif(os.name == "nt", reason="the fake ffmpeg is a script with a shebang")
def test_a_failed_decode_reports_the_end_of_ffmpeg_errors(tmp_path, monkeypatch) -> None:
    fake = _fake_ffmpeg(tmp_path, samples=16000, exit_code=1)
    monkeypatch.setattr(engine_local, "require_binary", lambda *_a, **_k: fake)
    outcome = _decode_in_thread(tmp_path / "glitchy.mp3")
    error = outcome["error"]
    assert isinstance(error, LocalEngineError)
    assert "glitchy.mp3" in str(error) and "LAST ERROR LINE" in str(error)


def test_reads_that_split_a_sample_are_rejoined(tmp_path, monkeypatch) -> None:
    source = np.arange(50_001, dtype=np.float32) / 7
    payload = source.tobytes()

    class SplitPipe:
        """Returns odd-sized reads, as a raw pipe may: samples straddle reads."""

        def __init__(self) -> None:
            self.pos, self.sizes, self.turn = 0, (1, 2, 3, 5, 7, 4093, 4097), 0

        def read(self, _n: int) -> bytes:
            size = self.sizes[self.turn % len(self.sizes)]
            self.turn += 1
            chunk = payload[self.pos : self.pos + size]
            self.pos += len(chunk)
            return chunk

        def close(self) -> None:
            pass

    class FakeProcess:
        def __init__(self, *_a, **_k) -> None:
            self.stdout, self.stderr = SplitPipe(), None

        def poll(self):
            return 0

        def wait(self):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(engine_local.subprocess, "Popen", FakeProcess)
    blocks = list(engine_local.decode_pcm(tmp_path / "a.wav"))
    assert np.array_equal(np.concatenate(blocks), source)


def test_cancel_during_the_run_stops_after_the_current_batch(tmp_path) -> None:
    audio = _tone(tmp_path / "long.wav", seconds=150)  # six windows: two batches
    token = CancelToken()
    fake = FakeRecognizer()

    def cancel_after_first_batch(event) -> None:
        if event.fraction is not None:
            token.cancel()

    with pytest.raises(JobCancelled):
        engine_local.transcribe_local(
            audio,
            tmp_path,
            progress=cancel_after_first_batch,
            cancel=token,
            recognizer_factory=lambda *_: fake,
        )
    assert len(fake.windows) == 4


def test_a_recogniser_failure_after_loading_is_an_engine_error(tmp_path) -> None:
    audio = _tone(tmp_path / "a.wav")

    class OutOfMemory(FakeRecognizer):
        def decode_streams(self, streams):
            raise MemoryError()

    with pytest.raises(LocalEngineError, match=r"a\.wav.*WhisperX online") as caught:
        engine_local.transcribe_local(audio, tmp_path, recognizer_factory=lambda *_: OutOfMemory())
    assert isinstance(caught.value.__cause__, MemoryError)


def test_cancel_is_not_turned_into_an_engine_error(tmp_path) -> None:
    audio = _tone(tmp_path / "a.wav")

    class Cancelled(FakeRecognizer):
        def decode_streams(self, streams):
            raise JobCancelled("transcribe was cancelled")

    with pytest.raises(JobCancelled):
        engine_local.transcribe_local(audio, tmp_path, recognizer_factory=lambda *_: Cancelled())

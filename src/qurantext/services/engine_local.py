"""The local engine: NVIDIA's FastConformer Arabic, run by sherpa-onnx on this computer.

Audio is decoded by the bundled FFmpeg straight to 16 kHz mono and read in
blocks, cut at pauses into windows of at most 28 s, recognised a few windows at a
time, and returned in the WhisperX raw shape the rest of the pipeline already
reads. Nothing leaves the machine.

Memory: the audio itself is never held whole (under 29 s in the cutter, at most
four windows pending, about 9 MB). The recogniser's working set is what costs:
with four windows per batch it peaks at about 1.8 GB and plateaus there (0.9 GB
on a 97 s clip, 1.7 GB on a 12-minute lecture, 1.8 GB on 82 minutes). The batch
size is not a tuning knob: each window is padded to its batch's longest, which
changes the features, so a different batch size changes transcripts (one window
per batch peaks at 0.7 GB but changed 66 of 982 words and ran 2.3x slower). The
parity gate approved four.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import numpy as np

from qurantext.core.pause_cut import SAMPLE_RATE, PauseCutter
from qurantext.core.token_words import tokens_to_words
from qurantext.core.video_common import require_binary
from qurantext.services.errors import LocalEngineError, ModelLoadError
from qurantext.utils.progress import CancelToken, JobCancelled, ProgressCallback, report

__all__ = [
    "DEFAULT_THREADS",
    "decode_pcm",
    "make_recognizer",
    "probe_duration",
    "runtime_problem",
    "transcribe_local",
]

#: Leave two cores to the window and the rest of the machine.
DEFAULT_THREADS = max(1, (os.cpu_count() or 1) - 2)
#: Windows recognised together. Part of what the parity gate approved: changing it
#: changes transcripts (see the module docstring) and needs the gate run again.
_BATCH_WINDOWS = 4
#: How much of FFmpeg's error output is read back for a failure's message.
_STDERR_TAIL_BYTES = 4096

RecognizerFactory = Callable[[Path, int], Any]


def runtime_problem() -> str | None:
    """Why the speech runtime (sherpa-onnx) cannot be used here, or None when it can.

    Checked before the model is downloaded, so a broken install does not first
    fetch about 110 MB only to fail.
    """
    try:
        import sherpa_onnx  # noqa: F401
    except Exception as error:  # noqa: BLE001 — ImportError, or a native library that will not load
        return str(error) or type(error).__name__
    return None


def make_recognizer(model_dir: Path, num_threads: int) -> Any:
    """Load the model. Any failure is a ModelLoadError, so the caller can re-verify it."""
    try:
        import sherpa_onnx

        return sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(model_dir / "encoder.onnx"),
            decoder=str(model_dir / "decoder.onnx"),
            joiner=str(model_dir / "joiner.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=num_threads,
            sample_rate=SAMPLE_RATE,
            feature_dim=80,
            decoding_method="greedy_search",
            model_type="nemo_transducer",
        )
    except Exception as error:  # noqa: BLE001 — every load failure means the same thing here
        raise ModelLoadError(
            f"The speech model could not be loaded from {model_dir}: {error}"
        ) from error


def probe_duration(audio_path: Path) -> float | None:
    """The recording's length, for an honest progress bar. None when unknown."""
    try:
        ffprobe = require_binary("ffprobe", "Install FFmpeg and try again.")
        out = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(audio_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.strip()
        return float(out) if out else None
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError):
        return None


def decode_pcm(audio_path: Path, *, block_seconds: float = 1.0) -> Iterator[np.ndarray]:
    """Yield the recording as 16 kHz mono float32 blocks, never the whole file at once.

    FFmpeg's error output goes to a temporary file, not a pipe: a damaged
    recording can produce more errors than a pipe holds, and FFmpeg would then
    stop writing audio while this waited for it.
    """
    ffmpeg = require_binary("ffmpeg", "Install FFmpeg and try again.")
    block_bytes = int(block_seconds * SAMPLE_RATE) * 4
    with tempfile.TemporaryFile() as errors_file:
        process = subprocess.Popen(
            [
                ffmpeg,
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(audio_path),
                "-ac",
                "1",
                "-ar",
                str(SAMPLE_RATE),
                "-f",
                "f32le",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=errors_file,
        )
        try:
            assert process.stdout is not None
            leftover = b""
            while chunk := process.stdout.read(block_bytes):
                data = leftover + chunk
                usable = len(data) - len(data) % 4
                leftover = data[usable:]
                if usable:
                    yield np.frombuffer(data[:usable], dtype=np.float32).copy()
            if process.wait() != 0:
                raise LocalEngineError(
                    f"FFmpeg could not read {Path(audio_path).name}: {_tail(errors_file)}"
                )
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stdout is not None:
                process.stdout.close()


def _tail(errors_file: Any) -> str:
    """The last few lines FFmpeg wrote to *errors_file*, for a failure's message."""
    errors_file.seek(0, os.SEEK_END)
    size = errors_file.tell()
    errors_file.seek(max(0, size - _STDERR_TAIL_BYTES))
    text = errors_file.read().decode("utf-8", "replace")
    return text.strip()[-400:]


def _minutes(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def transcribe_local(
    audio_path: Path,
    model_dir: Path,
    *,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
    recognizer_factory: RecognizerFactory = make_recognizer,
    num_threads: int = DEFAULT_THREADS,
) -> dict:
    """Transcribe *audio_path* on this computer, in the WhisperX raw shape."""
    audio_path = Path(audio_path)
    # Say so at once: probing and loading take seconds, and the window would
    # otherwise keep naming the stage before this one.
    report(progress, "transcribe", "Transcribing on this computer...")
    duration = probe_duration(audio_path)
    recognizer = recognizer_factory(Path(model_dir), num_threads)
    cutter = PauseCutter()
    segments: list[dict] = []
    pending: list[tuple[int, np.ndarray]] = []
    started = time.monotonic()

    def recognise() -> list:
        """The batch's decoded streams, one per window. A failure is a LocalEngineError."""
        try:
            streams = []
            for _start, samples in pending:
                stream = recognizer.create_stream()
                stream.accept_waveform(SAMPLE_RATE, samples)
                streams.append(stream)
            recognizer.decode_streams(streams)
            return streams
        except JobCancelled:
            raise
        except Exception as error:  # noqa: BLE001 — native errors and MemoryError alike
            detail = str(error) or type(error).__name__
            raise LocalEngineError(
                f"The local model stopped while recognising {audio_path.name} at "
                f"{_minutes(pending[0][0] / SAMPLE_RATE)} ({detail}). Close other programs "
                "and start the job again, or choose WhisperX online."
            ) from error

    def run_batch() -> None:
        streams = recognise()
        for (start, samples), stream in zip(pending, streams, strict=True):
            result = stream.result
            words = tokens_to_words(
                list(result.tokens),
                list(result.timestamps),
                window_end=len(samples) / SAMPLE_RATE,
                offset=start / SAMPLE_RATE,
            )
            if words:
                segments.append(
                    {
                        "start": words[0]["start"],
                        "end": words[-1]["end"],
                        "text": " ".join(w["word"] for w in words),
                        "words": words,
                    }
                )
        last_start, last_samples = pending[-1]
        reached = (last_start + len(last_samples)) / SAMPLE_RATE
        pending.clear()
        # ffprobe's length is an estimate for some MP3s, so only "done" says 100%.
        fraction = min(0.99, reached / duration) if duration else None
        elapsed = time.monotonic() - started
        eta = elapsed / fraction - elapsed if fraction and fraction > 0.01 else None
        total = f" of {_minutes(duration)}" if duration else ""
        report(
            progress,
            "transcribe",
            f"Transcribing on this computer: {_minutes(reached)}{total}",
            fraction=fraction,
            eta_seconds=eta,
        )

    # closing(): FFmpeg is reaped the moment we stop, not whenever the generator is collected.
    with closing(decode_pcm(audio_path)) as blocks:
        for block in blocks:
            if cancel is not None:
                cancel.raise_if_cancelled("transcribe")
            for window in cutter.feed(block):
                pending.append(window)
                if len(pending) >= _BATCH_WINDOWS:
                    run_batch()
    pending.extend(cutter.flush())
    if pending:
        run_batch()
    report(progress, "transcribe", "Transcribed on this computer.", fraction=1.0, done=True)
    return {"segments": segments, "detected_language": "ar"}

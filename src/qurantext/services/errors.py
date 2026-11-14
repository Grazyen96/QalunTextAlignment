"""Errors a transcription can end in, under one base the CLI and the window catch."""

from __future__ import annotations

__all__ = [
    "RUN_THE_DOCTOR",
    "WHISPERX_INSTEAD",
    "LocalEngineError",
    "ModelDownloadError",
    "ModelLoadError",
    "TranscriptionError",
    "WhisperXServiceError",
]


RUN_THE_DOCTOR = (
    "To see what is missing, run the doctor: `qalun --doctor` for the app, "
    "`qurantext doctor` from the command line."
)
WHISPERX_INSTEAD = "choose WhisperX online (`--engine whisperx` on the command line)"


class TranscriptionError(RuntimeError):
    """A transcription could not complete. The message says what to do about it."""


class WhisperXServiceError(TranscriptionError):
    """Raised when the WhisperX transcription service cannot complete successfully."""


class ModelDownloadError(TranscriptionError):
    """The local speech model could not be downloaded or failed its checksum."""


class LocalEngineError(TranscriptionError):
    """The local engine failed while reading the audio or recognising it."""


class ModelLoadError(LocalEngineError):
    """The local model's files are there but the recogniser could not load them."""

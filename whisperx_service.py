from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import replicate

from env_utils import load_project_env

MODEL_REF = "victor-upmeet/whisperx:84d2ad2d6194fe98a17d2b60bef1c7f910c46b2f6fd38996ca457afd9c8abfcb"

# Match the word-level parameters already used in audioAlignment.py.
DEFAULT_INPUT = {
    "debug": False,
    "language": "ar",
    "vad_onset": 0.5,
    "batch_size": 64,
    "vad_offset": 0.363,
    "diarization": False,
    "temperature": 0,
    "align_output": True,
    "language_detection_min_prob": 0,
    "language_detection_max_tries": 5,
}


class WhisperXServiceError(RuntimeError):
    """Raised when the WhisperX Replicate service cannot complete successfully."""


@dataclass(slots=True)
class WhisperXResult:
    """Structured result returned by :func:`transcribe_audio`."""

    output: dict | list
    audio_path: str
    raw_output_path: str | None
    model_ref: str
    segment_count: int
    word_count: int


def _count_segments(output: Any) -> int:
    if isinstance(output, dict):
        return len(output.get("segments", []))
    if isinstance(output, list):
        return len(output)
    return 0


def _count_words(output: Any) -> int:
    if isinstance(output, dict):
        return sum(len(segment.get("words", [])) for segment in output.get("segments", []))
    if isinstance(output, list):
        total = 0
        for item in output:
            if not isinstance(item, dict):
                continue
            words = item.get("words") or []
            total += len(words) if words else 1
        return total
    return 0


def _normalize_output_for_json(output: Any) -> dict | list:
    if isinstance(output, (dict, list)):
        return output
    return {"raw": str(output)}


def _save_raw_output(output: Any, destination: str | os.PathLike[str]) -> str:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(_normalize_output_for_json(output), fh, ensure_ascii=False, indent=2)
    return str(path)


def transcribe_audio(
    audio_path: str | os.PathLike[str],
    *,
    save_raw_to: str | os.PathLike[str] | None = None,
    model_ref: str = MODEL_REF,
) -> WhisperXResult:
    """
    Transcribe an audio file with WhisperX on Replicate using the project's
    existing Arabic word-alignment settings.

    Parameters
    ----------
    audio_path:
        Path to the input audio file.
    save_raw_to:
        Optional path where the raw Replicate response should be written as JSON.
    model_ref:
        Replicate model reference. Defaults to the model already used by this project.

    Returns
    -------
    WhisperXResult
        The raw Replicate output together with basic metadata.

    Raises
    ------
    FileNotFoundError
        If the audio file does not exist.
    WhisperXServiceError
        If the Replicate token is missing, the API call fails, or the response
        cannot be saved when ``save_raw_to`` is provided.
    """
    audio_file_path = Path(audio_path)
    if not audio_file_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

    load_project_env()

    if not os.getenv("REPLICATE_API_TOKEN"):
        raise WhisperXServiceError(
            "REPLICATE_API_TOKEN is not set. Add it to your shell environment, .env, or .env.local before running WhisperX."
        )

    try:
        with audio_file_path.open("rb") as audio_file:
            output = replicate.run(
                model_ref,
                input={
                    **DEFAULT_INPUT,
                    "audio_file": audio_file,
                },
            )
    except Exception as error:
        error_text = str(error)
        if "status: 404" in error_text:
            raise WhisperXServiceError(
                f"Replicate could not find the model: {model_ref}\n"
                "Check that the model exists and that your account has access to it."
            ) from error
        raise WhisperXServiceError(f"WhisperX transcription failed: {error_text}") from error

    raw_output_path: str | None = None
    if save_raw_to is not None:
        try:
            raw_output_path = _save_raw_output(output, save_raw_to)
        except Exception as error:
            raise WhisperXServiceError(
                f"WhisperX transcription succeeded, but saving raw output failed: {error}"
            ) from error

    return WhisperXResult(
        output=_normalize_output_for_json(output),
        audio_path=str(audio_file_path),
        raw_output_path=raw_output_path,
        model_ref=model_ref,
        segment_count=_count_segments(output),
        word_count=_count_words(output),
    )


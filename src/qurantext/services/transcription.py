from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any

from qurantext.config.settings import DEFAULT_MODEL_REF, get_settings
from qurantext.io.writers import write_json


class WhisperXServiceError(RuntimeError):
    """Raised when the WhisperX transcription service cannot complete successfully."""


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


def save_raw_output(output: Any, destination: str | PathLike[str]) -> str:
    """Persist raw WhisperX output to disk as UTF-8 JSON."""
    normalized_output = _normalize_output_for_json(output)
    return write_json(normalized_output, destination)


def transcribe_audio(
    audio_path: str | PathLike[str],
    *,
    save_raw_to: str | PathLike[str] | None = None,
    model_ref: str | None = None,
) -> WhisperXResult:
    """Transcribe an audio file with WhisperX on Replicate."""
    audio_file_path = Path(audio_path)
    if not audio_file_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

    settings = get_settings()
    resolved_model_ref = model_ref or settings.whisperx.model_ref or DEFAULT_MODEL_REF

    if not settings.replicate_api_token:
        raise WhisperXServiceError(
            "REPLICATE_API_TOKEN is not set. Add it to your shell environment, .env, or .env.local before running WhisperX."
        )

    try:
        import replicate

        with audio_file_path.open("rb") as audio_file:
            output = replicate.run(
                resolved_model_ref,
                input={
                    **settings.whisperx.input_kwargs(),
                    "audio_file": audio_file,
                },
            )
    except Exception as error:
        error_text = str(error)
        if "status: 404" in error_text:
            raise WhisperXServiceError(
                f"Replicate could not find the model: {resolved_model_ref}\n"
                "Check that the model exists and that your account has access to it."
            ) from error
        raise WhisperXServiceError(f"WhisperX transcription failed: {error_text}") from error

    raw_output_path: str | None = None
    if save_raw_to is not None:
        try:
            raw_output_path = save_raw_output(output, save_raw_to)
        except Exception as error:
            raise WhisperXServiceError(
                f"WhisperX transcription succeeded, but saving raw output failed: {error}"
            ) from error

    return WhisperXResult(
        output=_normalize_output_for_json(output),
        audio_path=str(audio_file_path),
        raw_output_path=raw_output_path,
        model_ref=resolved_model_ref,
        segment_count=_count_segments(output),
        word_count=_count_words(output),
    )

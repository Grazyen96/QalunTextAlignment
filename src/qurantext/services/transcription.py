from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any

from qurantext.config.settings import DEFAULT_MODEL_REF, ENGINES, AppSettings, get_settings
from qurantext.io.writers import write_json
from qurantext.services import engine_whisperx
from qurantext.services.errors import TranscriptionError, WhisperXServiceError
from qurantext.services.transcript_cache import cache_key, load_cached, store_cached
from qurantext.utils.progress import CancelToken, ProgressCallback

__all__ = [
    "ENGINE_LABELS",
    "TranscriptionError",
    "TranscriptionResult",
    "WhisperXResult",
    "WhisperXServiceError",
    "resolve_engine",
    "save_raw_output",
    "transcribe_audio",
]

#: How progress lines and messages name each engine.
ENGINE_LABELS = {"local": "the local model", "whisperx": "WhisperX on Replicate"}


def resolve_engine(engine: str | None, settings: AppSettings) -> str:
    """The engine to use: the explicit choice, else the setting."""
    value = (engine or settings.transcription.engine or "").strip().lower()
    if value not in ENGINES:
        choices = ", ".join(ENGINES)
        if engine:
            raise ValueError(f"Unknown transcription engine {value!r}; choose one of: {choices}.")
        raise ValueError(f"QURANTEXT_TRANSCRIBE_ENGINE is {value!r}; choose one of: {choices}.")
    return value


@dataclass(slots=True)
class TranscriptionResult:
    """Structured result returned by :func:`transcribe_audio`."""

    output: dict | list
    audio_path: str
    raw_output_path: str | None
    model_ref: str
    segment_count: int
    word_count: int
    #: True when the result came from the cache and nothing was sent anywhere.
    from_cache: bool = False
    #: Which engine produced the transcript: "whisperx" or "local".
    engine: str = "whisperx"


#: The name this type had while WhisperX was the only engine.
WhisperXResult = TranscriptionResult


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
    use_cache: bool = True,
    engine: str | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> TranscriptionResult:
    """Transcribe an audio file with the chosen engine (see :func:`resolve_engine`).

    The same audio with the same settings always gives the same transcript, so
    the result is cached against the audio's content. A repeat run — correcting
    one subtitle line and rendering again, say — costs nothing and needs no
    network. Pass ``use_cache=False`` to force a fresh call.
    """
    audio_file_path = Path(audio_path)
    if not audio_file_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

    settings = get_settings()
    resolved_engine = resolve_engine(engine, settings)
    if resolved_engine == "local":
        from qurantext.services.errors import LocalEngineError

        raise LocalEngineError("The local engine is not part of this build yet.")
    resolved_model_ref = model_ref or settings.whisperx.model_ref or DEFAULT_MODEL_REF
    key_settings = engine_whisperx.cache_settings(settings, resolved_model_ref)
    return _transcribe_cached(
        audio_file_path,
        key_settings=key_settings,
        model_ref=resolved_model_ref,
        engine="whisperx",
        run=lambda: engine_whisperx.run_whisperx(audio_file_path, settings, resolved_model_ref),
        save_raw_to=save_raw_to,
        use_cache=use_cache,
    )


def _transcribe_cached(
    audio_file_path: Path,
    *,
    key_settings: dict[str, Any],
    model_ref: str,
    engine: str,
    run: Callable[[], Any],
    save_raw_to: str | PathLike[str] | None,
    use_cache: bool,
) -> TranscriptionResult:
    """Cache lookup, run, cache store and save: the same for every engine."""
    key = cache_key(audio_file_path, key_settings) if use_cache else None
    if key is not None:
        cached = load_cached(key)
        if cached is not None:
            raw_output_path = (
                save_raw_output(cached, save_raw_to) if save_raw_to is not None else None
            )
            return TranscriptionResult(
                output=cached,
                audio_path=str(audio_file_path),
                raw_output_path=raw_output_path,
                model_ref=model_ref,
                segment_count=_count_segments(cached),
                word_count=_count_words(cached),
                from_cache=True,
                engine=engine,
            )

    output = run()

    if key is not None:
        store_cached(key, _normalize_output_for_json(output))
    raw_output_path: str | None = None
    if save_raw_to is not None:
        try:
            raw_output_path = save_raw_output(output, save_raw_to)
        except Exception as error:
            raise TranscriptionError(
                f"Transcription succeeded, but saving raw output failed: {error}"
            ) from error
    return TranscriptionResult(
        output=_normalize_output_for_json(output),
        audio_path=str(audio_file_path),
        raw_output_path=raw_output_path,
        model_ref=model_ref,
        segment_count=_count_segments(output),
        word_count=_count_words(output),
        engine=engine,
    )

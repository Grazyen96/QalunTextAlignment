from __future__ import annotations

import time
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any

from qurantext.config.settings import DEFAULT_MODEL_REF, get_settings
from qurantext.io.writers import write_json
from qurantext.services.transcript_cache import cache_key, load_cached, store_cached

# Gateway/rate-limit statuses that reflect a transient edge failure rather than a
# real problem with the prediction — safe to retry against the same prediction.
_TRANSIENT_STATUS_CODES = frozenset({429, 502, 503, 504})
_POLL_INTERVAL_SECONDS = 3.0
_MAX_TRANSIENT_RETRIES = 8


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
    #: True when the result came from the cache and nothing was sent anywhere.
    from_cache: bool = False


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


def _transient_status(error: Exception) -> int | None:
    """Return the HTTP status if *error* is a retryable gateway/rate-limit blip."""
    status = getattr(error, "status", None)
    if isinstance(status, int) and status in _TRANSIENT_STATUS_CODES:
        return status
    return None


def _create_prediction(client: Any, resolved_model_ref: str, prediction_input: dict[str, Any]):
    """Start a WhisperX prediction non-blocking, retrying transient create failures.

    A transient 5xx on the (quick, non-blocking) create request means the request
    almost certainly never produced a prediction, so retrying does not orphan a
    running job.
    """
    version_id = resolved_model_ref.split(":", 1)[1] if ":" in resolved_model_ref else None
    owner_name = resolved_model_ref.split(":", 1)[0]

    last_error: Exception | None = None
    for attempt in range(_MAX_TRANSIENT_RETRIES):
        try:
            if version_id is not None:
                return client.predictions.create(version=version_id, input=prediction_input)
            owner, _, name = owner_name.partition("/")
            return client.models.predictions.create(model=(owner, name), input=prediction_input)
        except Exception as error:  # noqa: BLE001 — re-raised below when not transient
            if _transient_status(error) is None:
                raise
            last_error = error
            time.sleep(min(_POLL_INTERVAL_SECONDS * (attempt + 1), 30.0))

    raise WhisperXServiceError(
        f"WhisperX transcription failed: Replicate kept returning gateway errors while "
        f"starting the prediction ({last_error})."
    )


def _await_prediction_output(prediction: Any) -> Any:
    """Poll *prediction* to completion, treating transient gateway errors as retries.

    ``replicate.run`` holds one long blocking request open, so a transient 502 from
    Replicate's gateway aborts the whole call even though the prediction itself
    succeeds on the backend. Polling with ``reload`` recovers that already-finished
    result: each poll is a fresh, retryable GET against the same prediction id.
    """
    terminal = {"succeeded", "failed", "canceled"}
    transient_streak = 0
    while prediction.status not in terminal:
        time.sleep(_POLL_INTERVAL_SECONDS)
        try:
            prediction.reload()
            transient_streak = 0
        except Exception as error:  # noqa: BLE001 — re-raised below when not transient
            if _transient_status(error) is None:
                raise
            transient_streak += 1
            if transient_streak > _MAX_TRANSIENT_RETRIES:
                raise WhisperXServiceError(
                    "WhisperX transcription failed: Replicate's gateway kept returning errors "
                    f"while polling prediction {prediction.id}. The prediction may still "
                    "complete — check the Replicate dashboard."
                ) from error

    if prediction.status != "succeeded":
        detail = prediction.error or f"prediction {prediction.status}"
        raise WhisperXServiceError(f"WhisperX transcription failed: {detail}")

    return prediction.output


def transcribe_audio(
    audio_path: str | PathLike[str],
    *,
    save_raw_to: str | PathLike[str] | None = None,
    model_ref: str | None = None,
    use_cache: bool = True,
) -> WhisperXResult:
    """Transcribe an audio file with WhisperX on Replicate.

    The same audio with the same settings always gives the same transcript, so
    the result is cached against the audio's content. A repeat run — correcting
    one subtitle line and rendering again, say — costs nothing and needs no
    network. Pass ``use_cache=False`` to force a fresh call.
    """
    audio_file_path = Path(audio_path)
    if not audio_file_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

    settings = get_settings()
    resolved_model_ref = model_ref or settings.whisperx.model_ref or DEFAULT_MODEL_REF

    key: str | None = None
    if use_cache:
        key = cache_key(
            audio_file_path,
            {"model": resolved_model_ref, **settings.whisperx.input_kwargs()},
        )
        cached = load_cached(key)
        if cached is not None:
            raw_output_path = (
                save_raw_output(cached, save_raw_to) if save_raw_to is not None else None
            )
            return WhisperXResult(
                output=cached,
                audio_path=str(audio_file_path),
                raw_output_path=raw_output_path,
                model_ref=resolved_model_ref,
                segment_count=_count_segments(cached),
                word_count=_count_words(cached),
                from_cache=True,
            )

    if not settings.replicate_api_token:
        from qurantext.config.paths import user_data_dir

        raise WhisperXServiceError(
            "No Replicate API token is set, so audio cannot be transcribed.\n"
            f"Create a file named .env in {user_data_dir()} containing one line:\n"
            "  REPLICATE_API_TOKEN=your-token\n"
            "Get a token from https://replicate.com/account/api-tokens, then "
            "restart the app — settings are read once at startup."
        )

    try:
        import replicate

        client = replicate.Client(api_token=settings.replicate_api_token)
        with audio_file_path.open("rb") as audio_file:
            prediction = _create_prediction(
                client,
                resolved_model_ref,
                {**settings.whisperx.input_kwargs(), "audio_file": audio_file},
            )
        # Poll after the file handle is closed — the audio is already uploaded.
        output = _await_prediction_output(prediction)
    except WhisperXServiceError:
        raise
    except Exception as error:
        error_text = str(error)
        status = getattr(error, "status", None)
        if "status: 401" in error_text or status == 401 or "Unauthenticated" in error_text:
            # Worth spelling out: a 401 means a token arrived and was refused,
            # which looks identical to having no token unless the message says
            # otherwise. The token is described rather than printed, because
            # this text ends up in logs people send to other people.
            from qurantext.config.paths import user_data_dir
            from qurantext.config.settings import describe_secret

            raise WhisperXServiceError(
                "Replicate rejected the API token.\n"
                f"What was sent: {describe_secret(settings.replicate_api_token)}.\n"
                "Compare that against the token at "
                "https://replicate.com/account/api-tokens — a Replicate token "
                "starts with 'r8_'. If it does not match, the likely cause is "
                "that REPLICATE_API_TOKEN is also set as a system environment "
                "variable, which takes precedence over the .env file in "
                f"{user_data_dir()}."
            ) from error
        if "status: 404" in error_text or status == 404:
            raise WhisperXServiceError(
                f"Replicate could not find the model: {resolved_model_ref}\n"
                "Check that the model exists and that your account has access to it."
            ) from error
        raise WhisperXServiceError(f"WhisperX transcription failed: {error_text}") from error

    if key is not None:
        store_cached(key, _normalize_output_for_json(output))

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

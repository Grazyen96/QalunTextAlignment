"""WhisperX on Replicate: the online engine.

Moved unchanged from ``transcription.py`` when a second, local engine arrived.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from qurantext.config.settings import AppSettings
from qurantext.services.errors import WhisperXServiceError

# Gateway/rate-limit statuses that reflect a transient edge failure rather than a
# real problem with the prediction — safe to retry against the same prediction.
_TRANSIENT_STATUS_CODES = frozenset({429, 502, 503, 504})
_POLL_INTERVAL_SECONDS = 3.0
_MAX_TRANSIENT_RETRIES = 8


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


def cache_settings(settings: AppSettings, model_ref: str) -> dict[str, Any]:
    """The settings that shape a WhisperX transcript. Unchanged, so old cache entries still hit."""
    return {"model": model_ref, **settings.whisperx.input_kwargs()}


def run_whisperx(audio_file_path: Path, settings: AppSettings, model_ref: str) -> Any:
    """Upload *audio_file_path* to Replicate and return WhisperX's raw output."""
    if not settings.replicate_api_token:
        from qurantext.config.settings import env_dir

        raise WhisperXServiceError(
            "No Replicate API token is set, so audio cannot be transcribed.\n"
            f"Create a file named .env in {env_dir()} containing one line:\n"
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
                model_ref,
                {**settings.whisperx.input_kwargs(), "audio_file": audio_file},
            )
        # Poll after the file handle is closed — the audio is already uploaded.
        return _await_prediction_output(prediction)
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
            from qurantext.config.settings import describe_secret, env_dir

            raise WhisperXServiceError(
                "Replicate rejected the API token.\n"
                f"What was sent: {describe_secret(settings.replicate_api_token)}.\n"
                "Compare that against the token at "
                "https://replicate.com/account/api-tokens — a Replicate token "
                "starts with 'r8_'. If it does not match, the likely cause is "
                "that REPLICATE_API_TOKEN is also set as a system environment "
                "variable, which takes precedence over the .env file in "
                f"{env_dir()}."
            ) from error
        if "status: 404" in error_text or status == 404:
            raise WhisperXServiceError(
                f"Replicate could not find the model: {model_ref}\n"
                "Check that the model exists and that your account has access to it."
            ) from error
        raise WhisperXServiceError(f"WhisperX transcription failed: {error_text}") from error

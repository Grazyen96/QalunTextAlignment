from __future__ import annotations

import pytest

from qurantext.services import engine_whisperx
from qurantext.services.engine_whisperx import (
    WhisperXServiceError,
    _await_prediction_output,
    _transient_status,
)


class _FakeReplicateError(Exception):
    """Mimics replicate.exceptions.ReplicateError (carries an HTTP status)."""

    def __init__(self, status: int) -> None:
        super().__init__(f"ReplicateError Details:\nstatus: {status}")
        self.status = status


class _FakePrediction:
    """A prediction whose polls fail transiently before it reports success."""

    def __init__(self, statuses, *, reload_errors=(), output=None, error=None) -> None:
        self.id = "pred-123"
        self._statuses = list(statuses)
        self.status = self._statuses.pop(0)
        self._reload_errors = list(reload_errors)
        self.output = output
        self.error = error

    def reload(self) -> None:
        if self._reload_errors:
            raise self._reload_errors.pop(0)
        if self._statuses:
            self.status = self._statuses.pop(0)


def test_transient_status_detects_gateway_codes() -> None:
    assert _transient_status(_FakeReplicateError(502)) == 502
    assert _transient_status(_FakeReplicateError(503)) == 503
    assert _transient_status(_FakeReplicateError(404)) is None
    assert _transient_status(ValueError("boom")) is None


def test_await_prediction_output_recovers_after_transient_502(monkeypatch) -> None:
    monkeypatch.setattr(engine_whisperx.time, "sleep", lambda _s: None)

    prediction = _FakePrediction(
        statuses=["processing", "succeeded"],
        reload_errors=[_FakeReplicateError(502)],  # one gateway blip while polling
        output={"segments": [{"words": [{"word": "a"}]}]},
    )
    output = _await_prediction_output(prediction)
    assert output == {"segments": [{"words": [{"word": "a"}]}]}


def test_await_prediction_output_raises_on_failed_status(monkeypatch) -> None:
    monkeypatch.setattr(engine_whisperx.time, "sleep", lambda _s: None)

    prediction = _FakePrediction(statuses=["failed"], error="model crashed")
    with pytest.raises(WhisperXServiceError, match="model crashed"):
        _await_prediction_output(prediction)


def test_await_prediction_output_gives_up_after_persistent_gateway_errors(monkeypatch) -> None:
    monkeypatch.setattr(engine_whisperx.time, "sleep", lambda _s: None)

    prediction = _FakePrediction(
        statuses=["processing"],
        reload_errors=[_FakeReplicateError(502)] * 50,
    )
    with pytest.raises(WhisperXServiceError, match="check the Replicate dashboard"):
        _await_prediction_output(prediction)


def test_await_prediction_output_propagates_non_transient_error(monkeypatch) -> None:
    monkeypatch.setattr(engine_whisperx.time, "sleep", lambda _s: None)

    prediction = _FakePrediction(
        statuses=["processing"],
        reload_errors=[_FakeReplicateError(404)],
    )
    with pytest.raises(_FakeReplicateError):
        _await_prediction_output(prediction)


class TestRejectedToken:
    """A 401 means a token arrived and was refused.

    That is a different problem from having no token, and it used to surface as
    the raw text of whatever the client threw, which says nothing a person can
    act on.
    """

    class _Unauthenticated(Exception):
        status = 401

        def __str__(self) -> str:
            return "ReplicateError Details:\ntitle: Unauthenticated\nstatus: 401"

    def _run(self, monkeypatch, tmp_path, token: str):
        import qurantext.config.settings as settings_module
        from qurantext.services import engine_whisperx, transcription

        audio = tmp_path / "a.wav"
        audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
        settings_module.get_settings.cache_clear()
        monkeypatch.setenv("REPLICATE_API_TOKEN", token)
        monkeypatch.setattr(
            engine_whisperx,
            "_create_prediction",
            lambda *a, **k: (_ for _ in ()).throw(self._Unauthenticated()),
        )
        try:
            transcription.transcribe_audio(str(audio), use_cache=False)
        except Exception as error:
            return str(error)
        finally:
            settings_module.get_settings.cache_clear()
        raise AssertionError("expected a failure")

    def test_says_the_token_was_rejected_not_that_it_is_missing(
        self, monkeypatch, tmp_path
    ) -> None:
        message = self._run(monkeypatch, tmp_path, "r8_a_token_that_is_wrong")
        assert "rejected" in message.lower()
        assert "is not set" not in message

    def test_describes_the_token_without_printing_it(self, monkeypatch, tmp_path) -> None:
        secret = "r8_a_token_that_is_wrong"
        message = self._run(monkeypatch, tmp_path, secret)
        assert secret not in message
        assert secret[-4:] in message

    def test_names_the_thing_that_silently_overrides_the_file(self, monkeypatch, tmp_path) -> None:
        """A system variable beats the .env file, which is invisible otherwise."""
        message = self._run(monkeypatch, tmp_path, "r8_a_token_that_is_wrong")
        assert "environment variable" in message
        assert ".env" in message


def test_every_transcription_error_shares_one_base() -> None:
    from qurantext.services.errors import (
        LocalEngineError,
        ModelDownloadError,
        ModelLoadError,
        TranscriptionError,
        WhisperXServiceError,
    )

    for cls in (WhisperXServiceError, ModelDownloadError, LocalEngineError, ModelLoadError):
        assert issubclass(cls, TranscriptionError)
    assert issubclass(ModelLoadError, LocalEngineError)
    assert issubclass(TranscriptionError, RuntimeError)


def test_old_names_still_import_from_transcription() -> None:
    from qurantext.services import errors, transcription

    assert transcription.WhisperXServiceError is errors.WhisperXServiceError
    assert transcription.WhisperXResult is transcription.TranscriptionResult


def test_result_records_its_engine() -> None:
    from qurantext.services.transcription import TranscriptionResult

    result = TranscriptionResult(
        output={},
        audio_path="a",
        raw_output_path=None,
        model_ref="m",
        segment_count=0,
        word_count=0,
    )
    assert result.engine == "whisperx"
    assert result.from_cache is False

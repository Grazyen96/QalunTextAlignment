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


class TestEngineChoice:
    def test_an_explicit_engine_wins_over_the_setting(self, monkeypatch) -> None:
        from qurantext.config.settings import get_settings
        from qurantext.services.transcription import resolve_engine

        monkeypatch.setenv("QURANTEXT_TRANSCRIBE_ENGINE", "local")
        get_settings.cache_clear()
        assert resolve_engine("whisperx", get_settings()) == "whisperx"
        assert resolve_engine(None, get_settings()) == "local"
        get_settings.cache_clear()

    def test_an_unknown_engine_names_the_choices(self, monkeypatch) -> None:
        from qurantext.config.settings import get_settings
        from qurantext.services.transcription import resolve_engine

        with pytest.raises(ValueError, match="local.*whisperx"):
            resolve_engine("cohere", get_settings())

    def test_the_whisperx_cache_key_is_unchanged(self, monkeypatch, tmp_path) -> None:
        """Existing cached transcripts must keep hitting after the engine seam."""
        from qurantext.config.settings import get_settings
        from qurantext.services import engine_whisperx

        settings = get_settings()
        assert engine_whisperx.cache_settings(settings, "m") == {
            "model": "m",
            **settings.whisperx.input_kwargs(),
        }

    def test_progress_and_cancel_are_accepted(self, monkeypatch, tmp_path) -> None:
        from qurantext.config.settings import get_settings
        from qurantext.services import engine_whisperx, transcription
        from qurantext.utils.progress import CancelToken

        audio = tmp_path / "a.wav"
        audio.write_bytes(b"RIFF....WAVE")
        monkeypatch.setenv("QURANTEXT_CACHE_DIR", str(tmp_path / "cache"))
        get_settings.cache_clear()
        monkeypatch.setattr(engine_whisperx, "run_whisperx", lambda *_a, **_k: {"segments": []})
        result = transcription.transcribe_audio(
            audio, engine="whisperx", progress=lambda _e: None, cancel=CancelToken()
        )
        get_settings.cache_clear()
        assert result.engine == "whisperx"


def test_detection_passes_engine_progress_and_cancel(monkeypatch, tmp_path) -> None:
    from qurantext.config.paths import DEFAULT_QURAN_PATH
    from qurantext.pipelines import detection
    from qurantext.utils.progress import CancelToken

    seen = {}

    def fake(audio, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop after the call")

    monkeypatch.setattr(detection, "transcribe_audio", fake)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF....WAVE")
    token = CancelToken()
    with pytest.raises(RuntimeError, match="stop after the call"):
        detection.run_detection(
            quran=DEFAULT_QURAN_PATH,
            output=tmp_path / "m.json",
            mode="lecture",
            audio=audio,
            echo=False,
            engine="whisperx",
            cancel=token,
        )
    assert seen["engine"] == "whisperx"
    assert seen["cancel"] is token
    assert "progress" in seen

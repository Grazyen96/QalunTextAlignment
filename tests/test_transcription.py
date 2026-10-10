from __future__ import annotations

from types import SimpleNamespace

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
            transcription.transcribe_audio(str(audio), use_cache=False, engine="whisperx")
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


class TestEngineErrors:
    def test_a_bad_environment_value_names_the_variable(self, monkeypatch) -> None:
        from qurantext.config.settings import get_settings
        from qurantext.services.transcription import resolve_engine

        monkeypatch.setenv("QURANTEXT_TRANSCRIBE_ENGINE", "nemo")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="QURANTEXT_TRANSCRIBE_ENGINE.*nemo.*local, whisperx"):
            resolve_engine(None, get_settings())
        get_settings.cache_clear()

    def test_a_blank_environment_value_means_the_default(self, monkeypatch) -> None:
        from qurantext.config.settings import DEFAULT_TRANSCRIBE_ENGINE, get_settings

        monkeypatch.setenv("QURANTEXT_TRANSCRIBE_ENGINE", "   ")
        get_settings.cache_clear()
        assert get_settings().transcription.engine == DEFAULT_TRANSCRIBE_ENGINE
        get_settings.cache_clear()

    def test_a_failed_raw_save_is_a_transcription_error(self, monkeypatch, tmp_path) -> None:
        from qurantext.config.settings import get_settings
        from qurantext.services import engine_whisperx, transcription
        from qurantext.services.errors import TranscriptionError

        audio = tmp_path / "a.wav"
        audio.write_bytes(b"RIFF....WAVE")
        monkeypatch.setenv("QURANTEXT_CACHE_DIR", str(tmp_path / "cache"))
        get_settings.cache_clear()
        monkeypatch.setattr(engine_whisperx, "run_whisperx", lambda *_a, **_k: {"segments": []})

        def boom(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(transcription, "save_raw_output", boom)
        with pytest.raises(TranscriptionError, match="saving raw output failed: disk full"):
            transcription.transcribe_audio(
                audio, engine="whisperx", save_raw_to=tmp_path / "r.json"
            )
        get_settings.cache_clear()

    def test_a_failed_raw_save_on_a_cache_hit_is_a_transcription_error(
        self, monkeypatch, tmp_path
    ) -> None:
        """A hit saves the raw output too, and must fail the same way as a fresh run."""
        from qurantext.config.settings import get_settings
        from qurantext.services import engine_whisperx, transcription
        from qurantext.services.errors import TranscriptionError

        audio = tmp_path / "a.wav"
        audio.write_bytes(b"RIFF....WAVE")
        monkeypatch.setenv("QURANTEXT_CACHE_DIR", str(tmp_path / "cache"))
        get_settings.cache_clear()
        monkeypatch.setattr(engine_whisperx, "run_whisperx", lambda *_a, **_k: {"segments": []})
        transcription.transcribe_audio(audio, engine="whisperx")

        def boom(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(transcription, "save_raw_output", boom)
        with pytest.raises(TranscriptionError, match="saving raw output failed: disk full"):
            transcription.transcribe_audio(
                audio, engine="whisperx", save_raw_to=tmp_path / "r.json"
            )
        get_settings.cache_clear()


def test_word_alignment_passes_engine_progress_and_cancel(monkeypatch, tmp_path) -> None:
    from qurantext.config.paths import DEFAULT_QURAN_PATH
    from qurantext.pipelines import recitation
    from qurantext.utils.progress import CancelToken

    seen = {}

    def fake(audio, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop after the call")

    monkeypatch.setattr(recitation, "transcribe_audio", fake)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF....WAVE")
    token = CancelToken()

    def on_progress(_event) -> None:
        pass

    with pytest.raises(RuntimeError, match="stop after the call"):
        recitation.run_word_alignment(
            DEFAULT_QURAN_PATH, audio, engine="local", progress=on_progress, cancel=token
        )
    assert seen["engine"] == "local"
    assert seen["progress"] is on_progress
    assert seen["cancel"] is token


def test_recitation_range_passes_engine_progress_and_cancel(monkeypatch, tmp_path) -> None:
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
        detection.run_recitation_range(
            quran=DEFAULT_QURAN_PATH,
            output=tmp_path / "m.json",
            surah_num=1,
            from_ayah=1,
            to_ayah=2,
            audio=audio,
            echo=False,
            engine="local",
            cancel=token,
        )
    assert seen["engine"] == "local"
    assert seen["cancel"] is token
    assert "progress" in seen


class TestLocalEngine:
    @pytest.fixture
    def env(self, monkeypatch, tmp_path):
        from qurantext.config.settings import get_settings
        from qurantext.services import engine_local, model_store, transcription

        monkeypatch.setenv("QURANTEXT_CACHE_DIR", str(tmp_path / "cache"))
        get_settings.cache_clear()
        calls = {"ensure": 0, "run": 0, "discard": 0, "verify": 0}
        # A fresh process: nothing checked yet. The runtime is there and the files intact.
        monkeypatch.setattr(transcription, "_VERIFIED", set())
        monkeypatch.setattr(engine_local, "runtime_problem", lambda: None)

        def verify(_m):
            calls["verify"] += 1
            return True

        monkeypatch.setattr(model_store, "verify_installed", verify)
        monkeypatch.setattr(
            model_store,
            "ensure_model",
            lambda m, **k: calls.__setitem__("ensure", calls["ensure"] + 1) or tmp_path,
        )
        monkeypatch.setattr(
            model_store, "discard", lambda m: calls.__setitem__("discard", calls["discard"] + 1)
        )
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"RIFF....WAVE")
        yield SimpleNamespace(
            calls=calls, audio=audio, engine_local=engine_local, model_store=model_store
        )
        get_settings.cache_clear()

    def test_local_is_the_default(self, env, monkeypatch) -> None:
        from qurantext.config.settings import get_settings
        from qurantext.services import transcription

        monkeypatch.delenv("QURANTEXT_TRANSCRIBE_ENGINE", raising=False)
        get_settings.cache_clear()
        monkeypatch.setattr(env.engine_local, "transcribe_local", lambda *a, **k: {"segments": []})
        result = transcription.transcribe_audio(env.audio)
        assert result.engine == "local"
        assert result.model_ref == env.model_store.LOCAL_MODEL.ref

    def test_a_repeat_run_hits_the_cache(self, env, monkeypatch) -> None:
        from qurantext.services import transcription

        def run(*_a, **_k):
            env.calls["run"] += 1
            return {"segments": []}

        monkeypatch.setattr(env.engine_local, "transcribe_local", run)
        transcription.transcribe_audio(env.audio, engine="local")
        second = transcription.transcribe_audio(env.audio, engine="local")
        assert env.calls["run"] == 1 and second.from_cache is True

    def test_cancelled_local_run_caches_nothing(self, env, monkeypatch) -> None:
        from qurantext.services import transcription
        from qurantext.utils.progress import JobCancelled

        def cancelled(*_a, **_k):
            raise JobCancelled("transcribe was cancelled")

        monkeypatch.setattr(env.engine_local, "transcribe_local", cancelled)
        with pytest.raises(JobCancelled):
            transcription.transcribe_audio(env.audio, engine="local")
        monkeypatch.setattr(env.engine_local, "transcribe_local", lambda *a, **k: {"segments": []})
        assert transcription.transcribe_audio(env.audio, engine="local").from_cache is False

    def test_a_damaged_model_is_downloaded_again_once(self, env, monkeypatch) -> None:
        from qurantext.services import transcription
        from qurantext.services.errors import ModelLoadError

        attempts = {"n": 0}

        def run(*_a, **_k):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ModelLoadError("bad file")
            return {"segments": []}

        checks = iter([True, False])  # intact before loading, damaged once it would not load
        monkeypatch.setattr(env.engine_local, "transcribe_local", run)
        monkeypatch.setattr(env.model_store, "verify_installed", lambda m: next(checks))
        transcription.transcribe_audio(env.audio, engine="local")
        assert env.calls["discard"] == 1 and env.calls["ensure"] == 2

    def test_files_are_checked_once_per_process_before_the_first_load(
        self, env, monkeypatch
    ) -> None:
        """A damaged file is replaced before loading: some damage ends the process instead."""
        from qurantext.services import transcription

        checks = iter([False])
        loads_after_discard: list[int] = []

        def run(*_a, **_k):
            loads_after_discard.append(env.calls["discard"])
            return {"segments": []}

        monkeypatch.setattr(env.engine_local, "transcribe_local", run)
        monkeypatch.setattr(env.model_store, "verify_installed", lambda m: next(checks))
        transcription.transcribe_audio(env.audio, engine="local")
        assert env.calls["discard"] == 1 and env.calls["ensure"] == 2
        assert loads_after_discard == [1]
        # The second job in the same process does not check again (iter would raise).
        transcription.transcribe_audio(env.audio, engine="local", use_cache=False)
        assert env.calls["discard"] == 1 and loads_after_discard == [1, 1]

    def test_a_second_load_failure_names_the_fix_and_caches_nothing(self, env, monkeypatch) -> None:
        from qurantext.services import transcription
        from qurantext.services.errors import (
            LocalEngineError,
            ModelLoadError,
            TranscriptionError,
        )

        def run(*_a, **_k):
            raise ModelLoadError("still broken")

        checks = iter([True, False])
        monkeypatch.setattr(env.engine_local, "transcribe_local", run)
        monkeypatch.setattr(env.model_store, "verify_installed", lambda m: next(checks))
        with pytest.raises(LocalEngineError, match="still broken") as caught:
            transcription.transcribe_audio(env.audio, engine="local")
        assert isinstance(caught.value, TranscriptionError)
        assert "--doctor" in str(caught.value) and "WhisperX online" in str(caught.value)
        assert env.calls["discard"] == 1 and env.calls["ensure"] == 2
        monkeypatch.setattr(env.engine_local, "transcribe_local", lambda *a, **k: {"segments": []})
        assert transcription.transcribe_audio(env.audio, engine="local").from_cache is False

    def test_a_missing_runtime_fails_before_downloading(self, env, monkeypatch) -> None:
        from qurantext.services import transcription
        from qurantext.services.errors import LocalEngineError

        monkeypatch.setattr(
            env.engine_local, "runtime_problem", lambda: "No module named 'sherpa_onnx'"
        )
        with pytest.raises(LocalEngineError, match="speech runtime.*sherpa_onnx"):
            transcription.transcribe_audio(env.audio, engine="local")
        assert env.calls["ensure"] == 0

    def test_a_cancel_during_recognition_caches_nothing(self, env, monkeypatch, tmp_path) -> None:
        import functools
        import shutil
        import subprocess

        from qurantext.services import transcription
        from qurantext.utils.progress import CancelToken, JobCancelled

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            pytest.skip("needs ffmpeg")
        audio = tmp_path / "long.wav"
        subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:r=16000:d=150", audio],
            check=True,
        )

        class Recogniser:
            def create_stream(self):
                return SimpleNamespace(
                    accept_waveform=lambda *_: None,
                    result=SimpleNamespace(tokens=[" قال"], timestamps=[0.1]),
                )

            def decode_streams(self, streams):
                pass

        real = env.engine_local.transcribe_local
        monkeypatch.setattr(
            env.engine_local,
            "transcribe_local",
            functools.partial(real, recognizer_factory=lambda *_: Recogniser()),
        )
        token = CancelToken()

        def cancel_after_first_batch(event) -> None:
            if event.stage == "transcribe" and event.fraction is not None:
                token.cancel()

        with pytest.raises(JobCancelled):
            transcription.transcribe_audio(
                audio, engine="local", progress=cancel_after_first_batch, cancel=token
            )
        finished = transcription.transcribe_audio(audio, engine="local")
        assert (
            finished.from_cache is False and finished.word_count > 4
        )  # every window, not one batch

    def test_an_intact_model_that_will_not_load_is_not_downloaded_again(
        self, env, monkeypatch
    ) -> None:
        from qurantext.services import transcription
        from qurantext.services.errors import LocalEngineError, ModelLoadError

        def run(*_a, **_k):
            raise ModelLoadError("runtime missing")

        monkeypatch.setattr(env.engine_local, "transcribe_local", run)
        monkeypatch.setattr(env.model_store, "verify_installed", lambda m: True)
        with pytest.raises(LocalEngineError):
            transcription.transcribe_audio(env.audio, engine="local")
        assert env.calls["discard"] == 0

    def test_the_local_cache_key_changes_with_the_model(self, env, monkeypatch) -> None:
        from dataclasses import replace

        from qurantext.services import transcription

        monkeypatch.setattr(env.engine_local, "transcribe_local", lambda *a, **k: {"segments": []})
        transcription.transcribe_audio(env.audio, engine="local")
        monkeypatch.setattr(
            env.model_store, "LOCAL_MODEL", replace(env.model_store.LOCAL_MODEL, version="next")
        )
        assert transcription.transcribe_audio(env.audio, engine="local").from_cache is False

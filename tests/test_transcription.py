from __future__ import annotations

import pytest

from qurantext.services import transcription
from qurantext.services.transcription import (
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
    monkeypatch.setattr(transcription.time, "sleep", lambda _s: None)

    prediction = _FakePrediction(
        statuses=["processing", "succeeded"],
        reload_errors=[_FakeReplicateError(502)],  # one gateway blip while polling
        output={"segments": [{"words": [{"word": "a"}]}]},
    )
    output = _await_prediction_output(prediction)
    assert output == {"segments": [{"words": [{"word": "a"}]}]}


def test_await_prediction_output_raises_on_failed_status(monkeypatch) -> None:
    monkeypatch.setattr(transcription.time, "sleep", lambda _s: None)

    prediction = _FakePrediction(statuses=["failed"], error="model crashed")
    with pytest.raises(WhisperXServiceError, match="model crashed"):
        _await_prediction_output(prediction)


def test_await_prediction_output_gives_up_after_persistent_gateway_errors(monkeypatch) -> None:
    monkeypatch.setattr(transcription.time, "sleep", lambda _s: None)

    prediction = _FakePrediction(
        statuses=["processing"],
        reload_errors=[_FakeReplicateError(502)] * 50,
    )
    with pytest.raises(WhisperXServiceError, match="check the Replicate dashboard"):
        _await_prediction_output(prediction)


def test_await_prediction_output_propagates_non_transient_error(monkeypatch) -> None:
    monkeypatch.setattr(transcription.time, "sleep", lambda _s: None)

    prediction = _FakePrediction(
        statuses=["processing"],
        reload_errors=[_FakeReplicateError(404)],
    )
    with pytest.raises(_FakeReplicateError):
        _await_prediction_output(prediction)

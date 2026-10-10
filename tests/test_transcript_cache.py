"""Remembering a transcript so the same audio is never sent twice.

Recognition is the one stage that is slow, billed and needs the network, and it
is perfectly repeatable. Without this, correcting one subtitle line and
rendering again paid for the whole recording a second time.
"""

from __future__ import annotations

import json

import pytest

from qurantext.services import transcript_cache as tc


@pytest.fixture()
def audio(tmp_path):
    path = tmp_path / "a.mp3"
    path.write_bytes(b"pretend this is audio" * 100)
    return path


SETTINGS = {"model": "whisperx:abc", "language": "ar"}


def test_the_key_follows_the_bytes_not_the_name(tmp_path, audio) -> None:
    """Renaming or moving a file must still hit the cache."""
    moved = tmp_path / "renamed.mp3"
    moved.write_bytes(audio.read_bytes())
    assert tc.cache_key(audio, SETTINGS) == tc.cache_key(moved, SETTINGS)


def test_editing_the_audio_misses(tmp_path, audio) -> None:
    before = tc.cache_key(audio, SETTINGS)
    audio.write_bytes(audio.read_bytes() + b"more")
    assert tc.cache_key(audio, SETTINGS) != before


def test_settings_that_change_the_output_change_the_key(audio) -> None:
    """Switching model or language must recognise again, not return something stale."""
    base = tc.cache_key(audio, SETTINGS)
    assert tc.cache_key(audio, {**SETTINGS, "model": "other"}) != base
    assert tc.cache_key(audio, {**SETTINGS, "language": "en"}) != base
    # Key order is not a difference.
    assert tc.cache_key(audio, dict(reversed(list(SETTINGS.items())))) == base


def test_store_then_load_round_trips(tmp_path, audio) -> None:
    root = tmp_path / "cache"
    key = tc.cache_key(audio, SETTINGS)
    assert tc.load_cached(key, root=root) is None

    payload = {"segments": [{"words": [{"word": "سَلَام", "start": 0.0, "end": 1.0}]}]}
    written = tc.store_cached(key, payload, root=root)

    assert written is not None and written.exists()
    assert tc.load_cached(key, root=root) == payload


def test_a_damaged_entry_is_a_miss_not_a_crash(tmp_path, audio) -> None:
    root = tmp_path / "cache"
    key = tc.cache_key(audio, SETTINGS)
    path = tc.cache_path(key, root=root)
    path.parent.mkdir(parents=True)
    path.write_text("{ truncated", encoding="utf-8")
    assert tc.load_cached(key, root=root) is None


def test_a_cache_that_cannot_be_written_is_reported_not_raised(
    tmp_path, audio, monkeypatch
) -> None:
    """A read-only cache directory must not fail someone's render."""

    def boom(*_args, **_kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr("pathlib.Path.mkdir", boom)
    assert tc.store_cached("deadbeef", {"a": 1}, root=tmp_path / "cache") is None


def test_no_partial_file_is_left_behind(tmp_path, audio) -> None:
    """A crash mid-write must not leave something a later run reads as a hit."""
    root = tmp_path / "cache"
    key = tc.cache_key(audio, SETTINGS)
    tc.store_cached(key, {"segments": []}, root=root)
    assert list(root.rglob("*.partial")) == []


def test_transcribe_uses_the_cache_instead_of_the_network(tmp_path, audio, monkeypatch) -> None:
    """The point of the whole module: a second run sends nothing."""
    from qurantext.config.settings import get_settings
    from qurantext.services import engine_whisperx, transcription

    monkeypatch.setenv("QURANTEXT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    get_settings.cache_clear()

    payload = {"segments": [{"words": [{"word": "أ", "start": 0.0, "end": 0.5}]}]}
    calls = {"n": 0}

    def fake_create(_client, _model, _input):
        calls["n"] += 1
        raise AssertionError("should not reach the network on a hit")

    # First run: populate the cache by hand, the way a real call would.
    key = transcription.cache_key(
        audio,
        {"model": get_settings().whisperx.model_ref, **get_settings().whisperx.input_kwargs()},
    )
    transcription.store_cached(key, payload)

    monkeypatch.setattr(engine_whisperx, "_create_prediction", fake_create)
    result = transcription.transcribe_audio(
        audio, save_raw_to=tmp_path / "raw.json", engine="whisperx"
    )
    get_settings.cache_clear()

    assert calls["n"] == 0, "a cache hit must not call out"
    assert result.from_cache is True
    assert result.output == payload
    assert result.word_count == 1
    assert json.loads((tmp_path / "raw.json").read_text(encoding="utf-8")) == payload


def test_use_cache_false_forces_a_fresh_call(tmp_path, audio, monkeypatch) -> None:
    from qurantext.config.settings import get_settings
    from qurantext.services import engine_whisperx, transcription

    monkeypatch.setenv("QURANTEXT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    get_settings.cache_clear()
    key = transcription.cache_key(
        audio,
        {"model": get_settings().whisperx.model_ref, **get_settings().whisperx.input_kwargs()},
    )
    transcription.store_cached(key, {"segments": []})

    reached = {"n": 0}

    def fake_create(*_args, **_kwargs):
        reached["n"] += 1
        raise RuntimeError("stop here")

    monkeypatch.setattr(engine_whisperx, "_create_prediction", fake_create)
    with pytest.raises(transcription.WhisperXServiceError):
        transcription.transcribe_audio(audio, use_cache=False, engine="whisperx")
    get_settings.cache_clear()

    assert reached["n"] == 1, "use_cache=False must bypass the hit"


def test_audio_digest_is_one_shared_function(tmp_path) -> None:
    """The waveform cache and the transcript cache must key on the same digest."""
    import hashlib

    from qurantext.core import waveform
    from qurantext.utils.hashing import audio_digest

    clip = tmp_path / "a.bin"
    clip.write_bytes(b"\x00\x01" * 1_000_000)
    assert audio_digest(clip) == hashlib.sha256(clip.read_bytes()).hexdigest()
    assert tc.audio_digest is audio_digest
    assert waveform.audio_digest is audio_digest

"""The real model on a real recitation. Opt-in: downloads ~110 MB once.

It runs about a minute, or about 15 s once its transcript is cached.

QURANTEXT_SLOW_TESTS=1 venv/bin/python -m pytest tests/test_local_engine_slow.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

CLIP = Path(__file__).resolve().parents[1] / "input/recitations/furquanTra7-11.mp3"

pytestmark = [
    pytest.mark.skipif(os.environ.get("QURANTEXT_SLOW_TESTS") != "1", reason="opt-in slow test"),
    pytest.mark.skipif(not CLIP.exists(), reason="needs the local test recording"),
]


@pytest.fixture(autouse=True)
def _real_cache(_private_cache_dir, monkeypatch):
    """The model and its transcript live in the person's real cache, as the docstring promises.

    The suite points every test at a private cache folder (``_private_cache_dir`` in
    conftest.py), which would download the model on every run; this test takes the
    real one back after that fixture has run.
    """
    monkeypatch.delenv("QURANTEXT_CACHE_DIR", raising=False)


def test_the_real_model_finds_furqan_7_to_11(tmp_path) -> None:
    from qurantext.config.paths import DEFAULT_QURAN_PATH
    from qurantext.pipelines.detection import run_detection
    from qurantext.services.transcription import transcribe_audio

    result = transcribe_audio(CLIP, engine="local", use_cache=False)
    assert result.engine == "local"
    assert result.word_count >= 60

    out = tmp_path / "m.json"
    run_detection(
        quran=DEFAULT_QURAN_PATH,
        output=out,
        mode="recitation",
        audio=CLIP,
        echo=False,
        engine="local",
    )
    match = json.loads(out.read_text(encoding="utf-8"))
    assert (match["first_ayah"]["surah_num"], match["first_ayah"]["ayah_num"]) == (25, 7)
    assert (match["last_ayah"]["surah_num"], match["last_ayah"]["ayah_num"]) == (25, 11)

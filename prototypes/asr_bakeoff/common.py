"""Shared by the engine runners: decode, cut at pauses, write WhisperX-shaped JSON.

Every engine writes the same raw shape the pipeline already reads
(``{"segments": [{"start", "end", "text", "words": [{"word", "start", "end",
"score"}]}]}``), so ``qurantext recitation-match --whisperx-json`` and
``lecture-match`` score all of them with the production code.
"""
import json
import re
import subprocess
from pathlib import Path

import numpy as np

SR = 16000


def load_audio(path: str | Path) -> np.ndarray:
    """Decode any file ffmpeg reads to 16 kHz mono float32."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        check=True,
        capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def chunk_at_pauses(audio: np.ndarray, max_s: float = 28.0, search_s: float = 10.0):
    """Yield (start_sample, end_sample) windows of at most ``max_s`` seconds.

    Each cut lands on the quietest 100 ms frame in the last ``search_s`` seconds
    of the window, so a waqf pause takes the cut instead of a word.
    """
    hop = SR // 10
    n = len(audio) // hop
    rms = np.sqrt(np.array([np.mean(audio[i * hop : (i + 1) * hop] ** 2) for i in range(n)]) + 1e-12)
    max_f, search_f = int(max_s * 10), int(search_s * 10)
    start = 0
    while start < n:
        if n - start <= max_f:
            yield start * hop, len(audio)
            return
        lo, hi = start + max_f - search_f, start + max_f
        cut = lo + int(np.argmin(rms[lo:hi]))
        yield start * hop, cut * hop
        start = cut


def write_whisperx_json(segments: list[dict], path: str | Path, meta: dict) -> None:
    out = {"detected_language": "ar", "segments": segments, "bakeoff_meta": meta}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


# Copy of qurantext.core.arabic.normalize_alignment_ar, so this environment does
# not need the package (and its PySide6 dependency) installed.
_TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")


def normalize_alignment_ar(text: str) -> str:
    text = _TASHKEEL.sub("", text).replace("ـ", "")
    text = re.sub(r"[إأآٱ]", "ا", text)
    text = text.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي").replace("ے", "ي")
    text = re.sub(r"[^ء-ي\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

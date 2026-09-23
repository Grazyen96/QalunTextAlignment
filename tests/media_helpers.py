"""Media the render and export tests share, and the check for whether it exists.

Kept out of any one test module so two modules can use it without importing
fixtures from each other.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from qurantext.config.paths import DEFAULT_FONT_PATH, DEFAULT_QURAN_PATH

__all__ = ["FFMPEG", "FFPROBE", "MEDIA_AVAILABLE", "MEDIA_REASON", "QURAN_FILE", "build_job"]

QURAN_FILE = DEFAULT_QURAN_PATH
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

#: Whether a real render can run here. Each media test module skips on it.
MEDIA_AVAILABLE = bool(FFMPEG and FFPROBE and QURAN_FILE.exists() and DEFAULT_FONT_PATH.exists())
MEDIA_REASON = "needs ffmpeg, ffprobe, the shipped Quran file and the bundled font"


def build_job(tmp_path, seconds=6.0):
    """A two-ayah recitation whose words are timed one every half second."""
    from qurantext.core.quran_parser import parse_ayat

    chosen = [a for a in parse_ayat(QURAN_FILE) if a["surah_num"] == 25 and 7 <= a["ayah_num"] <= 8]
    timings, t = [], 0.0
    for ayah in chosen:
        for token in str(ayah["text_raw"]).split():
            if not all("٠" <= c <= "٩" for c in token.strip()):
                timings.append({"word": token, "start": round(t, 3), "end": round(t + 0.3, 3)})
                t += 0.4

    matches = tmp_path / "m.json"
    matches.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "surah_num": 25,
                        "surah_name": "سُورَةُ الفُرقَانِ",
                        "from_ayah": 7,
                        "to_ayah": 8,
                        "full_text": "\n".join(a["text_raw"] for a in chosen),
                        "confidence": 1.0,
                        "start_time": 0.0,
                        "end_time": round(t, 3),
                        "word_timings": timings,
                    }
                ],
                "meta": {"mode": "recitation"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    audio = tmp_path / "a.m4a"
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            str(max(seconds, t)),
            "-c:a",
            "aac",
            str(audio),
        ],
        check=True,
    )
    return audio, matches

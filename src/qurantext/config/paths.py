from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

INPUT_DIR = PROJECT_ROOT / "input"
QURAN_INPUT_DIR = INPUT_DIR / "quran"
LECTURES_INPUT_DIR = INPUT_DIR / "lectures"
RECITATIONS_INPUT_DIR = INPUT_DIR / "recitations"
# User-supplied basmala spliced before each recitation (see core.basmala).
BASMALA_INPUT_DIR = INPUT_DIR / "basmala"
BASMALA_AUDIO_PATH = BASMALA_INPUT_DIR / "basmala.mp3"

OUTPUT_DIR = PROJECT_ROOT / "output"
VIDEOS_OUTPUT_DIR = OUTPUT_DIR / "videos"

# On-device data store (versioned SQLite build of the certified Qalun text).
DATA_DIR = PROJECT_ROOT / "data"
QURAN_DB_PATH = DATA_DIR / "quran.sqlite"
RECITATION_MATCHING_OUTPUT_DIR = OUTPUT_DIR / "recitation_matching"
LECTURE_MATCHING_OUTPUT_DIR = OUTPUT_DIR / "lecture_matching"
WHISPERX_TRANSCRIPTS_OUTPUT_DIR = OUTPUT_DIR / "whisperx_transcripts"
RANGE_MATCHING_OUTPUT_DIR = OUTPUT_DIR / "range_matching"

REQUIRED_DIRECTORIES = (
    INPUT_DIR,
    QURAN_INPUT_DIR,
    LECTURES_INPUT_DIR,
    RECITATIONS_INPUT_DIR,
    BASMALA_INPUT_DIR,
    OUTPUT_DIR,
    VIDEOS_OUTPUT_DIR,
    RECITATION_MATCHING_OUTPUT_DIR,
    LECTURE_MATCHING_OUTPUT_DIR,
    WHISPERX_TRANSCRIPTS_OUTPUT_DIR,
    RANGE_MATCHING_OUTPUT_DIR,
)


def ensure_required_directories() -> None:
    """Create the standard input/output directory tree when requested."""
    for directory in REQUIRED_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)

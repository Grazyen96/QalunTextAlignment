from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .paths import PROJECT_ROOT

DEFAULT_MODEL_REF = (
    "victor-upmeet/whisperx:84d2ad2d6194fe98a17d2b60bef1c7f910c46b2f6fd38996ca457afd9c8abfcb"
)

DEFAULT_WORD_MATCH_THRESHOLD = 0.80
DEFAULT_AYA_MATCH_THRESHOLD = 0.50

DEFAULT_RANGE_HEAD_WORDS = 80
DEFAULT_RANGE_TAIL_WORDS = 80
DEFAULT_RANGE_SEARCH_RANGE = 20
DEFAULT_RANGE_LOW_CONF = 0.40
DEFAULT_RANGE_POSITION_THRESHOLD = 0.55
DEFAULT_RANGE_POSITION_THRESHOLD_GLOBAL = 0.65
DEFAULT_RANGE_HIGH_CONF_POSITION = 0.75
DEFAULT_RANGE_MIN_WORDS_GLOBAL = 5

DEFAULT_RANGE_MATCHING = {
    "head_words": DEFAULT_RANGE_HEAD_WORDS,
    "tail_words": DEFAULT_RANGE_TAIL_WORDS,
    "search_range": DEFAULT_RANGE_SEARCH_RANGE,
    "low_conf": DEFAULT_RANGE_LOW_CONF,
    "position_threshold": DEFAULT_RANGE_POSITION_THRESHOLD,
    "position_threshold_global": DEFAULT_RANGE_POSITION_THRESHOLD_GLOBAL,
    "high_conf_position": DEFAULT_RANGE_HIGH_CONF_POSITION,
    "min_words_global": DEFAULT_RANGE_MIN_WORDS_GLOBAL,
}

DEFAULT_LECTURE_MAX_SPAN = 5
DEFAULT_LECTURE_MIN_WINDOW_WORDS = 5
DEFAULT_LECTURE_MAX_WINDOW_WORDS = 35
DEFAULT_LECTURE_WINDOW_STEP = 3
DEFAULT_LECTURE_THRESHOLD = 0.78
DEFAULT_LECTURE_MIN_MATCHED_WORDS = 4
DEFAULT_LECTURE_CANDIDATE_LIMIT = 25
DEFAULT_LECTURE_SHORT_PHRASE_THRESHOLD = 0.90
DEFAULT_LECTURE_SHORT_PHRASE_WORD_LIMIT = 6

DEFAULT_LECTURE_MATCHING = {
    "max_span": DEFAULT_LECTURE_MAX_SPAN,
    "min_window_words": DEFAULT_LECTURE_MIN_WINDOW_WORDS,
    "max_window_words": DEFAULT_LECTURE_MAX_WINDOW_WORDS,
    "window_step": DEFAULT_LECTURE_WINDOW_STEP,
    "min_score": DEFAULT_LECTURE_THRESHOLD,
    "min_matched_words": DEFAULT_LECTURE_MIN_MATCHED_WORDS,
    "candidate_limit": DEFAULT_LECTURE_CANDIDATE_LIMIT,
}

# Recitation word-highlight timing corrections (applied by refine_word_timings).
# Offset shifts every highlight start/end to cancel a consistent lag (negative)
# or lead (positive); 0.0 = neutral, dial empirically per reciter. Bridge_max is
# the largest inter-word silence (seconds) that gets closed so spans stay
# continuous — gaps beyond it are treated as genuine pauses and left intact.
DEFAULT_HIGHLIGHT_OFFSET_S = 0.0
DEFAULT_TIMING_BRIDGE_MAX_S = 0.6

DEFAULT_VIDEO_RENDERER = "frame"
DEFAULT_VIDEO_WIDTH = 1280
DEFAULT_VIDEO_HEIGHT = 720
DEFAULT_VIDEO_FPS = 25
# Gaps between consecutive ayah groups are bridged so no black screen shows.
# Gaps up to this many seconds pull the next group back to the previous group's
# end; longer gaps (a genuine pause) split the difference at the midpoint so the
# next card does not sit idle for the whole pause.
DEFAULT_VIDEO_GAP_MIDPOINT_THRESHOLD = 3.0
DEFAULT_VIDEO_FONT_FILE = str(PROJECT_ROOT / "fonts" / "qaloon.10.ttf")
# Splice the shipped input/basmala/basmala.mp3 before each recitation video when
# the recitation does not already open with one (see core.basmala).
DEFAULT_VIDEO_PREPEND_BASMALA = True

# (width, height, fps) tuples for named quality presets.
VIDEO_PRESETS: dict[str, tuple[int, int, int]] = {
    "fast": (960, 540, 24),
    "standard": (1280, 720, 25),
    "high": (1920, 1080, 30),
    "social": (1080, 1920, 30),
}

DEFAULT_VIDEO = {
    "renderer": DEFAULT_VIDEO_RENDERER,
    "width": DEFAULT_VIDEO_WIDTH,
    "height": DEFAULT_VIDEO_HEIGHT,
    "fps": DEFAULT_VIDEO_FPS,
    "gap_midpoint_threshold": DEFAULT_VIDEO_GAP_MIDPOINT_THRESHOLD,
    "prepend_basmala": DEFAULT_VIDEO_PREPEND_BASMALA,
}

DEFAULT_WHISPERX_INPUT = {
    "debug": False,
    "language": "ar",
    "vad_onset": 0.5,
    "batch_size": 64,
    "vad_offset": 0.363,
    "diarization": False,
    "temperature": 0,
    "align_output": True,
    "language_detection_min_prob": 0,
    "language_detection_max_tries": 5,
    # Fake "previous transcript" text Whisper conditions its first window on.
    # A sentence of Quranic/tafseer Arabic biases decoding toward classical
    # vocabulary and spellings, which cleans up quoted ayat inside dars audio.
    # Empty disables the parameter (it is omitted from the request payload).
    "initial_prompt": "",
}


def _parse_env_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    if line.startswith("export "):
        line = line[len("export ") :].strip()

    if "=" not in line:
        return None

    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()

    if not key:
        return None

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]

    return key, value


def _load_env_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return

    with path.open(encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            parsed = _parse_env_line(raw_line)
            if parsed is None:
                continue
            key, value = parsed
            if not value and os.environ.get(key):
                continue
            os.environ[key] = value


def load_project_env() -> None:
    """Load .env files while keeping the current process environment authoritative."""
    existing_env = dict(os.environ)
    _load_env_file(PROJECT_ROOT / ".env")
    _load_env_file(PROJECT_ROOT / ".env.local")

    for key, value in existing_env.items():
        os.environ[key] = value


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _coerce_env(name: str, value: str, caster: Any, kind: str) -> Any:
    try:
        return caster(value)
    except ValueError:
        raise ValueError(f"Environment variable {name}={value!r} is not a valid {kind}.") from None


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return _coerce_env(name, value, int, "integer")


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return _coerce_env(name, value, float, "number")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class WhisperXSettings:
    """Runtime configuration for WhisperX transcription."""

    model_ref: str
    debug: bool
    language: str
    vad_onset: float
    batch_size: int
    vad_offset: float
    diarization: bool
    temperature: float
    align_output: bool
    language_detection_min_prob: float
    language_detection_max_tries: int
    initial_prompt: str

    def input_kwargs(self) -> dict[str, Any]:
        """Return the Replicate input payload excluding the audio file handle."""
        kwargs: dict[str, Any] = {
            "debug": self.debug,
            "language": self.language,
            "vad_onset": self.vad_onset,
            "batch_size": self.batch_size,
            "vad_offset": self.vad_offset,
            "diarization": self.diarization,
            "temperature": self.temperature,
            "align_output": self.align_output,
            "language_detection_min_prob": self.language_detection_min_prob,
            "language_detection_max_tries": self.language_detection_max_tries,
        }
        if self.initial_prompt:
            kwargs["initial_prompt"] = self.initial_prompt
        return kwargs


@dataclass(frozen=True, slots=True)
class RangeMatchingSettings:
    """Runtime defaults for recitation-range detection and scoring."""

    head_words: int
    tail_words: int
    search_range: int
    low_conf: float
    position_threshold: float
    position_threshold_global: float
    high_conf_position: float
    min_words_global: int


@dataclass(frozen=True, slots=True)
class LectureMatchingSettings:
    """Runtime defaults for lecture-style mention detection."""

    max_span: int
    min_window_words: int
    max_window_words: int
    window_step: int
    min_score: float
    min_matched_words: int
    candidate_limit: int


@dataclass(frozen=True, slots=True)
class AlignmentSettings:
    """Runtime corrections applied to recitation word-highlight timings."""

    highlight_offset_s: float
    bridge_max_s: float


@dataclass(frozen=True, slots=True)
class VideoSettings:
    """Runtime defaults for video rendering."""

    renderer: str
    width: int
    height: int
    fps: int
    gap_midpoint_threshold: float
    prepend_basmala: bool


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Top-level runtime settings used by QuranText workflows."""

    replicate_api_token: str | None
    whisperx: WhisperXSettings
    range_matching: RangeMatchingSettings
    lecture_matching: LectureMatchingSettings
    alignment: AlignmentSettings
    video: VideoSettings
    word_match_threshold: float
    aya_match_threshold: float


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Load and cache runtime settings from the environment."""
    load_project_env()

    whisperx = WhisperXSettings(
        model_ref=_env_str("QURANTEXT_WHISPERX_MODEL", DEFAULT_MODEL_REF),
        debug=_env_bool("QURANTEXT_WHISPERX_DEBUG", bool(DEFAULT_WHISPERX_INPUT["debug"])),
        language=_env_str("QURANTEXT_WHISPERX_LANGUAGE", str(DEFAULT_WHISPERX_INPUT["language"])),
        vad_onset=_env_float(
            "QURANTEXT_WHISPERX_VAD_ONSET", float(DEFAULT_WHISPERX_INPUT["vad_onset"])
        ),
        batch_size=_env_int(
            "QURANTEXT_WHISPERX_BATCH_SIZE", int(DEFAULT_WHISPERX_INPUT["batch_size"])
        ),
        vad_offset=_env_float(
            "QURANTEXT_WHISPERX_VAD_OFFSET", float(DEFAULT_WHISPERX_INPUT["vad_offset"])
        ),
        diarization=_env_bool(
            "QURANTEXT_WHISPERX_DIARIZATION",
            bool(DEFAULT_WHISPERX_INPUT["diarization"]),
        ),
        temperature=_env_float(
            "QURANTEXT_WHISPERX_TEMPERATURE",
            float(DEFAULT_WHISPERX_INPUT["temperature"]),
        ),
        align_output=_env_bool(
            "QURANTEXT_WHISPERX_ALIGN_OUTPUT",
            bool(DEFAULT_WHISPERX_INPUT["align_output"]),
        ),
        language_detection_min_prob=_env_float(
            "QURANTEXT_WHISPERX_LANGUAGE_DETECTION_MIN_PROB",
            float(DEFAULT_WHISPERX_INPUT["language_detection_min_prob"]),
        ),
        language_detection_max_tries=_env_int(
            "QURANTEXT_WHISPERX_LANGUAGE_DETECTION_MAX_TRIES",
            int(DEFAULT_WHISPERX_INPUT["language_detection_max_tries"]),
        ),
        initial_prompt=_env_str(
            "QURANTEXT_WHISPERX_INITIAL_PROMPT",
            str(DEFAULT_WHISPERX_INPUT["initial_prompt"]),
        ),
    )

    range_matching = RangeMatchingSettings(
        head_words=_env_int("QURANTEXT_RANGE_HEAD_WORDS", DEFAULT_RANGE_HEAD_WORDS),
        tail_words=_env_int("QURANTEXT_RANGE_TAIL_WORDS", DEFAULT_RANGE_TAIL_WORDS),
        search_range=_env_int("QURANTEXT_RANGE_SEARCH_RANGE", DEFAULT_RANGE_SEARCH_RANGE),
        low_conf=_env_float("QURANTEXT_RANGE_LOW_CONF", DEFAULT_RANGE_LOW_CONF),
        position_threshold=_env_float(
            "QURANTEXT_RANGE_POSITION_THRESHOLD",
            DEFAULT_RANGE_POSITION_THRESHOLD,
        ),
        position_threshold_global=_env_float(
            "QURANTEXT_RANGE_POSITION_THRESHOLD_GLOBAL",
            DEFAULT_RANGE_POSITION_THRESHOLD_GLOBAL,
        ),
        high_conf_position=_env_float(
            "QURANTEXT_RANGE_HIGH_CONF_POSITION",
            DEFAULT_RANGE_HIGH_CONF_POSITION,
        ),
        min_words_global=_env_int(
            "QURANTEXT_RANGE_MIN_WORDS_GLOBAL",
            DEFAULT_RANGE_MIN_WORDS_GLOBAL,
        ),
    )

    lecture_matching = LectureMatchingSettings(
        max_span=_env_int("QURANTEXT_LECTURE_MAX_SPAN", DEFAULT_LECTURE_MAX_SPAN),
        min_window_words=_env_int(
            "QURANTEXT_LECTURE_MIN_WINDOW_WORDS",
            DEFAULT_LECTURE_MIN_WINDOW_WORDS,
        ),
        max_window_words=_env_int(
            "QURANTEXT_LECTURE_MAX_WINDOW_WORDS",
            DEFAULT_LECTURE_MAX_WINDOW_WORDS,
        ),
        window_step=_env_int("QURANTEXT_LECTURE_WINDOW_STEP", DEFAULT_LECTURE_WINDOW_STEP),
        min_score=_env_float("QURANTEXT_LECTURE_THRESHOLD", DEFAULT_LECTURE_THRESHOLD),
        min_matched_words=_env_int(
            "QURANTEXT_LECTURE_MIN_MATCHED_WORDS",
            DEFAULT_LECTURE_MIN_MATCHED_WORDS,
        ),
        candidate_limit=_env_int(
            "QURANTEXT_LECTURE_CANDIDATE_LIMIT",
            DEFAULT_LECTURE_CANDIDATE_LIMIT,
        ),
    )

    alignment = AlignmentSettings(
        highlight_offset_s=_env_float("QURANTEXT_HIGHLIGHT_OFFSET_S", DEFAULT_HIGHLIGHT_OFFSET_S),
        bridge_max_s=_env_float("QURANTEXT_TIMING_BRIDGE_MAX_S", DEFAULT_TIMING_BRIDGE_MAX_S),
    )

    video = VideoSettings(
        renderer=_env_str("QURANTEXT_VIDEO_RENDERER", DEFAULT_VIDEO_RENDERER),
        width=_env_int("QURANTEXT_VIDEO_WIDTH", DEFAULT_VIDEO_WIDTH),
        height=_env_int("QURANTEXT_VIDEO_HEIGHT", DEFAULT_VIDEO_HEIGHT),
        fps=_env_int("QURANTEXT_VIDEO_FPS", DEFAULT_VIDEO_FPS),
        gap_midpoint_threshold=_env_float(
            "QURANTEXT_VIDEO_GAP_MIDPOINT_THRESHOLD", DEFAULT_VIDEO_GAP_MIDPOINT_THRESHOLD
        ),
        prepend_basmala=_env_bool("QURANTEXT_VIDEO_PREPEND_BASMALA", DEFAULT_VIDEO_PREPEND_BASMALA),
    )

    return AppSettings(
        replicate_api_token=os.getenv("REPLICATE_API_TOKEN"),
        whisperx=whisperx,
        range_matching=range_matching,
        lecture_matching=lecture_matching,
        alignment=alignment,
        video=video,
        word_match_threshold=_env_float(
            "QURANTEXT_WORD_MATCH_THRESHOLD",
            DEFAULT_WORD_MATCH_THRESHOLD,
        ),
        aya_match_threshold=_env_float(
            "QURANTEXT_AYA_MATCH_THRESHOLD",
            DEFAULT_AYA_MATCH_THRESHOLD,
        ),
    )

# Architecture

## Overview

QuranText is organized around a small number of stable layers:

- `cli/` handles command-line argument parsing only.
- `config/` centralizes project paths, environment loading, and runtime settings.
- `core/` contains pure Quran parsing, transcript matching, lecture matching, and video rendering logic.
- `io/` loads and saves JSON, WhisperX transcript structures, and subtitle output.
- `services/` contains external integrations such as WhisperX transcription via Replicate.
- `pipelines/` coordinates complete workflows such as recitation matching, detect-range matching, and video generation.
- `scripts/` and root scripts are thin compatibility entry points.

## Module Responsibilities

### `src/qurantext/config`

- `paths.py` defines `PROJECT_ROOT` plus the standard `input/` and `output/` tree.
- `settings.py` loads `.env` and `.env.local`, exposes WhisperX defaults, and centralizes runtime defaults for range matching, lecture matching, and video rendering.

### `src/qurantext/core`

- `arabic.py` contains normalization variants, Arabic-Indic digit helpers, partial-ratio logic, and other shared text helpers.
- `quran_parser.py` parses Qalun-format Quran text and handles surah headers, basmala skipping, and ta'awwudh skipping.
- `range_matching.py` implements first/last ayah detection, confidence scoring, recitation timeline trimming, and warnings.
- `lecture_matching.py` builds ayah spans, scans transcript windows, scores lecture matches, and merges overlapping detections.
- `alignment.py` holds the legacy word- and segment-alignment fuzzy matching helpers.
- `video_common.py` contains shared validation, timing, JSON loading, and rendering helpers.
- `ass_renderer.py` contains ASS subtitle generation, FFmpeg ASS rendering, and font-family validation.
- `frame_renderer.py` contains the Pillow frame renderer and active-match tracking. Frames are
  streamed straight into FFmpeg, so the video is encoded once with no intermediate file.
- `video_renderer.py` is now the thin CLI/orchestration layer over the renderer modules.

### `src/qurantext/io`

- `readers.py` normalizes WhisperX JSON into word or segment lists.
- `writers.py` writes JSON and SRT outputs.

### `src/qurantext/services`

- `transcription.py` wraps Replicate WhisperX transcription with consistent settings and error handling.

### `src/qurantext/pipelines`

- `recitation.py` runs the legacy word-alignment pipeline.
- `detection.py` runs `range`, `lecture`, and `recitation` detect-range workflows.
- `video.py` invokes the packaged video renderer.

## Data Flow

### Detect-range flow

1. Parse Quran text with `core.quran_parser.parse_ayat`.
2. Load or transcribe WhisperX output.
3. Normalize transcript words with `io.readers.extract_matching_words`.
4. Run either:
   - `core.range_matching.detect_first_ayah` / `detect_last_ayah`
   - `core.lecture_matching.detect_quran_mentions_in_lecture`
5. Write JSON output with `io.writers.write_json`.
6. Optionally render a video with the video pipeline.

### Legacy word-align flow

1. Load Quran text.
2. Load or transcribe WhisperX output.
3. Normalize aligned words.
4. Fuzzy-match against canonical Quran words.
5. Write JSON and SRT output.

## Extending The Project

Add new pure matching logic under `core/`.
Add file format readers or writers under `io/`.
Add external services under `services/`.
Add new workflows under `pipelines/` and expose them from `cli/main.py`.
Keep root scripts and `scripts/` wrappers free of business logic.

## Old To New Mapping

- `detect_range.py` -> `src/qurantext/pipelines/detection.py`
- `lecture_mode.py` -> `src/qurantext/core/lecture_matching.py`
- `whisperx_service.py` -> `src/qurantext/services/transcription.py`
- `render_ayat_video.py` -> `src/qurantext/core/video_renderer.py` and `src/qurantext/pipelines/video.py`
- `audioAlignment.py` -> `src/qurantext/core/alignment.py` and `src/qurantext/pipelines/recitation.py`
- `fullAyaAlignment.py` -> retired legacy workflow
- `env_utils.py` -> `src/qurantext/config/settings.py`

## Compatibility Strategy

- The root scripts remain executable wrappers.
- The `scripts/` directory contains additional wrapper entry points.
- The package CLI under `python3 -m qurantext` is the preferred interface going forward.

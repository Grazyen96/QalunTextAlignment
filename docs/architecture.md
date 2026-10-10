# Architecture

## Overview

QuranText is organized around a small number of stable layers:

- `cli/` handles command-line argument parsing only, and is the ONLY parser in
  the project. The duplicate CLIs that lived in `pipelines/detection.py` and
  `core/video_renderer.py` are gone.
- `jobs/` is the callable boundary a user interface drives: typed requests
  (`RenderRequest`, `ExportRequest`), described results, the project file that
  owns a job's cards and editable captions, and the render and export entry points.
- `utils/progress.py` carries the progress event, the console reporter and the
  cancellation token. It sits below `jobs/` so `core/` can depend on it without
  a cycle.
- `config/` centralizes project paths, environment loading, and runtime settings.
- `core/` contains pure Quran parsing, transcript matching, lecture matching, and video rendering logic.
- `io/` loads and saves JSON, WhisperX transcript structures, and subtitle output.
- `services/` contains the transcription engines (a local model by default, WhisperX on Replicate) and the model store.
- `pipelines/` coordinates complete workflows such as recitation matching, detect-range matching, and video generation.
- `gui/` is the desktop window: widgets, a worker thread, and the one call it makes
  into the pipeline. Qt is optional, so nothing outside this package imports it.
- `scripts/` and root scripts are thin compatibility entry points.

## Module Responsibilities

### `src/qurantext/config`

- `paths.py` resolves every file location for both modes the code runs in. From a
  checkout it keeps the repository layout unchanged; installed, user files go to the
  platform's own directories (`%LOCALAPPDATA%`, `~/Library/Application Support`,
  `$XDG_DATA_HOME`) and bundled assets are read from inside the package.
  `QURANTEXT_DATA_DIR` and `QURANTEXT_OUTPUT_DIR` override either.
- `settings.py` loads `.env` and `.env.local`, exposes WhisperX defaults, and centralizes runtime defaults for range matching, lecture matching, and video rendering.

### `src/qurantext/core`

- `arabic.py` contains normalization variants, Arabic-Indic digit helpers, partial-ratio logic, and other shared text helpers.
- `quran_parser.py` parses Qalun-format Quran text and handles surah headers, basmala skipping, and ta'awwudh skipping.
- `range_matching.py` implements first/last ayah detection, confidence scoring, recitation timeline trimming, and warnings.
- `lecture_matching.py` builds ayah spans, scans transcript windows, scores lecture matches, and merges overlapping detections.
- `pause_cut.py` cuts a stream of audio into recognisable windows, at pauses.
- `token_words.py` turns the recogniser's sub-word tokens and their times into timed words.
- `alignment.py` holds the legacy word- and segment-alignment fuzzy matching helpers.
- `video_common.py` contains shared validation, timing, JSON loading, and rendering helpers.
- `ass_renderer.py` contains ASS subtitle generation, FFmpeg ASS rendering, and font-family validation.
- `subtitles.py` builds subtitle cues and writes them as SRT, WebVTT or ASS.
- `coverage.py` finds recited audio that no word timing covers, from the waveform.
- `frame_renderer.py` contains the Pillow frame renderer and active-match tracking. Frames are
  streamed straight into FFmpeg, so the video is encoded once with no intermediate file.
- `video_renderer.py` only re-exports the renderer modules for older imports; the render job itself is `jobs/render.py` (`core/` never imports `jobs/` or `gui/`, which `tests/test_layering.py` enforces).

### `src/qurantext/io`

- `readers.py` normalizes WhisperX JSON into word or segment lists.
- `writers.py` writes JSON and SRT outputs.

### `src/qurantext/services`

- `transcription.py` is the entry point: it chooses the engine and checks the transcript cache (`transcript_cache.py`) before running it.
- `transcript_cache.py` remembers each transcript against the audio's content and the settings that shape it, so the same recording is never recognised twice.
- `engine_local.py` is the local engine: NVIDIA's FastConformer Arabic run by sherpa-onnx on this computer, returning the WhisperX raw shape.
- `engine_whisperx.py` is WhisperX on Replicate, the optional online engine.
- `model_store.py` says where the local speech model lives and downloads it once, checked against pinned sizes and checksums.
- `errors.py` holds the errors a transcription can end in, under one base the CLI and the window catch.

### `src/qurantext/pipelines`

- `video.py` is a thin wrapper over `jobs.render.render_video`; it no longer
  marshals arguments into command-line strings.
- `recitation.py` runs the legacy word-alignment pipeline.
- `detection.py` runs `range`, `lecture`, and `recitation` detect-range workflows.
- `video.py` invokes the packaged video renderer.

## Data Flow

### Detect-range flow

1. Parse Quran text with `core.quran_parser.parse_ayat`.
2. Load a saved transcript, or transcribe (local model by default, or WhisperX).
3. Normalize transcript words with `io.readers.extract_matching_words`.
4. Run either:
   - `core.range_matching.detect_first_ayah` / `detect_last_ayah`
   - `core.lecture_matching.detect_quran_mentions_in_lecture`
5. Write JSON output with `io.writers.write_json`.
6. Optionally render a video with the video pipeline.

### Legacy word-align flow

1. Load Quran text.
2. Load a saved transcript, or transcribe (local model by default, or WhisperX).
3. Normalize aligned words.
4. Fuzzy-match against canonical Quran words.
5. Write JSON and SRT output.

## Developer Tooling

- `tools/export_local_model/` exports and packages the local speech model for release; see its `README.md`.
- `packaging/` builds the desktop app; `packaging/ci/` holds the release workflow's steps. The release gate runs the built app's `--doctor --release`, then checks the published speech model against the pin in `model_store.py` and transcribes a tone locally inside the built app; see [the transcription gate](../packaging/ci/README.md#the-transcription-gate).

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

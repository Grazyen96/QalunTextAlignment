# QuranText

QuranText helps you take Arabic audio or existing WhisperX transcripts and do four main things:

1. **Transcribe audio** with WhisperX.
2. **Detect a recitation range** by finding the first and last ayah in a recitation.
3. **Detect Quran mentions inside lecture audio** and return timestamped spans.
4. **Render timestamped Quran videos** from lecture or recitation match results.

The project uses a `src/` package layout and keeps the older root scripts as thin compatibility wrappers.

## Python Version

Python 3.10+ is required.

## What QuranText Can Do

Use QuranText when you have one of these starting points:

- **Audio only** and you want Quran matching.
- **A saved WhisperX JSON transcript** and you want matching without retranscribing.
- **A match JSON result** and you want to render a video.

Typical workflows:

- **Recitation audio** → detect the first and last ayah in the recited range.
- **Recitation audio** → detect the range and generate timestamped display spans.
- **Lecture audio** → find places where Quran ayat were mentioned.
- **Lecture or recitation match JSON** → render an MP4 overlay video.

## Installation

Create or activate a Python environment, then install runtime dependencies:

```bash
python3 -m pip install -r requirements.txt
```

For normal development, install the package in editable mode so `python3 -m qurantext ...` works directly:

```bash
python3 -m pip install -e .
```

Install development tooling when you want tests and linting:

```bash
python3 -m pip install pytest ruff
```

## How To Run The CLI

You have **three** common ways to run the project.

### Option 1: installed editable package (recommended)

```bash
python3 -m pip install -e .
python3 -m qurantext --help
```

### Option 2: run from the repo without installing

```bash
PYTHONPATH=src python3 -m qurantext --help
```

### Option 3: use compatibility wrapper scripts

```bash
python3 detect_range.py --help
python3 render_ayat_video.py --help
```

For new usage, prefer:

```bash
python3 -m qurantext ...
```

## Environment

Create a local `.env` or `.env.local` file from `.env.example` and set your Replicate token when using WhisperX transcription:

```env
REPLICATE_API_TOKEN=
```

If you are **only matching from an existing WhisperX JSON file**, you do **not** need the Replicate token.

Common runtime defaults can also be overridden from the environment. Examples:

```env
QURANTEXT_RANGE_HEAD_WORDS=80
QURANTEXT_RANGE_TAIL_WORDS=80
QURANTEXT_RANGE_SEARCH_RANGE=20
QURANTEXT_RANGE_LOW_CONF=0.40
QURANTEXT_LECTURE_MAX_SPAN=5
QURANTEXT_LECTURE_THRESHOLD=0.78
QURANTEXT_VIDEO_RENDERER=ass
QURANTEXT_VIDEO_WIDTH=1920
QURANTEXT_VIDEO_HEIGHT=1080
QURANTEXT_VIDEO_FPS=25
```

## Project Layout

```text
src/qurantext/
  cli/                 Command-line entry points
  config/              Paths, settings, environment loading
  core/                Quran parsing, matching, lecture matching, shared video helpers, and renderer modules
  io/                  JSON/transcript readers and writers
  pipelines/           End-to-end workflows
  services/            External service integrations such as WhisperX
  utils/               Small generic helpers
input/
  quran/
  lectures/
  recitations/
output/
  videos/
  recitation_matching/
  lecture_matching/
  whisperx_transcripts/
  range_matching/
scripts/               Thin convenience wrappers
```

## Inputs

Put inputs under these directories:

```text
input/
  quran/
  lectures/
  recitations/
```

Typical source files:

- Quran text: Qalun-format text files such as `UthmanicQaloon1-Ver05.txt`
- Lecture audio: `input/lectures/*.mp3`, `*.wav`
- Recitation audio: `input/recitations/*.mp3`, `*.wav`
- Existing WhisperX transcripts: JSON files from a prior transcription run

## Outputs

Generated files are written under:

```text
output/
  videos/
  recitation_matching/
  lecture_matching/
  whisperx_transcripts/
  range_matching/
```

## Choose The Right Workflow

### `transcribe`
Use when you only want raw WhisperX JSON.

### `range-match`
Use when you want:

- the detected **first ayah**
- the detected **last ayah**
- confidence and warning metadata

Best for: identifying the Quran range in a recitation.

### `lecture-match`
Use when you want:

- timestamped Quran mentions inside a lecture
- `matches` entries with surah/ayah ranges and times

Best for: extracting quoted ayat from dars/lecture audio.

### `recitation-match`
Use when you want:

- detected range **plus** timestamped ayah spans inside that range
- output suitable for recitation-style video overlays

Best for: continuous recitation clips where you want display timing.

### `generate-video`
Use when you already have a match JSON and want an MP4. Pass `--project` to
render from a project file instead, so any subtitle corrections in it are used.

### `project`
Use when you want to correct the subtitles before rendering.

`project init` turns a match result into a project file that owns the job's
ayah cards and its subtitle cues. Recognition output is converted to cues once,
here; after that the project is the source of truth and rendering never rebuilds
them, so an edit survives. The Quran text itself is not editable through the
project: a card records which ayah and when, and the canonical text is looked up
at render time.

```bash
python3 -m qurantext project init \
  --audio input/lectures/example.mp3 \
  --matches output/lecture_matching/example_lecture.json

# correct the caption text in example.qalun.json, then:
python3 -m qurantext generate-video \
  --project example.qalun.json \
  --matches output/lecture_matching/example_lecture.json \
  --output output/videos/example.mp4
```

### `build-db`
Builds the versioned SQLite store from the certified Qalun text. Lecture
matching builds it on demand; `export-editspec` requires it up front.

### `export-editspec`
Writes the format-neutral edit-spec package for a match result.

### `run-all`
Use when you want one command to:

- transcribe audio
- run matching
- optionally render a video

### `word-align`
Legacy word-level alignment workflow kept for compatibility.

## Main Commands

Show CLI help:

```bash
python3 -m qurantext --help
```

### 1. Transcribe audio with WhisperX

```bash
python3 -m qurantext transcribe \
  --audio input/lectures/example.mp3
```

This writes raw WhisperX JSON to the configured transcripts output directory unless `--output` is provided.

### 2. Detect the first and last ayah in a recitation

From audio:

```bash
python3 -m qurantext range-match \
  --quran input/quran/UthmanicQaloon1-Ver05.txt \
  --audio input/recitations/example.mp3
```

From an existing WhisperX transcript:

```bash
python3 -m qurantext range-match \
  --quran input/quran/UthmanicQaloon1-Ver05.txt \
  --whisperx-json output/whisperx_transcripts/example_whisperx_raw.json
```

Useful optional flags:

```text
--surah            restrict search to one surah
--head-words       words from the start used for first-ayah detection
--tail-words       words from the end used for last-ayah detection
--search-range     candidate ayat scanned near the edges
--low-conf         warning threshold
```

### 3. Detect Quran mentions in lecture audio

From audio:

```bash
python3 -m qurantext lecture-match \
  --quran input/quran/UthmanicQaloon1-Ver05.txt \
  --audio input/lectures/example.mp3
```

From an existing WhisperX transcript:

```bash
python3 -m qurantext lecture-match \
  --quran input/quran/UthmanicQaloon1-Ver05.txt \
  --whisperx-json output/whisperx_transcripts/example_whisperx_raw.json
```

Useful optional flags:

```text
--max-span             maximum consecutive ayat per candidate span
--lecture-threshold    minimum accepted confidence
--min-matched-words    minimum Quran-word overlap
```

### 4. Detect recitation range plus timestamped ayah spans

From audio:

```bash
python3 -m qurantext recitation-match \
  --quran input/quran/UthmanicQaloon1-Ver05.txt \
  --audio input/recitations/example.mp3
```

From an existing WhisperX transcript:

```bash
python3 -m qurantext recitation-match \
  --quran input/quran/UthmanicQaloon1-Ver05.txt \
  --whisperx-json output/whisperx_transcripts/example_whisperx_raw.json
```

This mode first detects the overall recitation range, then emits forward-moving timestamped spans inside that range.

### 5. Render a video from match output

ASS renderer:

```bash
python3 -m qurantext generate-video \
  --audio input/lectures/example.mp3 \
  --matches output/lecture_matching/example_lecture.json \
  --output output/videos/example_ass.mp4 \
  --renderer ass \
  --font-name "Amiri"
```

Frame renderer:

```bash
python3 -m qurantext generate-video \
  --audio input/recitations/example.mp3 \
  --matches output/recitation_matching/example_recitation.json \
  --output output/videos/example_frame.mp4 \
  --renderer frame \
  --font-file fonts/qaloon.10.ttf \
  --width 1920 \
  --height 1080 \
  --fps 25
```

The frame renderer is the direct replacement for older commands such as:

```bash
python3 render_ayat_video.py \
  --audio alFurqan.mp3 \
  --matches recitation_result.json \
  --output test2-recitation-alfurquan-frame.mp4 \
  --renderer frame \
  --font-file fonts/qaloon.10.ttf \
  --width 1920 \
  --height 1080 \
  --fps 25
```

Equivalent package command:

```bash
python3 -m qurantext generate-video \
  --audio alFurqan.mp3 \
  --matches recitation_result.json \
  --output test2-recitation-alfurquan-frame.mp4 \
  --renderer frame \
  --font-file fonts/qaloon.10.ttf \
  --width 1920 \
  --height 1080 \
  --fps 25
```

### 6. Run transcription + matching in one command

```bash
python3 -m qurantext run-all \
  --quran input/quran/UthmanicQaloon1-Ver05.txt \
  --audio input/lectures/example.mp3 \
  --mode lecture
```

With video rendering:

```bash
python3 -m qurantext run-all \
  --quran input/quran/UthmanicQaloon1-Ver05.txt \
  --audio input/lectures/example.mp3 \
  --mode lecture \
  --render-video \
  --font-name "Amiri"
```

### 7. Legacy word-level alignment workflow

```bash
python3 -m qurantext word-align \
  --quran alFurqan.txt \
  --audio alFurqan.mp3
```

## Common Recipes

### Match from a WhisperX transcript you already have

If you already have a WhisperX JSON file, use `--whisperx-json` instead of `--audio`.

Example:

```bash
python3 -m qurantext recitation-match \
  --quran input/quran/UthmanicQaloon1-Ver05.txt \
  --whisperx-json output/whisperx_transcripts/example_whisperx_raw.json
```

### Restrict matching to one surah

```bash
python3 -m qurantext range-match \
  --quran input/quran/UthmanicQaloon1-Ver05.txt \
  --audio input/recitations/example.mp3 \
  --surah "سُورَةُ الفُرقَانِ"
```

### Render a recitation result with the frame renderer

```bash
python3 -m qurantext generate-video \
  --audio alFurqan.mp3 \
  --matches recitation_result.json \
  --output output/videos/alFurqan-frame.mp4 \
  --renderer frame \
  --font-file fonts/qaloon.10.ttf
```

## Backward-Compatible Script Wrappers

These still work and delegate into the packaged implementation:

```bash
python3 detect_range.py --help
python3 render_ayat_video.py --help
python3 scripts/detect_range.py --help
python3 scripts/render_ayat_video.py --help
```

Prefer `python3 -m qurantext ...` for new usage.

## Old To New Command Mapping

```text
python3 detect_range.py ...         -> python3 -m qurantext range-match ...
python3 render_ayat_video.py ...    -> python3 -m qurantext generate-video ...
python3 scripts/detect_range.py ... -> python3 -m qurantext range-match ...
python3 scripts/render_ayat_video.py ... -> python3 -m qurantext generate-video ...
```

## Workflow Notes

- `range-match` returns `first_ayah`, `last_ayah`, warnings, and metadata.
- `lecture-match` returns `matches` for Quran mentions in lecture-style audio.
- `recitation-match` returns the detected range plus forward-moving display spans.
- `generate-video` supports `ass` and `frame` renderers.
- `word-align` is kept only for legacy compatibility.

## Testing And Checks

Run validation commands from the project root:

```bash
python3 -m compileall src
pytest
ruff check .
ruff format --check .
```

If `pytest` or `ruff` are not installed yet, install them first:

```bash
python3 -m pip install pytest ruff
```

## Troubleshooting

- If `python3 -m qurantext ...` fails with `No module named qurantext`, either install the package with `python3 -m pip install -e .` or run with `PYTHONPATH=src`.
- If transcription fails, verify `REPLICATE_API_TOKEN` in `.env`, `.env.local`, or your shell environment.
- If you already have a WhisperX transcript, use `--whisperx-json` instead of `--audio` to skip retranscription.
- If `generate-video --renderer ass` fails, confirm your FFmpeg build has `libass` support and that the font name exists on the system.
- If `generate-video --renderer frame` fails, install `Pillow` and `numpy`, check that FFmpeg is on your PATH, and use a valid `--font-file`.
- If it fails with a libraqm error, your Pillow build cannot shape Arabic. Pillow's wheels need FriBiDi installed separately; install it and reinstall Pillow.
- If matching confidence is low, increase `--head-words`, `--tail-words`, or `--search-range`, and confirm the Quran file matches the recitation riwaya.

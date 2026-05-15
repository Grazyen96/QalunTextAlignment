# `detect_range.py`

`detect_range.py` detects Qur'an content inside a WhisperX transcription and writes the result to JSON.

It is designed for Quran recitation workflows where you already have:

- a **Qalun-riwaya Quran text file**
- either a **WhisperX JSON transcription output** or an **audio file** to transcribe with WhisperX

The script supports two workflows:

- `range` mode: compare the beginning and end of the transcription against the Quran text and return the most likely verse range
- `lecture` mode: scan the whole transcription for Qur'an quotations inside lecture / Dars audio
- `recitation` mode: first detect the recited range, then output timestamped spans from only that surah/range

## What you need

Before running the script, make sure you have:

1. **Python 3.10+**
2. A Quran text file such as `UthmanicQaloon1-Ver05.txt`
3. Exactly one of the following:
   - a WhisperX JSON file exported from your transcription step, or
   - an audio file that you want the script to transcribe itself

If you use `--audio`, you must also set `REPLICATE_API_TOKEN` so the script can call Replicate.

The project now auto-loads variables from `.env` and `.env.local` in the project root, so you do not need to manually `export` the token if it is already stored there.

### Quran text file requirements

The Quran file should be a text file in the style used by this project:

- surah headers like `سُورَةُ الفُرقَانِ`
- verses containing Arabic text
- verse numbers that may appear as Arabic-Indic digits

The script handles:

- UTF-8 and UTF-16 files
- Qur'anic diacritics and reading marks
- Arabic-Indic digits
- basmala lines and ta'awwudh lines, which are skipped automatically

### WhisperX JSON requirements

The WhisperX file must be JSON and should contain transcription data in one of these shapes:

- `{"segments": [...]}`
- a list of segments
- word-level output with `segments[].words[]`
- segment-level fallback output with only `segments[]`

The script normalizes the transcription text before matching it to the Quran text.

## What the script does

1. Parses the Quran text into ordered ayat
2. Loads the WhisperX JSON output
3. Extracts the transcript words
4. Either:
   - detects the **first and last ayah** in recitation-oriented `range` mode, or
   - scans overlapping transcript windows for Qur'an mentions in `lecture` mode, or
   - detects the range and emits 1-5 ayah display spans in `recitation` mode
5. Writes a structured JSON result with confidence scores and metadata

## Usage

Run it from the project root:

```bash
python detect_range.py \
  --quran "UthmanicQaloon1-Ver05.txt" \
  --whisperx "whisperx.json" \
  --output "result.json"
```

Or let the script generate the WhisperX transcription from an audio file:

```bash
python detect_range.py \
  --quran "UthmanicQaloon1-Ver05.txt" \
  --audio "alFurqan.mp3" \
  --output "result.json"
```

You must provide **exactly one** of:

- `--whisperx`
- `--audio`

You cannot use both at the same time.

### Optional arguments

- `--mode` — choose `range`, `lecture`, or `recitation`
- `--surah` — restricts detection to one surah name exactly as it appears in the Quran file
- `--head-words` — number of words from the beginning of the transcription to scan for the first ayah
- `--tail-words` — number of words from the end of the transcription to scan for the last ayah
- `--search-range` — how many candidate ayat to inspect from each end
- `--low-conf` — confidence threshold used for warnings
- `--max-span` — maximum number of consecutive ayat to consider in `lecture` mode
- `--lecture-threshold` — minimum confidence required in `lecture` mode
- `--min-matched-words` — minimum overlapping Qur'an words required in `lecture` mode

Example with a surah filter:

```bash
python detect_range.py \
  --quran "UthmanicQaloon1-Ver05.txt" \
  --whisperx "whisperx.json" \
  --surah "سُورَةُ الفُرقَانِ" \
  --output "result.json"
```

Example for lecture mode:

```bash
python detect_range.py \
  --quran "UthmanicQaloon1-Ver05.txt" \
  --whisperx "whisperx.json" \
  --mode lecture \
  --max-span 5 \
  --lecture-threshold 0.78 \
  --min-matched-words 4 \
  --output "lecture_result.json"
```

`lecture` mode always scans the **full Quran**, even if `--surah` is provided.
The lecture matcher lives in the separate module `lecture_mode.py` to keep the CLI readable.

Example for full recitation mode:

```bash
python detect_range.py \
  --quran "UthmanicQaloon1-Ver05.txt" \
  --whisperx "result_whisperx_raw.json" \
  --mode recitation \
  --max-span 5 \
  --lecture-threshold 0.78 \
  --min-matched-words 4 \
  --output "recitation_result.json"
```

`recitation` mode uses the same first/last ayah range detection as `range` mode.
It then restricts matching to the detected surah/range, so repeated wording from other surahs does not appear in the result. Each displayed match is capped by `--max-span`, so the default output shows at most 5 ayat at a time.

## Output format

### `range` mode

The script writes a JSON file containing:

- `first_ayah`
- `last_ayah`
- `warnings`
- `meta`

Example structure:

```json
{
  "first_ayah": {
    "surah_num": 25,
    "surah_name": "سُورَةُ الفُرقَانِ",
    "ayah_num": 1,
    "text": "تَبَارَكَ الَّذِي نَزَّلَ الْفُرْقَانَ ...",
    "confidence": 0.92
  },
  "last_ayah": {
    "surah_num": 25,
    "surah_name": "سُورَةُ الفُرقَانِ",
    "ayah_num": 77,
    "text": "قُلْ مَا يَعْبَؤُا بِكُمْ رَبِّي ...",
    "confidence": 0.89
  },
  "warnings": [],
  "meta": {
    "input_type": "audio",
    "input_path": "/path/to/alFurqan.mp3",
    "whisperx_raw_output_path": "/path/to/result_whisperx_raw.json",
    "whisperx_model_ref": "victor-upmeet/whisperx:...",
    "whisperx_segments": 48,
    "total_ayat_in_file": 77,
    "whisperx_words": 1234,
    "audio_duration_s": 312.44,
    "global_search": false
  }
}
```

When `--audio` is used, the script automatically saves the raw WhisperX JSON next to your output file using a name like `result_whisperx_raw.json`.

### `lecture` mode

Lecture mode writes a `matches` array. Each match includes both:

- `detected_text` — the transcript fragment detected in the lecture audio
- `text` / `full_text` — the full matched Quran ayah/span text from the Quran source file

The video renderer described below uses `full_text` for on-screen display.

Example structure:

```json
{
  "matches": [
    {
      "surah_num": 1,
      "surah_name": "سُورَةُ الفَاتِحَةِ",
      "from_ayah": 1,
      "to_ayah": 3,
      "detected_text": "بسم الله الرحمن الرحيم الحمد لله رب العالمين الرحمن الرحيم",
      "text": "بِسْمِ اللَّهِ الرَّحْمَـٰنِ الرَّحِيمِ\nٱلْحَمْدُ لِلَّهِ رَبِّ ٱلْعَـٰلَمِينَ\nٱلرَّحْمَـٰنِ ٱلرَّحِيمِ",
      "full_text": "بِسْمِ اللَّهِ الرَّحْمَـٰنِ الرَّحِيمِ\nٱلْحَمْدُ لِلَّهِ رَبِّ ٱلْعَـٰلَمِينَ\nٱلرَّحْمَـٰنِ الرَّحِيمِ",
      "confidence": 0.91,
      "start_time": 183.52,
      "end_time": 197.21
    }
  ],
  "meta": {
    "mode": "lecture"
  }
}
```

### `recitation` mode

Recitation mode writes the same `first_ayah`, `last_ayah`, `warnings`, and `meta`
fields as `range` mode, plus a `matches` array like `lecture` mode. The matches
are limited to the detected recitation range and capped to `--max-span` ayat.

## Render an MP4 video from lecture matches

Use `render_ayat_video.py` to turn a lecture JSON result into:

- an `.mp4` video with a black background
- the original audio track
- burned-in ASS subtitles showing the matched Qur'an ayat
- a saved `.ass` subtitle file next to the output video

### ASS renderer (default)

Example:

```bash
python render_ayat_video.py \
  --audio "الفرقان7-11-final.wav" \
  --matches "test1-7-11.json" \
  --output "test1-7-11.mp4" \
  --font-name "DejaVu Sans" \
  --renderer ass \
  --width 1920 \
  --height 1080
```

### Frame renderer

The frame renderer creates a styled silent video in Python using Pillow + OpenCV,
then muxes the original audio back in with FFmpeg.

```bash
python render_ayat_video.py \
  --audio "الفرقان7-11-final.wav" \
  --matches "test1-7-11.json" \
  --output "test1-7-11-frame.mp4" \
  --renderer frame \
  --font-file "fonts/qaloon.10.ttf" \
  --width 1920 \
  --height 1080 \
  --fps 25
```

The renderer:

- reads the `matches` list from the lecture JSON
- uses each match's `start_time` and `end_time`
- displays the surah label plus the match `full_text`
- writes the ASS file as UTF-8 with BOM for better Arabic compatibility
- validates that the requested font exists before rendering
- prints a clear message if `matches` is empty, then still renders a black video with audio and no subtitle events

Renderer-specific behavior:

- `--renderer ass`
  - requires `--font-name`
  - writes an `.ass` file next to the output video
  - uses FFmpeg `ass=` subtitles on a black background
- `--renderer frame`
  - requires `--font-file`
  - uses Pillow for text drawing and OpenCV for frame writing
  - supports `--debug-detected-text` to show the transcript fragment in a small footer
  - creates a temporary silent MP4, then muxes the original audio with FFmpeg
  - deletes the temp file unless `--keep-temp` is passed

### Video rendering notes

- `--font-name` must be an installed system font family name that FFmpeg/libass can use.
- `--font-file` must point to a readable TTF/OTF/TTC font file when using `--renderer frame`.
- Arabic shaping depends on your local FFmpeg build. For best results, FFmpeg should include `libass`, `fribidi`, `harfbuzz`, and `fontconfig` support.
- The frame renderer requires Pillow, numpy, opencv-python, and Pillow built with `libraqm` support. If `libraqm` is unavailable, frame rendering stops with an explicit error instead of producing incorrect Arabic shaping.
- If a match has invalid or missing timestamps, or `end_time <= start_time`, it is skipped with a warning.
- If `full_text` is missing, the renderer falls back to `full_ayah_text`, then `text`.

### Install Python dependencies for the frame renderer

```bash
pip install -r requirements.txt
```

## When to use `--surah`

Use `--surah` when:

- you are matching a single surah file
- you want faster search
- you want more accurate results in a known surah
- you are using `range` mode

Leave it out when:

- you are using a full-Quran text file
- you want the script to search across all surahs automatically

In `lecture` mode, `--surah` is ignored and the script searches the full Quran.

## Notes and tips

- The script uses **fuzzy matching**, so it does not require exact transcription text.
- It normalizes Arabic text heavily, including removing tashkeel and unifying common letter variants.
- If the transcript begins with ta'awwudh or basmala, those words are skipped during first-ayah detection.
- If the result confidence is low, try increasing `--head-words`, `--tail-words`, or `--search-range`.
- Make sure the Quran file matches the **same riwaya** as the recitation being analyzed.

## Common problems

### No ayat parsed

This usually means one of the following:

- the Quran file path is wrong
- the file encoding is not readable
- the `--surah` name does not match the file exactly

### No word tokens extracted

This means the WhisperX JSON did not contain the expected transcription data, or the file is not valid JSON.

### Replicate token missing

If you use `--audio` and see an error about `REPLICATE_API_TOKEN`, put the token in `.env` or `.env.local` in the project root:

```bash
REPLICATE_API_TOKEN="your_token_here"
```

Or export it manually before running the script:

```bash
export REPLICATE_API_TOKEN="your_token_here"
```

### Wrong first or last ayah

Try:

- using a larger `--search-range`
- increasing `--head-words` or `--tail-words`
- checking that the Quran text file matches the actual recitation riwaya

---

If you want, you can also add a sample WhisperX JSON file and a sample output file in this repository for easier testing.

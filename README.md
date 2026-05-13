# `detect_range.py`

`detect_range.py` detects Qur'an content inside a WhisperX transcription and writes the result to JSON.

It is designed for Quran recitation workflows where you already have:

- a **Qalun-riwaya Quran text file**
- either a **WhisperX JSON transcription output** or an **audio file** to transcribe with WhisperX

The script supports two workflows:

- `range` mode: compare the beginning and end of the transcription against the Quran text and return the most likely verse range
- `lecture` mode: scan the whole transcription for Qur'an quotations inside lecture / Dars audio

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
   - scans overlapping transcript windows for Qur'an mentions in `lecture` mode
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

- `--mode` — choose `range` or `lecture`
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



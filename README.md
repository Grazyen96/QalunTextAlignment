# QuranText

QuranText helps you take Arabic audio or existing WhisperX transcripts and do four main things:

1. **Transcribe audio** on this computer with a local speech model (WhisperX on Replicate is optional).
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

The runtime dependencies are NumPy, Pillow (built with libraqm, for Arabic
shaping), certifi, the Replicate client (only used by the optional WhisperX
engine) and **sherpa-onnx** (Apache 2.0, though its PyPI build also contains
GPL-3.0 code; see [Licence](#licence)), which runs the local speech model.
That model, NVIDIA's FastConformer Hybrid Large (Arabic),
`stt_ar_fastconformer_hybrid_large_pcd_v1.0`, is not installed by pip: Qalun
downloads it once, on first use (about 110 MB). It is licensed CC BY 4.0; the
attribution is in `THIRD_PARTY_NOTICES.md`.

For normal development, install the package in editable mode so `python3 -m qurantext ...` works directly:

```bash
python3 -m pip install -e .
```

Install development tooling when you want tests and linting:

```bash
python3 -m pip install pytest ruff
```

## Just want to use it?

Download the app for your system from the
[Releases page](https://github.com/Grazyen96/QalunTextAlignment/releases),
unzip it, and run **Qalun**. There is nothing to install: no Python, no FFmpeg,
no Quran text file. Everything below is for working on the code.

## System requirements

- **Memory:** transcribing on this computer, the default, uses up to about
  1.8 GB of RAM while it runs, however long the recording (about 1 GB for a
  short clip). On a machine with 4 GB, close other large programs first; a long
  lecture may otherwise run out of memory. WhisperX online, the optional engine,
  transcribes elsewhere and needs none of it.
- **Disk:** the speech model takes about 140 MB once installed. It downloads
  once, on first use (about 110 MB), and needs about 270 MB free while it
  unpacks.
- **Internet:** once, for that first download; after that, transcription works
  offline.

## Is this machine set up?

```bash
python3 -m qurantext doctor
```

Checks Arabic shaping, FFmpeg, the bundled font, the Quran store, the output
folder and transcription (the configured engine, with the other one listed for
information), and tells you what to do about anything that is not ready. The packaged
app answers the same question with `qalun --doctor`, which matters because a
packaged app that will not render is exactly when there is no Python to hand.

## The window

```bash
python3 -m pip install -e '.[gui]'
qalun
```

The window opens on every job it already knows about, listed on the left, with
a form for starting a new one on the right.

**The job list.** Each row is one project: its name, whether it is a
recitation or a lecture, how much of the Quran it covers, and where it stands
— needs review, reviewed, rendered, changed since the last render, or damaged
(with the error on the row, shown on double-click). Double-clicking a row
opens it for review; right-click for "Show in folder" or "Remove from list",
which only hides a job (nothing on disk is touched, so it costs nothing to
undo).

**Starting a job.** Drop an audio file, say whether it is a recitation or a
lecture, pick the surah and the ayat if you know them, choose a video size,
and press Start. For a lecture, the surah is the one it studies: the video's
ayah card shows only that surah, and ayat quoted from other surahs stay in the
subtitles. Leave it on "Detect automatically" and the surah heard the longest
is used; the review window can change it later ("Surah on the cards").
Matching the same recording again keeps a surah chosen earlier unless you pick
another one, as it keeps the video's look. Progress and remaining time show as
it runs, Cancel stops it, and a cancelled job leaves nothing behind. The first
job transcribed on this computer downloads the speech model once (about
110 MB), shown as its own stage. Matching done, the review opens automatically
so corrections happen before anything is rendered.

**The review, in brief.** Play the recording, step word by word, and nudge a
word's start or end at the playhead; Save (Ctrl+S) writes the correction, Undo
and Redo step back and forth through them, and a gap the recording covers but
no word does is flagged so it does not go unnoticed. Render makes the video
once the timing looks right; Export writes the corrected subtitles on their
own. In a lecture, "Show ayah… from here" (beside Play) puts the ayat you pick
on the card from the playhead until the next card — for the ayah a teacher goes
back to and explains without reciting it — and a double-click on a card's Ayah
cell (or "Change ayah…" in its menu) changes which ayat it shows. The text
always comes from the Quran store, and a card placed by hand is marked ✎.

**Episode: intro, recitation and outro.** In a lecture's review, "Episode…"
(beside Render) chooses what plays around the lecture: an intro clip, the video
of one of your recitation jobs, and an outro clip (MP4, MOV, MKV or WebM). The
dialog shows each clip's length and the episode's total. Rendering the lecture
then also writes `<name> – episode.mp4` beside it: the parts joined in order,
each scaled and letterboxed to the lecture's size, so a phone clip filmed
upright keeps black bars rather than being stretched. A recitation that changed
since its last render is rendered first. When the job writes subtitle files,
the episode gets its own, `<name> – episode.srt` and so on, moved to where the
lecture starts in it. The lecture's own video is kept whatever happens to the
episode: a clip gone missing, or a cancel during the joining, is said in the
review and the episode is simply not written. The clips are copied beside the
project (`<name>.qalun.episode/`), so the folder can be moved with them inside;
the recitation is only referenced. The last intro and outro chosen are what new
lectures start with, and the review shows "Episode: on" when any part is set.

**More options**, folded away since most jobs don't need them: a Quran text
other than the certified one that ships with the app, subtitles burned into
the picture, written as files beside it, or both (and in which formats), an
output folder other than the default, where transcription runs (on this
computer, the default, or WhisperX online, which uploads the recording and needs
a Replicate token), and rendering right away instead of stopping for review —
for jobs you already trust. While More options is folded, a WhisperX choice is
still named under it, with a note when no token is set.

**Where files go.** Matching results land in `output/recitation_matching/` or
`output/lecture_matching/`, and a rendered video in `output/videos/`, unless
More options points the job at a folder of its own — then its match, project
and video files all go there together, and that folder is remembered so the
job list keeps finding it.

**Language.** The window is in English or Arabic. It follows the system's
language until you choose one at the bottom of the home window, and remembers
that choice from then on (switching waits until no review is open and no job
is running). Arabic lays the window out right to left. In both languages the
review window's timeline — the waveform and the word strip — runs right to
left, so an ayah's words read in their own order: the recording's start is on
the right, ← steps to the next word and → to the previous, and `,` / `.` nudge
the selected edge left (later) / right (earlier). Times and numbers read left
to right and stay Western digits in both. The Arabic text is a draft awaiting
review by a native speaker.

**Where settings live.** The window's settings (the language, the last choices
on the form, hidden jobs and job output folders) are kept where Qt keeps
settings for an app named Qalun:

| System | Where |
|---|---|
| Linux | `~/.config/Qalun/Qalun.conf` |
| Windows | the registry key `HKEY_CURRENT_USER\Software\Qalun\Qalun` |
| macOS | `~/Library/Preferences/com.qalun.Qalun.plist` |

Deleting it resets the window to how it was on the first run. Nothing on disk
is touched: hidden jobs come back into the list, and jobs written to a folder of
their own drop out of it until a new job uses that folder again.

Qt is an optional dependency, so the command line installs without it. Running
`qalun` without it prints one line telling you what to install.

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

Transcription runs on this computer by default, so no token is needed for it. Only the optional WhisperX engine on Replicate needs one. Create a `.env` or `.env.local` file from `.env.example` and set your Replicate token there:

```env
REPLICATE_API_TOKEN=
```

The `.env` files are read from the checkout root when you run from source, and from the user data folder when you run the packaged app.

You do **not** need the Replicate token for the local engine, or when matching from an existing WhisperX JSON file.

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

## Packaging

`packaging/` builds a self-contained desktop app with PyInstaller. See
[packaging/README.md](packaging/README.md) for the per-platform wrappers and
the two mistakes that are easy to make. Before a build is released, its gate
runs the built app's `--doctor --release` and then a real local transcription
inside it, after checking that the published speech model still matches the
pin; see [the transcription gate](packaging/ci/README.md#the-transcription-gate)
and [docs/release-checklist.md](docs/release-checklist.md).

## Project Layout

```text
src/qurantext/
  cli/                 Command-line entry points
  config/              Paths, settings, environment loading
  core/                Quran parsing, matching, lecture matching, shared video helpers, and renderer modules
  io/                  JSON/transcript readers and writers
  pipelines/           End-to-end workflows
  services/            Transcription engines (local model, WhisperX on Replicate) and the model store
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

The Quran text is not one of them: the certified Qalun text ships with the app,
so `--quran` is optional everywhere and defaults to it. Pass one only to
override.

Typical source files:
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
Use when you only want a raw transcript (WhisperX-shaped JSON).

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

### Subtitles as files, not only burned in

`generate-video` can write the subtitles beside the video instead of, or as well
as, into the picture.

```bash
python3 -m qurantext generate-video \
  --audio input/recitations/example.mp3 \
  --matches output/recitation_matching/example_recitation.json \
  --output output/videos/example.mp4 \
  --subtitles both --subtitle-format srt vtt
```

`burn` puts them in the picture, `sidecar` writes a clean video plus subtitle
files, `both` does what publishing usually wants. Formats are SRT, WebVTT and
ASS.

For a recitation the subtitle track is the canonical ayah text from the store,
one cue per ayah, never the recogniser's version of the Quran. For a lecture it
is the recognised speech, which is the thing you correct.

A recitation's ayah card is the visual, so a clean recitation video is nearly
empty; there the sidecar is an accessibility and platform deliverable rather
than a substitute for the card.

A lecture's ayah card keeps to the surah it studies, which is the surah heard the
longest unless you say otherwise with `--studied-surah N` on `generate-video` or
`preview`. A project's own choice wins: `generate-video` reads it from `--project`,
and `preview` from the project file beside `--matches` (for the surah only; the
preview's cards and look still come from the match file and `--look`). A
recitation ignores the flag. Ayat quoted from other surahs are still in the
subtitles.

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

### `preview`
Use when you want to see how the video will look before rendering it.

```bash
python3 -m qurantext preview \
  --matches output/recitation_matching/example_recitation.json \
  --preset social
```

Draws one frame to a PNG in well under a second, at the moment the first ayah
card is on screen. The window has the same thing on a button.

### `check-timing`
Use when you want to know whether the word timings actually cover the recitation.

Recognition can drop speech outright: on one 97-second clip it reported a
7.5-second gap between two words whose waveform sits two tenths of a decibel from
the level of known recitation either side. The highlight holds on the previous
word through stretches like that. This finds them from the waveform alone, with
no model and no confidence score.

```bash
python3 -m qurantext check-timing \
  --audio input/recitations/example.mp3 \
  --matches output/recitation_matching/example_recitation.json
```

### `build-db`
Builds the versioned SQLite store from the certified Qalun text. Lecture
matching and the range picker build it on demand.

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

### 1. Transcribe audio

```bash
python3 -m qurantext transcribe \
  --audio input/lectures/example.mp3
```

Transcription runs on this computer by default. The first time, Qalun downloads the speech model once (about 110 MB). Its licence is in `THIRD_PARTY_NOTICES.md`.

To use WhisperX on Replicate instead, pass `--engine whisperx` or set `QURANTEXT_TRANSCRIBE_ENGINE=whisperx`. That needs `REPLICATE_API_TOKEN`.

This writes raw transcript JSON to the configured transcripts output directory unless `--output` is provided.

### 2. Detect the first and last ayah in a recitation

From audio:

```bash
python3 -m qurantext range-match \
  --audio input/recitations/example.mp3
```

From an existing WhisperX transcript:

```bash
python3 -m qurantext range-match \
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
  --audio input/lectures/example.mp3
```

From an existing WhisperX transcript:

```bash
python3 -m qurantext lecture-match \
  --whisperx-json output/whisperx_transcripts/example_whisperx_raw.json
```

Useful optional flags:

```text
--max-span             maximum consecutive ayat per candidate span
--lecture-threshold    minimum accepted confidence
--min-matched-words    minimum Quran-word overlap
```

### 4. Time a recitation whose range you already know (fastest)

If you know which surah and ayat were recited, say so. There is then nothing to
detect and the job becomes alignment over known text.

```bash
python3 -m qurantext recitation-match \
  --audio input/recitations/example.mp3 \
  --surah-num 25 --from-ayah 7 --to-ayah 11
```

Measured on a 19-minute recitation of Al-Furqan, against searching for the range:

| | detected | stated |
|---|---|---|
| time | 583 s | 3.7 s |
| ayat covered | 74 / 77 | 77 / 77 |
| words timed | 876 | 902 |
| recitation with no word on it | 59.2 s | 25.5 s |

Faster and better, because the search was never the right question. Use
`python3 -m qurantext surahs --quran ...` to list surah numbers and ayah counts.

### 8. Detect recitation range plus timestamped ayah spans

From audio:

```bash
python3 -m qurantext recitation-match \
  --audio input/recitations/example.mp3
```

From an existing WhisperX transcript:

```bash
python3 -m qurantext recitation-match \
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
  --audio input/lectures/example.mp3 \
  --mode lecture
```

With video rendering:

```bash
python3 -m qurantext run-all \
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
  --whisperx-json output/whisperx_transcripts/example_whisperx_raw.json
```

### Restrict matching to one surah

```bash
python3 -m qurantext range-match \
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
- `generate-video` supports `ass` and `frame` renderers, and can write subtitles as sidecar files.
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
- If transcription with `--engine whisperx` fails, verify `REPLICATE_API_TOKEN` in `.env`, `.env.local`, or your shell environment. The local engine needs no token, only the one-time model download.
- If you already have a WhisperX transcript, use `--whisperx-json` instead of `--audio` to skip retranscription.
- If `generate-video --renderer ass` fails, confirm your FFmpeg build has `libass` support and that the font name exists on the system.
- If `generate-video --renderer frame` fails, install `Pillow` and `numpy`, check that FFmpeg is on your PATH, and use a valid `--font-file`.
- If it fails with a libraqm error, your Pillow build cannot shape Arabic. Pillow's wheels need FriBiDi installed separately; install it and reinstall Pillow.
- If matching confidence is low, increase `--head-words`, `--tail-words`, or `--search-range`, and confirm the Quran file matches the recitation riwaya.

## Licence

Qalun is free software, licensed under the GNU General Public License version 3
only (GPL-3.0-only); the full text is in [LICENSE](LICENSE).

Copyright (C) 2026 Khalil

It comes with ABSOLUTELY NO WARRANTY, to the extent permitted by law. It is
GPL-3.0 because the sherpa-onnx build the app bundles links espeak-ng
(GPL-3.0-or-later) into the app's own process.

The source is inside the download. Every app zip has, at its top, `LICENSE`,
`THIRD_PARTY_NOTICES.md`, `qalun-source.zip` (the complete source of the commit
the app was built from) and `third-party-sources/` (the exact source archives of
the bundled GPL and LGPL components that are not Qalun's own: espeak-ng, and on
Linux the ALSA library). The bundled components, the speech model and their
licences are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The licence does not cover the bundled Quran font (`qaloon.10.ttf`,
`qaloon.10.woff2`) or the Quran text (`UthmanicQaloon1-v10.txt`). They are
third-party works, their provenance and terms to be confirmed by the owner;
see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

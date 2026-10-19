# QuranText

QuranText (the package; the app's window is called **Qalun**) takes Arabic
audio, or an existing WhisperX transcript, and does four main things:

1. **Transcribe audio** on this computer with a local speech model (WhisperX on
   Replicate is optional).
2. **Detect a recitation range** by finding the first and last ayah in a recitation.
3. **Detect Quran mentions inside lecture audio** and return timestamped spans.
4. **Render timestamped Quran videos** from lecture or recitation match results.

It ships as a desktop app (Qalun, built with PySide6) and as a command-line
tool. The project uses a `src/` package layout and keeps the older root scripts
as thin compatibility wrappers.

## Python Version

Python 3.10+ is required.

## What QuranText Can Do

You can start from audio only, from a saved WhisperX JSON transcript (no
retranscribing), or from a match JSON result (to render a video).

**The app (Qalun)**

- Transcribes on this computer with NVIDIA's FastConformer Arabic model, run by
  sherpa-onnx and downloaded once on first use. WhisperX on Replicate is an
  optional choice that uploads the recording; there is no automatic fallback
  between the two.
- Matches a recitation (detected or stated range) or a lecture (the Quran
  ayat quoted in it) against the bundled Quran text: KFGQPC's Qaloon text v10,
  converted by `tools/convert_mushaf_v10.py`. Videos draw it in the bundled
  Qaloon font; the generated intro and outro write their titles in Amiri; the interface falls back to Noto Sans
  Arabic for Arabic letters on a machine with no Arabic font.
- A review window to correct word timing and subtitles, change the ayah cards
  (including cards placed by hand), choose the video's look and set up an episode
  (intro, recitation, lecture, outro) before anything is rendered.
- Renders MP4 videos and writes subtitles as SRT, WebVTT or ASS files.
- Generates an intro and an outro in the lecture's own look, the outro with a
  QR code for a tracked link.
- English and Arabic interface; an error log you can send when something goes
  wrong.

**The command line** does the same matching and rendering without the window:
`transcribe`, `range-match`, `lecture-match`, `recitation-match`,
`generate-video`, `run-all`, plus `project`, `preview`, `check-timing`,
`surahs`, `build-db`, `doctor` and the legacy `word-align`.

Typical workflows:

- **Recitation audio** → detect the first and last ayah, or give the range and
  time the ayat inside it.
- **Lecture audio** → find the places where Quran ayat were mentioned.
- **Lecture or recitation match JSON** → render an MP4 overlay video.

## Installation

Create or activate a Python environment, then install runtime dependencies:

```bash
python3 -m pip install -r requirements.txt
```

The runtime dependencies are NumPy, Pillow (built with libraqm, for Arabic
shaping), certifi, segno (the generated outro's QR code), the Replicate client
(only used by the optional WhisperX engine) and **sherpa-onnx** (Apache 2.0, though its PyPI build also contains
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
a form for starting a new one on the right. A header runs across the top: the
app's icon and name, then a sun/moon button that switches the theme, the
**Settings** gear and **Help**, which opens this README.

**The job list.** Each job is a card: a small picture of its first card at the
job's own look, its name (shortened in the middle when it is long; the whole
name shows on hover), a chip saying where it stands — needs review, reviewed,
rendered, changed since the last render, or damaged (with the error shown on
double-click) — whether it is a recitation or a lecture with how much of the
Quran it covers, and the day it was last saved. Double-clicking a card opens it
for review; Open, Show in folder and Remove from list sit under the list (and
in the right-click menu). Remove from list only hides a job: nothing on disk is
touched, so it costs nothing to undo. The list follows its folders, so a job
that appears, goes or is renamed shows without pressing Refresh. Before there
is any job, the list says who the app is for and offers a card for each kind
of job, recitation or lecture; choosing one sets the form to it.

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

**The review window.** Matching done, the review opens automatically so
corrections happen before anything is rendered.

- *Timing.* Play the recording, step word by word, and nudge a word's start or
  end at the playhead. Save (Ctrl+S) writes the correction, Undo and Redo step
  back and forth through them, and a gap the recording covers but no word does
  is flagged so it does not go unnoticed. The timeline (the waveform and the
  word strip) always runs right to left, in both interface languages, so an
  ayah's words read in their own order: the recording's start is on the right,
  ← steps to the next word and → to the previous, and `,` / `.` nudge the
  selected edge left (later) / right (earlier). Times and numbers stay Western
  digits, left to right. A time ruler with labels sits above the waveform
  (click or drag it to seek), and the transport row has previous/next word,
  Play, a one-click speed (1x, 0.75x, 0.5x) and the nudges. A card under the
  toolbar, above both columns, says when something needs attention (a missing
  recording, a finished render with its Play and Show in folder buttons). `?`
  opens a sheet of every shortcut, and a double-click on the preview (or the
  full-size button under it) opens the frame at full size.
- *Surah on the cards.* In a lecture the card shows one surah, the one it
  studies ("Surah on the cards", automatic by default). Ayat quoted from other
  surahs stay in the subtitles.
- *Cards by hand.* "Show ayah… from here" (beside Play) puts the ayat you pick
  on the card from the playhead until the next card, for the ayah a teacher
  goes back to and explains without reciting it. A double-click on a card's Ayah
  cell (or "Change ayah…" in its menu) changes which ayat it shows. The text
  always comes from the Quran store, and a card placed by hand is marked ✎.
- *Look.* See below.
- *Render and Export.* Render makes the video once the timing looks right;
  Export writes the corrected subtitles on their own.
- *Episode.* See below.

**Look: palettes and backgrounds.** The Look panel beside the frame preview
redraws the preview with every change, and the export looks like the preview.
Pick one of six palettes: Night gold (the default, and the look of a project
that never chose one), Emerald, Sand, Ink on paper (a light card with dark
text), Ocean and Rose. "Customise" opens pickers for the individual colours
(text, highlighted word, titles, the card and its opacity, the captions and the
background colour); a warning shows when a text colour is hard to read against
the card, and never blocks. The background covers the whole frame, with the card
on top: a solid colour, a gradient, one of three patterns (Stars, Lattice,
Arches) or your own image, which can be dimmed and blurred to keep the text
readable. A look is saved per video; "Use for new videos" makes the current one
the default for jobs started afterwards. From the command line, `--look` on
`generate-video` and `preview` takes the palette's name (`night_gold`, ...). The
separate ASS renderer keeps its own white-text style.

**Episode: intro, recitation and outro.** In a lecture's review, "Episode…"
(beside Render) chooses what plays around the lecture: an intro clip, the video
of one of your recitation jobs, and an outro clip (MP4, MOV, MKV or WebM). The
dialog lays the four parts out as cards in the order they play (intro,
recitation, lecture, outro), each with a picture of it and its length, and the
episode's total under them; a generated intro or outro, once its card is
selected, shows its fields and preview under the strip. Rendering the lecture
then also writes `<name> – episode.mp4` beside it: the parts joined in order,
each scaled and letterboxed to the lecture's size, so a phone clip filmed
upright keeps black bars rather than being stretched. A recitation that changed
since its last render is rendered first. When the job writes subtitle files,
the episode gets its own, `<name> – episode.srt` and so on, moved to where the
lecture starts in it. The lecture's own video is kept whatever happens to the
episode: a clip gone missing, or a cancel during the joining, is said in the
review and the episode is simply not written. The clips are copied beside the
project (`<name>.qalun.episode/`), so the folder can be moved with them inside;
the recitation is only referenced. What you change in the dialog also becomes the default for
new lectures (see below). The review shows "Episode: on" when any part is set. Clips copied beside
a project stay there after an Undo or a Remove (Redo needs them back); delete
the `.qalun.episode` folder's unused files by hand if it grows.

### Generated intro and outro

In the Episode dialog the intro and the outro are each **None**, **My clip** or
**Generated**. A generated part is drawn by Qalun in the lecture's own look, at
its size, while the episode is made, and kept beside the project
(`generated-intro-<hash>.mp4`) until something it is made from changes.

- **The intro** shows a name you type (your channel or the speaker) above the
  lecture's surah and ayat, read from its cards: «سورة الفرقان، الآيات ٤٤–٤٩».
- **The outro** shows a closing phrase (one of three, or your own) and, when
  you give a link, a QR code with the address written under it.
- Each has a style (Fade, Rise or Reveal), a length of 3 to 10 seconds and a
  still preview, its middle frame.

**The tracked link.** Every link put in front of viewers has to be measurable,
so the QR code does not open your link as you typed it: it opens it with UTM
parameters added — `utm_source` the platform you publish on ("Publishing on":
YouTube, Instagram, Facebook, TikTok, Telegram or WhatsApp), `utm_medium=video`,
`utm_content=outro-qr`, and `utm_campaign` naming the lecture
(`qalun-025-044-049`: surah and ayat) unless your link already has a campaign of
its own. Your link's other parameters and its `#fragment` are kept. The dialog
shows this tracked link as it changes. **Copy** gives the same link for the
video's description, with `utm_content=description` instead, so description
clicks and QR scans are counted apart in your analytics. The campaign follows
the lecture's cards, so copy the link once they are final. Change the platform
for the next upload and render again: the outro is made again with the new
source.

**Why the written address has no tracking.** Under the code Qalun writes the
plain address, `example.org/dars`, without the scheme or any parameter: short
enough for a viewer to read and type. Visits typed from it arrive without UTM
parameters and show as direct traffic in your analytics, apart from the QR
code's and the description's visits.

The dialog refuses what is not a web link (only `http` and `https`, a real host
name, no user name or password) and says why; leave the link empty for an outro
without a QR code. It refuses a generated part with nothing to show, too. It
warns when a link is too long for a QR code phones can read at the size the
next render makes (the job's preset), when the name, the phrase or the written
address has letters the title font (Amiri) cannot draw, and when the address
could pass for another site (a Cyrillic letter among Latin ones, say).

New lectures start with the intro and outro you last chose. Only what you change
in the dialog becomes the default, field by field: re-exporting an old lecture
for another platform changes the default platform, not the default link. A part
you set to None or My clip keeps its generated settings for the next time it is
Generated.

**More options**, folded away under the form since most jobs don't need them,
holds only the job's own extras: subtitles burned into the picture, written as
files beside it, or both (and, for files, in which formats), and rendering
right away instead of stopping for review — for jobs you already trust.

**Settings** (the gear in the header) holds everything that is about this
computer or every job, in five tabs:

- *General:* the window's language and theme.
- *Transcription:* where transcription runs — on this computer (the default) or
  WhisperX online, which uploads the recording and needs a Replicate token (the
  tab says when none is set). While WhisperX is chosen, the form says so above
  Start, with a link back to this tab.
- *Files:* a Quran text other than the certified one that ships with the app,
  an output folder other than the default, and the extra folders the job list
  reads.
- *Videos:* the look new jobs start with, and the intro and outro new lectures
  start with.
- *About:* the version, "Open log folder", the third-party notices and the
  project's page on GitHub.

**Where files go.** Matching results land in `output/recitation_matching/` or
`output/lecture_matching/`, and a rendered video in `output/videos/`, unless
Settings → Files names an output folder of its own — then each job's match,
project and video files all go there together, and that folder is remembered
so the job list keeps finding it.

**Language.** The window is in English or Arabic. It follows the system's
language until you choose one in Settings → General, and remembers that choice
from then on (switching waits until no review is open and no job is running).
Arabic lays the window out right to left; the review timeline runs right to
left in both languages (see above). The Arabic text is a draft awaiting review
by a native speaker.

The window follows the desktop's light or dark scheme until you choose one in
Settings → General; the sun/moon button in the header switches between the two.
More options on the home form and Customise in the review's Look panel open and
close in a short motion; turn off **Animate panels** in Settings → General and
they open at once.

**Where settings live.** The window's settings (the language, the theme, the
last choices on the form, hidden jobs and job output folders) are kept where Qt keeps
settings for an app named Qalun:

| System | Where |
|---|---|
| Linux | `~/.config/Qalun/Qalun.conf` |
| Windows | the registry key `HKEY_CURRENT_USER\Software\Qalun\Qalun` |
| macOS | `~/Library/Preferences/com.qalun.Qalun.plist` |

Deleting it resets the window to how it was on the first run. Nothing on disk
is touched: hidden jobs come back into the list, and jobs written to a folder of
their own drop out of it until a new job uses that folder again.

**The log file.** Errors the window would otherwise hide are written to
`qalun.log` in the `logs` folder of the app's data folder (on Linux
`~/.local/share/qalun/logs/`; `%LOCALAPPDATA%\Qalun\logs` on Windows,
`~/Library/Application Support/Qalun/logs` on macOS). It keeps 1 MB and three
older copies, and only warnings and worse. "Open log folder" in Settings →
About opens it (and says so there when it cannot), and `qurantext doctor` (or
`qalun --doctor`) prints the log's path. It is the file to send when something goes wrong.

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
  jobs/                Job catalogue, episode and generated intro/outro steps, export
  gui/                 The Qalun window (home and review)
  data/                The SQLite Quran store
  assets/              Bundled Quran text (KFGQPC Qaloon v10) and fonts (Qaloon, Amiri, Noto Sans Arabic)
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

### 5. Detect recitation range plus timestamped ayah spans

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

### 6. Render a video from match output

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
  --font-file src/qurantext/assets/fonts/qaloon.10.ttf \
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
  --font-file src/qurantext/assets/fonts/qaloon.10.ttf \
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
  --font-file src/qurantext/assets/fonts/qaloon.10.ttf \
  --width 1920 \
  --height 1080 \
  --fps 25
```

### 7. Run transcription + matching in one command

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

### 8. Legacy word-level alignment workflow

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
  --font-file src/qurantext/assets/fonts/qaloon.10.ttf
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

The licence does not cover the bundled Quran font (`qaloon.10.ttf`) or the
Quran text (`UthmanicQaloon1-v10.txt`). They are
third-party works, their provenance and terms to be confirmed by the owner;
see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Nor does it cover the
bundled Amiri font (`Amiri-Regular.ttf`, `Amiri-Bold.ttf`), which the generated
intro and outro write their titles in, or the bundled Noto Sans Arabic
(`NotoSansArabic-Regular.ttf`, `NotoSansArabic-Bold.ttf`), the window's own
fallback for Arabic letters: both are under the SIL Open Font License 1.1, whose
text ships beside each.

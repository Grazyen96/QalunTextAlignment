# Local transcription engine — design

**Date:** 9 October 2026
**Status:** approved in conversation, awaiting spec review

## Why

Every transcript today comes from WhisperX on Replicate: the audio is uploaded,
each run is billed, it needs the network, and it needs a Replicate token that
most people who install Qalun will never have. The ASR bake-off
(`docs/findings/asr-bakeoff.md`) found a local model that is at least as good on
all 17 Al-Furqān recordings: NVIDIA's FastConformer Arabic
(`nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0`, RNNT decoder).

- **Full-surah recitations:** 99.3% of the canonical words recognised, against
  WhisperX's 97.1–97.4%. Same detected range and same cards.
- **Lectures:** 55 of 72 studied ayat found, against WhisperX's 51.
- **Word onsets:** a median of about 55 ms from WhisperX's.
- **Speed:** 40–50× real time on the laptop CPU.

The bake-off ran it through NeMo and PyTorch, a 2.2 GB stack that cannot
reasonably ship inside the PyInstaller bundle on three platforms. This design
runs the same model through sherpa-onnx instead.

## Decisions (settled)

| Question | Decision |
|---|---|
| Where it must work | The packaged app on Windows, macOS and Linux, and the CLI |
| Runtime | sherpa-onnx running an ONNX export of the model. Not NeMo/PyTorch (too big to bundle), and not our own onnxruntime decoder (we would own the feature extraction and RNNT loop, the parts most likely to drift silently) |
| Decoder | RNNT. The model's CTC head times words worse (median 278–345 ms off WhisperX, against about 55 ms) |
| How the model arrives | Downloaded once, on first use, then fully offline. Not bundled in the installer |
| Where it is hosted | A release asset in a new **public** repo, `Grazyen96/qalun-models`. The app repo `Grazyen96/QalunTextAlignment` is private, so its release assets need a login |
| Default engine | Local. WhisperX on Replicate stays available as a choice |
| Choosing | A visible "Transcription" choice in the home window, plus `--engine` on the CLI and `QURANTEXT_TRANSCRIBE_ENGINE` in the environment |
| Fallback | None. If the local engine fails, the job stops with a message naming the fix. Audio is uploaded only when the person chose WhisperX |
| Hardware | CPU only |
| Output | Exactly the WhisperX raw JSON shape the pipeline reads today. Matching, review, rendering and existing projects are unchanged |

## Out of scope

- Optimising the matcher. That is the next, separate design: the bake-off
  measured about 16 minutes of `recitation-match` per full-surah recitation.
- GPU inference, other models, and choosing between several local models.
- Resuming an interrupted model download.
- Removing WhisperX or Replicate.
- Renaming the WhisperX format: `--whisperx-json`, `*_whisperx_raw.json` and
  `io/readers.py` keep their names, because they name the JSON format, not the
  service.
- Usage telemetry. The app keeps sending nothing. GitHub counts downloads per
  release asset, which measures model installs without any code in the app.

## 0. Phase-0 parity gate (before any product code)

The risk in this design is whether sherpa-onnx reproduces NeMo's words and
times for this model. It is settled first, with the bake-off harness, before
anything is built on it.

1. `tools/export_local_model/export.py` runs in a NeMo environment and is not
   part of the package. It exports the model to sherpa-onnx's transducer files
   (`encoder.onnx`, `decoder.onnx`, `joiner.onnx` and `tokens.txt`), with the
   metadata sherpa-onnx reads. It writes both fp32 and int8 versions.
2. A `prototypes/asr_bakeoff/run_sherpa.py` runner produces the WhisperX raw
   shape, using the same pause-cut windows and the word-grouping rule from §3.
3. `score.py` scores both exports on all 17 clips. The gate is passed when a
   version meets every check below, measured against the bake-off's NeMo RNNT
   results:

| Check | Pass if |
|---|---|
| Full recitations (`alFurqan`, `furqanTra`): recall | at least 883 of 893 canonical words each (NeMo: 887) |
| All four recitation clips: detected range identical to NeMo, ayat covered by cards at least NeMo's minus one | identical range; coverage ≥ NeMo − 1 |
| Lectures: studied ayat found | at least 54 of 72 (NeMo: 55) |
| Word starts against NeMo, over all recitation words | every clip's median ≤ 20 ms, and at least 95% of all recitation words within 100 ms |
| Word ends | no end is before its start, and no word overlaps the next. An RNNT decoder can emit two words on the same frame, so "equal" must be allowed |

Amended 10 October 2026 after the first run: identical card splits and a per-clip onset rate measured mostly the matcher's boundary noise and a known NeMo error at the end of 25:11, plus one int8 word merge in 25:10 (see the bake-off finding).

int8 ships if it passes. Otherwise fp32 ships, and the download size in §2
changes from about 120 MB to about 450 MB. If neither passes, work stops and
the runtime decision is reopened. The result is recorded in the bake-off
finding.

## 1. Engine seam — `services/transcription.py`

`transcribe_audio()` stays the only function the pipelines call. Its existing
arguments and behaviour are unchanged, and it gains three keyword arguments:

```python
def transcribe_audio(
    audio_path, *, save_raw_to=None, model_ref=None, use_cache=True,
    engine: str | None = None,              # "local" | "whisperx"; None reads the setting
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> TranscriptionResult
```

- **Engine choice:** it resolves the engine, checks the cache, calls the engine,
  stores the result in the cache, and saves `save_raw_to`. Those are the same
  responsibilities it has today.
- **Code moved out:** the Replicate code moves unchanged into
  `services/engine_whisperx.py`, including its prediction create/poll and its
  401/404 and token messages.
- **Result type:** `WhisperXResult` becomes `TranscriptionResult`, keeping the
  old name as an alias. It gains an `engine` field. `model_ref` holds the
  WhisperX model reference, or the local model's id and version (e.g.
  `nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0@int8-1`), so a match
  file's `meta` always says what produced its transcript.
- **Errors:** a new `TranscriptionError(RuntimeError)` base class.
  `WhisperXServiceError`, `ModelDownloadError` and `LocalEngineError` subclass
  it. Existing `except WhisperXServiceError` clauses keep catching what they
  catch today, apart from a failure to save the raw output, which is now a
  plain `TranscriptionError` (it has nothing to do with the service). The CLI
  and GUI catch `TranscriptionError`.
- **Cache key:** the WhisperX key is left byte-for-byte as it is today, so
  existing cached transcripts still hit. The local key is
  `{"engine": "local", "model": <id@version>, "manifest": <manifest sha256>}`.
  A new model version therefore transcribes again, rather than returning an old
  model's output.
- **Progress:** the three call sites (`cli/main.py`, `pipelines/detection.py`
  and `pipelines/recitation.py`) pass the `progress` and `cancel` they already
  have. Their "Transcribing audio with WhisperX" lines name the engine actually
  used.

Settings gain a `TranscriptionSettings(engine: str)` (default `"local"`,
validated to `local` or `whisperx`). `WhisperXSettings` is unchanged.

## 2. Model store — `services/model_store.py`

It finds the local model, or downloads it.

- **Pinned in code:** a `ModelManifest` constant gives the model id and
  version, the URL, size and SHA-256 of the one release asset (a `.tar.bz2`),
  and the name, size and SHA-256 of each file inside it. Nothing unpinned is
  ever fetched. Publishing a new model is a code change.
- **Location:** `user_cache_dir()/models/<id>-<version>/`. It is derived data:
  deleting it costs one download.
- **`ensure_model(progress, cancel) -> Path`** returns the folder when every
  file in it is present with the pinned size. If not, it:
  1. checks free disk space for the archive plus its unpacked size, with a 10%
     margin;
  2. downloads into a `.part` file, reporting bytes and ETA and checking
     `cancel` between blocks;
  3. verifies the archive's SHA-256;
  4. unpacks it into a temporary folder beside the target;
  5. checks each file's SHA-256;
  6. renames the folder into place, then deletes the archive.

  A half-written model folder is therefore never visible.
- **Load failure:** if the engine cannot load the model, the store re-verifies
  the per-file checksums. On a mismatch it deletes the folder and downloads once more,
  then gives up with `LocalEngineError`.
- **Concurrency:** an in-process lock serialises `ensure_model`, so a second
  job waits for the first job's download instead of starting its own. A stale
  `.part` file or half-unpacked folder left by a crash is deleted when a later
  download starts, once it is more than an hour old (so a download still running
  in another process is never touched).
- **HTTP:** standard library only (`urllib.request`), with a 30 s connect
  timeout. A network failure becomes `ModelDownloadError`, worded for someone
  who is offline.

## 3. Local engine — `services/engine_local.py`

```
audio ──ffmpeg (bundled)──► 16 kHz mono float32, decoded incrementally
      ──► pause-cut windows (≤ 28 s; each cut at the quietest 100 ms of the window's last 10 s)
      ──► sherpa-onnx OfflineRecognizer (transducer, greedy), one stream per window, batched
      ──► tokens + token start times, offset by the window's start
      ──► words ──► {"segments": [...]} in the WhisperX raw shape
```

- **Memory:** audio is read from FFmpeg's pipe in blocks and cut into windows
  as it arrives, never decoded whole. An 80-minute lecture would otherwise be
  more than 300 MB of float32 on a machine that is often near its memory limit.
- **Tokens to words:** a token that begins with the word marker (`▁`, which
  sherpa-onnx's Python API renders as a leading space) starts a new word, and
  the following tokens join it. A bare space token also starts the next word.
  Special tokens such as `<unk>` and `<blk>` are not speech and are skipped.
  - A word's **start** is its first token's time.
  - Its **end** is the next word's start, capped at its last token's time plus
    0.5 s. The last word of a window ends at the window's end or that cap,
    whichever is earlier.
  - Phase 0 measured this rule's ends on the raw recitation transcripts. The
    int8 ends sit a median 320 ms after NeMo's own ends (7% within 100 ms), and
    its card `end_time` is 0.42 s later on every card. Against WhisperX, which
    users get today, the median difference is 125 ms (73% within 250 ms); NeMo's
    own ends differ from WhisperX's by a median 208 ms. The renderer switches on
    word starts, so this is not user-visible.
  - Pure punctuation tokens attach to the word before them. The model's
    diacritics stay in the word text, because the matcher normalises them.
- **One segment per window:** `start`, `end`, `text` and `words`, where each
  word is `{"word", "start", "end", "score": 1.0}`. A constant score is honest:
  the bake-off found word confidence does not mark errors, and nothing
  downstream relies on it.
- **Threads:** the recogniser uses `max(1, os.cpu_count() - 2)` threads. It is
  created once per job and dropped afterwards. It recognises four windows per
  batch, and its working set peaks at about 1.8 GB of RAM and plateaus there
  (measured: 0.9 GB on a 97 s clip, 1.7 GB on a 12-minute lecture, 1.8 GB on
  82 minutes). The batch size is fixed, not a tuning knob: each window is padded
  to its batch's longest, so another batch size changes transcripts (one window
  per batch peaked at 0.7 GB but changed 66 of 982 words and ran 2.3x slower).
  Four is what the parity gate approved; changing it needs the gate run again.
  The doctor (Task 4.3) and the README (Task 4.4) state the 1.8 GB figure.
- **Progress and cancel:** progress is reported as minutes transcribed out of the
  recording's length (read with the bundled ffprobe; the number of windows is
  not known in advance while decoding streams). Cancel is checked between
  blocks.
- **Testability:** the recogniser is created by a factory the tests can
  replace, so all grouping and offset logic is tested without the model.

## 4. Home window, doctor and licences

**Home window** (`gui/home/new_job.py`, `gui/prefs.py`):
- A "Transcription" row with two choices: **On this computer** (default) and
  **WhisperX online (needs a Replicate token)**.
- It is remembered as `Prefs.engine` and passed through `gui/jobs.py` to the
  pipeline.
- When WhisperX is chosen and no token is set, a note under the row says so,
  with where to put the token, before Start. Start stays enabled, because a
  token can be added outside the app and settings are read at startup.
- First-run download progress appears in the job's existing progress line, as
  a stage: "Downloading the speech model, once (about 110 MB)".
- Both languages: new `i18n` keys in English and Arabic.

**Doctor** (`config/preflight.py`, `_transcription()`):
- Local engine: **blocking** if `sherpa_onnx` cannot be imported, or its native
  library cannot load. **Informational** if the model is not downloaded yet
  ("downloads about 110 MB on first use"). Fine if it is present and its sizes
  match.
- WhisperX: both engines are always listed, the configured one first. When
  WhisperX is not the configured engine, its token is information only (a
  missing token is never a problem). Under `--release` (the build gate) the
  Replicate client's import is blocking whatever the engine, because the window
  offers WhisperX (Phase 4 ruling).
- Both lines state the local engine's peak memory (about 1.8 GB), as
  information.

**Licences:**
- The app has no About or licences screen today, and this design does not add
  one.
- The model is CC-BY-4.0, which requires attribution. That is met in three
  places:
  1. a new `THIRD_PARTY_NOTICES.md` at the repository root, bundled beside the
     executable by `qalun.spec`, carrying the NVIDIA attribution, the
     CC-BY-4.0 licence's URI (which CC BY 4.0 §3(a)(1)(C) accepts in place of
     the text) and its "as is" disclaimer, plus sherpa-onnx (Apache 2.0);
  2. the doctor report's transcription line, which names the model and its
     licence;
  3. the same notice in the `qalun-models` release, next to the model files.
- The README lists sherpa-onnx and the model under its dependencies.

## 5. Packaging and release

- **Dependencies:** `sherpa-onnx` joins the core dependencies in
  `pyproject.toml`, pinned exactly (`==1.13.8`) to the version phase 0 was
  tested with: the third-party notices and the shipped third-party sources
  describe that very build, and a test fails if the installed version differs.
  `replicate` stays.
- **Bundle:** `packaging/qalun.spec` collects sherpa-onnx's native libraries
  and its onnxruntime. The bundle should grow by about 30–50 MB per platform,
  and the model is not bundled.
- **Release gate** (`release.yml`, `qalun --doctor --release`) gains:
  1. sherpa-onnx loads inside the frozen app, on all three platforms;
  2. a real transcription of a short test clip, which downloads the model from
     `qalun-models`. A broken URL, checksum or export then fails the release,
     not a user's first job.
- **Publishing the model** is a manual, outward-facing step. The person
  releasing creates the public `qalun-models` repo and uploads the export and
  its licence text as release `model-v1`. The manifest's SHA-256 values are
  then pinned in `model_store.py`.
- **Docs:** `docs/architecture.md`, the README and
  `docs/release-checklist.md` describe both engines, the model download, and
  the new release step.
- **Licence** (decided 10 Oct 2026, after the Phase 5 review found espeak-ng,
  GPL-3.0-or-later, linked into the PyPI sherpa-onnx): Qalun is licensed
  GPL-3.0-only. Amended in the final fix wave (user decision, the repository
  stays private): every app zip carries, beside the app, `qalun-source.zip`
  (`git archive` of the commit built) and `third-party-sources/`, the exact
  source archives of the bundled GPL/LGPL components that are not Qalun's
  (espeak-ng at the fork commit sherpa-onnx 1.13.8 builds; alsa-lib 1.2.12 in
  the Linux zip), each pinned by URL and sha256 in
  `packaging/third-party-sources.txt`, the build failing on a mismatch.

## 6. Testing

No unit test downloads the real model or needs sherpa-onnx's native library.

| Area | Tests |
|---|---|
| Engine seam | engine resolution (argument, env, default); the WhisperX cache key is unchanged from today; the local cache key changes with the model version; old `except WhisperXServiceError` still catches; `TranscriptionResult` and its alias; progress and cancel reach the engine |
| Local engine (fake recogniser) | tokens to words, including the `▁` marker, punctuation and diacritics; word end rule and cap; window offsets; empty windows; the output passes through `io/readers.py` and `recitation-match` unchanged; cancel between batches |
| Pause cutter | windows never exceed 28 s; cuts land on the quietest frame; clips shorter than a window; silence-only audio |
| Model store (local throwaway HTTP server) | download and verify; checksum mismatch deletes the file; cancel mid-download; not enough disk space; atomic rename; stale `.part` cleanup; two concurrent callers download once; re-download after a corrupt load |
| GUI | `Prefs.engine` round-trip; the row's default; the no-token note; both languages |
| Doctor | each engine × state, blocking or informational |
| Opt-in slow test (`QURANTEXT_SLOW_TESTS=1`) | the real model on `furquanTra7-11`: range 25:7–11 and at least 60 of 67 words |

## 7. Order of work

As preferred: no per-task reviews. One whole-branch review and fix pass at the
end of each phase, then a local merge.

0. **Parity gate** (§0). It stops here if it fails.
1. **Engine seam** (§1). The Replicate code moves; the neutral result type and
   errors, the setting and `--engine` are added. WhisperX stays the default
   during this phase, so behaviour does not change.
2. **Model store and export tool** (§2, §0's export script). This includes
   publishing `qalun-models`, after asking first.
3. **Local engine** (§3), and the default switches to `local`.
4. **Home window, doctor and licences** (§4).
5. **Packaging and release gate** (§5), on all three platforms.

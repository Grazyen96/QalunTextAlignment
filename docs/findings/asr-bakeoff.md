# ASR bake-off: WhisperX vs NVIDIA FastConformer vs Cohere Transcribe Arabic

**Date:** 8 October 2026
**Question:** is there a local Arabic recogniser that does at least as well as the
cloud WhisperX the pipeline uses today?

**Update, 9 October 2026:** extended to all 17 Al-Furqān recordings (two
full-surah recitations and thirteen lectures). NVIDIA held up: it is equal or
better on every clip. See "Extended test" below.

**Decision: NVIDIA's FastConformer Arabic (RNNT decoder) is the candidate to
replace cloud WhisperX. On our audio it matches WhisperX on recognition, range
detection and lecture mentions, its word onsets agree with WhisperX to a median
of about 50 ms, and it runs on the laptop CPU at 40–50× real time. Cohere
Transcribe Arabic hears recitation more faithfully when it works, but on
recitation its decoder falls into hallucination loops that cost the range its
last two ayat. It is not usable as it stands.**

A second result settles the question the
[forced-alignment finding](forced-alignment-prototype.md) left open: the
five-second disagreement in 25:7 is a **repeated phrase**, and each system
timed a different copy of it.

## What was compared

| Engine | Where it runs | Word timings from |
|---|---|---|
| WhisperX (`victor-upmeet/whisperx` on Replicate), the current pipeline | cloud GPU | WhisperX's wav2vec2 alignment |
| `nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0`, 115M, CC-BY-4.0, RNNT and CTC decoders | local CPU | the model itself |
| `CohereLabs/cohere-transcribe-arabic-07-2026`, 2B, Apache 2.0, gated | local CPU | `jonatasgrosman/wav2vec2-large-xlsr-53-arabic`, the aligner WhisperX uses for Arabic |

Every engine wrote the WhisperX raw JSON shape. Each transcript then went through
the production `qurantext recitation-match` / `lecture-match` code unchanged, so
the scores are what the app would actually get. The code is in
[prototypes/asr_bakeoff/](../../prototypes/asr_bakeoff/).

| Clip | Length | Content |
|---|---|---|
| `input/recitations/furquanTra7-11.mp3` | 97 s | recitation, Al-Furqān 7–11 |
| `input/recitations/alFurqanCut.mp3` | 292 s | recitation, Al-Furqān 23–44 |
| `input/lectures/الفرقان7-11-final.wav` | 782 s | dars on Al-Furqān 7–11, ayat quoted inside commentary |

**Recall** counts how many words of the true ayah range appear in the
transcript. It is a fuzzy edit-distance alignment at the pipeline's own 0.80
word-match threshold. **Timing** is agreement only: there is still no
human-verified reference, so a difference shows a disagreement, not which side
is right.

## Recitation

| | WhisperX | NVIDIA RNNT | NVIDIA CTC | Cohere + wav2vec2 |
|---|---|---|---|---|
| **97 s clip**: recall | 67/67 | 65/67 | 63/67 | 67/67 |
| range detected | 25:7–11 | 25:7–11 | 25:7–11 | 25:7–11 |
| onsets vs WhisperX: median / within 500 ms | — | 59 ms / 59 of 67 | 345 ms / 45 of 67 | 5 ms / 61 of 67 |
| **292 s clip**: recall | 224/228 | 226/228 | 227/228 | 224/228 (+67 words that are not there) |
| range detected | 25:23–44 | 25:23–44 | 25:23–44 | **25:23–42**: lost 43–44 |
| onsets vs WhisperX: median / within 500 ms | — | **52 ms / 228 of 228** | 278 ms / 186 of 228 | (range differs) |
| CPU time, 97 s + 292 s | (cloud) | 2 s + 7 s | 2 s + 7 s | 230 s + 737 s |

Cohere's 5 ms agreement on the short clip is not independent evidence. Its
timings come from the same wav2vec2 aligner WhisperX uses.

NVIDIA's CTC decoder recognises as well as RNNT but times noticeably worse. Use
RNNT.

## Lecture

All four engines find the same six mentions: 25:1, 7, 8, 9, 10 and 11. Start
times agree within a few seconds, with one exception. The 25:8 mention starts
at 233.5 s for WhisperX and Cohere but 262 s for NVIDIA. The transcripts are
the same there: the lecturer recites 7 and 8 straight through, and the matcher
drew the boundary between them differently. That is a matcher question, not a
recognition one.

CPU time for the 13-minute lecture: NVIDIA RNNT 20 s, Cohere 32 min.

A side observation: NVIDIA writes the quoted ayat with full tashkīl and the
lecturer's commentary without it. That is a free signal for where a quotation
starts and ends, which lecture mode does not use yet.

## The 25:7 passage: a repeat, not a dropout

Only Cohere transcribed it as recited:

| time | words (Cohere + wav2vec2) |
|---|---|
| 9.15–13.15 s | لولا أنزل إليه ملك |
| 14.43–18.34 s | لولا أنزل إليه ملك (**the reciter repeats it**) |
| 19.58–22.70 s | فيكون معه نذيرا |

WhisperX kept the first copy, which left its "7.5-second gap" over the repeat.
NVIDIA and the earlier local aligner kept the second copy. Both are right about
a different copy. The earlier finding's conclusion still stands (confidence
does not reveal errors, and QA needs a listener), but the specific dispute is
resolved.

This matters for the product. The canonical text has the phrase once, so
whichever engine is used, a repeated phrase leaves part of the audio without
its own highlight. The renderer holds the highlight through it, which is
acceptable, but a reciter's repeats are common and the review tool should
expect them.

Cohere also transcribes a salawat, "اللهم صل وسلم على سيدنا محمد", at about
70–73 s, in the middle of 25:10. WhisperX heard "إن أتن" there and NVIDIA a
doubled "جنات". The aligner placed those words in slivers with score 0.00, so
**whether the salawat is really in the audio needs one listen**.

## Cohere's failure on recitation

In the 292 s clip, 3 of 13 windows went wrong:

- 24 s: the start of 25:25 is correct, then the decoder emits a fake reference,
  "36:21", and *"The Lord of the world"* dozens of times in English. Ayat 26–27
  are missing.
- 122 s: a fake reference, "36:27", and *"And we will not give you the truth"*
  in English.
- 192 s: *"وكلا ضربنا له الأمثال"* repeated about eight times.

The other ten windows are clean, and diacritised where the model chose to be.
The model's benchmarks are conversational and dialect speech, and long tajwīd
elongations look outside what it was trained on. Decoding constraints
(`repetition_penalty`, `no_repeat_ngram_size`), shorter windows, or detecting
non-Arabic output might contain this. That is tuning work, and it would still
leave a 2B model running at 2–2.5× slower than real time on this laptop.

## Engineering constraints measured

| | NVIDIA FastConformer | Cohere Transcribe Arabic |
|---|---|---|
| model download | about 0.5 GB | about 4 GB, plus the 1.2 GB aligner |
| venv (CPU torch) | 2.2 GB (NeMo) | 1.6 GB (transformers 5.19) |
| peak RAM | small | 4.5 GB |
| speed on CPU, 16 cores | 40–50× real time | 0.4× real time |
| access | public | gated: accept terms + HF token |
| licence | CC-BY-4.0: shipping it needs attribution | Apache 2.0 |

The laptop's RTX A500 (4 GB) had no working NVIDIA driver, so everything ran on
CPU. During the scoring pass, an unrelated memory squeeze made systemd-oomd
kill several desktop apps. The bake-off itself is light apart from Cohere's
4.5 GB.

## Extended test: all Al-Furqān audio (9 October 2026)

WhisperX (Replicate API) against NVIDIA RNNT only. Cohere was left out, and so
was the unrelated `sh-kais` lecture. Added:

- the two full-surah recitations, `alFurqan.mp3` (19 min) and `furqanTra.mp3`
  (21 min)
- the twelve lecture recordings in `~/Downloads/alfurqan-lectures/audio/`
  (12–16 … 71–77, about two hours)

The original files were used, not the `refined/` speech-enhanced copies.

### Full-surah recitations

| | `alFurqan` WhisperX | `alFurqan` NVIDIA | `furqanTra` WhisperX | `furqanTra` NVIDIA |
|---|---|---|---|---|
| recall of 25:1–77 (893 words) | 867 (97.1%) | **887 (99.3%)** | 870 (97.4%) | **887 (99.3%)** |
| range detected | 1–77 | 1–77 | 1–77 | 1–77 |
| ayat covered by cards | 74 of 77 | 74 of 77 | 76 of 77 | 76 of 77 |
| cards | 20 | 20 | 21 | 21 |
| transcription time | about 40 s on Replicate | 54 s on CPU | (saved) | 57 s on CPU |

Both engines miss the same final ayat (75–77, and 77). Since the miss is
identical, it comes from the recording's ending or the matcher, not from
recognition.

Onsets were compared on the canonical words both timelines contain. The cards
split differently, so words are paired by aligning the word sequences:

| | words paired | median difference | within 100 ms | within 500 ms | over 1 s |
|---|---|---|---|---|---|
| `alFurqan` | 871 | 56 ms | 635 | 824 (95%) | 42 |
| `furqanTra` | 885 | 55 ms | 654 | 857 (97%) | 20 |

The over-1 s words are not scattered. They sit in four or five tight passages
per recording: `alFurqan` at 262–270, 290, 406–429, 714–737 and 1002 s;
`furqanTra` at 32–53, 146–153, 205 and 298 s. In `furqanTra`, 146–153 s is the
25:7 repeat and 205 s the salawat spot, because `furquanTra7-11` was cut from
this recording. The others most likely have the same cause, but that is not yet
confirmed by ear.

### Lectures

Coverage counts how many ayat of the lecture's own range, taken from its file
name, get a mention:

| Lecture | WhisperX | NVIDIA |
|---|---|---|
| 7–11 | 5/5 | 5/5 |
| 12–16 | 5/5 | 5/5 |
| 17–20 | 3/4 | 3/4 |
| 21–26 | 5/6 | 5/6 |
| 27–32 | 5/6 | 5/6 |
| 33–39 | 3/7 | **4/7** |
| 40–43 | 3/4 | **4/4** |
| 44–49 | 5/6 | 5/6 |
| 50–55 | 4/6 | 4/6 |
| 56–60 | 2/5 | 2/5 |
| 61–67 | 5/7 | 5/7 |
| 68–71 | 2/4 | **3/4** |
| 71–77 | 4/7 | **5/7** |
| **total** | **51/72** | **55/72** |

NVIDIA is never worse and better on four lectures. The ayat both engines miss
are probably ayat the lecturer explains without quoting in full; that has not
been checked. Mentions outside the studied range are almost identical between
the two engines: cross-references such as 67:7 and 98:7, and 37:180, the
closing "سبحان ربك رب العزة عما يصفون" that ends most lectures.

### Matcher cost

Transcription is no longer the slow step. Range detection plus matching with
`recitation-match` took about 16 minutes per full-surah recitation (951–974 s),
against under a minute to transcribe. Lecture matching took 24–224 s per
lecture; it was faster on NVIDIA's transcripts in every case. This is the cost
the comment in `pipelines/detection.py` describes, and it is removed by giving
the range up front.

## sherpa-onnx parity (Phase 0 of the local engine)

The model exported with `tools/export_local_model` (NeMo 3.0.0) and run through
sherpa-onnx 1.13.8 on the same 17 clips, checked against NeMo RNNT by
`prototypes/asr_bakeoff/gate.py`:

| Check | int8 | fp32 |
|---|---|---|
| alFurqan recall >= 883/893 | pass, 883/893 | pass, 887/893 |
| furqanTra recall >= 883/893 | pass, 889/893 | pass, 888/893 |
| furquanTra7-11 detected range identical, ayat covered within 1 of NeMo | pass, 5/5, range 25:7-11 | pass, 5/5, range 25:7-11 |
| alFurqanCut detected range identical, ayat covered within 1 of NeMo | pass, 22/22, range 25:23-44 | pass, 22/22, range 25:23-44 |
| alFurqan detected range identical, ayat covered within 1 of NeMo | pass, 76 (NeMo 74), range 25:1-77 | pass, 74 (NeMo 74), range 25:1-77 |
| furqanTra detected range identical, ayat covered within 1 of NeMo | pass, 75 (NeMo 76), range 25:1-77 | pass, 75 (NeMo 76), range 25:1-77 |
| Lecture studied ayat >= 54/72 | pass, 56/72 | pass, 56/72 |
| Onsets vs NeMo over all recitation words (every median <= 20 ms, >= 95% within 100 ms) | pass, 2007/2043 (98.2%), medians 0 ms | pass, 2025/2051 (98.7%), medians 0 ms |
| Word ends never before start nor past next start | pass, 0 | pass, 0 |

Both variants exit 0 under the amended gate.

The strict first run failed three checks. Mostly they measured the matcher's
boundary noise and a known NeMo error rather than the engine, with one
exception in int8 (below). "Range and cards identical" failed on the two
full-surah recitations: the card boundaries differ from NeMo's at four places
per full recitation for int8 and two for fp32 (int8 also has one extra card on
alFurqan), and WhisperX differs from NeMo as well, which was accepted. What
matters is card coverage (ayat covered of 77):

| | NeMo | sherpa int8 | sherpa fp32 | WhisperX |
|---|---|---|---|---|
| alFurqan | 74 | 76 | 74 | 74 |
| furqanTra | 76 | 75 (misses 6) | 75 (misses 76) | 76 |

The per-clip onset check failed on furquanTra7-11. fp32 scored 63/67: the four
off words are at the end of 25:11, where NeMo's own reference merged
"بالساعة وأعتدنا" into one garbled word. int8 scored 62/67, two words short of
95%, with five off words: the same four, plus `لَّكَ` in 25:10 (off by +0.56 s),
where int8 itself merged "ويجعل لك" into one word `ويجعلك`; fp32 and NeMo split
it correctly. int8's alFurqan recall sits exactly on the 883 floor (NeMo and
fp32: 887). The spec's criterion was over all recitation words, which passes
for both variants with margin (98.2% and 98.7%). The gate was amended on
10 October 2026 accordingly: the detected range must be identical to NeMo's, coverage must be
at least NeMo's minus one, and onsets are judged over all recitation words.
Separately, `score.py` now skips the five WhisperX reference words that were
never aligned (no start/end) when counting end violations.

**Shipping: int8 (108 MB archive).**

The shipped engine (`qurantext transcribe --engine local`) passes the same gate on all 17 clips.

## Licence finding (10 October 2026): the sherpa-onnx build contains espeak-ng

**Found:** the PyPI build of sherpa-onnx 1.13.8, which the app bundles to run the
model, is not Apache-2.0 and MIT only. It contains espeak-ng
(GPL-3.0-or-later), which sherpa-onnx uses for text to speech, a feature Qalun
does not use. The parity work above assumed an Apache-licensed runtime and did
not check this.

**How it was verified,** on Linux, in both the project's virtual environment and
the built bundle (`dist/qalun/_internal/sherpa_onnx/lib/`):

- `nm -D --defined-only _sherpa_onnx.cpython-312-x86_64-linux-gnu.so | grep -c ' espeak_'`
  gives **50** in both: the extension the app imports defines and exports
  `espeak_*` and `espeak_ng_*` functions (`espeak_Cancel`, `espeak_Char`,
  `espeak_CompileDictionary`, ...).
- `readelf -d` on it lists no espeak library among its `NEEDED` entries, so
  espeak-ng is linked in statically, not loaded from elsewhere.
- `libsherpa-onnx-c-api.so`, also in the bundle, contains espeak-ng code too.
- The Windows and macOS wheels were not inspected. They offer the same
  text-to-speech API, so they are expected to contain it as well.

**Status: Resolved 2026-10-10: Qalun is licensed GPL-3.0-only; the source ships
with each release.** The owner chose to release Qalun itself under GPL-3.0-only
(Copyright (C) 2026 Khalil), with which espeak-ng's GPL-3.0-or-later is
compatible. The repository stays private; instead, `packaging/ci/package.sh`
puts `qalun-source.zip` (`git archive` of the commit built) inside every app
zip, beside the app (decided 10 Oct 2026, after the source zip was first
attached to the release beside the app zips), together with
`third-party-sources/`: the exact espeak-ng archive sherpa-onnx 1.13.8 builds
from (csukuangfj/espeak-ng at `ed530aa1…`) and, in the Linux zip, alsa-lib
1.2.12, each pinned by URL and sha256 in `packaging/third-party-sources.txt`.
sherpa-onnx is pinned exactly to 1.13.8. `LICENSE` (the
full GPL-3.0 text) ships in the bundle and at the top of every zip, the
package metadata says `GPL-3.0-only`, `THIRD_PARTY_NOTICES.md` opens with
Qalun's own licence statement, and the doctor report names it. The sherpa-onnx
build itself is unchanged; `docs/release-checklist.md` now checks that each
app zip carries the source archives, `LICENSE` and `THIRD_PARTY_NOTICES.md`.

## What this changes

1. **Make NVIDIA FastConformer (RNNT) a local transcription engine** behind
   the existing WhisperX JSON interface, alongside Replicate, and make it the
   default. On all 17 Al-Furqān clips it is at least as good as WhisperX:
   higher recall on both full recitations, the same range and cards, and
   equal or better lecture coverage. It removes the cloud dependency and the
   Replicate cost, and works offline.
2. **Other reciters and surahs are still untested.** All the audio so far is
   Al-Furqān, from a few speakers.
3. **Listen to two spots**: `furquanTra7-11` at 14–19 s (confirms the repeat)
   and at 69–74 s (salawat or not). Then the timing comparison can name a
   winner rather than report agreement.
4. **NeMo's install size** (2.2 GB with CPU torch) matters for packaging the
   Qalun desktop app. Check exporting the model to ONNX before shipping NeMo
   itself.
5. Park Cohere. Revisit only if a GPU is available and repetition control
   tames the loops.

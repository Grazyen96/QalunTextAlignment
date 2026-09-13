# Forced alignment on tajwīd: prototype result

**Date:** 13 September 2026
**Plan item:** Phase 2, B6a — prototype forced alignment before committing to it

**Decision: do not move recitation timing onto a generic CTC forced aligner on
this evidence. The disagreement that matters cannot be settled without a
qualified listener, which is itself the result: alignment QA has to be a human
gate, as the architecture document already says.**

A second, firmer result: an aligner's confidence score does not reveal where it
is wrong, so QA cannot be confidence-gated.

## What was tried

A local CTC forced alignment — the same approach WhisperX uses internally for
word timings, run offline instead of through the cloud.

| | |
|---|---|
| Acoustic model | `jonatasgrosman/wav2vec2-large-xlsr-53-arabic` |
| Alignment | `torchaudio.functional.forced_align` over the model's emissions |
| Audio | `input/recitations/furquanTra7-11.mp3`, 97 s, Al-Furqān 7–11 |
| Text | canonical Qalun text for that range, 67 words |
| Reference | the current pipeline's word timings for the same clip |

The canonical text needed no new normalisation: `normalize_alignment_ar`
already emits undiacritised Arabic letters, and every character it produces is
in the model's 51-symbol vocabulary.

## Result: close agreement, then one five-second rift

All 67 words aligned, monotonically.

| Agreement with the current pipeline | |
|---|---|
| median onset difference | 9 ms |
| within 50 ms | 57 / 67 (85%) |
| within 500 ms | 60 / 67 (90%) |
| disagree by over 1 s | 7 / 67 (10%) |

The seven outliers are not scattered. They are one contiguous passage, the end
of 25:7 (`لولا أنزل إليه ملك فيكون معه نذيرا`), and each disagrees by about five
seconds.

## What is proven, and what is not

**Proven: the recogniser drops recited audio.** The current timings are exactly
what the recogniser reported, including a 7.5-second gap after `نذيرا` ends at
16.70 s and before `أو` begins at 24.18 s. Measuring the waveform directly, that
"gap" is not silence:

| region | mean level |
|---|---|
| 16.7–24.2 s, reported as nothing | −21.2 dBFS |
| 9.0–16.7 s, known recitation | −21.0 dBFS |

Two tenths of a decibel apart. Roughly seven seconds of audio at full recitation
level carries no word in the current timeline. The only true silences in that
stretch are 13.0–14.2 s and 23.0–24.0 s.

**Not proven: which system has the right onsets.** Greedy-decoding short windows
over the disputed region was attempted as an adjudicator and the output is too
degraded to trust — the model is trained on undiacritised conversational Arabic
and returns fragments like `قُن فِي لائيا` across an elongation. It is enough to
show speech is present; it is not enough to say which word is being recited at
19.5 s. A first pass at this over-read those fragments and briefly concluded
both systems were provably wrong in opposite directions. They are not: the
question is open, and settling it needs someone who can listen.

That is the honest shape of the result, and it points at the same place the
architecture document does when it calls for a review tool that plays the ayah
with the highlight running against the waveform.

## Coverage, and why it is the wrong metric

Measuring how much speech-level audio each timeline assigns to some word:

| system | speech covered | uncovered | longest hole |
|---|---|---|---|
| current pipeline | 86.1% | 12.0 s | 6.2 s |
| local forced align | 63.8% | 31.2 s | 3.0 s |

The aligner looks far worse, but this metric flatters neither fairly. CTC spans
cover a token's emission peak, not a word's full acoustic extent, so gaps
between them are expected. And the renderer switches the highlight on a word's
*start* and holds it through any gap, so an uncovered stretch does not blank the
screen. Onset accuracy is what a viewer feels; coverage is not.

## The confidence score does not flag the errors

This is the firm negative result, and it stands independently of the
adjudication above.

| | mean confidence |
|---|---|
| words the aligner disagrees on by over 1 s | 0.77 |
| words that agree within 1 s | 0.71 |

Confidence is *higher* where the aligner is at odds with the reference. Only one
of the seven disputed words scored below 0.5, while twelve words below that
threshold were timed consistently. Two of the five-second disagreements scored
0.96 and 0.97.

The architecture document proposes storing per-word confidence so review can
target weak spots. On this evidence that would hide the disputed passage and
spend the reviewer's attention on words that are fine.

## Engineering constraints measured along the way

- **Speed is not the problem.** 19 s of CPU compute for 97 s of audio, roughly
  0.2× realtime on 16 cores with no GPU.
- **Chunking is mandatory.** wav2vec2 uses full self-attention, so cost grows
  with the square of the input. The 97 s clip needed about 1.5 GB per layer; a
  292 s clip does not fit in 15 GB. Real use must window the audio and stitch
  the results, which is itself a source of boundary error.
- **Footprint.** CPU-only torch is about 1 GB installed, the acoustic model a
  further 1.2 GB.

## What this changes in the plan

1. **Recitation timing stays where it is** until there is a review tool that can
   settle disputes like this one. Swapping aligners without one trades a known
   failure for an unmeasured one.
2. **The recogniser dropping seven seconds of recited audio is a real defect**
   and is worth fixing regardless of which aligner wins. A gap between
   recognised words that carries speech-level energy is detectable without any
   model, from the waveform alone.
3. **Review cannot be confidence-gated.** The Phase 4 editor should show the
   recitation timeline against the waveform and let a person fix it, and must
   not promise that low confidence marks the spots worth checking.
4. **B6b is unaffected.** Swapping *recognition* for a stronger Arabic model
   still helps the lecture path, where the text is unknown and word-error rate
   drives how much correcting the user does.

## Reproducing

`prototypes/forced_alignment/` holds the scripts. They are not part of the
package and deliberately are not in its dependencies:

```bash
python3 -m venv /tmp/alignenv
/tmp/alignenv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio
/tmp/alignenv/bin/pip install numpy transformers soundfile
ffmpeg -i input/recitations/furquanTra7-11.mp3 -ac 1 -ar 16000 clip16k.wav
# align_probe.py expects align_input.json: the canonical tokens plus the
# current pipeline's timings for the same clip.
```

The waveform measurements need nothing beyond ffmpeg and numpy, which the
package already has.

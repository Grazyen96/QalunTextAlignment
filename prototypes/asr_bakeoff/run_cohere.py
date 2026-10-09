"""Cohere Transcribe Arabic (2B) for the words, WhisperX's Arabic wav2vec2 aligner for the times.

The model gives no timestamps, so each pause-cut window's transcript is forced
aligned against that window's audio with the same acoustic model WhisperX uses
for Arabic — the ASR is swapped and the aligner held constant.

    python run_cohere.py AUDIO OUT.json
"""
import argparse
import gc
import time

import numpy as np
import torch
import torchaudio.functional as AF
from transformers import (
    AutoProcessor,
    CohereAsrForConditionalGeneration,
    Wav2Vec2ForCTC,
    Wav2Vec2Processor,
)

from common import SR, chunk_at_pauses, load_audio, normalize_alignment_ar, write_whisperx_json

ASR = "CohereLabs/cohere-transcribe-arabic-07-2026"
ALIGN = "jonatasgrosman/wav2vec2-large-xlsr-53-arabic"  # WhisperX's default for "ar"

ap = argparse.ArgumentParser()
ap.add_argument("audio")
ap.add_argument("out")
args = ap.parse_args()

# The two models are loaded one after the other, never together: 2B in bf16
# plus the 1.2 GB aligner does not fit a laptop with everything else open.
t_load = time.time()
proc = AutoProcessor.from_pretrained(ASR)
asr = CohereAsrForConditionalGeneration.from_pretrained(ASR, dtype=torch.bfloat16).eval()
t_load = time.time() - t_load


def transcribe(chunk: np.ndarray) -> str:
    inputs = proc(chunk, sampling_rate=SR, return_tensors="pt", language="ar")
    inputs = inputs.to(asr.device, dtype=asr.dtype)
    out = asr.generate(**inputs, max_new_tokens=448)
    text = proc.decode(out, skip_special_tokens=True)
    # A batch of one decodes to a one-item list.
    return " ".join(text) if isinstance(text, list) else text


def align(chunk: np.ndarray, words: list[str], off: float) -> list[dict]:
    """Forced-align ``words`` inside ``chunk``; a word with no alignable letter
    inherits its neighbour's end so the list stays monotonic and complete."""
    targets, spans = [], []
    for i, w in enumerate(words):
        if i:
            targets.append(delim)
        a = len(targets)
        targets.extend(vocab[c] for c in normalize_alignment_ar(w).replace(" ", "") if c in vocab)
        spans.append((a, len(targets)))
    emission = torch.log_softmax(aligner(torch.from_numpy(chunk).unsqueeze(0)).logits, dim=-1)
    ratio = len(chunk) / emission.shape[1] / SR
    path, scores = AF.forced_align(emission, torch.tensor([targets], dtype=torch.int32), blank=blank)
    tokens = AF.merge_tokens(path[0], scores[0].exp())
    out, last = [], off
    for (a, b), w in zip(spans, words):
        seg = [t for t in tokens[a:b] if t.token != delim]
        if seg:
            s, e = off + seg[0].start * ratio, off + seg[-1].end * ratio
            score = float(np.mean([t.score for t in seg]))
        else:
            s = e = last
            score = 0.0
        out.append({"word": w, "start": round(s, 3), "end": round(e, 3), "score": round(score, 4)})
        last = e
    return out


audio = load_audio(args.audio)
windows = list(chunk_at_pauses(audio))
with torch.inference_mode():
    t0 = time.time()
    texts = []
    for a, b in windows:
        texts.append(transcribe(audio[a:b]))
        print(f"  {a / SR:7.1f}s  {len(texts[-1].split()):3d} words")
    t_asr = time.time() - t0
    del asr
    gc.collect()

    aproc = Wav2Vec2Processor.from_pretrained(ALIGN)
    aligner = Wav2Vec2ForCTC.from_pretrained(ALIGN).eval()
    vocab = aproc.tokenizer.get_vocab()
    blank, delim = aproc.tokenizer.pad_token_id, vocab["|"]

    t0 = time.time()
    segments = []
    for (a, b), text in zip(windows, texts):
        words = text.split()
        if not words:
            continue
        timed = align(audio[a:b], words, a / SR)
        segments.append(
            {"start": timed[0]["start"], "end": timed[-1]["end"], "text": text, "words": timed}
        )
    t_align = time.time() - t0

write_whisperx_json(
    segments,
    args.out,
    {
        "engine": "cohere+wav2vec2",
        "model": ASR,
        "aligner": ALIGN,
        "audio_s": round(len(audio) / SR, 1),
        "chunks": len(windows),
        "load_s": round(t_load, 1),
        "asr_s": round(t_asr, 1),
        "align_s": round(t_align, 1),
    },
)
print(f"{args.audio}: {sum(len(s['words']) for s in segments)} words, asr {t_asr:.0f}s align {t_align:.0f}s")

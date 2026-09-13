"""Step B: force-align the canonical text against the audio with a local CTC model.

This is the Phase 2 prototype. It asks one question: with the text already known,
can a local acoustic model place every canonical word in time well enough to
drive the word highlight? The reference is the current WhisperX-derived timing,
which the creator has already accepted in rendered videos.
"""
import json, sys, time
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
import torchaudio.functional as AF
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

S = Path(sys.argv[1])
MODEL = "jonatasgrosman/wav2vec2-large-xlsr-53-arabic"

data = json.load(open(S / "align_input.json"))
words = data["tokens_norm"]

audio, sr = sf.read(S / "clip16k.wav", dtype="float32")
assert sr == 16000, sr
print(f"audio {len(audio)/sr:.1f}s  words {len(words)}")

proc = Wav2Vec2Processor.from_pretrained(MODEL)
model = Wav2Vec2ForCTC.from_pretrained(MODEL).eval()
vocab = proc.tokenizer.get_vocab()
blank = proc.tokenizer.pad_token_id
delim = vocab["|"]

# Map the canonical text into the model's vocabulary. Anything the model has no
# symbol for would break the alignment, so report it rather than silently drop.
missing = sorted({c for w in words for c in w if c not in vocab})
if missing:
    print("WARNING characters absent from the model vocab:", missing)

targets, word_spans = [], []
for i, w in enumerate(words):
    if i:
        targets.append(delim)
    start = len(targets)
    targets.extend(vocab[c] for c in w if c in vocab)
    word_spans.append((start, len(targets)))

t0 = time.time()
with torch.inference_mode():
    # 97s at once on CPU is fine for a large model; chunk if this ever grows.
    logits = model(torch.from_numpy(audio).unsqueeze(0)).logits
    emission = torch.log_softmax(logits, dim=-1)
print(f"emissions {tuple(emission.shape)} in {time.time()-t0:.0f}s")

targets_t = torch.tensor([targets], dtype=torch.int32)
aligned, scores = AF.forced_align(emission, targets_t, blank=blank)
aligned, scores = aligned[0], scores[0].exp()

# Frame -> seconds. One emission frame covers len(audio)/num_frames samples.
ratio = len(audio) / emission.shape[1] / sr

spans = AF.merge_tokens(aligned, scores)          # one entry per emitted token
token_time = {}
for s in spans:
    token_time.setdefault(s.token, [])
by_index = [s for s in spans]

# merge_tokens returns spans in target order, so walk them alongside the targets.
assert len(by_index) == len(targets), (len(by_index), len(targets))
out = []
for (a, b), w in zip(word_spans, words):
    seg = by_index[a:b]
    if not seg:
        out.append(None); continue
    out.append({
        "word": w,
        "start": round(seg[0].start * ratio, 3),
        "end": round(seg[-1].end * ratio, 3),
        "score": round(float(np.mean([s.score for s in seg])), 4),
    })

json.dump(out, open(S / "align_output.json", "w"), ensure_ascii=False, indent=1)
print("aligned words:", sum(1 for o in out if o))
print("first 5:", json.dumps(out[:5], ensure_ascii=False))

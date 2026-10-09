"""NVIDIA FastConformer Arabic (115M, trained partly on EveryAyah) with its own word timestamps.

    python run_nemo.py AUDIO OUT.json [--decoder rnnt|ctc]
"""
import argparse
import tempfile
import time
from pathlib import Path

import soundfile as sf

from common import SR, chunk_at_pauses, load_audio, write_whisperx_json

MODEL = "nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0"

ap = argparse.ArgumentParser()
ap.add_argument("audio")
ap.add_argument("out")
ap.add_argument("--decoder", choices=["rnnt", "ctc"], default="rnnt")
args = ap.parse_args()

import nemo.collections.asr as nemo_asr  # noqa: E402  (slow import, after argparse)

t_load = time.time()
model = nemo_asr.models.EncDecHybridRNNTCTCBPEModel.from_pretrained(model_name=MODEL).eval()
model.change_decoding_strategy(decoder_type=args.decoder)
t_load = time.time() - t_load

audio = load_audio(args.audio)
windows = list(chunk_at_pauses(audio))

t0 = time.time()
with tempfile.TemporaryDirectory() as tmp:
    paths = []
    for i, (a, b) in enumerate(windows):
        p = Path(tmp) / f"{i:04d}.wav"
        sf.write(p, audio[a:b], SR)
        paths.append(str(p))
    hyps = model.transcribe(paths, batch_size=4, timestamps=True)
t_asr = time.time() - t0

segments = []
for (a, b), hyp in zip(windows, hyps):
    off = a / SR
    words = [
        {
            "word": w["word"],
            "start": round(off + w["start"], 3),
            "end": round(off + w["end"], 3),
            "score": 1.0,  # the model gives no per-word confidence
        }
        for w in hyp.timestamp["word"]
        if w["word"].strip()
    ]
    if words:
        segments.append(
            {"start": words[0]["start"], "end": words[-1]["end"], "text": hyp.text, "words": words}
        )

write_whisperx_json(
    segments,
    args.out,
    {
        "engine": f"nemo-{args.decoder}",
        "model": MODEL,
        "audio_s": round(len(audio) / SR, 1),
        "chunks": len(windows),
        "load_s": round(t_load, 1),
        "asr_s": round(t_asr, 1),
    },
)
print(f"{args.audio}: {sum(len(s['words']) for s in segments)} words, asr {t_asr:.0f}s")

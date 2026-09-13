"""Which timeline is right? Ask the acoustic model what is actually being said.

Greedy-decode the audio around each candidate onset and compare the transcript
to the canonical words. No listening required, and no appeal to either aligner.
"""
import sys
from pathlib import Path
import numpy as np, soundfile as sf, torch
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

S = Path(sys.argv[1])
proc = Wav2Vec2Processor.from_pretrained("jonatasgrosman/wav2vec2-large-xlsr-53-arabic")
model = Wav2Vec2ForCTC.from_pretrained("jonatasgrosman/wav2vec2-large-xlsr-53-arabic").eval()
audio, sr = sf.read(S / "clip16k.wav", dtype="float32")

def decode(t0, t1):
    seg = audio[int(t0 * sr): int(t1 * sr)]
    with torch.inference_mode():
        logits = model(torch.from_numpy(seg).unsqueeze(0)).logits
    return proc.batch_decode(torch.argmax(logits, dim=-1))[0].strip()

expected = "انزل اليه ملك فيكون معه نذيرا"
print("canonical words in dispute:", expected)
print()
print("current pipeline says they run 10.1s - 16.6s:")
print("   ->", decode(10.1, 16.6))
print()
print("local forced alignment says 15.7s - 22.2s:")
print("   ->", decode(15.7, 22.2))
print()
print("context, 0s - 10s:")
print("   ->", decode(0, 10))

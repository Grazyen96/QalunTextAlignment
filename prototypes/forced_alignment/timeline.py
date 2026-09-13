"""Sliding 2-second decode across the disputed region, so each word can be placed."""
import sys
from pathlib import Path
import soundfile as sf, torch
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

S = Path(sys.argv[1])
proc = Wav2Vec2Processor.from_pretrained("jonatasgrosman/wav2vec2-large-xlsr-53-arabic")
model = Wav2Vec2ForCTC.from_pretrained("jonatasgrosman/wav2vec2-large-xlsr-53-arabic").eval()
audio, sr = sf.read(S / "clip16k.wav", dtype="float32")

print("canonical order here: لولا  انزل  اليه  ملك  فيكون  معه  نذيرا")
print()
for t in range(8, 26):
    seg = audio[t * sr:(t + 2) * sr]
    with torch.inference_mode():
        logits = model(torch.from_numpy(seg).unsqueeze(0)).logits
    text = proc.batch_decode(torch.argmax(logits, dim=-1))[0].strip()
    print(f"  {t:2d}-{t+2:2d}s : {text}")

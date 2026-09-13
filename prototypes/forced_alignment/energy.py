"""Is a gap between recognised words silence, or dropped audio?

Needs only ffmpeg and numpy. Decode the clip to 16 kHz mono f32 first:

    ffmpeg -i clip.mp3 -ac 1 -ar 16000 -f f32le clip.raw

Then: python3 energy.py clip.raw 16.7 24.2
"""

import sys

import numpy as np

raw, lo, hi = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
sr, hop = 16000, 4000  # 250 ms frames
a = np.fromfile(raw, dtype=np.float32)
rms = np.sqrt(np.array([np.mean(a[i : i + hop] ** 2) for i in range(0, len(a) - hop, hop)]) + 1e-12)
db = 20 * np.log10(rms)
floor = np.percentile(db, 5)
frame = lambda t: int(t * sr / hop)  # noqa: E731

print(f"noise floor (5th pct): {floor:6.1f} dBFS")
print(f"mean level {lo}-{hi}s : {db[frame(lo) : frame(hi)].mean():6.1f} dBFS")
print(f"whole clip            : {db.mean():6.1f} dBFS")
print("A region within a decibel or two of the clip mean is recited audio, not a pause.")

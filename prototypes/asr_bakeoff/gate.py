"""Spec §0's parity gate: does ENGINE reproduce the bake-off's NeMo RNNT results?

    venv/bin/python prototypes/asr_bakeoff/gate.py BAKE ENGINE    # exit 0 = pass

Amended 2026-10-10 by the user's decision: card splits and a single clip's onsets
measured matcher noise and a known NeMo error; coverage and all-words onsets are
the criteria.
"""

import json
import sys
from pathlib import Path

bake, engine = Path(sys.argv[1]), sys.argv[2]
r = json.loads((bake / "results.json").read_text(encoding="utf-8"))
REF = "nemo-rnnt"
RECITATIONS = ("furquanTra7-11", "alFurqanCut", "alFurqan", "furqanTra")
checks = []


def hits(row):
    return int(row["canonical_recall"].split("/")[0])


for clip in ("alFurqan", "furqanTra"):
    got = hits(r[clip][engine])
    checks.append((f"{clip} recall >= 883/893", got >= 883, f"{got}/893"))


def ayat(mentions):
    return {a for m in mentions if m[0] == 25 for a in range(m[1], m[2] + 1)}


def detected(eng, clip):
    d = json.loads((bake / eng / f"{clip}_recitation_match.json").read_text(encoding="utf-8"))
    return d["first_ayah"]["surah_num"], d["first_ayah"]["ayah_num"], d["last_ayah"]["ayah_num"]


for clip in RECITATIONS:
    got, ref = len(ayat(r[clip][engine]["mentions"])), len(ayat(r[clip][REF]["mentions"]))
    rng = detected(engine, clip)
    ok = rng == detected(REF, clip) and got >= ref - 1
    checks.append((f"{clip} range identical, ayat covered within 1 of NeMo", ok, f"covered {got}/{ref} ayat (NeMo), detected range {rng[0]}:{rng[1]}-{rng[2]}"))
covered = sum(
    int(row[engine]["studied"]["covered"].split("/")[0])
    for clip, row in r.items()
    if clip.startswith("lecture") and engine in row
)
checks.append(("lecture studied ayat >= 54/72", covered >= 54, f"{covered}/72"))
ts = {clip: r[clip][engine][f"timing_vs_{REF}"] for clip in RECITATIONS}
for clip, t in ts.items():
    info = t if isinstance(t, str) else f"median {t['median_ms']} ms, {t['within_100ms']}/{t['paired']} within 100 ms"
    print(f"INFO  {clip} onsets vs NeMo  {info}")
if all(isinstance(t, dict) for t in ts.values()):
    within = sum(t["within_100ms"] for t in ts.values())
    paired = sum(t["paired"] for t in ts.values())
    medians = [t["median_ms"] for t in ts.values()]
    ok = max(medians) <= 20 and within >= 0.95 * paired
    detail = f"{within}/{paired} within 100 ms ({within / paired:.1%}), medians {medians} ms"
else:
    ok, detail = False, "missing timing"
checks.append(("onsets vs NeMo over all recitation words", ok, detail))
violations = sum(r[c][engine]["end_violations"] for c in r if engine in r[c])
checks.append(("word ends never before start nor past next start", violations == 0, str(violations)))

for name, ok, detail in checks:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
sys.exit(0 if all(ok for _, ok, _ in checks) else 1)

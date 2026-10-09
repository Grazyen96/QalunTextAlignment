"""Spec §0's parity gate: does ENGINE reproduce the bake-off's NeMo RNNT results?

    venv/bin/python prototypes/asr_bakeoff/gate.py BAKE ENGINE    # exit 0 = pass
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
for clip in RECITATIONS:
    same = [m[:3] for m in r[clip][engine]["mentions"]] == [m[:3] for m in r[clip][REF]["mentions"]]
    checks.append((f"{clip} range and cards identical", same, ""))
covered = sum(
    int(row[engine]["studied"]["covered"].split("/")[0])
    for clip, row in r.items()
    if clip.startswith("lecture") and engine in row
)
checks.append(("lecture studied ayat >= 54/72", covered >= 54, f"{covered}/72"))
for clip in RECITATIONS:
    t = r[clip][engine][f"timing_vs_{REF}"]
    ok = isinstance(t, dict) and t["median_ms"] <= 20 and t["within_100ms"] >= 0.95 * t["paired"]
    detail = t if isinstance(t, str) else f"median {t['median_ms']} ms, {t['within_100ms']}/{t['paired']} within 100 ms"
    checks.append((f"{clip} onsets vs NeMo", ok, detail))
violations = sum(r[c][engine]["end_violations"] for c in r if engine in r[c])
checks.append(("word ends never before start nor past next start", violations == 0, str(violations)))

for name, ok, detail in checks:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
sys.exit(0 if all(ok for _, ok, _ in checks) else 1)

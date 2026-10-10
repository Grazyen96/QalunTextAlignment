"""Score every engine's raw JSON through the production matcher, then compare.

Runs in the project venv (it imports qurantext):

    venv/bin/python prototypes/asr_bakeoff/score.py BAKE_DIR
    venv/bin/python prototypes/asr_bakeoff/score.py --list   # "clip<TAB>audio" for the runners

BAKE_DIR holds one folder per engine (``whisperx/``, ``nemo-rnnt/``, ...), each
with ``<clip>.json`` raw transcripts named as in CLIPS below. A clip an engine
has no transcript for is skipped.
"""
import json
import statistics
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

from qurantext.config.paths import DEFAULT_QURAN_PATH
from qurantext.core.arabic import normalize_alignment_ar, similarity
from qurantext.core.quran_parser import parse_ayat

QURANTEXT = Path(sys.executable).with_name("qurantext")
BASELINE = "whisperx"
WORD_MATCH = 0.80  # DEFAULT_WORD_MATCH_THRESHOLD in config/settings.py

REPO = Path(__file__).resolve().parents[2]
LECTURES = Path.home() / "Downloads/alfurqan-lectures/audio"

# clip -> (mode, surah, first ayah, last ayah, audio): the range actually recited
# or studied. A lecture's range is the one in its file name.
CLIPS = {
    "furquanTra7-11": ("recitation", 25, 7, 11, REPO / "input/recitations/furquanTra7-11.mp3"),
    "alFurqanCut": ("recitation", 25, 23, 44, REPO / "input/recitations/alFurqanCut.mp3"),
    "alFurqan": ("recitation", 25, 1, 77, REPO / "input/recitations/alFurqan.mp3"),
    "furqanTra": ("recitation", 25, 1, 77, REPO / "input/recitations/furqanTra.mp3"),
    "lecture7-11": ("lecture", 25, 7, 11, REPO / "input/lectures/الفرقان7-11-final.wav"),
    **{
        f"lecture{a}-{b}": ("lecture", 25, a, b, LECTURES / name)
        for a, b, name in [
            (12, 16, "الفرقان12-16.mp3"),
            (17, 20, "الفرقان17-20.mp3"),
            (21, 26, "الفرقان21-26.mp3"),
            (27, 32, "الفرقان27-32.mp3"),
            (33, 39, "الفرقان33-39.mp3"),
            (40, 43, "الفرقان40-43.mp3"),
            (44, 49, "الفرقان44-49.mp3"),
            (50, 55, "الفرقان50-55.mp3"),
            (56, 60, "الفرقان56-60.mp3"),
            (61, 67, "الفرقان61-67.mp3"),
            (68, 71, "الفرقان68-71.mp3"),
            (71, 77, "الفرقان 71 77.mp3"),
        ]
    },
}

if sys.argv[1] == "--list":
    for clip, spec in CLIPS.items():
        print(f"{clip}\t{spec[4]}")
    sys.exit(0)
BAKE = Path(sys.argv[1])

AYAT = parse_ayat(DEFAULT_QURAN_PATH)


def canonical_words(surah: int, first: int, last: int) -> list[str]:
    return [
        w
        for a in AYAT
        if int(a["surah_num"]) == surah and first <= int(a["ayah_num"]) <= last
        for w in normalize_alignment_ar(a["text_raw"]).split()
    ]


def transcript_words(raw: dict) -> list[str]:
    return [
        part
        for s in raw["segments"]
        for w in s.get("words", [])
        for part in normalize_alignment_ar(w["word"]).split()
    ]


def fuzzy_recall(ref: list[str], hyp: list[str]) -> tuple[int, int]:
    """Edit-distance alignment where two words are equal at >= WORD_MATCH similarity.
    Returns (canonical words matched, transcript words left unmatched)."""
    n, m = len(ref), len(hyp)
    prev = list(range(m + 1))
    back = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            same = similarity(ref[i - 1], hyp[j - 1]) >= WORD_MATCH
            options = (prev[j - 1] + (0 if same else 1), prev[j] + 1, cur[j - 1] + 1)
            cur[j] = min(options)
            back[i][j] = options.index(cur[j]) if not (same and cur[j] == options[0]) else 3
        prev = cur
    matched, i, j = 0, n, m
    while i and j:
        step = back[i][j]
        if step == 3:
            matched += 1
        if step in (0, 3):
            i, j = i - 1, j - 1
        elif step == 1:
            i -= 1
        else:
            j -= 1
    return matched, m - matched


def studied_coverage(mentions: list, surah: int, first: int, last: int) -> dict:
    """Which ayat of the studied range some mention covers, and what lies outside it."""
    studied = set(range(first, last + 1))
    covered = {a for s, f, t, *_ in mentions if s == surah for a in range(f, t + 1)}
    return {
        "covered": f"{len(studied & covered)}/{len(studied)}",
        "missing": sorted(studied - covered),
        "outside": sorted(f"{s}:{f}-{t}" for s, f, t, *_ in mentions if s != surah or t < first or f > last),
    }


def run_matcher(mode: str, raw_path: Path) -> dict:
    out = raw_path.with_name(raw_path.stem + f"_{mode}_match.json")
    if not out.exists():
        cmd = [str(QURANTEXT), f"{mode}-match", "--whisperx-json", str(raw_path), "--output", str(out)]
        subprocess.run(cmd, check=True, capture_output=True)
    return json.loads(out.read_text(encoding="utf-8"))


def onsets(match: dict) -> list[tuple[str, float]]:
    return [(w["word"], w["start"]) for m in match["matches"] for w in m.get("word_timings", [])]


def timing_agreement(a: list, b: list) -> dict | None:
    """Compare onsets of the canonical words both timelines contain. The two can
    split the range into different cards, so pair words by aligning the word
    sequences rather than by position."""
    blocks = SequenceMatcher(None, [w for w, _ in a], [w for w, _ in b], autojunk=False)
    pairs = [
        (a[i], b[j])
        for blk in blocks.get_matching_blocks()
        for i, j in zip(range(blk.a, blk.a + blk.size), range(blk.b, blk.b + blk.size))
    ]
    if not pairs:
        return None
    diffs = [abs(x[1] - y[1]) for x, y in pairs]
    return {
        "paired": len(pairs),
        "words": f"{len(pairs)} paired of {len(a)} / {len(b)}",
        "median_ms": round(statistics.median(diffs) * 1000),
        "within_100ms": sum(d <= 0.1 for d in diffs),
        "within_500ms": sum(d <= 0.5 for d in diffs),
        "over_1s": [(w, round(t, 2), round(d, 2)) for (_, (w, t)), d in zip(pairs, diffs) if d > 1.0],
    }


def end_violations(raw: dict) -> int:
    """Words whose end is before their start, or after the next word's start."""
    # WhisperX leaves words it failed to align without times; only timed words can violate.
    words = [w for s in raw["segments"] for w in s.get("words", []) if "start" in w and "end" in w]
    bad = sum(1 for w in words if w["end"] < w["start"])
    bad += sum(1 for a, b in zip(words, words[1:]) if a["end"] > b["start"] + 1e-6)
    return bad


engines = sorted(p.name for p in BAKE.iterdir() if p.is_dir() and not p.name.startswith(("venv", "hf")))
results: dict = {}
for clip, (mode, surah, first, last, _audio) in CLIPS.items():
    ref = canonical_words(surah, first, last)
    per_engine = {}
    for eng in engines:
        raw_path = BAKE / eng / f"{clip}.json"
        if not raw_path.exists():
            continue
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        match = run_matcher(mode, raw_path)
        row = {"meta": raw.get("bakeoff_meta", {}), "transcript_words": len(transcript_words(raw))}
        row["end_violations"] = end_violations(raw)
        row["mentions"] = [
            (m["surah_num"], m["from_ayah"], m["to_ayah"], m["start_time"], round(m["confidence"], 2))
            for m in match["matches"]
            if m.get("from_ayah") is not None  # skip the ta'awwudh/basmala preamble cards
        ]
        if mode == "lecture":
            row["studied"] = studied_coverage(row["mentions"], surah, first, last)
        if mode == "recitation":
            hit, extra = fuzzy_recall(ref, transcript_words(raw))
            row["canonical_recall"] = f"{hit}/{len(ref)} ({hit / len(ref):.1%})"
            row["unmatched_transcript_words"] = extra
            row["onsets"] = onsets(match)
        per_engine[eng] = row
    if mode == "recitation":
        for base in (BASELINE, "nemo-rnnt"):
            if base not in per_engine:
                continue
            for eng, row in per_engine.items():
                if eng != base:
                    row[f"timing_vs_{base}"] = (
                        timing_agreement(per_engine[base]["onsets"], row["onsets"])
                        or "no common words"
                    )
    for row in per_engine.values():
        row.pop("onsets", None)
    results[clip] = per_engine

(BAKE / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False, indent=1))

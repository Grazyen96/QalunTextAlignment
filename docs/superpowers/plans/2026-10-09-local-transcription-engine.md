# Local Transcription Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make NVIDIA's FastConformer Arabic model, run locally through sherpa-onnx and downloaded once, the default transcription engine of Qalun and the CLI. WhisperX on Replicate stays available as a choice.

**Architecture:** `services/transcription.py::transcribe_audio()` stays the single entry point and dispatches to one of two engines:
- `services/engine_whisperx.py` (today's Replicate code, moved);
- `services/engine_local.py` (sherpa-onnx, fed by an incremental FFmpeg decode and a pause cutter).

Both return the WhisperX raw JSON shape, so nothing downstream changes. `services/model_store.py` downloads a pinned, checksummed model archive from a public GitHub release on first use.

**Tech Stack:** Python 3.10+, numpy, sherpa-onnx (onnxruntime inside), FFmpeg/ffprobe (already bundled), PySide6, pytest. Developer-only: NeMo, onnx and onnxruntime, for the one-off export.

**Spec:** `docs/superpowers/specs/2026-10-09-local-transcription-engine-design.md`. Read it first. It records why each decision was made.

## Global Constraints

- Output of every engine is the WhisperX raw shape: `{"segments": [{"start", "end", "text", "words": [{"word", "start", "end", "score"}]}], "detected_language": "ar"}`.
- Engines are named exactly `local` and `whisperx`. The env var is `QURANTEXT_TRANSCRIBE_ENGINE`, the CLI flag is `--engine`, and the GUI preference key is `engine`.
- Default engine: `whisperx` until Task 3.4, then `local`.
- There is no automatic fallback between engines. Audio is uploaded only when the engine is `whisperx`.
- The WhisperX cache key stays byte-for-byte `{"model": <model_ref>, **settings.whisperx.input_kwargs()}`.
- The local cache key is `{"engine": "local", "model": <manifest.ref>, "manifest": <manifest.digest()>}`.
- The model is fetched only from the URL pinned in `model_store.LOCAL_MODEL`, and verified by SHA-256 before use.
- Model hosting: the public repo `Grazyen96/qalun-models`, release tag `model-v1`. The app repo is private.
- Local engine windows: at most 28 s each, cut at the quietest 100 ms frame within the window's last 10 s.
- Word end = the next word's start, capped at the last token's time + 0.5 s. The last word is capped at the window's end. An end is never before its start.
- Recogniser threads: `max(1, os.cpu_count() - 2)`.
- No telemetry: the app sends nothing except the model download.
- Model licence: CC-BY-4.0. Attribution goes in `THIRD_PARTY_NOTICES.md`, the doctor report, and the model release.
- App licence (decided 2026-10-10, because the bundled sherpa-onnx links GPL-3.0 espeak-ng): Qalun is GPL-3.0-only, Copyright (C) 2026 Khalil, and each release attaches `qalun-source-<tag>.zip` of the tagged commit.
- Code style: ruff `B, E, F, I, UP, PLE2502`, line length 100, `ruff format`. Python files under `prototypes/` are excluded from ruff and CI.
- Strings shown in the window go through `qurantext.gui.i18n.t()`, with both English and Arabic entries.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Process (the user's standing preference): no per-task reviews. At the end of each phase, one whole-branch review and one fix pass, then merge locally.

## Conventions used below

- `venv/bin/python -m pytest`: the project's test runner (the project venv is `./venv`).
- `BAKE`: the bake-off working directory with the per-engine transcripts. In this session it is
  `/tmp/claude-1000/-home-khalil-PycharmProjects-QuranText/ea640bee-253a-4697-9741-210d77dd8806/scratchpad/bake`.
  If it is gone, rebuild it with `prototypes/asr_bakeoff/README.md`. The NeMo
  environment is `$BAKE/venv-nemo`, and the clip list is
  `venv/bin/python prototypes/asr_bakeoff/score.py --list`.
- Before any job expected to use more than 1 GB of RAM, run `free -m`. If
  "available" is under twice the need, ask the user to close something first.
  This laptop has been OOM-killed before.

## Review Focus

These are input classes the spec implies but no obvious test covers. Each now has a test in the task named.

1. **A redirecting download URL.** GitHub release assets answer with a 302 to another host, and the download must follow it. Test: Task 2.1, `test_follows_a_redirect`.
2. **File names that are Arabic and contain spaces** (`الفرقان 71 77.mp3`). FFmpeg must get the path as one argument. Test: Task 3.3, `test_reads_an_arabic_path_with_spaces`.
3. **Audio with no speech** (silence, or music only). There should be no crash, and the output should be zero segments. Tests: Task 3.1 `test_silence_only_audio_is_one_window_per_28s` and Task 3.3 `test_windows_without_tokens_add_no_segment`.
4. **Stereo 44.1 kHz audio inside a video container (.mp4/.m4a).** The engine must still get 16 kHz mono. Test: Task 3.3, `test_decodes_stereo_44k_m4a_to_16k_mono`.
5. **A job cancelled during transcription must not leave a cached transcript behind**, or the next run would return a partial result. Test: Task 3.4, `test_cancelled_local_run_caches_nothing`.

---

## Phase 0: Parity gate (stop here if it fails)

### Task 0.1: Export tool: NeMo checkpoint → sherpa-onnx files → release archive

**Files:**
- Create: `tools/export_local_model/export.py`
- Create: `tools/export_local_model/package.py`
- Create: `tools/export_local_model/NOTICE.md`
- Create: `tools/export_local_model/README.md`

**Interfaces:**
- Produces:
  - `export.py --out-dir DIR` writes `DIR/fp32/{encoder,decoder,joiner}.onnx`, `DIR/int8/{encoder,decoder,joiner}.onnx` (the int8 files already renamed to the plain names) and `tokens.txt` in both folders.
  - `package.py --variant-dir DIR/int8 --version int8-1 --out-dir OUT` writes:
    - `OUT/stt_ar_fastconformer_hybrid_large_pcd_v1.0-int8-1.tar.bz2`, flat, holding the four model files plus `NOTICE.md`;
    - `OUT/manifest.json`;
    - `OUT/manifest_literal.py.txt`, a ready-to-paste `ModelManifest(...)` literal used in Task 2.2.

This task has no pytest tests. The tool runs only in the NeMo environment and is verified by running it (Step 5).

- [ ] **Step 1: Write `tools/export_local_model/export.py`**

```python
#!/usr/bin/env python3
"""Export NVIDIA's FastConformer Arabic to the files sherpa-onnx loads.

Developer-only. It runs in a NeMo environment (see README.md), never in the app.
It is adapted from sherpa-onnx's
scripts/nemo/fast-conformer-hybrid-transducer-ctc/export-onnx-transducer-non-streaming.py.
The transducer (RNNT) branch only: the bake-off found the CTC head times words
far worse.
"""

import argparse
import shutil
from pathlib import Path

import nemo.collections.asr as nemo_asr
import onnx
import torch
from onnxruntime.quantization import QuantType, quantize_dynamic

MODEL = "nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0"
PARTS = ("encoder", "decoder", "joiner")


def add_meta_data(filename: Path, meta_data: dict) -> None:
    model = onnx.load(str(filename))
    while len(model.metadata_props):
        model.metadata_props.pop()
    for key, value in meta_data.items():
        meta = model.metadata_props.add()
        meta.key = key
        meta.value = str(value)
    onnx.save(model, str(filename))


@torch.no_grad()
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args()
    fp32 = args.out_dir / "fp32"
    int8 = args.out_dir / "int8"
    fp32.mkdir(parents=True, exist_ok=True)
    int8.mkdir(parents=True, exist_ok=True)

    model = nemo_asr.models.ASRModel.from_pretrained(model_name=MODEL)
    with open(fp32 / "tokens.txt", "w", encoding="utf-8") as f:
        for i, s in enumerate(model.joint.vocabulary):
            f.write(f"{s} {i}\n")
        f.write(f"<blk> {i + 1}\n")

    model.change_decoding_strategy(decoder_type="rnnt")
    model.eval()
    model.set_export_config({"decoder_type": "rnnt"})
    model.encoder.export(str(fp32 / "encoder.onnx"))
    model.decoder.export(str(fp32 / "decoder.onnx"))
    model.joint.export(str(fp32 / "joiner.onnx"))

    normalize_type = model.cfg.preprocessor.normalize
    add_meta_data(
        fp32 / "encoder.onnx",
        {
            "vocab_size": model.decoder.vocab_size,
            "normalize_type": "" if normalize_type == "NA" else normalize_type,
            "pred_rnn_layers": model.decoder.pred_rnn_layers,
            "pred_hidden": model.decoder.pred_hidden,
            "subsampling_factor": 8,
            "model_type": "EncDecHybridRNNTCTCBPEModel",
            "version": "1",
            "model_author": "NeMo",
            "url": f"https://huggingface.co/{MODEL}",
            "comment": "Only the transducer branch is exported",
        },
    )

    for part in PARTS:
        quantize_dynamic(
            model_input=str(fp32 / f"{part}.onnx"),
            model_output=str(int8 / f"{part}.onnx"),
            weight_type=QuantType.QUInt8,
        )
    shutil.copy(fp32 / "tokens.txt", int8 / "tokens.txt")
    for folder in (fp32, int8):
        sizes = {p.name: p.stat().st_size for p in sorted(folder.iterdir())}
        print(folder, sizes)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write `tools/export_local_model/NOTICE.md`**

```markdown
# Speech recognition model

Qalun transcribes on your computer with **NVIDIA FastConformer Hybrid Large
(Arabic)**, `stt_ar_fastconformer_hybrid_large_pcd_v1.0`, © NVIDIA Corporation.

- Source: https://huggingface.co/nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0
- Licence: Creative Commons Attribution 4.0 International (CC BY 4.0),
  https://creativecommons.org/licenses/by/4.0/
- Changes made: converted to ONNX for sherpa-onnx (transducer branch only) and,
  for the int8 build, weights quantised to 8 bits.

The model is provided "as is", without warranties of any kind.
```

- [ ] **Step 3: Write `tools/export_local_model/package.py`** (standard library only)

```python
#!/usr/bin/env python3
"""Pack one exported variant into the release archive and print its pinned manifest."""

import argparse
import hashlib
import json
import shutil
import tarfile
from pathlib import Path

MODEL_ID = "nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0"
RELEASE_URL = "https://github.com/Grazyen96/qalun-models/releases/download/model-v1"
FILES = ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt", "NOTICE.md")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant-dir", required=True, type=Path)
    ap.add_argument("--version", required=True)  # e.g. int8-1
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(__file__).with_name("NOTICE.md"), args.variant_dir / "NOTICE.md")

    name = f"{MODEL_ID.split('/')[1]}-{args.version}.tar.bz2"
    archive = args.out_dir / name
    with tarfile.open(archive, "w:bz2") as tar:
        for file in FILES:
            tar.add(args.variant_dir / file, arcname=file)  # flat: no folders

    files = [
        {"name": f, "size": (args.variant_dir / f).stat().st_size, "sha256": sha256(args.variant_dir / f)}
        for f in FILES
    ]
    manifest = {
        "model_id": MODEL_ID,
        "version": args.version,
        "url": f"{RELEASE_URL}/{name}",
        "archive_size": archive.stat().st_size,
        "archive_sha256": sha256(archive),
        "files": files,
    }
    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    lines = [
        "LOCAL_MODEL = ModelManifest(",
        f'    model_id="{MODEL_ID}",',
        f'    version="{args.version}",',
        f'    url="{manifest["url"]}",',
        f"    archive_size={manifest['archive_size']},",
        f'    archive_sha256="{manifest["archive_sha256"]}",',
        "    files=(",
        *[f'        ModelFile("{f["name"]}", {f["size"]}, "{f["sha256"]}"),' for f in files],
        "    ),",
        ")",
    ]
    (args.out_dir / "manifest_literal.py.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write `tools/export_local_model/README.md`**

````markdown
# Exporting the local speech model

Developer-only, once per model version. The app never runs this.

```bash
python3 -m venv /tmp/venv-nemo
/tmp/venv-nemo/bin/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
/tmp/venv-nemo/bin/pip install "nemo_toolkit[asr]" onnx onnxruntime
/tmp/venv-nemo/bin/python tools/export_local_model/export.py --out-dir /tmp/qalun-export
python3 tools/export_local_model/package.py --variant-dir /tmp/qalun-export/int8 \
    --version int8-1 --out-dir /tmp/qalun-release
```

`/tmp/qalun-release` then holds the archive to upload to the `model-v1` release
of `Grazyen96/qalun-models`, together with `NOTICE.md`. It also holds
`manifest_literal.py.txt`, which is pasted over `LOCAL_MODEL` in
`src/qurantext/services/model_store.py`. A new model version is a new
`--version`, a new release asset and a new pinned literal. Never replace an
asset in place: installed apps verify against the old checksum.
````

- [ ] **Step 5: Run the export in the bake-off NeMo env**

```bash
free -m | sed -n 2p     # needs ~4 GB available
$BAKE/venv-nemo/bin/pip install -q onnx onnxruntime
HF_HOME=$BAKE/hf $BAKE/venv-nemo/bin/python tools/export_local_model/export.py --out-dir $BAKE/export
ls -la $BAKE/export/fp32 $BAKE/export/int8
```

Expected: both folders hold `encoder.onnx decoder.onnx joiner.onnx tokens.txt`, with fp32 at about 450 MB and int8 at about 120 MB in total. If `export()` fails on the hybrid model's `set_export_config`, read the NeMo error, fix the call to match the installed NeMo 3.0 API, and record the change in the README.

- [ ] **Step 6: Lint and commit**

```bash
venv/bin/ruff check tools && venv/bin/ruff format --check tools
git add tools/export_local_model
git commit -m "Add the developer tool that exports NVIDIA's Arabic FastConformer for sherpa-onnx and packs the release archive

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

If ruff reports `nemo`/`onnx` as unresolved imports, that is fine: ruff does not resolve third-party imports. Fix only real findings.

### Task 0.2: sherpa-onnx runner and gate scoring in the bake-off harness

**Files:**
- Create: `prototypes/asr_bakeoff/run_sherpa.py`
- Create: `prototypes/asr_bakeoff/gate.py`
- Modify: `prototypes/asr_bakeoff/score.py` (`timing_agreement` returns `paired`; every engine is timed against `nemo-rnnt`; add `end_violations`)
- Modify: `prototypes/asr_bakeoff/README.md`

**Interfaces:**
- Consumes: `$BAKE/export/{fp32,int8}` from Task 0.1, and `common.py` (`load_audio`, `chunk_at_pauses`, `write_whisperx_json`).
- Produces:
  - `run_sherpa.py AUDIO OUT.json --model-dir DIR --label sherpa-int8` writes the WhisperX raw shape.
  - `gate.py BAKE ENGINE` prints PASS/FAIL per spec §0 check, exiting 0 only when all pass.
  - The `tokens_to_words` algorithm here is the **reference** that Task 3.2 must reproduce exactly.

- [ ] **Step 1: Write `prototypes/asr_bakeoff/run_sherpa.py`**

```python
"""NVIDIA FastConformer Arabic through sherpa-onnx: the runtime the app will ship.

    python run_sherpa.py AUDIO OUT.json --model-dir DIR --label sherpa-int8
"""

import argparse
import os
import time

import sherpa_onnx

from common import SR, chunk_at_pauses, load_audio, write_whisperx_json

WORD_MARK = "▁"
MAX_TAIL = 0.5
PUNCT = frozenset(".,،؛;:!?؟\"'«»()[]-…")


def tokens_to_words(tokens, times, *, window_end, offset):
    pieces, pending = [], False
    for tok, t in zip(tokens, times, strict=True):
        starts = tok.startswith(WORD_MARK)
        text = tok.replace(WORD_MARK, "").strip()
        if not text:
            pending = pending or starts
            continue
        if all(ch in PUNCT for ch in text):
            if pieces:
                pieces[-1][0] += text
            continue
        if starts or pending or not pieces:
            pieces.append([text, t, t])
            pending = False
        else:
            pieces[-1][0] += text
            pieces[-1][2] = t
    words = []
    for i, (text, start, last) in enumerate(pieces):
        nxt = pieces[i + 1][1] if i + 1 < len(pieces) else window_end
        end = max(start, min(nxt, last + MAX_TAIL))
        words.append(
            {"word": text, "start": round(offset + start, 3), "end": round(offset + end, 3), "score": 1.0}
        )
    return words


ap = argparse.ArgumentParser()
ap.add_argument("audio")
ap.add_argument("out")
ap.add_argument("--model-dir", required=True)
ap.add_argument("--label", required=True)
args = ap.parse_args()

d = args.model_dir
recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
    encoder=f"{d}/encoder.onnx",
    decoder=f"{d}/decoder.onnx",
    joiner=f"{d}/joiner.onnx",
    tokens=f"{d}/tokens.txt",
    num_threads=max(1, (os.cpu_count() or 1) - 2),
    sample_rate=SR,
    feature_dim=80,
    decoding_method="greedy_search",
    model_type="nemo_transducer",
)

audio = load_audio(args.audio)
windows = list(chunk_at_pauses(audio))
t0 = time.time()
segments = []
for i in range(0, len(windows), 4):
    batch = windows[i : i + 4]
    streams = []
    for a, b in batch:
        s = recognizer.create_stream()
        s.accept_waveform(SR, audio[a:b])
        streams.append(s)
    recognizer.decode_streams(streams)
    for (a, b), s in zip(batch, streams, strict=True):
        r = s.result
        words = tokens_to_words(
            list(r.tokens), list(r.timestamps), window_end=(b - a) / SR, offset=a / SR
        )
        if words:
            segments.append(
                {
                    "start": words[0]["start"],
                    "end": words[-1]["end"],
                    "text": " ".join(w["word"] for w in words),
                    "words": words,
                }
            )
t_asr = time.time() - t0
write_whisperx_json(
    segments,
    args.out,
    {"engine": args.label, "model_dir": d, "audio_s": round(len(audio) / SR, 1), "asr_s": round(t_asr, 1)},
)
print(f"{args.audio}: {sum(len(s['words']) for s in segments)} words, asr {t_asr:.0f}s")
```

- [ ] **Step 2: Change `timing_agreement` in `score.py`** to also return the paired count as an int, and time every engine against `nemo-rnnt`

In `score.py`, inside `timing_agreement`, add `"paired": len(pairs),` as the first key of the returned dict.

Replace the block that starts `if mode == "recitation" and BASELINE in per_engine:` and ends at the `cohere` special case with:

```python
    if mode == "recitation":
        for ref in (BASELINE, "nemo-rnnt"):
            if ref not in per_engine:
                continue
            for eng, row in per_engine.items():
                if eng != ref:
                    row[f"timing_vs_{ref}"] = (
                        timing_agreement(per_engine[ref]["onsets"], row["onsets"])
                        or "no common words"
                    )
```

- [ ] **Step 3: Add end-time violations to `score.py`**

Add this function above `engines = sorted(...)`:

```python
def end_violations(raw: dict) -> int:
    """Words whose end is before their start, or after the next word's start."""
    words = [w for s in raw["segments"] for w in s.get("words", [])]
    bad = sum(1 for w in words if w["end"] < w["start"])
    bad += sum(1 for a, b in zip(words, words[1:]) if a["end"] > b["start"] + 1e-6)
    return bad
```

In the per-engine loop, after `row = {...}`, add `row["end_violations"] = end_violations(raw)`.

- [ ] **Step 4: Write `prototypes/asr_bakeoff/gate.py`**

```python
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
```

The per-clip timing check is at least as strict as the spec's "over all recitation words".

- [ ] **Step 5: Document the runner in `prototypes/asr_bakeoff/README.md`**

Add a row to the runner table:

```
| `run_sherpa.py` | the same NVIDIA model through sherpa-onnx (`--model-dir` from `tools/export_local_model`) | the model's own token times, grouped into words |
```

Add under "Running":

```
`gate.py $BAKE <engine>` checks an engine against spec §0 of the local
transcription engine design (exit 0 = pass).
```

- [ ] **Step 6: Commit**

```bash
git add prototypes/asr_bakeoff
git commit -m "Add a sherpa-onnx runner and the parity gate to the ASR bake-off

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 0.3: Run the gate and record the decision

**Files:**
- Modify: `docs/findings/asr-bakeoff.md` (new section "sherpa-onnx parity")

**Interfaces:**
- Produces: the shipping variant (`int8` or `fp32`) and the exact sherpa-onnx version that passed. Tasks 2.2 and 3.4 use both.

- [ ] **Step 1: Build the sherpa venv and run both variants on all 17 clips**

```bash
python3 -m venv $BAKE/venv-sherpa && $BAKE/venv-sherpa/bin/pip install -q sherpa-onnx numpy soundfile
$BAKE/venv-sherpa/bin/python -c "import sherpa_onnx; print(sherpa_onnx.__version__)"   # record this
venv/bin/python prototypes/asr_bakeoff/score.py --list > $BAKE/clips.tsv
cd prototypes/asr_bakeoff
for v in int8 fp32; do
  while IFS=$'\t' read -r clip audio; do
    $BAKE/venv-sherpa/bin/python run_sherpa.py "$audio" $BAKE/sherpa-$v/$clip.json \
      --model-dir $BAKE/export/$v --label sherpa-$v < /dev/null
  done < $BAKE/clips.tsv
done
cd ../..
```

Expected: 17 JSON files in each of `$BAKE/sherpa-int8` and `$BAKE/sherpa-fp32`, each recitation running far faster than real time.

- [ ] **Step 2: Pre-run the slow matchers in parallel, then score**

The scorer matches serially, and a full-surah recitation takes about 16 minutes. Run the matches six at a time first; `score.py` then reuses them.

```bash
for eng in sherpa-int8 sherpa-fp32; do while IFS=$'\t' read -r clip audio; do
  case $clip in lecture*) m=lecture;; *) m=recitation;; esac
  printf '%s\t%s\t%s\n' $m $BAKE/$eng/$clip.json $BAKE/$eng/${clip}_${m}_match.json
done < $BAKE/clips.tsv; done > $BAKE/todo.tsv
tr '\n' '\0' < $BAKE/todo.tsv | xargs -0 -P 6 -I{} bash -c 'IFS=$'"'"'\t'"'"' read -r m raw out <<< "{}"; [ -f "$out" ] || venv/bin/qurantext $m-match --whisperx-json "$raw" --output "$out" > /dev/null 2>&1'
venv/bin/python prototypes/asr_bakeoff/score.py $BAKE > $BAKE/score.log
```

- [ ] **Step 3: Run the gate for each variant**

```bash
venv/bin/python prototypes/asr_bakeoff/gate.py $BAKE sherpa-int8; echo "int8 exit $?"
venv/bin/python prototypes/asr_bakeoff/gate.py $BAKE sherpa-fp32; echo "fp32 exit $?"
```

Decision:
- **int8 exits 0:** ship int8.
- **Only fp32 exits 0:** ship fp32, and change "about 120 MB" to "about 450 MB" wherever it appears (spec §4, the i18n strings in Task 4.1, and the doctor text in Task 4.3).
- **Neither exits 0:** STOP. Report the failing checks to the user and do not start Phase 1.

If only the word-end check fails, look at the violating words first. A tokens-to-words bug is fixable in Task 0.2's function, which must then be mirrored in Task 3.2.

- [ ] **Step 4: Record the result in `docs/findings/asr-bakeoff.md`**

Add a section after "Extended test", in this form, filled in from the gate output:

```markdown
## sherpa-onnx parity (Phase 0 of the local engine)

The model exported with `tools/export_local_model` and run through sherpa-onnx
<version> on the same 17 clips, checked against NeMo RNNT by `gate.py`:

| Check | int8 | fp32 |
|---|---|---|
| ... one row per gate line, with its detail ... |

**Shipping:** <int8|fp32> (<size> download).
```

- [ ] **Step 5: Commit, then run the phase-end review**

```bash
git add docs/findings/asr-bakeoff.md
git commit -m "Record that sherpa-onnx reproduces the NeMo results, and which model variant ships

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Phase-end review: one whole-branch review of Phase 0, one fix pass, then merge locally.

---

## Phase 1: Engine seam (behaviour unchanged; WhisperX stays the default)

### Task 1.1: Shared errors, neutral result type, Replicate code moved out

**Files:**
- Create: `src/qurantext/services/errors.py`
- Create: `src/qurantext/services/engine_whisperx.py`
- Modify: `src/qurantext/services/transcription.py`
- Modify: `tests/test_transcription.py`, `tests/test_transcript_cache.py` (patch targets move)
- Test: `tests/test_transcription.py`

**Interfaces:**
- Produces:
  - `errors.TranscriptionError(RuntimeError)`, and its subclasses `WhisperXServiceError`, `ModelDownloadError` and `LocalEngineError`, plus `ModelLoadError(LocalEngineError)`.
  - `engine_whisperx.run_whisperx(audio: Path, settings: AppSettings, model_ref: str) -> dict | list`
  - `engine_whisperx.cache_settings(settings: AppSettings, model_ref: str) -> dict`
  - `transcription.TranscriptionResult` (fields: `output, audio_path, raw_output_path, model_ref, segment_count, word_count, from_cache=False, engine="whisperx"`), and the alias `WhisperXResult = TranscriptionResult`.
  - `transcription` re-exports `TranscriptionError` and `WhisperXServiceError`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_transcription.py`)

```python
def test_every_transcription_error_shares_one_base() -> None:
    from qurantext.services.errors import (
        LocalEngineError,
        ModelDownloadError,
        ModelLoadError,
        TranscriptionError,
        WhisperXServiceError,
    )

    for cls in (WhisperXServiceError, ModelDownloadError, LocalEngineError, ModelLoadError):
        assert issubclass(cls, TranscriptionError)
    assert issubclass(ModelLoadError, LocalEngineError)
    assert issubclass(TranscriptionError, RuntimeError)


def test_old_names_still_import_from_transcription() -> None:
    from qurantext.services import errors, transcription

    assert transcription.WhisperXServiceError is errors.WhisperXServiceError
    assert transcription.WhisperXResult is transcription.TranscriptionResult


def test_result_records_its_engine() -> None:
    from qurantext.services.transcription import TranscriptionResult

    result = TranscriptionResult(
        output={}, audio_path="a", raw_output_path=None, model_ref="m",
        segment_count=0, word_count=0,
    )
    assert result.engine == "whisperx"
    assert result.from_cache is False
```

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/bin/python -m pytest tests/test_transcription.py -q -k "base or old_names or records"`
Expected: FAIL with `ModuleNotFoundError: No module named 'qurantext.services.errors'`.

- [ ] **Step 3: Create `src/qurantext/services/errors.py`**

```python
"""Errors a transcription can end in, under one base the CLI and the window catch."""

from __future__ import annotations

__all__ = [
    "LocalEngineError",
    "ModelDownloadError",
    "ModelLoadError",
    "TranscriptionError",
    "WhisperXServiceError",
]


class TranscriptionError(RuntimeError):
    """A transcription could not complete. The message says what to do about it."""


class WhisperXServiceError(TranscriptionError):
    """Raised when the WhisperX transcription service cannot complete successfully."""


class ModelDownloadError(TranscriptionError):
    """The local speech model could not be downloaded or failed its checksum."""


class LocalEngineError(TranscriptionError):
    """The local engine failed while reading the audio or recognising it."""


class ModelLoadError(LocalEngineError):
    """The local model's files are there but the recogniser could not load them."""
```

- [ ] **Step 4: Create `src/qurantext/services/engine_whisperx.py`**

Move these from `transcription.py` **unchanged**:
- `_TRANSIENT_STATUS_CODES`, `_POLL_INTERVAL_SECONDS`, `_MAX_TRANSIENT_RETRIES`;
- `_transient_status`, `_create_prediction`, `_await_prediction_output`.

Their docstrings and comments move with them. Then add:

```python
"""WhisperX on Replicate: the online engine.

Moved unchanged from ``transcription.py`` when a second, local engine arrived.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from qurantext.config.settings import AppSettings
from qurantext.services.errors import WhisperXServiceError

# ... the moved constants and three functions go here, unchanged ...


def cache_settings(settings: AppSettings, model_ref: str) -> dict[str, Any]:
    """The settings that shape a WhisperX transcript. Unchanged, so old cache entries still hit."""
    return {"model": model_ref, **settings.whisperx.input_kwargs()}


def run_whisperx(audio_file_path: Path, settings: AppSettings, model_ref: str) -> Any:
    """Upload *audio_file_path* to Replicate and return WhisperX's raw output."""
    if not settings.replicate_api_token:
        from qurantext.config.paths import user_data_dir

        raise WhisperXServiceError(
            "No Replicate API token is set, so audio cannot be transcribed.\n"
            f"Create a file named .env in {user_data_dir()} containing one line:\n"
            "  REPLICATE_API_TOKEN=your-token\n"
            "Get a token from https://replicate.com/account/api-tokens, then "
            "restart the app — settings are read once at startup."
        )
    try:
        import replicate

        client = replicate.Client(api_token=settings.replicate_api_token)
        with audio_file_path.open("rb") as audio_file:
            prediction = _create_prediction(
                client,
                model_ref,
                {**settings.whisperx.input_kwargs(), "audio_file": audio_file},
            )
        # Poll after the file handle is closed — the audio is already uploaded.
        return _await_prediction_output(prediction)
    except WhisperXServiceError:
        raise
    except Exception as error:
        # ... the existing 401 / 404 / generic mapping from transcribe_audio, unchanged,
        # with `resolved_model_ref` renamed to `model_ref` ...
        raise WhisperXServiceError(f"WhisperX transcription failed: {error}") from error
```

The `except Exception` body is the existing 401/404/generic block from `transcribe_audio`, copied verbatim. The only change is `resolved_model_ref` → `model_ref`.

- [ ] **Step 5: Slim `transcription.py` down to the entry point**

Keep `_count_segments`, `_count_words`, `_normalize_output_for_json` and `save_raw_output`. Replace the rest (the imports, the dataclass and `transcribe_audio`) with:

```python
from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any

from qurantext.config.settings import DEFAULT_MODEL_REF, get_settings
from qurantext.io.writers import write_json
from qurantext.services import engine_whisperx
from qurantext.services.errors import TranscriptionError, WhisperXServiceError
from qurantext.services.transcript_cache import cache_key, load_cached, store_cached

__all__ = [
    "TranscriptionError",
    "TranscriptionResult",
    "WhisperXResult",
    "WhisperXServiceError",
    "save_raw_output",
    "transcribe_audio",
]


@dataclass(slots=True)
class TranscriptionResult:
    """Structured result returned by :func:`transcribe_audio`."""

    output: dict | list
    audio_path: str
    raw_output_path: str | None
    model_ref: str
    segment_count: int
    word_count: int
    #: True when the result came from the cache and nothing was sent anywhere.
    from_cache: bool = False
    #: Which engine produced the transcript: "whisperx" or "local".
    engine: str = "whisperx"


#: The name this type had while WhisperX was the only engine.
WhisperXResult = TranscriptionResult

# ... _count_segments, _count_words, _normalize_output_for_json, save_raw_output unchanged ...


def transcribe_audio(
    audio_path: str | PathLike[str],
    *,
    save_raw_to: str | PathLike[str] | None = None,
    model_ref: str | None = None,
    use_cache: bool = True,
) -> TranscriptionResult:
    """Transcribe an audio file with WhisperX on Replicate.

    The same audio with the same settings always gives the same transcript, so
    the result is cached against the audio's content. A repeat run — correcting
    one subtitle line and rendering again, say — costs nothing and needs no
    network. Pass ``use_cache=False`` to force a fresh call.
    """
    audio_file_path = Path(audio_path)
    if not audio_file_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

    settings = get_settings()
    resolved_model_ref = model_ref or settings.whisperx.model_ref or DEFAULT_MODEL_REF
    key_settings = engine_whisperx.cache_settings(settings, resolved_model_ref)
    return _transcribe_cached(
        audio_file_path,
        key_settings=key_settings,
        model_ref=resolved_model_ref,
        engine="whisperx",
        run=lambda: engine_whisperx.run_whisperx(audio_file_path, settings, resolved_model_ref),
        save_raw_to=save_raw_to,
        use_cache=use_cache,
    )


def _transcribe_cached(
    audio_file_path: Path,
    *,
    key_settings: dict[str, Any],
    model_ref: str,
    engine: str,
    run,
    save_raw_to: str | PathLike[str] | None,
    use_cache: bool,
) -> TranscriptionResult:
    """Cache lookup, run, cache store and save: the same for every engine."""
    key = cache_key(audio_file_path, key_settings) if use_cache else None
    if key is not None:
        cached = load_cached(key)
        if cached is not None:
            raw_output_path = (
                save_raw_output(cached, save_raw_to) if save_raw_to is not None else None
            )
            return TranscriptionResult(
                output=cached,
                audio_path=str(audio_file_path),
                raw_output_path=raw_output_path,
                model_ref=model_ref,
                segment_count=_count_segments(cached),
                word_count=_count_words(cached),
                from_cache=True,
                engine=engine,
            )

    output = run()

    if key is not None:
        store_cached(key, _normalize_output_for_json(output))
    raw_output_path: str | None = None
    if save_raw_to is not None:
        try:
            raw_output_path = save_raw_output(output, save_raw_to)
        except Exception as error:
            raise TranscriptionError(
                f"Transcription succeeded, but saving raw output failed: {error}"
            ) from error
    return TranscriptionResult(
        output=_normalize_output_for_json(output),
        audio_path=str(audio_file_path),
        raw_output_path=raw_output_path,
        model_ref=model_ref,
        segment_count=_count_segments(output),
        word_count=_count_words(output),
        engine=engine,
    )
```

- [ ] **Step 6: Point the existing tests at the moved code**

In `tests/test_transcription.py`:
- the import block becomes `from qurantext.services import engine_whisperx` and `from qurantext.services.engine_whisperx import WhisperXServiceError, _await_prediction_output, _transient_status`;
- every `monkeypatch.setattr(transcription.time, "sleep", ...)` becomes `monkeypatch.setattr(engine_whisperx.time, "sleep", ...)`;
- in `TestRejectedToken._run`, patch `engine_whisperx` instead (`from qurantext.services import engine_whisperx` then `monkeypatch.setattr(engine_whisperx, "_create_prediction", ...)`).

In `tests/test_transcript_cache.py`, the two `monkeypatch.setattr(transcription, "_create_prediction", ...)` become `monkeypatch.setattr(engine_whisperx, "_create_prediction", ...)`, after `from qurantext.services import engine_whisperx`.

- [ ] **Step 7: Run the whole suite**

Run: `venv/bin/python -m pytest -q`
Expected: all pass, including the three new tests. Then run `venv/bin/ruff check . && venv/bin/ruff format --check .`.

- [ ] **Step 8: Commit**

```bash
git add src/qurantext/services tests/test_transcription.py tests/test_transcript_cache.py
git commit -m "Move the Replicate code into its own engine module, and give transcription one error base and a neutral result type

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 1.2: The engine setting and the `engine` / `progress` / `cancel` arguments

**Files:**
- Modify: `src/qurantext/config/settings.py` (add `TranscriptionSettings`, `DEFAULT_TRANSCRIBE_ENGINE`, and an `AppSettings.transcription` field)
- Modify: `src/qurantext/config/__init__.py` (export `TranscriptionSettings`)
- Modify: `src/qurantext/services/transcription.py`
- Test: `tests/test_transcription.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `TranscriptionResult` and `_transcribe_cached` from Task 1.1.
- Produces:
  - `settings.ENGINES = ("local", "whisperx")` and `settings.DEFAULT_TRANSCRIBE_ENGINE = "whisperx"` (Task 3.4 changes it to `"local"`);
  - `AppSettings.transcription.engine: str`;
  - `transcription.resolve_engine(engine: str | None, settings: AppSettings) -> str`, which raises `ValueError` for unknown names;
  - `transcription.ENGINE_LABELS: dict[str, str]`;
  - `transcribe_audio(..., engine: str | None = None, progress: ProgressCallback | None = None, cancel: CancelToken | None = None)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_transcription_engine_defaults_and_reads_the_environment(monkeypatch) -> None:
    from qurantext.config.settings import DEFAULT_TRANSCRIBE_ENGINE, get_settings

    monkeypatch.delenv("QURANTEXT_TRANSCRIBE_ENGINE", raising=False)
    get_settings.cache_clear()
    assert get_settings().transcription.engine == DEFAULT_TRANSCRIBE_ENGINE
    monkeypatch.setenv("QURANTEXT_TRANSCRIBE_ENGINE", "local")
    get_settings.cache_clear()
    assert get_settings().transcription.engine == "local"
    get_settings.cache_clear()
```

Append to `tests/test_transcription.py`:

```python
class TestEngineChoice:
    def test_an_explicit_engine_wins_over_the_setting(self, monkeypatch) -> None:
        from qurantext.config.settings import get_settings
        from qurantext.services.transcription import resolve_engine

        monkeypatch.setenv("QURANTEXT_TRANSCRIBE_ENGINE", "local")
        get_settings.cache_clear()
        assert resolve_engine("whisperx", get_settings()) == "whisperx"
        assert resolve_engine(None, get_settings()) == "local"
        get_settings.cache_clear()

    def test_an_unknown_engine_names_the_choices(self, monkeypatch) -> None:
        from qurantext.config.settings import get_settings
        from qurantext.services.transcription import resolve_engine

        with pytest.raises(ValueError, match="local.*whisperx"):
            resolve_engine("cohere", get_settings())

    def test_the_whisperx_cache_key_is_unchanged(self, monkeypatch, tmp_path) -> None:
        """Existing cached transcripts must keep hitting after the engine seam."""
        from qurantext.config.settings import get_settings
        from qurantext.services import engine_whisperx

        settings = get_settings()
        assert engine_whisperx.cache_settings(settings, "m") == {
            "model": "m",
            **settings.whisperx.input_kwargs(),
        }

    def test_progress_and_cancel_are_accepted(self, monkeypatch, tmp_path) -> None:
        from qurantext.config.settings import get_settings
        from qurantext.services import engine_whisperx, transcription
        from qurantext.utils.progress import CancelToken

        audio = tmp_path / "a.wav"
        audio.write_bytes(b"RIFF....WAVE")
        monkeypatch.setenv("QURANTEXT_CACHE_DIR", str(tmp_path / "cache"))
        get_settings.cache_clear()
        monkeypatch.setattr(
            engine_whisperx, "run_whisperx", lambda *_a, **_k: {"segments": []}
        )
        result = transcription.transcribe_audio(
            audio, engine="whisperx", progress=lambda _e: None, cancel=CancelToken()
        )
        get_settings.cache_clear()
        assert result.engine == "whisperx"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/bin/python -m pytest tests/test_config.py tests/test_transcription.py -q -k "engine or cache_key_is or progress_and"`
Expected: FAIL (`AttributeError: ... 'transcription'` / `ImportError: resolve_engine`).

- [ ] **Step 3: Add the setting** in `src/qurantext/config/settings.py`

Next to the other defaults:

```python
#: The transcription engines, by the names the CLI, env and window use.
ENGINES = ("local", "whisperx")
DEFAULT_TRANSCRIBE_ENGINE = "whisperx"
```

Next to `WhisperXSettings`:

```python
@dataclass(frozen=True, slots=True)
class TranscriptionSettings:
    """Which engine transcribes. Validated where it is used, so a typo in the
    environment names the choices instead of stopping the app at startup."""

    engine: str
```

Add `transcription: TranscriptionSettings` to `AppSettings`, directly after its `whisperx` field. In the loader that builds `AppSettings`, pass:

```python
        transcription=TranscriptionSettings(
            engine=_env_str("QURANTEXT_TRANSCRIBE_ENGINE", DEFAULT_TRANSCRIBE_ENGINE).strip().lower()
        ),
```

Export `TranscriptionSettings` from `src/qurantext/config/__init__.py`, next to `WhisperXSettings`, in both the import and `__all__`.

- [ ] **Step 4: Add resolution and the new arguments** in `transcription.py`

```python
from qurantext.config.settings import ENGINES, AppSettings
from qurantext.utils.progress import CancelToken, ProgressCallback

#: How progress lines and messages name each engine.
ENGINE_LABELS = {"local": "the local model", "whisperx": "WhisperX on Replicate"}


def resolve_engine(engine: str | None, settings: AppSettings) -> str:
    """The engine to use: the explicit choice, else the setting."""
    value = (engine or settings.transcription.engine or "").strip().lower()
    if value not in ENGINES:
        raise ValueError(
            f"Unknown transcription engine {value!r}; choose 'local' or 'whisperx'."
        )
    return value
```

Change `transcribe_audio`'s signature to add `engine: str | None = None, progress: ProgressCallback | None = None, cancel: CancelToken | None = None`. After `settings = get_settings()`, add:

```python
    resolved_engine = resolve_engine(engine, settings)
    if resolved_engine == "local":
        from qurantext.services.errors import LocalEngineError

        raise LocalEngineError("The local engine is not part of this build yet.")
```

Update the docstring's first line to "Transcribe an audio file with the chosen engine (see :func:`resolve_engine`)." Task 3.4 replaces the `local` branch.

- [ ] **Step 5: Run the tests**

Run: `venv/bin/python -m pytest -q`
Expected: all pass. Then run `venv/bin/ruff check . && venv/bin/ruff format --check .`.

- [ ] **Step 6: Commit**

```bash
git add src/qurantext/config src/qurantext/services/transcription.py tests/test_config.py tests/test_transcription.py
git commit -m "Choose the transcription engine by argument or QURANTEXT_TRANSCRIBE_ENGINE, and let transcription take progress and cancel

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 1.3: Pass the engine, progress and cancel through the pipelines and the CLI

**Files:**
- Modify: `src/qurantext/pipelines/detection.py` (`run_recitation_range`, `run_detection`)
- Modify: `src/qurantext/pipelines/recitation.py` (`run_word_alignment`)
- Modify: `src/qurantext/cli/main.py`
- Modify: `tests/test_gui.py` (its fake `transcribe_audio` must accept the new keywords)
- Test: `tests/test_smoke.py` (CLI flag) and a new pipeline test in `tests/test_transcription.py`

**Interfaces:**
- Consumes: `transcribe_audio(..., engine, progress, cancel)`, `resolve_engine`, `ENGINE_LABELS` and `TranscriptionError` from Tasks 1.1–1.2.
- Produces:
  - `run_recitation_range(..., engine: str | None = None)` and `run_detection(..., engine: str | None = None)`;
  - `run_word_alignment(..., engine: str | None = None)`;
  - CLI `--engine {local,whisperx}` on `transcribe`, `word-align`, `range-match`, `lecture-match`, `recitation-match` and `run-all`;
  - match-file `meta["transcription_engine"]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_transcription.py`:

```python
def test_detection_passes_engine_progress_and_cancel(monkeypatch, tmp_path) -> None:
    from qurantext.config.paths import DEFAULT_QURAN_PATH
    from qurantext.pipelines import detection
    from qurantext.utils.progress import CancelToken

    seen = {}

    def fake(audio, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop after the call")

    monkeypatch.setattr(detection, "transcribe_audio", fake)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF....WAVE")
    token = CancelToken()
    with pytest.raises(RuntimeError, match="stop after the call"):
        detection.run_detection(
            quran=DEFAULT_QURAN_PATH, output=tmp_path / "m.json", mode="lecture",
            audio=audio, echo=False, engine="whisperx", cancel=token,
        )
    assert seen["engine"] == "whisperx"
    assert seen["cancel"] is token
    assert "progress" in seen
```

Append to `tests/test_smoke.py` (it already imports `build_parser`; add `import pytest` to its imports):

```python
def test_cli_offers_the_engine_choice(capsys) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["transcribe", "--help"])
    out = capsys.readouterr().out
    assert "--engine" in out and "local" in out and "whisperx" in out
```

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/bin/python -m pytest tests/test_transcription.py::test_detection_passes_engine_progress_and_cancel tests/test_smoke.py::test_cli_offers_the_engine_choice -q`
Expected: FAIL (`TypeError: run_detection() got an unexpected keyword argument 'engine'`, and no `--engine` in the help).

- [ ] **Step 3: Pipelines**

In `detection.py`, add `engine: str | None = None,` after `audio` in both `run_recitation_range` and `run_detection`. At both `transcribe_audio(...)` call sites (around lines 209 and 370), replace the emit-and-call pair with:

```python
        label = ENGINE_LABELS[resolve_engine(engine, get_settings())]
        emit(f"[2/3] Transcribing audio with {label}: {audio}")
        service_result = transcribe_audio(
            audio,
            save_raw_to=default_whisperx_raw_path(out_path),
            engine=engine,
            progress=progress,
            cancel=cancel,
        )
```

Keep each site's existing step number in the f-string. Then import `ENGINE_LABELS` and `resolve_engine` from `qurantext.services.transcription`, and `get_settings` if it isn't already imported.

Where each function builds `meta` (search `"whisperx_model_ref"` in `detection.py`), add `"transcription_engine": service_result.engine if service_result else None`. Follow the existing pattern for `whisperx_model_ref`: in the `--whisperx-json` branch the value is `None`.

In `recitation.py::run_word_alignment`, add `engine: str | None = None` to the signature and `engine=engine` to its `transcribe_audio(...)` call. Change the "No word timestamps were returned by the Replicate model" message to "No word timestamps were returned by the transcription."

- [ ] **Step 4: CLI**

In `cli/main.py`, add this helper next to the other argument helpers:

```python
def _add_engine_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--engine",
        choices=ENGINES,
        default=None,
        help="Transcription engine: 'local' runs on this computer, 'whisperx' uploads "
        "to Replicate. Defaults to QURANTEXT_TRANSCRIBE_ENGINE, else the built-in default.",
    )
```

Call `_add_engine_argument(...)` on `transcribe_parser`, `word_align_parser`, each `subparser` in the range/lecture/recitation loop, and `run_all_parser`.

Pass `engine=args.engine` at every call that can transcribe:
- `_run_transcribe` → `transcribe_audio(...)`;
- `_run_word_align` → `run_word_alignment(...)`;
- `_run_detection_mode` → both `run_recitation_range(...)` and `run_detection(...)`;
- `_run_all` → `run_detection(...)`.

In `_run_transcribe`, catch `(FileNotFoundError, TranscriptionError)` instead of `WhisperXServiceError`, and print `Saved the raw transcript to {result.raw_output_path}`. At the second catch site (search `WhisperXServiceError is a RuntimeError`), add `TranscriptionError` to the caught types the same way.

Import `ENGINES` from `qurantext.config.settings` and `TranscriptionError` from `qurantext.services.transcription`.

- [ ] **Step 5: Keep the GUI test's fake in step**

In `tests/test_gui.py`, the fake passed to `monkeypatch.setattr(detection, "transcribe_audio", fake_transcribe)` must accept the new keywords. Change its signature to `def fake_transcribe(audio_path, save_raw_to=None, **_kwargs):`, keeping its body.

- [ ] **Step 6: Run everything**

Run: `venv/bin/python -m pytest -q && venv/bin/ruff check . && venv/bin/ruff format --check .`
Expected: all pass.

- [ ] **Step 7: Commit, then run the phase-end review**

```bash
git add src/qurantext/pipelines src/qurantext/cli tests
git commit -m "Pass the engine choice, progress and cancel from the CLI and pipelines down to transcription

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Phase-end review: one whole-branch review of Phase 1, one fix pass, then merge locally.

---

## Phase 2: Model store and publishing the model

### Task 2.1: `model_store`: find, download, verify, unpack

**Files:**
- Create: `src/qurantext/services/model_store.py`
- Test: `tests/test_model_store.py`

**Interfaces:**
- Consumes: `errors.ModelDownloadError`, `utils.progress.{CancelToken, JobCancelled, ProgressCallback, report}`, `config.paths.user_cache_dir`.
- Produces:
  - `ModelFile(name: str, size: int, sha256: str)`
  - `ModelManifest(model_id, version, url, archive_size, archive_sha256, files)`, with:
    - `.ref -> str` (`"<model_id>@<version>"`);
    - `.folder_name -> str`;
    - `.unpacked_size -> int`;
    - `.digest() -> str`.
  - `models_dir() -> Path` and `model_dir(m) -> Path`
  - `is_installed(m) -> bool`, `verify_installed(m) -> bool`, `discard(m) -> None`
  - `ensure_model(m, *, progress=None, cancel=None) -> Path`
  - `LOCAL_MODEL` is added in Task 2.2. Progress events use stage `"download"`.

- [ ] **Step 1: Write the failing tests** (`tests/test_model_store.py`)

```python
from __future__ import annotations

import hashlib
import io
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qurantext.services import model_store
from qurantext.services.errors import ModelDownloadError
from qurantext.services.model_store import ModelFile, ModelManifest
from qurantext.utils.progress import CancelToken, JobCancelled

FILES = {"encoder.onnx": b"E" * 3000, "tokens.txt": "▁ق 0\n<blk> 1\n".encode()}


def _archive(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Server:
    """Serves /model.tar.bz2, and /redirect answering 302 to it, counting requests."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requests = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 — http.server's name
                outer.requests += 1
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/model.tar.bz2")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *_args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, path: str = "/model.tar.bz2") -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"

    def close(self) -> None:
        self.httpd.shutdown()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("QURANTEXT_CACHE_DIR", str(tmp_path / "cache"))
    return tmp_path / "cache"


@pytest.fixture
def server():
    s = _Server(_archive(FILES))
    yield s
    s.close()


def _manifest(server, *, url=None, archive_sha=None, files=None) -> ModelManifest:
    body = server.body
    return ModelManifest(
        model_id="test/model",
        version="t-1",
        url=url or server.url(),
        archive_size=len(body),
        archive_sha256=archive_sha or _sha(body),
        files=files
        or tuple(ModelFile(n, len(d), _sha(d)) for n, d in FILES.items()),
    )


def test_downloads_verifies_and_unpacks(cache, server) -> None:
    m = _manifest(server)
    folder = model_store.ensure_model(m)
    assert folder == model_store.model_dir(m)
    for name, data in FILES.items():
        assert (folder / name).read_bytes() == data
    assert model_store.is_installed(m)
    assert not list(model_store.models_dir().glob("*.part"))


def test_a_second_call_does_not_download_again(cache, server) -> None:
    m = _manifest(server)
    model_store.ensure_model(m)
    model_store.ensure_model(m)
    assert server.requests == 1


def test_follows_a_redirect(cache, server) -> None:
    """GitHub release assets answer 302 to another host."""
    m = _manifest(server, url=server.url("/redirect"))
    assert model_store.is_installed(m) is False
    model_store.ensure_model(m)
    assert model_store.is_installed(m)


def test_archive_checksum_mismatch_leaves_nothing(cache, server) -> None:
    m = _manifest(server, archive_sha="0" * 64)
    with pytest.raises(ModelDownloadError, match="damaged"):
        model_store.ensure_model(m)
    assert not model_store.model_dir(m).exists()
    assert not list(model_store.models_dir().iterdir())


def test_file_checksum_mismatch_leaves_no_folder(cache, server) -> None:
    bad = tuple(ModelFile(n, len(d), "0" * 64) for n, d in FILES.items())
    m = _manifest(server, files=bad)
    with pytest.raises(ModelDownloadError, match="damaged"):
        model_store.ensure_model(m)
    assert not list(model_store.models_dir().iterdir())


def test_cancel_mid_download_removes_the_part_file(cache, server, monkeypatch) -> None:
    monkeypatch.setattr(model_store, "_BLOCK", 1024)
    token = CancelToken()

    def progress(_event):
        token.cancel()

    m = _manifest(server)
    with pytest.raises(JobCancelled):
        model_store.ensure_model(m, progress=progress, cancel=token)
    assert not list(model_store.models_dir().iterdir())


def test_not_enough_disk_space_is_said_before_downloading(cache, server, monkeypatch) -> None:
    import collections

    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(model_store.shutil, "disk_usage", lambda _p: usage(10, 10, 0))
    m = _manifest(server)
    with pytest.raises(ModelDownloadError) as info:
        model_store.ensure_model(m)
    assert str(model_store.models_dir()) in str(info.value)
    assert server.requests == 0


def test_offline_names_the_way_out(cache, server) -> None:
    m = _manifest(server, url="http://127.0.0.1:9/nothing-listens-here")
    with pytest.raises(ModelDownloadError, match="WhisperX online"):
        model_store.ensure_model(m)


def test_a_stale_part_file_is_cleared(cache, server) -> None:
    m = _manifest(server)
    model_store.models_dir().mkdir(parents=True)
    stale = model_store.models_dir() / f"{m.folder_name}.tar.bz2.part"
    stale.write_bytes(b"left over from a crash")
    model_store.ensure_model(m)
    assert not stale.exists()


def test_two_jobs_download_once(cache, server) -> None:
    m = _manifest(server)
    errors: list[BaseException] = []

    def run():
        try:
            model_store.ensure_model(m)
        except BaseException as error:  # noqa: BLE001 — surfaced below
            errors.append(error)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert server.requests == 1


def test_installed_checks_and_discard(cache, server) -> None:
    m = _manifest(server)
    folder = model_store.ensure_model(m)
    assert model_store.verify_installed(m)
    data = bytearray((folder / "encoder.onnx").read_bytes())
    data[0] ^= 0xFF  # same size, different bytes
    (folder / "encoder.onnx").write_bytes(bytes(data))
    assert model_store.is_installed(m) is True  # sizes still match
    assert model_store.verify_installed(m) is False
    model_store.discard(m)
    assert not folder.exists()


def test_unpack_failure_leaves_no_half_folder(cache, server, monkeypatch) -> None:
    def broken_open(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(model_store.tarfile, "open", broken_open)
    m = _manifest(server)
    with pytest.raises(ModelDownloadError):
        model_store.ensure_model(m)
    assert not list(model_store.models_dir().iterdir())


def test_the_manifest_digest_changes_with_any_field(server) -> None:
    from dataclasses import replace

    a = _manifest(server)
    assert a.digest() != replace(a, version="t-2").digest()
    assert a.digest() != replace(a, url=a.url + "?x").digest()
    assert a.ref == "test/model@t-1"
    assert a.folder_name == "test--model-t-1"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/bin/python -m pytest tests/test_model_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'qurantext.services.model_store'`.

- [ ] **Step 3: Write `src/qurantext/services/model_store.py`**

```python
"""The local speech model: where it lives, and fetching it once.

The model is too large to ship inside the installer, so the first local
transcription downloads it. Everything about that download is pinned in code —
the URL, the archive's size and checksum, every file's size and checksum — so
the app never fetches anything it has not been told to trust, and a new model
version is a deliberate code change. The folder is derived data: deleting it
costs one download.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from qurantext.config.paths import user_cache_dir
from qurantext.services.errors import ModelDownloadError
from qurantext.utils.progress import CancelToken, JobCancelled, ProgressCallback, report

__all__ = [
    "ModelFile",
    "ModelManifest",
    "discard",
    "ensure_model",
    "is_installed",
    "model_dir",
    "models_dir",
    "verify_installed",
]

_BLOCK = 1 << 20
_TIMEOUT_SECONDS = 30
_SPACE_MARGIN = 1.10
#: One download at a time: a second job waits for the first one's model.
_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class ModelFile:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ModelManifest:
    model_id: str
    version: str
    url: str
    archive_size: int
    archive_sha256: str
    files: tuple[ModelFile, ...]

    @property
    def ref(self) -> str:
        return f"{self.model_id}@{self.version}"

    @property
    def folder_name(self) -> str:
        return f"{self.model_id.replace('/', '--')}-{self.version}"

    @property
    def unpacked_size(self) -> int:
        return sum(f.size for f in self.files)

    def digest(self) -> str:
        """Changes when anything pinned changes, so a new model transcribes again."""
        payload = json.dumps(asdict(self), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def models_dir() -> Path:
    return user_cache_dir() / "models"


def model_dir(manifest: ModelManifest) -> Path:
    return models_dir() / manifest.folder_name


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(_BLOCK), b""):
            h.update(block)
    return h.hexdigest()


def is_installed(manifest: ModelManifest) -> bool:
    """Every file is there with its pinned size. Cheap: run before every job."""
    folder = model_dir(manifest)
    return all(
        (folder / f.name).is_file() and (folder / f.name).stat().st_size == f.size
        for f in manifest.files
    )


def verify_installed(manifest: ModelManifest) -> bool:
    """Every file matches its pinned checksum. Slow: run when loading failed."""
    folder = model_dir(manifest)
    return is_installed(manifest) and all(
        _sha256(folder / f.name) == f.sha256 for f in manifest.files
    )


def discard(manifest: ModelManifest) -> None:
    shutil.rmtree(model_dir(manifest), ignore_errors=True)


def _mb(n: int) -> str:
    return f"{n / 1_000_000:.0f} MB"


def ensure_model(
    manifest: ModelManifest,
    *,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> Path:
    """The model's folder, downloading and installing it first if needed."""
    with _LOCK:
        if is_installed(manifest):
            return model_dir(manifest)
        root = models_dir()
        root.mkdir(parents=True, exist_ok=True)
        need = int((manifest.archive_size + manifest.unpacked_size) * _SPACE_MARGIN)
        free = shutil.disk_usage(root).free
        if free < need:
            raise ModelDownloadError(
                f"Not enough free disk space for the speech model: it needs {_mb(need)} "
                f"in {root}, and {_mb(free)} is free."
            )
        part = root / f"{manifest.folder_name}.tar.bz2.part"
        part.unlink(missing_ok=True)
        try:
            _download(manifest, part, progress, cancel)
            return _install(manifest, part)
        finally:
            part.unlink(missing_ok=True)


def _download(
    manifest: ModelManifest,
    part: Path,
    progress: ProgressCallback | None,
    cancel: CancelToken | None,
) -> None:
    digest = hashlib.sha256()
    done = 0
    started = time.monotonic()
    try:
        with urllib.request.urlopen(manifest.url, timeout=_TIMEOUT_SECONDS) as response:
            with part.open("wb") as out:
                while block := response.read(_BLOCK):
                    out.write(block)
                    digest.update(block)
                    done += len(block)
                    fraction = min(1.0, done / manifest.archive_size)
                    elapsed = time.monotonic() - started
                    eta = elapsed / fraction - elapsed if fraction > 0.01 else None
                    report(
                        progress,
                        "download",
                        f"Downloading the speech model, once: {_mb(done)} of "
                        f"{_mb(manifest.archive_size)}",
                        fraction=fraction,
                        eta_seconds=eta,
                    )
                    if cancel is not None:
                        cancel.raise_if_cancelled("download")
    except JobCancelled:
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise ModelDownloadError(
            "The speech model is downloaded once, on first use, and that download "
            f"failed ({error}). Check the internet connection and start the job again, "
            "or choose WhisperX online."
        ) from error
    if done != manifest.archive_size or digest.hexdigest() != manifest.archive_sha256:
        raise ModelDownloadError(
            "The downloaded speech model is damaged (its checksum does not match), so "
            "it was deleted. Start the job again to download it again."
        )
    report(progress, "download", "Downloaded the speech model.", fraction=1.0, done=True)


def _install(manifest: ModelManifest, part: Path) -> Path:
    """Unpack the pinned files only, verify them, and move the folder in at once."""
    root = models_dir()
    target = model_dir(manifest)
    tmp = Path(tempfile.mkdtemp(prefix=f".{manifest.folder_name}-", dir=root))
    try:
        try:
            with tarfile.open(part, "r:bz2") as tar:
                for f in manifest.files:
                    source = tar.extractfile(tar.getmember(f.name))
                    if source is None:
                        raise KeyError(f.name)
                    with source, (tmp / f.name).open("wb") as out:
                        shutil.copyfileobj(source, out, _BLOCK)
        except (OSError, KeyError, tarfile.TarError) as error:
            raise ModelDownloadError(
                f"The speech model could not be unpacked into {root} ({error})."
            ) from error
        if any(_sha256(tmp / f.name) != f.sha256 for f in manifest.files):
            raise ModelDownloadError(
                "The downloaded speech model is damaged (a file's checksum does not "
                "match), so it was deleted. Start the job again to download it again."
            )
        shutil.rmtree(target, ignore_errors=True)
        tmp.rename(target)
        return target
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
```

Only the files named in the manifest are read out of the archive, each by exact name. A crafted archive therefore cannot write outside the folder.

- [ ] **Step 4: Run the tests**

Run: `venv/bin/python -m pytest tests/test_model_store.py -q`
Expected: all pass. If `test_offline_names_the_way_out` is slow (port 9 is filtered rather than refused on this machine), pick another closed port from `ss -ltn`. It must fail fast.

- [ ] **Step 5: Run the whole suite and lint, then commit**

```bash
venv/bin/python -m pytest -q && venv/bin/ruff check . && venv/bin/ruff format --check .
git add src/qurantext/services/model_store.py tests/test_model_store.py
git commit -m "Add the model store: find the local speech model, or download it once against pinned checksums

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2.2: Publish the model and pin it

**Files:**
- Modify: `src/qurantext/services/model_store.py` (add `LOCAL_MODEL`)
- Test: `tests/test_model_store.py`

**Interfaces:**
- Consumes: Task 0.3's shipping variant, and `package.py` from Task 0.1.
- Produces: `model_store.LOCAL_MODEL: ModelManifest`, pinned to the public release.

- [ ] **Step 1: Pack the shipping variant**

```bash
python3 tools/export_local_model/package.py --variant-dir $BAKE/export/<int8|fp32> \
    --version <int8|fp32>-1 --out-dir $BAKE/release
cat $BAKE/release/manifest_literal.py.txt
```

- [ ] **Step 2: ASK THE USER before publishing.** This is outward-facing.

Show them the archive name and size, and the NOTICE text. Ask them to do the following (`gh` is not installed on this machine, so it is done in the browser):
1. Create the **public** repository `Grazyen96/qalun-models`, with a README saying what it holds, the model's licence, and a link to the NVIDIA source.
2. Create the release `model-v1` and upload `$BAKE/release/<archive>.tar.bz2` and `tools/export_local_model/NOTICE.md`.

Wait for them to confirm.

- [ ] **Step 3: Check that the asset downloads without logging in, and matches**

```bash
url=$(python3 -c "import json;print(json.load(open('$BAKE/release/manifest.json'))['url'])")
curl -sSL -o /tmp/claude-1000/model-check.tar.bz2 "$url" && sha256sum /tmp/claude-1000/model-check.tar.bz2
python3 -c "import json;print(json.load(open('$BAKE/release/manifest.json'))['archive_sha256'])"
rm /tmp/claude-1000/model-check.tar.bz2
```

Expected: the two hashes are equal. A 404 means the repo or release is not public yet.

- [ ] **Step 4: Write the failing test** (append to `tests/test_model_store.py`)

```python
def test_the_shipped_model_is_pinned_to_the_public_release() -> None:
    m = model_store.LOCAL_MODEL
    assert m.model_id == "nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0"
    assert m.url.startswith("https://github.com/Grazyen96/qalun-models/releases/download/model-v1/")
    assert {f.name for f in m.files} == {
        "encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt", "NOTICE.md"
    }
    assert all(len(f.sha256) == 64 for f in m.files) and len(m.archive_sha256) == 64
```

Run: `venv/bin/python -m pytest tests/test_model_store.py::test_the_shipped_model_is_pinned_to_the_public_release -q`
Expected: FAIL with `AttributeError: module ... has no attribute 'LOCAL_MODEL'`.

- [ ] **Step 5: Paste the literal** from `$BAKE/release/manifest_literal.py.txt` at the end of `model_store.py`, under this comment:

```python
#: The model the local engine runs. Pinned: produced by
#: tools/export_local_model/package.py, published as release model-v1 of the
#: public Grazyen96/qalun-models repo. Never edit by hand; re-run the tool.
```

Add `"LOCAL_MODEL"` to `__all__`.

- [ ] **Step 6: Run the tests, then commit and run the phase-end review**

```bash
venv/bin/python -m pytest -q && venv/bin/ruff check . && venv/bin/ruff format --check .
git add src/qurantext/services/model_store.py tests/test_model_store.py
git commit -m "Pin the published speech model: model-v1 of the public qalun-models repo

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Phase-end review: one whole-branch review of Phase 2, one fix pass, then merge locally.

---

## Phase 3: Local engine, and the default switches to it

### Task 3.1: Pause cutter (`core/pause_cut.py`)

**Files:**
- Create: `src/qurantext/core/pause_cut.py`
- Test: `tests/test_pause_cut.py`

**Interfaces:**
- Produces:
  - `SAMPLE_RATE = 16000`
  - `class PauseCutter(max_seconds=28.0, search_seconds=10.0, frame_seconds=0.1, sample_rate=16000)` with:
    - `.feed(block: np.ndarray) -> list[tuple[int, np.ndarray]]`, returning completed windows as `(start_sample, float32 samples)`;
    - `.flush() -> list[tuple[int, np.ndarray]]`;
    - `.buffered_samples -> int`.
  - The cut rule is the bake-off's `common.chunk_at_pauses`, made incremental.

- [ ] **Step 1: Write the failing tests** (`tests/test_pause_cut.py`)

```python
from __future__ import annotations

import numpy as np

from qurantext.core.pause_cut import SAMPLE_RATE, PauseCutter

SR = SAMPLE_RATE


def _noise(seconds: float, seed: int = 0) -> np.ndarray:
    return (np.random.default_rng(seed).standard_normal(int(seconds * SR)) * 0.3).astype(np.float32)


def _run(audio: np.ndarray, block_seconds: float = 1.0, **kw):
    cutter = PauseCutter(**kw)
    windows = []
    step = int(block_seconds * SR)
    for i in range(0, len(audio), step):
        windows += cutter.feed(audio[i : i + step])
    return windows + cutter.flush()


def test_a_short_clip_is_one_window() -> None:
    windows = _run(_noise(5))
    assert len(windows) == 1
    assert windows[0][0] == 0 and len(windows[0][1]) == 5 * SR


def test_windows_never_exceed_28_seconds_and_cover_everything() -> None:
    audio = _noise(200)
    windows = _run(audio)
    assert all(len(w) <= 28 * SR for _, w in windows)
    assert sum(len(w) for _, w in windows) == len(audio)
    starts = [s for s, _ in windows]
    assert starts == sorted(starts) and starts[0] == 0
    for (s, w), (s2, _) in zip(windows, windows[1:]):
        assert s + len(w) == s2


def test_the_cut_lands_on_the_pause() -> None:
    audio = _noise(40)
    audio[int(22.0 * SR) : int(22.3 * SR)] = 0.0  # a waqf
    windows = _run(audio)
    assert abs(len(windows[0][1]) / SR - 22.0) <= 0.1


def test_silence_only_audio_is_one_window_per_28s() -> None:
    windows = _run(np.zeros(60 * SR, dtype=np.float32))
    assert sum(len(w) for _, w in windows) == 60 * SR
    assert all(len(w) <= 28 * SR for _, w in windows)


def test_the_buffer_stays_bounded_on_long_audio() -> None:
    cutter = PauseCutter()
    block = _noise(1)
    for _ in range(600):  # ten minutes
        cutter.feed(block)
        assert cutter.buffered_samples < 29 * SR


def test_an_empty_feed_is_harmless() -> None:
    cutter = PauseCutter()
    assert cutter.feed(np.zeros(0, dtype=np.float32)) == []
    assert cutter.flush() == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/bin/python -m pytest tests/test_pause_cut.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write `src/qurantext/core/pause_cut.py`**

```python
"""Cut a stream of audio into recognisable windows, at pauses.

The recogniser takes at most about thirty seconds at a time. Cutting blindly
splits a word in two, so each cut lands on the quietest tenth of a second in the
window's last ten seconds, which in recitation is nearly always a waqf. Audio is
fed in blocks as it is decoded, so an hour-long lecture is never in memory whole.
"""

from __future__ import annotations

import numpy as np

__all__ = ["SAMPLE_RATE", "PauseCutter"]

SAMPLE_RATE = 16000


class PauseCutter:
    """Accumulates audio blocks and hands back windows of at most *max_seconds*."""

    def __init__(
        self,
        *,
        max_seconds: float = 28.0,
        search_seconds: float = 10.0,
        frame_seconds: float = 0.1,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        self._max = int(max_seconds * sample_rate)
        self._search = int(search_seconds * sample_rate)
        self._frame = int(frame_seconds * sample_rate)
        self._buf = np.zeros(0, dtype=np.float32)
        self._offset = 0

    @property
    def buffered_samples(self) -> int:
        return len(self._buf)

    def feed(self, block: np.ndarray) -> list[tuple[int, np.ndarray]]:
        if len(block):
            self._buf = np.concatenate([self._buf, block.astype(np.float32, copy=False)])
        windows = []
        while len(self._buf) >= self._max:
            cut = self._quietest_cut()
            windows.append((self._offset, self._buf[:cut].copy()))
            self._buf = self._buf[cut:]
            self._offset += cut
        return windows

    def flush(self) -> list[tuple[int, np.ndarray]]:
        if not len(self._buf):
            return []
        window = (self._offset, self._buf.copy())
        self._offset += len(self._buf)
        self._buf = np.zeros(0, dtype=np.float32)
        return [window]

    def _quietest_cut(self) -> int:
        lo = self._max - self._search
        region = self._buf[lo : self._max]
        frames = len(region) // self._frame
        if frames == 0:
            return self._max
        rms = np.sqrt(
            np.mean(region[: frames * self._frame].reshape(frames, self._frame) ** 2, axis=1)
        )
        cut = lo + int(np.argmin(rms)) * self._frame
        return cut if cut > 0 else self._max
```

- [ ] **Step 4: Run the tests and lint, then commit**

```bash
venv/bin/python -m pytest tests/test_pause_cut.py -q && venv/bin/ruff check . && venv/bin/ruff format --check .
git add src/qurantext/core/pause_cut.py tests/test_pause_cut.py
git commit -m "Add the pause cutter that feeds the local engine windows of at most 28 s, cut at the quietest moment

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3.2: Tokens to words (`core/token_words.py`)

**Files:**
- Create: `src/qurantext/core/token_words.py`
- Test: `tests/test_token_words.py`

**Interfaces:**
- Produces:
  - `tokens_to_words(tokens: Sequence[str], times: Sequence[float], *, window_end: float, offset: float = 0.0) -> list[dict]`, returning `{"word", "start", "end", "score": 1.0}` dicts in absolute seconds, rounded to 3 places;
  - the constants `WORD_MARK = "▁"`, `WORD_STARTS = (WORD_MARK, " ")` and `MAX_TAIL_SECONDS = 0.5`.
- It must behave exactly like `tokens_to_words` in `prototypes/asr_bakeoff/run_sherpa.py` (Task 0.2), which passed the gate: a token starts a word if it begins with `▁` or with a space (sherpa-onnx's Python API renders the mark as a leading space), and `<...>` special tokens are skipped.

- [ ] **Step 1: Write the failing tests** (`tests/test_token_words.py`)

```python
from __future__ import annotations

import pytest

from qurantext.core.token_words import tokens_to_words

M = "▁"


def _w(words):
    return [(w["word"], w["start"], w["end"]) for w in words]


def test_the_word_mark_starts_a_word_and_pieces_join_it() -> None:
    words = tokens_to_words([f"{M}وقا", "لوا", f"{M}ما"], [0.0, 0.16, 0.8], window_end=2.0)
    assert [w["word"] for w in words] == ["وقالوا", "ما"]


def test_start_is_the_first_token_and_end_is_the_next_start() -> None:
    words = tokens_to_words([f"{M}a", "b", f"{M}c"], [1.0, 1.2, 1.4], window_end=3.0)
    assert _w(words)[0] == ("ab", 1.0, 1.4)


def test_end_is_capped_half_a_second_after_the_last_token() -> None:
    words = tokens_to_words([f"{M}a", f"{M}b"], [1.0, 5.0], window_end=9.0)
    assert _w(words)[0] == ("a", 1.0, 1.5)


def test_the_last_word_is_capped_at_the_window_end() -> None:
    words = tokens_to_words([f"{M}a"], [2.8], window_end=3.0)
    assert _w(words) == [("a", 2.8, 3.0)]


def test_offset_moves_everything_into_the_recording() -> None:
    words = tokens_to_words([f"{M}a"], [0.5], window_end=1.0, offset=60.0)
    assert _w(words) == [("a", 60.5, 61.0)]


def test_a_bare_mark_starts_the_next_piece_as_a_word() -> None:
    words = tokens_to_words([f"{M}a", M, "b"], [0.0, 0.4, 0.48], window_end=2.0)
    assert [w["word"] for w in words] == ["a", "b"]
    assert words[1]["start"] == 0.48


def test_punctuation_attaches_to_the_word_before() -> None:
    words = tokens_to_words([f"{M}a", "،", f"{M}b", "."], [0.0, 0.2, 0.4, 0.6], window_end=1.0)
    assert [w["word"] for w in words] == ["a،", "b."]


def test_leading_punctuation_is_dropped() -> None:
    words = tokens_to_words(["،", f"{M}a"], [0.0, 0.2], window_end=1.0)
    assert [w["word"] for w in words] == ["a"]


def test_a_leading_space_starts_a_word_like_the_mark() -> None:
    # sherpa-onnx's Python API renders the SentencePiece mark as a leading space.
    words = tokens_to_words([" وقا", "لوا", " ما"], [0.0, 0.16, 0.8], window_end=2.0)
    assert [w["word"] for w in words] == ["وقالوا", "ما"]
    assert _w(words)[0] == ("وقالوا", 0.0, 0.66)


def test_a_bare_space_starts_the_next_piece_as_a_word() -> None:
    words = tokens_to_words([" a", " ", "b"], [0.0, 0.4, 0.48], window_end=2.0)
    assert [w["word"] for w in words] == ["a", "b"]
    assert words[1]["start"] == 0.48


def test_punctuation_after_a_leading_space_attaches_to_the_word_before() -> None:
    words = tokens_to_words([" a", " ،", "b"], [0.0, 0.2, 0.3], window_end=1.0)
    assert [w["word"] for w in words] == ["a،", "b"]


def test_a_marked_punctuation_token_still_starts_the_next_piece() -> None:
    words = tokens_to_words([f"{M}a", f"{M}،", "b"], [0.0, 0.2, 0.3], window_end=1.0)
    assert [w["word"] for w in words] == ["a،", "b"]


def test_special_tokens_are_not_speech() -> None:
    words = tokens_to_words(
        [" a", "<unk>", " b", " <blk>", " c"], [0, 0.1, 0.2, 0.3, 0.4], window_end=1.0
    )
    assert [w["word"] for w in words] == ["a", "b", "c"]


def test_a_continuation_with_nothing_before_starts_a_word() -> None:
    words = tokens_to_words(["ab", "c"], [0.0, 0.1], window_end=1.0)
    assert [w["word"] for w in words] == ["abc"]


def test_two_words_on_one_frame_keep_end_equal_to_start() -> None:
    words = tokens_to_words([f"{M}a", f"{M}b"], [0.4, 0.4], window_end=1.0)
    assert words[0]["end"] == words[0]["start"] == 0.4


def test_diacritics_stay_in_the_word() -> None:
    text = "وَقَالُوا"
    assert tokens_to_words([f"{M}{text}"], [0.0], window_end=1.0)[0]["word"] == text


def test_every_word_scores_one() -> None:
    assert {w["score"] for w in tokens_to_words([f"{M}a", f"{M}b"], [0, 1], window_end=2)} == {1.0}


def test_mismatched_lengths_are_an_error() -> None:
    with pytest.raises(ValueError):
        tokens_to_words([f"{M}a"], [0.0, 1.0], window_end=2.0)


def test_no_tokens_no_words() -> None:
    assert tokens_to_words([], [], window_end=2.0) == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/bin/python -m pytest tests/test_token_words.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write `src/qurantext/core/token_words.py`**

```python
"""Turn the recogniser's sub-word tokens and their times into timed words.

The model emits SentencePiece tokens: a token beginning with the word mark
starts a new word and the tokens after it continue that word. sherpa-onnx's
Python API renders the mark ``▁`` as a leading space (``" وقال"``, and a bare
``" "``), so a token starts a word on either; this mirrors
``prototypes/asr_bakeoff/run_sherpa.py`` exactly. Each token carries only a start
time, so a word ends where the next one starts, capped half a second after its
last token so a long pause does not stretch the word across it. Punctuation the
model writes belongs to the word before it. The rule is the one the ASR bake-off's
parity gate accepted (``prototypes/asr_bakeoff/run_sherpa.py``).
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["MAX_TAIL_SECONDS", "WORD_MARK", "WORD_STARTS", "tokens_to_words"]

WORD_MARK = "▁"
WORD_STARTS = (WORD_MARK, " ")
MAX_TAIL_SECONDS = 0.5
_PUNCT = frozenset(".,،؛;:!?؟\"'«»()[]-…")


def tokens_to_words(
    tokens: Sequence[str],
    times: Sequence[float],
    *,
    window_end: float,
    offset: float = 0.0,
) -> list[dict]:
    """Words with absolute start/end seconds, from one window's tokens."""
    if len(tokens) != len(times):
        raise ValueError(f"{len(tokens)} tokens but {len(times)} times")
    pieces: list[list] = []  # [text, start, last token time]
    pending = False
    for token, t in zip(tokens, times, strict=True):
        starts = token.startswith(WORD_STARTS)
        text = token.replace(WORD_MARK, "").strip()
        if not text:
            pending = pending or starts
            continue
        if text.startswith("<") and text.endswith(">"):  # <unk>, <blk>: not speech
            pending = pending or starts
            continue
        if all(ch in _PUNCT for ch in text):
            if pieces:
                pieces[-1][0] += text
            pending = pending or starts
            continue
        if starts or pending or not pieces:
            pieces.append([text, float(t), float(t)])
            pending = False
        else:
            pieces[-1][0] += text
            pieces[-1][2] = float(t)

    words = []
    for i, (text, start, last) in enumerate(pieces):
        following = pieces[i + 1][1] if i + 1 < len(pieces) else window_end
        end = max(start, min(following, last + MAX_TAIL_SECONDS))
        words.append(
            {
                "word": text,
                "start": round(offset + start, 3),
                "end": round(offset + end, 3),
                "score": 1.0,
            }
        )
    return words
```

- [ ] **Step 4: Run the tests and lint, then commit**

```bash
venv/bin/python -m pytest tests/test_token_words.py -q && venv/bin/ruff check . && venv/bin/ruff format --check .
git add src/qurantext/core/token_words.py tests/test_token_words.py
git commit -m "Add the rule that groups the recogniser's sub-word tokens into timed words

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3.3: The local engine (`services/engine_local.py`)

**Files:**
- Create: `src/qurantext/services/engine_local.py`
- Test: `tests/test_engine_local.py`

**Interfaces:**
- Consumes:
  - `PauseCutter` and `SAMPLE_RATE` (Task 3.1);
  - `tokens_to_words` (Task 3.2);
  - `errors.LocalEngineError` and `errors.ModelLoadError` (Task 1.1);
  - `core.video_common.require_binary`, `utils.progress.report`.
- Produces:
  - `DEFAULT_THREADS: int`
  - `make_recognizer(model_dir: Path, num_threads: int)`, which wraps sherpa-onnx and raises `ModelLoadError` on any load failure;
  - `decode_pcm(audio_path: Path, *, block_seconds: float = 1.0) -> Iterator[np.ndarray]`
  - `probe_duration(audio_path: Path) -> float | None`
  - `transcribe_local(audio_path: Path, model_dir: Path, *, progress=None, cancel=None, recognizer_factory=make_recognizer, num_threads=DEFAULT_THREADS) -> dict`, returning the WhisperX raw shape.
  - Progress stage: `"transcribe"`.

- [ ] **Step 1: Write the failing tests** (`tests/test_engine_local.py`)

```python
from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from qurantext.io.readers import extract_alignment_words  # the reader pipelines/recitation.py uses
from qurantext.services import engine_local
from qurantext.services.errors import LocalEngineError, ModelLoadError
from qurantext.utils.progress import CancelToken, JobCancelled

FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="needs ffmpeg")


def _tone(path, seconds=3.0, *, rate=16000, channels=1, extra=()):
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
         f"sine=frequency=440:sample_rate={rate}:duration={seconds}",
         "-ac", str(channels), *extra, str(path)],
        check=True,
    )
    return path


class FakeRecognizer:
    """Returns two words per window, at fixed times, and records what it was given."""

    def __init__(self, *, tokens=(" قال", " رب"), times=(0.1, 0.5)):
        self.windows: list[np.ndarray] = []
        self._tokens, self._times = list(tokens), list(times)

    def create_stream(self):
        rec = self

        class Stream:
            def accept_waveform(self, rate, samples):
                assert rate == 16000
                rec.windows.append(np.asarray(samples))
                self.result = SimpleNamespace(tokens=rec._tokens, timestamps=rec._times)

        return Stream()

    def decode_streams(self, streams):
        pass


def test_produces_the_whisperx_shape(tmp_path) -> None:
    audio = _tone(tmp_path / "a.wav")
    fake = FakeRecognizer()
    out = engine_local.transcribe_local(audio, tmp_path, recognizer_factory=lambda *_: fake)
    assert out["detected_language"] == "ar"
    seg = out["segments"][0]
    assert set(seg) == {"start", "end", "text", "words"}
    assert [w["word"] for w in seg["words"]] == ["قال", "رب"]
    assert seg["text"] == "قال رب"
    assert len(extract_alignment_words(out)) == 2  # the pipeline's own reader accepts it


def test_window_offsets_place_words_in_the_recording(tmp_path) -> None:
    audio = _tone(tmp_path / "long.wav", seconds=60)
    fake = FakeRecognizer()
    out = engine_local.transcribe_local(audio, tmp_path, recognizer_factory=lambda *_: fake)
    starts = [s["words"][0]["start"] for s in out["segments"]]
    assert len(starts) >= 3 and starts[0] == pytest.approx(0.1)
    assert all(b > a for a, b in zip(starts, starts[1:]))
    assert all(len(w) <= 28 * 16000 for w in fake.windows)


def test_windows_without_tokens_add_no_segment(tmp_path) -> None:
    audio = _tone(tmp_path / "a.wav")
    fake = FakeRecognizer(tokens=(), times=())
    out = engine_local.transcribe_local(audio, tmp_path, recognizer_factory=lambda *_: fake)
    assert out["segments"] == []


def test_decodes_stereo_44k_m4a_to_16k_mono(tmp_path) -> None:
    audio = _tone(tmp_path / "a.m4a", seconds=2.0, rate=44100, channels=2, extra=("-c:a", "aac"))
    samples = np.concatenate(list(engine_local.decode_pcm(audio)))
    assert samples.dtype == np.float32
    assert abs(len(samples) - 2.0 * 16000) < 0.05 * 16000


def test_reads_an_arabic_path_with_spaces(tmp_path) -> None:
    audio = _tone(tmp_path / "الفرقان 71 77.wav")
    fake = FakeRecognizer()
    out = engine_local.transcribe_local(audio, tmp_path, recognizer_factory=lambda *_: fake)
    assert out["segments"]


def test_unreadable_audio_names_the_file(tmp_path) -> None:
    bad = tmp_path / "broken.mp3"
    bad.write_bytes(b"not audio")
    with pytest.raises(LocalEngineError, match="broken.mp3"):
        engine_local.transcribe_local(bad, tmp_path, recognizer_factory=lambda *_: FakeRecognizer())


def test_cancel_stops_between_blocks(tmp_path) -> None:
    audio = _tone(tmp_path / "a.wav", seconds=30)
    token = CancelToken()
    token.cancel()
    with pytest.raises(JobCancelled):
        engine_local.transcribe_local(
            audio, tmp_path, cancel=token, recognizer_factory=lambda *_: FakeRecognizer()
        )


def test_progress_reports_the_transcribe_stage(tmp_path) -> None:
    audio = _tone(tmp_path / "a.wav", seconds=30)
    events = []
    engine_local.transcribe_local(
        audio, tmp_path, progress=events.append, recognizer_factory=lambda *_: FakeRecognizer()
    )
    assert events and {e.stage for e in events} == {"transcribe"}
    assert events[-1].done is True


def test_a_model_that_will_not_load_raises_model_load_error(tmp_path) -> None:
    pytest.importorskip("sherpa_onnx")
    (tmp_path / "encoder.onnx").write_bytes(b"garbage")
    with pytest.raises(ModelLoadError):
        engine_local.make_recognizer(tmp_path, 1)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/bin/python -m pytest tests/test_engine_local.py -q`
Expected: FAIL (`ModuleNotFoundError: ... engine_local`).

- [ ] **Step 3: Write `src/qurantext/services/engine_local.py`**

```python
"""The local engine: NVIDIA's FastConformer Arabic, run by sherpa-onnx on this computer.

Audio is decoded by the bundled FFmpeg straight to 16 kHz mono and read in
blocks, cut at pauses into windows of at most 28 s, recognised a few windows at a
time, and returned in the WhisperX raw shape the rest of the pipeline already
reads. Nothing leaves the machine.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np

from qurantext.core.pause_cut import SAMPLE_RATE, PauseCutter
from qurantext.core.token_words import tokens_to_words
from qurantext.core.video_common import require_binary
from qurantext.services.errors import LocalEngineError, ModelLoadError
from qurantext.utils.progress import CancelToken, ProgressCallback, report

__all__ = [
    "DEFAULT_THREADS",
    "decode_pcm",
    "make_recognizer",
    "probe_duration",
    "transcribe_local",
]

#: Leave two cores to the window and the rest of the machine.
DEFAULT_THREADS = max(1, (os.cpu_count() or 1) - 2)
_BATCH_WINDOWS = 4

RecognizerFactory = Callable[[Path, int], Any]


def make_recognizer(model_dir: Path, num_threads: int) -> Any:
    """Load the model. Any failure is a ModelLoadError, so the caller can re-verify it."""
    try:
        import sherpa_onnx

        return sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(model_dir / "encoder.onnx"),
            decoder=str(model_dir / "decoder.onnx"),
            joiner=str(model_dir / "joiner.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=num_threads,
            sample_rate=SAMPLE_RATE,
            feature_dim=80,
            decoding_method="greedy_search",
            model_type="nemo_transducer",
        )
    except Exception as error:  # noqa: BLE001 — every load failure means the same thing here
        raise ModelLoadError(f"The speech model could not be loaded from {model_dir}: {error}") from error


def probe_duration(audio_path: Path) -> float | None:
    """The recording's length, for an honest progress bar. None when unknown."""
    try:
        ffprobe = require_binary("ffprobe", "Install FFmpeg and try again.")
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio_path)],
            check=True, capture_output=True, text=True, timeout=60,
        ).stdout.strip()
        return float(out) if out else None
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError):
        return None


def decode_pcm(audio_path: Path, *, block_seconds: float = 1.0) -> Iterator[np.ndarray]:
    """Yield the recording as 16 kHz mono float32 blocks, never the whole file at once."""
    ffmpeg = require_binary("ffmpeg", "Install FFmpeg and try again.")
    block_bytes = int(block_seconds * SAMPLE_RATE) * 4
    process = subprocess.Popen(
        [ffmpeg, "-v", "error", "-nostdin", "-i", str(audio_path),
         "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert process.stdout is not None
        leftover = b""
        while chunk := process.stdout.read(block_bytes):
            data = leftover + chunk
            usable = len(data) - len(data) % 4
            leftover = data[usable:]
            if usable:
                yield np.frombuffer(data[:usable], dtype=np.float32).copy()
        stderr = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
        if process.wait() != 0:
            raise LocalEngineError(
                f"FFmpeg could not read {Path(audio_path).name}: {stderr.strip()[-400:]}"
            )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def _minutes(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def transcribe_local(
    audio_path: Path,
    model_dir: Path,
    *,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
    recognizer_factory: RecognizerFactory = make_recognizer,
    num_threads: int = DEFAULT_THREADS,
) -> dict:
    """Transcribe *audio_path* on this computer, in the WhisperX raw shape."""
    audio_path = Path(audio_path)
    duration = probe_duration(audio_path)
    recognizer = recognizer_factory(Path(model_dir), num_threads)
    cutter = PauseCutter()
    segments: list[dict] = []
    pending: list[tuple[int, np.ndarray]] = []
    started = time.monotonic()

    def run_batch() -> None:
        streams = []
        for _start, samples in pending:
            stream = recognizer.create_stream()
            stream.accept_waveform(SAMPLE_RATE, samples)
            streams.append(stream)
        recognizer.decode_streams(streams)
        for (start, samples), stream in zip(pending, streams, strict=True):
            result = stream.result
            words = tokens_to_words(
                list(result.tokens),
                list(result.timestamps),
                window_end=len(samples) / SAMPLE_RATE,
                offset=start / SAMPLE_RATE,
            )
            if words:
                segments.append(
                    {
                        "start": words[0]["start"],
                        "end": words[-1]["end"],
                        "text": " ".join(w["word"] for w in words),
                        "words": words,
                    }
                )
        last_start, last_samples = pending[-1]
        reached = (last_start + len(last_samples)) / SAMPLE_RATE
        pending.clear()
        fraction = min(1.0, reached / duration) if duration else None
        elapsed = time.monotonic() - started
        eta = elapsed / fraction - elapsed if fraction and fraction > 0.01 else None
        total = f" of {_minutes(duration)}" if duration else ""
        report(
            progress,
            "transcribe",
            f"Transcribing on this computer: {_minutes(reached)}{total}",
            fraction=fraction,
            eta_seconds=eta,
        )

    for block in decode_pcm(audio_path):
        if cancel is not None:
            cancel.raise_if_cancelled("transcribe")
        for window in cutter.feed(block):
            pending.append(window)
            if len(pending) >= _BATCH_WINDOWS:
                run_batch()
    pending.extend(cutter.flush())
    if pending:
        run_batch()
    report(progress, "transcribe", "Transcribed on this computer.", fraction=1.0, done=True)
    return {"segments": segments, "detected_language": "ar"}
```

Make sure `test_cancel_stops_between_blocks` passes: the cancel check runs before the first block is used, so a pre-cancelled token raises at once.

- [ ] **Step 4: Run the tests and lint, then commit**

```bash
venv/bin/python -m pytest tests/test_engine_local.py -q && venv/bin/ruff check . && venv/bin/ruff format --check .
git add src/qurantext/services/engine_local.py tests/test_engine_local.py
git commit -m "Add the local engine: stream the audio through FFmpeg, cut it at pauses, and recognise it with sherpa-onnx

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

The model-load test skips until sherpa-onnx is a dependency, which happens in Task 3.4.

### Task 3.4: Wire `local` into `transcribe_audio`, add the dependency, and switch the default

**Files:**
- Modify: `pyproject.toml` (add `sherpa-onnx~=<version from Task 0.3>`)
- Modify: `src/qurantext/services/transcription.py`
- Modify: `src/qurantext/config/settings.py` (`DEFAULT_TRANSCRIBE_ENGINE = "local"`)
- Modify: `tests/test_transcription.py`, `tests/test_transcript_cache.py` (WhisperX tests now say `engine="whisperx"`)
- Test: `tests/test_transcription.py`

**Interfaces:**
- Consumes: `model_store.{LOCAL_MODEL, ensure_model, verify_installed, discard}` (Phase 2), and `engine_local.transcribe_local` (Task 3.3).
- Produces: `transcribe_audio(engine="local")` returns `TranscriptionResult(engine="local", model_ref=LOCAL_MODEL.ref)`. The default engine is `local`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_transcription.py`)

```python
class TestLocalEngine:
    @pytest.fixture
    def env(self, monkeypatch, tmp_path):
        from qurantext.config.settings import get_settings
        from qurantext.services import engine_local, model_store

        monkeypatch.setenv("QURANTEXT_CACHE_DIR", str(tmp_path / "cache"))
        get_settings.cache_clear()
        calls = {"ensure": 0, "run": 0, "discard": 0}
        monkeypatch.setattr(
            model_store, "ensure_model",
            lambda m, **k: calls.__setitem__("ensure", calls["ensure"] + 1) or tmp_path,
        )
        monkeypatch.setattr(model_store, "discard", lambda m: calls.__setitem__("discard", calls["discard"] + 1))
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"RIFF....WAVE")
        yield SimpleNamespace(calls=calls, audio=audio, engine_local=engine_local, model_store=model_store)
        get_settings.cache_clear()

    def test_local_is_the_default(self, env, monkeypatch) -> None:
        from qurantext.services import transcription

        monkeypatch.delenv("QURANTEXT_TRANSCRIBE_ENGINE", raising=False)
        monkeypatch.setattr(env.engine_local, "transcribe_local", lambda *a, **k: {"segments": []})
        result = transcription.transcribe_audio(env.audio)
        assert result.engine == "local"
        assert result.model_ref == env.model_store.LOCAL_MODEL.ref

    def test_a_repeat_run_hits_the_cache(self, env, monkeypatch) -> None:
        from qurantext.services import transcription

        def run(*_a, **_k):
            env.calls["run"] += 1
            return {"segments": []}

        monkeypatch.setattr(env.engine_local, "transcribe_local", run)
        transcription.transcribe_audio(env.audio, engine="local")
        second = transcription.transcribe_audio(env.audio, engine="local")
        assert env.calls["run"] == 1 and second.from_cache is True

    def test_cancelled_local_run_caches_nothing(self, env, monkeypatch) -> None:
        from qurantext.services import transcription
        from qurantext.utils.progress import JobCancelled

        def cancelled(*_a, **_k):
            raise JobCancelled("transcribe was cancelled")

        monkeypatch.setattr(env.engine_local, "transcribe_local", cancelled)
        with pytest.raises(JobCancelled):
            transcription.transcribe_audio(env.audio, engine="local")
        monkeypatch.setattr(env.engine_local, "transcribe_local", lambda *a, **k: {"segments": []})
        assert transcription.transcribe_audio(env.audio, engine="local").from_cache is False

    def test_a_damaged_model_is_downloaded_again_once(self, env, monkeypatch) -> None:
        from qurantext.services import transcription
        from qurantext.services.errors import ModelLoadError

        attempts = {"n": 0}

        def run(*_a, **_k):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ModelLoadError("bad file")
            return {"segments": []}

        monkeypatch.setattr(env.engine_local, "transcribe_local", run)
        monkeypatch.setattr(env.model_store, "verify_installed", lambda m: False)
        transcription.transcribe_audio(env.audio, engine="local")
        assert env.calls["discard"] == 1 and env.calls["ensure"] == 2

    def test_an_intact_model_that_will_not_load_is_not_downloaded_again(self, env, monkeypatch) -> None:
        from qurantext.services import transcription
        from qurantext.services.errors import LocalEngineError, ModelLoadError

        def run(*_a, **_k):
            raise ModelLoadError("runtime missing")

        monkeypatch.setattr(env.engine_local, "transcribe_local", run)
        monkeypatch.setattr(env.model_store, "verify_installed", lambda m: True)
        with pytest.raises(LocalEngineError):
            transcription.transcribe_audio(env.audio, engine="local")
        assert env.calls["discard"] == 0

    def test_the_local_cache_key_changes_with_the_model(self, env, monkeypatch) -> None:
        from dataclasses import replace

        from qurantext.services import transcription

        monkeypatch.setattr(env.engine_local, "transcribe_local", lambda *a, **k: {"segments": []})
        transcription.transcribe_audio(env.audio, engine="local")
        monkeypatch.setattr(
            env.model_store, "LOCAL_MODEL", replace(env.model_store.LOCAL_MODEL, version="next")
        )
        assert transcription.transcribe_audio(env.audio, engine="local").from_cache is False
```

Add `from types import SimpleNamespace` to the file's imports.

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/bin/python -m pytest tests/test_transcription.py -q -k TestLocalEngine`
Expected: FAIL (`LocalEngineError: The local engine is not part of this build yet.`).

- [ ] **Step 3: Implement the local branch** in `transcription.py`

Replace the Phase-1 `if resolved_engine == "local": raise ...` with:

```python
    if resolved_engine == "local":
        from qurantext.services import model_store

        manifest = model_store.LOCAL_MODEL
        return _transcribe_cached(
            audio_file_path,
            key_settings={"engine": "local", "model": manifest.ref, "manifest": manifest.digest()},
            model_ref=manifest.ref,
            engine="local",
            run=lambda: _run_local(audio_file_path, progress, cancel),
            save_raw_to=save_raw_to,
            use_cache=use_cache,
        )
```

Then add:

```python
def _run_local(audio_file_path: Path, progress, cancel) -> dict:
    """Run the local engine, re-downloading the model once if its files are damaged."""
    from qurantext.services import engine_local, model_store
    from qurantext.services.errors import LocalEngineError, ModelLoadError

    manifest = model_store.LOCAL_MODEL
    model_dir = model_store.ensure_model(manifest, progress=progress, cancel=cancel)
    try:
        return engine_local.transcribe_local(
            audio_file_path, model_dir, progress=progress, cancel=cancel
        )
    except ModelLoadError as error:
        if model_store.verify_installed(manifest):
            raise LocalEngineError(
                f"{error}\nThe model's files are intact, so the speech runtime itself "
                "could not start. Run `qalun --doctor` to see what is missing."
            ) from error
        model_store.discard(manifest)
        model_dir = model_store.ensure_model(manifest, progress=progress, cancel=cancel)
        return engine_local.transcribe_local(
            audio_file_path, model_dir, progress=progress, cancel=cancel
        )
```

- [ ] **Step 4: Switch the default and add the dependency**

In `settings.py`, set `DEFAULT_TRANSCRIBE_ENGINE = "local"`.

In `pyproject.toml`, add the following to `dependencies`, using the exact version Task 0.3 recorded:

```toml
  # The local transcription engine (NVIDIA FastConformer Arabic through ONNX).
  # Pinned to the release the parity gate passed with: docs/findings/asr-bakeoff.md.
  "sherpa-onnx~=<X.Y.Z>",
```

Then install it: `venv/bin/pip install -e '.[gui,dev]'`.

- [ ] **Step 5: Make the WhisperX tests say which engine they test**

These tests relied on WhisperX being the default. Add `engine="whisperx"` to each of their `transcribe_audio(...)` calls:
- in `tests/test_transcription.py`: `TestRejectedToken._run`;
- in `tests/test_transcript_cache.py`: `test_cache_hit...` and `test_use_cache_false_forces_a_fresh_call`.

In `tests/test_transcript_cache.py`, keep the cache key built with `{"model": ..., **input_kwargs()}`. That is the "unchanged key" guarantee.

- [ ] **Step 6: Run everything**

Run: `venv/bin/python -m pytest -q && venv/bin/ruff check . && venv/bin/ruff format --check .`
Expected: all pass, including `test_a_model_that_will_not_load_raises_model_load_error`, which no longer skips.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/qurantext tests
git commit -m "Transcribe on this computer by default: wire the local engine into transcription, re-downloading a damaged model once

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3.5: The product reproduces the gate, plus an opt-in slow test

**Files:**
- Create: `tests/test_local_engine_slow.py`
- Modify: `docs/findings/asr-bakeoff.md` (one line under the sherpa-onnx parity section)

**Interfaces:**
- Consumes: the CLI `transcribe --engine local`, `prototypes/asr_bakeoff/gate.py`, and the real model from the public release.

- [ ] **Step 1: Write the slow test** (`tests/test_local_engine_slow.py`)

```python
"""The real model on a real recitation. Opt-in: downloads ~110 MB once and runs ~10 s.

    QURANTEXT_SLOW_TESTS=1 venv/bin/python -m pytest tests/test_local_engine_slow.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

CLIP = Path(__file__).resolve().parents[1] / "input/recitations/furquanTra7-11.mp3"

pytestmark = [
    pytest.mark.skipif(os.environ.get("QURANTEXT_SLOW_TESTS") != "1", reason="opt-in slow test"),
    pytest.mark.skipif(not CLIP.exists(), reason="needs the local test recording"),
]


def test_the_real_model_finds_furqan_7_to_11(tmp_path) -> None:
    from qurantext.config.paths import DEFAULT_QURAN_PATH
    from qurantext.pipelines.detection import run_detection
    from qurantext.services.transcription import transcribe_audio

    result = transcribe_audio(CLIP, engine="local", use_cache=False)
    assert result.engine == "local"
    assert result.word_count >= 60

    out = tmp_path / "m.json"
    run_detection(
        quran=DEFAULT_QURAN_PATH, output=out, mode="recitation", audio=CLIP, echo=False,
        engine="local",
    )
    import json

    match = json.loads(out.read_text(encoding="utf-8"))
    assert (match["first_ayah"]["surah_num"], match["first_ayah"]["ayah_num"]) == (25, 7)
    assert (match["last_ayah"]["surah_num"], match["last_ayah"]["ayah_num"]) == (25, 11)
```

- [ ] **Step 2: Run it**

```bash
free -m | sed -n 2p
QURANTEXT_SLOW_TESTS=1 venv/bin/python -m pytest tests/test_local_engine_slow.py -q
```

Expected: PASS. The first run downloads the model from the public release.

- [ ] **Step 3: Rerun the gate with the product engine on all 17 clips**

```bash
while IFS=$'\t' read -r clip audio; do
  venv/bin/qurantext transcribe --engine local --no-cache --audio "$audio" --output $BAKE/local/$clip.json < /dev/null
done < $BAKE/clips.tsv
# pre-run the matchers in parallel exactly as in Task 0.3 Step 2, with eng=local, then:
venv/bin/python prototypes/asr_bakeoff/score.py $BAKE > $BAKE/score.log
venv/bin/python prototypes/asr_bakeoff/gate.py $BAKE local; echo "exit $?"
```

Expected: exit 0. If it fails where `sherpa-<variant>` passed, the product's tokens-to-words or window handling differs from the prototype. Diff `$BAKE/local/<clip>.json` against `$BAKE/sherpa-<variant>/<clip>.json` to find it before going on.

- [ ] **Step 4: Record it and commit, then run the phase-end review**

Under "sherpa-onnx parity" in `docs/findings/asr-bakeoff.md`, add: "The shipped engine (`qurantext transcribe --engine local`) passes the same gate on all 17 clips."

```bash
git add tests/test_local_engine_slow.py docs/findings/asr-bakeoff.md
git commit -m "Check the shipped local engine against the parity gate, and add an opt-in test on a real recitation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Phase-end review: one whole-branch review of Phase 3, one fix pass, then merge locally.

---

## Phase 4: Window, doctor, licences

### Task 4.1: The engine choice travels from preferences to the job, and the new stages have words

**Files:**
- Modify: `src/qurantext/gui/prefs.py` (`engine` property)
- Modify: `src/qurantext/gui/jobs.py` (`JobSpec.engine`, passed to both pipeline calls)
- Modify: `src/qurantext/gui/main_window.py` (`_KNOWN_STAGES` gains `download` and `transcribe`)
- Modify: `src/qurantext/gui/i18n.py` (new keys, English and Arabic)
- Test: `tests/test_prefs.py`, `tests/test_gui.py`, `tests/test_i18n.py`

**Interfaces:**
- Consumes: `settings.ENGINES`; `run_recitation_range(..., engine=)` and `run_detection(..., engine=)` (Task 1.3).
- Produces:
  - `Prefs.engine: str` (default `"local"`);
  - `JobSpec.engine: str = "local"`;
  - the i18n keys `job.stage.download`, `job.stage.transcribe`, `home.engine`, `home.engine.local`, `home.engine.whisperx` and `home.engine.no_token`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_prefs.py` (its `settings` fixture is a QSettings on a throwaway INI):

```python
def test_engine_defaults_to_local_and_round_trips(settings) -> None:
    prefs = Prefs(settings)
    assert prefs.engine == "local"
    prefs.engine = "whisperx"
    assert Prefs(settings).engine == "whisperx"


def test_an_unknown_stored_engine_reads_as_local(settings) -> None:
    settings.setValue("engine", "cohere")
    assert Prefs(settings).engine == "local"
```

Append to `tests/test_gui.py` (it already has `_spec(tmp_path, **overrides)`; `jobs_module` is imported locally in its tests, as here):

```python
def test_the_engine_choice_reaches_the_pipeline(tmp_path, monkeypatch) -> None:
    from qurantext.gui import jobs as jobs_module

    seen = {}

    def fake_range(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop")

    monkeypatch.setattr(jobs_module, "run_recitation_range", fake_range)
    with pytest.raises(RuntimeError, match="stop"):
        jobs_module.run_matching(_spec(tmp_path, engine="whisperx"))
    assert seen["engine"] == "whisperx"


def test_a_spec_transcribes_locally_unless_told_otherwise(tmp_path) -> None:
    assert _spec(tmp_path).engine == "local"
```

Append to `tests/test_i18n.py`. The engine labels are looked up dynamically (`f"home.engine.{value}"`), so the existing used-keys scan cannot see them:

```python
def test_engine_and_stage_strings_exist_in_both_languages() -> None:
    from qurantext.gui import i18n

    keys = (
        "job.stage.download", "job.stage.transcribe", "home.engine",
        "home.engine.local", "home.engine.whisperx", "home.engine.no_token",
    )
    for language in ("en", "ar"):
        for key in keys:
            assert i18n.STRINGS[language].get(key), f"{language} lacks {key}"
    assert "{folder}" in i18n.STRINGS["en"]["home.engine.no_token"]
    assert "{folder}" in i18n.STRINGS["ar"]["home.engine.no_token"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/bin/python -m pytest tests/test_prefs.py tests/test_gui.py tests/test_i18n.py -q -k "engine"`
Expected: FAIL.

- [ ] **Step 3: Implement**

`prefs.py`: import `ENGINES` from `qurantext.config.settings` and add, after `subtitles`:

```python
    # -- transcription engine ----------------------------------------------------

    @property
    def engine(self) -> str:
        value = self._settings.value("engine", "local")
        return value if isinstance(value, str) and value in ENGINES else "local"

    @engine.setter
    def engine(self, value: str) -> None:
        self._settings.setValue("engine", value)
        self._settings.sync()
```

`jobs.py`:
- add the field `engine: str = "local"` to `JobSpec`, after `render_right_away`, with the comment `#: "local" (this computer) or "whisperx" (Replicate). Never switched automatically.`;
- pass `engine=spec.engine` in both the `run_recitation_range(...)` and `run_detection(...)` calls.

`main_window.py`: `_KNOWN_STAGES = frozenset({"download", "transcribe", "detect", "match", "render", "export"})`.

`i18n.py`: add to the English table:

```python
        "job.stage.download": "Downloading the speech model, once (about 110 MB)…",
        "job.stage.transcribe": "Transcribing on this computer…",
        "home.engine": "Transcription:",
        "home.engine.local": "On this computer",
        "home.engine.whisperx": "WhisperX online (needs a Replicate token)",
        "home.engine.no_token": "No Replicate token is set. Put REPLICATE_API_TOKEN=… in a file named .env in {folder}, then restart Qalun.",
```

and to the Arabic table:

```python
        "job.stage.download": "جارٍ تنزيل نموذج التعرّف على الكلام، مرة واحدة فقط (نحو 110 ميغابايت)…",
        "job.stage.transcribe": "جارٍ تفريغ الصوت على هذا الحاسوب…",
        "home.engine": "التفريغ:",
        "home.engine.local": "على هذا الحاسوب",
        "home.engine.whisperx": "WhisperX عبر الإنترنت (يتطلّب رمز Replicate)",
        "home.engine.no_token": "لم يُضبط رمز Replicate. ضع السطر REPLICATE_API_TOKEN=… في ملف باسم ‎.env‎ داخل {folder}، ثم أعد تشغيل Qalun.",
```

`t(key, **fmt)` fills `{folder}`, so Task 4.2 calls `t("home.engine.no_token", folder=...)`. Arabic lines containing Latin runs follow the project's RTL rule from the 2026-10-07 UI review: a values-only line starts with an RLM. Run `tests/test_rtl.py` to confirm.

If Task 0.3 chose fp32, write "about 450 MB" and "نحو 450 ميغابايت".

- [ ] **Step 4: Run the tests and lint, then commit**

```bash
venv/bin/python -m pytest -q && venv/bin/ruff check . && venv/bin/ruff format --check .
git add src/qurantext/gui tests
git commit -m "Carry the engine choice from the window's preferences into the job, and name the download and transcribe stages in both languages

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4.2: The "Transcription" row in the home window

**Files:**
- Modify: `src/qurantext/gui/home/new_job.py`
- Test: `tests/test_home_panels.py`

**Interfaces:**
- Consumes: `Prefs.engine`, `JobSpec.engine` and the i18n keys (Task 4.1); `get_settings().replicate_api_token`; `config.paths.user_data_dir`.
- Produces: `NewJobPanel.engine_buttons: dict[str, QRadioButton]` and `NewJobPanel.no_token_label: QLabel`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_home_panels.py`, after its NewJobPanel tests; the `qt_app`, `prefs` and `store` fixtures and the `_panel(prefs, store)` helper already exist there)

```python
def test_the_engine_row_defaults_to_this_computer(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    assert panel.engine_buttons["local"].isChecked()
    assert panel.spec().engine == "local"
    assert panel.no_token_label.isHidden()


def test_choosing_whisperx_is_remembered_and_reaches_the_spec(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    panel.engine_buttons["whisperx"].setChecked(True)
    assert panel.spec().engine == "whisperx"
    assert _panel(prefs, store).engine_buttons["whisperx"].isChecked()


def test_whisperx_without_a_token_says_where_to_put_it(qt_app, prefs, store, monkeypatch) -> None:
    from qurantext.config.settings import get_settings

    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    get_settings.cache_clear()
    try:
        panel = _panel(prefs, store)
        panel.engine_buttons["whisperx"].setChecked(True)
        assert not panel.no_token_label.isHidden()
        assert ".env" in panel.no_token_label.text()
        # The note informs; it does not add a reason to keep Start disabled.
        assert panel.problem() == panel.spec().validate()
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/bin/python -m pytest tests/test_home_panels.py -q -k engine`
Expected: FAIL (`AttributeError: ... 'engine_buttons'`).

- [ ] **Step 3: Implement** in `new_job.py`

In `_build`, directly before the `self.subtitles_row = QWidget()` block:

```python
        self.engine_row = QWidget()
        engine_row = QVBoxLayout(self.engine_row)
        engine_row.setContentsMargins(0, 0, 0, 0)
        choices = QHBoxLayout()
        self._engine_group = QButtonGroup(self)
        self._engine_group.setExclusive(True)
        self.engine_buttons: dict[str, QRadioButton] = {}
        for value in ENGINES:
            button = QRadioButton(t(f"home.engine.{value}"))
            self.engine_buttons[value] = button
            self._engine_group.addButton(button)
            choices.addWidget(button)
        choices.addStretch(1)
        engine_row.addLayout(choices)
        self.no_token_label = QLabel()
        self.no_token_label.setWordWrap(True)
        engine_row.addWidget(self.no_token_label)
        self.more_form.addRow(t("home.engine"), self.engine_row)
        self._engine_group.buttonToggled.connect(self._engine_changed)
```

In `_apply_prefs`, after the subtitle lines:

```python
        self.engine_buttons[self._prefs.engine].setChecked(True)
        self._show_token_note(self._prefs.engine)
```

Add these methods next to `_subtitles_changed`:

```python
    def _current_engine(self) -> str:
        for value, button in self.engine_buttons.items():
            if button.isChecked():
                return value
        return "local"

    def _engine_changed(self) -> None:
        value = self._current_engine()
        self._prefs.engine = value
        self._show_token_note(value)
        self._refresh()

    def _show_token_note(self, engine: str) -> None:
        """Say before Start, not after a failed upload, that WhisperX has no token."""
        missing = engine == "whisperx" and not get_settings().replicate_api_token
        if missing:
            self.no_token_label.setText(t("home.engine.no_token", folder=user_data_dir()))
        self.no_token_label.setVisible(missing)
```

In `spec()`, add `engine=self._current_engine(),` to the `JobSpec(...)` arguments.

Imports: `QVBoxLayout` and `QLabel` from PySide6, if not already imported; `ENGINES` and `get_settings` from `qurantext.config.settings`; `user_data_dir` from `qurantext.config.paths`.

- [ ] **Step 4: Run the tests and lint, then commit**

```bash
venv/bin/python -m pytest -q && venv/bin/ruff check . && venv/bin/ruff format --check .
git add src/qurantext/gui/home/new_job.py tests/test_home_panels.py
git commit -m "Let the person choose where transcription runs, and say before Start when WhisperX has no token

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4.3: The doctor checks the engine that is actually configured

**Files:**
- Modify: `src/qurantext/config/preflight.py` (`_transcription`)
- Test: `tests/test_preflight.py`

**Interfaces:**
- Consumes:
  - `get_settings().transcription.engine` (Task 1.2);
  - `model_store.{LOCAL_MODEL, is_installed, models_dir, model_dir}` (Phase 2);
  - preflight's existing `CheckResult(name, status, detail, remedy="")` and `Status.{OK, WARN, FAIL}`, where `blocking` is `status == FAIL`.
- Produces: `_transcription()` checks only the configured engine. The local check is named `"Transcription"`, like today's check. Today's body is kept as `_whisperx_check()`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_preflight.py`)

```python
class TestTranscriptionCheck:
    @pytest.fixture
    def engine(self, monkeypatch):
        from qurantext.config.settings import get_settings

        def use(name: str) -> None:
            monkeypatch.setenv("QURANTEXT_TRANSCRIBE_ENGINE", name)
            get_settings.cache_clear()

        yield use
        get_settings.cache_clear()

    def test_local_without_the_runtime_is_blocking(self, engine, monkeypatch) -> None:
        import builtins

        from qurantext.config import preflight
        from qurantext.config.preflight import Status

        real_import = builtins.__import__

        def no_sherpa(name, *args, **kwargs):
            if name == "sherpa_onnx":
                raise ImportError("no sherpa")
            return real_import(name, *args, **kwargs)

        engine("local")
        monkeypatch.delitem(sys.modules, "sherpa_onnx", raising=False)
        monkeypatch.setattr(builtins, "__import__", no_sherpa)
        result = preflight._transcription()
        assert result.status == Status.FAIL and "sherpa-onnx" in result.detail

    def test_local_with_no_model_yet_only_informs(self, engine, monkeypatch) -> None:
        from qurantext.config import preflight
        from qurantext.config.preflight import Status
        from qurantext.services import model_store

        engine("local")
        monkeypatch.setattr(model_store, "is_installed", lambda m: False)
        result = preflight._transcription()
        assert result.status == Status.WARN
        assert "first use" in result.detail

    def test_local_names_the_model_and_its_licence(self, engine, monkeypatch) -> None:
        from qurantext.config import preflight
        from qurantext.config.preflight import Status
        from qurantext.services import model_store

        engine("local")
        monkeypatch.setattr(model_store, "is_installed", lambda m: True)
        result = preflight._transcription()
        assert result.status == Status.OK
        assert "NVIDIA" in result.detail and "CC BY 4.0" in result.detail

    def test_no_replicate_token_is_not_a_problem_for_the_local_engine(self, engine, monkeypatch) -> None:
        from qurantext.config import preflight
        from qurantext.services import model_store

        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        engine("local")
        monkeypatch.setattr(model_store, "is_installed", lambda m: True)
        assert not preflight._transcription().blocking

    def test_whisperx_keeps_todays_token_check(self, engine, monkeypatch) -> None:
        from qurantext.config import preflight

        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        engine("whisperx")
        assert preflight._transcription() == preflight._whisperx_check()
```

Check that `tests/test_preflight.py` imports `sys` and `pytest`, and add either if it is missing. The existing Replicate tests in this file (around lines 240–270) call `_transcription()` expecting WhisperX behaviour. Make them set `QURANTEXT_TRANSCRIBE_ENGINE=whisperx` (with `get_settings.cache_clear()`), or call `_whisperx_check()` directly.

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/bin/python -m pytest tests/test_preflight.py -q -k TestTranscriptionCheck`
Expected: FAIL (`AttributeError: ... '_whisperx_check'`).

- [ ] **Step 3: Implement** in `preflight.py`

Rename today's `def _transcription() -> CheckResult:` to `def _whisperx_check() -> CheckResult:`, with its body unchanged. Add:

```python
_MODEL_CREDIT = (
    "NVIDIA FastConformer Arabic (stt_ar_fastconformer_hybrid_large_pcd_v1.0), CC BY 4.0"
)


def _transcription() -> CheckResult:
    """Check the engine that is configured, and only that one.

    Someone who transcribes on their own computer never needs a Replicate token,
    so its absence is not reported to them as a problem.
    """
    if get_settings().transcription.engine == "whisperx":
        return _whisperx_check()
    return _local_engine_check()


def _local_engine_check() -> CheckResult:
    try:
        import sherpa_onnx  # noqa: F401 — loading its native library is the point
    except Exception as error:  # noqa: BLE001 — any failure to load means the same thing here
        return CheckResult(
            "Transcription",
            Status.FAIL,
            f"the speech runtime (sherpa-onnx) did not load: {error}",
            "Transcription on this computer cannot start. Reinstall Qalun; from source, "
            "`pip install -e .` installs sherpa-onnx.",
        )
    from qurantext.services import model_store

    manifest = model_store.LOCAL_MODEL
    if not model_store.is_installed(manifest):
        return CheckResult(
            "Transcription",
            Status.WARN,
            f"on this computer with {_MODEL_CREDIT}; the model downloads once, on first "
            f"use (about {manifest.archive_size // 1_000_000} MB), into {model_store.models_dir()}",
            "Nothing to do: the first transcription downloads it. It needs an internet "
            "connection that one time.",
        )
    return CheckResult(
        "Transcription",
        Status.OK,
        f"on this computer with {_MODEL_CREDIT}, installed in {model_store.model_dir(manifest)}",
    )
```

If `get_settings` is not yet imported in `preflight.py`, import it from `qurantext.config.settings`. The existing `_whisperx_check` uses it already.

- [ ] **Step 4: Run the tests and lint, then commit**

```bash
venv/bin/python -m pytest -q && venv/bin/ruff check . && venv/bin/ruff format --check .
git add src/qurantext/config/preflight.py tests/test_preflight.py
git commit -m "Make the doctor check the transcription engine that is configured, naming the local model and its licence

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4.4: Licence notice and documentation

**Files:**
- Create: `THIRD_PARTY_NOTICES.md`
- Modify: `README.md`, `docs/architecture.md`, `docs/release-checklist.md`
- Test: `tests/test_packaging_spec.py` (the notice file exists and names the licence)

**Interfaces:**
- Produces: `THIRD_PARTY_NOTICES.md` at the repository root. Task 5.1 bundles it.

- [ ] **Step 1: Write the failing test** (append to `tests/test_packaging_spec.py`)

```python
def test_the_third_party_notice_credits_the_speech_model() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "stt_ar_fastconformer_hybrid_large_pcd_v1.0" in text
    assert "CC BY 4.0" in text
    assert "sherpa-onnx" in text and "Apache" in text
```

Run: `venv/bin/python -m pytest tests/test_packaging_spec.py -q -k notice`
Expected: FAIL (`FileNotFoundError`).

- [ ] **Step 2: Write `THIRD_PARTY_NOTICES.md`**

```markdown
# Third-party notices

## Speech recognition model

Qalun transcribes on your computer with **NVIDIA FastConformer Hybrid Large
(Arabic)**, `stt_ar_fastconformer_hybrid_large_pcd_v1.0`, © NVIDIA Corporation,
licensed under the Creative Commons Attribution 4.0 International licence
(CC BY 4.0): https://creativecommons.org/licenses/by/4.0/

Source: https://huggingface.co/nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0.
Changes: converted to ONNX for sherpa-onnx (transducer branch only), and
quantised to 8 bits for the int8 build. Qalun downloads it once, on first use,
from https://github.com/Grazyen96/qalun-models.

## sherpa-onnx

https://github.com/k2-fsa/sherpa-onnx, Apache License 2.0. It includes
ONNX Runtime (MIT License).
```

If Task 0.3 chose fp32, delete the quantisation sentence.

- [ ] **Step 3: Update the docs**

- `README.md`: in the "Transcribe audio" section, say that transcription runs on this computer by default (one model download of about 110 MB on first use), and that `--engine whisperx` or `QURANTEXT_TRANSCRIBE_ENGINE=whisperx` uses Replicate, which needs `REPLICATE_API_TOKEN`. In the `.env` section, say the token is needed **only** for WhisperX. In the layout listing, describe `services/` as "transcription engines (local model, WhisperX on Replicate) and the model store".
- `docs/architecture.md`: under `services`, replace the `transcription.py` line with one line each for `transcription.py` (the entry point, cache, engine choice), `engine_local.py`, `engine_whisperx.py`, `model_store.py` and `errors.py`. Under `core`, add `pause_cut.py` and `token_words.py`. In the data-flow steps, change "Load or transcribe WhisperX output" to "Load a saved transcript, or transcribe (local model by default, or WhisperX)".
- `docs/release-checklist.md`: add a step, "Publishing a new speech model: `tools/export_local_model/README.md`. Never replace a release asset in place."

- [ ] **Step 4: Run the tests and commit, then run the phase-end review**

```bash
venv/bin/python -m pytest -q && venv/bin/ruff check . && venv/bin/ruff format --check .
git add THIRD_PARTY_NOTICES.md README.md docs tests/test_packaging_spec.py
git commit -m "Credit the speech model and sherpa-onnx, and document the two transcription engines

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Phase-end review: one whole-branch review of Phase 4, one fix pass, then merge locally.

---

## Phase 5: Packaging and the release gate

### Task 5.1: Bundle sherpa-onnx and the notice

**Files:**
- Modify: `packaging/qalun.spec`
- Modify: `packaging/README.md` (Size section)
- Test: `tests/test_packaging_spec.py`

**Interfaces:**
- Consumes: the `sherpa-onnx` dependency (Task 3.4) and `THIRD_PARTY_NOTICES.md` (Task 4.4).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_packaging_spec.py`)

The file already defines `SPEC = .../packaging/qalun.spec`:

```python
def test_the_spec_collects_sherpa_onnx() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert 'collect_dynamic_libs("sherpa_onnx")' in text
    assert 'collect_submodules("sherpa_onnx")' in text


def test_the_spec_ships_the_third_party_notice() -> None:
    assert "THIRD_PARTY_NOTICES.md" in SPEC.read_text(encoding="utf-8")
```

Run: `venv/bin/python -m pytest tests/test_packaging_spec.py -q -k "sherpa or notice"`
Expected: FAIL.

- [ ] **Step 2: Edit `packaging/qalun.spec`**

Next to the existing `collect_*` calls:

```python
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

# The local transcription engine. Its wheel carries native libraries
# (sherpa-onnx's own and ONNX Runtime) that the import graph cannot see.
sherpa_binaries = collect_dynamic_libs("sherpa_onnx")
sherpa_hidden = collect_submodules("sherpa_onnx")
```

Add `sherpa_binaries` to the `Analysis(binaries=...)` list, and `sherpa_hidden` to `hiddenimports`. Add `("../THIRD_PARTY_NOTICES.md", ".")` to `datas`, using the same path style the spec already uses for the font and Quran text.

**Do not** touch the Pillow collection. `packaging/README.md` explains why.

- [ ] **Step 3: Build locally and run the doctor inside the bundle**

```bash
free -m | sed -n 2p
venv/bin/pip install pyinstaller && venv/bin/pyinstaller packaging/qalun.spec --noconfirm
du -sh dist/qalun
QT_QPA_PLATFORM=offscreen dist/qalun/qalun --doctor
QT_QPA_PLATFORM=offscreen dist/qalun/qalun --cli transcribe --engine local --audio input/recitations/furquanTra7-11.mp3 --output /tmp/claude-1000/frozen.json
```

Expected:
- the doctor's transcription line is not blocking and names the model and CC BY 4.0;
- the frozen transcription downloads the model (or reuses it from the cache) and writes JSON with more than 60 words;
- the bundle grows by under about 80 MB over today's.

- [ ] **Step 4: Record the size in `packaging/README.md`** under "Size", e.g. "sherpa-onnx and ONNX Runtime add about N MB. The speech model is not bundled: it downloads on first use."

- [ ] **Step 5: Run the tests and commit**

```bash
venv/bin/python -m pytest -q && venv/bin/ruff check . && venv/bin/ruff format --check .
git add packaging tests/test_packaging_spec.py
git commit -m "Bundle sherpa-onnx and the third-party notice into the desktop app

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5.2: The release gate proves the engine on all three platforms

**Files:**
- Modify: `.github/workflows/release.yml`
- Modify: `packaging/ci/README.md`
- Modify: `docs/release-checklist.md`

**Interfaces:**
- Consumes: `qalun --doctor --release` and `qalun --cli transcribe --engine local`.

- [ ] **Step 1: Add a gate step** to `release.yml`, after the existing doctor/gate step in the per-OS build job.

It runs inside the frozen app on each OS. A tone is generated with the FFmpeg the workflow already provides; it needs no recording in the repo, because the step proves that the runtime loads, the model downloads and verifies from the public release, and the output is valid. Recognition quality is covered by the parity gate.

```yaml
      - name: Local transcription works inside the frozen app
        shell: bash
        run: |
          ffmpeg -v error -f lavfi -i "sine=frequency=440:duration=5" -ac 1 -ar 16000 gate-tone.wav
          "$QALUN_EXE" --cli transcribe --engine local --no-cache --audio gate-tone.wav --output gate-tone.json
          python -c "import json; d=json.load(open('gate-tone.json')); assert 'segments' in d, d"
```

Set `QALUN_EXE` the same way the existing gate step locates the frozen executable on each OS; copy that expression from the step above. If FFmpeg is only beside the frozen executable, call that copy. The job's timeout must allow the about 110 MB download.

- [ ] **Step 2: Document the step** in `packaging/ci/README.md` and the release checklist: what it proves, and that a failure here usually means a broken `qalun-models` asset, a changed checksum, or a missing sherpa-onnx library in the bundle.

- [ ] **Step 3: Ask the user before pushing anything.** The release workflow runs on GitHub, which is outward-facing. The user decides when to push the branch and trigger *Run workflow*. After a run, read the three platform logs and report the gate step's result on each.

- [ ] **Step 4: Commit, then run the phase-end review**

```bash
git add .github/workflows/release.yml packaging/ci/README.md docs/release-checklist.md
git commit -m "Make the release gate run a local transcription inside the frozen app on every platform

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Phase-end review: one whole-branch review of Phase 5, one fix pass, then merge locally.

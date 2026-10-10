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
of `Grazyen96/qalun-models`. The `NOTICE.md` that belongs with it is
`tools/export_local_model/NOTICE.md` (a copy also sits in the variant directory,
inside the archive). `/tmp/qalun-release` also holds
`manifest_literal.py.txt`, which is pasted over `LOCAL_MODEL` in
`src/qurantext/services/model_store.py`. A new model version is a new
`--version`, a new release asset and a new pinned literal. Never replace an
asset in place: installed apps verify against the old checksum.

`package.py` writes the archive with fixed tar headers (no timestamps, no local
user name), so running it again on the same files gives the same bytes and the
same checksum. The literal therefore stays valid even if the release folder is
rebuilt before the upload.

Downloads are measurable without adding tracking to the app: GitHub counts each
release asset's downloads.

```bash
gh api repos/Grazyen96/qalun-models/releases/tags/model-v1 \
    --jq '.assets[] | {name, download_count}'
```

## Tested with

`export.py` was run on 2026-10-09 with nemo_toolkit 3.0.0, torch 2.14.1 (CPU),
onnx 1.23.2 and onnxruntime 1.31.0. The NeMo calls taken from the sherpa-onnx
script (`set_export_config({"decoder_type": "rnnt"})`, then `encoder`,
`decoder` and `joint` `.export()`) worked unchanged. The output was fp32
477,388,050 bytes and int8 136,477,730 bytes for the three ONNX files together.

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

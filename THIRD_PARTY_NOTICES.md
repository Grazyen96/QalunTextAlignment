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

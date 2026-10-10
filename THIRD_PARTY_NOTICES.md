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

The model is provided "as is", without warranties of any kind.

## sherpa-onnx

https://github.com/k2-fsa/sherpa-onnx, version 1.13.8 as published on PyPI.
sherpa-onnx's own code is under the Apache License 2.0; its licence text is in
the app's folder, at `_internal/sherpa_onnx/LICENSE`.

The bundled sherpa-onnx build is not under the Apache License 2.0 alone. Its
compiled libraries also contain the following components, each under its own
licence.

**GNU General Public License version 3 or later (GPL-3.0-or-later):**

- **espeak-ng**, https://github.com/espeak-ng/espeak-ng, including its
  `ucd-tools` library. sherpa-onnx uses it for text to speech, which Qalun does
  not use, but the PyPI build of sherpa-onnx links it statically into
  `_sherpa_onnx` (the Python extension the app loads) and into
  `libsherpa-onnx-c-api`. Found in the Linux build; the Windows and macOS builds
  of the same version offer the same text-to-speech functions and are expected
  to contain it too.

**MIT License:**

- **ONNX Runtime** 1.28.2, https://github.com/microsoft/onnxruntime, © Microsoft
  Corporation, the library sherpa-onnx runs the model with (`libonnxruntime`,
  `onnxruntime.dll`). Its licence text is in the app's folder, at
  `_internal/sherpa_onnx/lib/onnxruntime-LICENSE`. ONNX Runtime itself contains
  third-party code (among others protobuf, abseil, flatbuffers, ONNX and Eigen),
  whose licences and notices ONNX Runtime lists in its `ThirdPartyNotices.txt`:
  https://github.com/microsoft/onnxruntime/blob/v1.28.2/ThirdPartyNotices.txt
- **piper-phonemize**, https://github.com/rhasspy/piper-phonemize (text to
  speech, unused by Qalun).
- **cppjieba**, https://github.com/yanyiwu/cppjieba (Chinese word splitting,
  unused by Qalun).
- **nlohmann/json**, https://github.com/nlohmann/json.

**Apache License 2.0:**

- **kaldi-native-fbank**, https://github.com/csukuangfj/kaldi-native-fbank
- **kaldi-decoder**, https://github.com/k2-fsa/kaldi-decoder
- **kaldifst**, https://github.com/k2-fsa/kaldifst, and **OpenFst**,
  https://www.openfst.org
- **simple-sentencepiece**, https://github.com/pkufool/simple-sentencepiece

**BSD 3-Clause License:**

- **pybind11**, https://github.com/pybind/pybind11

## certifi

https://github.com/certifi/python-certifi, Mozilla Public License 2.0. Qalun
uses its certificate bundle (`cacert.pem`) to check the speech model's download.
The licence text is in the app's folder, at
`_internal/certifi-<version>.dist-info/licenses/LICENSE`.

## ALSA library (Linux builds only)

The Linux build includes `libasound` from alsa-lib,
https://github.com/alsa-project/alsa-lib, GNU Lesser General Public License
version 2.1. sherpa-onnx's Linux package brings it, and the app links it
dynamically, so it can be replaced with another build of the same library. The
licence text is in the app's folder, at
`_internal/sherpa_onnx.libs/libasound-LGPL-2.1.txt`.

# Third-party notices

## Qalun

Qalun is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License, version 3 only (GPL-3.0-only), as
published by the Free Software Foundation. The full text is in `LICENSE`, at
the top of the app zip and in the app's folder.

Copyright (C) 2026 Khalil

Qalun is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
details.

This licence covers Qalun's own code. It does not cover the bundled Quran font
and Quran text (see "Quran text and font" below), nor the components listed
after them, each of which is under its own licence.

**Source.** The source is inside the download. Every app zip carries, at its
top, beside `LICENSE` and this file:

- `qalun-source.zip`: the complete source of the commit the app was built from,
  including the build scripts (`packaging/`);
- `third-party-sources/`: the exact source archives of the GPL and LGPL
  components below that are not Qalun's own (espeak-ng in every zip, and the
  ALSA library in the Linux zip), with `SOURCES.txt` listing where each came
  from and its sha256. The build downloads them, checks each against the sha256
  pinned in `packaging/third-party-sources.txt`, and fails on a mismatch.

Each component listed below is under a licence compatible with GPL-3.0. The
speech model is not part of the app: it is data, downloaded on first use, under
CC BY 4.0.

**Where the files named below are.** On Windows and Linux, inside the app's
folder `qalun/`, under `_internal/`. On macOS, inside `Qalun.app`: licence texts
and other data under `Qalun.app/Contents/Resources/` (for example
`Contents/Resources/sherpa_onnx/LICENSE` where this file says
`_internal/sherpa_onnx/LICENSE`), and the libraries under
`Qalun.app/Contents/Frameworks/`.

## Quran text and font

These files ship inside the app, the Python package and `qalun-source.zip`:

- `qurantext/assets/fonts/qaloon.10.ttf` and `qaloon.10.woff2`: the Qalun
  Quran font;
- `qurantext/assets/quran/UthmanicQaloon1-v10.txt`: the Quran text in the
  Qalun riwaya.

They are third-party works and are **not** licensed under the GPL by Qalun's
licence statement above. Their provenance and terms are to be confirmed by the
owner, and will be stated here.

The Quran text is the KFGQPC (King Fahd Glorious Quran Printing Complex) Qaloon
text v10, obtained via `thetruetruth/quran-data-kfgqpc` at commit e35e7b5
(`qaloon/data/QaloonData_v10.json`) and converted by
`tools/convert_mushaf_v10.py`. Its source is recorded here; the terms on which it
may be redistributed are not, and are to be confirmed by the owner.

## Amiri font

The generated intro and outro write their titles in **Amiri**, release 1.003,
https://github.com/aliftype/amiri/releases/tag/1.003, Copyright 2010-2022 The
Amiri Project Authors (https://github.com/aliftype/amiri), licensed under the
SIL Open Font License, Version 1.1. These files ship unmodified inside the app,
the Python package and `qalun-source.zip`:

- `qurantext/assets/fonts/Amiri-Regular.ttf`, sha256
  `cd2550c0f4c05eb341bf97958211aaa39382bca96577ba3a67d4a3b4912c43c0`
- `qurantext/assets/fonts/Amiri-Bold.ttf`, sha256
  `8cfed49b66de57e360ac61631d882dddfa23095d3ddb39fc2133eaf93892e79a`

The licence text is beside them, at `qurantext/assets/fonts/Amiri-OFL.txt`
(in the app's folder, `_internal/qurantext/assets/fonts/Amiri-OFL.txt`), and in
the source at `packaging/licenses/Amiri-OFL.txt`. The OFL is not the GPL; it lets
the font be bundled with any software, and it stays under the OFL.

## Lucide icons

The window's icons are from **Lucide**, release 1.56.0,
https://github.com/lucide-icons/lucide/releases/tag/1.56.0, Copyright (c)
Lucide Icons and Contributors, licensed under the ISC License. Thirty-one SVG
files ship unmodified inside the app, the Python package and
`qalun-source.zip`, under `qurantext/assets/icons/` (in the app's folder,
`_internal/qurantext/assets/icons/`); the app recolours them when it draws
them. The licence text is beside them at `qurantext/assets/icons/LICENSE`
and in the source at `packaging/licenses/Lucide-LICENSE.txt`. The ISC
licence is compatible with the GPL-3.0-only licence of Qalun.

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

- **espeak-ng**, including its `ucd-tools` library. sherpa-onnx uses it for
  text to speech, which Qalun does not use, but the PyPI build of sherpa-onnx
  links it statically into `_sherpa_onnx` (the Python extension the app loads)
  and into `libsherpa-onnx-c-api`. Found in the Linux build; the Windows and
  macOS builds of the same version offer the same text-to-speech functions and
  are expected to contain it too. This is compatible with Qalun's licence:
  Qalun is GPL-3.0-only, and GPL-3.0-or-later code may be combined with it and
  distributed under GPL-3.0. The GPL-3.0 text is `LICENSE`.

  The code compiled is not upstream espeak-ng but a fork of it: sherpa-onnx
  v1.13.8 builds espeak-ng from
  https://github.com/csukuangfj/espeak-ng (itself a fork of
  https://github.com/rhasspy/espeak-ng) at commit
  `ed530aa113046142eb5115cf2fc9157854d0ffe1`, the archive
  `espeak-ng-ed530aa113046142eb5115cf2fc9157854d0ffe1.zip` with sha256
  `e4e262cbe34f7fe21f91f1ba3397f2728e1f30eafbae7853f2b753a9ed13f0dd`, as its
  `cmake/espeak-ng-for-piper.cmake` pins it. **That archive is in every app
  zip, at `third-party-sources/`.** sherpa-onnx's own source for this version is
  https://github.com/k2-fsa/sherpa-onnx/tree/v1.13.8, and its source
  distribution on PyPI, https://pypi.org/project/sherpa-onnx/1.13.8/#files.

**MIT License:**

- **ONNX Runtime** 1.28.2, https://github.com/microsoft/onnxruntime, © Microsoft
  Corporation, the library sherpa-onnx runs the model with (`libonnxruntime`,
  `onnxruntime.dll`). Its licence text is in the app's folder, at
  `_internal/sherpa_onnx/lib/onnxruntime-LICENSE`. ONNX Runtime itself contains
  third-party code (among others protobuf, abseil, flatbuffers, ONNX and Eigen),
  whose licences and notices ONNX Runtime lists in its `ThirdPartyNotices.txt`.
  That file is in the app's folder, at
  `_internal/sherpa_onnx/lib/onnxruntime-ThirdPartyNotices.txt`, copied from
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

**Mozilla Public License 2.0 (MPL-2.0):**

- **Eigen**, https://gitlab.com/libeigen/eigen, compiled into sherpa-onnx's C
  API library (`libsherpa-onnx-c-api`), which ships with the app but which it
  does not load. Its source is at that
  address; the MPL-2.0 text is https://mozilla.org/MPL/2.0/

**BSD 3-Clause License:**

- **pybind11**, https://github.com/pybind/pybind11
- **kissfft**, https://github.com/mborgerding/kissfft, compiled into the same C
  API library.

## ALSA library (Linux builds only)

The Linux build includes `libasound` from alsa-lib 1.2.12,
https://github.com/alsa-project/alsa-lib, GNU Lesser General Public License
version 2.1. sherpa-onnx's Linux package builds it from tag `v1.2.12` and
brings it, and the app links it dynamically, so it can be replaced with another
build of the same library. The licence text is in the app's folder, at
`_internal/sherpa_onnx.libs/libasound-LGPL-2.1.txt`. **Its source is in the
Linux app zip, at `third-party-sources/alsa-lib-1.2.12.tar.bz2`**, the alsa
project's release archive of that version
(https://www.alsa-project.org/files/pub/lib/alsa-lib-1.2.12.tar.bz2, sha256
`4868cd908627279da5a634f468701625be8cc251d84262c7e5b6a218391ad0d2`).

## certifi

https://github.com/certifi/python-certifi, Mozilla Public License 2.0. Qalun
uses its certificate bundle (`cacert.pem`) to check the speech model's download.
The licence text is in the app's folder, at
`_internal/certifi-<version>.dist-info/licenses/LICENSE`.

## segno

https://github.com/heuer/segno, version 1.6.6 as published on PyPI, © Lars
Heuer, BSD 3-Clause License. Qalun uses it to encode the generated outro's QR
code. The licence text is in the app's folder, at `_internal/segno-LICENSE.txt`.

## idna

https://github.com/kjd/idna, version 3.13 as published on PyPI, © Kim Davies and contributors,
BSD 3-Clause License. Qalun uses it to turn an international host name in the
outro's link into the form the QR code carries, as browsers do. The licence
text is in the app's folder, at `_internal/idna-3.13.dist-info/licenses/LICENSE.md`.

## The rest of the app

The app is built with PyInstaller from the following, each bundled in the app's
folder.

- **Python** 3.12, https://www.python.org, the interpreter and its standard
  library, Python Software Foundation License (PSF-2.0). Python links further
  libraries, each under its own permissive licence (among them OpenSSL, Apache
  2.0; libffi, MIT; zlib; bzip2; XZ; SQLite, public domain; Expat, MIT).
- **PyInstaller's bootloader**, https://pyinstaller.org, the start-up code of
  the `qalun` executable: GPL-2.0-or-later with PyInstaller's bootloader
  exception, which allows it to be distributed with any program.
- **Qt 6** through **PySide6** and **Shiboken6**, https://www.qt.io and
  https://wiki.qt.io/Qt_for_Python, GNU Lesser General Public License version 3
  (LGPL-3.0), linked dynamically (`_internal/PySide6/`). Qt itself contains
  third-party code listed at https://doc.qt.io/qt-6/licenses-used-in-qt.html;
  its playback uses the FFmpeg libraries PySide6 ships (LGPL builds).
- **Pillow**, https://github.com/python-pillow/Pillow, the HPND licence
  (Historical Permission Notice and Disclaimer). Its package brings its own
  image and text libraries (among them libjpeg-turbo, libpng, libtiff, libwebp,
  OpenJPEG, Little CMS, FreeType, HarfBuzz and raqm), whose licences Pillow
  lists in its `LICENSE`.
- **NumPy**, https://numpy.org, BSD 3-Clause License. Its package brings
  OpenBLAS (BSD 3-Clause) and, on Linux, the GCC Fortran runtime
  (`libgfortran`, GPL-3.0-or-later with the GCC Runtime Library Exception);
  NumPy lists them in its `LICENSE.txt`.
- **FriBiDi**, https://github.com/fribidi/fribidi, GNU Lesser General Public
  License version 2.1 or later, loaded by Pillow at runtime to shape Arabic
  (`fribidi-0.dll`, `libfribidi.dylib` or `libfribidi.so.0` beside the
  executable). The build copies it from MSYS2 (Windows), Homebrew (macOS) or
  Ubuntu (Linux).
- **FFmpeg**, https://ffmpeg.org, the `ffmpeg` and `ffprobe` programs beside
  the executable, which Qalun runs as separate programs to read audio and write
  video. These are GPL builds (GNU General Public License, version 2 or later or
  3 or later depending on the build), taken from gyan.dev or BtbN (Windows),
  Homebrew (macOS) and johnvansickle.com or BtbN (Linux).
- **The Replicate client** (Apache 2.0), used only by the optional WhisperX
  engine, with httpx, httpcore and idna (BSD 3-Clause), anyio, h11, pydantic,
  pydantic-core, annotated-types and typing-inspection (MIT), typing-extensions
  (PSF-2.0) and packaging (Apache 2.0 or BSD 2-Clause), and **PyYAML** (MIT).
- On Linux, the build machine's system libraries that Qt and the other
  libraries link (among them GLib, GTK, ICU, PulseAudio, libsndfile and the X11
  and xcb libraries), each under its distribution's licence.

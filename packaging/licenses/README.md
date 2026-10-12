# Licence texts the build has to supply

The spec copies these into the bundle beside the binaries they cover, because
the wheels the binaries come from do not carry them.

- `onnxruntime-LICENSE`: ONNX Runtime, MIT License, © Microsoft Corporation.
  The sherpa-onnx wheel ships `libonnxruntime` (`.so`, `.dylib` or `.dll`) inside
  `sherpa_onnx/lib/` but not its licence. Copied verbatim from
  https://github.com/microsoft/onnxruntime/blob/main/LICENSE (fetched 10 Oct 2026).

- `libasound-LGPL-2.1.txt`: the GNU Lesser General Public License, version 2.1,
  for ALSA's `libasound` (alsa-lib, https://github.com/alsa-project/alsa-lib).
  sherpa-onnx's Linux wheel vendors it as `sherpa_onnx.libs/libasound-*.so.2.0.0`
  (alsa-lib 1.2.12 in sherpa-onnx 1.13.8), linked dynamically, without its
  licence. The spec ships this beside it only when the installed wheel carries
  it, so Linux builds only. Copied verbatim from
  https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt (fetched 10 Oct 2026).

- `onnxruntime-ThirdPartyNotices.txt`: the notices for the third-party code
  inside ONNX Runtime (protobuf, abseil, flatbuffers, ONNX, Eigen and others),
  which their licences ask to reproduce with the binary. Not in the sherpa-onnx
  wheel either; shipped beside `onnxruntime-LICENSE`. Copied verbatim from
  https://github.com/microsoft/onnxruntime/blob/v1.28.2/ThirdPartyNotices.txt
  (fetched 10 Oct 2026). 1.28.2 is the ONNX Runtime the sherpa-onnx 1.13.8 wheel
  bundles: its `libonnxruntime.so` defines its symbols under the version
  `VERS_1.28.2` (`nm -D --defined-only ... | grep VERS`). Fetch it again from
  the matching tag whenever the sherpa-onnx pin moves.

- `segno-LICENSE.txt`: segno, BSD 3-Clause License, © Lars Heuer, the QR
  encoder for the generated outro. Its wheel does carry this file, in its
  `.dist-info`, but segno is pure Python, so PyInstaller puts its code inside
  the app's archive and leaves the metadata out; the spec ships this copy
  beside `THIRD_PARTY_NOTICES.md` instead. Copied verbatim from the installed
  segno 1.6.6 (`segno-1.6.6.dist-info/licenses/LICENSE`, fetched 12 Oct 2026);
  `tests/test_packaging_spec.py` fails if it stops matching the installed one.

- `Amiri-OFL.txt`: the SIL Open Font License 1.1 for the Amiri font, the
  release's own `OFL.txt` from
  https://github.com/aliftype/amiri/releases/tag/1.003 (`Amiri-1.003.zip`,
  fetched 12 Oct 2026). The same file sits beside the fonts in
  `src/qurantext/assets/fonts/`, so the wheel carries it too, and the spec's
  copy of `assets/` puts it beside them in the app; it is kept here with the
  other licence texts, and a test holds the two copies equal.

sherpa-onnx's own licence (Apache 2.0) is not here: its wheel carries it, and the
spec takes it from the installed distribution so it always matches the version built.

The licence texts are not the whole obligation for the GPL and LGPL code: its
source has to travel with the app too. `packaging/third-party-sources.txt` pins
those source archives (espeak-ng for every platform, alsa-lib for Linux) by URL
and sha256, and `packaging/ci/package.sh` puts them in every app zip under
`third-party-sources/`. sherpa-onnx is pinned exactly (`sherpa-onnx==1.13.8` in
`pyproject.toml`), so these files and that list always describe the build that
ships; `tests/test_packaging_spec.py` fails if the installed version differs.

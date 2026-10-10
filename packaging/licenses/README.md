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

ONNX Runtime's `ThirdPartyNotices.txt` (the notices for the code inside ONNX
Runtime) is not in the sherpa-onnx wheel either, and is not kept here yet:
`THIRD_PARTY_NOTICES.md` links the copy for the bundled version, 1.28.2.

sherpa-onnx's own licence (Apache 2.0) is not here: its wheel carries it, and the
spec takes it from the installed distribution so it always matches the version built.

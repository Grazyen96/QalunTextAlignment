# Licence texts the build has to supply

The spec copies these into the bundle beside the binaries they cover, because
the wheels the binaries come from do not carry them.

- `onnxruntime-LICENSE`: ONNX Runtime, MIT License, © Microsoft Corporation.
  The sherpa-onnx wheel ships `libonnxruntime` (`.so`, `.dylib` or `.dll`) inside
  `sherpa_onnx/lib/` but not its licence. Copied verbatim from
  https://github.com/microsoft/onnxruntime/blob/main/LICENSE (fetched 10 Oct 2026).

sherpa-onnx's own licence (Apache 2.0) is not here: its wheel carries it, and the
spec takes it from the installed distribution so it always matches the version built.

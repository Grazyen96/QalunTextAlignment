# Packaging

**You probably do not need any of this.** GitHub builds the app for all three
platforms on its own machines — see `.github/workflows/release.yml`. Push a tag
or press *Run workflow* in the Actions tab, and download the zips. Nobody needs
Python installed: not the people who use the app, and not the person releasing
it. What follows is for building by hand.

Before tagging a release, work through
[docs/release-checklist.md](../docs/release-checklist.md): what has to be checked by
hand, on real machines, because CI cannot.

Builds the desktop app as a self-contained bundle. `qalun.spec` is shared by all
three platforms; what differs is the wrapper around the result and the signing.

```bash
pip install -e '.[gui]' pyinstaller
pyinstaller packaging/qalun.spec --noconfirm
```

Verified on Linux: the bundle runs with no Python, no virtual environment and no
repository present, builds the Quran store into the platform data directory,
renders a video using the font from inside the bundle, and writes sidecar
subtitles with the Arabic intact, and transcribes on the computer with
sherpa-onnx. About 317 MB, before FFmpeg and FriBiDi are copied in (see Size).

The frozen app can diagnose itself, which matters because a packaged app that
will not render is exactly when there is no Python to run anything else with:

```
qalun --doctor          what works on this machine, and what to do about the rest
qalun --cli <command>   any command-line subcommand
```

To test playback and fonts, the doctor starts a Qt application of its own (offscreen on
Linux, the native one on Windows and macOS), so it can take a few seconds. An exported
`QT_QPA_PLATFORM` is honoured: over SSH with `QT_QPA_PLATFORM=xcb` and no display, Qt
aborts the doctor instead of letting it report, so unset it or set it to `offscreen`.
The doctor keeps the FFmpeg plugin's own log out of its report (`QT_LOGGING_RULES`), and
`--doctor --release` asks Qt for the FFmpeg multimedia backend (`QT_MEDIA_BACKEND`) and
fails unless the test recording played through it.

## Per platform

| | Windows | Ubuntu | macOS |
|---|---|---|---|
| Wrapper | Inno Setup or MSIX | AppImage or a tarball | `Qalun.app`, made by the spec |
| Signing | Authenticode | not required | `codesign` then `notarytool`, mandatory |
| FriBiDi | ship it beside the executable | ship it beside the executable | ship it beside the executable |
| FFmpeg | ship beside the executable | ship beside the executable | ship beside the executable |

Build on the platform you are shipping to. PyInstaller does not cross-compile.

## Two things that are easy to get wrong

**Do not add `collect_dynamic_libs("PIL")`.** PyInstaller's Pillow hook already
collects Pillow's own libraries into `pillow.libs/` with the right search path.
Adding them again puts a second copy at the bundle root, where Pillow's HarfBuzz
shadows the one Qt ships. Note this does not get you FriBiDi, which is not in
the wheel to collect — see below.

**FriBiDi has to be supplied, on every platform.** Pillow links raqm and
HarfBuzz statically but loads FriBiDi by name at runtime, because FriBiDi is
LGPL and loading it at runtime is what keeps the wheel redistributable. No
Pillow wheel for any platform contains one. Without it Pillow reports no raqm
support, Arabic does not shape, and the renderer refuses to draw. A developer
never notices, because `apt` or Homebrew already put one on the system; a person
who downloads the app has nothing. The build copies one in beside the executable
and the app loads it itself at startup, rather than trusting three different
loaders to find a bare name in the application directory — which Windows does,
Linux does only because PyInstaller arranges it, and macOS does not do at all.
See `qurantext.config.fribidi`.

**`multiprocessing.freeze_support()` belongs behind a Windows check.** It is only
needed where a frozen app re-executes itself to start a child process. Called
unconditionally it hung this build on Linux before a line of our own code ran,
which is a hard failure to diagnose because there is no output at all. Nothing
here uses multiprocessing anyway.

## FFmpeg

Not bundled by the spec, because the binary is large and which build you may
redistribute depends on how it was compiled. The release workflow fetches one
per platform and copies it into the app folder.

Copying it there is enough: `require_binary` looks beside the running executable
before it looks at `PATH`, so a packaged app uses the FFmpeg it shipped with and
a user who has installed nothing still gets a video. Verified by rendering with
an empty `PATH`. `--doctor` reports which one was found and its version.

## Size

Playback (Qt Multimedia, from PySide6-Addons) is the one thing the review editor
added to the bundle. Measured on Linux, 24 Sep 2026, PyInstaller 6.22, PySide6 6.11.2,
FFmpeg and FriBiDi not included (they are the same before and after):

| | folder | zip |
|---|---|---|
| before (Multimedia excluded) | 249 MB | 144 MB |
| after | 275 MB | 164 MB |
| difference | 26 MB | 20 MB |

These zips were made the way the release workflow made them until then, with
Python's `shutil.make_archive`, which stores each of the bundle's 59 symlinked
libraries a second time (the zip unpacks to 446 MB). `packaging/ci/package.sh`
keeps the links: the same after-bundle zips to 113 MB and unpacks to the 275 MB
folder. The workflow's Package step runs it; see [ci/README.md](ci/README.md).

### The local transcription engine

sherpa-onnx and the ONNX Runtime inside it take about 42 MB of the bundle
(`_internal/sherpa_onnx/` 37 MB, `_internal/sherpa_onnx.libs/` 5 MB, the ALSA
library the wheel vendors). The speech model is not bundled: it downloads on
first use (about 110 MB) into the cache folder. Measured on Linux, 10 Oct 2026,
PyInstaller 6.22.3, sherpa-onnx 1.13.8, FFmpeg and FriBiDi not included, zips
made with `zip -qry` as `package.sh` makes them:

| | folder | zip |
|---|---|---|
| spec before this change | 312 MB | 120 MB |
| after | 317 MB | 122 MB |
| difference | 5 MB | 2 MB |
| with FFmpeg and FriBiDi copied in | 470 MB | |

The difference is small because PyInstaller already found most of the engine on
its own: it follows the engine's import inside a function, and the Python
extension's linked libraries (ONNX Runtime, ALSA). What the spec adds by naming
it is sherpa-onnx's C and C++ API libraries, which the analysis cannot see, and
the certainty that a release never depends on the analysis following a lazy
import. Against the 275 MB of 24 Sep, the bundle has grown 42 MB, nearly all of
it the engine.

The spec also ships, beside the engine's binaries, the licences that have to
travel with them: `sherpa_onnx/LICENSE` (Apache 2.0, from the wheel) and
`sherpa_onnx/lib/onnxruntime-LICENSE` (MIT, kept in [licenses/](licenses/)
because the wheel does not carry it), and `THIRD_PARTY_NOTICES.md` at the top of
`_internal/`. And it ships certifi's `cacert.pem`, which the model download
trusts alongside the system's certificates. Verified in the frozen app with the
system's certificates hidden (`SSL_CERT_FILE` and `SSL_CERT_DIR` pointed at
nothing): the download completes through certifi alone, and fails with
`CERTIFICATE_VERIFY_FAILED` once certifi's file is removed too.

The PyPI build of sherpa-onnx is not Apache/MIT only: it links espeak-ng
(GPL-3.0-or-later), for its text to speech, statically into the extension the
app loads. `THIRD_PARTY_NOTICES.md` names it and the other components inside the
build. Releasing is blocked until the owner decides how to resolve it; see
[docs/release-checklist.md](../docs/release-checklist.md) and the "Licence
finding" in [docs/findings/asr-bakeoff.md](../docs/findings/asr-bakeoff.md).

**ONNX Runtime telemetry (Windows): not verified on the binary.** Qalun collects no
usage data: the app opens a connection only to download the speech model and,
when someone chooses it, to transcribe online with WhisperX. ONNX Runtime's Windows builds *can* emit usage events through Windows'
own event tracing (TraceLogging), which Windows' diagnostic service may upload;
Microsoft's official builds have it on, builds from source have it off unless
built with `--use_telemetry`. What was checked (10 Oct 2026, by reading, not on
a Windows machine):

- sherpa-onnx's `cmake/onnxruntime-win-x64.cmake` takes ONNX Runtime 1.28.2 not
  from Microsoft but from `csukuangfj/onnxruntime-libs`, and that repository's
  `windows-x64.yaml` workflow builds `onnxruntime.dll` from source with
  `tools/ci_build/build.py` and no `--use_telemetry` (it copies only the headers,
  `LICENSE`, `ThirdPartyNotices.txt` and similar files from Microsoft's zip). So
  the DLL in the Windows wheel is very likely not a telemetry build.
- The Linux `libonnxruntime.so` is such a custom build too (source paths under
  `/shared/onnxruntime/`), and on Linux ONNX Runtime has no telemetry provider.
- Neither sherpa-onnx's Python API nor anything Qalun loads exposes ONNX
  Runtime's `DisableTelemetryEvents`, so the app cannot switch it off itself.
  The C API has it, but it needs the `OrtEnv` sherpa-onnx keeps to itself.

Not checked: the DLL inside the sherpa-onnx 1.13.8 Windows wheel itself, which
needs that wheel or a Windows machine. Until then, "no telemetry" holds for
Qalun's own code, and for ONNX Runtime on Windows only as far as the above goes.

Windows and macOS: record from the first release-workflow run after this change
(the zip sizes on the run's summary page) — see
[docs/release-checklist.md](../docs/release-checklist.md).

## Not done here

Signing and notarization need the target machines and your certificates, so they
are documented rather than scripted. On macOS, `codesign --deep --options
runtime` then `notarytool submit --wait`; on Windows, `signtool sign /fd sha256
/tr <timestamp server>`.

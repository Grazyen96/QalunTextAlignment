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
subtitles with the Arabic intact. About 275 MB, before FFmpeg and FriBiDi are
copied in (see Size).

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
folder. The workflow uses it once its Package step is changed; see
[ci/README.md](ci/README.md).

Windows and macOS: record from the first release-workflow run after this change
(the zip sizes on the run's summary page) — see
[docs/release-checklist.md](../docs/release-checklist.md).

## Not done here

Signing and notarization need the target machines and your certificates, so they
are documented rather than scripted. On macOS, `codesign --deep --options
runtime` then `notarytool submit --wait`; on Windows, `signtool sign /fd sha256
/tr <timestamp server>`.

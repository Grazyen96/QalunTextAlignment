# Packaging

**You probably do not need any of this.** GitHub builds the app for all three
platforms on its own machines — see `.github/workflows/release.yml`. Push a tag
or press *Run workflow* in the Actions tab, and download the zips. Nobody needs
Python installed: not the people who use the app, and not the person releasing
it. What follows is for building by hand.

Builds the desktop app as a self-contained bundle. `qalun.spec` is shared by all
three platforms; what differs is the wrapper around the result and the signing.

```bash
pip install -e '.[gui]' pyinstaller
pyinstaller packaging/qalun.spec --noconfirm
```

Verified on Linux: the bundle runs with no Python, no virtual environment and no
repository present, builds the Quran store into the platform data directory,
renders a video using the font from inside the bundle, and writes sidecar
subtitles with the Arabic intact. About 223 MB.

The frozen app can diagnose itself, which matters because a packaged app that
will not render is exactly when there is no Python to run anything else with:

```
qalun --doctor          what works on this machine, and what to do about the rest
qalun --cli <command>   any command-line subcommand
```

## Per platform

| | Windows | Ubuntu | macOS |
|---|---|---|---|
| Wrapper | Inno Setup or MSIX | AppImage or a tarball | `Qalun.app`, made by the spec |
| Signing | Authenticode | not required | `codesign` then `notarytool`, mandatory |
| FriBiDi | ship `fribidi.dll` beside the executable | collected from the build machine | collected from the build machine |
| FFmpeg | ship beside the executable | ship beside the executable | ship beside the executable |

Build on the platform you are shipping to. PyInstaller does not cross-compile.

## Two things that are easy to get wrong

**Do not add `collect_dynamic_libs("PIL")`.** PyInstaller's Pillow hook already
collects raqm, HarfBuzz and FriBiDi into `pillow.libs/` with the right search
path. Adding them again puts a second copy at the bundle root, where Pillow's
HarfBuzz shadows the one Qt ships.

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

## Not done here

Signing and notarization need the target machines and your certificates, so they
are documented rather than scripted. On macOS, `codesign --deep --options
runtime` then `notarytool submit --wait`; on Windows, `signtool sign /fd sha256
/tr <timestamp server>`.

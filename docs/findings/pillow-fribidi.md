# No Pillow wheel ships FriBiDi, so a packaged app must

**Date:** 2026-09-13. **Found by:** the macOS build failing its own preflight.

## What happened

The first macOS build produced an app that ran, opened, found its font and its
FFmpeg, and could not draw a single Arabic glyph:

```
[FAIL] Arabic shaping  Pillow 12.3.0 has no raqm support (has ; missing harfbuzz, fribidi)
```

Linux had passed. The obvious reading — that the Mac was missing two libraries —
is wrong, and the message saying so was itself a bug.

## What is actually true

Pillow links raqm and HarfBuzz **statically** into `_imagingft`, and loads
FriBiDi **by name at runtime**. That is a licensing decision: FriBiDi is LGPL,
and dlopening it is what lets the wheel be redistributed.

The consequence is that no Pillow wheel on any platform contains a FriBiDi
library. Opening the 12.3.0 wheels:

| wheel | raqm | HarfBuzz | FriBiDi |
| --- | --- | --- | --- |
| `win_amd64` | no | no | no |
| `manylinux_2_28_x86_64` | no | vendored | no |
| `macosx_11_0_arm64` | no | vendored | no |

The names it asks the loader for, read out of the compiled module rather than
the documentation:

| platform | asks for |
| --- | --- |
| Windows | `fribidi-0.dll`, `libfribidi-0.dll`, `fribidi.dll` |
| macOS | `libfribidi.dylib`, `libfribidi.0.dylib` |
| Linux | `libfribidi.so.0`, `libfribidi.so` |

And because Pillow reports the HarfBuzz and FriBiDi versions *through* raqm,
losing FriBiDi makes all three read as missing. That is why the message
implicated HarfBuzz, which was present and fine the whole time.

## Why only the Mac failed

Every developer machine has a FriBiDi: `apt install libfribidi0` put one there,
or Homebrew did. The Linux CI image ships one too. The macOS image does not.
Nobody who works on this project would ever have hit it, and every person who
downloads the app would have.

## The fix, and why it is not "copy the file in"

Shipping the library is half of it. Pillow asks the loader for a bare name, and
a bare name is not resolved the same way everywhere. Windows searches the folder
the executable is in. Linux searches what the loader was told at exec, which for
a frozen app PyInstaller arranges. macOS searches neither — only `DYLD_*` paths
and the system directories — so a copy sitting beside the executable is
invisible to it.

So the app loads the library itself, by absolute path, before anything imports
Pillow (`qurantext.config.fribidi`, called from the frozen entry point). Every
one of those loaders answers a bare-name request with an already-loaded library
of that name instead of searching again.

Verified on Linux with a purpose-built library whose SONAME nothing on the
system can resolve: the bare-name request fails, the same request succeeds after
the library is preloaded by absolute path. Windows and macOS rest on the same
principle but were not verified locally; the build's `--doctor` gate is what
confirms them, per platform, before anything is shipped.

## Two things this changed besides the packaging

* The preflight remedy used to end "Then reinstall Pillow." Reinstalling Pillow
  can never help, since no wheel has the library. It now names FriBiDi as the
  one missing piece, and tells a packaged user it is a build fault rather than
  something to fix on their machine.
* The preflight FFmpeg check searched `PATH` while the renderer searched beside
  the executable first. A stripped-`PATH` run of the built app reported two
  failures for a build that would have rendered perfectly. Both now ask the same
  way. A check that disagrees with the code it checks is worse than no check.

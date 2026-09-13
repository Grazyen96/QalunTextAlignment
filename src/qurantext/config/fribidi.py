"""Make FriBiDi findable in a packaged app, so Arabic shapes.

Pillow links raqm and HarfBuzz statically but loads FriBiDi by *name* at
runtime. That is a licensing decision, not an oversight: FriBiDi is LGPL, and
asking the loader for it at runtime keeps the wheel redistributable. The
consequence is that **no PyPI Pillow wheel contains FriBiDi** — verified by
opening the Windows, macOS and Linux wheels for 12.3.0, none of which holds a
FriBiDi library of any name. Whoever runs the app has to supply one.

A developer never notices, because the system has one: `apt install libfribidi0`
put it there, or Homebrew did. Someone who downloads an app and double-clicks it
has installed nothing, and without FriBiDi Pillow reports no raqm support, the
renderer refuses to draw, and every Arabic frame is lost. This was the whole of
the macOS build failure.

So the app ships its own copy — and shipping it is only half the job. Pillow asks
the loader for a bare name ("libfribidi.dylib", "fribidi-0.dll"), and a bare name
is not resolved the same way everywhere: Windows searches the folder the
executable is in, Linux searches what the loader was told at exec, and macOS
searches neither, only DYLD paths and /usr/lib. Relying on any of that is relying
on a different mechanism per platform, one of which does not work.

Loading the library here first, by absolute path, sidesteps all three. Every one
of those loaders answers a bare-name request with an already-loaded library of
that name rather than searching again, so Pillow's request is satisfied by the
copy we chose. It has to happen before ``PIL.ImageFont`` is first imported.

Doing nothing is always safe. Outside a frozen app this is a no-op — a checkout
uses the system library, as it always did. If the bundled copy is missing or
will not load, Pillow simply falls back to no raqm, preflight reports Arabic
shaping as failed, and the person gets a message naming the cause.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

__all__ = ["fribidi_names", "preload_fribidi"]


def fribidi_names() -> tuple[str, ...]:
    """The file names Pillow asks the loader for, on this platform.

    Taken from the strings embedded in Pillow's own ``_imagingft`` module rather
    than from its documentation, so this list is what the code actually requests.
    """
    if sys.platform == "win32":
        return ("fribidi-0.dll", "libfribidi-0.dll", "fribidi.dll")
    if sys.platform == "darwin":
        return ("libfribidi.dylib", "libfribidi.0.dylib")
    return ("libfribidi.so.0", "libfribidi.so")


def preload_fribidi() -> str | None:
    """Load the FriBiDi shipped beside the executable. Returns its path, or None.

    None is not an error: it means this is not a packaged app, or no copy was
    shipped, in which case the system library is used exactly as before.
    """
    if not getattr(sys, "frozen", False):
        return None

    directory = Path(sys.executable).resolve().parent

    # On Windows the library may have been built against sibling runtime DLLs.
    # Loading by absolute path does not put that folder on the search path for
    # its dependencies, so say so explicitly first.
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(directory))
        except OSError:
            pass

    for name in fribidi_names():
        candidate = directory / name
        if not candidate.is_file():
            continue
        try:
            ctypes.CDLL(str(candidate), mode=getattr(ctypes, "RTLD_GLOBAL", 0))
        except OSError:
            continue
        return str(candidate)
    return None

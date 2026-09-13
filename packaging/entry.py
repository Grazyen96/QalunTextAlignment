"""Frozen-app entry point.

A separate file rather than a console script, because PyInstaller analyses a
script and the shim pip generates for a console script is not one.

It also has to answer for itself. A packaged app that will not render is exactly
when someone needs ``doctor``, and there is no ``python -m qurantext`` inside a
frozen build, so the flags are handled here before Qt is touched.

This is also the only place early enough to load the bundled FriBiDi, which has
to be in the process before anything imports Pillow's font module. See
:mod:`qurantext.config.fribidi`.
"""

from __future__ import annotations

import sys

USAGE = """Qalun — turn Arabic audio into a subtitled video.

  qalun                 open the window
  qalun --doctor        check this machine can render, and say what to fix
  qalun --cli ...       run a command-line subcommand, e.g. --cli preview --help
  qalun --version       print the version
"""


def _attach_console() -> None:
    """On Windows, print into the console that launched us.

    The app is built windowed so that double-clicking it does not flash a black
    box. The cost is that a windowed process starts with no standard output at
    all, so ``qalun --doctor`` typed into a terminal printed nothing whatsoever —
    the one command someone runs when the app will not work was silent. Windows
    lets a process adopt its parent's console after the fact; do that, and only
    for the text commands, so the window still opens clean.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        import ctypes

        ATTACH_PARENT_PROCESS = -1
        if not ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            return
        for stream, target in (("stdout", "w"), ("stderr", "w")):
            try:
                setattr(sys, stream, open("CONOUT$", target, encoding="utf-8", errors="replace"))
            except OSError:
                pass
    except Exception:
        # Never let diagnostics stop the command the person actually asked for.
        pass


def _save_report(report: str) -> str | None:
    """Keep the doctor's report on disk, so it can be sent to someone."""
    try:
        from qurantext.config.paths import user_data_dir

        destination = user_data_dir() / "doctor-report.txt"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(report, encoding="utf-8")
        return str(destination)
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    # Before anything imports Pillow. A packaged app carries its own FriBiDi
    # because no Pillow wheel contains one, and without it Arabic does not
    # shape and the renderer refuses to draw. A no-op outside a frozen build.
    from qurantext.config.fribidi import preload_fribidi

    preload_fribidi()

    # freeze_support() is only needed where a frozen app re-executes itself to
    # start a child process, which means Windows. Calling it unconditionally
    # hung this build on Linux before a line of our own code ran, and nothing
    # here uses multiprocessing anyway — parallel rendering was measured and
    # declined, see docs/findings/parallel-rendering.md.
    if sys.platform == "win32":
        import multiprocessing

        multiprocessing.freeze_support()

    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] in ("-h", "--help"):
        _attach_console()
        print(USAGE)
        return 0

    if args and args[0] == "--version":
        _attach_console()
        from qurantext import __version__

        print(f"qalun {__version__}")
        return 0

    if args and args[0] == "--doctor":
        from qurantext.config.preflight import Status, format_report, run_checks

        _attach_console()
        results = run_checks()
        report = format_report(results)
        print(report)
        saved = _save_report(report)
        if saved:
            print(f"\nA copy of this report was saved to {saved}")
        return 1 if any(r.status == Status.FAIL for r in results) else 0

    if args and args[0] == "--cli":
        _attach_console()
        from qurantext.cli.main import main as cli_main

        return cli_main(args[1:])

    from qurantext.gui import main as gui_main

    return gui_main([sys.argv[0], *args])


if __name__ == "__main__":
    raise SystemExit(main())

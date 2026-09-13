"""Frozen-app entry point.

A separate file rather than a console script, because PyInstaller analyses a
script and the shim pip generates for a console script is not one.

It also has to answer for itself. A packaged app that will not render is exactly
when someone needs ``doctor``, and there is no ``python -m qurantext`` inside a
frozen build, so the flags are handled here before Qt is touched.
"""

from __future__ import annotations

import sys

USAGE = """Qalun — turn Arabic audio into a subtitled video.

  qalun                 open the window
  qalun --doctor        check this machine can render, and say what to fix
  qalun --cli ...       run a command-line subcommand, e.g. --cli preview --help
  qalun --version       print the version
"""


def main(argv: list[str] | None = None) -> int:
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
        print(USAGE)
        return 0

    if args and args[0] == "--version":
        from qurantext import __version__

        print(f"qalun {__version__}")
        return 0

    if args and args[0] == "--doctor":
        from qurantext.config.preflight import Status, format_report, run_checks

        results = run_checks()
        print(format_report(results))
        return 1 if any(r.status == Status.FAIL for r in results) else 0

    if args and args[0] == "--cli":
        from qurantext.cli.main import main as cli_main

        return cli_main(args[1:])

    from qurantext.gui import main as gui_main

    return gui_main([sys.argv[0], *args])


if __name__ == "__main__":
    raise SystemExit(main())

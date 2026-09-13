#!/usr/bin/env python3
"""Compatibility wrapper for the packaged detect-range workflow.

The standalone parser this used to reach is gone; the package CLI is now the
only one. Arguments are forwarded verbatim, and the main parser accepts
``--whisperx`` as an alias of ``--whisperx-json`` so old command lines keep
working.

Prefer ``python3 -m qurantext range-match ...`` for new usage.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

# The old flag chose the workflow; the package CLI uses a subcommand instead.
_MODE_TO_COMMAND = {
    "range": "range-match",
    "lecture": "lecture-match",
    "recitation": "recitation-match",
}


def _forwarded_argv(argv: list[str]) -> list[str]:
    """Turn `--mode X` into the matching subcommand, defaulting to range-match."""
    mode = "range"
    remaining: list[str] = []
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--mode" and index + 1 < len(argv):
            mode = argv[index + 1]
            index += 2
            continue
        if item.startswith("--mode="):
            mode = item.split("=", 1)[1]
            index += 1
            continue
        remaining.append(item)
        index += 1

    command = _MODE_TO_COMMAND.get(mode)
    if command is None:
        raise SystemExit(f"Unknown --mode {mode!r}. Choose from: {', '.join(_MODE_TO_COMMAND)}.")
    return [command, *remaining]


def main(argv: list[str] | None = None) -> int:
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    from qurantext.cli.main import main as cli_main

    return cli_main(_forwarded_argv(list(argv if argv is not None else sys.argv[1:])))


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run the packaged legacy word-alignment workflow."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"


def main(argv: list[str] | None = None) -> int:
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    from qurantext.cli.main import main as cli_main

    forwarded_argv = ["word-align", *(argv or sys.argv[1:])]
    return cli_main(forwarded_argv)


if __name__ == "__main__":
    raise SystemExit(main())

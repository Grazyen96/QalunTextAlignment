#!/usr/bin/env python3
"""Compatibility wrapper for the packaged video-rendering workflow.

The standalone parser this used to reach is gone; the package CLI is now the
only one, and arguments are forwarded verbatim.

Prefer ``python3 -m qurantext generate-video ...`` for new usage.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"


def main(argv: list[str] | None = None) -> int:
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    from qurantext.cli.main import main as cli_main

    return cli_main(["generate-video", *(argv if argv is not None else sys.argv[1:])])


if __name__ == "__main__":
    raise SystemExit(main())

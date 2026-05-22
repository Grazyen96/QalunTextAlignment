#!/usr/bin/env python3
"""Run the packaged video-rendering workflow."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"


def main(argv: list[str] | None = None) -> int:
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    import qurantext.compat as compat

    return compat.run_module_main("qurantext.pipelines.video", argv)


if __name__ == "__main__":
    raise SystemExit(main())

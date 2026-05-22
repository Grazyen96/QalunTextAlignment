"""Compatibility exports for project environment loading."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"


def load_project_env() -> None:
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    import qurantext.compat as compat

    compat.export_public_names("qurantext.config.settings")["load_project_env"]()


__all__ = ["load_project_env"]

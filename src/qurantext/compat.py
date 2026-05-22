from __future__ import annotations

import importlib
from typing import Any


def run_module_main(module_name: str, argv: list[str] | None = None) -> int:
    """Import a module lazily and invoke its ``main`` function."""
    module = importlib.import_module(module_name)
    return module.main(argv)


def export_public_names(module_name: str) -> dict[str, Any]:
    """Return the public attributes from a lazily imported compatibility target."""
    module = importlib.import_module(module_name)
    return {name: getattr(module, name) for name in dir(module) if not name.startswith("_")}


__all__ = ["export_public_names", "run_module_main"]


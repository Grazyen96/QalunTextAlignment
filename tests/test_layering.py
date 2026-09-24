"""``core/`` is the engine every front end stands on, so it never reaches up into them.

``jobs/`` and ``gui/`` import ``core/``; a ``core/`` module importing either
turns that into a cycle waiting to happen, and makes the engine unusable
without the window or the job layer. Imports are read from the source with
``ast`` rather than by importing, so a lazy import inside a function counts too.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1] / "src" / "qurantext" / "core"
FORBIDDEN = ("qurantext.jobs", "qurantext.gui")


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    """Every absolute module name *path* imports, with its line number.

    Relative imports are resolved against ``qurantext.core``, so
    ``from ..jobs import render`` is caught as ``qurantext.jobs``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = "qurantext.core".split(".")[: 2 - node.level + 1]
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            found.append((node.lineno, module))
    return found


def _is_forbidden(module: str) -> bool:
    return any(module == name or module.startswith(name + ".") for name in FORBIDDEN)


@pytest.mark.parametrize("path", sorted(CORE.glob("*.py")), ids=lambda p: p.name)
def test_core_never_imports_jobs_or_gui(path: Path) -> None:
    bad = [
        f"{path.name}:{line} imports {module}"
        for line, module in _imported_modules(path)
        if _is_forbidden(module)
    ]
    assert not bad, "; ".join(bad)


def test_relative_imports_are_resolved_against_core(tmp_path: Path) -> None:
    """The checker itself: a relative reach into jobs/ is caught, a sibling import is not."""
    source = tmp_path / "probe.py"
    source.write_text(
        "from ..jobs import render\nfrom . import video_common\nimport qurantext.gui.app\n",
        encoding="utf-8",
    )
    modules = [module for _, module in _imported_modules(source)]
    assert modules == ["qurantext.jobs", "qurantext.core", "qurantext.gui.app"]
    assert [_is_forbidden(module) for module in modules] == [True, False, True]

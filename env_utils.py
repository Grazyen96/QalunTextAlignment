from __future__ import annotations

import os
from pathlib import Path


def _parse_env_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    if line.startswith("export "):
        line = line[len("export "):].strip()

    if "=" not in line:
        return None

    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()

    if not key:
        return None

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]

    return key, value


def _load_env_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return

    with path.open(encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            parsed = _parse_env_line(raw_line)
            if parsed is None:
                continue
            key, value = parsed
            if not value and os.environ.get(key):
                continue
            os.environ[key] = value


def load_project_env() -> None:
    """
    Load environment variables from project-local `.env` files.

    Precedence:
    1. Existing process environment wins over `.env`
    2. `.env.local` overrides `.env`

    This keeps shell-exported values authoritative while still making local
    development work without manually exporting variables first.
    """
    project_root = Path(__file__).resolve().parent

    existing_env = dict(os.environ)
    _load_env_file(project_root / ".env")
    _load_env_file(project_root / ".env.local")

    for key, value in existing_env.items():
        os.environ[key] = value


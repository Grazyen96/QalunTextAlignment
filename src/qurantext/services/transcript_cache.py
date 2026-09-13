"""Remember a transcript so the same audio is never sent twice.

Recognition is the one stage that is slow, billed and needs the network. It is
also perfectly repeatable: the same audio and the same settings give the same
transcript. Without a cache, correcting one subtitle line and re-rendering paid
for the whole recording again.

The key is the audio's content, not its path, so renaming or moving a file still
hits, and editing it does not. Settings that change the output are part of the
key too, so changing the model or the language recognises again rather than
returning something stale.

Cached files are derived data: deleting the cache directory costs one
re-transcription and nothing else.
"""

from __future__ import annotations

import hashlib
import json
from os import PathLike
from pathlib import Path
from typing import Any

from qurantext.config.paths import user_cache_dir

__all__ = ["cache_key", "cache_path", "load_cached", "store_cached"]

_CHUNK = 1 << 20


def _audio_digest(audio_path: Path) -> str:
    digest = hashlib.sha256()
    with audio_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_key(audio_path: str | PathLike[str], settings: dict[str, Any]) -> str:
    """A key over the audio's bytes and the settings that shape the result."""
    payload = json.dumps(settings, sort_keys=True, ensure_ascii=False, default=str)
    combined = hashlib.sha256()
    combined.update(_audio_digest(Path(audio_path)).encode("ascii"))
    combined.update(b"\0")
    combined.update(payload.encode("utf-8"))
    return combined.hexdigest()


def cache_path(key: str, *, root: Path | None = None) -> Path:
    base = root if root is not None else user_cache_dir() / "transcripts"
    # One level of fan-out keeps a big cache directory listable.
    return base / key[:2] / f"{key}.json"


def load_cached(key: str, *, root: Path | None = None) -> dict | list | None:
    """The cached transcript for *key*, or None. A damaged entry is a miss."""
    path = cache_path(key, root=root)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def store_cached(key: str, output: dict | list, *, root: Path | None = None) -> Path | None:
    """Save a transcript. Returns None when the cache cannot be written to.

    A cache that cannot be written is not an error worth failing a job over, so
    this reports rather than raises.
    """
    path = cache_path(key, root=root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written beside the target and moved, so a crash mid-write cannot leave
        # a half-file that would later be read as a hit.
        temporary = path.with_suffix(".partial")
        temporary.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        return path
    except OSError:
        return None

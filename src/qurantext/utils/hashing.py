"""Content digests shared by the caches.

The transcript cache and the waveform cache both key on a recording's bytes,
not its path, so a renamed file still hits and an edited one misses. One
function keeps the two keys the same.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

__all__ = ["audio_digest"]

_CHUNK = 1 << 20


def audio_digest(audio_path: Path) -> str:
    """SHA-256 of the audio file's bytes, read in chunks."""
    digest = hashlib.sha256()
    with Path(audio_path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()

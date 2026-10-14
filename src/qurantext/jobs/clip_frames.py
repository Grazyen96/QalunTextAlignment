"""A still from a video clip, for the Episode dialog's cards.

ffmpeg writes the clip's middle frame as a PNG under the same ``thumbs``
cache the home list's thumbnails use, keyed by the clip's path, time and
size, so a clip is read once however often the dialog opens. Everything that
can go wrong (no ffmpeg, a file that is not a video, a slow decode, a cache
that cannot be written) gives ``None``: the card then shows an icon, and the
dialog opens all the same. Runs where it is called: the dialog already reads
each clip with ffprobe on the UI thread, and a frame costs about as much.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from qurantext.core.video_common import require_binary

__all__ = ["TIMEOUT_S", "clip_frame"]

_log = logging.getLogger(__name__)

#: A frame that takes longer than this is not worth the wait.
TIMEOUT_S = 10


def clip_frame(
    path: Path, cache_dir: Path | None, *, seconds: float | None, long_side: int = 176
) -> Path | None:
    """The PNG of *path*'s frame at ``seconds / 2`` (0 when unknown), *long_side* wide or tall.

    Served from the cache when it is there; ``None`` for anything that fails.
    """
    if cache_dir is None:
        return None
    part: Path | None = None
    try:
        path = Path(path)
        stat = path.stat()
        folder = Path(cache_dir) / "thumbs"
        folder.mkdir(parents=True, exist_ok=True)
        raw = f"clip|{path}|{stat.st_mtime_ns}|{stat.st_size}|{long_side}"
        key = hashlib.sha1(raw.encode("utf-8")).hexdigest()  # noqa: S324 - a cache name
        target = folder / f"clip-{key}.png"
        if target.is_file():
            return target
        ffmpeg = require_binary("ffmpeg")
        at = max(0.0, (seconds or 0.0) / 2)
        scale = f"scale='if(gt(iw,ih),{long_side},-1)':'if(gt(iw,ih),-1,{long_side})'"
        handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed at once, replaced below
            dir=folder, prefix=".", suffix=".png.part", delete=False
        )
        handle.close()
        part = Path(handle.name)
        # A seek past the picture's end (a short sting under a longer sound) exits 0 and
        # writes nothing: try the first frame then, and cache nothing if that is empty too.
        for seek in (at, 0.0) if at > 0 else (at,):
            subprocess.run(
                [
                    ffmpeg, "-y", "-nostdin", "-v", "error",
                    "-ss", f"{seek:.3f}", "-i", str(path),
                    "-frames:v", "1", "-vf", scale, "-c:v", "png", "-f", "image2", "-update", "1",
                    str(part),
                ],
                check=True,
                timeout=TIMEOUT_S,
                capture_output=True,
            )  # fmt: skip
            if part.stat().st_size > 0:
                os.replace(part, target)
                part = None
                return target
        _log.debug("No frame for %s: ffmpeg wrote nothing", path)
        return None
    except Exception as error:  # noqa: BLE001 - a picture is never worth a failed dialog
        _log.debug("No frame for %s: %s", path, error)
        return None
    finally:
        if part is not None:
            part.unlink(missing_ok=True)

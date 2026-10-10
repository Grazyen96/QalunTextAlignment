"""The local speech model: where it lives, and fetching it once.

The model is too large to ship inside the installer, so the first local
transcription downloads it. Everything about that download is pinned in code —
the URL, the archive's size and checksum, every file's size and checksum — so
the app never fetches anything it has not been told to trust, and a new model
version is a deliberate code change. The folder is derived data: deleting it
costs one download.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from qurantext.config.paths import user_cache_dir
from qurantext.services.errors import ModelDownloadError
from qurantext.utils.progress import CancelToken, JobCancelled, ProgressCallback, report

__all__ = [
    "ModelFile",
    "ModelManifest",
    "discard",
    "ensure_model",
    "is_installed",
    "model_dir",
    "models_dir",
    "verify_installed",
]

_BLOCK = 1 << 20
_TIMEOUT_SECONDS = 30
_SPACE_MARGIN = 1.10
#: One download at a time: a second job waits for the first one's model.
_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class ModelFile:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ModelManifest:
    model_id: str
    version: str
    url: str
    archive_size: int
    archive_sha256: str
    files: tuple[ModelFile, ...]

    @property
    def ref(self) -> str:
        return f"{self.model_id}@{self.version}"

    @property
    def folder_name(self) -> str:
        return f"{self.model_id.replace('/', '--')}-{self.version}"

    @property
    def unpacked_size(self) -> int:
        return sum(f.size for f in self.files)

    def digest(self) -> str:
        """Changes when anything pinned changes, so a new model transcribes again."""
        payload = json.dumps(asdict(self), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def models_dir() -> Path:
    return user_cache_dir() / "models"


def model_dir(manifest: ModelManifest) -> Path:
    return models_dir() / manifest.folder_name


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(_BLOCK), b""):
            h.update(block)
    return h.hexdigest()


def is_installed(manifest: ModelManifest) -> bool:
    """Every file is there with its pinned size. Cheap: run before every job."""
    folder = model_dir(manifest)
    return all(
        (folder / f.name).is_file() and (folder / f.name).stat().st_size == f.size
        for f in manifest.files
    )


def verify_installed(manifest: ModelManifest) -> bool:
    """Every file matches its pinned checksum. Slow: run when loading failed."""
    folder = model_dir(manifest)
    return is_installed(manifest) and all(
        _sha256(folder / f.name) == f.sha256 for f in manifest.files
    )


def discard(manifest: ModelManifest) -> None:
    shutil.rmtree(model_dir(manifest), ignore_errors=True)


def _mb(n: int) -> str:
    return f"{n / 1_000_000:.0f} MB"


def ensure_model(
    manifest: ModelManifest,
    *,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> Path:
    """The model's folder, downloading and installing it first if needed."""
    with _LOCK:
        if is_installed(manifest):
            return model_dir(manifest)
        root = models_dir()
        root.mkdir(parents=True, exist_ok=True)
        need = int((manifest.archive_size + manifest.unpacked_size) * _SPACE_MARGIN)
        free = shutil.disk_usage(root).free
        if free < need:
            raise ModelDownloadError(
                f"Not enough free disk space for the speech model: it needs {_mb(need)} "
                f"in {root}, and {_mb(free)} is free."
            )
        part = root / f"{manifest.folder_name}.tar.bz2.part"
        part.unlink(missing_ok=True)
        try:
            _download(manifest, part, progress, cancel)
            return _install(manifest, part)
        finally:
            part.unlink(missing_ok=True)


def _download(
    manifest: ModelManifest,
    part: Path,
    progress: ProgressCallback | None,
    cancel: CancelToken | None,
) -> None:
    digest = hashlib.sha256()
    done = 0
    started = time.monotonic()
    try:
        with urllib.request.urlopen(manifest.url, timeout=_TIMEOUT_SECONDS) as response:
            with part.open("wb") as out:
                while block := response.read(_BLOCK):
                    out.write(block)
                    digest.update(block)
                    done += len(block)
                    fraction = min(1.0, done / manifest.archive_size)
                    elapsed = time.monotonic() - started
                    eta = elapsed / fraction - elapsed if fraction > 0.01 else None
                    report(
                        progress,
                        "download",
                        f"Downloading the speech model, once: {_mb(done)} of "
                        f"{_mb(manifest.archive_size)}",
                        fraction=fraction,
                        eta_seconds=eta,
                    )
                    if cancel is not None:
                        cancel.raise_if_cancelled("download")
    except JobCancelled:
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise ModelDownloadError(
            "The speech model is downloaded once, on first use, and that download "
            f"failed ({error}). Check the internet connection and start the job again, "
            "or choose WhisperX online."
        ) from error
    if done != manifest.archive_size or digest.hexdigest() != manifest.archive_sha256:
        raise ModelDownloadError(
            "The downloaded speech model is damaged (its checksum does not match), so "
            "it was deleted. Start the job again to download it again."
        )
    report(progress, "download", "Downloaded the speech model.", fraction=1.0, done=True)


def _install(manifest: ModelManifest, part: Path) -> Path:
    """Unpack the pinned files only, verify them, and move the folder in at once."""
    root = models_dir()
    target = model_dir(manifest)
    tmp = Path(tempfile.mkdtemp(prefix=f".{manifest.folder_name}-", dir=root))
    try:
        try:
            with tarfile.open(part, "r:bz2") as tar:
                for f in manifest.files:
                    source = tar.extractfile(tar.getmember(f.name))
                    if source is None:
                        raise KeyError(f.name)
                    with source, (tmp / f.name).open("wb") as out:
                        shutil.copyfileobj(source, out, _BLOCK)
        except (OSError, KeyError, tarfile.TarError) as error:
            raise ModelDownloadError(
                f"The speech model could not be unpacked into {root} ({error})."
            ) from error
        if any(_sha256(tmp / f.name) != f.sha256 for f in manifest.files):
            raise ModelDownloadError(
                "The downloaded speech model is damaged (a file's checksum does not "
                "match), so it was deleted. Start the job again to download it again."
            )
        shutil.rmtree(target, ignore_errors=True)
        tmp.rename(target)
        return target
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

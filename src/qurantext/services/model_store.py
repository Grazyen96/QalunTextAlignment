"""The local speech model: where it lives, and fetching it once.

The model is too large to ship inside the installer, so the first local
transcription downloads it. Everything about that download is pinned in code —
the URL, the archive's size and checksum, every file's size and checksum — so
the app never fetches anything it has not been told to trust, and a new model
version is a deliberate code change. The folder is derived data: deleting it
costs one download.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import json
import os
import shutil
import ssl
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO

from qurantext.config.paths import user_cache_dir
from qurantext.services.errors import ModelDownloadError
from qurantext.utils.progress import CancelToken, JobCancelled, ProgressCallback, report

__all__ = [
    "LOCAL_MODEL",
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
#: Progress is said at most this often: a read returns whatever has arrived, often a few KB.
_REPORT_EVERY_SECONDS = 0.2
#: A temporary download or folder this old was left by a run that crashed or was
#: killed; a live run touches its own far more often than this.
_STALE_AFTER_SECONDS = 3600
#: Putting the folder in place is tried this often, this far apart: on Windows an
#: antivirus scan can hold a freshly written file for a moment.
_PLACE_ATTEMPTS = 5
_PLACE_PAUSE_SECONDS = 0.2
#: One download at a time within this process: a second job waits for the first
#: one's model. Other processes are not waited for; each downloads under its own
#: temporary names, and the first verified folder moved in is the one kept.
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

    @property
    def download_mb(self) -> int:
        """The download's size for people, rounded to ten MB: 110 in "about 110 MB"."""
        return max(10, round(self.archive_size / 10_000_000) * 10)

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


def _complete(folder: Path, manifest: ModelManifest) -> bool:
    """Every pinned file is in *folder* with its pinned size."""
    return all(
        (folder / f.name).is_file() and (folder / f.name).stat().st_size == f.size
        for f in manifest.files
    )


def is_installed(manifest: ModelManifest) -> bool:
    """Every file is there with its pinned size. Cheap: run before every job."""
    return _complete(model_dir(manifest), manifest)


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


def _check(cancel: CancelToken | None, stage: str) -> None:
    if cancel is not None:
        cancel.raise_if_cancelled(stage)


def _remove(path: Path) -> None:
    """Delete *path*, a file or a folder, as far as it can be; never raises."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def _temporary_prefix(manifest: ModelManifest) -> str:
    """What every temporary name of *manifest*'s install starts with, in the models folder."""
    return f".{manifest.folder_name}-"


def _clear_stale(manifest: ModelManifest, root: Path) -> None:
    """Delete the partial downloads and half-unpacked folders a crashed run left.

    Every run names its own, so only those old enough that no live run can still
    be writing them go. Run before measuring free space, which they would count against.
    """
    cutoff = time.time() - _STALE_AFTER_SECONDS
    for path in root.glob(f"{_temporary_prefix(manifest)}*"):
        with contextlib.suppress(OSError):
            if path.lstat().st_mtime < cutoff:
                _remove(path)


def _folder_error(root: Path, error: OSError) -> ModelDownloadError:
    return ModelDownloadError(
        f"The speech model's folder {root} could not be prepared ({error}). Check that "
        "it can be written to, then start the job again, or choose WhisperX online."
    )


def _damaged(detail: str) -> ModelDownloadError:
    return ModelDownloadError(
        f"The downloaded speech model is damaged ({detail}), so it was deleted. "
        "Start the job again to download it again."
    )


def ensure_model(
    manifest: ModelManifest,
    *,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> Path:
    """The model's folder, downloading and installing it first if needed.

    Safe across processes as well as threads: each run downloads and unpacks
    under its own temporary names, and moves its folder in only once every file
    is verified. Two processes starting at once may both download; both end
    with the same verified folder, and neither removes the other's.
    """
    _check(cancel, "download")
    with _LOCK:
        if is_installed(manifest):
            return model_dir(manifest)
        _check(cancel, "download")
        root = models_dir()
        try:
            root.mkdir(parents=True, exist_ok=True)
            _clear_stale(manifest, root)
            free = shutil.disk_usage(root).free
        except OSError as error:
            raise _folder_error(root, error) from error
        need = int((manifest.archive_size + manifest.unpacked_size) * _SPACE_MARGIN)
        if free < need:
            raise ModelDownloadError(
                f"Not enough free disk space for the speech model: it needs {_mb(need)} "
                f"in {root}, and {_mb(free)} is free."
            )
        try:
            handle, name = tempfile.mkstemp(
                prefix=_temporary_prefix(manifest), suffix=".tar.bz2.part", dir=root
            )
            os.close(handle)
        except OSError as error:
            raise _folder_error(root, error) from error
        part = Path(name)
        try:
            _download(manifest, part, progress, cancel)
            return _install(manifest, part, progress, cancel)
        finally:
            _remove(part)


def _ssl_context() -> ssl.SSLContext:
    """The system's trusted certificates, plus certifi's bundle when it is there.

    A frozen app's OpenSSL looks for certificates where the build machine kept
    them, which a person's Mac or another Linux does not have. certifi's bundle
    travels with the app; adding it keeps the system's own (a company's root on
    Windows, say) trusted too.
    """
    context = ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        return context
    with contextlib.suppress(OSError, ssl.SSLError):
        context.load_verify_locations(cafile=certifi.where())
    return context


@contextlib.contextmanager
def _saving(part: Path) -> Iterator[None]:
    """Say a failure to write the download as the disk's problem, not the network's."""
    try:
        yield
    except OSError as error:
        raise ModelDownloadError(
            f"The speech model could not be saved in {part.parent} ({error}). Free some "
            "disk space, then start the job again."
        ) from error


def _download(
    manifest: ModelManifest,
    part: Path,
    progress: ProgressCallback | None,
    cancel: CancelToken | None,
) -> None:
    size = manifest.archive_size
    # Without a fraction, so a window says the stage's own sentence first.
    report(
        progress,
        "download",
        f"Downloading the speech model, once (about {manifest.download_mb} MB)...",
    )
    _check(cancel, "download")
    digest = hashlib.sha256()
    done = 0
    started = time.monotonic()
    said: float | None = None
    try:
        with urllib.request.urlopen(
            manifest.url, timeout=_TIMEOUT_SECONDS, context=_ssl_context()
        ) as response:
            _check_length(manifest, response.headers.get("Content-Length"))
            with _saving(part):
                out: BinaryIO = open(part, "wb")  # closed by the with below
            with out:
                # read1 returns what has arrived, so cancel and progress keep up on a
                # slow link; asking for one byte past the pinned size catches a body
                # that is too long without ever writing it.
                while block := response.read1(min(_BLOCK, size - done + 1)):
                    if done + len(block) > size:
                        raise _wrong_file(manifest, f"more than {size:,} bytes")
                    with _saving(part):
                        out.write(block)
                    digest.update(block)
                    done += len(block)
                    now = time.monotonic()
                    if said is None or now - said >= _REPORT_EVERY_SECONDS or done == size:
                        said = now
                        fraction = done / size
                        elapsed = now - started
                        eta = elapsed / fraction - elapsed if fraction > 0.01 else None
                        report(
                            progress,
                            "download",
                            f"Downloading the speech model, once: {_mb(done)} of {_mb(size)}",
                            fraction=fraction,
                            eta_seconds=eta,
                        )
                    _check(cancel, "download")
                with _saving(part):
                    out.flush()
    except (JobCancelled, ModelDownloadError):
        raise
    except urllib.error.HTTPError as error:
        error.close()  # it holds the answer's connection open
        if error.code in (404, 410):
            advice = "Update Qalun to get the model's current address"
        else:
            advice = "Start the job again later"
        raise ModelDownloadError(
            f"The speech model could not be downloaded: its address answered HTTP "
            f"{error.code} ({error.reason}). {advice}, or choose WhisperX online."
        ) from error
    except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
        raise ModelDownloadError(
            "The speech model is downloaded once, on first use, and that download "
            f"failed ({error}). Check the internet connection and start the job again, "
            "or choose WhisperX online."
        ) from error
    if done < size:
        raise ModelDownloadError(
            f"The speech model's download was interrupted after {_mb(done)} of "
            f"{_mb(size)}. Check the internet connection and start the job again, or "
            "choose WhisperX online."
        )
    if digest.hexdigest() != manifest.archive_sha256:
        raise _damaged("its checksum does not match")
    report(progress, "download", "Downloaded the speech model.", fraction=1.0, done=True)


def _check_length(manifest: ModelManifest, header: str | None) -> None:
    """Refuse, before reading a byte, a body the server says is not the pinned size."""
    if header is None:
        return
    try:
        length = int(header)
    except ValueError:
        return
    if length != manifest.archive_size:
        raise _wrong_file(manifest, f"{length:,} bytes")


def _wrong_file(manifest: ModelManifest, got: str) -> ModelDownloadError:
    return ModelDownloadError(
        f"The speech model's address sent a different file ({got} instead of the pinned "
        f"{manifest.archive_size:,}), so it was not kept. Update Qalun, or choose "
        "WhisperX online."
    )


def _install(
    manifest: ModelManifest,
    part: Path,
    progress: ProgressCallback | None,
    cancel: CancelToken | None,
) -> Path:
    """Unpack the pinned files only, verify them, and move the folder in at once."""
    report(progress, "unpack", "Unpacking and checking the speech model...")
    root = models_dir()
    try:
        tmp = Path(tempfile.mkdtemp(prefix=_temporary_prefix(manifest), dir=root))
    except OSError as error:
        raise _folder_error(root, error) from error
    try:
        _unpack(manifest, part, tmp, cancel)
        return _place(manifest, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _unpack(manifest: ModelManifest, part: Path, tmp: Path, cancel: CancelToken | None) -> None:
    """Write each pinned file once into *tmp*, checking its checksum as it is written.

    One pass over the archive: a member is taken only when it is a regular file,
    named in the manifest, of its pinned size, and seen for the first time.
    Anything else named in the manifest fails the install; anything not named in
    it is skipped and never written.
    """
    pinned = {f.name: f for f in manifest.files}
    found: set[str] = set()
    try:
        with tarfile.open(part, "r|bz2") as tar:
            for member in tar:
                pin = pinned.get(member.name)
                if pin is None:
                    continue
                if member.name in found or not member.isreg() or member.size != pin.size:
                    raise _damaged(f"{member.name} is not the pinned file")
                found.add(member.name)
                source = tar.extractfile(member)
                if source is None:
                    raise _damaged(f"{member.name} could not be read")
                digest = hashlib.sha256()
                with source, (tmp / pin.name).open("wb") as out:
                    while block := source.read(_BLOCK):
                        out.write(block)
                        digest.update(block)
                        _check(cancel, "unpack")
                if digest.hexdigest() != pin.sha256:
                    raise _damaged(f"the checksum of {pin.name} does not match")
    except (OSError, EOFError, tarfile.TarError) as error:
        raise ModelDownloadError(
            f"The speech model could not be unpacked into {tmp.parent} ({error})."
        ) from error
    missing = sorted(pinned.keys() - found)
    if missing:
        raise _damaged(f"{', '.join(missing)} missing")


def _place(manifest: ModelManifest, tmp: Path) -> Path:
    """Move the verified *tmp* in as the model's folder, in one rename.

    The folder may already be there: another process may have put its own
    verified copy in first, and that one is kept (it may be loading it). Only a
    folder that is not a complete install is moved aside and deleted.
    """
    target = model_dir(manifest)
    error: OSError | None = None
    for attempt in range(_PLACE_ATTEMPTS):
        if attempt > 1:
            time.sleep(_PLACE_PAUSE_SECONDS)
        try:
            tmp.rename(target)
            return target
        except OSError as caught:
            error = caught
        if is_installed(manifest):
            return target
        _set_aside(manifest, target)
    if is_installed(manifest):
        return target
    raise ModelDownloadError(
        f"The speech model could not be put in place at {target} ({error}). Close "
        "other Qalun windows, delete that folder, and start the job again."
    )


def _set_aside(manifest: ModelManifest, target: Path) -> None:
    """Move an incomplete *target* out of the way, and delete it.

    The move is atomic, so a complete folder another process put in after the
    last check is never half deleted: it is found complete and put back.
    """
    aside = target.with_name(f"{_temporary_prefix(manifest)}old-{uuid.uuid4().hex[:8]}")
    try:
        target.rename(aside)
    except OSError:
        return  # gone already, or held open: the next attempt says which
    if _complete(aside, manifest):
        with contextlib.suppress(OSError):
            aside.rename(target)
            return
    _remove(aside)


#: The model the local engine runs. Pinned: produced by
#: tools/export_local_model/package.py, published as release model-v1 of the
#: public Grazyen96/qalun-models repo. Never edit by hand; re-run the tool.
LOCAL_MODEL = ModelManifest(
    model_id="nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0",
    version="int8-1",
    url="https://github.com/Grazyen96/qalun-models/releases/download/model-v1/stt_ar_fastconformer_hybrid_large_pcd_v1.0-int8-1.tar.bz2",
    archive_size=108151682,
    archive_sha256="bc9956a0f6485a797545b1240d63c43fb05f92a5c1ce0d5fb9818f31a4592d01",
    files=(
        ModelFile(
            "encoder.onnx",
            131113685,
            "891c7b36e01d6a0da1c14e3507b4bb7084b7753f9fc2f26736471d5af26bfded",
        ),
        ModelFile(
            "decoder.onnx",
            3955864,
            "ebfe9bc355b9c591331c54ad5f84eac9d6af187ffca407e2dd19e4af8255f87b",
        ),
        ModelFile(
            "joiner.onnx",
            1408181,
            "a0397fa92f0e361e92237de874dfdbe0093c5034873525388e391aac08b5500b",
        ),
        ModelFile(
            "tokens.txt",
            12858,
            "9b938381a19a69bb279cdcfc299419f25a049ea1de192e0d10317274a0f20074",
        ),
        ModelFile(
            "NOTICE.md",
            582,
            "2df87de3c00dbecf15de3dd0a2472e4ad67083ebc419d07b398ca35cbe59b3b0",
        ),
    ),
)

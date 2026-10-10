from __future__ import annotations

import builtins
import contextlib
import hashlib
import io
import os
import ssl
import sys
import tarfile
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qurantext.services import model_store
from qurantext.services.errors import ModelDownloadError
from qurantext.services.model_store import ModelFile, ModelManifest
from qurantext.utils.progress import CancelToken, JobCancelled

FILES = {"encoder.onnx": b"E" * 3000, "tokens.txt": "▁ق 0\n<blk> 1\n".encode()}


def _archive(files: dict[str, bytes], *, extra: tuple[tarfile.TarInfo, ...] = ()) -> bytes:
    """A bz2 tar of *files*, then any *extra* members (links, devices) as they are."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for info in extra:
            tar.addfile(info)
    return buf.getvalue()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Server:
    """Serves /model.tar.bz2, and /redirect answering 302 to it, counting requests.

    What it answers can be changed per test: *status* other than 200 answers
    that error, *length* is the Content-Length sent ("auto" for the body's,
    None for none), *raw* replaces the whole answer with those bytes, and
    *before_body* runs after the headers (to hold two requests together), and
    *between* runs after the body's first KiB (to trickle it).
    """

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requests = 0
        self.status = 200
        self.length: str | int | None = "auto"
        self.raw: bytes | None = None
        self.before_body = None
        self.between = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 — http.server's name
                outer.requests += 1
                if outer.raw is not None:
                    self.wfile.write(outer.raw)
                    return
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/model.tar.bz2")
                    self.end_headers()
                    return
                if outer.status != 200:
                    self.send_error(outer.status)
                    return
                self.send_response(200)
                if outer.length == "auto":
                    self.send_header("Content-Length", str(len(outer.body)))
                elif outer.length is not None:
                    self.send_header("Content-Length", str(outer.length))
                self.end_headers()
                if outer.before_body is not None:
                    outer.before_body()
                with contextlib.suppress(OSError):  # the client may have given up
                    if outer.between is None:
                        self.wfile.write(outer.body)
                        return
                    self.wfile.write(outer.body[:1024])
                    self.wfile.flush()
                    outer.between()
                    self.wfile.write(outer.body[1024:])

            def log_message(self, *_args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, args=(0.02,), daemon=True).start()

    def url(self, path: str = "/model.tar.bz2") -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("QURANTEXT_CACHE_DIR", str(tmp_path / "cache"))
    return tmp_path / "cache"


@pytest.fixture
def server():
    s = _Server(_archive(FILES))
    yield s
    s.close()


def _manifest(server, *, url=None, archive_sha=None, files=None) -> ModelManifest:
    body = server.body
    return ModelManifest(
        model_id="test/model",
        version="t-1",
        url=url or server.url(),
        archive_size=len(body),
        archive_sha256=archive_sha or _sha(body),
        files=files or tuple(ModelFile(n, len(d), _sha(d)) for n, d in FILES.items()),
    )


def test_downloads_verifies_and_unpacks(cache, server) -> None:
    m = _manifest(server)
    folder = model_store.ensure_model(m)
    assert folder == model_store.model_dir(m)
    for name, data in FILES.items():
        assert (folder / name).read_bytes() == data
    assert model_store.is_installed(m)
    assert not list(model_store.models_dir().glob("*.part"))


def test_a_second_call_does_not_download_again(cache, server) -> None:
    m = _manifest(server)
    model_store.ensure_model(m)
    model_store.ensure_model(m)
    assert server.requests == 1


def test_follows_a_redirect(cache, server) -> None:
    """GitHub release assets answer 302 to another host."""
    m = _manifest(server, url=server.url("/redirect"))
    assert model_store.is_installed(m) is False
    model_store.ensure_model(m)
    assert model_store.is_installed(m)


def test_archive_checksum_mismatch_leaves_nothing(cache, server) -> None:
    m = _manifest(server, archive_sha="0" * 64)
    with pytest.raises(ModelDownloadError, match="damaged"):
        model_store.ensure_model(m)
    assert not model_store.model_dir(m).exists()
    assert not list(model_store.models_dir().iterdir())


def test_file_checksum_mismatch_leaves_no_folder(cache, server) -> None:
    bad = tuple(ModelFile(n, len(d), "0" * 64) for n, d in FILES.items())
    m = _manifest(server, files=bad)
    with pytest.raises(ModelDownloadError, match="damaged"):
        model_store.ensure_model(m)
    assert not list(model_store.models_dir().iterdir())


def test_cancel_mid_download_removes_the_part_file(cache, server, monkeypatch) -> None:
    monkeypatch.setattr(model_store, "_BLOCK", 1024)
    token = CancelToken()

    def progress(event):
        if event.fraction is not None:  # the first block has been written
            token.cancel()

    m = _manifest(server)
    with pytest.raises(JobCancelled):
        model_store.ensure_model(m, progress=progress, cancel=token)
    assert server.requests == 1
    assert not list(model_store.models_dir().iterdir())


def test_not_enough_disk_space_is_said_before_downloading(cache, server, monkeypatch) -> None:
    import collections

    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(model_store.shutil, "disk_usage", lambda _p: usage(10, 10, 0))
    m = _manifest(server)
    with pytest.raises(ModelDownloadError) as info:
        model_store.ensure_model(m)
    assert str(model_store.models_dir()) in str(info.value)
    assert server.requests == 0


def test_offline_names_the_way_out(cache, server) -> None:
    m = _manifest(server, url="http://127.0.0.1:9/nothing-listens-here")
    with pytest.raises(ModelDownloadError, match="WhisperX online"):
        model_store.ensure_model(m)


def _age(path, seconds: float) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then))


def test_what_a_crashed_run_left_is_cleared_before_free_space_is_measured(
    cache, server, monkeypatch
) -> None:
    """A stale download or half-unpacked folder goes; one young enough to be live stays."""
    m = _manifest(server)
    root = model_store.models_dir()
    root.mkdir(parents=True)
    stale_part = root / f".{m.folder_name}-abc123.tar.bz2.part"
    stale_part.write_bytes(b"left over from a crash")
    stale_dir = root / f".{m.folder_name}-def456"
    stale_dir.mkdir()
    (stale_dir / "encoder.onnx").write_bytes(b"half")
    _age(stale_dir / "encoder.onnx", 7200)
    _age(stale_part, 7200)
    _age(stale_dir, 7200)
    live_part = root / f".{m.folder_name}-live99.tar.bz2.part"
    live_part.write_bytes(b"another process is writing this")
    other_model = root / ".other--model-t-1-zzz.tar.bz2.part"
    other_model.write_bytes(b"not ours")
    _age(other_model, 7200)

    real_usage = model_store.shutil.disk_usage
    seen_when_measured: list[bool] = []

    def usage(path):
        seen_when_measured.append(stale_part.exists() or stale_dir.exists())
        return real_usage(path)

    monkeypatch.setattr(model_store.shutil, "disk_usage", usage)
    model_store.ensure_model(m)
    assert seen_when_measured == [False]
    assert not stale_part.exists() and not stale_dir.exists()
    assert live_part.exists(), "a young one may be another process's live download"
    assert other_model.exists(), "another model's files are not this install's to clear"


def test_two_jobs_download_once(cache, server) -> None:
    m = _manifest(server)
    errors: list[BaseException] = []

    def run():
        try:
            model_store.ensure_model(m)
        except BaseException as error:  # noqa: BLE001 — surfaced below
            errors.append(error)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert server.requests == 1


def test_installed_checks_and_discard(cache, server) -> None:
    m = _manifest(server)
    folder = model_store.ensure_model(m)
    assert model_store.verify_installed(m)
    data = bytearray((folder / "encoder.onnx").read_bytes())
    data[0] ^= 0xFF  # same size, different bytes
    (folder / "encoder.onnx").write_bytes(bytes(data))
    assert model_store.is_installed(m) is True  # sizes still match
    assert model_store.verify_installed(m) is False
    model_store.discard(m)
    assert not folder.exists()


def test_unpack_failure_leaves_no_half_folder(cache, server, monkeypatch) -> None:
    def broken_open(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(model_store.tarfile, "open", broken_open)
    m = _manifest(server)
    with pytest.raises(ModelDownloadError):
        model_store.ensure_model(m)
    assert not list(model_store.models_dir().iterdir())


@pytest.mark.parametrize(
    "change",
    [
        {"model_id": "test/other"},
        {"version": "t-2"},
        {"url": "https://example.invalid/other.tar.bz2"},
        {"archive_size": 1},
        {"archive_sha256": "1" * 64},
        {"files": "first file's name"},
        {"files": "first file's size"},
        {"files": "first file's sha256"},
        {"files": "order"},
        {"files": "one dropped"},
    ],
    ids=lambda change: next(iter(change.values())) if "files" in change else next(iter(change)),
)
def test_the_manifest_digest_changes_with_every_pinned_field(server, change) -> None:
    a = _manifest(server)
    first, *rest = a.files
    files = {
        "first file's name": (replace(first, name="renamed.onnx"), *rest),
        "first file's size": (replace(first, size=first.size + 1), *rest),
        "first file's sha256": (replace(first, sha256="2" * 64), *rest),
        "order": tuple(reversed(a.files)),
        "one dropped": tuple(rest),
    }
    if "files" in change:
        change = {"files": files[change["files"]]}
    assert a.digest() != replace(a, **change).digest()


def test_the_manifest_names_itself(server) -> None:
    a = _manifest(server)
    assert a.ref == "test/model@t-1"
    assert a.folder_name == "test--model-t-1"
    assert a.digest() == _manifest(server).digest()


def test_the_shipped_model_is_pinned_to_the_public_release() -> None:
    m = model_store.LOCAL_MODEL
    assert m.model_id == "nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0"
    assert m.url.startswith("https://github.com/Grazyen96/qalun-models/releases/download/model-v1/")
    assert {f.name for f in m.files} == {
        "encoder.onnx",
        "decoder.onnx",
        "joiner.onnx",
        "tokens.txt",
        "NOTICE.md",
    }
    assert all(len(f.sha256) == 64 for f in m.files) and len(m.archive_sha256) == 64


def test_the_shipped_download_is_said_as_about_110_mb() -> None:
    """108,151,682 bytes: what people read is rounded from the pin, never typed in."""
    assert model_store.LOCAL_MODEL.download_mb == 110
    assert replace(model_store.LOCAL_MODEL, archive_size=450_000_000).download_mb == 450


# -- what goes wrong, and what each failure says -------------------------------


class _CountingFile:
    """Wraps the .part file to count what the download writes into it."""

    def __init__(self, path, mode) -> None:
        self.file = builtins.open(path, mode)
        self.written = 0

    def write(self, data) -> int:
        self.written += len(data)
        return self.file.write(data)

    def flush(self) -> None:
        self.file.flush()

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        self.file.close()


@pytest.fixture
def written(monkeypatch) -> list[_CountingFile]:
    opened: list[_CountingFile] = []

    def counting_open(path, mode="r"):
        opened.append(_CountingFile(path, mode))
        return opened[-1]

    monkeypatch.setattr(model_store, "open", counting_open, raising=False)
    return opened


def _left_in_models() -> list[str]:
    root = model_store.models_dir()
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


@pytest.mark.parametrize("length", [None, "auto", 10**12])
def test_a_body_larger_than_pinned_is_never_written_past_its_size(
    cache, server, written, monkeypatch, length
) -> None:
    """No Content-Length, an honest one, or a lying one: the disk never takes more."""
    monkeypatch.setattr(model_store, "_BLOCK", 4096)
    m = _manifest(server)
    server.body = server.body + b"\0" * (2 << 20)
    server.length = length
    with pytest.raises(ModelDownloadError, match="different file") as info:
        model_store.ensure_model(m)
    assert "WhisperX online" in str(info.value)
    assert all(f.written <= m.archive_size for f in written)
    if length is not None:
        assert written == [], "a Content-Length that is not the pin is refused before writing"
    assert _left_in_models() == []


@pytest.mark.parametrize("length", [None, "full"])
def test_a_dropped_connection_says_the_download_was_interrupted(cache, server, length) -> None:
    m = _manifest(server)
    server.length = len(server.body) if length == "full" else None
    server.body = server.body[: len(server.body) // 2]
    with pytest.raises(ModelDownloadError, match="interrupted") as info:
        model_store.ensure_model(m)
    assert "damaged" not in str(info.value)
    assert _left_in_models() == []


@pytest.mark.parametrize(
    ("status", "advice"), [(404, "Update Qalun"), (410, "Update Qalun"), (503, "again later")]
)
def test_an_http_error_names_its_status_and_what_to_do(cache, server, status, advice) -> None:
    server.status = status
    with pytest.raises(ModelDownloadError, match=f"HTTP {status}") as info:
        model_store.ensure_model(_manifest(server))
    assert advice in str(info.value) and "WhisperX online" in str(info.value)
    assert "internet connection" not in str(info.value)
    assert _left_in_models() == []


def test_a_garbled_answer_is_a_download_error_not_a_traceback(cache, server) -> None:
    server.raw = b"NOT HTTP AT ALL\r\n\r\n"
    with pytest.raises(ModelDownloadError, match="internet connection"):
        model_store.ensure_model(_manifest(server))
    assert _left_in_models() == []


def test_a_full_disk_while_downloading_says_so(cache, server, monkeypatch) -> None:
    import errno

    class FullDisk(_CountingFile):
        def write(self, data) -> int:
            raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(model_store, "open", FullDisk, raising=False)
    with pytest.raises(ModelDownloadError, match="could not be saved") as info:
        model_store.ensure_model(_manifest(server))
    assert "disk space" in str(info.value) and "internet" not in str(info.value)
    assert _left_in_models() == []


def test_a_models_folder_that_cannot_be_made_is_a_download_error(
    tmp_path, monkeypatch, server
) -> None:
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")
    monkeypatch.setenv("QURANTEXT_CACHE_DIR", str(blocker / "cache"))
    with pytest.raises(ModelDownloadError, match="could not be prepared"):
        model_store.ensure_model(_manifest(server))
    assert server.requests == 0


def test_a_pinned_file_missing_from_the_archive_fails_and_leaves_nothing(cache, server) -> None:
    m = _manifest(server)
    m = replace(m, files=(*m.files, ModelFile("joiner.onnx", 5, "3" * 64)))
    with pytest.raises(ModelDownloadError, match="joiner.onnx missing"):
        model_store.ensure_model(m)
    assert _left_in_models() == []


def _link(name: str, target: str, kind: bytes = tarfile.SYMTYPE) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = target
    return info


@pytest.mark.parametrize(
    "extra",
    [
        _link("decoder.onnx", "/etc/passwd"),
        _link("decoder.onnx", "encoder.onnx", tarfile.LNKTYPE),
        _link("decoder.onnx", "", tarfile.FIFOTYPE),
    ],
    ids=["symlink", "hardlink", "fifo"],
)
def test_a_pinned_name_that_is_not_a_regular_file_is_refused(cache, extra) -> None:
    s = _Server(_archive(FILES, extra=(extra,)))
    try:
        m = _manifest(s, files=(*_manifest(s).files, ModelFile("decoder.onnx", 0, _sha(b""))))
        with pytest.raises(ModelDownloadError, match="decoder.onnx is not the pinned file"):
            model_store.ensure_model(m)
        assert _left_in_models() == []
    finally:
        s.close()


def test_a_pinned_name_twice_in_the_archive_is_refused(cache) -> None:
    body = io.BytesIO()
    with tarfile.open(fileobj=body, mode="w:bz2") as tar:
        for name, data in [*FILES.items(), ("tokens.txt", FILES["tokens.txt"])]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    s = _Server(body.getvalue())
    try:
        with pytest.raises(ModelDownloadError, match="tokens.txt is not the pinned file"):
            model_store.ensure_model(_manifest(s))
        assert _left_in_models() == []
    finally:
        s.close()


def test_members_not_in_the_manifest_are_never_written(cache, tmp_path) -> None:
    escape = tmp_path / "evil"
    files = {**FILES, "../../evil": b"x", str(escape): b"x", "./encoder.onnx": b"y"}
    s = _Server(_archive(files))
    try:
        m = _manifest(s)
        folder = model_store.ensure_model(m)
        assert sorted(p.name for p in folder.iterdir()) == sorted(FILES)
        assert not escape.exists()
        assert _left_in_models() == [m.folder_name]
    finally:
        s.close()


# -- progress and cancel ----------------------------------------------------------


def test_the_download_first_says_its_stage_without_a_fraction(cache, server) -> None:
    """A window says a stage's own sentence only for an event without a fraction."""
    events = []
    seen_requests = []

    def progress(event):
        events.append(event)
        seen_requests.append(server.requests)

    model_store.ensure_model(_manifest(server), progress=progress)
    assert events[0].stage == "download" and events[0].fraction is None
    assert seen_requests[0] == 0, "said before connecting"
    fractions = [e.fraction for e in events if e.stage == "download" and e.fraction is not None]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0
    unpack = [e for e in events if e.stage == "unpack"]
    assert unpack and all(e.fraction is None for e in unpack)
    assert events.index(unpack[0]) > max(
        i for i, e in enumerate(events) if e.stage == "download"
    ), "unpacking is said after the download's last event"


def test_cancel_before_connecting_downloads_nothing(cache, server) -> None:
    token = CancelToken()
    token.cancel()
    with pytest.raises(JobCancelled):
        model_store.ensure_model(_manifest(server), cancel=token)
    assert server.requests == 0
    assert _left_in_models() == []


def test_cancel_keeps_up_on_a_slow_link(cache) -> None:
    """A read returns what has arrived, not a whole block, so cancel is checked at once."""
    released = threading.Event()
    s = _Server(os.urandom(64 * 1024))
    s.between = lambda: released.wait(10)
    token = CancelToken()

    def progress(event):
        if event.fraction is not None:
            token.cancel()

    started = time.monotonic()
    try:
        with pytest.raises(JobCancelled):
            model_store.ensure_model(_manifest(s), progress=progress, cancel=token)
        assert time.monotonic() - started < 5, "waited for a whole block to arrive"
        assert _left_in_models() == []
    finally:
        released.set()
        s.close()


def test_cancel_while_unpacking_leaves_nothing(cache, server, monkeypatch) -> None:
    monkeypatch.setattr(model_store, "_BLOCK", 512)
    token = CancelToken()

    def progress(event):
        if event.stage == "unpack":
            token.cancel()

    with pytest.raises(JobCancelled):
        model_store.ensure_model(_manifest(server), progress=progress, cancel=token)
    assert _left_in_models() == []


# -- two processes at once ----------------------------------------------------------


def test_two_processes_downloading_at_once_both_end_with_the_model(
    cache, server, monkeypatch
) -> None:
    """No shared lock, as between two processes: both download, both succeed, one folder."""
    monkeypatch.setattr(model_store, "_LOCK", contextlib.nullcontext())
    together = threading.Barrier(2, timeout=10)
    server.before_body = together.wait
    m = _manifest(server)
    results: list[object] = []

    def run():
        try:
            results.append(model_store.ensure_model(m))
        except BaseException as error:  # noqa: BLE001 — surfaced below
            results.append(error)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [model_store.model_dir(m)] * 2
    assert server.requests == 2
    assert model_store.verify_installed(m)
    assert _left_in_models() == [m.folder_name]


def test_a_folder_another_process_put_in_first_is_kept(cache, server, monkeypatch) -> None:
    """The other process may already be loading it: it is neither replaced nor touched."""
    monkeypatch.setattr(model_store, "_LOCK", contextlib.nullcontext())
    m = _manifest(server)
    real_download = model_store._download
    theirs: list[tuple[int, ...]] = []

    def download_while_another_installs(*args, **kwargs):
        real_download(*args, **kwargs)
        # The other process finishes first, while this one is still downloading.
        monkeypatch.setattr(model_store, "_download", real_download)
        folder = model_store.ensure_model(m)
        theirs.append(tuple(os.stat(folder / n).st_ino for n in FILES))
        monkeypatch.setattr(model_store, "_download", download_while_another_installs)

    monkeypatch.setattr(model_store, "_download", download_while_another_installs)
    folder = model_store.ensure_model(m)
    assert folder == model_store.model_dir(m)
    assert theirs == [tuple(os.stat(folder / n).st_ino for n in FILES)], "theirs was replaced"
    assert server.requests == 2
    assert model_store.verify_installed(m)
    assert _left_in_models() == [m.folder_name]


def test_an_incomplete_folder_in_the_way_is_replaced(cache, server) -> None:
    m = _manifest(server)
    target = model_store.model_dir(m)
    target.mkdir(parents=True)
    (target / "encoder.onnx").write_bytes(b"short")
    folder = model_store.ensure_model(m)
    assert model_store.verify_installed(m)
    assert _left_in_models() == [folder.name]


# -- trusted certificates -------------------------------------------------------------


class _RecordingContext:
    def __init__(self) -> None:
        self.loaded: list[dict] = []

    def load_verify_locations(self, **kwargs) -> None:
        self.loaded.append(kwargs)


def test_the_download_trusts_certifi_s_bundle_too(monkeypatch) -> None:
    import certifi

    context = _RecordingContext()
    monkeypatch.setattr(model_store.ssl, "create_default_context", lambda: context)
    assert model_store._ssl_context() is context
    assert context.loaded == [{"cafile": certifi.where()}]


def test_without_certifi_the_system_s_certificates_are_used(monkeypatch) -> None:
    context = _RecordingContext()
    monkeypatch.setattr(model_store.ssl, "create_default_context", lambda: context)
    monkeypatch.setitem(sys.modules, "certifi", None)  # import certifi raises ImportError
    assert model_store._ssl_context() is context
    assert context.loaded == []


def test_the_download_connects_with_that_context(cache, server, monkeypatch) -> None:
    real_urlopen = model_store.urllib.request.urlopen
    contexts = []

    def urlopen(url, **kwargs):
        contexts.append(kwargs.get("context"))
        return real_urlopen(url, **kwargs)

    monkeypatch.setattr(model_store.urllib.request, "urlopen", urlopen)
    model_store.ensure_model(_manifest(server))
    assert len(contexts) == 1 and isinstance(contexts[0], ssl.SSLContext)
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED and contexts[0].check_hostname

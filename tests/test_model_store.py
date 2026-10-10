from __future__ import annotations

import hashlib
import io
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qurantext.services import model_store
from qurantext.services.errors import ModelDownloadError
from qurantext.services.model_store import ModelFile, ModelManifest
from qurantext.utils.progress import CancelToken, JobCancelled

FILES = {"encoder.onnx": b"E" * 3000, "tokens.txt": "▁ق 0\n<blk> 1\n".encode()}


def _archive(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Server:
    """Serves /model.tar.bz2, and /redirect answering 302 to it, counting requests."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requests = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 — http.server's name
                outer.requests += 1
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/model.tar.bz2")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *_args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, path: str = "/model.tar.bz2") -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"

    def close(self) -> None:
        self.httpd.shutdown()


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

    def progress(_event):
        token.cancel()

    m = _manifest(server)
    with pytest.raises(JobCancelled):
        model_store.ensure_model(m, progress=progress, cancel=token)
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


def test_a_stale_part_file_is_cleared(cache, server) -> None:
    m = _manifest(server)
    model_store.models_dir().mkdir(parents=True)
    stale = model_store.models_dir() / f"{m.folder_name}.tar.bz2.part"
    stale.write_bytes(b"left over from a crash")
    model_store.ensure_model(m)
    assert not stale.exists()


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


def test_the_manifest_digest_changes_with_any_field(server) -> None:
    from dataclasses import replace

    a = _manifest(server)
    assert a.digest() != replace(a, version="t-2").digest()
    assert a.digest() != replace(a, url=a.url + "?x").digest()
    assert a.ref == "test/model@t-1"
    assert a.folder_name == "test--model-t-1"

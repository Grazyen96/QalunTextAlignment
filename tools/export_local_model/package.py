#!/usr/bin/env python3
"""Pack one exported variant into the release archive and print its pinned manifest."""

import argparse
import hashlib
import json
import shutil
import tarfile
from pathlib import Path

MODEL_ID = "nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0"
RELEASE_URL = "https://github.com/Grazyen96/qalun-models/releases/download/model-v1"
FILES = ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt", "NOTICE.md")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _anonymous(info: tarfile.TarInfo) -> tarfile.TarInfo:
    # Same files, same archive bytes: no build time and no local user name in the
    # headers, so a re-run reproduces the checksum already pinned in the app.
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mode = 0o644
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant-dir", required=True, type=Path)
    ap.add_argument("--version", required=True)  # e.g. int8-1
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(__file__).with_name("NOTICE.md"), args.variant_dir / "NOTICE.md")

    name = f"{MODEL_ID.split('/')[1]}-{args.version}.tar.bz2"
    archive = args.out_dir / name
    with tarfile.open(archive, "w:bz2") as tar:
        for file in FILES:
            tar.add(args.variant_dir / file, arcname=file, filter=_anonymous)  # flat

    files = [
        {
            "name": f,
            "size": (args.variant_dir / f).stat().st_size,
            "sha256": sha256(args.variant_dir / f),
        }
        for f in FILES
    ]
    manifest = {
        "model_id": MODEL_ID,
        "version": args.version,
        "url": f"{RELEASE_URL}/{name}",
        "archive_size": archive.stat().st_size,
        "archive_sha256": sha256(archive),
        "files": files,
    }
    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    lines = [
        "LOCAL_MODEL = ModelManifest(",
        f'    model_id="{MODEL_ID}",',
        f'    version="{args.version}",',
        f'    url="{manifest["url"]}",',
        f"    archive_size={manifest['archive_size']},",
        f'    archive_sha256="{manifest["archive_sha256"]}",',
        "    files=(",
        *[
            f'        ModelFile(\n            "{f["name"]}",\n            {f["size"]},\n            "{f["sha256"]}",\n        ),'
            for f in files
        ],
        "    ),",
        ")",
    ]
    (args.out_dir / "manifest_literal.py.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
# Zip the built app into out/<artifact>.zip, the file the build uploads.
#
#   bash packaging/ci/package.sh qalun-linux
#
# Linux needs its own zip. PyInstaller puts symlinks in _internal/ that point at
# the Qt and FFmpeg libraries under PySide6/Qt/lib/, and Python's
# shutil.make_archive follows them, storing each of those libraries twice: the
# app then unpacks to about 446 MB instead of 275 MB. `zip -y` stores a link as
# a link. macOS keeps using ditto, which already keeps links; Windows bundles
# have no links, so it keeps the zip it has always had.
set -euo pipefail

artifact="${1:?usage: package.sh <artifact-name>, e.g. qalun-linux}"

if [ ! -d "dist/Qalun.app" ] && [ ! -d "dist/qalun" ]; then
  echo "package.sh: no dist/qalun or dist/Qalun.app here; run the build first" >&2
  exit 1
fi

mkdir -p out
zip_path="$PWD/out/$artifact.zip"
rm -f "$zip_path"  # zip adds to an existing archive rather than replacing it

if [ -d "dist/Qalun.app" ]; then
  ditto -c -k --keepParent "dist/Qalun.app" "$zip_path"
elif [ "$(uname -s)" = "Linux" ]; then
  if ! command -v zip >/dev/null 2>&1; then
    echo "package.sh: 'zip' is not installed; without it the symlinks cannot be kept" >&2
    exit 1
  fi
  # From inside dist/, so the archive's top folder is qalun/, as before.
  (cd dist && zip -qry "$zip_path" qalun)
else
  python -c "
import shutil, sys
shutil.make_archive(sys.argv[1], 'zip', 'dist', 'qalun')
" "out/$artifact"
fi

ls -la out

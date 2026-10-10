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
#
# THIRD_PARTY_NOTICES.md goes in at the top, where someone who unzips the app
# sees it: beside the executable in qalun/, and on macOS beside Qalun.app (the
# app carries its own copy inside as well). It credits the speech model, whose
# CC BY 4.0 licence asks for attribution, and the libraries the engine brings.
# LICENSE, Qalun's own licence (GPL-3.0-only), goes beside it.
#
# The Linux job also writes out/qalun-source-<tag or commit>.zip: the complete
# source of the commit being built (`git archive`, so the committed tree only,
# nothing git ignores). Qalun is GPL-3.0-only and the repository is private, so
# each release carries its source; the release attaches every zip the jobs upload
# from out/. Only Linux writes it, so it is made once. Outside a git checkout the
# step fails rather than let a release go out without its source.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
notices="$root/THIRD_PARTY_NOTICES.md"
licence="$root/LICENSE"

artifact="${1:?usage: package.sh <artifact-name>, e.g. qalun-linux}"

if [ ! -d "dist/Qalun.app" ] && [ ! -d "dist/qalun" ]; then
  echo "package.sh: no dist/qalun or dist/Qalun.app here; run the build first" >&2
  exit 1
fi

mkdir -p out
zip_path="$PWD/out/$artifact.zip"
rm -f "$zip_path"  # zip adds to an existing archive rather than replacing it

if [ -d "dist/Qalun.app" ]; then
  # ditto zips one folder, so the app and the notice are gathered in one first;
  # without --keepParent its contents become the top of the archive.
  top="out/macos-top"
  rm -rf "$top"
  mkdir -p "$top"
  ditto "dist/Qalun.app" "$top/Qalun.app"
  cp "$notices" "$licence" "$top/"
  ditto -c -k "$top" "$zip_path"
  rm -rf "$top"
elif [ "$(uname -s)" = "Linux" ]; then
  if ! command -v zip >/dev/null 2>&1; then
    echo "package.sh: 'zip' is not installed; without it the symlinks cannot be kept" >&2
    exit 1
  fi
  cp "$notices" "$licence" dist/qalun/
  # From inside dist/, so the archive's top folder is qalun/, as before.
  (cd dist && zip -qry "$zip_path" qalun)

  # Named after the tag on a release build, otherwise after the commit.
  if [ "${GITHUB_REF_TYPE:-}" = "tag" ] && [ -n "${GITHUB_REF_NAME:-}" ]; then
    ref="$GITHUB_REF_NAME"
  elif ! ref="$(git -C "$root" rev-parse --short=12 HEAD 2>/dev/null)"; then
    echo "package.sh: $root is not a git checkout, so the source archive cannot be made" >&2
    exit 1
  fi
  source_zip="$PWD/out/qalun-source-${ref//\//-}.zip"
  rm -f "$source_zip"
  git -C "$root" archive --format=zip --prefix=qalun-source/ -o "$source_zip" HEAD
else
  cp "$notices" "$licence" dist/qalun/
  python -c "
import shutil, sys
shutil.make_archive(sys.argv[1], 'zip', 'dist', 'qalun')
" "out/$artifact"
fi

ls -la out

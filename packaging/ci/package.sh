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
# What goes in at the top, where someone who unzips the app sees it: beside the
# executable in qalun/, and on macOS beside Qalun.app (the app carries its own
# copy of the two texts inside as well):
#
# - THIRD_PARTY_NOTICES.md: credits the speech model, whose CC BY 4.0 licence
#   asks for attribution, and every component the app bundles, with its licence.
# - LICENSE: Qalun's own licence, GPL-3.0-only.
# - qalun-source.zip: the complete source of the commit being built (`git
#   archive`, so the committed tree only, nothing git ignores). Qalun is
#   GPL-3.0-only and the repository is private, so every app zip carries its own
#   source (GPL-3.0 section 6(a)). Outside a git checkout the step fails rather
#   than let a zip go out without its source.
# - third-party-sources/: the corresponding sources of the GPL and LGPL code
#   inside the bundle that is not Qalun's, listed with their URL and sha256 in
#   packaging/third-party-sources.txt. Each is downloaded here and refused unless
#   its sha256 matches. Downloads are kept in QALUN_SOURCES_CACHE (default
#   .ci-cache/third-party-sources), and a kept file is checked again before use.
#
# On a tag build the tag must be v<version>, the version in
# src/qurantext/__init__.py (the one place it is written down; pyproject.toml
# reads it from there), or the step fails before zipping anything.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
notices="$root/THIRD_PARTY_NOTICES.md"
licence="$root/LICENSE"
pins="$root/packaging/third-party-sources.txt"

artifact="${1:?usage: package.sh <artifact-name>, e.g. qalun-linux}"

if [ ! -d "dist/Qalun.app" ] && [ ! -d "dist/qalun" ]; then
  echo "package.sh: no dist/qalun or dist/Qalun.app here; run the build first" >&2
  exit 1
fi

# A release's version is its tag's: `qalun --version` and the doctor report say
# __version__, so a tag that disagrees would ship an app that names another one.
if [ "${GITHUB_REF_TYPE:-}" = "tag" ] && [ -n "${GITHUB_REF_NAME:-}" ]; then
  init="$root/src/qurantext/__init__.py"
  version="$(sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' "$init" 2>/dev/null | tr -d '\r' || true)"
  if [ "v$version" != "$GITHUB_REF_NAME" ]; then
    echo "package.sh: the tag is $GITHUB_REF_NAME but src/qurantext/__init__.py says" \
      "__version__ = \"$version\". Set it to the tag's number, commit, and tag that commit." >&2
    exit 1
  fi
fi

if [ -d "dist/Qalun.app" ]; then
  platform=macos
elif [ "$(uname -s)" = "Linux" ]; then
  platform=linux
else
  platform=windows
fi

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

# Every pinned source for this platform, downloaded (or reused) and checked, into
# the folder $1.
fetch_sources() {
  local dest="$1" cache="${QALUN_SOURCES_CACHE:-$root/.ci-cache/third-party-sources}"
  local where file sha url got
  mkdir -p "$cache" "$dest"
  while read -r where file sha url; do
    url="${url%$'\r'}"  # a Windows checkout may have given the list CRLF endings
    case "$where" in "" | "#"* | $'\r') continue ;; esac
    [ "$where" = all ] || [ "$where" = "$platform" ] || continue
    if [ -z "$url" ] || [ "${#sha}" -ne 64 ]; then
      echo "package.sh: cannot read the line for '$file' in $pins" >&2
      return 1
    fi
    if [ -f "$cache/$file" ] && [ "$(sha256_of "$cache/$file")" = "$sha" ]; then
      echo "Third-party source $file: already downloaded and its sha256 matches."
    else
      rm -f "$cache/$file" "$cache/$file.part"
      if ! curl -fsSL --retry 3 --max-time 600 -o "$cache/$file.part" "$url"; then
        rm -f "$cache/$file.part"
        echo "package.sh: could not download the source $file from $url" >&2
        return 1
      fi
      got="$(sha256_of "$cache/$file.part")"
      if [ "$got" != "$sha" ]; then
        rm -f "$cache/$file.part"
        echo "package.sh: the source $file from $url has sha256 $got;" \
          "packaging/third-party-sources.txt pins $sha. Not shipping it." >&2
        return 1
      fi
      mv "$cache/$file.part" "$cache/$file"
      echo "Third-party source $file: downloaded, sha256 $sha matches the pin."
    fi
    cp "$cache/$file" "$dest/$file"
    printf '%s\n  from %s\n  sha256 %s\n\n' "$file" "$url" "$sha" >>"$dest/SOURCES.txt"
  done <"$pins"
}

# The notice, the licence, Qalun's own source and the third-party sources, into
# the folder $1 that becomes the top of the zip.
add_release_files() {
  local top="$1"
  cp "$notices" "$licence" "$top/"
  if ! git -C "$root" rev-parse --verify -q HEAD >/dev/null 2>&1; then
    echo "package.sh: $root is not a git checkout, so the source archive cannot be made" >&2
    return 1
  fi
  rm -f "$top/qalun-source.zip"
  git -C "$root" archive --format=zip --prefix=qalun-source/ -o "$top/qalun-source.zip" HEAD
  rm -rf "$top/third-party-sources"
  mkdir -p "$top/third-party-sources"
  {
    echo "The corresponding sources of the GPL and LGPL components inside this app"
    echo "that are not Qalun's own; THIRD_PARTY_NOTICES.md says which is which."
    echo "Qalun's own source is qalun-source.zip, beside this folder."
    echo
  } >"$top/third-party-sources/SOURCES.txt"
  fetch_sources "$top/third-party-sources"
}

mkdir -p out
zip_path="$PWD/out/$artifact.zip"
rm -f "$zip_path"  # zip adds to an existing archive rather than replacing it

if [ "$platform" = macos ]; then
  # ditto zips one folder, so the app and the files beside it are gathered in
  # one first; without --keepParent its contents become the top of the archive.
  top="out/macos-top"
  rm -rf "$top"
  mkdir -p "$top"
  ditto "dist/Qalun.app" "$top/Qalun.app"
  add_release_files "$top"
  ditto -c -k "$top" "$zip_path"
  rm -rf "$top"
elif [ "$platform" = linux ]; then
  if ! command -v zip >/dev/null 2>&1; then
    echo "package.sh: 'zip' is not installed; without it the symlinks cannot be kept" >&2
    exit 1
  fi
  add_release_files dist/qalun
  # From inside dist/, so the archive's top folder is qalun/, as before.
  (cd dist && zip -qry "$zip_path" qalun)
else
  add_release_files dist/qalun
  python -c "
import shutil, sys
shutil.make_archive(sys.argv[1], 'zip', 'dist', 'qalun')
" "out/$artifact"
fi

ls -la out

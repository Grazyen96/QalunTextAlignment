#!/usr/bin/env bash
# Fetch what the Linux app needs at runtime into vendor/.
set -euo pipefail

sudo apt-get update -qq
# libxcb-cursor0 is not for vendor/: Qt 6.5 and later's xcb platform plugin
# links libxcb-cursor.so.0, and PyInstaller can only bundle it if the build
# machine has it. Without it the window cannot start on an X11 desktop that
# lacks the package (Wayland sessions are unaffected).
sudo apt-get install -y --no-install-recommends libfribidi0 libxcb-cursor0
mkdir -p vendor

fetch() {
  local out="$1"; shift
  for url in "$@"; do
    for attempt in 1 2 3; do
      echo "Fetching $url (attempt $attempt)"
      if curl -fsSL --max-time 300 -o "$out" "$url"; then return 0; fi
      sleep $((5 * attempt))
    done
  done
  return 1
}

# The smaller build first: 40 MB against 144 MB, and a 77 MB binary against a
# 165 MB one. That difference is what someone has to download to use this. The
# second is on GitHub's own CDN and exists so that a third-party host having a
# bad afternoon cannot fail a release.
fetch ffmpeg.tar.xz \
  "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" \
  "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"

mkdir -p ffmpeg-src
tar -xJf ffmpeg.tar.xz -C ffmpeg-src --strip-components=1
find ffmpeg-src -type f \( -name ffmpeg -o -name ffprobe \) -exec cp {} vendor/ \;
chmod +x vendor/ffmpeg vendor/ffprobe

# Pillow loads FriBiDi by name at runtime and no Pillow wheel contains one.
cp /usr/lib/x86_64-linux-gnu/libfribidi.so.0 vendor/

ls -la vendor

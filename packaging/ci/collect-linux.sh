#!/usr/bin/env bash
# Fetch what the Linux app needs at runtime into vendor/.
set -euo pipefail

sudo apt-get update -qq
# The runner is a bare machine, with no sound or graphics stack, and PyInstaller
# bundles only the libraries it finds on the build machine. So the libraries
# Qt links are installed here, none of them for vendor/:
#
#   libpulse0          Qt Multimedia's sound output. Without it on the runner the
#                      bundle has no libpulse and playback cannot load at all (the
#                      first real CI build failed on exactly this).
#   libxcb-cursor0,    Qt's xcb platform plugin and its helpers; Qt 6.5 and later
#   libxcb-*,          need libxcb-cursor, and a desktop without these packages
#   libxkbcommon*      cannot open the window on X11. Bundled once present here.
#   libegl1, libgl1,   never bundled (PyInstaller leaves the graphics driver's
#   libfontconfig1,    libraries to the system, which every desktop has), but the
#   libdbus-1-3        gate cannot load Qt's drawing library on the runner without
#                      them.
sudo apt-get install -y --no-install-recommends \
  libfribidi0 \
  libpulse0 \
  libegl1 libgl1 libfontconfig1 libdbus-1-3 \
  libxkbcommon0 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1
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

#!/usr/bin/env bash
# Fetch what the macOS app needs at runtime into vendor/.
set -euo pipefail

brew install ffmpeg fribidi dylibbundler
mkdir -p vendor
cp "$(command -v ffmpeg)" "$(command -v ffprobe)" vendor/

# Homebrew's FFmpeg is linked against some sixty libraries under the Homebrew
# prefix. Copying the bare binary produces a Mac app that works only on a machine
# that already has Homebrew FFmpeg installed, which is to say almost none of
# them. dylibbundler copies those libraries in and rewrites the load paths.
dylibbundler -od -b -x vendor/ffmpeg -x vendor/ffprobe -d vendor/libs -p @executable_path/libs

# Pillow loads FriBiDi by name at runtime and no Pillow wheel contains one.
cp "$(brew --prefix fribidi)/lib/libfribidi.0.dylib" vendor/libfribidi.dylib
# The app loads this by absolute path, and the loader then answers Pillow's
# bare-name request with it — but only if the name it carries is the one Pillow
# asks for.
install_name_tool -id libfribidi.dylib vendor/libfribidi.dylib

ls -la vendor

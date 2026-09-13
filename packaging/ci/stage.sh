#!/usr/bin/env bash
# Copy everything in vendor/ in beside the built executable, where the app looks
# for it before it looks at PATH.
set -euo pipefail

target="dist/qalun"
[ -d "dist/Qalun.app" ] && target="dist/Qalun.app/Contents/MacOS"
cp -R vendor/* "$target/"
ls "$target" | head -25

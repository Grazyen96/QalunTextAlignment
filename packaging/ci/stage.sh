#!/usr/bin/env bash
# Copy everything in vendor/ in beside the built executable, where the app looks
# for it before it looks at PATH.
set -euo pipefail

target="dist/qalun"
[ -d "dist/Qalun.app" ] && target="dist/Qalun.app/Contents/MacOS"
cp -R vendor/* "$target/"
ls "$target" | head -25

# PyInstaller ad-hoc signed Qalun.app before the copy above, so the files just
# added under Contents/MacOS lie outside the bundle's seal: codesign --verify
# reports them as added, and a downloaded (quarantined) app may be called
# damaged. Sign the whole bundle again, ad hoc as before, now that it is complete.
if [ -d "dist/Qalun.app" ]; then
  codesign --force --deep --sign - dist/Qalun.app
fi

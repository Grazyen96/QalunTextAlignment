#!/usr/bin/env bash
# The gate: does the built app say it can render?
#
# PATH is stripped on purpose. Someone who downloads an app and double-clicks it
# has put nothing on PATH, so anything the app can only find there it cannot find
# at all. Leaving the real PATH in place is how a build passes here and then
# fails on a real machine.
#
# --release makes playback, Qt's Arabic translation and an Arabic interface font
# blocking: a developer's checkout is only told about them, a release must have
# them. On Linux there is no display here; the app draws offscreen for the check.
set -euo pipefail

if [ -d "dist/Qalun.app" ]; then
  app="dist/Qalun.app/Contents/MacOS/qalun"
else
  app="dist/qalun/qalun"
fi
PATH=/nonexistent "$app" --doctor --release

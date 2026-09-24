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
#
# Bounded: the media load inside the doctor waits at most 5 s, but starting Qt,
# asking for audio outputs and the sound-server client bundled from the build
# machine have no bound of their own, and a hang would hold the job for its
# 6 hours. QALUN_GATE_TIMEOUT_S (seconds, default 180) is for this script's tests.
set -euo pipefail

limit="${QALUN_GATE_TIMEOUT_S:-180}"

if [ -d "dist/Qalun.app" ]; then
  app="dist/Qalun.app/Contents/MacOS/qalun"
else
  app="dist/qalun/qalun"
fi

# Looked up here, while PATH is still the real one. macOS has no timeout(1);
# perl's alarm survives the exec and ends the app the same way.
if bound="$(command -v timeout)"; then
  bounded=("$bound" "$limit")
else
  bounded=("$(command -v perl)" -e 'alarm shift; exec @ARGV or die "cannot run $ARGV[0]: $!\n"' "$limit")
fi

status=0
code=0
PATH=/nonexistent "${bounded[@]}" "$app" --doctor --release || code=$?
if [ "$code" -eq 124 ] || [ "$code" -eq 142 ]; then
  echo "The gate failed: the built app's doctor did not finish within ${limit} s." >&2
  status=1
elif [ "$code" -ne 0 ]; then
  echo "The gate failed: the built app's doctor reported a problem (exit code $code; see above)." >&2
  status="$code"
fi

# The doctor draws offscreen on Linux, so it never loads the xcb platform plugin
# and cannot notice the library that plugin needs to start on an X11 desktop.
if [ "$(uname -s)" = "Linux" ]; then
  if [ -z "$(find dist/qalun -name 'libxcb-cursor.so.0*' -print -quit)" ]; then
    echo "The gate failed: the bundle has no libxcb-cursor.so.0, so the window will not" \
      "open on X11. Install libxcb-cursor0 on the build machine and build again." >&2
    status=1
  fi
fi

exit "$status"

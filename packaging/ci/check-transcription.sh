#!/usr/bin/env bash
# The second gate: does a transcription on this computer actually work inside
# the built app? check.sh runs it on macOS and Linux, check.ps1 on Windows (in
# Git's bash), each only after the doctor has passed.
#
# The doctor proves the sherpa-onnx runtime imports. This proves the rest of
# what a person's first local transcription does: the speech model downloads
# from the public qalun-models release, its size and checksums verify, the
# model loads, FFmpeg decodes, and the app writes a transcript with "segments".
# The audio is a five-second tone made here, so nothing is kept in the
# repository; how well the model recognises speech is the parity gate's job.
#
# A failure here usually means one of three things: the qalun-models release
# asset is broken or gone, the pinned checksum in model_store.py no longer
# matches it, or the bundle is missing one of sherpa-onnx's native libraries.
#
# The model folder: QURANTEXT_CACHE_DIR when it is set; on GitHub Actions
# otherwise .ci-cache/qalun, the folder release.yml caches between runs so that
# a build does not download the model each time (every download counts towards
# the release's download numbers, which is how installs are counted); otherwise
# wherever the app keeps it for the person running this.
#
# PATH is stripped for the app, as in check.sh: it must find FFmpeg beside
# itself. Bounded by QALUN_TRANSCRIPTION_GATE_TIMEOUT_S (seconds, default 900),
# which covers the 110 MB download on a slow runner.
set -euo pipefail

limit="${QALUN_TRANSCRIPTION_GATE_TIMEOUT_S:-900}"

windows=false
case "$(uname -s)" in
  MINGW* | MSYS* | CYGWIN*) windows=true ;;
esac

if [ -d "dist/Qalun.app" ]; then
  app="dist/Qalun.app/Contents/MacOS/qalun"
elif [ "$windows" = true ]; then
  app="dist/qalun/qalun.exe"
else
  app="dist/qalun/qalun"
fi
app_dir="$(dirname "$app")"

# The FFmpeg stage.sh put beside the app; the runner's own only as a fallback,
# because the tone is test input, not something the app is being checked for.
ffmpeg="$app_dir/ffmpeg"
[ "$windows" = true ] && ffmpeg="$app_dir/ffmpeg.exe"
if [ ! -x "$ffmpeg" ]; then
  ffmpeg="$(command -v ffmpeg || true)"
fi
if [ -z "$ffmpeg" ]; then
  echo "The transcription gate failed: no FFmpeg beside the app or on PATH to make the test tone." >&2
  exit 1
fi

# A Python to read the transcript with. On Windows, python3 may be the Store's
# stand-in, which runs but is not Python; asking it to import json tells them apart.
python=""
for candidate in python3 python; do
  if found="$(command -v "$candidate")" && "$found" -c "import json" >/dev/null 2>&1; then
    python="$found"
    break
  fi
done
if [ -z "$python" ]; then
  echo "The transcription gate failed: no Python on PATH to read the transcript with." >&2
  exit 1
fi

# GNU timeout where there is one (Linux, Git's bash on Windows); Windows' own
# timeout.exe only waits, and macOS has none, so anything that does not answer
# --version like GNU's is passed over for perl, as in check.sh.
if bound="$(command -v timeout)" && "$bound" --version >/dev/null 2>&1; then
  bounded=("$bound" "$limit")
else
  bounded=("$(command -v perl)" -e 'alarm shift; exec @ARGV or die "cannot run $ARGV[0]: $!\n"' "$limit")
fi

if [ -z "${QURANTEXT_CACHE_DIR:-}" ] && [ "${GITHUB_ACTIONS:-}" = "true" ]; then
  QURANTEXT_CACHE_DIR="$PWD/.ci-cache/qalun"
fi
if [ -n "${QURANTEXT_CACHE_DIR:-}" ]; then
  mkdir -p "$QURANTEXT_CACHE_DIR"
  # The app is a Windows program there and wants a Windows path.
  [ "$windows" = true ] && QURANTEXT_CACHE_DIR="$(cygpath -m "$QURANTEXT_CACHE_DIR")"
  export QURANTEXT_CACHE_DIR
  echo "Speech model folder: $QURANTEXT_CACHE_DIR/models"
fi

stripped=/nonexistent
if [ "$windows" = true ]; then
  # What check.ps1 leaves the doctor: Windows' own folders and nothing else.
  system_root="$(cygpath -u "${SYSTEMROOT:-${SystemRoot:-C:/Windows}}")"
  stripped="$system_root/System32:$system_root"
fi

work="build/transcription-gate"
rm -rf "$work"
mkdir -p "$work"
tone="$work/tone.wav"
transcript="$work/tone.json"

"$ffmpeg" -v error -y -f lavfi -i "sine=frequency=440:duration=5" -ac 1 -ar 16000 "$tone"

code=0
PATH="$stripped" QURANTEXT_TRANSCRIBE_ENGINE=local "${bounded[@]}" "$app" --cli transcribe \
  --engine local --no-cache --audio "$tone" --output "$transcript" || code=$?
if [ "$code" -eq 124 ] || [ "$code" -eq 142 ]; then
  echo "The transcription gate failed: the built app did not finish within ${limit} s." >&2
  exit 1
elif [ "$code" -ne 0 ]; then
  echo "The transcription gate failed: the built app could not transcribe (exit code $code; see above)." >&2
  echo "Usually: a broken qalun-models asset, a changed checksum, or a sherpa-onnx library missing from the bundle." >&2
  exit "$code"
fi

if ! "$python" - "$transcript" <<'PY'; then
import json
import sys

path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
except (OSError, ValueError) as error:
    sys.exit(f"cannot read the transcript {path}: {error}")
segments = data.get("segments") if isinstance(data, dict) else None
if not isinstance(segments, list):
    sys.exit(f'the transcript {path} has no "segments" list')
print(f"The built app transcribed on this computer: {len(segments)} segment(s) for a 5 s tone.")
PY
  echo "The transcription gate failed: the app finished, but its transcript is not valid." >&2
  exit 1
fi

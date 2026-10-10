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
# Before that, every run (cache hit or not) asks GitHub's API whether the
# published asset still has the pinned name, size and sha256, so a run that
# restores the model from the cache still proves the release a person will
# download from. A cache miss prints one QALUN-CI-MODEL-DOWNLOAD line.
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

work="build/transcription-gate"
rm -rf "$work"
mkdir -p "$work"

# The published asset still matches the pin, checked every run, cache or not.
# On a cache hit the app never touches the release, so without this a deleted,
# renamed or replaced model-v1 asset (or qalun-models made private) would ship.
# This reads the release's metadata from GitHub's API, which does not count as
# a download of the asset. What it expects is read from model_store.py, the one
# place the pin is written down; that import needs nothing outside the standard
# library, so any Python 3.10+ can run it from src/, installed or not.
src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../src" && pwd)"
if ! pin="$("$python" -c '
import sys
sys.path.insert(0, sys.argv[1])
from qurantext.services.model_store import LOCAL_MODEL as m, model_dir
parts = m.url.split("/")
if parts[:3] != ["https:", "", "github.com"] or parts[5:7] != ["releases", "download"] or len(parts) != 9:
    sys.exit(f"the pinned URL is not a GitHub release asset: {m.url}")
owner, repo, tag, name = parts[3], parts[4], parts[7], parts[8]
api = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
print("\t".join([tag, api, name, str(m.archive_size), m.archive_sha256, str(model_dir(m))]))
' "$src_dir" | tr -d '\r')"; then
  echo "The transcription gate failed: could not read the pinned model from model_store.py." >&2
  exit 1
fi
IFS=$'\t' read -r pin_tag pin_api pin_name pin_size pin_sha256 pin_dir <<<"$pin"
[ "$windows" = true ] && pin_dir="$(cygpath -u "$pin_dir")"

curl="$(command -v curl || true)"
if [ -z "$curl" ]; then
  echo "The transcription gate failed: no curl on PATH to check the published model with." >&2
  exit 1
fi
# GITHUB_TOKEN, which the workflow passes to the gate steps: anonymous calls are
# limited to 60 an hour per address, and hosted runners (macOS above all) share
# their addresses with other people's jobs. Without one the call is anonymous.
# The token never reaches the log.
auth=()
token="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
if [ -n "$token" ]; then
  auth=(-H "Authorization: Bearer $token")
fi
release_json="$work/release.json"
# The HTTP status is kept so the failure can name its cause.
status="$("$curl" -sSL --retry 3 --max-time 60 -H "Accept: application/vnd.github+json" \
  ${auth[@]+"${auth[@]}"} -w '%{http_code}' -o "$release_json" "$pin_api")" || status="${status:-000}"
status="${status//[^0-9]/}"
if [ "$status" != 200 ]; then
  echo "The transcription gate failed: could not read release $pin_tag from $pin_api" \
    "(HTTP ${status:-000})." >&2
  case "$status" in
    403 | 429)
      echo "GitHub refused the call: usually its API rate limit, which an anonymous call" \
        "shares with every job on the same address. The workflow passes GITHUB_TOKEN to" \
        "this step; check it still does, then run the job again." >&2
      ;;
    404 | 410)
      echo "The release or its repository is gone, renamed or private." >&2
      ;;
    000 | "")
      echo "GitHub could not be reached; run the job again." >&2
      ;;
  esac
  exit 1
fi
if ! "$python" - "$release_json" "$pin_name" "$pin_size" "$pin_sha256" "$pin_tag" <<'PY'; then
import json
import sys

path, name, size, sha256, tag = sys.argv[1:6]
try:
    with open(path, encoding="utf-8") as handle:
        release = json.load(handle)
except (OSError, ValueError) as error:
    sys.exit(f"cannot read the release metadata {path}: {error}")
assets = release.get("assets") if isinstance(release, dict) else None
if not isinstance(assets, list):
    sys.exit(f"release {tag} lists no assets")
found = [a for a in assets if isinstance(a, dict) and a.get("name") == name]
if not found:
    sys.exit(f"release {tag} has no asset named {name}")
asset = found[0]
if asset.get("size") != int(size):
    sys.exit(f"the asset {name} is {asset.get('size')} bytes; the pin says {size}")
digest = asset.get("digest")
if digest:
    if digest != f"sha256:{sha256}":
        sys.exit(f"the asset {name} has digest {digest}; the pin says sha256:{sha256}")
    print(f"The published model matches the pin: {name} in {tag}, {size} bytes, sha256 {sha256}.")
else:
    print(f"The published model matches the pin by size: {name} in {tag}, {size} bytes"
          " (GitHub gave no digest to compare the sha256 with).")
PY
  echo "The transcription gate failed: the published model no longer matches model_store.py." >&2
  echo "A release asset is never replaced in place; see tools/export_local_model/README.md." >&2
  exit 1
fi

# One greppable line per download this run adds to the asset's count, so CI's
# share of it can be counted from the Actions logs:
#   gh run view <run-id> --log | grep -c 'QALUN-CI-MODEL-DOWNLOAD '
if [ -d "$pin_dir" ]; then
  echo "Speech model already in the cache ($pin_dir): no download."
else
  echo "QALUN-CI-MODEL-DOWNLOAD $pin_tag $pin_name: not in the cache, so this run downloads it once."
fi

stripped=/nonexistent
if [ "$windows" = true ]; then
  # What check.ps1 leaves the doctor: Windows' own folders and nothing else.
  system_root="$(cygpath -u "${SYSTEMROOT:-${SystemRoot:-C:/Windows}}")"
  stripped="$system_root/System32:$system_root"
fi

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

# What the build runs

The build file under `.github/workflows/` is orchestration only: which machines,
in what order, and what to upload. Everything platform-specific lives here, in
ordinary scripts.

That split is deliberate, and it was learned the hard way. A GitHub token needs a
separate `workflow` scope to change anything under `.github/workflows/`, so
editing the build file is a manual step for whoever holds the right credentials,
while these scripts push like any other file. Fixing Windows three times in a row
should not mean editing the build file three times in a row.

| script | runs on | does |
| --- | --- | --- |
| `collect-windows.ps1` | Windows | fetch FFmpeg and FriBiDi into `vendor/` |
| `collect-macos.sh` | macOS | the same, and make FFmpeg self-contained |
| `collect-linux.sh` | Linux | the same, and install the libraries Qt links (sound, graphics, xcb) on the bare runner, so PyInstaller bundles the ones it may and the gate can load Qt |
| `stage.sh` | all | copy `vendor/` in beside the built executable |
| `check.sh` / `check.ps1` | all | run the built app's own `--doctor --release`, with PATH stripped and `QURANTEXT_TRANSCRIBE_ENGINE=local`: render, the local engine's runtime (sherpa-onnx), the Replicate client (blocking whatever the engine, because the window offers WhisperX), play audio (through FFmpeg), Qt's Arabic translation, an Arabic interface font. Killed and failed after 180 s. On Linux, also fail when the bundle has no `libxcb-cursor.so.0`, which the doctor, drawing offscreen, cannot notice. When all that passes, run `check-transcription.sh` |
| `check-transcription.sh` | all (Git's bash on Windows) | check through GitHub's API that the published model asset still has the size and sha256 pinned in `model_store.py`, then transcribe a 5 s tone inside the built app with `--cli transcribe --engine local --no-cache`, PATH stripped, and fail unless the transcript has a `segments` list. Killed and failed after 900 s. See below |
| `package.sh <artifact>` | all | zip the app into `out/<artifact>.zip`: `ditto` on macOS, `zip -ry` on Linux so symlinks stay symlinks, Python's `make_archive` on Windows. `THIRD_PARTY_NOTICES.md` and `LICENSE` go at the top: beside the executable in `qalun/`, and beside `Qalun.app` on macOS. On Linux only, also write `out/qalun-source-<tag or commit>.zip`, `git archive` of the commit built (Qalun is GPL-3.0-only, so each release carries its source); fails outside a git checkout |

`vendor/` holds what the app needs at runtime but does not carry itself: FFmpeg,
because nobody should have to install an encoder, and FriBiDi, because Pillow
loads it by name at runtime and no Pillow wheel contains one. See
`docs/findings/pillow-fribidi.md`.

## The transcription gate

`check-transcription.sh` proves that transcription on this computer, the default
engine, works inside the app that ships, on each platform: the sherpa-onnx runtime
loads, the speech model downloads from the public `qalun-models` release and its
size and checksums verify (when there is no cache; see below), the model loads,
FFmpeg beside the app decodes, and the app writes a
transcript with `segments`. The audio is a 5 s tone made with FFmpeg, so no
recording is kept in the repository. A tone has no words, so it usually gives no
segments; that is fine. How well the model recognises speech is the parity gate's
job, not this one's.

When it fails, it is usually one of three things:

- the `qalun-models` release asset is broken, renamed or gone;
- the pinned checksum in `src/qurantext/services/model_store.py` no longer matches
  the asset (a release asset is never replaced in place; see
  `tools/export_local_model/README.md`);
- a sherpa-onnx native library (its own, ONNX Runtime, or on Linux the vendored
  `libasound`) is missing from the bundle.

It runs only after the doctor has passed, so a build that will not ship never
downloads the model.

On a run that restores the cache below, the model comes from the cache, not from
the release. So every run, cache or not, first reads release `model-v1` of
`Grazyen96/qalun-models` from GitHub's REST API and fails unless it has an asset
with the pinned file name, the pinned size and, when the API gives a `digest`, the
pinned sha256. Reading release metadata does not add to the asset's download
count. The expected values come from `LOCAL_MODEL` in `model_store.py`, read with
the runner's Python, so they are written down in one place; a test checks that the
script does not repeat them. The call uses `GITHUB_TOKEN` when the environment has
one and is anonymous otherwise (one call per platform per run, well inside
GitHub's anonymous limit); the workflow passes no token today. The cache itself
only ever holds a folder that a previous run downloaded and verified, because a
cache is saved only when the job succeeds.

### The model cache, and the download count

Downloads of the model's release asset are how installs are counted, so CI should
not add one per build. On GitHub Actions the gate points the app at
`.ci-cache/qalun` (`QURANTEXT_CACHE_DIR`, unless that is already set), and the
**Keep the speech model between runs** step in `release.yml` caches
`.ci-cache/qalun/models` between runs, one cache per platform. Its key is the
model archive's pinned sha256 from `model_store.py`, written out in `release.yml`;
`tests/test_gate_script.py` fails if the two disagree. Publishing a new model
therefore needs one edit to `release.yml`, by someone whose token has the
`workflow` scope.

The count still includes CI downloads: one per platform each time a cache misses.
That happens on the first run after the key changes and after GitHub evicts a
cache that has gone unused for 7 days, which, with releases weeks apart, may be
most release runs. Caches are also per branch: a run can restore a cache saved on
its own branch or on the default branch, so a tag build can use master's, but a
run dispatched on a feature branch misses until that branch has saved one.

Each miss is logged. Before the app runs, the gate prints exactly one line
starting `QALUN-CI-MODEL-DOWNLOAD` (with the release tag and asset name) when the
model folder is not in the cache, and none on a hit. CI's share of the count is
the number of those lines in the build logs, for example
`gh run view <run-id> --log | grep -c 'QALUN-CI-MODEL-DOWNLOAD '` per run; take
that off the asset's download count.

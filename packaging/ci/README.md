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
| `check-transcription.sh` | all (Git's bash on Windows) | transcribe a 5 s tone inside the built app with `--cli transcribe --engine local --no-cache`, PATH stripped, and fail unless the transcript has a `segments` list. Killed and failed after 900 s. See below |
| `package.sh <artifact>` | all | zip the app into `out/<artifact>.zip`: `ditto` on macOS, `zip -ry` on Linux so symlinks stay symlinks, Python's `make_archive` on Windows. `THIRD_PARTY_NOTICES.md` goes at the top: beside the executable in `qalun/`, and beside `Qalun.app` on macOS |

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
the release: the gate then proves the runtime, the model loading and the output,
but not that the asset can still be downloaded. The cache only ever holds a folder
that a previous run downloaded and verified, because a cache is saved only when the
job succeeds. To prove the asset itself before a release, delete the
`qalun-model-*` caches (Actions → Caches) and run the build again.

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
most release runs. Read the asset's download count with up to three per workflow
run taken off.

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
| `collect-linux.sh` | Linux | the same |
| `stage.sh` | all | copy `vendor/` in beside the built executable |
| `check.sh` / `check.ps1` | all | run the built app's own `--doctor --release`, with PATH stripped: render, transcribe, play audio, Qt's Arabic translation, an Arabic interface font |
| `package.sh <artifact>` | all | zip the app into `out/<artifact>.zip`: `ditto` on macOS, `zip -ry` on Linux so symlinks stay symlinks, Python's `make_archive` on Windows |

`vendor/` holds what the app needs at runtime but does not carry itself: FFmpeg,
because nobody should have to install an encoder, and FriBiDi, because Pillow
loads it by name at runtime and no Pillow wheel contains one. See
`docs/findings/pillow-fribidi.md`.

## One change the build file still needs

`package.sh` is not used yet. The **Package** step in `release.yml` still zips with
Python's `shutil.make_archive`, which follows symlinks. PyInstaller puts links in
the Linux bundle's `_internal/` to the Qt and FFmpeg libraries, so every one of
those libraries is stored twice and the Linux app unpacks to 446 MB instead of
275 MB. Whoever holds a token with the `workflow` scope should replace that
step's whole `run:` block with one line, keeping `shell: bash`:

```yaml
      - name: Package
        shell: bash
        run: bash packaging/ci/package.sh ${{ matrix.artifact }}
```

It writes the same `out/<artifact>.zip` the upload step already picks up, and does
what the old block did on macOS and Windows.

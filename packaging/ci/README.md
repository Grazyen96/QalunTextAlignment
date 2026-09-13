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
| `check.sh` / `check.ps1` | all | run the built app's own `--doctor`, with PATH stripped |

`vendor/` holds what the app needs at runtime but does not carry itself: FFmpeg,
because nobody should have to install an encoder, and FriBiDi, because Pillow
loads it by name at runtime and no Pillow wheel contains one. See
`docs/findings/pillow-fribidi.md`.

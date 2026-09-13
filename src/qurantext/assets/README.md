# Bundled assets

Files that ship inside the wheel, reached with
`qurantext.config.paths.bundled_asset(...)`.

They live under the package rather than at the repository root because a wheel
only carries what is inside `src/qurantext/`. Keeping the font here is what
makes `pip install qurantext` produce a working renderer instead of one that
resolves its default font into the Python installation directory.

- `fonts/qaloon.10.ttf` — the Qalun face the frame renderer draws with.
- `fonts/qaloon.10.woff2` — the same face for web use.

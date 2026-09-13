# Bundled assets

Files that ship inside the wheel, reached with
`qurantext.config.paths.bundled_asset(...)`.

They live under the package rather than at the repository root because a wheel
only carries what is inside `src/qurantext/`. Keeping the font here is what
makes `pip install qurantext` produce a working renderer instead of one that
resolves its default font into the Python installation directory.

- `fonts/qaloon.10.ttf` — the Qalun face the frame renderer draws with.
- `fonts/qaloon.10.woff2` — the same face for web use.
- `quran/UthmanicQaloon1-Ver05.txt` — the certified Qalun text everything is
  built from: the store, the citation index, the ayah text on screen.

The Quran text ships for more than convenience. The parser expects this file's
exact conventions, and the ayah numbering has to be the Madani counting the rest
of the data assumes, so "bring your own text" is a way to get subtly wrong
output rather than an obvious failure.

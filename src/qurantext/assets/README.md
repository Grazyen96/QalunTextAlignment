# Bundled assets

Files that ship inside the wheel, reached with
`qurantext.config.paths.bundled_asset(...)`.

They live under the package rather than at the repository root because a wheel
only carries what is inside `src/qurantext/`. Keeping the font here is what
makes `pip install qurantext` produce a working renderer instead of one that
resolves its default font into the Python installation directory.

- `fonts/qaloon.10.ttf` — the Qalun face the frame renderer draws with.
- `fonts/qaloon.10.woff2` — the same face for web use.
- `fonts/Amiri-Regular.ttf`, `fonts/Amiri-Bold.ttf` — the text font for the
  generated intro's and outro's titles, which need Latin letters as well as
  Arabic ones; the Quran font has no Latin. `fonts/Amiri-OFL.txt` is its licence.
- `quran/UthmanicQaloon1-v10.txt` — the certified Qalun text everything is
  built from: the store, the citation index, the ayah text on screen.
- `icons/*.svg` — the window's interface icons, 31 Lucide icons at release
  1.56.0, drawn in the theme's colours by `qurantext.gui.icons`. `icons/LICENSE`
  is their licence: ISC, and MIT for the nine derived from Feather (see
  `THIRD_PARTY_NOTICES.md`).
- `icon/` — the app's own icon (`qalun.svg` and the sizes drawn from it, the
  `.ico` for Windows and the `.icns` for macOS); the project's own work, under
  Qalun's licence.

The Quran text ships for more than convenience. The parser expects this file's
exact conventions, and the ayah numbering has to be the Madani counting the rest
of the data assumes, so "bring your own text" is a way to get subtly wrong
output rather than an obvious failure.

## Where the Quran text comes from

`quran/UthmanicQaloon1-v10.txt` is the KFGQPC (King Fahd Glorious Quran
Printing Complex) Qaloon text v10, obtained via `thetruetruth/quran-data-kfgqpc`
at commit e35e7b5 (`qaloon/data/QaloonData_v10.json`, sha256
`18465c40ebeec40a92eb98745c9b89796ac6e31f6e93988883dfb6602faaea95`) and
converted by `tools/convert_mushaf_v10.py`. v10 is the edition the bundled
`qaloon.10` font was drawn for, with the pause marks the font has glyphs for.

The converter keeps the layout of the KFGQPC Ver05 text Qalun shipped before
(`UthmanicQaloon1-Ver05.txt`, now only in git history): its surah headers,
basmala lines, page breaks, ayah markers and line breaks, with the v10 words in
place of the Ver05 ones. The parser is unchanged and every word keeps its page
and line. The letters of every ayah are the same in both editions; v10 adds
pause marks, places some ۞ and ۩ differently, writes alef maksura where Ver05
writes yeh, and splits two words Ver05 ran together (41:46 «مَا مِنَّا», 41:50
«وَنَـَٔا بِجَانِبِهِۦۖ»). KFGQPC's Ver05 attribution footer, which named that
edition's version number, is not carried over.

## Licence: not Qalun's

The font (`fonts/qaloon.10.ttf`, `fonts/qaloon.10.woff2`) and the Quran text
(`quran/UthmanicQaloon1-v10.txt`) are third-party works. Qalun's own licence,
GPL-3.0-only, does not cover them, even though they ship inside the package,
the app and its source zip. Their provenance and terms are to be confirmed by
the owner; until then `THIRD_PARTY_NOTICES.md` says so, and the release
checklist holds the first release until they are confirmed and written down
there. The text's source is recorded above; its terms are not.

## Amiri: the text font

`fonts/Amiri-Regular.ttf` and `fonts/Amiri-Bold.ttf` are Amiri release 1.003,
https://github.com/aliftype/amiri/releases/tag/1.003, taken unmodified from
the release archive `Amiri-1.003.zip` (sha256
`81af0aff7d2086d8af24cea7202f7546130997982534691373485cd96744d05e`, the digest
GitHub publishes for it), fetched 12 Oct 2026:

- `Amiri-Regular.ttf`, sha256
  `cd2550c0f4c05eb341bf97958211aaa39382bca96577ba3a67d4a3b4912c43c0`
- `Amiri-Bold.ttf`, sha256
  `8cfed49b66de57e360ac61631d882dddfa23095d3ddb39fc2133eaf93892e79a`

Copyright 2010-2022 The Amiri Project Authors, under the SIL Open Font License,
Version 1.1. The licence, the release's `OFL.txt`, is `fonts/Amiri-OFL.txt`
beside the fonts, so it travels wherever they do (the wheel, the app, the
source zip); `packaging/licenses/Amiri-OFL.txt` keeps the same text.
`tests/test_packaging_spec.py` checks both hashes.

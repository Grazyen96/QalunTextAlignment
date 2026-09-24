# Release checklist

What a person has to check before tagging a release, because a machine here cannot.
Work top to bottom; stop at the first item that fails and fix it before going on.

## Once, before the first release that uses `package.sh`

- [ ] In `.github/workflows/release.yml`, replace the whole `run:` block of the
      **Package** step with `run: bash packaging/ci/package.sh ${{ matrix.artifact }}`.
      This needs a token with the `workflow` scope, which is why it is not done in the
      repository already (see `packaging/ci/README.md`). Until then the Linux zip stores
      every symlinked library twice and unpacks to about 600 MB instead of about 430 MB
      (both with FFmpeg).

## Build

- [ ] Actions → **Build the app** → **Run workflow**, on the commit you mean to tag.
- [ ] Every platform's gate step (**Check the built app can render**, which runs
      `--doctor --release`) passes on Windows, macOS and Linux.
- [ ] In each platform's gate log, the Playback line says `through the FFmpeg backend,
      as QT_MEDIA_BACKEND asks`. Windows and macOS also ship a native backend, and only
      this line shows the recording did not play through that one instead.
- [ ] Record the Windows and macOS zip sizes (on the run's summary page) in the Size
      table in `packaging/README.md`. Compare each with that platform's zip from a build
      of `30a159c` (23 Sep 2026) or earlier: the one before `57fc739`, which is where
      Multimedia entered the bundle, because PyInstaller follows the player's import on
      its own. There are no `v*` tags, so there is no Release to compare with, and
      workflow artifacts expire after 30 days. If no such run survives, compare with
      Linux instead: Multimedia added 20 MB to the Linux zip, so expect about that. If a
      zip grew far more than 30–40 MB, stop and find out why before releasing.
- [ ] Download `qalun-linux.zip` and unzip it with `unzip`. Check two things (the gate
      already checks that `libxcb-cursor.so.0` is in the bundle):
  - `find qalun -type l | wc -l` is not 0. If it is 0, the links were not kept: check
    the Package step change above.
  - `du -sm qalun` is about 430 MB, FFmpeg included. About 600 MB means the links were
    followed and every linked library is stored twice.
- [ ] Extract `qalun-linux.zip` once more with the desktop's own **Extract here** (or
      `unzip`), and start the app from that folder. Some extractors (Python's `zipfile`,
      a few minimal tools) write each stored link as a small text file, and the app then
      cannot find its Qt libraries. In the release notes, tell Linux users: "Extract with
      your file manager or `unzip`."

## By ear, on Windows and Linux

This is the spec's §6 manual check.

- [ ] Open the packaged app. Do not use a checkout.
- [ ] Start a recitation job on `furquanTra7-11.mp3` (surah 25, ayat 7–11). It is in
      `input/recitations/`, which is not in git.
- [ ] In the review, play the recording. Find the late words at the end of 25:7, where
      speech runs uncovered from about 16.7 s to 24.2 s. Fix the rift by ear by rippling
      the late words.
- [ ] Save, then render.
- [ ] Check that the MP4 matches what the editor showed. Export an SRT and check that it
      matches too.
- [ ] On Linux, play the recording on a real desktop other than the build machine, for
      example a PipeWire desktop or a distribution other than Ubuntu. Sound must come out.
      The bundle carries the build machine's PulseAudio and libsndfile client libraries,
      so the doctor's playback check on CI does not prove this.
- [ ] On Linux, start the window in an X11 session as well as a Wayland one.

## Arabic, on a real desktop

- [ ] Switch the window to العربية.
- [ ] With an Arabic keyboard layout active, check that `[ ] , .` still set and nudge in
      the review. Do this on Windows and macOS as well as Linux: the key codes those two
      use have not been tried on real machines. Try it with the segment table not
      focused: while it has focus, an Arabic letter goes to the table instead, on purpose.
- [ ] Window title bars show no boxes.
- [ ] Qt's own buttons, in the file dialog and in Save/Discard, are in Arabic.
- [ ] On a machine without an Arabic font (a fresh Linux VM), the window still draws
      Arabic letters, using the bundled Quran font. Check that the result is readable.
      This has not been seen on a real machine yet.
- [ ] On macOS, after choosing a language, check that the settings file is at
      `~/Library/Preferences/com.qalun.Qalun.plist`, as `README.md` says.

## Words

- [ ] A native Arabic speaker reviews `STRINGS["ar"]` in `src/qurantext/gui/i18n.py`,
      in the running app, and edits the table in place. Start with the uncertain ones:
  - `review.mark_reviewed`, `review.snap` and `segments.retimed`
  - «م.ث» (milliseconds)
  - the Cancel and Close forms
  - `review.save` used as a dialog title
  - `home.reading`
  - the five `job.stage.*` lines
  - the video header: «الآيات 7 - 11» or «الآيات من 7 إلى 11»
- [ ] Keep every direction mark: the U+2066…U+2069 isolates and the U+200F marks,
      written as `\u2066`-style escapes in the source. The tests fail if a key goes
      missing.

## Publish

- [ ] Tag the release and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`. The
      workflow builds again and attaches the three zips to a Release.
- [ ] If the release is announced anywhere (a website, a post, a QR code on printed
      material), link to the Release page with UTM parameters. Use one `utm_source` per
      channel, so downloads can be counted per channel:
      `https://github.com/Grazyen96/QalunTextAlignment/releases/latest?utm_source=<channel>&utm_medium=<post|print|qr>&utm_campaign=qalun-vX.Y.Z`.
      GitHub's own download counts for the release give the total. GitHub does not show
      the owner which query strings a visit came with, so to read the UTMs back, point
      the printed link or QR code at a page or redirect you have analytics on, and let it
      forward to the Release page. The app itself sends nothing.

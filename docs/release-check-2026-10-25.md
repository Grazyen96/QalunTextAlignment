# Qalun release check: v0.3.0 pre-release

Date: 2026-10-25. Release candidate: `13b8166` on master (equal to `origin/master`, clean
tree). Scope: the whole app as a tester would get it (the new-job form, transcription,
matching, the review editor, Look, render, export, episode, the home window, Settings, both
languages and themes, the command line, logs), plus what ships with it (bundle contents,
licences, notices, docs, links) and the Quran text from its source to the screen.

## 1. Verdict

**Not ready to tag at `13b8166`, but two small fixes away.** Both blockers were reproduced
independently, and both are cheap to fix:

- **QRN-1:** the subtitle files write open tanween with code points that only the bundled
  KFGQPC font draws as open tanween. Any other font shows other marks (an inverted damma, a
  fatha with two dots, a subscript alef). That affects SRT, VTT and ASS on YouTube, in any
  player, and in the ASS file's own font, in 57 % of ayat.
- **REL-1:** Pillow's 18 bundled libraries ship without their licence notices.

Everything else can go out as a pre-release. Nine majors are cheap enough to fix in the same
round (section 4.2). The most important:

- **The new user guide is wrong on three core steps.** It offers "Detect automatically" for
  recitations, which do not have it. It gives a nudge instruction that moves the wrong word.
  It describes a first-open step that macOS 15 no longer allows.
- **Every icon is cropped on high-density screens:** every Retina Mac and most Windows laptops.
- **A cancelled or interrupted re-render deletes the earlier video.**

Four majors need design work and should be named as known issues in the release notes
(section 4.3).

The base is strong:

- 2,493 tests pass, and all three user journeys finish end to end.
- The Quran text is byte-identical to its pinned source, and every card and video frame draws
  it exactly.
- The full-size preview matches the rendered frame.
- A 13-minute episode joins frame- and sample-exact, and its outro QR decodes to the right
  tracked link.
- Projects and settings from v0.2.0 open unchanged.
- Matching, the review editor and rendering did not regress since v0.2.0.

Two things did get worse since then: the icons on high-density screens (SHL-1), and the
review window's Quran font (QRN-2).

Totals: 96 findings from eight auditors. All 26 reported as blocker or major were re-checked
by fresh agents:

- 2 blockers held.
- 13 distinct majors held (18 reports, because some were found by two or three lenses).
- 5 were downgraded to minor, and 1 is already on the owner's licence list.
- The 70 minor and polish findings are listed in section 7 but were not re-checked. Section 7
  also has one more minor, found while verifying this report (VER-1).

## 2. How this check was run

- **What is being released:** v0.3.0, published as a GitHub pre-release (as v0.2.0 was) for
  testers on Windows, macOS and Linux. The four first-release blockers at the top of
  `docs/release-checklist.md` stay open for a pre-release and did not decide this verdict.
- **Phase 0, freeze and rules:** a feature inventory (25 features in four groups), one
  severity scale, one scorecard, one finding format, and a list of what is intended or
  already known, so that decisions were not reported as bugs.
- **Phase 1, automated checks, run once:** the results in section 3, shared by every agent.
- **Phase 2, audit:** eight read-only auditors in parallel:
  - three end-to-end journeys as the guide's reader
  - every screen
  - the four feature groups: input and transcription, the review editor, output, the app
    frame
  - release and docs
  - the Quran text from its source to the screen
- **Phase 3, verification:** every blocker and major went to a fresh agent that had to
  reproduce it with its own evidence. What it could not reproduce was dropped or downgraded
  (section 8). In all, 16 agents ran for 52 minutes.
- **Evidence:** `output/release-check-2026-10-25/` (git-ignored, on this machine only):
  - `00-brief.md`, `features.md`, `known.md`
  - `gates/`, `links/`, `shots/`, `runs/`, `frames/`
  - each agent's probe scripts, outputs and grabs, under `findings/<lens>/`

  Every probe ran with `sandbox/env.sh`, so settings, logs, caches, the Quran store and
  outputs stayed out of the real folders. There were two exceptions, both before or outside
  the sandbox:
  - The first probe, `qalun --help`, opened the window against the real settings for about
    two minutes before it was stopped. `~/.config/Qalun/Qalun.conf` was saved at 07:39 and
    holds no value from this check.
  - The test suite overwrote `~/.local/share/qalun/doctor-report.txt` with "a report"
    (VER-1). `qalun --doctor` writes it again.

  The repository has no change except this report.
- **What this check could not cover:** everything ran on one Linux laptop, from the checkout
  and offscreen. Not covered:
  - the packaged zips (CI builds them)
  - Windows and macOS
  - real sound output and listening by ear
  - a native Arabic reading
  - real keyboards and real HiDPI screens (simulated with `QT_SCALE_FACTOR`)
  - Gatekeeper and SmartScreen
  - how YouTube and other players draw the subtitle files

  These stay on the owner's checklist (section 10).

## 3. Automated checks (Phase 1)

| Check | Result |
|---|---|
| Test suite (offscreen) | 2,493 passed, 2 skipped (the Windows fault log; the opt-in slow model test), 213 s |
| Lint (ruff 0.15.13) | Clean |
| `qalun --doctor --release` (`packaging/entry.py`, from the checkout) | Every check ok, "Ready to render"; the version still says 0.2.0 |
| Screenshots (`tools/screenshots.py`) | 68 images: every window and dialog, English and Arabic, light and dark, in 31 s |
| Recitation, range stated (`furquanTra7-11.mp3`, 97 s, 25:7–11) | Transcribed and aligned in 4.3 s at a peak of 0.97 GB; one five-ayah card |
| Recitation, range detected (CLI) | Found 25:7–11 at confidence 1.00, with the same card and word timings |
| Recitation render (1280×720 at 25 fps, subtitles both) | 2,527 frames in 7 s; MP4 plus SRT, VTT and ASS |
| Lecture (`الفرقان7-11-final.wav`, 13 min) | Transcribed and matched in 30 s at a peak of 1.0 GB; 6 cards, 34 captions |
| Lecture render (960×540 at 24 fps, subtitles both) | 60 s; MP4 plus SRT, VTT and ASS |
| Links (93 unique, loaded without a login) | All load except one dead address inside onnxruntime's own notice file. Help and About load (200) since the repository was made public on 25 Oct. |
| Release page | v0.2.0 is a published pre-release with three zips (Linux 210 MB, Windows 184 MB, macOS 104 MB); GitHub counts 0 downloads |

## 4. Blockers and majors (verified)

### 4.1 Blockers: fix before tagging

| # | Finding | Where | Fix |
|---|---|---|---|
| QRN-1 | **Subtitle files show wrong tanween marks.** The shipped text writes open fathatan, dammatan and kasratan as U+0657, U+065E and U+0656. Only `qaloon.10.ttf` draws these as open tanween. Every other font draws an inverted damma, a fatha with two dots or a subscript alef. SRT, VTT and ASS copy the text byte for byte, so the marks are wrong wherever the files are shown: YouTube, players, and the ASS file's own Amiri. 3,522 of 6,214 ayat carry them. The video is right, because it is drawn in the KFGQPC face. Not a regression: v0.2.0 shipped the same. | `core/subtitles.py:123-160`, `:232` | When writing subtitles (and for the CLI's `--renderer ass`), map U+0657→U+08F0, U+065E→U+08F1 and U+0656→U+08F2. Never map for the video, because `qaloon.10` has no U+08F0–08F2. Add a test that written subtitles contain none of the three. Leave U+06D2 as it is: the verifier found that half is not a defect (section 8). |
| REL-1 | **Pillow's bundled libraries ship without their licence notices.** The spec copies metadata only for certifi, idna and replicate, so the 18 libraries in `pillow.libs` ship with none of their notices. These include libjpeg-turbo, libtiff, FreeType, HarfBuzz, lcms2, OpenJPEG, libwebp, brotli, zstd, libavif and libxcb. Their licences allow redistribution only with the notice. `THIRD_PARTY_NOTICES.md:250-254` points at a Pillow LICENSE the app does not carry. Python's own libffi, Expat and bzip2 texts are missing too. | `packaging/qalun.spec:101-111` | Add `datas += copy_metadata('pillow')` and Python's `LICENSE.txt`, and point the notices at both. Let `tests/test_packaging_spec.py` assert they are in `datas`. |

### 4.2 Majors that are cheap enough to fix before tagging

| Finding (lenses that found it) | What happens | Fix |
|---|---|---|
| **Guide promises "Detect automatically" for recitations** (JRN-1, INT-1, REL-3) | The recitation form has no such choice. It opens on Al-Fatiha 1–7 with Start enabled. Leaving it there gives a confident wrong match: two Al-Fatiha cards, confidence 1.0, no warning. The guide's troubleshooting repeats the advice (`USER_GUIDE.md:71-72`, `:210-212`). | Rewrite step 3 and the troubleshooting line. A recitation needs its surah and ayat; "Detect automatically" is the lecture's choice. |
| **Guide's nudge step retimes the next word, not the late one** (JRN-2, REV-1) | Selecting a word arms its end edge (`word_strip.py:141`). The nudge then moves the next word's light-up (52 of 67 words) and never the selected one's. | Default the armed edge to the start, which is what the highlight follows, and show which edge is armed. Or reword the guide. |
| **Cancelling or closing a re-render deletes the earlier video** (JRN-3, INT-3) | The render writes straight to `<stem>.mp4` and deletes it when it does not finish (`frame_renderer.py:1268`, `:1538-1544`). The list still says Rendered and the project names the missing file. Closing a review while it renders asks nothing. | Render to a `.part` file and replace on success, as `jobs/episode.py` already does. Have `job_status` treat a missing video as not rendered. Ask before closing a review that is rendering. |
| **Every icon is cropped above 100 % display scaling** (SHL-1) | `gui/icons.py:85` renders the SVG with no target rectangle, so every 2× pixmap holds the icon's top-left quarter (123 of 123). Every Retina Mac and most Windows laptops (125–175 %) show fragments: the gear, Help, the theme toggle, the transport. The guide steers by those glyphs. New since v0.2.0, which had text-only buttons. | One line: `renderer.render(painter, QRectF(0, 0, size, size))`, plus a 2× test. |
| **The review window draws Quran words with the wrong tanween** (QRN-2) | Same cause as QRN-1. The word strip, the segment table's text cells and the selection bar use the interface font, Noto Sans Arabic since 9e14e6b. Only the ayah picker uses the Quran face. So the editor shows the wrong marks, and the checklist's "SRT matches the editor" step cannot catch QRN-1. | `setFamilies([quran_family, …])` on those widgets, as `ayah_picker.py:59-70` does. Or apply QRN-1's mapping for display. |
| **The basmala card and cue drop the Qaloon wasl marks** (QRN-3) | `core/preamble.py:43` holds a Hafs-style «بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ». The shipped text writes «بِسْمِ اِ۬للَّهِ اِ۬لرَّحْمَٰنِ اِ۬لرَّحِيمِ» on 111 of 113 basmala lines. The constant shows on the card and in the subtitle cue whenever a spoken basmala is detected. | Build it from the shipped text's opening basmala line. |
| **macOS 15+: "right-click → Open" no longer works** (JRN-6, REL-4) | The release notes template (`release.yml:151-153`) and the live v0.2.0 page give that advice. Apple removed the override in macOS Sequoia: users must use System Settings → Privacy & Security → Open Anyway. The guide says nothing about first-open warnings on any system. | Fix the notes template and the guide's step 2: on Mac, Open Anyway; on Windows, More info → Run anyway. |
| **The macOS app is changed after it is signed** (REL-5; reproduced in code only, no Mac here) | `packaging/ci/stage.sh:6-8` copies FFmpeg and its libraries into `Qalun.app` after PyInstaller's ad-hoc signature. That breaks the bundle seal, so a downloaded app likely reads "damaged". The gate runs the binary unquarantined and cannot notice. If confirmed, it blocks Mac testers. | Sign again after `stage.sh`, and add `codesign --verify --deep --strict` to the macOS gate. |
| **No OS or CPU requirements anywhere** (REL-6) | 37 bundled Linux libraries need glibc 2.38+ (Ubuntu 24.04 or newer, and the like). The macOS build is Apple silicon only. The guide and README list only memory, disk and internet. | State it in the guide, the README and the release notes, or build Linux on an older base. |

### 4.3 Majors to name as known issues in the release notes

| Finding | What happens | Direction |
|---|---|---|
| **A stated range that does not fit the recording is accepted silently** (INT-2) | Wrong ranges align at confidence 1.0 with no warning. Only 9–30 % of heard words fit the stated text, against 100 % for the right range. | Measure the fit after alignment, and warn in the review banner and the job list. |
| **Lecture cards appear 12–18 s before the ayah is quoted** (INT-4) | A card starts at the earliest overlapping matcher window. In the run, 25:7 stays on screen through the whole 25:8 recitation. | Trim each card to the words that align to its ayah, and expose the card edges in the review (`set_card_times` has no UI). |
| **Short ayat quoted verbatim are missed** (INT-5) | The dagger alef (U+0670) is stripped in normalisation, and ayat under six words need 0.90. 75:5 scores 0.881 and is dropped; with U+0670 read as alef it scores 1.000. | Map U+0670 to alef in the detection normaliser, and accept a whole short ayah heard exactly. |
| **Changing a job's video size strands its corrections** (JRN-4) | The size is chosen on the new-job form only. Re-running the job to change it replaces the corrected project and moves the corrections to an unlisted `.qalun-backup.json`. | Let the review change the size before Render, or keep corrections when a re-run uses the same transcript. |

## 5. Scorecard per feature

Scores from 1 (broken) to 5 (nothing wrong found): works · fails well · clear · consistent ·
documented · tested. The verdicts are the auditors'. C3 is moved to **hold** because the
Quran lens's verified blocker QRN-1 sits in its output.

| Feature | Verdict | W | F | C | K | D | T | Main reason |
|---|---|---|---|---|---|---|---|---|
| A1 New-job form | ship, known issues | 4 | 3 | 3 | 4 | 2 | 4 | Arabic letters and spaces in paths work end to end; no detect choice for recitations, opens on 1:1–7 |
| A2 Transcription | ship | 5 | 4 | 4 | 4 | 4 | 5 | 22–26× real time at ≤1.0 GB; offline, 404, bad checksum and Cancel all end cleanly |
| A3 Recitation matching | ship, known issues | 4 | 2 | 3 | 3 | 3 | 4 | Stated and detected runs agree on 67/67 timings; wrong ranges pass at confidence 1.0 (INT-2) |
| A4 Lecture matching | ship, known issues | 3 | 3 | 3 | 4 | 3 | 3 | All six studied ayat and the right surah found; cards early (INT-4); short quotes missed (INT-5) |
| A5 Job lifecycle | ship, known issues | 4 | 2 | 3 | 4 | 2 | 3 | Plain stages and errors; cancelling a re-render deletes the video (INT-3) |
| B1 Playback | ship, known issues | 5 | 3 | 4 | 4 | 4 | 4 | Plays, rates and seeks; silent with no audio device (REV-6); no relink (REV-7) |
| B2 Timeline | ship | 5 | 4 | 4 | 5 | 5 | 5 | Right to left, identical in English and Arabic |
| B3 Retiming & history | ship, known issues | 3 | 4 | 2 | 4 | 2 | 4 | Undo exact after 5,400 random actions; the guide's nudge moves the wrong edge (REV-1) |
| B4 Segment table | ship, known issues | 5 | 3 | 4 | 4 | 3 | 4 | Quran cells locked; a caption fix that adds a word drops its timings (REV-5); wrong tanween (QRN-2) |
| B5 Banner & coverage | ship, known issues | 4 | 4 | 4 | 5 | 3 | 4 | Flags real gaps and re-checks after edits; the checklist's stretch is stale (REV-4) |
| B6 Shortcuts | ship | 5 | 4 | 4 | 4 | 4 | 5 | The sheet equals the 13 installed shortcuts; Arabic scancodes work |
| B7 Preview | ship | 5 | 4 | 4 | 5 | 4 | 5 | Equals the MP4 frame within compression noise (2.65/255) |
| B8 Lecture-only edits | ship | 5 | 5 | 4 | 5 | 5 | 5 | Every rule as specified, in both languages |
| C1 Look | ship, known issues | 4 | 4 | 4 | 4 | 4 | 5 | Colours reach the MP4 exactly; oversized PNGs are decoded before refusal (OUT-9) |
| C2 Render | ship, known issues | 4 | 4 | 4 | 2 | 2 | 4 | Presets exact; the small preview pages long cards differently (OUT-1) |
| C3 Export subtitles | **hold** | 4 | 4 | 3 | 3 | 4 | 4 | Cues valid and exact, but the tanween draws wrong outside the Quran font (QRN-1); ASS never wraps (OUT-2) |
| C4 Episode | ship, known issues | 5 | 5 | 4 | 4 | 4 | 5 | A 13-minute episode joins frame- and sample-exact; subtitles shifted exactly |
| C5 Generated parts & links | ship, known issues | 4 | 4 | 4 | 4 | 3 | 5 | The QR decodes to the exact tracked link; the campaign names the span, not the video (OUT-6) |
| D1 Home | ship, known issues | 4 | 4 | 4 | 4 | 3 | 4 | Statuses and watcher right; Show in folder opens the project's folder (JRN-7) |
| D2 Settings | ship, known issues | 5 | 3 | 4 | 4 | 4 | 4 | Every tab persists; an unwritable output folder is accepted (SHL-8) |
| D3 Language & direction | ship | 5 | 5 | 4 | 5 | 4 | 4 | No missing keys in either language; Qt's own words switch |
| D4 Theme & keyboard | ship, known issues | 2 | 3 | 3 | 3 | 4 | 3 | Icons cropped above 100 % (SHL-1); Tab cannot leave the segment table (SHL-2) |
| D5 Logs & doctor | ship, known issues | 4 | 4 | 4 | 4 | 4 | 4 | The efce116 log fix holds; with two windows on Linux/macOS one logs to `.1` (SHL-4) |
| D6 Command line | ship, known issues | 4 | 3 | 4 | 4 | 3 | 3 | Every `--help` works and errors are one line; pip's `qalun --help` opens the window (SHL-5) |
| D7 Help & About | ship, known issues | 4 | 3 | 3 | 3 | 3 | 3 | Both links tracked and loading; failures are silent (SHL-6) |

## 6. Area verdicts

- **Journeys: ship with known issues.** All three journeys finish:
  - the first recitation video
  - a lecture with an episode
  - next week's correction and re-render

  The guide is the persona's only help and is new in this commit, and it carries most of the
  friction (4.2). The other gaps on these paths are the re-render that deletes last week's
  video (JRN-3), and the size change that strands corrections (JRN-4).
- **Screens: ship with known issues.** The 2026-10-13 audit's presentation layer holds across
  all 68 shots, and Arabic shaping is clean everywhere. Against that audit:
  - Fixed: C1–C3 and C5–C7; H5–H8; R1–R4 and R6–R10; D1–D2; section 6 checks 2, 5, 6 and 7.
  - Partly fixed:
    - C4 spacing (no gutter between the home columns, SCR-6)
    - C8 layout shift (a filling banner, known; a render start, SCR-14)
    - H1–H4 (the home form's hierarchy details)
    - R5 (the Look panel below the fold, known)
    - Check 1: field frames 1.21:1 on the dark Settings pane, SCR-4
    - Check 4: the Arabic zoom row, SCR-2

  On the checklist's image items: `home-running-en-dark` and `export-en-dark` pass, and
  `settings-general-ar-dark` passes only partly (SCR-4).
- **Release & docs: hold, on REL-1 only.**
  - Clean:
    - The spec collects everything added since v0.2.0.
    - The privacy promise holds.
    - The CC BY 4.0 model attribution is visible in About.
    - A v0.2.0 settings file, Quran store and lecture project open unchanged, and so do seven
      older match files.
  - Faulty:
    - Pillow's notices (REL-1).
    - The macOS first-open and signing (REL-4, REL-5).
    - The missing system requirements (REL-6).
    - Stale checklist lines (REL-8).
- **Quran text: hold, on QRN-1 only.** The text is sound end to end:
  - The pinned KFGQPC v10 JSON matches its sha256, and the documented conversion rebuilds the
    shipped file byte for byte.
  - It has 114 surahs, 6,214 ayat and 77,430 words, with 113 opening basmalas plus 27:30.
  - Both stores, every card and the recitation cues are exact.
  - The frames draw the right words, order and ayah numbers.

  What fails is drawing that text outside the Quran font (QRN-1, QRN-2), plus the hard-coded
  basmala (QRN-3).

**What must survive future changes** (the auditors' strengths):

- Every review edit goes through `ReviewSession` and `timing_edit`, and undo is exact.
- Saves are atomic, and the close prompt never loses work.
- The `?` sheet is built from the same bindings the window installs.
- The render path is one function shared by the window, the CLI and the episode.
- The episode join probes before encoding and renames its file only when it is complete.
- Tracked links are strict and keep a person's own parameters.
- The model download is pinned and fails cleanly.
- The transcript cache keys on content.
- The job list never skips a damaged project.
- The converter refuses unpinned data, and nothing in `src/` normalises Unicode.

## 7. Minor and polish findings (reported, not re-checked)

| # | Sev | Feature | Finding |
|---|---|---|---|
| JRN-8 | minor | C4 | Episode subtitle files are only possible if chosen before Start |
| JRN-9 | minor | A1 | Common recording types are refused silently; bad files fail only after the model step |
| JRN-10 | minor | D3 | In Arabic, Help opens the English guide and errors stay English |
| JRN-11 | minor | B5 | A moved recording cannot be relinked; Render just fails |
| JRN-12 | polish | C3 | Export says the video includes a basmala it does not have |
| JRN-13 | polish | D1 | Status names differ from the guide; "Reviewed" needs a button the guide never names |
| JRN-14 | polish | C2 | The review's render bar shows no time estimate |
| SCR-2 | minor | B2 | Arabic zoom row: − and + sit at the wrong slider ends |
| SCR-3 | minor | B1 | English step buttons point against the timeline and their keys |
| SCR-4 | minor | D4 | Dark Settings pane hides its fields (frame 1.21:1) |
| SCR-5 | minor | B5 | Missing recording: neutral notice, Render enabled, no relink |
| SCR-6 | polish | D1 | No gutter between the job list and the form |
| SCR-7 | polish | — | Checked segments wear the primary button's fill |
| SCR-8 | polish | B6 | Arabic shortcut sheet: ragged key column |
| SCR-9 | polish | C3 | Arabic Export dialog cuts the folder path mid-word |
| SCR-10 | polish | D3 | Arabic Close, Cancel and OK are worded differently per dialog |
| SCR-11 | polish | D3 | Two Arabic percent forms («42%» and «٪90») |
| SCR-12 | polish | C5 | Ayah numbers mix Western and Arabic-Indic digits |
| SCR-13 | polish | C4 | Arabic spin-box values sit far from their labels |
| SCR-14 | polish | C2 | Starting a render nudges the review body up 2 px |
| SCR-15 | polish | C1 | The Look panel's Blur readout has no unit |
| SCR-16 | polish | — | "Choose…" buttons carry the folder icon only on the home window |
| INT-6 | minor | A5 | Cancel during matching leaves the transcript in the job folder |
| INT-7 | minor | A1 | Readable phone and camera formats are refused on drop without a word |
| INT-8 | minor | A5 | Unreadable or silent recordings fail late, with technical text |
| INT-9 | minor | A3 | Release builds never prepend the basmala a checkout prepends |
| INT-10 | minor | A3 | CLI range detection answers confidently on non-recitation input |
| INT-11 | minor | A2 | Cancel cannot stop a WhisperX transcription |
| INT-12 | polish | A2 | Download-failure advice loops on checksum errors and names a CLI flag |
| INT-13 | polish | A4 | A lecture with no ayah found opens a reassuring review |
| REV-2 | minor | B3 | Grabbing an edge snaps it to the pointer, by up to 0.19 s |
| REV-3 | minor | B3 | Ripple later is capped by the silence after the last word |
| REV-4 | minor | B5 | The checklist's 25:7 stretch (16.7–24.2 s) is stale; the default engine flags 9.5–13.0 s |
| REV-5 | minor | B4 | A caption fix that adds a word drops its timings and causes false coverage gaps |
| REV-6 | minor | B1 | With no audio output, playback runs silently with no notice |
| REV-7 | minor | B1 | Moved recording: Play stays enabled but does nothing; no relink |
| REV-8 | polish | B6 | A recitation's shortcut sheet lists the lecture-only change-ayah double-click |
| REV-9 | polish | B3 | A failed save names a hidden temporary file |
| OUT-2 | minor | C3 | ASS sidecars never wrap: long cues lose both ends (16 of 34 portrait lecture cues) |
| OUT-3 | minor | C2 | The basmala splice depends on a checkout-only file the app never ships |
| OUT-4 | minor | C3 | Export says "includes the basmala" for videos without one |
| OUT-5 | minor | C5 | The address written under the QR drops a page-selecting query |
| OUT-6 | minor | C5 | The tracked campaign names the surah span, not the video |
| OUT-7 | minor | C4 | A recitation rendered for an episode skips its chosen subtitle files |
| OUT-8 | minor | C3 | Export proposes the global videos folder, not the job's |
| OUT-9 | minor | C1 | An oversized PNG background is decoded in full before it is refused |
| OUT-10 | polish | C1 | A recitation's look warns about caption colours it never draws |
| OUT-11 | polish | C1 | `preview --look` help claims a project's look wins |
| SHL-2 | minor | D4 | Tab cannot leave the review's segment table |
| SHL-3 | minor | D1 | Projects rendered by the CLI list as "Changed since render" |
| SHL-4 | minor | D5 | With two windows on Linux/macOS, one logs into `qalun.log.1` |
| SHL-5 | minor | D6 | pip-installed `qalun --help`, `--version` and `--doctor` open the window (RC-4) |
| SHL-6 | minor | D7 | About's links fail silently; Help's failure gives no address |
| SHL-7 | minor | D1 | Remove from list has no undo in the app; the README's advice is wrong |
| SHL-8 | minor | D2 | An unwritable output folder is accepted; the job fails after transcribing |
| SHL-9 | polish | D6 | The CLI shows a traceback for a folder or an unreadable input |
| SHL-10 | polish | D1 | Doc nits: a chip's name, right-click Open, the checklist's Help target |
| SHL-11 | polish | D4 | The header logo and job thumbnails are soft on HiDPI |
| SHL-12 | polish | D6 | `qalun --cli` usage names a `qurantext` command |
| SHL-13 | polish | D3 | The Arabic unsaved-changes prompt says «ارفض» for Discard |
| REL-7 | minor | — | The last Linux build fell back to BtbN's FFmpeg master snapshot: zip +82 MB |
| REL-8 | minor | — | The release checklist has stale steps beyond RC-1 |
| REL-9 | minor | — | The macOS app reports version 0.0.0; the Windows exe has none |
| REL-10 | minor | — | The guide's and README's download links cannot be counted per source |
| REL-11 | minor | — | The source zip carries a third Quran text (`alFurqan.txt`) the notices do not list |
| REL-12 | minor | D1 | Lecture job cards show cross-surah spans such as 25:44–39:17 |
| REL-13 | polish | — | The notices undercount the Lucide icons (31 said, 41 ship) |
| REL-14 | polish | D1 | The guide's "Changed since the last render" differs from the app's chip |
| QRN-5 | minor | C5 | A lecture intro announces ayat 1–11 for a lesson on 7–11 |
| QRN-6 | polish | C2 | The card header uses Latin digits, its marker Arabic-Indic ones |
| VER-1 | minor | — | Found while verifying this report: `tests/test_entry.py` (`test_report_is_saved_where_it_says`, `test_doctor_returns_a_verdict_and_leaves_a_report`) write `doctor-report.txt` into the real user data folder, because `_save_report` uses `user_data_dir()` and the tests do not redirect it. Running the suite overwrites a developer's real report. |

## 8. Dropped or downgraded in verification

| # | Reported as | After verification | Why |
|---|---|---|---|
| JRN-5 Remove from list has no undo | major | minor | A side path; the files are untouched, and the guide's own sentence about it is accurate (the README's is not, SHL-7) |
| JRN-7 Show in folder opens the project's folder | major | minor | After every render the done banner reveals the video itself |
| SCR-1 ۞ drawn at the wrong end in the English review | major | minor | Only in the English window's table and strip; the text, the video and the picker are right |
| OUT-1 The review preview lays out cards differently from the video | major | minor | The small in-window preview (480×270) hits the renderer's pixel floors and pages long cards differently; at full size the preview equals the frame |
| QRN-4 Lecture captions misquote 25:7 in vowelled text | major | minor | Captions are the recognised speech by design; the same quote reads correctly later in the lecture |
| REL-2 LGPL libquadmath ships unnamed | blocker | known | numpy's bundled LICENSE names it; it belongs in the open licence review (add it there) |
| QRN-1, its U+06D2 half ("Urdu ya") | blocker | not a defect | `qaloon.10` itself draws U+06D2 as «ے», and Noto draws the same; only Amiri stretches it |

## 9. Measurability

The organisation's rule is that every link handed out must be measurable. The state at this
commit:

- **Video links (outro QR and the Copy button): measurable.**
  - Each carries `utm_source=<platform>`, `utm_medium=video`, `utm_campaign=qalun-SSS-AAA-BBB`
    (or the person's own campaign) and `utm_content=outro-qr` or `description`.
  - The QR decodes to exactly that link, even from the joined episode.
  - The counts land in the creator's own site analytics.
  - Two gaps: the campaign names the surah span, so two videos on the same ayat share one
    campaign (OUT-6); and the readable address drops a page-selecting query (OUT-5).
- **App links (Help, About): tracked but not countable.** They carry `utm_source=qalun-app`,
  `utm_medium=app` and the campaign `help` or `about`, and both load. But GitHub reports no
  UTM parameters, so no one can read them back (known owner item).
- **Download links: neither tracked nor countable per source.**
  - The README and the guide link to the plain releases page (REL-10).
  - The checklist's template uses `/releases/latest`, which lands on the releases list while
    every v0.* release is a pre-release, and the redirect drops the query (RC-3).
- **Installs:** GitHub's per-asset download count is the only count today; v0.2.0's three
  zips show 0. The model asset's count also includes CI cache misses.

**Recommendation:** one redirect host under your own domain, with analytics, in front of:

- the release page, using `/releases/tag/vX.Y.Z` (not `/latest`)
- the guide
- the repository

Give each channel its own path or `utm_source`. Then point the app's Help and About, the
README, the guide, the release notes and any QR code at it.

## 10. Owner checklist before tagging

1. **Fix round.** Fix the two blockers (4.1) and, preferably, the nine majors in 4.2. Then run
   section 3's checks again: the test suite, `--doctor --release`, screenshots, the two runs
   and the link check.
2. **Version.** Set `__version__ = "0.3.0"` and commit it. The macOS bundle still says 0.0.0
   (REL-9).
3. **Build the app** in Actions, on the commit you will tag. Check:
   - All three gates are green.
   - The zip sizes are as expected. Watch the FFmpeg source line, because the last Linux build
     fell back to BtbN's master snapshot (REL-7).
   - Each zip's top holds `LICENSE`, the notices, `qalun-source.zip`, `third-party-sources/`,
     and Pillow's licence once REL-1 is fixed.
4. **On a Mac** (Apple silicon, macOS 15+), test the first open:
   - Download the zip in a browser, so it is quarantined.
   - Unzip it and open it through Privacy & Security → Open Anyway.
   - If macOS says "damaged", REL-5 is confirmed.
5. **By ear on Windows, macOS and Linux** (checklist "By ear"). On the default engine the
   uncovered stretch in 25:7 is now about 9.5–13.0 s, not 16.7–24.2 s (REV-4).
6. **Arabic.** Check Arabic on a real desktop, and have a native speaker review the strings
   (checklist "Arabic" and "Words"). Add SCR-10, SCR-11 and SHL-13 to that review.
7. **First-release blockers.** They stay open for this pre-release. But the repository is
   public now, so the Quran font and text are already published while their terms are
   unconfirmed, and so is the stray `alFurqan.txt` in the source zip (REL-11). Add
   libquadmath (REL-2) to the licence review.
8. **Release notes.**
   - Name section 4.3 as known issues.
   - State the system requirements (REL-6).
   - Give the first-open steps for Mac and Windows (REL-4).
   - Keep "Extract with your file manager or `unzip`" for Linux.
9. **Measurability.** Decide the redirect host (section 9) before anything is announced.
10. **The checklist itself.** Bring `docs/release-checklist.md` up to date: the repository is
    public; v0.2.0 exists; Help opens the guide; the 25:7 stretch; and the rest of REL-8.

## 11. Found while planning this check

| # | Finding | Status |
|---|---|---|
| RC-1 | Help and the guide's download link answered 404 while the repository was private | Resolved when the repository was made public on 25 Oct; both load. The checklist still says private (REL-8). |
| RC-2 | The guide says "about 300 MB free" | Open. The Linux app folder is about 490 MB, plus the 110 MB model and the zip itself. |
| RC-3 | `/releases/latest` lands on the list and drops the UTM query while every release is a pre-release | Open (section 9) |
| RC-4 | pip-installed `qalun --help` opens the window | Rated minor (SHL-5); the shipped entry point handles `--help` |

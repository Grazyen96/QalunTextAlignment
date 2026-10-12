# Generated intro and outro — design

Date: 2026-10-12 · Status: approved in conversation, awaiting written-spec review

## 1. Purpose

The episode feature (`docs/superpowers/specs/2026-10-12-episode-design.md`) joins an intro clip,
a recitation, the lecture and an outro clip. Not everyone has intro and outro clips. Just as the
Look feature draws card backgrounds in code, Qalun should **draw the intro and outro itself**, in
the lecture's own look, so a person gets a finished, consistent episode without a video editor.

Success means:

- In the Episode dialog, the person picks **Generated** for the intro and/or the outro, sets a few
  fields once, and the render produces matching clips automatically.
- The generated outro's link is **measurable**. This is an organisation rule: every link or QR code
  in promotional or sales material must be trackable.

Decisions from the brainstorm (the owner's answers):

| Question | Decision |
|---|---|
| Intro content | **Channel / teacher name** + the lecture's **surah and ayat** |
| Outro content | A **closing phrase** + a **link as a QR code with short readable text** |
| Sound | **Silent** |
| Platforms (tracking source) | YouTube, Instagram, Facebook, TikTok, Telegram, WhatsApp — **chosen per export** |
| Animation | **A few presets**: Fade, Rise, Reveal |

Out of scope: sound or music, a logo image, a date, a "next lecture" teaser, more than one link,
and generated clips for anything other than the episode's intro and outro.

## 2. What the person sees

### 2.1 The Episode dialog

The Intro and Outro rows each become a choice: **None · My clip · Generated**. *My clip* behaves
as it does today.

**Generated intro** shows:

- **Name**: free text, e.g. «دروس الشيخ …» or "Dars of Sheikh …". It is remembered.
- **Title line**: read-only. It is filled from the lecture: the surah name and ayat range of its
  on-screen cards (studied surah, hand-made cards included), e.g. «سورة الفرقان، الآيات ٤٤–٤٩». The separator is the Arabic comma «،»: Amiri draws a
  middle dot «·» between Arabic words like an Arabic zero «٠».
  When nothing is known, it is the surah name alone, or the line is left out.
- **Style**: Fade, Rise or Reveal.
- **Length**: 3–10 s, default 5.
- A **still preview**: the clip's middle frame, at a small size.

**Generated outro** shows:

- **Closing phrase**: a combobox with
  - «جزاكم الله خيرًا»
  - «بارك الله فيكم»
  - «سبحانك اللهم وبحمدك، أشهد أن لا إله إلا أنت، أستغفرك وأتوب إليك»
  - *Custom…*, which opens a text field.

  The phrase is remembered.
- **Link**: a URL field, remembered. Only `http` and `https` are accepted; a missing scheme becomes
  `https://`. Leaving it empty means no QR code and no address. The link must have a real host
  name (or a valid IDN, or an IP address) with an optional valid port, and no user name or
  password, spaces or invisible characters; mistyped schemes (`https:/x`, `https//x`, `https:x`)
  are refused. `normalise_link` raises `LinkError` with a `code` the dialog words (empty, spaces,
  scheme, slashes, userinfo, host, port).
- **Publishing on**: YouTube, Instagram, Facebook, TikTok, Telegram or WhatsApp. It is remembered
  as the last one used and shown, editable, each time the dialog opens, because it can change per
  export (no separate confirmation on OK).
- **Tracked link**: read-only, showing the full URL inside the QR code, with a **Copy** button for
  the video description. Copy gives the same link with `utm_content=description` instead of
  `outro-qr`, so description clicks and QR scans are counted apart (§3).
- **Style** (default Fade), **Length** (3–10 s, default 6), and a still preview.

**Defaults:** generated settings follow the same "only what you changed" rule as clips, **field
by field**: the name, phrase, link, platform, style and length are each saved as the default only
when that field was changed in the dialog; a field left alone keeps the default's value, not the
open lecture's. The kind is saved only when it was changed. New lectures start with the default
intro and outro *kind*, so a person who chose Generated keeps getting it. The generated settings
are remembered apart from the kind: choosing None or My clip keeps them for when the part is
Generated again.

**Refused and warned:** OK is disabled for a refused link and for a generated part with nothing to
show (no name and no surah for the intro; no phrase and no link for the outro). Warnings, which
leave OK enabled: a link too long for a QR code at the size the next render makes (the job's
preset), characters the title font cannot draw (name, phrase and written address), and an
address that could pass for another (`lookalike_host`: alphabets mixed in one name, or a name
wholly in Latin-looking Cyrillic or Greek letters).

### 2.2 Output

When rendering an episode with a generated part, the clip is made just before joining. Progress
reads "Making the intro…" / "Making the outro…".

The clip lives in the project's episode folder as `generated-intro-<hash12>.mp4` /
`generated-outro-<hash12>.mp4`. Its hash covers every input: text, style, length, look, geometry,
fps, tracked URL and the generator's version. When nothing changed, the clip is reused, not redrawn.

## 3. The tracked link (organisation rule)

`tracked_link(url, *, platform, campaign, content="outro-qr") -> str`:

- It parses the URL and **keeps every existing query parameter and the fragment**.
- It sets:
  - `utm_source=<platform>` (`youtube`, `instagram`, `facebook`, `tiktok`, `telegram`, `whatsapp`);
  - `utm_medium=video`;
  - `utm_content=<content>`: `outro-qr` for the link the QR code opens, `description` for the
    same link copied into the video's description, so scans and description clicks are measured
    apart.

  These three always overwrite.
- It sets `utm_campaign=<campaign>` **only when the link has none**, so a campaign the person set
  themselves wins.
- The automatic campaign is `qalun-<surah:03d>-<from:03d>-<to:03d>`, e.g. `qalun-025-044-049`.
  With no ayat it is `qalun-<surah:03d>`; with no surah it is `qalun-lecture`.

The **readable text** under the QR code is `host + path`, without scheme, query, fragment, user
name or a trailing `/`, e.g. `example.org/dars`. It is decoded for people (display only): an IDN
host in its own script, a percent-encoded path as its words («example.org/دروس»). Visits typed from it show as direct traffic, apart
from the QR code's (`outro-qr`) and the description's (`description`) visits.

The person can see the tracked link (§2.1) and copy its description form. The campaign is read
from the lecture's cards when the dialog opens and again when the clip is made, so the link is
best copied once the cards are final. The QR code
encodes exactly that tracked link, in ASCII: an IDN host in punycode (IDNA 2008 with UTS #46 non-transitional mapping, as browsers do:
«straße.de» is `xn--strae-oqa.de`, not `strasse.de`), a non-ASCII path or fragment
percent-encoded. Existing query pieces are kept exactly as written (their encoding, a bare
`flag`, a `;`); an empty `utm_campaign` counts as none.

## 4. Architecture

### 4.1 `core/title_cards.py` (new; no Qt)

`IntroSpec(name: str, title: str, style: str, seconds: float)` and
`OutroSpec(phrase: str, link_text: str | None, qr_url: str | None, style: str, seconds: float)`
are frozen dataclasses with a stable `cache_key()`.

`render_title_frame(spec, look, width, height, t, *, fonts) -> PIL.Image (RGB)` draws one frame at
time *t*:

- **Background:** `backgrounds.base_layer(look, w, h, card_box, radius)`, the look's background
  plus card. The card box is a centred title panel, about 70 % × 40 % of the frame.
- **Text:**
  - with the **text font** (§4.3); the basmala ligature ﷽ (U+FDFD), which Amiri cannot
    rasterise, is drawn spelled out as «بسم الله الرحمن الرحيم»; a font failure is a
    `TitleTextError` (a `ValueError`) naming the text, never a crash;
  - right to left with raqm, the Arabic text shaped;
  - Latin text such as an English name laid out left to right, each text's direction taken from
    its first strong letter; the link text always left to right, whatever its script;
  - mixed text isolated.
- **Colours:** the name uses `look.header_text`, the title line `look.body_text`, the phrase
  `look.body_text` and the link text `look.placeholder_text`.
- **Sizes:** the name starts at 9 % of the frame height and the title line at 0.7 × the name's
  fitted size, so the title reads as the smaller line.
- **QR code** (outro only):
  - drawn from segno's module matrix with Pillow;
  - error correction "M", quiet zone of 4 modules;
  - dark modules on a light square: of `look.body_text` and `look.card` (at full opacity), the
    darker draws the modules and the lighter the square. On a dark look that is card-coloured
    modules on a body-text square: an inverted code (light on dark) is one many phone scanners,
    and OpenCV, cannot read;
  - if contrast is below 4.5:1, the code uses black on white instead;
  - each module is a whole number of pixels, `max(5, ceil(0.25 · short side / (modules + 8)))`,
    so the code with its quiet zone is at least 25 % of the frame's shorter side. At 4 px a code
    stops decoding once a platform scales the video to 480p or 360p. A clip refuses a size where
    such a code cannot fit in the panel (`qr_fits`); a small preview may draw smaller modules;
  - it sits beside or above the phrase, depending on whether the frame is landscape or portrait.
- **Animation:** `progress = t / seconds`.
  - **Fade:** everything fades in over the first 0.6 s and out over the last 0.6 s, alpha-blended
    over the background.
  - **Rise:** the text slides up 6 % of the height while fading in, and the end fades.
  - **Reveal:** the background pattern draws in over the first 40 %, from the edge the clip's
    own text starts at: right to left for Arabic, left to right for a Latin name or phrase (the
    intro's name, else its title, which is always Arabic; the outro's phrase). This is the spec's
    `rtl` field, so it is in the cache key and a preview matches its clip. It does not follow the
    window's language: the clip is read by the video's viewers, and switching the window to
    English must not remake the same Arabic clip mirrored. Then the text fades in. The QR code never animates: it is fully drawn from
    14 % to 86 % of the outro, which is at least 70 % of its frames, so a viewer can scan it.

`render_title_clip(spec, look, output, *, width, height, fps, progress, cancel) -> Path` streams
frames to FFmpeg:

- raw RGB in; libx264, crf 18, yuv420p; no audio track. The episode join already adds silence for
  parts without audio;
- written to a `.part` file and then renamed;
- cancel kills FFmpeg, the same way the episode join does.

### 4.2 `jobs/generated_parts.py` (new)

- `title_for(project, surah_names)` builds the title from the project's on-screen cards
  (`cards_on_screen`) and the studied surah, through `video_common.lecture_span`, the same rule
  the lecture's own opening card uses: the chosen studied surah, else the automatic guess (hand-made
  cards do not vote). The intro, its link's campaign and the opening card name the same surah. The
  surah name is the store's, written in plain letters (`core.arabic.plain_surah_name`: marks that
  form letters are joined, a final «يٰ» is «ى», the other marks go).
- `intro_spec_for(project, settings, surah_names) -> IntroSpec` and
  `outro_spec_for(project, settings, surah_names) -> OutroSpec`; the outro uses `tracked_link` (§3).
- `ensure_generated_part(project, kind, spec, look, *, width, height, fps, progress, cancel) -> Path`
  returns the reused or newly made clip in the episode folder. Its name covers the spec, what the
  clip draws of the look (a background photo by its content, not its path), the size and the rate.

### 4.3 Text font

The bundled Quran font has no Latin glyphs. Qalun therefore bundles **Amiri** (Regular and Bold),
which covers Arabic and Latin, under the SIL Open Font License 1.1.

- The files go in `assets/fonts/`, each pinned by sha256 from the upstream release.
- Licence text and attribution go in `THIRD_PARTY_NOTICES.md` and `packaging/licenses/`.
- `packaging/qalun.spec` already bundles the whole `assets/` folder; a packaging test checks the
  font is there.

### 4.4 QR code library

**segno** is a pure-Python QR encoder under the BSD-3-Clause licence, compatible with GPL-3.0.

- It is added to `pyproject.toml` with an exact pin.
- Its notice goes in `THIRD_PARTY_NOTICES.md` / `packaging/licenses/` and the packaging
  dependency checks.
- Only its module matrix is used. Drawing stays in Pillow, so the look's colours apply.

### 4.5 Project data and the render flow

`project.episode` gains `intro_generated` / `outro_generated`, a dict of the settings. When it is
present it takes the place of a clip path for that part, and the dialog's kind decides which
applies. Loading tolerates bad values; the content-hash rule is unchanged, since it hashes
`episode` when non-empty.

`Prefs.default_episode` gains the generated settings and kinds, following the "only what changed"
semantics.

In `run_render`'s episode step, a generated part calls `ensure_generated_part` at the lecture
render's geometry before `assemble_episode`. A failure becomes `episode_error`, translated, and the
lecture is kept. This is the same rule as for clips.

## 5. Failure handling

| Situation | Behaviour |
|---|---|
| Link not http/https, or unparsable | The dialog refuses it with a message; OK is disabled while it is invalid |
| Link too long for a QR code at level M, or for the lecture's frame at 5 px modules | The dialog says so, using `qr_fits` with the lecture's size (a fixed character count is wrong. Measured with 5 px modules, the longest tracked link that fits is 412 characters at 960×540, 779 at 1280×720, 1,911 at 1920×1080 and 2,213 at 1080×1920) |
| A character the title font cannot draw (Cyrillic, emoji) | The dialog warns, using `missing_glyphs` |
| No ayat known for the title | The title shows the surah name, or is left out |
| Text too long for the panel | Font size shrinks (the renderer's `fit_font_size`); wraps to at most 2 lines, the last cut with «…» if it still does not fit |
| Generation fails or is cancelled | `episode_error`; the lecture is kept |
| A light look where QR contrast is low | Black on white is used instead |

## 6. Testing

- **`tracked_link`:**
  - a plain URL;
  - existing query and fragment are kept;
  - an existing `utm_campaign` wins;
  - existing source, medium and content are overwritten;
  - every platform value;
  - the readable text;
  - a refused scheme.
- **QR:** render an outro frame, then decode it with OpenCV's `QRCodeDetector`; it must equal the
  tracked link exactly. Test at 1080×1920 and 1920×1080, with dark and light looks. Skip if OpenCV
  is absent.
- **Frames:**
  - every style at t = 0, the middle and the end;
  - the text and QR code are drawn by the visible frames;
  - the QR code is fully visible over ≥ 70 % of the outro;
  - Arabic shaping: no isolated forms in a known word;
  - a Latin name draws glyphs, not tofu boxes.
- **Clip:** length within ±1 frame, size, fps, and no audio stream. Reused when inputs are equal,
  redrawn when any input changes (the look, the ayat or the platform).
- **Episode:** a render with a generated intro and outro joins them; the episode's length is the
  sum; a generation failure keeps the lecture.
- **Dialog:**
  - the kinds;
  - fields are remembered only when changed;
  - the tracked-link display and Copy;
  - an invalid link disables OK;
  - the previews.
- **Packaging:** the font and segno notices are present, and the font is in the bundle.

## 7. Delivery

One branch, `feat/generated-parts`, in three phases:

1. tracked links, QR codes, the font, and `title_cards` frames and clip;
2. project data, prefs and the render flow;
3. the Episode dialog.

Each phase gets one review and a local merge after the owner agrees.

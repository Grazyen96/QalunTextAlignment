# Qalun Recitation & Tafseer Video Tool — System Architecture

> **Purpose of this document.** This is the target architecture. Use it to audit the current project and bring it into line. Where the existing code diverges, prefer this design unless there's a concrete reason recorded otherwise.
>
> **Locked decisions (do not re-litigate):**
> 1. **Single reciter voice** — recitation is a pre-aligned lookup; no runtime ML for recitation.
> 2. **Two outputs, every job:** an editable Premiere project (`.prproj`) **and** a rendered `.mp4`.
> 3. **The MP4 is produced by exporting the generated project via Adobe Media Encoder** — not a separate compositor. One render engine, guaranteed parity.
> 4. **Desktop deployment** on the creator's machine, with Premiere installed.
> 5. **Fully on-device / offline** after a one-time data download. No cloud processing.
> 6. **Sidecar pattern is mandatory:** a native local companion process does the ML/processing; the UXP panel does UI + project assembly + export. UXP's JS engine cannot run ML.
> 7. **ASR = whisper.cpp** (native binary), not faster-whisper, to avoid bundling a Python runtime.
> 8. **Own-voice recitation is out of scope** (it would require on-device forced alignment). Single voice only for now.

## 1. Guiding principles

1. **Two different problems, one shared spine.** The recitation video is a *forced-alignment* problem (the text is known). The tafseer video is an *ASR + retrieval* problem (the speech is unknown). They share only the data layer and the output layer.
2. **The "database" is a pre-computed cache, not a competing design.** With a single accepted reciter voice, the recitation half becomes a lookup against pre-aligned data built once.
3. **Two outputs from one render.** The UXP plugin builds the editable `.prproj` from a neutral edit-spec JSON, then triggers Adobe Media Encoder to export the `.mp4`. The rendered video is the project's own export, so the two artifacts are always identical — no separate compositor, no parity drift.
4. **Sacred text is locked content with editable styling; subtitles are editable text.** Quran characters are never editable; their position/color/timing are. ASR subtitles are fully editable.
5. **Religious correctness is a release gate, not a feature.** A wrong harakah or madd blocks shipping.

---

## 2. High-level system map (on-device, desktop)

Everything below runs on the creator's machine. After a one-time data download it works fully offline. Two processes — the **UXP panel** (inside Premiere) and the **native sidecar** — talk over localhost.

```
 CREATOR'S MACHINE — offline after first-run download
 ════════════════════════════════════════════════════════════════════════

 ┌─────────────────────────── LOCAL DATA STORE ──────────────────────────┐
 │ downloaded once as component packs, then read-only                    │
 │  • Qalun certified text + metadata (Madani counting)                  │
 │  • Single-sheikh Qalun recitation audio (per-ayah)                    │
 │  • Word-level alignment timestamps          ← the jewel               │
 │  • Pre-shaped text assets (SVG/PNG, normal + highlight)               │
 │  • Citation index (normalized)                                        │
 │  • whisper.cpp model file (ASR pack — only if tafseer used)           │
 │  • MOGRT templates (.mogrt)                                           │
 └──────────────────────────────────┬────────────────────────────────────┘
                                     │ reads
 ┌───────────────────────────────────▼───────────────────────────────────┐
 │ NATIVE SIDECAR  (local service, no cloud)                              │
 │  ┌─ RECITATION BUILDER ────────┐   ┌─ TAFSEER BUILDER ───────────────┐ │
 │  │ in: surah + from/to ayah     │   │ in: dars audio/video + surah    │ │
 │  │ • slice audio   • timestamps │   │ • whisper.cpp ASR → transcript  │ │
 │  │ • shaped assets • highlight kf│   │ • subtitle cues                 │ │
 │  │ NO ML — pure lookup, instant │   │ • citation detector (local idx) │ │
 │  └──────────────┬───────────────┘   └───────────────┬─────────────────┘ │
 │                 └───────────────┬───────────────────┘                   │
 │                   emits EDIT-SPEC JSON + stages local asset files       │
 └──────────────────────────────────┬─────────────────────────────────────┘
                                     │ localhost (HTTP/IPC)
 ┌───────────────────────────────────▼───────────────────────────────────┐
 │ UXP PANEL  (inside Premiere Pro)                                       │
 │  • UI: pick range / drop dars / pick studied surah                    │
 │  • reads edit-spec → imports media                                    │
 │  • caption track (editable subtitles)                                 │
 │  • MOGRTs for ayah overlays + word highlight (locked text)            │
 │  • applies transforms / colors / keyframes → saves  project.prproj    │
 │  • triggers Adobe Media Encoder export        →     video.mp4         │
 └────────────────────────────────────────────────────────────────────────┘

 OUTPUT (every job):   project.prproj  (editable)   +   video.mp4  (rendered)
```

The **edit-spec JSON** remains the contract between the sidecar and the panel. It is kept format-neutral so a different generator (e.g. DaVinci Resolve) could consume it later, but Premiere + AME is the only target in scope now.

---

## 3. The static data layer ("database") — what's in it

| # | Component | Contents | Purpose |
|---|-----------|----------|---------|
| A | **Canonical text** | Qalun (riwāyah of Qālūn ʿan Nāfiʿ) certified text, per surah/ayah/word, with stable IDs `surah:ayah:word` | Ground truth for everything |
| B | **Metadata** | Surah info (name, Makki/Madani, count, mushaf pages), ayah info (juz, hizb, sajda, page, **Madani ayah numbering**) | Indexing, display, resolving references |
| C | **Phonetic/alignment text** | Per-ayah representation tuned for the aligner (phoneme or normalized grapheme form, accounting for madd/tajwīd) | Forced alignment input |
| D | **Font + pre-shaped assets** | Certified Qalun font; per-word and per-ayah pre-shaped **SVG (preferred) / PNG-with-alpha**, in normal + highlighted states | Correct, locked Arabic rendering |
| E | **Recitation audio** | One sheikh, full Quran, **Qalun**, normalized; per-ayah files (or continuous + markers) | Recitation video source |
| F | **Alignment timestamps** | `surah:ayah:word → {start_ms, end_ms, confidence}` for the entire Quran | Word-by-word highlight timing |
| G | **Citation index** | Every ayah in **normalized** form (no diacritics, unified alef/hamza/ya/ta-marbuta, no tatweel) + n-gram/phrase index → `surah:ayah` | Detect quoted ayat in the dars |
| H | **Reference resolver** | Surah name variants and how teachers say them ("في سورة البقرة"), counting edge cases | Map spoken references to IDs |
| I | **MOGRT templates** | Premiere/AE motion-graphics templates: subtitle, ayah-display, word-highlight | Editable on-screen graphics |

> **Critical correctness notes**
> - Use a **certified Qalun text** (e.g. KFGQPC Qalun mushaf). Do **not** transform a Hafs text into Qalun — the character sequence and diacritics genuinely differ; it is *not* a font swap.
> - **Ayah numbering differs by counting system.** Qalun uses Madani counting, which diverges from the Kufi counting common in Hafs datasets (basmala counting, verse boundaries). Pick one counting (Madani) and enforce it everywhere, or every cross-reference will be off by a verse in places.

---

## 4. Database creation pipeline (build once, then version)

```
1. ACQUIRE TEXT      → license certified Qalun text; checksum vs source
2. STRUCTURE         → parse into surah/ayah/word records; assign IDs; load metadata
3. ACQUIRE AUDIO     → license single-sheikh Qalun recitation
4. NORMALIZE AUDIO   → resample, loudness-normalize, silence-trim, split per ayah
5. BUILD PHONETICS   → per-ayah alignment representation
6. FORCE-ALIGN       → run aligner over full recitation → word timestamps + confidence
7. ALIGNMENT QA      → review tool, fix low-confidence words, human correction pass
8. SHAPE TEXT        → HarfBuzz shape every word/ayah → SVG/PNG (normal + highlight)
9. BUILD CITATION IX → normalization pipeline + n-gram/phrase index over all ayat
10. BUILD METADATA   → juz/hizb/page/sajda/surah tables, reference-resolver dictionary
11. RELIGIOUS QA     → qualified reviewer (qāriʾ/mujāz) verifies text + sampled alignment
12. PACKAGE & VERSION→ lock a versioned, immutable DB release; define update process
```

**Notes per step**

- **Step 5–6 (alignment) is the real work.** Generic aligners (Montreal Forced Aligner, WhisperX/CTC) are trained on conversational speech; tajwīd elongations (madd), ghunnah, and tartīl pacing break naive duration models. Prototype on one sheikh early — this is your biggest technical risk. Store a **confidence score** per word so QA can target weak spots.
- **Step 7 (alignment QA)** needs a small internal tool: play the ayah, show the highlight running against the waveform, let a reviewer nudge boundaries. Word-level Qalun timing barely exists publicly, so plan for a real human pass.
- **Step 8 (shaping)** is done with HarfBuzz (e.g. `uharfbuzz` in Python, or a Node service) so Arabic joining + diacritic positioning are correct. Prefer **SVG** so assets scale cleanly at any resolution. Output the highlight state as either a second asset or a separate overlay layer.
- **Step 11 (religious QA)** is a hard gate. Version and lock only after sign-off.

---

## 5. Storage — build-time vs on-device runtime

There are two storage contexts. Don't conflate them.

**Build-time (your authoring environment, where the DB is produced):**
- **Relational (Postgres):** text, words, metadata, alignment timestamps during authoring/QA.
- **Object storage (S3-compatible):** audio + pre-shaped assets during authoring.
- This side never ships; it's where you build and version the data.

**On-device runtime (what ships to the creator's machine):**
- **Embedded DB (SQLite):** text, metadata, alignment timestamps, citation index — single-file, zero-config, offline.
- **Flat files on disk:** recitation audio (per-ayah), pre-shaped SVG/PNG assets, MOGRTs, whisper.cpp model. The sidecar stages the specific files a job needs into a local working folder so Premiere can import them.
- Everything keyed by the same `surah:ayah:word` IDs so layers join cleanly.
- The runtime store is **read-only and versioned**; updates arrive as new component packs (see §13).

---

## 6. Recitation builder (runtime, lightweight)

```
input:  surah, from_ayah, to_ayah, style_options
─────────────────────────────────────────────────
1. fetch audio for range (concat per-ayah files OR slice continuous)
2. fetch word timestamps for range; rebase to segment-relative time
3. fetch pre-shaped word/ayah assets
4. build highlight keyframes  (word_in → word_out per word)
5. emit edit-spec JSON
```

Because alignment is pre-computed, this is near-instant. No ML at runtime.

---

## 7. Tafseer builder (runtime, the heavier path)

```
input:  dars audio/video, studied_surah
─────────────────────────────────────────────────
1. ASR (Arabic, Whisper-class) → transcript + word/segment timestamps
2. subtitle cue builder → split into readable lines with timing
3. citation detection:
     • slide a window over the transcript
     • normalize the window (same normalization as the index)
     • fuzzy-match against citation index → candidate ayat + span + score
     • threshold; resolve surah:ayah
     • label SAME-surah vs CROSS-reference using studied_surah
4. for each citation:
     • pull canonical ayah text + pre-shaped asset (locked, certified)
     • compute on-screen window (start ~0.5s before quote; sensible duration)
5. emit edit-spec JSON (video track + subtitle cues + ayah-overlay cues)
```

**Hard parts to budget for**

- **ASR dialect.** Dars speech mixes MSA, dialect (Egyptian/Maghrebi/Gulf), and classical quotation. Whisper large handles MSA decently; dialect is weaker. Subtitles are undiacritized — that's normal and fine.
- **Quote vs paraphrase.** A teacher often half-quotes or paraphrases. Tune the match threshold and prefer detecting *partial* ayat (phrase index) over requiring full-verse matches. Always display the **canonical** ayah text, never the ASR's version of it.
- **Subtitles always need human correction**, so they ship as editable captions, not baked text.

---

## 8. The edit-spec (the contract everything hangs off)

A neutral JSON your backend emits and each generator consumes. Sketch:

```jsonc
{
  "project": { "fps": 25, "width": 1920, "height": 1080 },
  "media": [
    { "id": "aud1", "type": "audio", "path": "…/recitation_segment.wav" },
    { "id": "vid1", "type": "video", "path": "…/dars.mp4" }
  ],
  "tracks": [
    {
      "kind": "video",
      "clips": [ { "media": "vid1", "in": 0, "out": 1800.0 } ]
    },
    {
      "kind": "captions",          // editable subtitle track (tafseer)
      "cues": [
        { "in": 12.30, "out": 15.10, "text": "ASR line, editable" }
      ]
    },
    {
      "kind": "graphics",
      "items": [
        {
          "type": "ayah_overlay",   // locked content, editable style
          "mogrt": "ayah_display_v1",
          "asset": "shaped/002_255.svg",
          "ref": "2:255",
          "relation": "cross_reference",
          "in": 30.0, "out": 38.0,
          "transform": { "x": 960, "y": 880, "scale": 1.0 },
          "color": "#FFFFFF"
        },
        {
          "type": "word_highlight", // recitation
          "mogrt": "highlight_v1",
          "ayah_asset": "shaped/108_001.svg",
          "keyframes": [ { "word": "1:1:1", "in": 0.00, "out": 0.62 } ]
        }
      ]
    }
  ]
}
```

Keeping this format-neutral is what lets you target Premiere now and Resolve/web later without touching the backend.

---

## 9. Output / Adobe generation layer

**Why scripting, not export formats:** interchange files (OTIO, FCP7 XML, AAF) carry only cut/clip information, not your editable text, graphics, and colors. OTIO in Premiere is also still beta-only and cutlist-only. So the editable project must be **built through Premiere's scripting.**

**Target UXP, not ExtendScript.** Premiere moved to UXP (added in 25.6, enabled via Preferences → Plugins → developer mode). ExtendScript is being sunset (supported only through Sept 2026), so a new tool should not be built on it.

**What the UXP plugin does:**
```
read edit-spec JSON
 → import media
 → create sequence at project settings
 → place audio/video clips
 → create caption track from subtitle cues          (editable text)
 → instantiate MOGRTs for ayah overlays + highlight  (editable style, locked text)
 → apply highlight keyframes
 → set transforms/colors from spec
 → save project.prproj                               ← editable output
 → trigger Adobe Media Encoder export → video.mp4    ← rendered output
```

- **Subtitles → caption track** (fully editable text — needed for ASR correction).
- **Quran text → MOGRT fed by pre-shaped SVG/PNG** (move/recolor/retime yes; retype no).
- **MOGRTs authored once** in After Effects/Essential Graphics; they expose the editable knobs.
- **Both outputs come from the same project**, so the rendered MP4 always matches the editable project exactly. The MP4 is the un-edited baseline; the project is the creator's starting point for changes (and their own re-export becomes their final).
- Verify the current UXP API for the export/encoder trigger; if a given UXP build can't invoke AME directly, fall back to an AME watch-folder the panel drops the sequence into.

**Future-only note — DaVinci Resolve.** Because the edit-spec is format-neutral, a Resolve Python generator could consume the same spec later. Out of scope now; Premiere + AME is the only target.

---

## 10. Tech stack

| Layer | Build-time (authoring the DB) | On-device runtime (ships to creator) |
|-------|-------------------------------|--------------------------------------|
| ASR | — | **whisper.cpp** (native binary; CPU / Metal / CUDA) |
| Forced alignment | MFA or CTC/WhisperX + custom QA tool (run **once** per reciter) | none (pre-aligned; lookup only) |
| Citation matching | build normalized index | local match against SQLite/embedded index |
| Text shaping | HarfBuzz (`uharfbuzz`) → SVG/PNG | none (assets pre-shaped at build time) |
| Data store | Postgres + S3 | **SQLite + flat files**, read-only, versioned |
| Sidecar service | — | native local process (Rust/Go/C++ or a packaged binary) exposing localhost IPC/HTTP |
| Adobe integration | — | **UXP panel** (TypeScript) inside Premiere; triggers AME export |

> The sidecar wraps whisper.cpp and the lookup/citation logic and emits the edit-spec. Prefer a compiled native sidecar over a bundled Python interpreter to keep the install lean and code-signable.

---

## 11. Cross-cutting concerns

- **Licensing & redistribution.** On-device means you ship copies of the recitation audio and Qalun font to every machine — that's *distribution*, not just playback. Confirm rights cover redistribution.
- **Religious QA & certification:** text correctness + sampled alignment signed off by a qualified reviewer; gate every DB version on it.
- **Versioning:** the runtime store is immutable per release; corrections ship as new component packs.
- **Confidence + human-in-the-loop:** store alignment/citation confidence; surface low-confidence items for review rather than shipping silently.
- **Arabic shaping correctness:** never rely on Adobe's text engine for Uthmani/Qalun glyphs; use pre-shaped assets.
- **Counting consistency:** enforce Madani ayah numbering end to end.
- **Hardware variance (on-device cost):** transcription speed depends on the creator's machine. A 1-hour dars with whisper.cpp `large-v3` can run ~real-time or slower on CPU, faster on Apple-Silicon/Metal. Mitigate with model-size tiers (`medium` vs `large-v3`), Metal/CUDA acceleration, and a visible progress indicator. Recitation has no such cost — it's instant.
- **Sidecar lifecycle:** the panel must start/health-check/recover the sidecar and handle it not running.

---

## 12. Suggested build order

1. **Static data layer** (text + segmentation + font + shaped assets + citation index) → packaged as the on-device SQLite store + asset files.
2. **Forced-alignment engine + QA tool** on one sheikh → produces the timestamp jewel (build-time only).
3. **Edit-spec schema** (freeze it early — it's the contract between sidecar and panel).
4. **Sidecar skeleton** (localhost service) + **recitation builder** (pure lookup) → emits edit-spec.
5. **UXP panel**: consume edit-spec → assemble `.prproj` → trigger AME → `.mp4`. First end-to-end output.
6. **MOGRT styles** refined (subtitle / ayah-display / highlight).
7. **Tafseer builder**: whisper.cpp ASR → subtitles; citation detector → overlays.
8. **Packaging & first-run downloader** (component packs, model tiers, signing).

---

## 13. Deployment & packaging (on-device)

- **Two installable pieces:** (a) the **UXP plugin** (packaged and distributed for Premiere), and (b) a **native installer** for the sidecar + first-run downloader. They communicate over localhost.
- **First-run downloads as component packs**, so users pull only what they need:
  - `core` — Qalun text, metadata, citation index, MOGRTs (small, always required).
  - `recitation` — recitation audio + alignment timestamps + shaped assets (large; required for recitation videos).
  - `asr-medium` / `asr-large` — whisper.cpp model tier (only if the creator uses tafseer).
- **Offline after download.** No network needed at runtime; updates are checked on launch and delivered as new packs.
- **Signing/notarization** required for the native sidecar (macOS notarization, Windows code-signing).
- **Cross-platform:** whisper.cpp covers CPU / Apple-Silicon-Metal / CUDA; pick the right build per platform at install.

---

## 14. Component breakdown — for auditing/modifying the existing project

Map the current codebase onto these components. Each should exist (or be created) with the stated responsibility and boundary.

| Component | Responsibility | Must NOT do |
|-----------|----------------|-------------|
| **Data-build pipeline** (offline) | Produce the versioned SQLite store + asset files from certified sources; run alignment once; shape text; build citation index | Ship Postgres/S3 to the device |
| **Runtime data store** | Read-only SQLite + flat asset files on device, keyed by `surah:ayah:word` | Be writable at runtime |
| **Sidecar service** | Host whisper.cpp; run recitation lookup + tafseer ASR + citation detection; stage job assets; emit edit-spec over localhost | Touch Premiere directly; require cloud |
| **Recitation builder** (in sidecar) | surah+range → audio slice + timestamps + assets + highlight keyframes → edit-spec | Run any ML |
| **Tafseer builder** (in sidecar) | dars + studied-surah → ASR → subtitle cues + detected-ayah overlays → edit-spec | Display ASR text for the ayah (always use canonical) |
| **Edit-spec schema** | The frozen JSON contract; versioned | Carry Adobe-specific assumptions |
| **UXP panel** | UI; consume edit-spec; build sequence (captions + MOGRTs + keyframes); save `.prproj`; trigger AME → `.mp4`; manage sidecar lifecycle | Run ML; mutate the data store |
| **MOGRT templates** | Editable on-screen graphics (subtitle / ayah / highlight) with exposed knobs | Hold the only copy of Quran text (text comes from shaped assets) |
| **First-run downloader / updater** | Fetch component packs; verify; place locally; check updates on launch | Be required at runtime once packs are present |

**Audit red flags to look for in the current project**
- Any cloud/API call on the tafseer or recitation path → must be local.
- ASR or shaping attempted inside UXP/JS → move to the sidecar / data-build.
- A separate MP4 compositor (FFmpeg/Remotion) → remove; MP4 now comes from AME export.
- Hafs text or Kufi/standard ayah numbering anywhere → must be Qalun text + Madani counting.
- Quran text rendered as live editable text in Premiere → must be pre-shaped, locked assets.
- faster-whisper / bundled Python for ASR → switch to whisper.cpp native.
- Writable runtime data store → must be read-only + versioned.

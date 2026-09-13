# Qalun Edit-Spec Builder — Premiere Pro UXP panel

Consumes the `ExportPackage_<basename>/edit_spec.json` written by the Python
backend (`qurantext export-editspec`, or `generate-video --edit-spec`) and
builds the *editable* Premiere project that matches the rendered MP4
(architecture §8/§9). Targets **UXP, not ExtendScript** — ExtendScript is
supported only through Sept 2026.

## Status

The pipeline shape is complete (load spec → import media → sequence →
audio/overlays/captions/markers → save → AME export). All API signatures now
follow the published **Premiere 25.6** reference, which is the *minimum* version
supporting UXP at all and the version we target. It has not yet been driven
against a live Premiere install — the first run is a test, not a demo.

## Install / run

1. **Premiere Pro 25.6+** with developer mode on: Settings → Plugins →
   "Enable developer mode" → **restart Premiere**.
2. Install the [UXP Developer Tool](https://developer.adobe.com/premiere-pro/uxp/)
   (v2.2.1+) → "Add Plugin" → select this folder's `manifest.json` → **Load**.
3. In Premiere: **open a project first** (button 2 needs one), then open the panel
   from **Window → UXP Plugins → Qalun Edit-Spec** (*not* Window → Extensions —
   that's legacy CEP and the panel will never show up there).
4. Buttons 1 → 4 in order.
5. Debugging: UDT → Actions → **Debug** opens Chrome DevTools against the panel.
   A load-time error leaves the panel's own log pane empty, so DevTools is the
   only way to see it.

## What each stage does

| Stage | API used | Notes |
|---|---|---|
| Load spec | `uxp.storage.localFileSystem` file picker; paths resolved relative to the package | separator rewritten for Windows |
| Import media | `project.importFiles(paths, true, rootItem, false)` | |
| Create sequence | `project.createSequenceFromMedia(name, [ref], rootItem)` — conforms the sequence to the render's exact width/height/fps without a preset file; falls back to `createSequence(name)` + a loud warning | |
| Place audio | `SequenceEditor.createOverwriteItemAction(item, TickTime.createWithSeconds(0), 0, 0)` inside `lockedAccess`/`executeTransaction` | the reference MP4 carries its own AAC track; this overwrites it, so A1 ends up holding the package `.m4a` |
| Ayah overlays | `insertMogrtFromPath` when `mogrts/<name>.mogrt` exists in the package; otherwise the interim transparent PNG is overwritten onto **V2** at the spec's `in` time | |
| Trim overlays | `videoClipTrackItem.createSetEndAction(TickTime)` — stills are trimmed to the spec's card window instead of keeping Premiere's ~5 s default still duration | falls back to a warning + manual trim |
| Word-highlight keyframes | staged, **not applied** — the `highlight_v1` MOGRT that exposes a keyable param is not authored yet | **blocked on MOGRT** |
| Captions | **UXP has no caption-writing API in any shipped version** (`getCaptionTrack*` is read-only). The panel imports the package SRT (UTF-8 BOM) and asks for one manual drag onto the timeline — after which the captions are fully editable | fallback by design |
| Ayah markers | `Markers.createAddMarkerAction(ref, "Comment", in, dur, text)`, one per caption cue `ref` — jump between ayat from the Markers panel | `markerType` is a plain string; there is no `Constants.MarkerType` enum |
| Save | `project.saveAs(<package>/project.prproj)` | |
| Export | `EncoderManager.exportSequence(seq, ExportType.QUEUE_TO_AME, out, preset, true)` | **needs a preset — see below** |

## The export preset (`.epr`)

Premiere 25.6's `exportSequence` **requires** a preset file; there is no
3-argument overload. The panel looks for `export/qalun_h264.epr` inside the
package and, if it isn't there, tells you to export by hand rather than failing
deep inside AME with an opaque error.

To create it once: **File → Export → Media → H.264 → Save Preset**, then save it
into the package as `export/qalun_h264.epr`. Ship it with future packages.

Note `EncoderManager.launchEncoder()` is **26.3+ only**; on 25.6 the job is
queued and you bring AME to the front yourself.

## If the panel doesn't load

UXP's `require()` does **no** Node-style resolution — relative modules need the
explicit `.js` extension (`require("./spec.js")`, not `require("./spec")`). That
is already fixed here. If the module graph still fails on your build, switch to
the pre-generated flat bundle: edit `index.html` and change

    <script src="src/main.js"></script>   ->   <script src="index.bundle.js"></script>

Regenerate the bundle after editing anything in `src/` with:

    python3 uxp-panel/build_bundle.py

## MOGRT contract (next step, not this repo)

Author in After Effects → Essential Graphics:

- `ayah_display_v1.mogrt` — takes the pre-shaped ayah artwork (interim: the
  overlay PNG; target: shaped SVG from component packs, §5), exposes
  position/scale/color, locks the text.
- `highlight_v1.mogrt` — exposes one keyable "active word index" (or highlight
  position) param; the spec's `word_highlight.keyframes` (`surah:ayah:word`
  keyed, float seconds) then map 1:1 onto `ComponentParam.createAddKeyframeAction`.

Drop them into the package under `mogrts/` and `build.js` picks them up
automatically instead of the PNGs.

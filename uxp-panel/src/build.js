/**
 * Build the editable sequence from the edit-spec (architecture §9).
 *
 * Signatures below follow the published Premiere 25.6 API reference (25.6 is the
 * minimum version supporting UXP at all, and is what we target):
 *   - project.importFiles(paths, suppressUI, targetBin, asNumberedStills)
 *   - project.createSequenceFromMedia(name, clipProjectItems, targetBin)
 *   - ppro.SequenceEditor.getEditor(seq).createOverwriteItemAction(item, time, vIdx, aIdx)
 *   - ppro.TickTime.createWithSeconds(seconds)
 *   - ppro.Markers.getMarkers(sequence) + createAddMarkerAction(...) — markerType
 *     is a plain string ("Comment"); there is no Constants.MarkerType enum.
 *   - videoClipTrackItem.createSetEndAction(tickTime) to trim a placed still.
 *   - project.lockedAccess(cb) / project.executeTransaction(cb, name)
 *
 * Still missing from UXP entirely (not a bug here):
 *   - caption-cue creation — caption tracks are READ-ONLY through 26.3, see
 *     captions.js for the SRT fallback;
 *   - the highlight_v1 MOGRT that word_highlight keyframes would drive.
 */
"use strict";

const ppro = require("premierepro");
const { resolvePath, fileExists } = require("./spec.js");

/** Run one prepared action inside a locked transaction (Adobe sample pattern). */
function runTransaction(project, name, buildActions) {
  project.lockedAccess(() => {
    project.executeTransaction((compoundAction) => {
      for (const action of buildActions()) {
        compoundAction.addAction(action);
      }
    }, name);
  });
}

/** Find a project item by file name. getRootItem() is async and returns a FolderItem. */
async function findProjectItemByName(project, name) {
  const root = await project.getRootItem();
  const stack = [root];
  while (stack.length) {
    const folder = stack.pop();
    const items = await folder.getItems();
    for (const item of items) {
      if (item.name === name) return item;
      if (typeof item.getItems === "function") stack.push(item);
    }
  }
  return null;
}

/** Import every media path in the spec plus all overlay PNG assets. */
async function importPackageMedia(project, spec, packageNativePath, log) {
  const paths = [];
  for (const media of spec.media) paths.push(resolvePath(packageNativePath, media.path));
  const graphics = spec.tracks.find((t) => t.kind === "graphics");
  const seen = new Set();
  for (const item of (graphics ? graphics.items : [])) {
    if (item.type === "ayah_overlay" && item.asset && !seen.has(item.asset)) {
      seen.add(item.asset);
      paths.push(resolvePath(packageNativePath, item.asset));
    }
  }
  log(`Importing ${paths.length} file(s)…`);
  const root = await project.getRootItem();
  const ok = await project.importFiles(
    paths,
    /* suppressUI */ true,
    /* targetBin */ root,
    /* asNumberedStills */ false
  );
  if (!ok) throw new Error("importFiles reported failure");
  return paths;
}

/**
 * Create the sequence. Preferred: createSequenceFromMedia with the reference
 * render, which conforms the sequence to the exact render settings
 * (width/height/fps) without needing a .sqpreset on disk. Fallback: default
 * preset + a loud warning to fix settings by hand.
 */
async function createSequence(project, spec, log) {
  const videoMedia = spec.media.find((m) => m.type === "video");
  const name = "Qalun " + ((spec.meta && spec.meta.created_from && spec.meta.created_from.audio) || "sequence");
  if (videoMedia) {
    const refItem = await findProjectItemByName(project, baseName(videoMedia.path));
    if (refItem) {
      const clipItem = castClipProjectItem(refItem);
      const root = await project.getRootItem();
      const sequence = await project.createSequenceFromMedia(name, [clipItem], root);
      log("Sequence created from the reference render (settings conformed).", "ok");
      return sequence;
    }
  }
  log(
    "No reference render found — created a default-preset sequence; verify " +
      `${spec.project.width}x${spec.project.height}@${spec.project.fps} manually.`,
    "warn"
  );
  return project.createSequence(name);
}

/** ClipProjectItem.cast narrows a ProjectItem; feature-detected for safety. */
function castClipProjectItem(item) {
  if (ppro.ClipProjectItem && typeof ppro.ClipProjectItem.cast === "function") {
    return ppro.ClipProjectItem.cast(item);
  }
  return item;
}

/** Place the job audio on A1 at 0 (the sequence-from-media path already has it). */
async function placeAudio(project, sequence, spec, log) {
  const audioMedia = spec.media.find((m) => m.type === "audio");
  const item = await findProjectItemByName(project, baseName(audioMedia.path));
  if (!item) throw new Error(`Audio '${audioMedia.path}' not found after import`);
  const editor = ppro.SequenceEditor.getEditor(sequence);
  runTransaction(project, "Qalun: place audio", () => [
    editor.createOverwriteItemAction(
      castClipProjectItem(item),
      ppro.TickTime.createWithSeconds(0),
      0,
      0
    ),
  ]);
  log("Audio placed on A1 at 0.", "ok");
}

/**
 * Place ayah overlays. When the MOGRT from the spec exists inside the package
 * (mogrts/<name>.mogrt) instantiate it; otherwise fall back to the interim
 * transparent PNG on V2 (V1 holds the reference render).
 */
async function placeOverlays(project, sequence, spec, packageNativePath, log) {
  const graphics = spec.tracks.find((t) => t.kind === "graphics");
  if (!graphics) return;
  const overlays = graphics.items.filter((i) => i.type === "ayah_overlay");
  const editor = ppro.SequenceEditor.getEditor(sequence);

  let placed = 0;
  let untrimmed = 0;
  for (const overlay of overlays) {
    const startTime = ppro.TickTime.createWithSeconds(overlay.in);
    const mogrtPath = resolvePath(packageNativePath, `mogrts/${overlay.mogrt}.mogrt`);
    if (await fileExists(mogrtPath)) {
      // §9 target state: MOGRT with editable style, locked text.
      editor.insertMogrtFromPath(mogrtPath, startTime, 1, 1);
      placed++;
      continue;
    }
    const item = await findProjectItemByName(project, baseName(overlay.asset));
    if (!item) {
      log(`Overlay asset missing in project: ${overlay.asset}`, "warn");
      continue;
    }
    runTransaction(project, `Qalun: overlay ${overlay.ref}`, () => [
      editor.createOverwriteItemAction(castClipProjectItem(item), startTime, 1, 0),
    ]);
    if (!(await trimOverlayToSpec(project, sequence, overlay, log))) untrimmed++;
    placed++;
  }
  log(`Placed ${placed}/${overlays.length} ayah overlay(s) on V2.`, placed === overlays.length ? "ok" : "warn");
  if (untrimmed) {
    log(`${untrimmed} overlay(s) kept Premiere's default still duration — trim by hand.`, "warn");
  }
}

/**
 * Trim a placed still to its card window. Without this the PNG keeps Premiere's
 * default still duration (~5 s) rather than running to overlay.out — for the
 * furquanTra7-11 package that would end the ayah card at ~9 s instead of ~101 s.
 * Defensive: a failure here costs one manual trim, not the whole build.
 */
async function trimOverlayToSpec(project, sequence, overlay, log) {
  try {
    const track = await sequence.getVideoTrack(1);
    if (!track) return false;
    const items = await track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
    if (!items || !items.length) return false;

    // The clip we just overwrote is the one starting at overlay.in.
    let target = null;
    let closest = Infinity;
    for (const item of items) {
      const start = await item.getStartTime();
      const delta = Math.abs(Number(start.seconds) - overlay.in);
      if (delta < closest) {
        closest = delta;
        target = item;
      }
    }
    if (!target || typeof target.createSetEndAction !== "function") return false;

    runTransaction(project, `Qalun: trim overlay ${overlay.ref}`, () => [
      target.createSetEndAction(ppro.TickTime.createWithSeconds(overlay.out)),
    ]);
    return true;
  } catch (error) {
    log(`Could not trim overlay ${overlay.ref} (${error.message}).`, "warn");
    return false;
  }
}

/**
 * Word-highlight keyframes. Target state (§9): drive the highlight_v1 MOGRT's
 * position/progress param per keyframe. Until that MOGRT is authored there is
 * no numeric param to key, so this logs the intent and — as a proof of the
 * keyframe pipeline — keys Opacity on the overlay clip when reachable.
 */
async function applyHighlightKeyframes(project, sequence, spec, log) {
  const graphics = spec.tracks.find((t) => t.kind === "graphics");
  if (!graphics) return;
  const highlights = graphics.items.filter((i) => i.type === "word_highlight");
  const total = highlights.reduce((n, i) => n + (i.keyframes || []).length, 0);
  if (!total) return;
  log(
    `word_highlight: ${total} keyframes staged for '${highlights[0].mogrt}'. ` +
      "MOGRT not authored yet — keyframes are NOT applied in this skeleton " +
      "(see README: highlight MOGRT contract).",
    "warn"
  );
  // Pipeline proof (runs when the first overlay clip is reachable):
  //   const track = await sequence.getVideoTrack(1);
  //   const clip = track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false)[0];
  //   const chain = await clip.getComponentChain();
  //   ...find Opacity componentParam → createKeyframe/createAddKeyframeAction
  // Left commented until the MOGRT lands so the walking skeleton never fights
  // a designer's manual opacity work.
}

/** One sequence marker named "surah:ayah" at each ayah start (cue refs). */
async function addAyahMarkers(project, sequence, spec, log) {
  const captions = spec.tracks.find((t) => t.kind === "captions");
  if (!captions) return;
  const markers = await ppro.Markers.getMarkers(sequence);
  const cuesWithRefs = captions.cues.filter((cue) => cue.ref);
  runTransaction(project, "Qalun: ayah markers", () =>
    cuesWithRefs.map((cue) =>
      markers.createAddMarkerAction(
        cue.ref,
        "Comment", // markerType is a plain string; there is no Constants.MarkerType enum
        ppro.TickTime.createWithSeconds(cue.in),
        ppro.TickTime.createWithSeconds(Math.max(0, cue.out - cue.in)),
        cue.text || ""
      )
    )
  );
  log(`Added ${cuesWithRefs.length} ayah marker(s).`, "ok");
}

function baseName(relPath) {
  return relPath.split("/").pop();
}

module.exports = {
  importPackageMedia,
  createSequence,
  placeAudio,
  placeOverlays,
  applyHighlightKeyframes,
  addAyahMarkers,
  findProjectItemByName,
};

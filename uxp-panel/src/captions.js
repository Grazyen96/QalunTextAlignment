/**
 * Caption track from the spec's cue list (editable text — the whole point of
 * §9's "scripting, not export formats").
 *
 * Reality check against @adobe/premierepro 26.3.0: caption tracks are
 * READ-ONLY in UXP today — Sequence exposes getCaptionTrackCount() and
 * getCaptionTrack(i), and CaptionTrack has no cue-creation methods. The
 * ExtendScript API had Sequence.createCaptionTrack(projectItem, …) fed by an
 * imported SRT/caption project item, but ExtendScript sunsets Sept 2026 and
 * is not a base to build on.
 *
 * Strategy, in order:
 *   1. Feature-detect a createCaptionTrack on the UXP sequence object (newer
 *      builds may add it) and feed it the imported SRT project item.
 *   2. Fallback: import the package's SRT (UTF-8 BOM, RTL-safe) into the
 *      project bin and tell the user to drop it on a caption track — one
 *      manual drag, captions stay fully editable afterwards.
 */
"use strict";

const { resolvePath } = require("./spec.js");

async function buildCaptions(project, sequence, spec, packageNativePath, log) {
  const captions = spec.tracks.find((t) => t.kind === "captions");
  if (!captions || !captions.cues || !captions.cues.length) {
    log("No caption cues in spec; skipping captions.");
    return;
  }

  const srtNative = resolvePath(packageNativePath, captions.srt);
  const root = await project.getRootItem();
  const imported = await project.importFiles([srtNative], true, root, false);
  if (!imported) {
    log(`Could not import caption SRT '${captions.srt}'.`, "error");
    return;
  }

  if (typeof sequence.createCaptionTrack === "function") {
    // Not in any shipped UXP build (caption tracks are read-only through 26.3);
    // feature-detected so the panel picks it up the moment Adobe ships it.
    const { findProjectItemByName } = require("./build.js");
    const srtItem = await findProjectItemByName(project, captions.srt.split("/").pop());
    try {
      await sequence.createCaptionTrack(srtItem);
      log(`Caption track created from ${captions.srt} (${captions.cues.length} cues).`, "ok");
      return;
    } catch (error) {
      log(`createCaptionTrack failed (${error.message}); falling back.`, "warn");
    }
  }

  log(
    `Caption cues imported as '${captions.srt}' in the project bin. UXP cannot ` +
      "create caption tracks yet (read-only caption API as of 26.3) — drag the " +
      "SRT onto the sequence once; Premiere converts it to an editable caption track.",
    "warn"
  );
}

module.exports = { buildCaptions };

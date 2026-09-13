/**
 * Save the editable project and trigger the AME export (§9: both outputs come
 * from the same project, so the MP4 always matches the .prproj exactly).
 *
 * Premiere 25.6 API reference:
 *   EncoderManager.getManager(), manager.isAMEInstalled (property)
 *   manager.exportSequence(sequence, exportType, outputFile, presetFile, exportFull)
 *     — presetFile (.epr) is REQUIRED; there is no 3-arg overload.
 *   Constants.ExportType.{QUEUE_TO_AME, QUEUE_TO_APP, IMMEDIATELY}
 *   manager.launchEncoder() is 26.3+ ONLY — feature-detect before calling.
 */
"use strict";

const ppro = require("premierepro");
const { resolvePath, fileExists } = require("./spec.js");

const PRESET_REL = "export/qalun_h264.epr";

async function saveProjectIntoPackage(project, packageNativePath, log) {
  const target = resolvePath(packageNativePath, "project.prproj");
  const ok = await project.saveAs(target);
  if (!ok) throw new Error("project.saveAs failed");
  log(`Saved editable project: ${target}`, "ok");
  return target;
}

async function exportViaAME(project, sequence, spec, packageNativePath, log) {
  const manager = ppro.EncoderManager.getManager();
  const output = resolvePath(packageNativePath, "video/export_from_premiere.mp4");
  const preset = resolvePath(packageNativePath, PRESET_REL);

  // 25.6 requires a preset file. We ship none, and passing a bogus path fails
  // deeper in AME with an opaque error — so bail out with instructions instead.
  if (!(await fileExists(preset))) {
    log(
      `No export preset at '${PRESET_REL}'. Premiere 25.6 requires one for a ` +
        "scripted export. Either create it once (File → Export → Media → H.264 → " +
        `Save Preset → save into the package as ${PRESET_REL}) and click again, ` +
        "or just export by hand with File → Export → Media.",
      "warn"
    );
    return;
  }

  if (manager.isAMEInstalled) {
    const queued = await manager.exportSequence(
      sequence,
      ppro.Constants.ExportType.QUEUE_TO_AME,
      output,
      preset,
      /* exportFull */ true
    );
    if (queued) {
      if (typeof manager.launchEncoder === "function") {
        await manager.launchEncoder(); // 26.3+ only
        log(`Export queued in Adobe Media Encoder → ${output}`, "ok");
      } else {
        log(
          `Export queued → ${output}. Switch to Adobe Media Encoder and press ` +
            "Play to render (launchEncoder needs Premiere 26.3+).",
          "warn"
        );
      }
      return;
    }
    log("Queueing to AME failed; trying in-app export.", "warn");
  } else {
    log("AME not installed; using in-app export.", "warn");
  }

  // Fallback 1: Premiere's own export queue (no AME needed, blocks the app).
  const done = await manager.exportSequence(
    sequence,
    ppro.Constants.ExportType.IMMEDIATELY,
    output,
    preset,
    /* exportFull */ true
  );
  if (done) {
    log(`Exported in-app → ${output}`, "ok");
    return;
  }

  // Fallback 2 (§9): an AME watch folder. Nothing to automate from here —
  // the user points a watch folder at the package and drops project.prproj in.
  log(
    "Automatic export failed. Fallback: configure an AME watch folder on the " +
      "package directory and drop project.prproj into it.",
    "error"
  );
}

module.exports = { saveProjectIntoPackage, exportViaAME };

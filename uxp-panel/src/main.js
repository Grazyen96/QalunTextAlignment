/**
 * Panel bootstrap: wires the four buttons to the §9 pipeline
 * (read spec → import media → build sequence → captions/overlays/markers →
 * save project.prproj → AME export).
 */
"use strict";

// UXP's require() does no Node-style resolution: relative modules must carry
// the explicit .js extension or the panel dies at load.
const ppro = require("premierepro");
const { loadSpecInteractive, summarize } = require("./spec.js");
const build = require("./build.js");
const { buildCaptions } = require("./captions.js");
const { saveProjectIntoPackage, exportViaAME } = require("./exporter.js");

const state = { spec: null, packageNativePath: null, sequence: null };

const logEl = document.getElementById("log");
function log(message, cls) {
  const line = document.createElement("div");
  if (cls) line.className = cls;
  line.textContent = message;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}

async function activeProject() {
  const project = await ppro.Project.getActiveProject();
  if (!project) throw new Error("Open (or create) a project in Premiere first.");
  return project;
}

document.getElementById("btn-load").addEventListener("click", async () => {
  try {
    const loaded = await loadSpecInteractive();
    if (!loaded) return;
    state.spec = loaded.spec;
    state.packageNativePath = loaded.packageNativePath;
    document.getElementById("spec-summary").textContent = summarize(loaded.spec);
    document.getElementById("btn-build").disabled = false;
    log(`Loaded spec from ${loaded.packageNativePath}`, "ok");
    for (const warning of (loaded.spec.meta && loaded.spec.meta.validation_warnings) || []) {
      log(`emitter warning: ${warning}`, "warn");
    }
  } catch (error) {
    log(error.message, "error");
  }
});

document.getElementById("btn-build").addEventListener("click", async () => {
  try {
    const project = await activeProject();
    const { spec, packageNativePath } = state;

    await build.importPackageMedia(project, spec, packageNativePath, log);
    state.sequence = await build.createSequence(project, spec, log);
    await build.placeAudio(project, state.sequence, spec, log);
    await build.placeOverlays(project, state.sequence, spec, packageNativePath, log);
    await build.applyHighlightKeyframes(project, state.sequence, spec, log);
    await buildCaptions(project, state.sequence, spec, packageNativePath, log);
    await build.addAyahMarkers(project, state.sequence, spec, log);

    document.getElementById("btn-save").disabled = false;
    log("Sequence built. Review, then save + export.", "ok");
  } catch (error) {
    log("Build failed: " + error.message, "error");
  }
});

document.getElementById("btn-save").addEventListener("click", async () => {
  try {
    const project = await activeProject();
    await saveProjectIntoPackage(project, state.packageNativePath, log);
    document.getElementById("btn-export").disabled = false;
  } catch (error) {
    log("Save failed: " + error.message, "error");
  }
});

document.getElementById("btn-export").addEventListener("click", async () => {
  try {
    const project = await activeProject();
    await exportViaAME(project, state.sequence, state.spec, state.packageNativePath, log);
  } catch (error) {
    log("Export failed: " + error.message, "error");
  }
});

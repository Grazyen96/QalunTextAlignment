/**
 * Load and validate an edit_spec.json package (architecture §8).
 *
 * The spec is format-neutral: float-second times, media paths relative to the
 * package folder. Everything Premiere-specific happens in build.js/exporter.js.
 */
"use strict";

const uxp = require("uxp");

/** Minimal structural validation — fail loudly before touching the project. */
function validateSpec(spec) {
  const problems = [];
  if (!spec || typeof spec !== "object") problems.push("root is not an object");
  if (!spec.project || !spec.project.fps || !spec.project.width || !spec.project.height) {
    problems.push("project.fps/width/height missing");
  }
  if (!Array.isArray(spec.media) || spec.media.length === 0) {
    problems.push("media list missing or empty");
  }
  if (!Array.isArray(spec.tracks)) problems.push("tracks list missing");
  const audio = (spec.media || []).find((m) => m.type === "audio");
  if (!audio) problems.push("no audio media entry");
  return problems;
}

/**
 * Open a folder picker rooted at the package, read edit_spec.json, and return
 * { spec, packageFolder } where packageFolder is a UXP folder entry used to
 * resolve the spec's relative media paths to native paths.
 */
async function loadSpecInteractive() {
  const fs = uxp.storage.localFileSystem;
  const specFile = await fs.getFileForOpening({ types: ["json"] });
  if (!specFile) return null;

  const spec = JSON.parse(await specFile.read());
  const problems = validateSpec(spec);
  if (problems.length) {
    throw new Error("edit_spec.json is not usable: " + problems.join("; "));
  }

  // The package folder is the spec file's parent; relative paths resolve
  // against it. UXP file entries expose the OS path via nativePath.
  const packageNativePath = specFile.nativePath.replace(/[\\/][^\\/]+$/, "");
  return { spec, packageNativePath };
}

/** Resolve a spec-relative path ("audio/x.m4a") to a native OS path. */
function resolvePath(packageNativePath, relPath) {
  const sep = packageNativePath.includes("\\") ? "\\" : "/";
  return packageNativePath + sep + relPath.split("/").join(sep);
}

/** Does a native path exist? Used to probe for optional package assets. */
async function fileExists(nativePath) {
  try {
    await uxp.storage.localFileSystem.getEntryWithUrl("file:" + nativePath);
    return true;
  } catch (error) {
    return false;
  }
}

/** One-line human summary for the panel UI. */
function summarize(spec) {
  const captions = spec.tracks.find((t) => t.kind === "captions");
  const graphics = spec.tracks.find((t) => t.kind === "graphics");
  const overlays = graphics ? graphics.items.filter((i) => i.type === "ayah_overlay") : [];
  const highlights = graphics ? graphics.items.filter((i) => i.type === "word_highlight") : [];
  const keyframes = highlights.reduce((n, i) => n + (i.keyframes || []).length, 0);
  return [
    `mode: ${(spec.meta && spec.meta.mode) || "?"}`,
    `project: ${spec.project.width}x${spec.project.height} @ ${spec.project.fps} fps`,
    `media: ${spec.media.length}  cues: ${captions ? captions.cues.length : 0}`,
    `overlays: ${overlays.length}  highlight keyframes: ${keyframes}`,
    `warnings from emitter: ${(spec.meta && (spec.meta.validation_warnings || []).length) || 0}`,
  ].join("\n");
}

module.exports = { loadSpecInteractive, resolvePath, fileExists, summarize, validateSpec };

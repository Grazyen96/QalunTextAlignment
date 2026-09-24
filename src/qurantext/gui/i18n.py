"""The window's words, in one table per language.

Every string a person reads in the window comes from here, so adding a
language means adding a table, not editing widgets. English is the fallback for
a key a newer build added before its translation; the key itself is the last
resort, and a test fails the build long before that shows.
"""

from __future__ import annotations

__all__ = ["LANGUAGES", "STRINGS", "current_language", "set_language", "t"]

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # Tasks 3–9 add their keys here, grouped by widget.
        "home.jobs": "Your jobs",
        "home.refresh": "Refresh",
        "home.mode.recitation": "Recitation",
        "home.mode.lecture": "Lecture",
        "home.cards": "{count} card(s)",
        "home.status.needs_review": "Needs review",
        "home.status.reviewed": "Reviewed",
        "home.status.rendered": "Rendered",
        "home.status.changed_since_render": "Changed since render",
        "home.status.damaged": "Damaged",
        "home.show_in_folder": "Show in folder",
        "home.remove_from_list": "Remove from list",
        "home.empty": "Your jobs appear here once you start one.",
        "home.new_job": "New job",
        "home.drop": "Drop an audio file, or choose one",
        "home.choose": "Choose…",
        "home.choose_audio.dialog_title": "Choose an audio file",
        "home.surah": "Surah",
        "home.surah_item": "{num}. {name}  ({count} ayat)",
        "home.filter.audio": "Audio and video",
        "home.filter.text": "Text files",
        "home.filter.all": "All files",
        "home.range": "Ayat",
        "home.range_from": "from",
        "home.range_to": "to",
        "home.video_size": "Video size",
        "preset.social": "Portrait 1080×1920 · 30 fps",
        "preset.high": "Landscape 1920×1080 · 30 fps",
        "preset.standard": "Landscape 1280×720 · 25 fps",
        "preset.fast": "Quick draft 960×540 · 24 fps",
        "home.more": "More options",
        "home.quran_missing": "Choose the Quran text file first",
        "home.quran_store_error": "Could not read the Quran store: {details}",
        "home.quran_override.default": "Quran text: the certified text that ships with Qalun",
        "home.quran_override.custom": "Quran text: {path}",
        "home.quran_override.reset": "Use the shipped text",
        "home.quran_override.dialog_title": "Choose the Quran text file",
        "home.output_dir.default": "Output folder: the default location",
        "home.output_dir.custom": "Output folder: {path}",
        "home.output_dir.reset": "Default",
        "home.output_dir.dialog_title": "Choose the output folder",
        "home.subtitles.burn": "In the picture",
        "home.subtitles.sidecar": "As files beside the video",
        "home.subtitles.both": "Both",
        "format.srt": "SRT",
        "format.vtt": "VTT",
        "format.ass": "ASS",
        "home.render_right_away": "Render right away (skip the review)",
        "home.start": "Start",
        "home.cancel": "Cancel",
        "job.need_audio": "Choose an audio file.",
        "job.need_quran": "Choose the Quran text file.",
        "job.need_range": "Choose the surah and the ayah range.",
        "job.bad_range": "The last ayah cannot come before the first.",
        "job.need_format": "Choose at least one subtitle format.",
        "job.progress.aligning": "Aligning against the ayat you chose…",
        "job.progress.detecting": "Looking for Quran in the audio…",
        "job.progress.kept": "Kept your earlier corrections in {name}",
        "app.title": "Qalun",
        "home.progress.starting": "Starting…",
        "home.progress.stopping": "Stopping…",
        "home.progress.matching": "Matching — {percent}%",
        "home.progress.matching_eta": "Matching — {percent}%, about {eta} left",
        "home.progress.rendering": "Rendering — {percent}%",
        "home.progress.rendering_eta": "Rendering — {percent}%, about {eta} left",
        "home.eta.seconds": "{seconds}s",
        "home.eta.minutes": "{minutes}m {seconds}s",
        "home.finished.matched": "Matched {count} card(s). The review is open.",
        "home.finished.rendered": "Saved the video to {path}",
        "home.failed": "That did not finish: {details}",
        "home.failed.title": "That did not finish",
        "home.cancelled": "Stopped before it finished.",
        "home.damaged": "This job cannot be opened: {details}",
        "home.close_review_first": "Close the review of this job before running it again.",
        "home.review_failed": "Could not open {name} for review: {details}",
        "main.saved": "Corrections saved to {path}",
        "player.unavailable": "Playback is off on this machine: {details}",
        "player.unavailable_short": "Playback is off: install PySide6-Addons to hear the recording.",
        "waveform.reading": "Reading the recording…",
        "waveform.missing": "The recording is not available.",
        "frame.error": "Could not draw the frame: {details}",
        "segments.ref": "Ayah",
        "segments.time": "Time",
        "segments.text": "Text",
        "segments.retimed": "Retimed",
        "segments.speech": "Speech",
        "segments.locked": "Quran text is read from the store and cannot be edited here.",
        "review.title": "Review — {name}",
        "review.save": "Save",
        "review.undo": "Undo",
        "review.redo": "Redo",
        "review.mark_reviewed": "Mark as reviewed",
        "review.export": "Export subtitles…",
        "review.render": "Render with corrections",
        "review.remove": "Remove selected",
        "review.remove_none": "Select a row to remove.",
        "review.play": "Play",
        "review.pause": "Pause",
        "review.rate": "{rate:g}×",
        "review.zoom": "Zoom",
        "review.snap": "Snap to playhead",
        "review.minus": "−50 ms",
        "review.plus": "+50 ms",
        "review.no_selection": "Select a word to retime it",
        "review.selected": "{word}  {start} → {end} s",
        "review.gaps": "{count} stretch(es) of speech have no word:",
        "review.gap": "{duration:.1f} s at {start:.1f}–{end:.1f} s",
        "review.jump": "Jump",
        "review.covered": "Every stretch of speech is covered by a word.",
        "review.checking": "Checking the recording for speech with no word…",
        "review.more_gaps": "…and {count} more",
        "review.audio_missing": "The recording is not where the project says: {path}",
        "review.discard_title": "Save your corrections?",
        "review.discard_text": "This review has changes that are not saved.",
        "review.shortcuts": (
            "Space plays · ←/→ step words · [ and ] set start/end at the playhead · "
            ", and . nudge · Ctrl-drag an edge to part two words · Ctrl+Z undoes"
        ),
        "export.title": "Export subtitles",
        "export.formats": "Formats",
        "export.folder": "Folder",
        "export.choose": "Choose…",
        "export.name": "File name",
        "export.match_video": "Match the rendered video (includes the basmala at the start)",
        "export.match_audio": "Match the original recording",
        "export.go": "Export",
        "export.done": "Wrote {count} file(s):",
        "export.show": "Show in folder",
        "export.none_chosen": "Choose at least one format.",
        "export.no_name": "Enter a file name.",
        "export.stale": "(rendered before your latest changes)",
        "export.close": "Close",
        "render.running": "Rendering — {percent}%",
        "render.done": "The video is ready: {path}",
        "render.show": "Show the video",
        "render.failed": "The render did not finish: {details}",
        "render.cancelled": "Rendering stopped.",
        "render.cancel": "Cancel",
    },
}
LANGUAGES = tuple(STRINGS)

_current = "en"


def current_language() -> str:
    return _current


def set_language(code: str) -> None:
    global _current
    if code not in STRINGS:
        raise ValueError(f"Unknown language {code!r}; choose from {', '.join(LANGUAGES)}.")
    _current = code


def t(key: str, **fmt: object) -> str:
    text = STRINGS.get(_current, {}).get(key) or STRINGS["en"].get(key) or key
    return text.format(**fmt) if fmt else text

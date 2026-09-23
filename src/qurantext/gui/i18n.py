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
        "player.unavailable": "Playback is off on this machine: {details}",
        "waveform.reading": "Reading the recording…",
        "frame.error": "Could not draw the frame: {details}",
        "segments.ref": "Ayah",
        "segments.time": "Time",
        "segments.text": "Text",
        "segments.retimed": "Retimed",
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
        "review.audio_missing": "The recording is not where the project says: {path}",
        "review.discard_title": "Save your corrections?",
        "review.discard_text": "This review has changes that are not saved.",
        "review.shortcuts": (
            "Space plays · ←/→ step words · [ and ] set start/end at the playhead · "
            ", and . nudge · Ctrl+Z undoes"
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

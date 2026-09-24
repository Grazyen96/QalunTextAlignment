"""The window's words, in one table per language.

Every string a person reads in the window comes from here, so adding a
language means adding a table, not editing widgets. English is the fallback for
a key a newer build added before its translation; the key itself is the last
resort, and a test fails the build long before that shows.

A key whose sentence depends on a number maps to its plural forms (CLDR's
cardinal categories: ``zero one two few many other``) and is read with
:func:`tn`; English needs ``one`` and ``other``, Arabic all six. In a
right-to-left language every value formatted into a sentence is isolated, so a
time range or a Latin file name keeps its own direction instead of being
reordered by the Arabic around it.

No Qt here: the review session raises errors in these words, and it imports no Qt.
"""

from __future__ import annotations

import string

__all__ = [
    "LANGUAGES",
    "LANGUAGE_NAMES",
    "RTL_LANGUAGES",
    "STRINGS",
    "current_language",
    "is_rtl",
    "ltr",
    "plural_category",
    "set_language",
    "t",
    "time_span",
    "tn",
]

#: Languages written right to left: their layout mirrors, and every value
#: formatted into their sentences is isolated so it keeps its own direction.
RTL_LANGUAGES = frozenset({"ar"})

#: Each language by its own name, for the language menu; never translated.
LANGUAGE_NAMES = {"en": "English", "ar": "العربية"}

_FSI, _LRI, _PDI = "\u2068", "\u2066", "\u2069"

STRINGS: dict[str, dict[str, str | dict[str, str]]] = {
    "en": {
        # Tasks 3–9 add their keys here, grouped by widget.
        "home.jobs": "Your jobs",
        "home.refresh": "Refresh",
        "home.mode.recitation": "Recitation",
        "home.mode.lecture": "Lecture",
        "home.cards": {"one": "{count} card", "other": "{count} cards"},
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
        "home.surah_item": {
            "one": "{num}. {name}  ({count} ayah)",
            "other": "{num}. {name}  ({count} ayat)",
        },
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
        "home.finished.matched": {
            "one": "Matched {count} card. The review is open.",
            "other": "Matched {count} cards. The review is open.",
        },
        "home.finished.rendered": "Saved the video to {path}",
        "home.failed": "That did not finish: {details}",
        "home.failed.title": "That did not finish",
        "home.cancelled": "Stopped before it finished.",
        "home.damaged": "This job cannot be opened: {details}",
        "home.close_review_first": "Close the review of this job before running it again.",
        "home.busy_matching": "This job is running again; open its review once it finishes.",
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
        "review.selected": "{word}  {span} s",
        "review.gaps": {
            "one": "{count} stretch of speech has no word:",
            "other": "{count} stretches of speech have no word:",
        },
        "review.gap": "{duration:.1f} s at {span} s",
        "review.jump": "Jump",
        "review.covered": "Every stretch of speech is covered by a word.",
        "review.checking": "Checking the recording for speech with no word…",
        "review.more_gaps": {"one": "…and {count} more", "other": "…and {count} more"},
        "review.audio_missing": "The recording is not where the project says: {path}",
        "review.save_failed": "The corrections were not saved: {details}",
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
        "export.match_video_stale": (
            "Match the video's timeline (rendered before your latest changes)"
        ),
        "export.match_audio": "Match the original recording",
        "export.go": "Export",
        "export.done": {
            "one": "Wrote {count} file: {names}",
            "other": "Wrote {count} files: {names}",
        },
        "export.show": "Show in folder",
        "export.none_chosen": "Choose at least one format.",
        "export.no_name": "Enter a file name.",
        "export.failed": "The subtitles were not written: {details}",
        "export.close": "Close",
        "render.running": "Rendering — {percent}%",
        "render.done": "The video is ready: {path}",
        "render.show": "Show the video",
        "render.failed": "The render did not finish: {details}",
        "render.cancelled": "Rendering stopped.",
        "render.cancel": "Cancel",
        "session.card_follows_words": (
            "This card's times follow its words; retime the words instead."
        ),
        "session.no_file": "This project has no file to write back to.",
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


def is_rtl(code: str | None = None) -> bool:
    """Whether *code* (default: the current language) is written right to left."""
    return (code or _current) in RTL_LANGUAGES


def plural_category(language: str, n: int) -> str:
    """CLDR's cardinal category of *n* in *language* (only the two we ship).

    Arabic has six forms: 0, 1, 2, then by the last two digits 3–10 ("few")
    and 11–99 ("many"), and "other" for the hundreds (100, 102…). Every other
    language falls back to English's one/other.
    """
    n = abs(int(n))
    if language == "ar":
        if n == 0:
            return "zero"
        if n == 1:
            return "one"
        if n == 2:
            return "two"
        if 3 <= n % 100 <= 10:
            return "few"
        if 11 <= n % 100 <= 99:
            return "many"
        return "other"
    return "one" if n == 1 else "other"


class _Isolating(string.Formatter):
    """Wraps every formatted value in FSI…PDI.

    Without it a time range inside an Arabic sentence ("12.3–15.2") is laid out
    as "15.2–12.3", and a Latin file name drags the words around it out of order.
    FSI gives each value the direction of its own first strong letter, and a
    value with none (a number, a range of times) runs left to right.
    """

    def format_field(self, value: object, format_spec: str) -> str:
        return _FSI + super().format_field(value, format_spec) + _PDI


_ISOLATING = _Isolating()


def _lookup(key: str) -> tuple[str, str | dict[str, str]] | None:
    """*key*'s entry and the language it came from: the current one, else English."""
    for language in (_current, "en"):
        value = STRINGS.get(language, {}).get(key)
        if value:
            return language, value
    return None


def _format(text: str, fmt: dict[str, object]) -> str:
    """The one place values enter a sentence, so none escapes isolation in RTL."""
    if not fmt:
        return text
    return _ISOLATING.format(text, **fmt) if is_rtl() else text.format(**fmt)


def t(key: str, **fmt: object) -> str:
    """*key*'s text in the current language, with *fmt* formatted in."""
    found = _lookup(key)
    if found is None:
        return key
    _, value = found
    if isinstance(value, dict):
        raise TypeError(f"{key!r} depends on a count; use tn({key!r}, count).")
    return _format(value, fmt)


def tn(key: str, count: int, **fmt: object) -> str:
    """*key*'s text for *count* things, in the current language's plural form.

    The form is chosen by the language the text came from, so an English
    fallback inside an Arabic window still reads "1 file", not "1 files".
    """
    found = _lookup(key)
    if found is None:
        return key
    language, value = found
    if isinstance(value, str):
        return _format(value, {"count": count, **fmt})
    text = value.get(plural_category(language, count)) or value["other"]
    return _format(text, {"count": count, **fmt})


def time_span(start: float, end: float, *, digits: int = 2, sep: str = "–") -> str:
    """Two times as one value, so a sentence in any language keeps them in order."""
    return f"{start:.{digits}f}{sep}{end:.{digits}f}"


def ltr(text: str) -> str:
    """*text* forced left to right inside right-to-left surroundings (a table cell of times)."""
    return f"{_LRI}{text}{_PDI}" if is_rtl() else text

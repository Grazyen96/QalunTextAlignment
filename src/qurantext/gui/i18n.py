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
import unicodedata

from qurantext.services.model_store import LOCAL_MODEL

__all__ = [
    "LANGUAGES",
    "LANGUAGE_NAMES",
    "RTL_LANGUAGES",
    "STRINGS",
    "clock",
    "current_language",
    "is_rtl",
    "ltr",
    "path_text",
    "plain_title",
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

_FSI, _LRI, _PDI, _LRM = "\u2068", "\u2066", "\u2069", "\u200e"
_RLI, _RLM = "\u2067", "\u200f"

#: The speech model's download, rounded for people ("about 110 MB"); read from
#: the pinned model so a new one never leaves an old figure behind.
_MODEL_MB = LOCAL_MODEL.download_mb

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
        # The name is isolated here too: an Arabic file name leading the line
        # would otherwise lay it out right to left.
        "home.running_row": "\u2068{name}\u2069 — {progress}",
        "home.open": "Open",
        "home.show_in_folder": "Show in folder",
        "home.remove_from_list": "Remove from list",
        "home.reading": "Reading your jobs…",
        "home.new_job": "New job",
        "home.drop": "Drop an audio file, or choose one",
        "home.choose": "Choose…",
        "home.choose_audio.dialog_title": "Choose an audio file",
        "home.surah": "Surah",
        "home.surah_item": {
            "one": "{num}. {name}  ({count} ayah)",
            "other": "{num}. {name}  ({count} ayat)",
        },
        "surah.detect": "Detect automatically",
        "surah.item": "{num}. {name}",
        "surah.number": "Surah {num}",
        "home.studied_surah.tip": (
            "The ayah cards show only this surah; ayat quoted from other surahs stay "
            "in the subtitles. Detect automatically picks the surah heard the longest."
        ),
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
        "home.quran_text": "Quran text",
        "home.output_dir": "Output folder",
        "home.subtitles": "Subtitles",
        "home.engine": "Transcription",
        "home.engine.local": "On this computer",
        "home.engine.whisperx": "WhisperX online (needs a Replicate token)",
        "home.engine.no_token": (
            "No Replicate token is set. Put REPLICATE_API_TOKEN=… in a file named .env "
            "in {folder}, then restart Qalun."
        ),
        "home.formats": "Files",
        "home.quran_override.default": "The certified text that ships with Qalun",
        "home.quran_override.custom": "{path}",
        "home.quran_override.reset": "Use the shipped text",
        "home.quran_override.dialog_title": "Choose the Quran text file",
        "home.output_dir.default": "The default location",
        "home.output_dir.custom": "{path}",
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
        # What the status line says while a stage runs; the pipeline's own
        # messages are English log lines and are never shown.
        "job.stage.download": f"Downloading the speech model, once (about {_MODEL_MB} MB)…",
        "job.stage.unpack": "Unpacking and checking the speech model…",
        "job.stage.transcribe": "Transcribing on this computer…",
        "job.stage.transcribe_online": "Transcribing with WhisperX online…",
        "job.stage.detect": "Matching the recording to the Quran text…",
        "job.stage.match": "Looking for Quran citations in the lecture…",
        "job.stage.render": "Rendering the video…",
        "job.stage.export": "Writing subtitle files…",
        "job.stage.working": "Working…",
        "job.stage.episode_lecture": "Rendering the lecture…",
        "job.stage.episode_intro": "Making the intro…",
        "job.stage.episode_outro": "Making the outro…",
        "job.stage.episode_recitation": "Preparing the recitation for the episode…",
        "job.stage.episode_join": "Joining the episode…",
        "app.title": "Qalun",
        "home.progress.starting": "Starting…",
        "home.progress.stopping": "Stopping…",
        "home.progress.matching": "Matching — {percent}%",
        "home.progress.matching_eta": "Matching — {percent}%, about {eta} left",
        "home.progress.downloading": "Downloading the speech model — {percent}%",
        "home.progress.downloading_eta": "Downloading the speech model — {percent}%, about {eta} left",
        "home.progress.transcribing": "Transcribing — {percent}%",
        "home.progress.transcribing_eta": "Transcribing — {percent}%, about {eta} left",
        "home.progress.rendering": "Rendering — {percent}%",
        "home.progress.rendering_eta": "Rendering — {percent}%, about {eta} left",
        "home.progress.episode_lecture": "Rendering the lecture — {percent}%",
        "home.progress.episode_lecture_eta": "Rendering the lecture — {percent}%, about {eta} left",
        "home.progress.episode_intro": "Making the intro — {percent}%",
        "home.progress.episode_intro_eta": "Making the intro — {percent}%, about {eta} left",
        "home.progress.episode_outro": "Making the outro — {percent}%",
        "home.progress.episode_outro_eta": "Making the outro — {percent}%, about {eta} left",
        "home.progress.episode_recitation": "Rendering the recitation — {percent}%",
        "home.progress.episode_recitation_eta": (
            "Rendering the recitation — {percent}%, about {eta} left"
        ),
        "home.progress.episode_join": "Joining the episode — {percent}%",
        "home.progress.episode_join_eta": "Joining the episode — {percent}%, about {eta} left",
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
        "home.language": "Language",
        "home.theme": "Theme",
        "home.theme.system": "System",
        "home.theme.light": "Light",
        "home.theme.dark": "Dark",
        "home.language_busy": (
            "Close the open reviews and wait for the job to finish before changing the language."
        ),
        "home.open_log_folder": "Open log folder",
        "home.open_log_folder.tip": "Where Qalun writes down what went wrong: {path}",
        "home.open_log_failed": "Could not open the log folder {path}.",
        "home.header.theme_to_dark": "Switch to the dark theme",
        "home.header.theme_to_light": "Switch to the light theme",
        "home.header.settings": "Settings",
        "home.header.help": "Help",
        "home.help_failed": "Could not open the help page in your browser.",
        "home.mode.recitation.desc": "Times the ayat of a recitation, word by word.",
        "home.mode.lecture.desc": "Finds the ayat quoted in a lecture and shows them as cards.",
        "home.engine.note": "Transcribes online with WhisperX, which uploads the recording.",
        "home.engine.change": "Change in Settings",
        "home.empty.title": "No jobs yet",
        "home.empty.hint": "Drop a recording on the right to start one.",
        "home.detail": "{mode} · {scope}",
        "settings.title": "Settings",
        "settings.tab.general": "General",
        "settings.tab.transcription": "Transcription",
        "settings.tab.files": "Files",
        "settings.tab.videos": "Videos",
        "settings.tab.about": "About",
        "settings.job_dirs": "Also look for jobs in",
        "settings.add_dir": "Add folder…",
        "settings.add_dir.dialog_title": "Choose a folder with jobs",
        "settings.remove_dir": "Remove",
        "settings.look": "Default look for new videos",
        "settings.look.based_on": "Based on {preset}",
        "settings.look.reset": "Reset to Night gold",
        "settings.episode": "Default episode for new lectures",
        "settings.episode.intro": "Intro",
        "settings.episode.outro": "Outro",
        "settings.episode.none": "None",
        "settings.episode.generated": "Generated",
        "settings.episode.clear": "Clear",
        "settings.version": "Qalun {version}",
        "settings.notices": "Third-party notices",
        "settings.notices.missing": "The notices file is not in this build.",
        "settings.github": "Qalun on GitHub",
        "settings.close": "Close",
        "main.saved": "Corrections saved to {path}",
        "player.unavailable": "Playback is off on this machine: {details}",
        "player.unavailable_short": "Playback is off: install PySide6-Addons to hear the recording.",
        "waveform.reading": "Reading the recording…",
        "waveform.missing": "The recording is not available.",
        "frame.error": "Could not draw the frame: {details}",
        "segments.ref": "Ayah",
        "segments.time": "Time",
        "segments.text": "Text",
        "segments.retimed": "Retimed words",
        "segments.speech": "Speech",
        "segments.locked": "Quran text is read from the store and cannot be edited here.",
        "segments.change_ayah": "Change ayah…",
        "segments.manual": "Placed by hand",
        "review.title": "Review — {name}",
        "review.save": "Save",
        "review.undo": "Undo",
        "review.redo": "Redo",
        "review.mark_reviewed": "Mark as reviewed",
        "review.export": "Export subtitles…",
        "review.render": "Render",
        "review.render.tip": "Render the video with your corrections",
        "review.episode": "Episode…",
        "review.episode.tip": "Add an intro, a recitation and an outro around this lecture.",
        "review.episode_on": "Episode: on",
        "review.episode_written": "The episode was written too: \u2068{name}\u2069",
        "review.remove": "Remove selected",
        "review.remove_none": "Select a row to remove.",
        "review.play": "Play",
        "review.pause": "Pause",
        "review.rate": "{rate:g}×",
        "review.zoom": "Zoom",
        "review.studied_surah": "Surah on the cards",
        "review.studied_surah.tip": (
            "The ayah cards show only this surah; ayat quoted from other surahs stay "
            "in the subtitles."
        ),
        "review.show_ayah": "Show ayah… from here",
        "review.show_ayah.tip": (
            "From the playhead on, the card shows the ayat you choose, until the next card."
        ),
        "review.studied_surah_missing": (
            "No ayah of the chosen surah ({surah}) was found, so the video shows only "
            "its opening title card."
        ),
        "review.snap": "Snap to playhead",
        "review.minus": "−50 ms",
        "review.plus": "+50 ms",
        "review.no_selection": "Select a word to retime it",
        # The word is isolated here too: a Quran word leading the line would
        # otherwise lay it out right to left and reverse the two times.
        "review.selected": "\u2068{word}\u2069  {span}",
        "review.gaps": {
            "one": "{count} stretch of speech has no word:",
            "other": "{count} stretches of speech have no word:",
        },
        "review.gap": "{duration:.1f} s at {span}",
        "review.jump": "Jump",
        "review.covered": "Every stretch of speech is covered by a word.",
        "review.checking": "Checking the recording for speech with no word…",
        "review.more_gaps": {"one": "…and {count} more", "other": "…and {count} more"},
        "review.audio_missing": "The recording is not where the project says: {path}",
        "review.save_failed": "The corrections were not saved: {details}",
        "review.discard_title": "Save your corrections?",
        "review.discard_text": "This review has changes that are not saved.",
        "review.shortcuts": (
            "Space plays · ← next word, → previous · [ ] set start/end at the playhead · "
            ", . nudge the edge left/right 50 ms (Shift: 10 ms) · "
            "Shift-drag ripples the later words · "
            "Ctrl-drag an edge to part two words · Ctrl+Z undoes"
        ),
        "review.tip": "{action} ({keys})",
        "review.tip_fine": "{action} ({keys}; with Shift: 10 ms)",
        "review.key_space": "Space",
        "review.span": {"one": "{count} s shown", "other": "{count} s shown"},
        "review.span_minutes": "{minutes}:{seconds} shown",
        "review.zoom_in": "Zoom in",
        "review.zoom_out": "Zoom out",
        "review.fit": "Fit",
        "review.actual_size": "Actual size",
        "review.prev_word": "Previous word",
        "review.next_word": "Next word",
        "review.rate_label": "Speed",
        "review.help": "Shortcuts (?)",
        "review.hint": 'Space plays · ← → words · [ ] set start/end · <a href="shortcuts">? all shortcuts</a>',
        "review.shortcuts.title": "Shortcuts",
        "review.shortcuts.playback": "Playback",
        "review.shortcuts.editing": "Editing",
        "review.shortcuts.file": "File",
        "review.key.play": "Play or pause",
        "review.key.next_word": "Next word (later)",
        "review.key.prev_word": "Previous word (earlier)",
        "review.key.scrub": "Seek: click or drag the waveform or the ruler",
        "review.key.set_start": "Set the selected word's start at the playhead",
        "review.key.set_end": "Set the selected word's end at the playhead",
        "review.key.nudge_later": "Nudge the edge later by 50 ms",
        "review.key.nudge_earlier": "Nudge the edge earlier by 50 ms",
        "review.key.nudge_fine": "With Shift: 10 ms",
        "review.key.ripple": "Shift-drag a word: ripple the later words",
        "review.key.detach": "Ctrl-drag an edge: part two words",
        "review.key.change_ayah": "Double-click an Ayah cell: change the ayah",
        "review.key.undo": "Undo",
        "review.key.redo": "Redo",
        "review.key.save": "Save",
        "review.key.sheet": "This sheet",
        "review.gaps_toggle": {
            "one": "{count} stretch of speech has no word",
            "other": "{count} stretches of speech have no word",
        },
        "review.full_frame": "Show the frame full size (double-click)",
        "render.done_banner": "Rendered \u2068{name}\u2069",
        "render.done_banner_timed": "Rendered \u2068{name}\u2069 · {duration}",
        "render.play": "Play",
        "render.play_failed": "Could not open the video with your player.",
        "banner.dismiss": "Dismiss",
        "export.title": "Export subtitles",
        "export.formats": "Formats",
        "export.folder": "Folder",
        "export.choose": "Choose…",
        "export.name": "File name",
        "export.match_video": "Match the rendered video (includes the basmala at the start)",
        "export.match_video_stale": (
            "Match the rendered video (includes the basmala at the start)"
            " — rendered before your latest changes"
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
        "render.running_lecture": "Lecture — {percent}%",
        "render.running_intro": "Intro — {percent}%",
        "render.running_outro": "Outro — {percent}%",
        "render.running_recitation": "Recitation — {percent}%",
        "render.running_join": "Joining — {percent}%",
        "render.done": "The video is ready: {path}",
        "render.show": "Show the video",
        "render.failed": "The render did not finish: {details}",
        "render.cancelled": "Rendering stopped.",
        "render.cancel": "Cancel",
        "session.card_follows_words": (
            "This card's times follow its words; retime the words instead."
        ),
        "session.manual_lecture_only": "Ayah cards can only be placed by hand in a lecture.",
        "session.episode_lecture_only": "Only a lecture can have an intro, a recitation and an outro.",
        "session.manual_bad_reference": "Surah {surah} has no ayat {first}–{last}.",
        "session.manual_store_unavailable": (
            "Could not read the Quran store, so no ayah card was made: {details}"
        ),
        "session.no_file": "This project has no file to write back to.",
        "ayah_picker.title": "Choose the ayat for this card",
        "ayah_picker.surah": "Surah",
        "ayah_picker.from": "From ayah",
        "ayah_picker.to": "To ayah",
        "ayah_picker.more": {"one": "…and {count} more", "other": "…and {count} more"},
        "ayah_picker.no_store": "The Quran text is not ready yet, so no ayah can be chosen.",
        "look.title": "Look",
        "look.palette": "Palette",
        "look.preset.night_gold": "Night gold",
        "look.preset.emerald": "Emerald",
        "look.preset.sand": "Sand",
        "look.preset.ink_on_paper": "Ink on paper",
        "look.preset.ocean": "Ocean",
        "look.preset.rose": "Rose",
        "look.custom_from": "Custom (from {name})",
        "look.customise": "Customise",
        "look.colour.body_text": "Ayah text",
        "look.colour.highlight_word": "Highlighted word",
        "look.colour.header_text": "Surah title",
        "look.colour.card": "Card",
        "look.colour.caption_text": "Caption text",
        "look.colour.caption_active": "Caption, word being spoken",
        "look.colour.placeholder_text": "Opening text",
        "look.colour.background": "Background colour",
        "look.card_opacity": "Card opacity",
        "look.background": "Background",
        "look.bg.solid": "Solid colour",
        "look.bg.gradient": "Gradient",
        "look.bg.pattern_stars": "Stars pattern",
        "look.bg.pattern_lattice": "Lattice pattern",
        "look.bg.pattern_arches": "Arches pattern",
        "look.bg.image": "My image",
        "look.choose_image": "Choose image…",
        "look.dim": "Dim",
        "look.blur": "Blur",
        "look.low_contrast": "Hard to read: {parts}",
        "look.use_for_new": "Use for new videos",
        "look.default_saved": "New videos will start with this look.",
        "look.reset": "Reset",
        "look.image_failed": "\u2068{name}\u2069 could not be used as a background.",
        "look.image_missing": (
            "The background image is missing; the palette's background is shown instead."
        ),
        "look.image_unreadable": (
            "The background image could not be read; the palette's background is shown instead."
        ),
        # The episode: intro, recitation, lecture and outro joined into one video.
        "episode.error.missing": (
            "The clip \u2068{name}\u2069 is missing, so the episode was not made."
        ),
        "episode.error.not_video": (
            "\u2068{name}\u2069 is not a video Qalun can read, so the episode was not made."
        ),
        "episode.error.recitation": "The recitation job could not be used: {reason}",
        "episode.error.ffmpeg": "Joining the episode failed: {reason}",
        "episode.error.subtitles": (
            "The episode was made, but its subtitle files could not be written: {reason}"
        ),
        "episode.error.part_missing": "The {part} clip is missing, so the episode was not made.",
        "episode.error.part_not_video": (
            "The {part} clip is not a video Qalun can read, so the episode was not made."
        ),
        "episode.error.cancelled": "The episode was cancelled; the lecture video is kept.",
        "episode.error.generate": "The {part} could not be made, so the episode was not made.",
        "episode.error.generate_empty": (
            "The generated {part} has no words and no link to show, so the episode was not "
            "made. Give it a name or a phrase in the Episode dialog."
        ),
        "episode.error.qr_too_big": (
            "The outro's link is too long for a QR code phones can read in a {size} video, "
            "so the episode was not made. Shorten the link."
        ),
        "episode.error.recitation_changed": (
            "The recitation's video \u2068{name}\u2069 was rendered again while the episode "
            "was being made, so the episode was not made. Render again to use the new one."
        ),
        "episode.error.locked": (
            "\u2068{name}\u2069 could not be replaced: it may be open in another program, "
            "such as a video player. Close it and render again."
        ),
        "episode.part.intro": "intro",
        "episode.part.outro": "outro",
        "episode.seed.missing": (
            "The default {part} clip is missing, so this lecture starts without it."
        ),
        "episode.seed.failed": (
            "The default {part} clip could not be copied beside this lecture, "
            "so it starts without it."
        ),
        "episode.title": "Episode",
        "episode.intro": "Intro",
        "episode.recitation": "Recitation",
        "episode.outro": "Outro",
        "episode.none": "None",
        "episode.choose": "Choose…",
        "episode.remove": "Remove",
        "episode.rendered": "rendered",
        "episode.render_first": "will be rendered first",
        "episode.damaged": "damaged",
        "episode.total": "Total length: {length}",
        "episode.defaults_hint": "Changes you make here also become the default for new lectures.",
        "episode.unknown": "?",
        "episode.clip": "\u2068{name}\u2069 · {length}",
        "episode.recitation_entry": "\u2068{name}\u2069 · {range} · {status}",
        "episode.recitation_entry_no_range": "\u2068{name}\u2069 · {status}",
        "episode.clip_filter": "Video clips",
        "episode.clip_missing": "The {part} clip is missing: choose it again, or remove it.",
        "episode.copy_failed": "The clip could not be copied beside the job: {reason}",
        "episode.default_failed": (
            "The episode is set, but it could not be kept for new lectures: {reason}"
        ),
        "episode.kind.none": "None",
        "episode.kind.clip": "My clip",
        "episode.kind.generated": "Generated",
        "episode.gen.name": "Name",
        "episode.gen.title": "Title",
        "episode.gen.style": "Style",
        "episode.gen.style.fade": "Fade",
        "episode.gen.style.rise": "Rise",
        "episode.gen.style.reveal": "Reveal",
        "episode.gen.seconds": "Length (s)",
        "episode.gen.phrase": "Closing phrase",
        "episode.gen.custom": "Custom…",
        "episode.gen.link": "Link",
        "episode.gen.platform": "Publishing on",
        "episode.gen.tracked": "Link in the QR code",
        "episode.gen.tracked.tip": (
            "The link the QR code opens, with tracking that says the visit came from this "
            "video's QR code on this platform."
        ),
        "episode.gen.copy": "Copy",
        "episode.gen.copy.tip": (
            "Copy the link for the video's description: the same link, marked as the "
            "description's, so its clicks are counted apart from the QR code's scans. "
            "Copy it once the lecture's cards are final: they name its campaign."
        ),
        "episode.gen.readable": "Written under the code: {link}",
        "episode.gen.readable.tip": (
            "The address viewers can type. It has no tracking, so typed visits show as "
            "direct traffic, apart from the QR code's and the description's visits."
        ),
        "episode.gen.empty_intro": (
            "The intro has nothing to show: give it a name (this lecture's cards name no surah)."
        ),
        "episode.gen.empty_outro": (
            "The outro has nothing to show: choose a closing phrase or give a link."
        ),
        "episode.link_warning.mixed": (
            "This address mixes alphabets in one name, like a Cyrillic letter among Latin "
            "ones: it could pass for another site. Check it."
        ),
        "episode.link_warning.confusable": (
            "This address is written in letters that look Latin but are not: it could pass "
            "for another site. Check it."
        ),
        "episode.gen.qr_too_big": (
            "This link is too long for a QR code phones can read in a {size} video. "
            "Shorten it, or the episode will not be made."
        ),
        "episode.gen.missing_glyphs": (
            "The title font cannot draw \u2068{chars}\u2069: these would show as empty boxes."
        ),
        "episode.link_invalid": "Enter a web address starting with http:// or https://.",
        "episode.link_invalid.spaces": ("A link cannot have spaces or invisible characters in it."),
        "episode.link_invalid.slashes": ("Start the link with https:// — a colon and two slashes."),
        "episode.link_invalid.userinfo": (
            "A link with a user name or password cannot go in a video."
        ),
        "episode.link_invalid.host": (
            "This is not a web address: check the site's name, like example.org."
        ),
        "episode.link_invalid.port": (
            "The port after the site's name must be a number from 1 to 65535."
        ),
        "platform.youtube": "YouTube",
        "platform.instagram": "Instagram",
        "platform.facebook": "Facebook",
        "platform.tiktok": "TikTok",
        "platform.telegram": "Telegram",
        "platform.whatsapp": "WhatsApp",
    },
    # Drafted for the first release; a native speaker must review every line
    # before it ships (spec §4). Keep the order and grouping of "en".
    # \u2066…\u2069 isolates keep Latin and number runs left to right, and a leading
    # \u200f (RLM) makes a line of only values read right to left; they must be kept.
    "ar": {
        "home.jobs": "مهامك",
        "home.refresh": "حدِّث",
        "home.mode.recitation": "تلاوة",
        "home.mode.lecture": "محاضرة",
        "home.cards": {
            "zero": "لا بطاقات",
            "one": "بطاقة واحدة",
            "two": "بطاقتان",
            "few": "{count} بطاقات",
            "many": "{count} بطاقة",
            "other": "{count} بطاقة",
        },
        "home.status.needs_review": "بحاجة إلى مراجعة",
        "home.status.reviewed": "تمت المراجعة",
        "home.status.rendered": "تم إخراج الفيديو",
        "home.status.changed_since_render": "عُدِّلت بعد إخراج الفيديو",
        "home.status.damaged": "تالفة",
        # Only values and marks: the RLM makes the line right to left, else it
        # would be laid out left to right with the mode on the left.
        "home.running_row": "\u200f{name} — {progress}",
        "home.open": "افتح",
        "home.show_in_folder": "اعرض في المجلد",
        "home.remove_from_list": "أزِل من القائمة",
        "home.reading": "جارٍ قراءة مهامك…",
        "home.new_job": "مهمة جديدة",
        "home.drop": "أفلِت ملفًا صوتيًا هنا، أو اختر واحدًا",
        "home.choose": "اختر…",
        "home.choose_audio.dialog_title": "اختر ملفًا صوتيًا",
        "home.surah": "السورة",
        "home.surah_item": {
            "zero": "{num}. {name}  (لا آيات)",
            "one": "{num}. {name}  (آية واحدة)",
            "two": "{num}. {name}  (آيتان)",
            "few": "{num}. {name}  ({count} آيات)",
            "many": "{num}. {name}  ({count} آية)",
            "other": "{num}. {name}  ({count} آية)",
        },
        "surah.detect": "تحديد تلقائي",
        # Only values: the RLM lays the item out right to left, number first.
        "surah.item": "\u200f{num}. {name}",
        "surah.number": "سورة {num}",
        "home.studied_surah.tip": (
            "لا تعرض بطاقات الآيات إلا هذه السورة، وتبقى الآيات المستشهد بها من سور "
            "أخرى في الترجمة النصية. التحديد التلقائي يختار السورة الأطول سماعًا."
        ),
        "home.filter.audio": "ملفات الصوت والفيديو",
        "home.filter.text": "ملفات نصية",
        "home.filter.all": "كل الملفات",
        "home.range": "الآيات",
        "home.range_from": "من",
        "home.range_to": "إلى",
        "home.video_size": "مقاس الفيديو",
        "preset.social": "عمودي \u20661080×1920\u2069 · 30 إطارًا/ث",
        "preset.high": "أفقي \u20661920×1080\u2069 · 30 إطارًا/ث",
        "preset.standard": "أفقي \u20661280×720\u2069 · 25 إطارًا/ث",
        "preset.fast": "مسودة سريعة \u2066960×540\u2069 · 24 إطارًا/ث",
        "home.more": "خيارات أخرى",
        "home.quran_missing": "اختر ملف نص القرآن أولًا",
        "home.quran_store_error": "تعذّرت قراءة قاعدة بيانات القرآن: {details}",
        "home.quran_text": "نص القرآن",
        "home.output_dir": "مجلد الحفظ",
        "home.subtitles": "الترجمة النصية",
        # \u2066…\u2069 keep the variable, ".env" and "WhisperX" in one left-to-right
        # run each: the "=…" and the leading dot would otherwise move to the far side.
        "home.engine": "التفريغ",
        "home.engine.local": "على هذا الحاسوب",
        "home.engine.whisperx": "\u2066WhisperX\u2069 عبر الإنترنت (يتطلّب رمز Replicate)",
        "home.engine.no_token": (
            "لم يُضبط رمز Replicate. ضع السطر \u2066REPLICATE_API_TOKEN=…\u2069 في ملف "
            "باسم \u2066.env\u2069 داخل {folder}، ثم أعد تشغيل Qalun."
        ),
        "home.formats": "الملفات",
        "home.quran_override.default": "النص الموثَّق المرفق مع Qalun",
        "home.quran_override.custom": "\u200f{path}",
        "home.quran_override.reset": "استخدم النص المرفق",
        "home.quran_override.dialog_title": "اختر ملف نص القرآن",
        "home.output_dir.default": "الموضع الافتراضي",
        "home.output_dir.custom": "\u200f{path}",
        "home.output_dir.reset": "الافتراضي",
        "home.output_dir.dialog_title": "اختر مجلد الحفظ",
        "home.subtitles.burn": "مدمجة في الصورة",
        "home.subtitles.sidecar": "ملفات بجانب الفيديو",
        "home.subtitles.both": "كلاهما",
        "format.srt": "SRT",
        "format.vtt": "VTT",
        "format.ass": "ASS",
        "home.render_right_away": "أخرِج الفيديو مباشرةً (دون مراجعة)",
        "home.start": "ابدأ",
        "home.cancel": "إلغاء",
        "job.need_audio": "اختر ملفًا صوتيًا.",
        "job.need_quran": "اختر ملف نص القرآن.",
        "job.need_range": "اختر السورة ونطاق الآيات.",
        "job.bad_range": "لا يمكن أن تسبق الآيةُ الأخيرة الآيةَ الأولى.",
        "job.need_format": "اختر صيغة واحدة على الأقل للترجمة النصية.",
        "job.progress.aligning": "جارٍ مطابقة التلاوة مع الآيات التي اخترتها…",
        "job.progress.detecting": "جارٍ البحث عن القرآن في التسجيل…",
        "job.progress.kept": "أُبقيت تصحيحاتك السابقة في {name}",
        "job.stage.download": f"جارٍ تنزيل نموذج التعرّف على الكلام، مرة واحدة فقط (نحو {_MODEL_MB} ميغابايت)…",
        "job.stage.unpack": "جارٍ فكّ نموذج التعرّف على الكلام والتحقق منه…",
        "job.stage.transcribe": "جارٍ تفريغ الصوت على هذا الحاسوب…",
        "job.stage.transcribe_online": "جارٍ تفريغ الصوت باستخدام \u2066WhisperX\u2069 عبر الإنترنت…",
        "job.stage.detect": "جارٍ مطابقة التسجيل مع نص القرآن…",
        "job.stage.match": "جارٍ البحث عن الاستشهادات القرآنية في المحاضرة…",
        "job.stage.render": "جارٍ إخراج الفيديو…",
        "job.stage.export": "جارٍ كتابة ملفات الترجمة النصية…",
        "job.stage.working": "جارٍ العمل…",
        "job.stage.episode_lecture": "إخراج الدرس…",
        "job.stage.episode_intro": "جارٍ إعداد المقدمة…",
        "job.stage.episode_outro": "جارٍ إعداد الخاتمة…",
        "job.stage.episode_recitation": "تجهيز التلاوة للحلقة…",
        "job.stage.episode_join": "تجميع الحلقة…",
        "app.title": "Qalun",
        "home.progress.starting": "جارٍ البدء…",
        "home.progress.stopping": "جارٍ الإيقاف…",
        "home.progress.matching": "المطابقة — \u2066{percent}%\u2069",
        "home.progress.matching_eta": "المطابقة — \u2066{percent}%\u2069، يتبقى نحو {eta}",
        "home.progress.downloading": "تنزيل نموذج التعرّف على الكلام — \u2066{percent}%\u2069",
        "home.progress.downloading_eta": "تنزيل نموذج التعرّف على الكلام — \u2066{percent}%\u2069، يتبقى نحو {eta}",
        "home.progress.transcribing": "تفريغ الصوت — \u2066{percent}%\u2069",
        "home.progress.transcribing_eta": "تفريغ الصوت — \u2066{percent}%\u2069، يتبقى نحو {eta}",
        "home.progress.rendering": "إخراج الفيديو — \u2066{percent}%\u2069",
        "home.progress.rendering_eta": "إخراج الفيديو — \u2066{percent}%\u2069، يتبقى نحو {eta}",
        "home.progress.episode_lecture": "إخراج الدرس — \u2066{percent}%\u2069",
        "home.progress.episode_lecture_eta": "إخراج الدرس — \u2066{percent}%\u2069، يتبقى نحو {eta}",
        "home.progress.episode_intro": "إعداد المقدمة — \u2066{percent}%\u2069",
        "home.progress.episode_intro_eta": "إعداد المقدمة — \u2066{percent}%\u2069، يتبقى نحو {eta}",
        "home.progress.episode_outro": "إعداد الخاتمة — \u2066{percent}%\u2069",
        "home.progress.episode_outro_eta": "إعداد الخاتمة — \u2066{percent}%\u2069، يتبقى نحو {eta}",
        "home.progress.episode_recitation": "إخراج التلاوة — \u2066{percent}%\u2069",
        "home.progress.episode_recitation_eta": (
            "إخراج التلاوة — \u2066{percent}%\u2069، يتبقى نحو {eta}"
        ),
        "home.progress.episode_join": "تجميع الحلقة — \u2066{percent}%\u2069",
        "home.progress.episode_join_eta": "تجميع الحلقة — \u2066{percent}%\u2069، يتبقى نحو {eta}",
        "home.eta.seconds": "{seconds} ث",
        "home.eta.minutes": "{minutes} د {seconds} ث",
        "home.finished.matched": {
            "zero": "لم تتم مطابقة أي بطاقة. المراجعة مفتوحة.",
            "one": "تمت مطابقة بطاقة واحدة. المراجعة مفتوحة.",
            "two": "تمت مطابقة بطاقتين. المراجعة مفتوحة.",
            "few": "تمت مطابقة {count} بطاقات. المراجعة مفتوحة.",
            "many": "تمت مطابقة {count} بطاقة. المراجعة مفتوحة.",
            "other": "تمت مطابقة {count} بطاقة. المراجعة مفتوحة.",
        },
        "home.finished.rendered": "حُفظ الفيديو في {path}",
        "home.failed": "لم تكتمل العملية: {details}",
        "home.failed.title": "لم تكتمل العملية",
        "home.cancelled": "توقفت العملية قبل أن تكتمل.",
        "home.damaged": "لا يمكن فتح هذه المهمة: {details}",
        "home.close_review_first": "أغلق مراجعة هذه المهمة قبل تشغيلها مرة أخرى.",
        "home.busy_matching": "هذه المهمة قيد التشغيل مرة أخرى؛ افتح مراجعتها بعد أن تنتهي.",
        "home.review_failed": "تعذّر فتح {name} للمراجعة: {details}",
        "home.language": "اللغة",
        "home.theme": "المظهر",
        "home.theme.system": "حسب النظام",
        "home.theme.light": "فاتح",
        "home.theme.dark": "داكن",
        "home.language_busy": "أغلق المراجعات المفتوحة وانتظر انتهاء المهمة قبل تغيير اللغة.",
        "home.open_log_folder": "افتح مجلد السجلات",
        "home.open_log_folder.tip": "حيث يدوّن قالون ما حدث من أخطاء: {path}",
        "home.open_log_failed": "تعذّر فتح مجلد السجلات {path}.",
        "home.header.theme_to_dark": "بدِّل إلى المظهر الداكن",
        "home.header.theme_to_light": "بدِّل إلى المظهر الفاتح",
        "home.header.settings": "الإعدادات",
        "home.header.help": "مساعدة",
        "home.help_failed": "تعذّر فتح صفحة المساعدة في المتصفح.",
        "home.mode.recitation.desc": "يوقّت آيات التلاوة كلمةً كلمة.",
        "home.mode.lecture.desc": "يجد الآيات المذكورة في المحاضرة ويعرضها في بطاقات.",
        "home.engine.note": "ينسخ الصوت عبر الإنترنت بواسطة \u2066WhisperX\u2069، وهذا يرفع التسجيل.",
        "home.engine.change": "غيِّر ذلك في الإعدادات",
        "home.empty.title": "لا مهام بعد",
        "home.empty.hint": "أفلت تسجيلًا على اليسار لتبدأ مهمة.",
        "home.detail": "\u200f{mode} · {scope}",
        "settings.title": "الإعدادات",
        "settings.tab.general": "عام",
        "settings.tab.transcription": "النسخ الصوتي",
        "settings.tab.files": "الملفات",
        "settings.tab.videos": "الفيديوهات",
        "settings.tab.about": "حول",
        "settings.job_dirs": "ابحث عن المهام أيضًا في",
        "settings.add_dir": "أضف مجلدًا…",
        "settings.add_dir.dialog_title": "اختر مجلدًا يحوي مهامًا",
        "settings.remove_dir": "أزل",
        "settings.look": "المظهر الافتراضي للفيديوهات الجديدة",
        "settings.look.based_on": "مبني على {preset}",
        "settings.look.reset": "أعد إلى ذهبي ليلي",
        "settings.episode": "الحلقة الافتراضية للمحاضرات الجديدة",
        "settings.episode.intro": "المقدمة",
        "settings.episode.outro": "الخاتمة",
        "settings.episode.none": "بلا",
        "settings.episode.generated": "مولَّدة",
        "settings.episode.clear": "امسح",
        "settings.version": "\u200fقالون {version}",
        "settings.notices": "إشعارات الطرف الثالث",
        "settings.notices.missing": "ملف الإشعارات ليس في هذه النسخة.",
        "settings.github": "قالون على GitHub",
        "settings.close": "أغلق",
        "main.saved": "حُفظت التصحيحات في {path}",
        "player.unavailable": "التشغيل غير متاح على هذا الجهاز: {details}",
        "player.unavailable_short": "التشغيل غير متاح: ثبّت PySide6-Addons لسماع التسجيل.",
        "waveform.reading": "جارٍ قراءة التسجيل…",
        "waveform.missing": "التسجيل غير متاح.",
        "frame.error": "تعذّر رسم الإطار: {details}",
        "segments.ref": "الآية",
        "segments.time": "الوقت",
        "segments.text": "النص",
        "segments.retimed": "كلمات أُعيد توقيتها",
        "segments.speech": "كلام",
        "segments.locked": "يُقرأ نص القرآن من قاعدة البيانات ولا يمكن تعديله هنا.",
        "segments.change_ayah": "غيّر الآية…",
        "segments.manual": "وُضعت يدويًا",
        "review.title": "مراجعة — {name}",
        "review.save": "احفظ",
        "review.undo": "تراجع",
        "review.redo": "إعادة",
        "review.mark_reviewed": "علِّم كمُراجَعة",
        "review.export": "صدِّر الترجمة النصية…",
        "review.render": "أخرِج الفيديو بالتصحيحات",
        "review.render.tip": "صدِّر الفيديو مع تصحيحاتك",
        "review.episode": "الحلقة…",
        "review.episode.tip": "أضف مقدمة وتلاوة وخاتمة حول هذا الدرس.",
        "review.episode_on": "الحلقة: مفعّلة",
        "review.episode_written": "كُتبت الحلقة أيضًا: \u2068{name}\u2069",
        "review.remove": "أزِل المحدد",
        "review.remove_none": "حدِّد صفًا لإزالته.",
        "review.play": "شغِّل",
        "review.pause": "أوقف مؤقتًا",
        "review.rate": "\u2066{rate:g}×\u2069",
        "review.zoom": "التكبير",
        "review.studied_surah": "السورة على البطاقات",
        "review.studied_surah.tip": (
            "لا تعرض بطاقات الآيات إلا هذه السورة، وتبقى الآيات المستشهد بها من سور "
            "أخرى في الترجمة النصية."
        ),
        "review.show_ayah": "اعرض آية… من هنا",
        "review.show_ayah.tip": (
            "من موضع التشغيل فصاعدًا تعرض البطاقة الآيات التي تختارها حتى البطاقة التالية."
        ),
        "review.studied_surah_missing": (
            "لم يُعثر على أي آية من السورة المختارة ({surah})، فلا يعرض الفيديو "
            "سوى بطاقة العنوان الافتتاحية."
        ),
        "review.snap": "اضبط على مؤشر التشغيل",
        "review.minus": "\u2066−50\u2069 م.ث",
        "review.plus": "\u2066+50\u2069 م.ث",
        "review.no_selection": "اختر كلمة لتعديل توقيتها",
        # Only values: the RLM lays the line out right to left, word first.
        "review.selected": "\u200f{word}  {span}",
        "review.gaps": {
            "zero": "لا مقاطع كلام لا تغطيها أي كلمة:",
            "one": "مقطع كلام واحد لا تغطيه أي كلمة:",
            "two": "مقطعا كلام لا تغطيهما أي كلمة:",
            "few": "{count} مقاطع كلام لا تغطيها أي كلمة:",
            "many": "{count} مقطع كلام لا تغطيه أي كلمة:",
            "other": "{count} مقطع كلام لا تغطيه أي كلمة:",
        },
        "review.gap": "{duration:.1f} ث عند {span}",
        "review.jump": "انتقل",
        "review.covered": "كل مقاطع الكلام تغطيها كلمات.",
        "review.checking": "جارٍ فحص التسجيل بحثًا عن كلام لا تغطيه أي كلمة…",
        "review.more_gaps": {
            "zero": "…ولا مقاطع أخرى",
            "one": "…ومقطع آخر",
            "two": "…ومقطعان آخران",
            "few": "…و{count} مقاطع أخرى",
            "many": "…و{count} مقطعًا آخر",
            "other": "…و{count} مقطع آخر",
        },
        "review.audio_missing": "التسجيل ليس في الموضع الذي يذكره المشروع: {path}",
        "review.save_failed": "لم تُحفظ التصحيحات: {details}",
        "review.discard_title": "هل تحفظ تصحيحاتك؟",
        "review.discard_text": "في هذه المراجعة تغييرات غير محفوظة.",
        "review.shortcuts": (
            "المسافة للتشغيل · \u2066←\u2069 للكلمة التالية و \u2066→\u2069 للسابقة · "
            "\u2066[ ]\u2069 للبداية/النهاية عند مؤشر التشغيل · "
            "\u2066,\u2069 لإزاحة الحافة يسارًا و \u2066.\u2069 يمينًا 50 م.ث (مع Shift: 10 م.ث) · "
            "اسحب مع Shift لإزاحة الكلمات التالية · "
            "اسحب حافة مع Ctrl لفصل كلمتين · Ctrl+Z للتراجع"
        ),
        "review.tip": "\u200f{action} ({keys})",
        "review.tip_fine": "{action} ({keys}؛ مع Shift: 10 م.ث)",
        "review.key_space": "المسافة",
        "review.span": {
            "zero": "\u200f{count} ث معروضة",
            "one": "\u200f{count} ث معروضة",
            "two": "\u200f{count} ث معروضة",
            "few": "\u200f{count} ث معروضة",
            "many": "\u200f{count} ث معروضة",
            "other": "\u200f{count} ث معروضة",
        },
        "review.span_minutes": "\u200f{minutes}:{seconds} معروضة",
        "review.zoom_in": "كبِّر",
        "review.zoom_out": "صغِّر",
        "review.fit": "ملاءمة",
        "review.actual_size": "الحجم الفعلي",
        "review.prev_word": "الكلمة السابقة",
        "review.next_word": "الكلمة التالية",
        "review.rate_label": "السرعة",
        "review.help": "الاختصارات (?)",
        "review.hint": 'المسافة للتشغيل · ← → للكلمات · [ ] للبداية/النهاية · <a href="shortcuts">? كل الاختصارات</a>',
        "review.shortcuts.title": "الاختصارات",
        "review.shortcuts.playback": "التشغيل",
        "review.shortcuts.editing": "التحرير",
        "review.shortcuts.file": "الملف",
        "review.key.play": "تشغيل أو إيقاف مؤقت",
        "review.key.next_word": "الكلمة التالية (لاحقًا)",
        "review.key.prev_word": "الكلمة السابقة (سابقًا)",
        "review.key.scrub": "الانتقال: انقر أو اسحب على الموجة أو المسطرة",
        "review.key.set_start": "اضبط بداية الكلمة المحددة عند مؤشر التشغيل",
        "review.key.set_end": "اضبط نهاية الكلمة المحددة عند مؤشر التشغيل",
        "review.key.nudge_later": "أزح الحافة لاحقًا بمقدار 50 م.ث",
        "review.key.nudge_earlier": "أزح الحافة سابقًا بمقدار 50 م.ث",
        "review.key.nudge_fine": "مع Shift: 10 م.ث",
        "review.key.ripple": "اسحب كلمة مع Shift: إزاحة الكلمات التالية",
        "review.key.detach": "اسحب حافة مع Ctrl: فصل كلمتين",
        "review.key.change_ayah": "انقر نقرًا مزدوجًا على خلية الآية: غيِّر الآية",
        "review.key.undo": "تراجع",
        "review.key.redo": "إعادة",
        "review.key.save": "حفظ",
        "review.key.sheet": "هذه اللوحة",
        "review.gaps_toggle": {
            "zero": "لا مقاطع كلام بلا كلمة",
            "one": "مقطع كلام واحد بلا كلمة",
            "two": "مقطعا كلام بلا كلمة",
            "few": "\u200f{count} مقاطع كلام بلا كلمة",
            "many": "\u200f{count} مقطع كلام بلا كلمة",
            "other": "\u200f{count} مقطع كلام بلا كلمة",
        },
        "review.full_frame": "اعرض الإطار بالحجم الكامل (نقر مزدوج)",
        "render.done_banner": "أُخرج \u2068{name}\u2069",
        "render.done_banner_timed": "أُخرج \u2068{name}\u2069 · {duration}",
        "render.play": "شغِّل",
        "render.play_failed": "تعذّر فتح الفيديو بمشغّلك.",
        "banner.dismiss": "أخفِ",
        "export.title": "تصدير الترجمة النصية",
        "export.formats": "الصيغ",
        "export.folder": "المجلد",
        "export.choose": "اختر…",
        "export.name": "اسم الملف",
        "export.match_video": "طابِق الفيديو المُخرَج (يتضمن البسملة في بدايته)",
        "export.match_video_stale": (
            "طابِق الفيديو المُخرَج (يتضمن البسملة في بدايته) — أُخرِج قبل آخر تغييراتك"
        ),
        "export.match_audio": "طابِق التسجيل الأصلي",
        "export.go": "صدِّر",
        "export.done": {
            "zero": "لم يُكتب أي ملف: {names}",
            "one": "كُتب ملف واحد: {names}",
            "two": "كُتب ملفان: {names}",
            "few": "كُتبت {count} ملفات: {names}",
            "many": "كُتب {count} ملفًا: {names}",
            "other": "كُتب {count} ملف: {names}",
        },
        "export.show": "اعرض في المجلد",
        "export.none_chosen": "اختر صيغة واحدة على الأقل.",
        "export.no_name": "أدخل اسمًا للملف.",
        "export.failed": "لم تُكتب الترجمة النصية: {details}",
        "export.close": "إغلاق",
        "render.running": "إخراج الفيديو — \u2066{percent}%\u2069",
        "render.running_lecture": "الدرس — \u2066{percent}%\u2069",
        "render.running_intro": "المقدمة — \u2066{percent}%\u2069",
        "render.running_outro": "الخاتمة — \u2066{percent}%\u2069",
        "render.running_recitation": "التلاوة — \u2066{percent}%\u2069",
        "render.running_join": "التجميع — \u2066{percent}%\u2069",
        "render.done": "الفيديو جاهز: {path}",
        "render.show": "اعرض الفيديو",
        "render.failed": "لم يكتمل إخراج الفيديو: {details}",
        "render.cancelled": "توقف إخراج الفيديو.",
        "render.cancel": "إلغاء",
        "session.card_follows_words": (
            "توقيت هذه البطاقة يتبع كلماتها؛ عدِّل توقيت الكلمات بدلًا منها."
        ),
        "session.manual_lecture_only": "لا تُضاف بطاقات الآيات يدويًا إلا في الدروس.",
        "session.episode_lecture_only": "لا تكون المقدمة والتلاوة والخاتمة إلا للدروس.",
        "session.manual_bad_reference": "لا تضمّ السورة {surah} الآيات {first}–{last}.",
        "session.manual_store_unavailable": (
            "تعذّرت قراءة قاعدة بيانات القرآن، فلم تُنشأ بطاقة الآية: {details}"
        ),
        "session.no_file": "ليس لهذا المشروع ملف يُحفظ فيه.",
        "ayah_picker.title": "اختر آيات هذه البطاقة",
        "ayah_picker.surah": "السورة",
        "ayah_picker.from": "من الآية",
        "ayah_picker.to": "إلى الآية",
        "ayah_picker.more": {
            "zero": "…ولا آيات أخرى",
            "one": "…وآية أخرى",
            "two": "…وآيتان أخريان",
            "few": "…و{count} آيات أخرى",
            "many": "…و{count} آية أخرى",
            "other": "…و{count} آية أخرى",
        },
        "ayah_picker.no_store": "نص القرآن غير جاهز بعد، فلا يمكن اختيار آية.",
        "look.title": "المظهر",
        "look.palette": "لوحة الألوان",
        "look.preset.night_gold": "ذهبي ليلي",
        "look.preset.emerald": "زمردي",
        "look.preset.sand": "رملي",
        "look.preset.ink_on_paper": "حبر على ورق",
        "look.preset.ocean": "محيطي",
        "look.preset.rose": "وردي",
        "look.custom_from": "مخصص (من {name})",
        "look.customise": "تخصيص",
        "look.colour.body_text": "نص الآية",
        "look.colour.highlight_word": "الكلمة المُبرزة",
        "look.colour.header_text": "عنوان السورة",
        "look.colour.card": "البطاقة",
        "look.colour.caption_text": "نص الترجمة النصية",
        "look.colour.caption_active": "الكلمة المنطوقة الآن",
        "look.colour.placeholder_text": "نص الافتتاح",
        "look.colour.background": "لون الخلفية",
        "look.card_opacity": "عتامة البطاقة",
        "look.background": "الخلفية",
        "look.bg.solid": "لون واحد",
        "look.bg.gradient": "تدرّج",
        "look.bg.pattern_stars": "نقش النجوم",
        "look.bg.pattern_lattice": "نقش الشبكة",
        "look.bg.pattern_arches": "نقش الأقواس",
        "look.bg.image": "صورتي",
        "look.choose_image": "اختر صورة…",
        "look.dim": "تعتيم",
        "look.blur": "تمويه",
        "look.low_contrast": "صعب القراءة: {parts}",
        "look.use_for_new": "استخدمه للمقاطع الجديدة",
        "look.default_saved": "ستبدأ المقاطع الجديدة بهذا المظهر.",
        "look.reset": "إعادة الضبط",
        "look.image_failed": "تعذّر استخدام \u2068{name}\u2069 خلفيةً.",
        "look.image_missing": "صورة الخلفية مفقودة؛ تُعرض خلفية اللوحة بدلًا منها.",
        "look.image_unreadable": "تعذّرت قراءة صورة الخلفية؛ تُعرض خلفية اللوحة بدلًا منها.",
        "episode.error.missing": "المقطع \u2068{name}\u2069 مفقود، فلم تُصنع الحلقة.",
        "episode.error.not_video": (
            "\u2068{name}\u2069 ليس فيديو يستطيع قالون قراءته، فلم تُصنع الحلقة."
        ),
        "episode.error.recitation": "تعذّر استخدام مهمة التلاوة: {reason}",
        "episode.error.ffmpeg": "فشل تجميع الحلقة: {reason}",
        "episode.error.subtitles": "صُنعت الحلقة، لكن تعذّرت كتابة ملفات ترجمتها النصية: {reason}",
        "episode.error.part_missing": "مقطع \u2068{part}\u2069 مفقود، فلم تُصنع الحلقة.",
        "episode.error.part_not_video": (
            "مقطع \u2068{part}\u2069 ليس فيديو يستطيع قالون قراءته، فلم تُصنع الحلقة."
        ),
        "episode.error.cancelled": "أُلغيت الحلقة، وبقي فيديو المحاضرة كما هو.",
        "episode.error.generate": "تعذّر إعداد {part}، فلم تُصنع الحلقة.",
        "episode.error.generate_empty": (
            "ليس في {part} المُعدّة كلمات ولا رابط تعرضه، فلم تُصنع الحلقة. "
            "أعطها اسمًا أو عبارة في نافذة الحلقة."
        ),
        "episode.error.qr_too_big": (
            "رابط الخاتمة أطول من أن تقرأ الهواتف رمز الاستجابة السريعة الخاص به "
            "في فيديو بحجم \u2066{size}\u2069، فلم تُصنع الحلقة. اختصر الرابط."
        ),
        "episode.error.recitation_changed": (
            "أُعيد إخراج فيديو التلاوة \u2068{name}\u2069 أثناء صنع الحلقة، فلم تُصنع الحلقة. "
            "أعد الإخراج لاستخدام الجديد."
        ),
        "episode.error.locked": (
            "تعذّر استبدال \u2068{name}\u2069: قد يكون مفتوحًا في برنامج آخر "
            "كمشغّل فيديو. أغلقه ثم أعد الإخراج."
        ),
        "episode.part.intro": "المقدمة",
        "episode.part.outro": "الخاتمة",
        "episode.seed.missing": (
            "مقطع \u2068{part}\u2069 الافتراضي مفقود، فتبدأ هذه المحاضرة بدونه."
        ),
        "episode.seed.failed": (
            "تعذّر نسخ مقطع \u2068{part}\u2069 الافتراضي بجانب هذه المحاضرة، فتبدأ بدونه."
        ),
        "episode.title": "الحلقة",
        "episode.intro": "المقدمة",
        "episode.recitation": "التلاوة",
        "episode.outro": "الخاتمة",
        "episode.none": "بدون",
        "episode.choose": "اختر…",
        "episode.remove": "أزل",
        "episode.rendered": "مُخرَجة",
        "episode.render_first": "ستُخرَج أولًا",
        "episode.damaged": "تالفة",
        "episode.total": "المدة الكاملة: {length}",
        "episode.defaults_hint": "ما تغيّره هنا يصبح أيضًا الافتراضي للدروس الجديدة.",
        "episode.unknown": "؟",
        "episode.clip": "\u200f\u2068{name}\u2069 · {length}",
        "episode.recitation_entry": "\u200f\u2068{name}\u2069 · {range} · {status}",
        "episode.recitation_entry_no_range": "\u200f\u2068{name}\u2069 · {status}",
        "episode.clip_filter": "مقاطع الفيديو",
        "episode.clip_missing": "مقطع \u2068{part}\u2069 مفقود: اختره من جديد أو أزله.",
        "episode.copy_failed": "تعذّر نسخ المقطع بجانب المهمة: {reason}",
        "episode.default_failed": "ضُبطت الحلقة، لكن تعذّر حفظها للدروس الجديدة: {reason}",
        "episode.kind.none": "بدون",
        "episode.kind.clip": "مقطعي",
        "episode.kind.generated": "مُولَّد",
        "episode.gen.name": "الاسم",
        "episode.gen.title": "العنوان",
        "episode.gen.style": "النمط",
        "episode.gen.style.fade": "تلاشٍ",
        "episode.gen.style.rise": "صعود",
        "episode.gen.style.reveal": "كشف",
        "episode.gen.seconds": "المدة (ث)",
        "episode.gen.phrase": "عبارة الختام",
        "episode.gen.custom": "عبارة أخرى…",
        "episode.gen.link": "الرابط",
        "episode.gen.platform": "النشر على",
        "episode.gen.tracked": "الرابط داخل رمز QR",
        "episode.gen.tracked.tip": (
            "الرابط الذي يفتحه رمز QR، ومعه تتبّع يبيّن أن الزيارة جاءت من رمز هذا الفيديو "
            "على هذه المنصة."
        ),
        "episode.gen.copy": "انسخ",
        "episode.gen.copy.tip": (
            "انسخ الرابط لوصف الفيديو: هو الرابط نفسه، معلَّمًا بأنه من الوصف، فتُحسب نقراته "
            "منفصلةً عن مسح رمز QR. انسخه بعد أن تستقر بطاقات الدرس، فهي تسمّي حملته."
        ),
        "episode.gen.readable": "يُكتب تحت الرمز: {link}",
        "episode.gen.readable.tip": (
            "العنوان الذي يستطيع المشاهد كتابته. ليس فيه تتبّع، فتظهر زياراته زياراتٍ مباشرة، "
            "منفصلةً عن زيارات الرمز وزيارات الوصف."
        ),
        "episode.gen.empty_intro": (
            "ليس في المقدمة ما تعرضه: أعطها اسمًا (فبطاقات هذا الدرس لا تذكر سورة)."
        ),
        "episode.gen.empty_outro": "ليس في الخاتمة ما تعرضه: اختر عبارة ختام أو أعطها رابطًا.",
        "episode.link_warning.mixed": (
            "يخلط هذا العنوان أبجديات في اسم واحد، كحرف كيريلي بين حروف لاتينية: "
            "قد يُظنّ موقعًا آخر. تحقّق منه."
        ),
        "episode.link_warning.confusable": (
            "هذا العنوان مكتوب بحروف تشبه اللاتينية وليست منها: قد يُظنّ موقعًا آخر. تحقّق منه."
        ),
        "episode.gen.qr_too_big": (
            "هذا الرابط أطول من أن تقرأ الهواتف رمز QR الخاص به في فيديو بحجم {size}. "
            "اختصره، وإلا فلن تُصنع الحلقة."
        ),
        "episode.gen.missing_glyphs": ("لا يستطيع خط العنوان رسم {chars}: ستظهر مربعاتٍ فارغة."),
        "episode.link_invalid": "أدخل عنوان ويب يبدأ بـ \u2066http://\u2069 أو \u2066https://\u2069.",
        "episode.link_invalid.spaces": "لا يصح أن يحوي الرابط مسافات أو محارف غير مرئية.",
        "episode.link_invalid.slashes": (
            "ابدأ الرابط بـ \u2066https://\u2069: نقطتان رأسيتان ثم شرطتان مائلتان."
        ),
        "episode.link_invalid.userinfo": ("لا يصح وضع رابط فيه اسم مستخدم أو كلمة مرور في فيديو."),
        "episode.link_invalid.host": (
            "هذا ليس عنوان ويب: تحقق من اسم الموقع، مثل \u2066example.org\u2069."
        ),
        "episode.link_invalid.port": (
            "يجب أن يكون المنفذ بعد اسم الموقع رقمًا من \u20661\u2069 إلى \u206665535\u2069."
        ),
        "platform.youtube": "يوتيوب",
        "platform.instagram": "إنستغرام",
        "platform.facebook": "فيسبوك",
        "platform.tiktok": "تيك توك",
        "platform.telegram": "تيليغرام",
        "platform.whatsapp": "واتساب",
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


def clock(seconds: float, *, digits: int = 2) -> str:
    """*seconds* as ``mm:ss.cc`` (``digits`` fraction digits), rounded once.

    One rounding of the whole value, so 59.999 reads ``01:00.00`` and never
    ``00:60.00``; a negative time reads as zero.
    """
    scale = 10**digits
    units = max(0, int(round(seconds * scale)))
    minutes, rest = divmod(units, 60 * scale)
    whole, fraction = divmod(rest, scale)
    return f"{minutes:02d}:{whole:02d}.{fraction:0{digits}d}"


def time_span(start: float, end: float, *, digits: int = 2, sep: str = "–") -> str:
    """Two times as one value, so a sentence in any language keeps them in order."""
    return f"{clock(start, digits=digits)}{sep}{clock(end, digits=digits)}"


def ltr(text: str) -> str:
    """*text* forced left to right inside right-to-left surroundings (a table cell of times)."""
    return f"{_LRI}{text}{_PDI}" if is_rtl() else text


def path_text(path: object) -> str:
    """*path* as one left-to-right run whose folders keep their order, in any language.

    An isolate alone is not enough: inside it, two Arabic folder names with a
    "/" between them merge into one right-to-left run and swap places
    ("/home/k/فيديو/تلاوة.mp4" read as ".../تلاوة/فيديو"). An LRM after each
    separator ends every folder's run at its separator. The same in every
    language, since an English sentence can hold an Arabic folder too.
    """
    text = "".join(c + _LRM if c in "/\\" else c for c in str(path))
    return f"{_LRI}{text}{_PDI}"


def _first_strong(text: str) -> str | None:
    """``"L"`` or ``"R"``: the direction of *text*'s first strong letter, as FSI reads it.

    Letters inside an isolate nested in *text* do not count, as in the Unicode
    bidi algorithm; None when there is no strong letter (a number, a time).
    """
    depth = 0
    for char in text:
        if char in (_FSI, _LRI, _RLI):
            depth += 1
        elif char == _PDI:
            depth = max(0, depth - 1)
        elif depth == 0:
            kind = unicodedata.bidirectional(char)
            if kind == "L":
                return "L"
            if kind in ("R", "AL"):
                return "R"
    return None


def plain_title(text: str) -> str:
    """*text* with its isolates turned into order marks, for a window's title bar.

    Some native title bars (older Windows and X11 window managers among them)
    predate the isolate controls and draw each one as a box. Each outermost
    FSI/LRI/RLI…PDI run becomes its content between two LRMs when it runs left
    to right (LRI, or FSI over Latin letters or none) or two RLMs when it runs
    right to left (RLI, or FSI over Arabic): marks every title bar has
    understood for decades. The mark after keeps a Latin name from pulling the
    Arabic words or the ``*`` after it into its run; the mark before keeps the
    Arabic words before it from turning a name's leading digits into Arabic
    numbers (UAX #9 W2), which drew "25_7-11" as "11-7_25". Order marks already
    in *text* stay, a stray PDI goes, and an isolate left open ends at the end
    of the text.
    """
    out: list[str] = []
    opener = ""  # the outermost open isolate
    start = 0  # where its content starts in *text*
    mark_at = 0  # where its content starts in *out*
    depth = 0

    def close(end: int) -> None:
        if opener == _LRI:
            direction = "L"
        elif opener == _RLI:
            direction = "R"
        else:
            direction = _first_strong(text[start:end]) or "L"
        mark = _RLM if direction == "R" else _LRM
        out.insert(mark_at, mark)
        out.append(mark)

    for index, char in enumerate(text):
        if char in (_FSI, _LRI, _RLI):
            if depth == 0:
                opener, start, mark_at = char, index + 1, len(out)
            depth += 1
        elif char == _PDI:
            if depth == 0:
                continue  # closes nothing
            depth -= 1
            if depth == 0:
                close(index)
        else:
            out.append(char)
    if depth:
        close(len(text))
    return "".join(out)

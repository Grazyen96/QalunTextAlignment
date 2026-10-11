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
        "home.row_detail": "{mode} · {scope} · {status}",
        # The name is isolated here too: an Arabic file name leading the line
        # would otherwise lay it out right to left.
        "home.running_row": "\u2068{name}\u2069 — {progress}",
        "home.open": "Open",
        "home.show_in_folder": "Show in folder",
        "home.remove_from_list": "Remove from list",
        "home.empty": "Your jobs appear here once you start one.",
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
        "home.engine.folded": "Transcription: WhisperX online, which uploads the recording.",
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
        "home.language_busy": (
            "Close the open reviews and wait for the job to finish before changing the language."
        ),
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
        "review.studied_surah": "Surah on the cards",
        "review.studied_surah.tip": (
            "The ayah cards show only this surah; ayat quoted from other surahs stay "
            "in the subtitles."
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
        "render.done": "The video is ready: {path}",
        "render.show": "Show the video",
        "render.failed": "The render did not finish: {details}",
        "render.cancelled": "Rendering stopped.",
        "render.cancel": "Cancel",
        "session.card_follows_words": (
            "This card's times follow its words; retime the words instead."
        ),
        "session.manual_lecture_only": "Ayah cards can only be placed by hand in a lecture.",
        "session.no_file": "This project has no file to write back to.",
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
        "home.row_detail": "\u200f{mode} · {scope} · {status}",
        "home.running_row": "\u200f{name} — {progress}",
        "home.open": "افتح",
        "home.show_in_folder": "اعرض في المجلد",
        "home.remove_from_list": "أزِل من القائمة",
        "home.empty": "تظهر مهامك هنا بعد أن تبدأ أول مهمة.",
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
        "home.engine.folded": "التفريغ: \u2066WhisperX\u2069 عبر الإنترنت، ويُرفَع التسجيل إليه.",
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
        "home.language_busy": "أغلق المراجعات المفتوحة وانتظر انتهاء المهمة قبل تغيير اللغة.",
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
        "review.title": "مراجعة — {name}",
        "review.save": "احفظ",
        "review.undo": "تراجع",
        "review.redo": "إعادة",
        "review.mark_reviewed": "علِّم كمُراجَعة",
        "review.export": "صدِّر الترجمة النصية…",
        "review.render": "أخرِج الفيديو بالتصحيحات",
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
        "render.done": "الفيديو جاهز: {path}",
        "render.show": "اعرض الفيديو",
        "render.failed": "لم يكتمل إخراج الفيديو: {details}",
        "render.cancelled": "توقف إخراج الفيديو.",
        "render.cancel": "إلغاء",
        "session.card_follows_words": (
            "توقيت هذه البطاقة يتبع كلماتها؛ عدِّل توقيت الكلمات بدلًا منها."
        ),
        "session.manual_lecture_only": "لا تُضاف بطاقات الآيات يدويًا إلا في الدروس.",
        "session.no_file": "ليس لهذا المشروع ملف يُحفظ فيه.",
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

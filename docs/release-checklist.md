# Release checklist

What a person has to check before tagging a release, because a machine here cannot.
Work top to bottom; stop at the first item that fails and fix it before going on.

## Before the first release: blocking

Each of these holds the first tag until it is done. Tick it once, with a note of
what was decided; later releases only re-check it when the thing it names changes.

- [ ] **Quran font and text: confirm their source and terms before the first tag.**
      `src/qurantext/assets/fonts/qaloon.10.ttf`, `qaloon.10.woff2` and
      `src/qurantext/assets/quran/UthmanicQaloon1-v10.txt` ship inside every app
      zip, the Python package and `qalun-source.zip`. The text's source is
      recorded (KFGQPC Qaloon v10, see `src/qurantext/assets/README.md`); its
      terms and the font's provenance are not, so `THIRD_PARTY_NOTICES.md`, the README, `pyproject.toml` and
      `src/qurantext/assets/README.md` keep them out of Qalun's GPL statement as
      "third-party works, provenance and terms to be confirmed by the owner". Find
      out where each came from and on what terms it may be redistributed, with an
      app and inside a source archive. Write the source and terms into the "Quran text and font"
      section of `THIRD_PARTY_NOTICES.md` and into `src/qurantext/assets/README.md`.
      If the terms do not allow redistribution, do not release until the files are
      replaced.
- [ ] **Licence review: source obligations for Qt (LGPL), FriBiDi (LGPL) and the GPL
      FFmpeg build.** `THIRD_PARTY_NOTICES.md` names them, but only espeak-ng and
      alsa-lib have their sources in the zips (`third-party-sources/`). The FFmpeg
      programs are GPL builds fetched as "latest" (gyan.dev or BtbN on Windows,
      Homebrew on macOS, johnvansickle.com or BtbN on Linux), so not even their
      version is fixed; Qt (with the FFmpeg libraries PySide6 ships) and FriBiDi are
      LGPL. On Linux the bundle also carries the build machine's system libraries.
      The owner decides, with legal advice if needed, what each requires and how
      the release meets it. Not resolved in the code.
- [ ] **Public download location.** The app repository is private: its Releases page,
      and every link to it (the UTM links and QR codes under Publish, and the
      README's "Releases page"), answers 404 to anyone without access. Public
      download links, and any UTM parameters or QR codes, must not point at the
      private repository's release page. The owner decides a public download
      location (for example a public releases-only repository, or a page with
      analytics that serves the zips), and the Publish links below are changed to
      it before anything is announced.
- [ ] **A Windows account whose name is in Arabic.** The speech model lives under the
      user's profile (`%LOCALAPPDATA%\qalun\…`), so for such a user its path is not
      ASCII, and CI only runs as `runneradmin`. On a real Windows machine, set
      `QURANTEXT_CACHE_DIR` to a folder whose name has Arabic letters (or use an
      account named in Arabic), start the packaged app, and run a recitation job on
      the default engine. The model must download, load and transcribe. If it fails
      with "the speech runtime itself could not start", the fix is to load the
      model from a short ASCII path.

## Version

- [ ] Set `__version__` in `src/qurantext/__init__.py` to the release's number (the
      tag without its `v`) and commit it before tagging. It is the one place the
      version is written: `pyproject.toml` reads it, `qalun --version` and the
      doctor report's first line say it, and the **Package** step fails on a tag
      that is not `v` followed by it.

## Build

- [ ] Actions → **Build the app** → **Run workflow**, on the commit you mean to tag.
- [ ] Every platform's gate step (**Check the built app can render**, which runs
      `--doctor --release` and then a local transcription) passes on Windows, macOS
      and Linux.
- [ ] In each platform's gate log, the transcription gate ends with `The built app
      transcribed on this computer: ... for a 5 s tone.` It proves the speech model
      loads and runs inside the app that ships. Before it, the line `The published
      model matches the pin: ...` proves, cache or not, that the `qalun-models`
      release still has the asset with the size and sha256 pinned in
      `model_store.py`. If it says `matches the pin by size` instead, GitHub gave no
      sha256 to compare; when the step **Keep the speech model between runs** found
      no cache, the line `QALUN-CI-MODEL-DOWNLOAD ...` shows the run downloaded and
      verified the asset itself. If the gate fails, it is usually a broken
      `qalun-models` asset, a checksum in `model_store.py` that no longer matches it,
      or a sherpa-onnx library missing from the bundle; see `packaging/ci/README.md`.
- [ ] In each platform's gate log, the Playback line says `through the FFmpeg backend,
      as QT_MEDIA_BACKEND asks`. Windows and macOS also ship a native backend, and only
      this line shows the recording did not play through that one instead.
- [ ] Record the Windows and macOS zip sizes (on the run's summary page) in the Size
      table in `packaging/README.md`. Compare each with that platform's zip from a build
      of `30a159c` (23 Sep 2026) or earlier: the one before `57fc739`, which is where
      Multimedia entered the bundle, because PyInstaller follows the player's import on
      its own. There are no `v*` tags, so there is no Release to compare with, and
      workflow artifacts expire after 30 days. If no such run survives, compare with
      Linux instead. Since then each zip has grown by three things: Multimedia (about
      20 MB on Linux), the speech engine (about 10 MB) and the sources now inside every
      zip (about 20 MB, nearly all espeak-ng's 18 MB archive; alsa-lib adds 1 MB to
      Linux only). So expect about 50 MB in all. If a zip grew far more than 60–70 MB,
      stop and find out why before releasing.
- [ ] Each zip has, at its top (beside `qalun.exe` or `qalun` in `qalun/`, and beside
      `Qalun.app` in the macOS zip): `THIRD_PARTY_NOTICES.md`, `LICENSE`,
      `qalun-source.zip` and `third-party-sources/`. Qalun is GPL-3.0-only because
      the bundled sherpa-onnx links espeak-ng (GPL-3.0-or-later) into the app's
      process (the "Licence finding" in `docs/findings/asr-bakeoff.md`), and the
      repository is private, so the source travels inside every app zip:
  - `qalun-source.zip` unzips to `qalun-source/` with `LICENSE` at its top, and its
    `src/qurantext/__init__.py` says the version being released.
  - `third-party-sources/` holds `espeak-ng-ed530aa1….zip` in every zip, and
    `alsa-lib-1.2.12.tar.bz2` in the Linux zip only, with `SOURCES.txt`. The
    **Package** step logs `matches the pin` for each; it fails on a sha256 that
    does not match `packaging/third-party-sources.txt`.
- [ ] Download `qalun-linux.zip` and unzip it with `unzip`. Check two things (the gate
      already checks that `libxcb-cursor.so.0` is in the bundle):
  - `find qalun -type l | wc -l` is not 0. If it is 0, the links were not kept: check
    that the **Package** step still runs `packaging/ci/package.sh`.
  - `du -sm qalun` is about 490 MB, FFmpeg and the sources included (measured 10 Oct
    2026). About 660 MB means the links were followed and every linked library is
    stored twice.
- [ ] Extract `qalun-linux.zip` once more with the desktop's own **Extract here** (or
      `unzip`), and start the app from that folder. Some extractors (Python's `zipfile`,
      a few minimal tools) write each stored link as a small text file, and the app then
      cannot find its Qt libraries. In the release notes, tell Linux users: "Extract with
      your file manager or `unzip`."

## By ear, on Windows, macOS and Linux

This is the spec's §6 manual check. Do it on all three: transcription now runs on
the machine, and the CI gate only proves the model loads (a tone has no words), so
this is the only place anyone hears each platform's build recognise speech.

- [ ] Open the packaged app. Do not use a checkout.
- [ ] Start a recitation job on `furquanTra7-11.mp3` (surah 25, ayat 7–11), on the
      default engine (On this computer). It is in `input/recitations/`, which is not
      in git. Check the words appear: the review must open on 25:7–11 with the
      recited words in it (about 60 or more), not an empty or near-empty transcript.
      On macOS (Apple silicon, its own ONNX Runtime build) this is the first time
      anyone sees that build recognise speech.
- [ ] In the review, play the recording. Find the late words at the end of 25:7, where
      speech runs uncovered from about 16.7 s to 24.2 s. Fix the rift by ear by rippling
      the late words.
- [ ] Save, then render.
- [ ] Check that the MP4 matches what the editor showed. Export an SRT and check that it
      matches too.
- [ ] On Linux, play the recording on a real desktop other than the build machine, for
      example a PipeWire desktop or a distribution other than Ubuntu. Sound must come out.
      The bundle carries the build runner's PulseAudio and libsndfile client libraries
      (`collect-linux.sh` installs them there), so the doctor's playback check on CI,
      which has no sound device, does not prove this.
- [ ] On Linux, start the window in an X11 session as well as a Wayland one.
- [ ] In the packaged app, open **Settings** (the gear in the header), go to the
      **About** tab and click the **Open log folder** link. The file manager must
      open the `logs` folder that `qalun --doctor` names on its "error log in" line,
      with `qalun.log` in it (and, on Linux and macOS, `faults.log`). The gate never
      opens the window, so it never makes this folder; only a real start does. The
      log can name the person's own files and folders: say so when asking for it.
- [ ] Press **Help** in the header, then the GitHub link in Settings → About. The
      browser must open the README and the project's page, each address carrying
      `utm_source=qalun-app&utm_medium=app` and `utm_campaign=help` or `about`
      (`config/links.py`). GitHub itself does not report these parameters: decide
      before release whether the links go through a redirect your analytics sees.
- [ ] On Windows, open two windows of the packaged app at once and make the log pass
      1 MB (for example, copy a 1 MB text file over `qalun.log` and fail a job in each
      window). Nothing may be lost: `qalun.log` keeps growing while both are open,
      `qalun.log.1` to `.3` stay as they were, and it rotates once one window has
      closed. Only a simulated refusal has been tested.

## Arabic, on a real desktop

- [ ] Switch the window to العربية.
- [ ] With an Arabic keyboard layout active, check that `[ ] , .` still set and nudge in
      the review. Do this on Windows and macOS as well as Linux: the key codes those two
      use have not been tried on real machines. Try it with the segment table not
      focused: while it has focus, an Arabic letter goes to the table instead, on purpose.
- [ ] Window title bars show no boxes.
- [ ] Qt's own buttons, in the file dialog and in Save/Discard, are in Arabic.
- [ ] On a machine without an Arabic font (a fresh Linux VM), the window still draws
      Arabic letters, using the bundled Quran font. Check that the result is readable.
      This has not been seen on a real machine yet.
- [ ] On macOS, after choosing a language, check that the settings file is at
      `~/Library/Preferences/com.qalun.Qalun.plist`, as `README.md` says.
- [ ] Run `QT_QPA_PLATFORM=offscreen venv/bin/python tools/screenshots.py output/shots` and
      look at every image in both themes and both languages: primary buttons filled,
      icons on the buttons the phase A spec lists (Start, Cancel, Close and the nudge
      buttons have none by design), nothing unreadable or cut off, including the Settings
      tabs and the empty first launch, and the review window's shortcut sheet and full-size preview.

## Words

- [ ] A native Arabic speaker reviews `STRINGS["ar"]` in `src/qurantext/gui/i18n.py`,
      in the running app, and edits the table in place. Start with the uncertain ones:
  - `review.mark_reviewed`, `review.snap` and `segments.retimed`
  - «م.ث» (milliseconds)
  - the Cancel and Close forms
  - `review.save` used as a dialog title
  - `home.reading`
  - the fourteen `job.stage.*` lines, among them `download`, `unpack`, `transcribe`,
    `transcribe_online` and the episode's two, `episode_recitation` («تجهيز التلاوة للحلقة…»)
    and `episode_join` («تجميع الحلقة…»): the other stage lines open with «جارٍ»; should
    these two as well?
  - the transcription choice and its progress: `home.engine`, `home.engine.local`,
    `home.engine.whisperx`, `home.engine.no_token`, the form's upload note
    `home.engine.note` and its link `home.engine.change`,
    `home.progress.downloading`, `home.progress.downloading_eta`,
    `home.progress.transcribing` and `home.progress.transcribing_eta`. The note says
    «ينسخ» where older lines say «التفريغ» for transcription: which should every line use?
  - the video header: «الآيات 7 - 11» or «الآيات من 7 إلى 11»
  - the Look panel, every `look.*` line, read beside the panel and its swatches: the
    palette names (`look.preset.*`: «ذهبي ليلي»، «زمردي»، «رملي»، «حبر على ورق»، «محيطي»،
    «وردي»), the colour names (`look.colour.*`, among them «نص الترجمة النصية», «الكلمة
    المنطوقة الآن», «نص الافتتاح» and the background colour picker «لون الخلفية»),
    `look.card_opacity` («عتامة البطاقة»), the backgrounds (`look.bg.*`),
    `look.dim` and `look.blur` («تعتيم»، «تمويه»), `look.use_for_new`, `look.reset`,
    `look.low_contrast`, and the image lines `look.image_failed`, `look.image_missing` and
    `look.image_unreadable`. A list of colour names in `look.low_contrast` is joined
    with «، ».
  - a lecture's studied surah, read on the new-job screen in lecture mode and in the
    review window's toolbar: `surah.detect` («تحديد تلقائي»: is «اكتشاف تلقائي» or
    «تلقائيًا» better?), `surah.number` («سورة 25»), `review.studied_surah` («السورة على
    البطاقات»), the two tooltips `home.studied_surah.tip` and `review.studied_surah.tip`
    («الآيات المستشهد بها»، «الأطول سماعًا»), and the warning
    `review.studied_surah_missing` («بطاقة العنوان الافتتاحية»).
  - hand-made ayah cards in a lecture, read in the review window (the button beside
    Play, the segment list) and the ayah picker: the button `review.show_ayah` («اعرض
    آية… من هنا») and its tooltip `review.show_ayah.tip` («من موضع التشغيل فصاعدًا»), the
    context-menu entry `segments.change_ayah` («غيّر الآية…»), the ✎ tooltip
    `segments.manual` («وُضعت يدويًا»), the picker's `ayah_picker.title`,
    `ayah_picker.surah`, `ayah_picker.from`, `ayah_picker.to`, the six plural forms of
    `ayah_picker.more` («…وآية أخرى»، «…وآيتان أخريان»، «…و3 آيات أخرى»، «…و15 آية
    أخرى», shown under a preview of more than five ayat) and `ayah_picker.no_store`, and the three
    errors `session.manual_lecture_only`, `session.manual_bad_reference` («لا تضمّ
    السورة 25 الآيات 1–99») and `session.manual_store_unavailable`.
  - the episode (intro, recitation, lecture and outro joined into one video), read where
    a lecture render reports it:
    - the errors `episode.error.missing` («المقطع … مفقود، فلم تُصنع الحلقة»),
      `episode.error.not_video`, `episode.error.recitation`, `episode.error.ffmpeg` («فشل
      تجميع الحلقة») and `episode.error.subtitles` («صُنعت الحلقة، لكن تعذّرت كتابة ملفات
      ترجمتها النصية»);
    - the errors that name a part, `episode.error.part_missing` («مقطع المقدمة مفقود، فلم
      تُصنع الحلقة») and `episode.error.part_not_video`, with the part names
      `episode.part.intro` («المقدمة») and `episode.part.outro` («الخاتمة»): are these the
      right words for an episode's opening and closing clips?
    - `episode.error.cancelled` («أُلغيت الحلقة، وبقي فيديو المحاضرة كما هو»);
    - the two notices a new lecture's default intro or outro can give,
      `episode.seed.missing` («مقطع المقدمة الافتراضي مفقود، فتبدأ هذه المحاضرة بدونه») and
      `episode.seed.failed`;
    - `episode.error.recitation_changed` («أُعيد إخراج فيديو التلاوة … أثناء صنع الحلقة») and
      `episode.error.locked` («تعذّر استبدال …: قد يكون مفتوحًا في برنامج آخر»);
    - the Episode dialog, read in a lecture's review: `episode.title` («الحلقة»),
      `episode.intro`, `episode.recitation` («التلاوة»), `episode.outro`, `episode.none`
      («بدون»), `episode.choose` («اختر…»), `episode.remove` («أزل»), the recitation states
      `episode.rendered` («مُخرَجة»), `episode.render_first` («ستُخرَج أولًا») and
      `episode.damaged` («تالفة»): do these agree with a recitation as feminine? They
      use the render verb «أخرِج / إخراج», as `review.render` does, and not «صدِّر», which is
      Export subtitles; is «مُخرَجة» natural here?
      `episode.total` («المدة الكاملة»), `episode.unknown` («؟»), `episode.clip_missing`
      («مقطع المقدمة مفقود: اختره من جديد أو أزله»), `episode.clip_filter`
      («مقاطع الفيديو»), `episode.copy_failed`, `episode.default_failed` («ضُبطت الحلقة،
      لكن تعذّر حفظها للدروس الجديدة») and `session.episode_lecture_only`;
    - in the review's toolbar: `review.episode` («الحلقة…»), its tooltip
      `review.episode.tip` («أضف مقدمة وتلاوة وخاتمة حول هذا الدرس»), `review.episode_on`
      («الحلقة: مفعّلة») and, after a render, `review.episode_written` («كُتبت الحلقة
      أيضًا»);
    - the lecture step's sentence `job.stage.episode_lecture` («إخراج الدرس…»);
    - the progress of each step: in the review's bar `render.running_lecture` («الدرس»),
      `render.running_recitation` («التلاوة») and `render.running_join` («التجميع»), and on
      the home window `home.progress.episode_lecture` («إخراج الدرس»),
      `home.progress.episode_recitation` («إخراج التلاوة») and
      `home.progress.episode_join` («تجميع الحلقة»), each with its `_eta` form.
    - the generated intro and outro, made during the render: the steps
      `job.stage.episode_intro` («جارٍ إعداد المقدمة…») and `job.stage.episode_outro`
      («جارٍ إعداد الخاتمة…»), their progress `home.progress.episode_intro` and
      `home.progress.episode_outro` («إعداد المقدمة»، «إعداد الخاتمة», each with its `_eta`
      form) and, in the review's bar, `render.running_intro` («المقدمة») and
      `render.running_outro` («الخاتمة»); the errors `episode.error.generate` («تعذّر إعداد
      المقدمة، فلم تُصنع الحلقة»), `episode.error.generate_empty` («ليس في المقدمة المُعدّة
      كلمات ولا رابط تعرضه… أعطها اسمًا أو عبارة في نافذة الحلقة») and `episode.error.qr_too_big` («رابط الخاتمة أطول من أن
      تقرأ الهواتف رمز الاستجابة السريعة الخاص به في فيديو بحجم 1280×720…»): is «رمز
      الاستجابة السريعة» what a person calls a QR code, or «رمز QR»? And the intro's title
      line, drawn into the video itself from the lecture's cards: «سورة الفرقان، الآيات
      ٤٤–٤٩» and, for one ayah, «سورة الفرقان، الآية ٧» (Arabic-Indic digits, the Arabic
      comma and an en dash), with the outro's default phrase «جزاكم الله خيرًا».
    - the Episode dialog's generated intro and outro: the kinds `episode.kind.none`
      («بدون»), `episode.kind.clip` («مقطعي») and `episode.kind.generated` («مُولَّد»);
      the fields `episode.gen.name` («الاسم»), `episode.gen.title` («العنوان»),
      `episode.gen.style` («النمط») with `episode.gen.style.fade` («تلاشٍ»),
      `episode.gen.style.rise` («صعود») and `episode.gen.style.reveal` («كشف»),
      `episode.gen.seconds` («المدة (ث)»), `episode.gen.phrase` («عبارة الختام»),
      `episode.gen.custom` («عبارة أخرى…»), `episode.gen.link` («الرابط»),
      `episode.gen.platform` («النشر على»), `episode.gen.tracked` («الرابط داخل رمز QR»)
      and its tooltip `episode.gen.tracked.tip`, `episode.gen.copy` («انسخ») and its
      tooltip `episode.gen.copy.tip` («هو الرابط نفسه، معلَّمًا بأنه من الوصف، فتُحسب نقراته
      منفصلةً عن مسح رمز QR»), `episode.gen.readable` («يُكتب تحت الرمز: …») and its tooltip
      `episode.gen.readable.tip` («ليس فيه تتبّع، فتظهر زياراته زياراتٍ مباشرة، منفصلةً عن
      زيارات الرمز وزيارات الوصف»: is «زيارات مباشرة» what analytics calls direct traffic in
      Arabic?); the line above OK and Cancel `episode.defaults_hint` («ما تغيّره هنا يصبح أيضًا الافتراضي
      للدروس الجديدة»); the refusals `episode.gen.empty_intro` («ليس في المقدمة ما تعرضه») and
      `episode.gen.empty_outro`; the warnings `episode.gen.qr_too_big`,
      `episode.gen.missing_glyphs` («لا يستطيع خط العنوان رسم …: ستظهر مربعاتٍ فارغة»),
      `episode.link_warning.mixed` («يخلط هذا العنوان أبجديات في اسم واحد») and
      `episode.link_warning.confusable` («مكتوب بحروف تشبه اللاتينية وليست منها»); the link
      errors `episode.link_invalid` («أدخل عنوان
      ويب يبدأ بـ http:// أو https://»), `episode.link_invalid.spaces`,
      `episode.link_invalid.slashes`, `episode.link_invalid.userinfo`,
      `episode.link_invalid.host` and `episode.link_invalid.port`; and the platform
      names `platform.youtube` («يوتيوب»), `platform.instagram` («إنستغرام»),
      `platform.facebook` («فيسبوك»), `platform.tiktok` («تيك توك»), `platform.telegram`
      («تيليغرام») and `platform.whatsapp` («واتساب»). Is «مقطعي» clear for "my own
      clip", and «مُولَّد» for a clip Qalun makes? The three closing phrases the outro
      offers are the video's words and are the same in both languages: «جزاكم الله
      خيرًا», «بارك الله فيكم» and «سبحانك اللهم وبحمدك، أشهد أن لا إله إلا أنت،
      أستغفرك وأتوب إليك».
    - the 114 surah names as the intro's title writes them, in plain letters, listed in
      `tests/test_surah_names.py` (`PLAIN_TITLES`): «سورة آل عمران», «سورة الشورى», «سورة
      الأعلى», «سورة الضحى» and the rest. 34 «سبأ» and 78 «النبأ» are written as most people
      write them, not as the shipped text's Uthmani «سبإ» and «النبإ»: confirm that is right.

    Is «الحلقة» the right word for the episode, and «الدرس» or «المحاضرة» for the lecture
    (both are used now)?
  - the error log, on the link in Settings → About (the gear in the header):
    `home.open_log_folder` («افتح مجلد السجلات»), its tooltip
    `home.open_log_folder.tip` («حيث يدوّن قالون ما حدث من أخطاء») and
    `home.open_log_failed` («تعذّر فتح مجلد السجلات»). Is «السجلات» what a person would
    look for, or «سجل الأخطاء»?
- [ ] Keep every direction mark: the U+2066…U+2069 isolates and the U+200F marks,
      written as `\u2066`-style escapes in the source. The tests fail if a key goes
      missing.

## Speech model

- [ ] Publishing a new speech model: follow `tools/export_local_model/README.md`. A new
      model is a new release asset. Never replace a release asset in place, because
      shipped apps pin the old one by size and checksum.
- [ ] With a new model, change the sha256 in the key of the **Keep the speech model
      between runs** step in `release.yml` to the new archive's (the tests fail until
      it matches). This needs a token with the `workflow` scope.
- [ ] When reading the model asset's download count as installs, remember CI: each
      build that misses its cache downloads once per platform (up to three per run).
      See `packaging/ci/README.md`.

## Publish

- [ ] Tag the release and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`. The
      workflow builds again and attaches the three app zips to a Release. There is no
      separate source zip: each app zip carries `qalun-source.zip` and
      `third-party-sources/`.
- [ ] On the Release page, download each zip once more and check its top as under
      Build: `LICENSE`, `THIRD_PARTY_NOTICES.md`, `qalun-source.zip` and
      `third-party-sources/`. Wherever an app zip is posted besides (a website, a
      download page), post the zip as built, never the app without them.
- [ ] If the release is announced anywhere (a website, a post, a QR code on printed
      material), first settle the public download location (the blocking item at the
      top): the link below is the private repository's and answers 404 to the public.
      Then link to that public location with UTM parameters. Use one `utm_source` per
      channel, so downloads can be counted per channel:
      `https://github.com/Grazyen96/QalunTextAlignment/releases/latest?utm_source=<channel>&utm_medium=<post|print|qr>&utm_campaign=qalun-vX.Y.Z`.
      GitHub's own download counts for the release give the total. GitHub does not show
      the owner which query strings a visit came with, so to read the UTMs back, point
      the printed link or QR code at a page or redirect you have analytics on, and let it
      forward to the Release page. The app itself sends nothing.

# Episode: intro + recitation + lecture + outro — design

Date: 2026-10-12 · Status: approved in conversation, awaiting written-spec review

## 1. Purpose

A lecture is usually published as one programme. The programme runs:

1. the channel's **intro** clip;
2. the **recitation** of the ayat being studied (made in Qalun as a recitation job);
3. the **lecture** itself;
4. an **outro** clip.

Today the person joins these in another editor. Qalun should produce the joined video, called the
**episode**, alongside the lecture.

Success means:

- From a lecture's review window, the person chooses an intro clip, one of their recitation jobs,
  and an outro clip. Each is optional.
- Rendering the lecture then also writes `<lecture name> – episode.mp4`, which plays the four parts
  in order with no glitches, whatever the clips' sizes, frame rates or audio.
- The plain lecture video is still written as today.
- Choices are saved with the lecture, and the last intro and outro are pre-filled for the next
  lecture.

Decisions taken in the brainstorm (the owner's answers):

| Question | Decision |
|---|---|
| Where the parts are chosen | **In the lecture's own render flow**: saved with the lecture project |
| Which recitation video | **Its latest render; if it has none or it is stale, render it first**, with its own look |
| Intro/outro remembered | **Yes**: the last choice is the default for the next lecture, and can be cleared |
| Subtitle files | **The lecture's only, shifted** to where the lecture starts in the episode |

Out of scope:

- still images as an intro;
- fades or transitions;
- music under clips;
- reordering the parts, or more than one recitation;
- subtitles for the recitation, intro or outro;
- an episode for recitation projects;
- burning the lecture's captions into the intro or outro.

## 2. What the person sees

- **"Episode…" button** in the review window's toolbar, lecture projects only. It sits next to
  "Render with corrections" and is hidden during a render, like that button, so the window still
  fits 1280 px.
- It opens the **Episode dialog**:
  - **Intro**: the file name, with *Choose…* and *Remove*. MP4, MOV, MKV and WebM are accepted.
    The clip's length is shown once it has been read.
  - **Recitation**: a list containing *None*, then every recitation job in the job list. Each entry
    shows the surah, the ayat and the status: "rendered", "will be rendered first" or
    "damaged" (damaged entries are disabled).
  - **Outro**: as Intro.
  - **Total length**: intro + recitation + lecture + outro. A part whose length is unknown shows
    "?".
  - *OK* saves the choices as **one undoable edit**; *Cancel* changes nothing.
- When any part is set, the toolbar shows a small "Episode: on" label next to the button. The
  render progress then names each stage: "Rendering the recitation…", "Rendering the lecture…",
  "Joining the episode…".
- **Files written** in the job's video folder:
  - `<stem>.mp4`: the lecture, as today;
  - `<stem> – episode.mp4`;
  - when the job writes subtitle files, also `<stem> – episode.<fmt>` for each format. These hold
    the lecture's subtitles shifted by the episode offset (see §3.4). The lecture's own subtitle
    files are written as today.
- **Defaults:**
  - When the person saves the dialog with an intro or outro, those clips become the default.
  - A new lecture job starts with the default intro and outro, and no recitation.
  - Clearing them in the dialog clears the default too, because it is the last choice.
- **Job list:** a lecture whose episode choices changed after its last render shows "changed since
  render", as a look change does.

## 3. Architecture

### 3.1 Project data (`jobs/project.py`, `jobs/episode_assets.py`)

`project.episode` is stored under the project's existing known-keys mechanism, as a new key
`"episode"`. Unknown keys inside it are preserved.

```json
{"intro": "<stem>.qalun.episode/<sha12>.mp4",
 "recitation": "/abs/or/relative/path/to/<recitation>.qalun.json",
 "outro": null}
```

- Paths are stored relative to the project folder when the file lies inside it, and absolute
  otherwise. This is the same rule as the Look image paths.
- The clips are **copied** into `<stem>.qalun.episode/<sha256[:12]><ext>` beside the project. The
  copy is streamed, file mode 0644, and reused when identical. It uses the content-addressed helper
  from the Look work (`jobs/look_assets.copy_by_content`).
- The recitation is **referenced, not copied**: it is a live job that the person may correct later.
- `content_hash()` includes `episode` only when it is non-empty. Existing projects keep their hash.
- On load, a value of the wrong type falls back to "none" for that part. An unknown suffix is
  ignored.
- A re-match keeps the earlier project's episode choices, the same rule as for look and studied
  surah.
- Prefs `default_episode` holds the default intro and outro as absolute paths, in the app's data
  folder `episode/<sha12><ext>`.
  - The default is copied there when it is saved.
  - New lecture jobs are seeded from it: the clips are copied into the new project's folder.
  - A default clip that has gone missing is skipped with a notice, and the job is still created.

### 3.2 Recitation part (`jobs/episode.py`)

`recitation_video(path, *, avoid, progress, cancel) -> Path` loads the referenced recitation
project. *avoid* is the lecture video just written.

- It reuses the recorded render when `recitation_needs_render` says it may: the job list calls the
  render current (`job_status(project) == RENDERED`: nothing it was made from, nor the job's size
  or subtitles choice, changed since), the video file exists, and it is not *avoid*. The Episode
  dialog's "will be rendered first" follows the same rule.
- Otherwise it renders the recitation with `jobs.project_render.render_project`, using the
  recitation's own job settings (preset, look, and its **own** subtitles choice, so the job list
  does not call the render "changed since"), with `formats=()` so no subtitle file is written
  beside it. The output goes to the recitation's own default video path (or
  `<stem> – recitation.mp4` when that is *avoid*), and the render record is written onto the
  recitation's project file as it is when the render ends, so a correction saved meanwhile is
  kept and reads as stale.
- A recitation project that is missing or damaged raises `EpisodeError`, carrying a translated
  message key.

### 3.3 Joining (`jobs/episode.py`)

`assemble_episode(parts: list[Path], output: Path, *, width, height, fps, progress, cancel) ->
EpisodeResult` produces the episode.

- **Probing:** each part is probed with `ffprobe` for its duration, whether it has a video stream
  and whether it has an audio stream. A part with no video stream raises `EpisodeError`.
- **One FFmpeg run** with a `concat` filter graph re-encodes everything to the lecture's geometry:
  - video: `scale=W:H:force_original_aspect_ratio=decrease, pad=W:H:(ow-iw)/2:(oh-ih)/2:black,
    setsar=1, fps=FPS, format=yuv420p`;
  - audio: `aresample=48000, aformat=channel_layouts=stereo`. A part without audio gets
    `anullsrc` for exactly its duration;
  - `concat=n=N:v=1:a=1`;
  - encoding: H.264 and AAC, with the same quality settings as the frame renderer's encoder (read
    `_start_frame_encoder` and reuse its arguments).
- **Binaries:** FFmpeg and ffprobe are found the same way the renderer finds them
  (`require_binary`), which includes the packaged app's own copies.
- **Writing:**
  - The output is written to `<output>.part.mp4`, then renamed. Cancelling or failing removes the
    partial file.
  - Progress comes from FFmpeg's `-progress pipe:1` `out_time`, against the total duration.
- `EpisodeResult(output, durations: tuple[float, ...], lecture_offset: float)` reports what was
  made. `lecture_offset` is the sum of the durations before the lecture part.

### 3.4 Rendering flow (`gui/jobs.run_render`, `jobs/project_render`)

When the project has a non-empty episode, `run_render` does the following after the lecture render
succeeds:

1. Resolve the parts: the intro, then the recitation through `recitation_video`, then the lecture
   video just written, then the outro. Skip the parts that are not set.
2. If only the lecture remains, skip the episode.
3. `assemble_episode(..., width, height, fps)`, using the lecture render's recorded geometry.
4. If the job writes subtitle files, write `<stem> – episode.<fmt>`: the lecture's cues on the
   video timeline, shifted by `lecture_offset`. This reuses `export_project_subtitles` with an
   extra offset parameter.
5. Record `episode` in `project.render` (path, lecture offset, durations), and add `episode_video`
   to `JobOutcome`.

**Failure handling:** if the lecture render fails, nothing changes. If the episode step fails or a
part is missing, the lecture video and its subtitles are kept and `JobOutcome.episode_error`
carries the translated message. The review window shows it in the warnings strip, and the main
window's status line shows it for "render right away". Cancel stops whichever step is running; a
cancel during the episode step (after the lecture is written and recorded) ends as
`episode_error` ("The episode was cancelled; the lecture video is kept.") and the job finishes with
the lecture. A missing intro or outro is named as "the intro" / "the outro", and is looked for
before the recitation is rendered. The subtitle files are named from the episode's full path, so a
recording name with a dot ("Tafsir 25.7-11") keeps the lecture's and the episode's files apart.

### 3.5 GUI

- `gui/review/episode_dialog.py` holds the dialog in §2. It reads the recitation jobs from
  `jobs.catalog.list_jobs` (recitation entries only) and the clip lengths through a helper that
  wraps ffprobe. It writes through `ReviewSession.set_episode(dict)`.
- `set_episode` is a session edit like `set_look`: the snapshot, dirty state and undo are extended
  the same way.
- Every string goes through `gui/i18n.py`, in English and Arabic, and the Arabic strings are added
  to the native-speaker review list.

## 4. Failure handling

| Situation | Behaviour |
|---|---|
| Intro/outro file gone at render time | The episode is skipped with "The intro clip is missing"; the lecture is kept |
| Recitation project missing or damaged | The episode is skipped with the message; the lecture is kept |
| Recitation render fails | The episode is skipped with its error; the lecture is kept |
| A clip has no audio | Silence for its duration |
| A clip has no video stream, or ffprobe cannot read it | Refused in the dialog ("not a video"); at render, the episode is skipped |
| A clip with a different size, aspect, fps or rotation | Scaled to fit with black bars. Rotation metadata is honoured by FFmpeg's autorotate |
| Disk full or FFmpeg error | The partial file is removed and the FFmpeg log tail is shown, as for renders |
| Cancel during any stage | Stops; no partial episode; the lecture is kept if its stage had finished |

## 5. Testing

- **`assemble_episode`**, on tiny clips generated with FFmpeg (1–2 s each):
  - different sizes (640×360 and 360×640), frame rates (25 and 30) and audio (with and without);
  - the output's duration is within ±0.1 s of the sum;
  - the output has the lecture's size and fps, with one video stream and one stereo 48 kHz audio
    stream;
  - cancelling removes the `.part` file.
  
  These tests are skipped when FFmpeg is absent.
- **`recitation_video`**: a current render is reused; a missing, stale or "changed since" render
  renders first (spy on `render_project`); a damaged project raises.
- **Project:**
  - `episode` round-trips through save and reopen;
  - relative paths survive moving the folder;
  - tolerant load;
  - the hash rule, so an empty episode keeps the old hash;
  - copy dedup and mode 0644;
  - a re-match keeps the choices.
- **Prefs:** the default is saved, a new job is seeded from it, and a default clip that has gone
  missing is skipped with a notice.
- **`run_render`:**
  - writes the episode and the shifted subtitle files;
  - a missing part keeps the lecture and sets `episode_error`;
  - only the lecture set means no episode.
- **GUI** (offscreen; pytest-qt is not installed):
  - the dialog's defaults, Choose and Remove, the recitation list states and the total length;
  - OK is one undo step, and Cancel changes nothing;
  - the button appears in lecture projects only and hides during a render;
  - the window still fits 1280 px.
- **i18n:** every key exists in both languages.

## 6. Delivery

One branch, `feat/episode`, in its own worktree, in three phases:

1. data and joining: `episode_assets`, `assemble_episode`, `recitation_video`;
2. the render flow, subtitles and prefs defaults;
3. the dialog and window wiring.

Each phase gets one review, and each is merged locally after the owner agrees.

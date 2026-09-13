"""Produce the deliverables: a video, subtitle files, or both.

This is what replaces the Premiere branch. That path required a paid
application, two motion-graphics templates nobody has authored, an export preset
nothing writes, and a caption API that does not exist in any shipped version of
the plugin host. The editable artifact it was chasing is a subtitle file, and
every tool already reads one.

Three choices, because they answer different needs:

* **burn** — subtitles in the picture, ready to post.
* **sidecar** — a clean video plus subtitle files, so the words stay selectable,
  searchable and correctable after the fact.
* **both** — the usual answer for publishing.

For a lecture the caption band genuinely can move out of the picture and into a
file. For a recitation the ayah card *is* the visual, so a clean recitation
video is nearly empty; there the sidecar is an accessibility and platform
deliverable rather than a substitute for the card.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from qurantext.config.paths import QURAN_DB_PATH
from qurantext.core.subtitles import (
    Cue,
    ayah_caption_cues,
    ayah_rows_for_card,
    card_ref,
    latched_card_windows,
    write_subtitles,
)
from qurantext.core.video_common import (
    get_audio_duration,
    load_caption_segments,
    load_matches,
    validated_matches,
    warn,
)
from qurantext.jobs.render import RenderRequest, RenderResult, render_video
from qurantext.utils.progress import CancelToken, ProgressCallback, report

__all__ = ["SUBTITLE_MODES", "ExportRequest", "ExportResult", "build_cues", "export_job"]

#: How subtitles reach the viewer.
SUBTITLE_MODES = ("burn", "sidecar", "both")

STAGE = "export"


@dataclass(frozen=True, slots=True)
class ExportRequest:
    """What to produce for one job."""

    audio: Path
    matches: Path
    output: Path
    subtitles: str = "burn"
    formats: tuple[str, ...] = ("srt",)
    preset: str | None = None
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    font_file: Path | None = None
    title: str | None = None
    db_path: Path = QURAN_DB_PATH
    #: Caption cues from a project file, used verbatim when given.
    captions: tuple[dict, ...] | None = None

    def __post_init__(self) -> None:
        if self.subtitles not in SUBTITLE_MODES:
            raise ValueError(
                f"subtitles must be one of {', '.join(SUBTITLE_MODES)}, got {self.subtitles!r}."
            )


@dataclass(frozen=True, slots=True)
class ExportResult:
    """What was produced."""

    video: Path | None
    subtitles: list[Path] = field(default_factory=list)
    cues: int = 0
    render: RenderResult | None = None


def build_cues(
    matches_path: Path,
    duration: float,
    *,
    mode: str,
    db_path: Path = QURAN_DB_PATH,
    captions: tuple[dict, ...] | None = None,
) -> list[Cue]:
    """The subtitle track for a job.

    A lecture's track is the recognised speech, which is the thing a person
    corrects. A recitation's is the canonical ayah text split per ayah, taken
    from the store — never the recogniser's version of the Quran.
    """
    if mode == "lecture":
        segments = (
            [dict(cue) for cue in captions]
            if captions is not None
            else load_caption_segments(matches_path)
        )
        return [
            Cue(start=float(s["start"]), end=float(s["end"]), text=str(s["text"])) for s in segments
        ]

    cards = sorted(
        validated_matches(load_matches(matches_path), bridge_gaps=False),
        key=lambda card: float(card["_start_time"]),
    )
    if not cards:
        return []
    windows = latched_card_windows(cards, duration)

    needs_store = any(
        card.get("kind") != "preamble" and card.get("surah_num") is not None for card in cards
    )
    conn: sqlite3.Connection | None = None
    if needs_store:
        from qurantext.data.quran_db import connect

        conn = connect(db_path)

    cues: list[Cue] = []
    try:
        for card, window in zip(cards, windows, strict=True):
            rows = None
            if conn is not None and card.get("kind") != "preamble":
                try:
                    rows = ayah_rows_for_card(
                        conn, int(card["surah_num"]), int(card["from_ayah"]), int(card["to_ayah"])
                    )
                except (ValueError, sqlite3.DatabaseError, TypeError) as error:
                    warn(f"Card {card_ref(card)}: {error}")
            for cue in ayah_caption_cues(card, window, rows):
                cues.append(
                    Cue(
                        start=float(cue["in"]),
                        end=float(cue["out"]),
                        text=str(cue["text"]),
                        ref=cue.get("ref"),
                    )
                )
    finally:
        if conn is not None:
            conn.close()
    return cues


def export_job(
    request: ExportRequest,
    *,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> ExportResult:
    """Render and write whatever *request* asked for."""
    audio = Path(request.audio).expanduser().resolve()
    matches = Path(request.matches).expanduser().resolve()
    output = Path(request.output).expanduser().resolve()

    from qurantext.core.basmala import load_matches_meta

    mode = str(load_matches_meta(matches).get("mode") or "recitation").lower()

    # A sidecar-only job still renders: the ayah card and the word highlight are
    # the picture. What changes is whether the caption band is burned in.
    burn_captions = request.subtitles in ("burn", "both")
    render_request = RenderRequest(
        audio=audio,
        matches=matches,
        output=output,
        preset=request.preset,
        width=request.width,
        height=request.height,
        fps=request.fps,
        font_file=request.font_file,
        title=request.title,
        captions=request.captions if burn_captions else (),
    )
    render_result = render_video(render_request, progress=progress, cancel=cancel)

    written: list[Path] = []
    cues: list[Cue] = []
    if request.subtitles in ("sidecar", "both"):
        if cancel is not None:
            cancel.raise_if_cancelled(STAGE)
        report(progress, STAGE, "Writing subtitle files...")
        # The match file's timings predate the basmala splice, so the cues are
        # built on the pre-splice timeline and shifted afterwards. The duration
        # has to match that timeline too: passing the rendered (post-splice)
        # length here stretched the last cue, which holds to the end of the
        # audio, and then shifting it added the offset a second time.
        offset = render_result.basmala_offset_seconds
        duration = (render_result.duration_seconds or get_audio_duration(audio)) - offset
        cues = build_cues(
            matches,
            duration,
            mode=mode,
            db_path=Path(request.db_path),
            captions=request.captions,
        )
        if offset:
            cues = [
                Cue(start=c.start + offset, end=c.end + offset, text=c.text, ref=c.ref)
                for c in cues
            ]
        if cues:
            written = write_subtitles(
                cues,
                output.with_suffix(""),
                request.formats,
                width=render_result.width,
                height=render_result.height,
            )
            report(
                progress,
                STAGE,
                f"Wrote {len(written)} subtitle file(s): " + ", ".join(p.name for p in written),
            )
        else:
            warn("No subtitle cues could be built, so no sidecar files were written.")

    return ExportResult(
        video=render_result.output, subtitles=written, cues=len(cues), render=render_result
    )

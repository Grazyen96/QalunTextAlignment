"""The video render as a callable job.

Rendering used to be reachable only by building a list of command-line strings
and handing it to ``argparse``, which returned ``0`` or ``1``. That is fine for
a shell and useless for anything else: a caller could not learn what was
produced, could not follow progress, and could not stop a render once it began.

This module is the real entry point. It takes a typed :class:`RenderRequest`,
reports progress through an optional callback, honours an optional
:class:`~qurantext.utils.progress.CancelToken`, and returns a
:class:`RenderResult` describing what it wrote. The CLI is now one caller of it
among others.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qurantext.config.settings import DEFAULT_VIDEO_FONT_FILE, VIDEO_PRESETS, get_settings
from qurantext.core.ass_renderer import build_ass, render_ass_video, validate_font_name
from qurantext.core.basmala import load_matches_meta, maybe_prepend_basmala
from qurantext.core.frame_renderer import (
    DEFAULT_PLACEHOLDER_TITLE,
    render_frame_video,
    validate_font_file,
)
from qurantext.core.looks import NIGHT_GOLD, Look
from qurantext.core.video_common import (
    cards_on_screen,
    get_audio_duration,
    has_surah_cards,
    load_caption_segments,
    load_matches,
    validate_dimensions,
    validate_fps,
    validate_input_file,
    warn,
)
from qurantext.utils.progress import CancelToken, ProgressCallback, report

__all__ = ["RenderRequest", "RenderResult", "look_warning_message", "render_video"]

STAGE = "render"

#: What each look warning code means to the person, said once per render.
_LOOK_WARNINGS = {
    "image_missing": "The background image is missing; the preset's background was used.",
    "image_unreadable": "The background image could not be read; the preset's background was used.",
}


def look_warning_message(code: str) -> str:
    """The sentence a person reads for a look warning *code*."""
    return _LOOK_WARNINGS.get(code, f"The look could not be drawn as chosen ({code}).")


@dataclass(frozen=True, slots=True)
class RenderRequest:
    """Everything needed to render one video.

    Geometry is resolved before construction: pass ``preset`` OR explicit
    ``width``/``height``/``fps``. Leaving all four unset falls back to the
    configured video defaults.
    """

    audio: Path
    matches: Path
    output: Path
    renderer: str = "frame"
    preset: str | None = None
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    font_name: str | None = None
    font_file: Path | None = None
    title: str | None = None
    debug_detected_text: bool = False
    keep_temp: bool = False
    #: Caption cues supplied by the caller, usually from a project file. When
    #: given, the renderer uses these verbatim instead of re-deriving cues from
    #: the raw recognition output, which is what lets a correction survive.
    captions: tuple[dict, ...] | None = None
    #: Ayah cards supplied by the caller, usually from a project file. When
    #: given, they are rendered instead of the match file's, which is what lets
    #: a timing correction reach the video. The match file is still read for
    #: its metadata (the basmala splice needs it).
    cards: tuple[dict, ...] | None = None
    #: Colours and background of the frame renderer. The ass renderer ignores it.
    look: Look = NIGHT_GOLD
    #: The surah a lecture's cards keep to; None guesses it
    #: (``core.video_common.cards_on_screen``).
    studied_surah: int | None = None

    def resolved_format(self) -> tuple[int, int, int]:
        """Return ``(width, height, fps)`` with preset and defaults applied."""
        if self.preset is not None:
            return VIDEO_PRESETS[self.preset]
        video = get_settings().video
        return (
            self.width if self.width is not None else video.width,
            self.height if self.height is not None else video.height,
            self.fps if self.fps is not None else video.fps,
        )


@dataclass(frozen=True, slots=True)
class RenderResult:
    """What a completed render produced."""

    output: Path
    width: int
    height: int
    fps: int
    duration_seconds: float
    #: Seconds the basmala splice pushed the recitation timeline back by.
    basmala_offset_seconds: float = 0.0
    caption_segments: int = 0
    #: Written by the ASS renderer only.
    ass_path: Path | None = None
    #: Codes for what the look could not do (``image_missing``,
    #: ``image_unreadable``); the render still finished with the preset's background.
    look_warnings: tuple[str, ...] = ()
    #: The chosen studied surah when none of its ayat has a card: the video
    #: shows only its opening title card. None otherwise.
    studied_surah_missing: int | None = None


def render_video(
    request: RenderRequest,
    *,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> RenderResult:
    """Render *request* and return what was written.

    Raises ``FileNotFoundError``/``ValueError`` for bad input, ``RuntimeError``
    when a tool fails, and
    :class:`~qurantext.utils.progress.JobCancelled` if *cancel* is set partway.
    """
    width, height, fps = request.resolved_format()

    audio_path = Path(request.audio).expanduser().resolve()
    matches_path = Path(request.matches).expanduser().resolve()
    output_path = Path(request.output).expanduser().resolve()
    font_file_path = Path(request.font_file).expanduser().resolve() if request.font_file else None
    ass_path = output_path.with_suffix(".ass")

    validate_input_file(audio_path, "Audio file")
    validate_input_file(matches_path, "Matches JSON")
    validate_dimensions(width, height)
    validate_fps(fps)

    if cancel is not None:
        cancel.raise_if_cancelled(STAGE)

    matches = (
        [dict(card) for card in request.cards]
        if request.cards is not None
        else load_matches(matches_path)
    )
    # A lecture's card keeps to the surah it studies; quotes from elsewhere
    # stay in the captions only.
    mode = load_matches_meta(matches_path).get("mode")
    studied_surah_missing = (
        request.studied_surah
        if str(mode or "").lower() == "lecture"
        and request.studied_surah is not None
        and not has_surah_cards(matches, request.studied_surah)
        else None
    )
    detected = bool(matches)
    matches = cards_on_screen(matches, mode, request.studied_surah)
    if studied_surah_missing is not None and detected:
        warn(
            f"No ayah of the chosen surah {studied_surah_missing} was found. Rendering "
            "the opening title card only."
        )
    elif not matches:
        warn(
            "No matches were found in the match JSON. Rendering a dark video with the "
            "original audio and no ayah overlays."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    basmala_temp_audio: Path | None = None
    basmala_offset = 0.0
    look_warnings: list[str] = []
    try:
        # Splice the shipped basmala before recitations that do not already open
        # with one, shifting every timing back by its duration (see core.basmala).
        if get_settings().video.prepend_basmala:
            report(progress, STAGE, "Checking for a leading basmala...")
            prepend = maybe_prepend_basmala(
                matches_path, matches, audio_path, work_dir=output_path.parent
            )
            if prepend is not None:
                matches = prepend.matches
                audio_path = prepend.audio_path
                basmala_temp_audio = prepend.audio_path
                basmala_offset = prepend.offset
                report(
                    progress,
                    STAGE,
                    f"Prepending shipped basmala; shifting timings by {prepend.offset:.2f}s.",
                )

        if cancel is not None:
            cancel.raise_if_cancelled(STAGE)

        if request.renderer == "ass":
            _warn_ignored_for_ass(request, font_file_path)
            if not request.font_name:
                raise ValueError("font_name is required when the ass renderer is selected")
            validate_font_name(request.font_name)

            report(progress, STAGE, "Building ASS subtitles...")
            ass_document = build_ass(matches, request.font_name.strip(), width, height)
            ass_path.write_text(ass_document, encoding="utf-8-sig")

            report(progress, STAGE, "Encoding video with burned-in subtitles...")
            render_ass_video(audio_path, ass_path, output_path, width, height, fps=fps)
            duration = get_audio_duration(audio_path)
            caption_count = 0
        else:
            if request.font_name:
                warn("Ignoring font_name because the frame renderer uses font_file instead.")
            font_file_path = _resolve_frame_font(font_file_path, progress)
            validate_font_file(font_file_path)

            if request.captions is not None:
                captions = [dict(cue) for cue in request.captions]
            else:
                captions = load_caption_segments(matches_path)
            caption_count = len(captions)
            if captions:
                report(
                    progress,
                    STAGE,
                    f"Loaded {caption_count} caption segment(s) for the bottom band.",
                )

            duration = render_frame_video(
                audio_path,
                matches,
                output_path,
                width,
                height,
                fps,
                font_file_path,
                keep_temp=request.keep_temp,
                debug_detected_text=request.debug_detected_text,
                captions=captions,
                title=request.title or DEFAULT_PLACEHOLDER_TITLE,
                progress=progress,
                cancel=cancel,
                look=request.look,
                look_warnings=look_warnings,
            )
            for code in look_warnings:
                warn(look_warning_message(code))
            ass_path = None  # type: ignore[assignment]
    finally:
        # The concatenated basmala+recitation audio is a throwaway render input.
        if basmala_temp_audio is not None and not request.keep_temp:
            basmala_temp_audio.unlink(missing_ok=True)

    report(progress, STAGE, f"MP4 video saved to: {output_path}", done=True)
    return RenderResult(
        output=output_path,
        width=width,
        height=height,
        fps=fps,
        duration_seconds=duration,
        basmala_offset_seconds=basmala_offset,
        caption_segments=caption_count,
        ass_path=ass_path,
        look_warnings=tuple(look_warnings),
        studied_surah_missing=studied_surah_missing,
    )


def _warn_ignored_for_ass(request: RenderRequest, font_file_path: Path | None) -> None:
    if font_file_path is not None:
        warn("Ignoring font_file because the ass renderer uses installed font_name fonts.")
    if request.debug_detected_text:
        warn("Ignoring debug_detected_text because it only applies to the frame renderer.")
    if request.title:
        warn("Ignoring title because it only applies to the frame renderer.")
    if request.look != NIGHT_GOLD:
        warn("Ignoring the look because it only applies to the frame renderer.")


def _resolve_frame_font(font_file_path: Path | None, progress: ProgressCallback | None) -> Path:
    if font_file_path is not None:
        return font_file_path
    default_font = Path(DEFAULT_VIDEO_FONT_FILE)
    if not default_font.exists():
        raise ValueError(
            "font_file is required when the frame renderer is selected "
            "(the bundled default font was not found)."
        )
    report(progress, STAGE, f"No font_file given; using bundled default font: {default_font}")
    return default_font

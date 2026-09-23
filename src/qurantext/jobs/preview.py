"""Draw one frame, so a style can be judged in a second.

Checking how a video looks meant rendering the whole thing. At the portrait
default that was 23 seconds for a 101-second clip even after the Phase 0 work,
and minutes for a lecture — a slow way to find out a font is too big.

The renderer already draws exactly one frame at an arbitrary time, which is what
makes this nearly free: the same function the encoder calls, once, to a PNG.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qurantext.config.settings import DEFAULT_VIDEO_FONT_FILE, VIDEO_PRESETS, get_settings
from qurantext.core.video_common import (
    get_audio_duration,
    load_caption_segments,
    load_matches,
    validate_input_file,
    validated_matches,
)

__all__ = ["PreviewRequest", "PreviewResult", "render_preview"]


@dataclass(frozen=True, slots=True)
class PreviewRequest:
    """One frame of a job, at a chosen moment."""

    matches: Path
    output: Path
    #: Seconds into the video. None picks the first moment a card is on screen,
    #: which is the frame worth looking at rather than the opening placeholder.
    at: float | None = None
    preset: str | None = None
    width: int | None = None
    height: int | None = None
    font_file: Path | None = None
    title: str | None = None
    audio: Path | None = None

    def resolved_size(self) -> tuple[int, int]:
        if self.preset is not None:
            width, height, _ = VIDEO_PRESETS[self.preset]
            return width, height
        video = get_settings().video
        return (
            self.width if self.width is not None else video.width,
            self.height if self.height is not None else video.height,
        )


@dataclass(frozen=True, slots=True)
class PreviewResult:
    """Where the frame was written, and what it shows."""

    output: Path
    at: float
    width: int
    height: int
    #: The card visible at that moment, as ``25:7``, or None for the placeholder.
    card: str | None = None


def render_preview(request: PreviewRequest) -> PreviewResult:
    """Render a single frame of *request* to a PNG."""
    from qurantext.core.frame_renderer import (
        DEFAULT_PLACEHOLDER_TITLE,
        _frame_dependencies,
        placeholder_lines,
        render_frame_pillow,
    )
    from qurantext.core.subtitles import card_ref

    matches_path = Path(request.matches).expanduser().resolve()
    validate_input_file(matches_path, "Matches JSON")
    width, height = request.resolved_size()
    font_file = Path(request.font_file or DEFAULT_VIDEO_FONT_FILE)
    validate_input_file(font_file, "Font file")

    cards = sorted(
        validated_matches(load_matches(matches_path), bridge_gaps=False),
        key=lambda card: float(card["_start_time"]),
    )
    captions = load_caption_segments(matches_path)

    at = request.at
    if at is None:
        # Halfway into the first card: past the placeholder, and far enough in
        # that a word highlight is showing.
        if cards:
            first = cards[0]
            at = float(first["_start_time"]) + max(
                0.1, (float(first["_end_time"]) - float(first["_start_time"])) / 2
            )
        else:
            at = 0.0
    if request.audio is not None and Path(request.audio).is_file():
        at = min(at, get_audio_duration(Path(request.audio)))

    active = [c for c in cards if float(c["_start_time"]) <= at]
    card = active[-1] if active else None

    caption = next((c for c in captions if float(c["start"]) <= at <= float(c["end"])), None)
    reserve_band = bool(captions)
    title, placeholder_subtitle = placeholder_lines(
        cards, reserve_caption_band=reserve_band, title=request.title or DEFAULT_PLACEHOLDER_TITLE
    )

    frame = render_frame_pillow(
        at,
        card,
        width,
        height,
        font_file,
        caption_text=str(caption["text"]) if caption else "",
        caption_word_timings=caption.get("word_timings") if caption else None,
        title=title,
        placeholder_subtitle=placeholder_subtitle,
        reserve_caption_band=reserve_band,
    )

    # render_frame_pillow returns BGR for the encoder; PNG wants RGB.
    _, image_module, _, _, _ = _frame_dependencies()
    output = Path(request.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    image_module.fromarray(frame[:, :, ::-1]).save(output)

    return PreviewResult(
        output=output,
        at=round(at, 3),
        width=width,
        height=height,
        card=card_ref(card) if card else None,
    )

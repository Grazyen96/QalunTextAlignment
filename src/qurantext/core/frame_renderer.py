from __future__ import annotations

import bisect
import math
import subprocess
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from qurantext.core.looks import NIGHT_GOLD, Look
from qurantext.core.video_common import (
    ayah_label,
    get_audio_duration,
    lecture_intro_lines,
    require_binary,
    validate_input_file,
    validated_matches,
    warn,
)
from qurantext.utils.progress import CancelToken, ProgressCallback, report

if TYPE_CHECKING:
    from qurantext.core.backgrounds import BaseLayer

COLOUR_BG = (10, 10, 12, 255)
COLOUR_CARD = (36, 36, 42, 230)
COLOUR_CARD_BORDER = (255, 255, 255, 28)
COLOUR_HEADER_TEXT = (230, 230, 235, 255)
COLOUR_BODY_TEXT = (255, 255, 255, 255)
COLOUR_HIGHLIGHT_WORD = (255, 215, 0, 255)  # Gold — active recited word
COLOUR_DEBUG_TEXT = (188, 188, 198, 255)
COLOUR_SUBTLE = (150, 150, 162, 255)
COLOUR_CAPTION_BG = (0, 0, 0, 165)  # translucent strip behind the live captions
COLOUR_CAPTION_TEXT = (240, 240, 245, 255)  # already-spoken caption words
COLOUR_CAPTION_ACTIVE = (128, 226, 234, 255)  # soft cyan — word being spoken now
COLOUR_CAPTION_UPCOMING = (150, 150, 162, 255)  # dimmed — not yet spoken
COLOUR_PLACEHOLDER_TEXT = (205, 205, 215, 255)

CARD_WIDTH_RATIO = 0.86
# Ayah card height as a fraction of the region *above* the caption band.
CARD_REGION_HEIGHT_RATIO = 0.90
CARD_RADIUS_RATIO = 0.024
CARD_PADDING_X_RATIO = 0.055
CARD_PADDING_Y_RATIO = 0.06
HEADER_FONT_RATIO = 0.036
BODY_FONT_START_RATIO = 0.060
BODY_FONT_MIN_RATIO = 0.024
DEBUG_FONT_START_RATIO = 0.025
DEBUG_FONT_MIN_RATIO = 0.015
LINE_SPACING_RATIO = 0.30
SECTION_GAP_RATIO = 0.02

# Live-transcript caption band pinned to the bottom of the frame. The text is
# kept inside a safe area (insets from the edges) so players that crop-to-fill —
# phone fullscreen, TV overscan — don't clip it, and sized generously so it stays
# legible on a phone held at arm's length. A taller band both gives long captions
# more room and pulls the caption text up closer to the ayah card.
CAPTION_BAND_RATIO = 0.34
CAPTION_PADDING_X_RATIO = 0.08
# Keep caption text this far above the very bottom edge (fraction of frame height).
CAPTION_SAFE_BOTTOM_RATIO = 0.07
CAPTION_FONT_START_RATIO = 0.055
CAPTION_FONT_MIN_RATIO = 0.034
# A single WhisperX segment can run long enough to overflow the band even at the
# minimum font size. Cap how many words are shown at once: the caption is paged
# in fixed chunks of this size and only the chunk holding the spoken word is
# drawn, so the text stays inside the band and shifts only at chunk boundaries.
MAX_CAPTION_WORDS = 28

# Centre placeholder shown before the first ayah is detected.
DEFAULT_PLACEHOLDER_TITLE = "القرآن الكريم"
PLACEHOLDER_FONT_START_RATIO = 0.060
PLACEHOLDER_FONT_MIN_RATIO = 0.030


def placeholder_lines(
    matches: list[dict[str, Any]],
    *,
    reserve_caption_band: bool,
    title: str = DEFAULT_PLACEHOLDER_TITLE,
) -> tuple[str, str]:
    """The (title, subtitle) drawn before any ayah has started.

    A lecture — one with a caption band to show, i.e. *reserve_caption_band* —
    announces the surah and ayah range it ponders instead of the generic
    *title*, via :func:`~qurantext.core.video_common.lecture_intro_lines`. A
    recitation render, or a lecture whose matches carry no ayah numbering,
    keeps the generic title with no subtitle. This is the one place that
    choice is made: :func:`write_frame_video` and any single-frame preview of
    the same moment (``jobs.preview.render_preview``, the desktop review
    window's live frame) call this so the placeholder never disagrees between
    what a person previews and what the exported video actually draws.
    """
    if reserve_caption_band:
        intro = lecture_intro_lines(matches)
        if intro is not None:
            return intro
    return title, ""


@lru_cache(maxsize=1)
def _frame_dependencies() -> tuple[Any, Any, Any, Any, Any]:
    """numpy and Pillow, imported on first use with a friendly error when missing.

    :mod:`qurantext.core.backgrounds` imports Pillow at module level, so this
    module imports it lazily too (inside the functions that draw) to keep
    importing ``frame_renderer`` cheap and this error reachable.
    """
    try:
        import numpy as np
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "frame renderer requires numpy. Install it with: pip install numpy"
        ) from error

    try:
        from PIL import Image, ImageDraw, ImageFont, features
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "frame renderer requires Pillow. Install it with: pip install pillow"
        ) from error

    return np, Image, ImageDraw, ImageFont, features


@lru_cache(maxsize=1)
def _require_raqm_support() -> None:
    _, _, _, _, features = _frame_dependencies()
    if not features.check("raqm"):
        raise RuntimeError(
            "Pillow was not built with libraqm. Arabic shaping/RTL rendering may be incorrect. "
            "Frame renderer requires libraqm support, so install a Pillow build with libraqm enabled."
        )


def active_match_at(matches: list[dict[str, Any]], t: float) -> dict[str, Any] | None:
    """Return the highest-priority match active at timestamp ``t``."""
    active: list[dict[str, Any]] = []
    for match in matches:
        start_time = match.get("_start_time")
        end_time = match.get("_end_time")
        if not isinstance(start_time, (int, float)) or not isinstance(end_time, (int, float)):
            continue
        if start_time <= t <= end_time:
            active.append(match)

    if not active:
        return None

    active.sort(
        key=lambda match: (
            float(match.get("_confidence", 0.0)),
            float(match.get("_duration", 0.0)),
        ),
        reverse=True,
    )
    return active[0]


@dataclass(slots=True)
class ActiveMatchTracker:
    """Track active matches efficiently while timestamps advance monotonically."""

    matches: list[dict[str, Any]]
    _next_index: int = 0
    _active: list[dict[str, Any]] = field(default_factory=list)

    def at(self, t: float) -> dict[str, Any] | None:
        while self._next_index < len(self.matches):
            next_match = self.matches[self._next_index]
            start_time = next_match.get("_start_time")
            if not isinstance(start_time, (int, float)) or start_time > t:
                break
            self._active.append(next_match)
            self._next_index += 1

        self._active = [
            match
            for match in self._active
            if isinstance(match.get("_end_time"), (int, float)) and float(match["_end_time"]) >= t
        ]
        if not self._active:
            return None

        return max(
            self._active,
            key=lambda match: (
                float(match.get("_confidence", 0.0)),
                float(match.get("_duration", 0.0)),
            ),
        )


@lru_cache(maxsize=256)
def load_font(font_file: Path, size: int) -> Any:
    """Load a TrueType/OpenType font file for frame rendering.

    Cached by ``(font_file, size)``: ``fit_font_size`` probes many sizes per
    match and the same sizes recur across thousands of frames, so re-reading and
    re-parsing the TTF every call dominated render time. PIL font objects are
    safe to reuse for measuring and drawing.
    """
    _, _, _, image_font, _ = _frame_dependencies()
    try:
        return image_font.truetype(str(font_file), size=size)
    except OSError as error:
        raise RuntimeError(f"Failed to load font file '{font_file}': {error}") from error


@lru_cache(maxsize=1)
def _measure_probe() -> Any:
    """A 1x1 canvas used only for text measurement.

    ``textbbox`` derives its result from the font's own metrics, so the size and
    mode of the canvas it is called on never affect the answer. Keeping one
    shared probe lets the layout caches below key on the text and the box alone,
    without dragging a per-frame ``ImageDraw`` into the cache key.
    """
    _, image_module, image_draw, _, _ = _frame_dependencies()
    return image_draw.Draw(image_module.new("RGBA", (1, 1)))


def measure_text_bbox(draw: Any, text: str, font: Any) -> tuple[int, int]:
    """Measure text width and height using Pillow."""
    probe_text = text if text else " "
    bbox = draw.textbbox((0, 0), probe_text, font=font, direction="rtl")
    return max(0, bbox[2] - bbox[0]), max(0, bbox[3] - bbox[1])


def wrap_text_to_width(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    """Wrap text by spaces while preserving explicit newlines."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = normalized.split("\n")
    wrapped: list[str] = []

    for paragraph in paragraphs:
        stripped = paragraph.strip()
        if not stripped:
            wrapped.append("")
            continue

        words = stripped.split()
        current = words[0]

        for word in words[1:]:
            candidate = f"{current} {word}"
            w, _ = measure_text_bbox(draw, candidate, font)
            if w <= max_width:
                current = candidate
                continue

            wrapped.append(current)
            current = word

        wrapped.append(current)

    return wrapped or [""]


def _multiline_metrics(
    draw: Any, lines: list[str], font: Any, line_spacing: int
) -> tuple[int, int]:
    widths: list[int] = []
    heights: list[int] = []
    for line in lines:
        width, height = measure_text_bbox(draw, line, font)
        widths.append(width)
        heights.append(height)

    total_height = sum(heights)
    if len(lines) > 1:
        total_height += line_spacing * (len(lines) - 1)
    return (max(widths) if widths else 0), total_height


@lru_cache(maxsize=512)
def _fit_font_size_cached(
    text: str,
    font_file: Path,
    max_width: int,
    max_height: int,
    start_size: int,
    min_size: int,
) -> tuple[Any, tuple[str, ...]]:
    """Cached core of :func:`fit_font_size` (see it for the contract).

    The size sweep re-wraps and re-measures the whole text at every candidate
    size, and each wrap issues one Raqm shaping call per word and per line, so
    this is the single most expensive thing a frame does. The result depends
    only on the text and the box, while the renderer asks for the same card or
    caption again on every word of the highlight, so it is cached rather than
    recomputed per rendered frame.
    """
    draw = _measure_probe()
    min_size = max(8, min_size)
    best_font = load_font(font_file, min_size)
    best_lines = wrap_text_to_width(draw, text, best_font, max_width)

    for size in range(max(start_size, min_size), min_size - 1, -2):
        font = load_font(font_file, size)
        lines = wrap_text_to_width(draw, text, font, max_width)
        line_spacing = max(4, int(size * LINE_SPACING_RATIO))
        width, height = _multiline_metrics(draw, lines, font, line_spacing)
        if width <= max_width and height <= max_height:
            return font, tuple(lines)
        best_font = font
        best_lines = lines

    return best_font, tuple(best_lines)


def fit_font_size(
    draw: Any,
    text: str,
    font_file: Path,
    max_width: int,
    max_height: int,
    start_size: int,
    min_size: int,
) -> tuple[Any, list[str]]:
    """Fit wrapped text into the given box by reducing the font size.

    *draw* is accepted for call-site compatibility but not used for measurement:
    text metrics come from the font, not the canvas, so the cached core measures
    against a shared probe instead.
    """
    font, lines = _fit_font_size_cached(
        text, font_file, max_width, max_height, start_size, min_size
    )
    return font, list(lines)


@lru_cache(maxsize=512)
def _paginate_lines_cached(
    lines: tuple[str, ...],
    font: Any,
    line_spacing: int,
    max_height: int,
) -> tuple[tuple[str, ...], ...]:
    """Cached core of :func:`paginate_lines`.

    Measures a growing run of lines, so it costs a shaping call per line per
    page. Like the fit above, the answer depends only on the lines and the box,
    and the renderer re-asks for it on every word of the highlight.
    """
    if not lines:
        return ((),)

    draw = _measure_probe()
    pages: list[tuple[str, ...]] = []
    current: list[str] = []

    for line in lines:
        candidate = current + [line]
        _, h = _multiline_metrics(draw, candidate, font, line_spacing)
        if h <= max_height or not current:
            current = candidate
        else:
            pages.append(tuple(current))
            current = [line]

    if current:
        pages.append(tuple(current))

    return tuple(pages) or ((),)


def paginate_lines(
    lines: list[str],
    draw: Any,
    font: Any,
    line_spacing: int,
    max_height: int,
) -> list[list[str]]:
    """Split a list of wrapped lines into pages that each fit within max_height.

    *draw* is accepted for call-site compatibility but not used: see
    :func:`fit_font_size`.
    """
    return [
        list(page) for page in _paginate_lines_cached(tuple(lines), font, line_spacing, max_height)
    ]


def draw_rounded_rectangle(
    image: Any,
    box: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] = COLOUR_CARD_BORDER,
) -> None:
    """Draw a semi-transparent rounded rectangle using Pillow."""
    _, image_module, image_draw, _, _ = _frame_dependencies()
    overlay = image_module.new("RGBA", image.size, (0, 0, 0, 0))
    draw = image_draw.Draw(overlay, "RGBA")

    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2)
    else:
        x0, y0, x1, y1 = box
        draw.rectangle((x0 + radius, y0, x1 - radius, y1), fill=fill)
        draw.rectangle((x0, y0 + radius, x1, y1 - radius), fill=fill)
        draw.ellipse((x0, y0, x0 + 2 * radius, y0 + 2 * radius), fill=fill)
        draw.ellipse((x1 - 2 * radius, y0, x1, y0 + 2 * radius), fill=fill)
        draw.ellipse((x0, y1 - 2 * radius, x0 + 2 * radius, y1), fill=fill)
        draw.ellipse((x1 - 2 * radius, y1 - 2 * radius, x1, y1), fill=fill)

    image.alpha_composite(overlay)


def draw_centered_multiline_text(
    draw: Any,
    lines: list[str],
    font: Any,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int, int],
    line_spacing: int,
) -> None:
    """Draw multiline text centered inside a bounding box."""
    x0, y0, x1, y1 = box
    _, total_height = _multiline_metrics(draw, lines, font, line_spacing)
    current_y = y0 + max(0, ((y1 - y0) - total_height) / 2)

    for line in lines:
        line_width, line_height = measure_text_bbox(draw, line, font)
        current_x = x0 + max(0, ((x1 - x0) - line_width) / 2)
        draw.text(
            (current_x, current_y),
            line,
            font=font,
            fill=fill,
            direction="rtl",
            align="center",
        )
        current_y += line_height + line_spacing


def _is_ayah_marker(token: str) -> bool:
    """Return True if *token* is an ayah number marker (Arabic-Indic digits only)."""
    stripped = token.strip()
    return bool(stripped) and all("\u0660" <= c <= "\u0669" for c in stripped)


def _count_non_marker_words(line: str) -> int:
    """Count word tokens on *line*, excluding ayah-number markers.

    Mirrors the word counting in ``draw_centered_multiline_text_with_highlight``
    so a highlight index can be made page-local.
    """
    return sum(1 for token in line.split() if not _is_ayah_marker(token))


def _page_index_for_word(pages: list[list[str]], word_idx: int) -> int:
    """Return the page holding the *word_idx*-th non-marker word.

    Page turns are driven by which word is being recited (via word timings)
    rather than elapsed clock time, so the displayed page tracks the highlight
    instead of running ahead or lagging behind the reciter's pace.
    """
    cumulative = 0
    for page_idx, page in enumerate(pages):
        page_words = sum(_count_non_marker_words(line) for line in page)
        if word_idx < cumulative + page_words:
            return page_idx
        cumulative += page_words
    return max(0, len(pages) - 1)


def active_word_timing_index(word_timings: list[dict[str, Any]], t: float) -> int | None:
    """Return the index of the word in *word_timings* being recited at time *t*.

    If *t* falls between two words the most recently started word is returned so
    the highlight never disappears mid-silence.  Returns ``None`` when
    *word_timings* is empty or *t* is before the first word.
    """
    last_started: int | None = None
    for i, wt in enumerate(word_timings):
        start = wt.get("start")
        end = wt.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        if start <= t:
            last_started = i
        if start <= t <= end:
            return i
    return last_started


class CaptionTrack:
    """Which caption the video shows at a moment, for many lookups against one list.

    The rule is the renderer's: of the cues that have started by *t*, the one
    that started last is shown if it still covers *t*; otherwise none is (an
    earlier, longer cue does not come back). Captions are not latched the way
    ayah cards are — they roll with the speech and clear in the gaps. Ties on
    start go to the later cue in list order. The review window and the
    single-frame preview use this too, so neither can show a different
    caption than the render where cues overlap.
    """

    __slots__ = ("_ends", "_order", "_starts")

    def __init__(self, spans: Iterable[tuple[float, float]]) -> None:
        pairs = [(float(start), float(end)) for start, end in spans]
        self._order = sorted(range(len(pairs)), key=lambda i: pairs[i][0])
        self._starts = [pairs[i][0] for i in self._order]
        self._ends = [pairs[i][1] for i in self._order]

    def index_at(self, t: float) -> int | None:
        """The shown cue's index in the spans given, or ``None`` when none is shown."""
        latest = bisect.bisect_right(self._starts, t) - 1
        if latest < 0 or t > self._ends[latest]:
            return None
        return self._order[latest]


def caption_spans(captions: Sequence[Mapping[str, Any]]) -> list[tuple[float, float]]:
    """``(start, end)`` of each caption segment; a segment with no start never shows."""
    spans = []
    for caption in captions:
        start = float(caption.get("start", math.inf))
        spans.append((start, float(caption.get("end", start))))
    return spans


def active_caption_index(captions: Sequence[Mapping[str, Any]], t: float) -> int | None:
    """Index into *captions* of the segment the video shows at *t* (see :class:`CaptionTrack`)."""
    return CaptionTrack(caption_spans(captions)).index_at(t)


def draw_rtl_line_with_highlight(
    draw: Any,
    line_words: list[str],
    font: Any,
    box_x0: int,
    box_x1: int,
    line_y: int,
    default_fill: tuple[int, int, int, int],
    highlight_fill: tuple[int, int, int, int],
    highlight_local_idx: int | None,
    space_w: float,
) -> None:
    """Render a single RTL Arabic line word-by-word, highlighting one word.

    Each word is rendered independently with Pillow so that one word can use a
    different fill colour.  The total line width is measured as a whole string
    first (for accurate centering); individual words are then placed from right
    to left within that measured extent.
    """
    if not line_words:
        return

    joined = " ".join(line_words)
    total_w, _ = measure_text_bbox(draw, joined, font)
    word_widths = [measure_text_bbox(draw, w, font)[0] for w in line_words]

    sum_widths = sum(word_widths)
    n_gaps = max(1, len(line_words) - 1)
    computed_space = max(1.0, (total_w - sum_widths) / n_gaps) if len(line_words) > 1 else 0.0

    # Centre the total line inside the box.
    line_left = box_x0 + max(0, ((box_x1 - box_x0) - total_w) / 2)
    # Start placing from the right edge of the line (RTL visual order).
    current_right = line_left + total_w

    for i, (word, ww) in enumerate(zip(line_words, word_widths, strict=True)):
        left = current_right - ww
        fill = highlight_fill if i == highlight_local_idx else default_fill
        draw.text((left, line_y), word, font=font, fill=fill, direction="rtl")
        current_right -= ww + computed_space


def draw_rtl_line_colored(
    draw: Any,
    line_words: list[str],
    fills: list[tuple[int, int, int, int]],
    font: Any,
    box_x0: int,
    box_x1: int,
    line_y: int,
) -> None:
    """Render one RTL Arabic line word-by-word, each word in its own colour.

    Geometry mirrors :func:`draw_rtl_line_with_highlight` (measure the whole line
    for centring, then place words right-to-left within that extent); the only
    difference is that every word takes an independent colour from *fills*.
    """
    if not line_words:
        return

    joined = " ".join(line_words)
    total_w, _ = measure_text_bbox(draw, joined, font)
    word_widths = [measure_text_bbox(draw, w, font)[0] for w in line_words]

    sum_widths = sum(word_widths)
    n_gaps = max(1, len(line_words) - 1)
    computed_space = max(1.0, (total_w - sum_widths) / n_gaps) if len(line_words) > 1 else 0.0

    line_left = box_x0 + max(0, ((box_x1 - box_x0) - total_w) / 2)
    current_right = line_left + total_w

    for word, ww, fill in zip(line_words, word_widths, fills, strict=True):
        left = current_right - ww
        draw.text((left, line_y), word, font=font, fill=fill, direction="rtl")
        current_right -= ww + computed_space


def draw_caption_progressive(
    draw: Any,
    lines: list[str],
    font: Any,
    box: tuple[int, int, int, int],
    line_spacing: int,
    active_word_idx: int | None,
    *,
    spoken_fill: tuple[int, int, int, int] = COLOUR_CAPTION_TEXT,
    active_fill: tuple[int, int, int, int] = COLOUR_CAPTION_ACTIVE,
    upcoming_fill: tuple[int, int, int, int] = COLOUR_CAPTION_UPCOMING,
) -> None:
    """Draw wrapped caption text with karaoke-style progressive colouring.

    Words before *active_word_idx* use *spoken_fill*, the word at that index uses
    *active_fill*, and later (not-yet-spoken) words use *upcoming_fill*. The index
    counts every whitespace token across *lines* in order — captions carry no
    ayah markers — so it maps directly onto the caption's word-timing list. When
    *active_word_idx* is ``None`` (before the first word) every word is upcoming.
    """
    x0, y0, x1, y1 = box
    _, total_height = _multiline_metrics(draw, lines, font, line_spacing)
    current_y = y0 + max(0, ((y1 - y0) - total_height) / 2)

    global_idx = 0
    for line in lines:
        probe = line if line.strip() else " "
        line_height = measure_text_bbox(draw, probe, font)[1]
        line_words = line.split() if line.strip() else []

        fills: list[tuple[int, int, int, int]] = []
        for _ in line_words:
            if active_word_idx is None or global_idx > active_word_idx:
                fills.append(upcoming_fill)
            elif global_idx == active_word_idx:
                fills.append(active_fill)
            else:
                fills.append(spoken_fill)
            global_idx += 1

        if line_words:
            draw_rtl_line_colored(draw, line_words, fills, font, x0, x1, int(current_y))
        current_y += line_height + line_spacing


def draw_centered_multiline_text_with_highlight(
    draw: Any,
    lines: list[str],
    font: Any,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int, int],
    line_spacing: int,
    highlight_word_idx: int | None = None,
    highlight_fill: tuple[int, int, int, int] = COLOUR_HIGHLIGHT_WORD,
) -> None:
    """Draw multiline RTL text centered inside *box*, highlighting one word.

    When *highlight_word_idx* is ``None`` this behaves identically to
    :func:`draw_centered_multiline_text`.  Otherwise the word at that position
    in the flat word list (ayah-marker tokens are skipped) is rendered in
    *highlight_fill*; every other word uses *fill*.

    Lines that do not contain the highlighted word are rendered as a single
    :py:meth:`~PIL.ImageDraw.ImageDraw.draw.text` call (better Arabic shaping);
    only the line that contains the highlighted word is split word-by-word.
    """
    x0, y0, x1, y1 = box
    _, total_height = _multiline_metrics(draw, lines, font, line_spacing)
    current_y = y0 + max(0, ((y1 - y0) - total_height) / 2)

    space_w = max(2.0, measure_text_bbox(draw, " ", font)[0])

    global_word_idx = 0  # counts only non-marker words

    for line in lines:
        probe = line if line.strip() else " "
        line_height = measure_text_bbox(draw, probe, font)[1]

        line_words = line.split() if line.strip() else []

        # Determine whether the highlighted word falls inside this line.
        highlight_local_idx: int | None = None
        if highlight_word_idx is not None:
            temp_global = global_word_idx
            for local_i, token in enumerate(line_words):
                if _is_ayah_marker(token):
                    continue
                if temp_global == highlight_word_idx:
                    highlight_local_idx = local_i
                    break
                temp_global += 1

        if highlight_local_idx is not None:
            draw_rtl_line_with_highlight(
                draw,
                line_words,
                font,
                x0,
                x1,
                int(current_y),
                fill,
                highlight_fill,
                highlight_local_idx,
                space_w,
            )
        else:
            # No highlight on this line — render as one string (better shaping).
            lw, _ = measure_text_bbox(draw, line, font)
            cx = x0 + max(0, ((x1 - x0) - lw) / 2)
            draw.text(
                (cx, current_y),
                line,
                font=font,
                fill=fill,
                direction="rtl",
                align="center",
            )

        # Advance the global non-marker word counter.
        for token in line_words:
            if not _is_ayah_marker(token):
                global_word_idx += 1

        current_y += line_height + line_spacing


@dataclass(slots=True)
class _FrameLayout:
    """Geometry shared by the ayah card (centre) and the caption band (bottom)."""

    card: tuple[int, int, int, int]
    pad_x: int
    pad_y: int
    gap: int
    caption_band: tuple[int, int, int, int]


def _frame_layout(width: int, height: int, *, reserve_caption_band: bool = True) -> _FrameLayout:
    """Split the frame into a centred card region and a bottom caption band.

    When *reserve_caption_band* is False (recitation mode, or any render without
    live captions) the band collapses to nothing and the card centres in the
    full frame, so there is no dead black strip at the bottom.
    """
    caption_band_h = max(1, int(height * CAPTION_BAND_RATIO)) if reserve_caption_band else 0
    caption_band_top = height - caption_band_h
    region_h = caption_band_top  # space available above the caption band

    card_width = int(width * CARD_WIDTH_RATIO)
    card_height = int(region_h * CARD_REGION_HEIGHT_RATIO)
    card_x0 = (width - card_width) // 2
    card_y0 = max(0, (region_h - card_height) // 2)
    card_x1 = card_x0 + card_width
    card_y1 = card_y0 + card_height

    return _FrameLayout(
        card=(card_x0, card_y0, card_x1, card_y1),
        pad_x=int(card_width * CARD_PADDING_X_RATIO),
        pad_y=int(card_height * CARD_PADDING_Y_RATIO),
        gap=max(12, int(height * SECTION_GAP_RATIO)),
        caption_band=(0, caption_band_top, width, height),
    )


@dataclass(slots=True)
class _CardContent:
    """Resolved header/body/debug text and pagination for one ayah card."""

    header_text: str
    header_font: Any
    header_box: tuple[int, int, int, int]
    body_box: tuple[int, int, int, int]
    body_font: Any
    body_spacing: int
    body_pages: list[list[str]]
    debug_font: Any | None
    debug_lines: list[str]
    debug_height: int


def _card_content(
    draw: Any,
    match: dict[str, Any],
    layout: _FrameLayout,
    height: int,
    font_file: Path,
    debug_detected_text: bool,
) -> _CardContent:
    """Fit the header, body and optional debug text for *match* into the card.

    Shared by :func:`render_frame_pillow` and :func:`_body_pages` so the page
    boundaries used to pick the displayed page match the ones actually drawn.
    """
    card_x0, card_y0, card_x1, card_y1 = layout.card
    card_width = card_x1 - card_x0
    card_height = card_y1 - card_y0
    pad_x, pad_y, gap = layout.pad_x, layout.pad_y, layout.gap

    header_text = ayah_label(match)
    header_font = load_font(font_file, max(18, int(height * HEADER_FONT_RATIO)))
    header_height = measure_text_bbox(draw, header_text, header_font)[1]

    debug_lines: list[str] = []
    debug_font = None
    debug_height = 0
    if debug_detected_text:
        detected_text = str(match.get("detected_text") or "").strip()
        if detected_text:
            debug_font, debug_lines = fit_font_size(
                draw,
                detected_text,
                font_file,
                max_width=card_width - (2 * pad_x),
                max_height=max(32, int(card_height * 0.16)),
                start_size=max(16, int(height * DEBUG_FONT_START_RATIO)),
                min_size=max(12, int(height * DEBUG_FONT_MIN_RATIO)),
            )
            debug_spacing = max(4, int(debug_font.size * LINE_SPACING_RATIO))
            _, debug_height = _multiline_metrics(draw, debug_lines, debug_font, debug_spacing)

    header_box = (
        card_x0 + pad_x,
        card_y0 + pad_y,
        card_x1 - pad_x,
        card_y0 + pad_y + header_height,
    )
    body_top = card_y0 + pad_y + header_height + gap
    body_bottom = card_y1 - pad_y - (debug_height + gap if debug_lines else 0)
    body_box = (card_x0 + pad_x, body_top, card_x1 - pad_x, max(body_top, body_bottom))
    body_font, body_lines = fit_font_size(
        draw,
        str(match.get("_display_text") or ""),
        font_file,
        max_width=body_box[2] - body_box[0],
        max_height=max(40, body_box[3] - body_box[1]),
        start_size=max(24, int(height * BODY_FONT_START_RATIO)),
        min_size=max(16, int(height * BODY_FONT_MIN_RATIO)),
    )
    body_spacing = max(4, int(body_font.size * LINE_SPACING_RATIO))
    body_max_height = max(40, body_box[3] - body_box[1])
    body_pages = paginate_lines(body_lines, draw, body_font, body_spacing, body_max_height)

    return _CardContent(
        header_text=header_text,
        header_font=header_font,
        header_box=header_box,
        body_box=body_box,
        body_font=body_font,
        body_spacing=body_spacing,
        body_pages=body_pages,
        debug_font=debug_font,
        debug_lines=debug_lines,
        debug_height=debug_height,
    )


def _draw_ayah_card(
    draw: Any,
    t: float,
    match: dict[str, Any],
    layout: _FrameLayout,
    height: int,
    font_file: Path,
    debug_detected_text: bool,
    *,
    look: Look = NIGHT_GOLD,
) -> None:
    """Draw the surah/ayah header plus the (paged, highlighted) ayah body."""
    content = _card_content(draw, match, layout, height, font_file, debug_detected_text)
    body_pages = content.body_pages

    # Resolve the active word first: page turns follow the recited word so the
    # displayed page tracks the highlight instead of a fixed time fraction.
    _word_timings = match.get("_word_timings") or []
    _highlight_idx = active_word_timing_index(_word_timings, t) if _word_timings else None

    if len(body_pages) > 1:
        if _highlight_idx is not None:
            _page_idx = _page_index_for_word(body_pages, _highlight_idx)
        else:
            # No active word (silence or missing timings) — fall back to
            # clock-proportional paging so multi-page cards still advance.
            _start = float(match.get("_start_time", t))
            _end = float(match.get("_end_time", _start + 1.0))
            _dur = max(_end - _start, 0.001)
            _progress = max(0.0, min(1.0, (t - _start) / _dur))
            _page_idx = min(int(_progress * len(body_pages)), len(body_pages) - 1)
        display_lines = body_pages[_page_idx]
    else:
        _page_idx = 0
        display_lines = body_pages[0] if body_pages else []

    draw_centered_multiline_text(
        draw, [content.header_text], content.header_font, content.header_box, look.header_text, 0
    )

    # _word_timings carries one entry per canonical (non-marker) word, aligned
    # to the display text upstream (see detection.py), so this index maps
    # directly onto the word the highlight helper colours.
    if _highlight_idx is not None and _page_idx > 0:
        # active_word_timing_index returns an index over the whole ayah's word
        # list, but only one page is drawn. Make it page-local by subtracting
        # the non-marker words on earlier pages; the draw helper leaves the
        # highlight off when the index is not on this page.
        words_before_page = sum(
            _count_non_marker_words(line) for page in body_pages[:_page_idx] for line in page
        )
        _highlight_idx -= words_before_page
    draw_centered_multiline_text_with_highlight(
        draw,
        display_lines,
        content.body_font,
        content.body_box,
        look.body_text,
        content.body_spacing,
        highlight_word_idx=_highlight_idx,
        highlight_fill=look.highlight_word,
    )

    if debug_detected_text and content.debug_lines and content.debug_font is not None:
        card_x0, card_y0, card_x1, card_y1 = layout.card
        card_width = card_x1 - card_x0
        pad_x, pad_y, gap = layout.pad_x, layout.pad_y, layout.gap
        debug_spacing = max(4, int(content.debug_font.size * LINE_SPACING_RATIO))
        debug_label = "النص المكتشف"
        label_font = load_font(font_file, max(14, content.debug_font.size))
        label_width, label_height = measure_text_bbox(draw, debug_label, label_font)
        label_y = card_y1 - pad_y - content.debug_height - gap - label_height
        draw.text(
            (card_x0 + ((card_width - label_width) / 2), label_y),
            debug_label,
            font=label_font,
            fill=look.subtle,
            direction="rtl",
            align="center",
        )
        debug_box = (
            card_x0 + pad_x,
            label_y + label_height + 6,
            card_x1 - pad_x,
            card_y1 - pad_y,
        )
        draw_centered_multiline_text(
            draw,
            content.debug_lines,
            content.debug_font,
            debug_box,
            look.debug_text,
            debug_spacing,
        )


def _draw_placeholder(
    draw: Any,
    title: str,
    layout: _FrameLayout,
    height: int,
    font_file: Path,
    subtitle: str = "",
    *,
    look: Look = NIGHT_GOLD,
) -> None:
    """Draw the centre placeholder shown before the first ayah is detected.

    When *subtitle* is given (lecture intro), *title* is the surah name drawn as
    a headline with the ayah-range line below it; otherwise *title* is centred on
    its own.
    """
    card_x0, card_y0, card_x1, card_y1 = layout.card
    pad_x, pad_y = layout.pad_x, layout.pad_y
    box = (card_x0 + pad_x, card_y0 + pad_y, card_x1 - pad_x, card_y1 - pad_y)

    if not subtitle:
        font, lines = fit_font_size(
            draw,
            title,
            font_file,
            max_width=box[2] - box[0],
            max_height=max(40, box[3] - box[1]),
            start_size=max(24, int(height * PLACEHOLDER_FONT_START_RATIO)),
            min_size=max(18, int(height * PLACEHOLDER_FONT_MIN_RATIO)),
        )
        spacing = max(4, int(font.size * LINE_SPACING_RATIO))
        draw_centered_multiline_text(draw, lines, font, box, look.placeholder_text, spacing)
        return

    inner_w = box[2] - box[0]
    inner_h = box[3] - box[1]
    gap = layout.gap

    title_font, title_lines = fit_font_size(
        draw,
        title,
        font_file,
        max_width=inner_w,
        max_height=max(40, int(inner_h * 0.5)),
        start_size=max(24, int(height * PLACEHOLDER_FONT_START_RATIO)),
        min_size=max(18, int(height * PLACEHOLDER_FONT_MIN_RATIO)),
    )
    title_spacing = max(4, int(title_font.size * LINE_SPACING_RATIO))
    _, title_h = _multiline_metrics(draw, title_lines, title_font, title_spacing)

    sub_font, sub_lines = fit_font_size(
        draw,
        subtitle,
        font_file,
        max_width=inner_w,
        max_height=max(32, int(inner_h * 0.4)),
        start_size=max(18, int(height * BODY_FONT_START_RATIO)),
        min_size=max(14, int(height * BODY_FONT_MIN_RATIO)),
    )
    sub_spacing = max(4, int(sub_font.size * LINE_SPACING_RATIO))
    _, sub_h = _multiline_metrics(draw, sub_lines, sub_font, sub_spacing)

    block_h = title_h + gap + sub_h
    top = box[1] + max(0, (inner_h - block_h) // 2)
    title_box = (box[0], top, box[2], top + title_h)
    sub_box = (box[0], top + title_h + gap, box[2], top + title_h + gap + sub_h)

    draw_centered_multiline_text(
        draw, title_lines, title_font, title_box, look.header_text, title_spacing
    )
    draw_centered_multiline_text(
        draw, sub_lines, sub_font, sub_box, look.placeholder_text, sub_spacing
    )


def _caption_window(
    word_timings: list[dict[str, Any]], active_idx: int | None, max_words: int
) -> tuple[list[str], int | None]:
    """Return ``(display_words, local_active_idx)`` for a bounded caption view.

    Short captions (``<= max_words``) show whole. Longer ones are paged in fixed
    chunks of *max_words*; the chunk holding the spoken word is shown, so the
    caption stays inside the band and the text shifts only when the highlight
    crosses a chunk boundary — not on every word. *local_active_idx* is the
    active word's index within the returned slice (``None`` before the first
    word, or when the active word falls outside the shown chunk).
    """
    words = [str(w.get("word") or "") for w in word_timings]
    if len(words) <= max_words:
        return words, active_idx

    anchor = active_idx if active_idx is not None else 0
    page = anchor // max_words
    lo = page * max_words
    hi = min(lo + max_words, len(words))
    local = None if active_idx is None or not (lo <= active_idx < hi) else active_idx - lo
    return words[lo:hi], local


def _draw_caption(
    image: Any,
    draw: Any,
    caption_text: str,
    layout: _FrameLayout,
    width: int,
    height: int,
    font_file: Path,
    *,
    word_timings: list[dict[str, Any]] | None = None,
    t: float = 0.0,
    look: Look = NIGHT_GOLD,
) -> None:
    """Draw the live-transcript caption inside the bottom band.

    When *word_timings* is given, the caption is drawn karaoke-style: the word
    being spoken at time *t* is accented and the rest fade between spoken and
    upcoming (see :func:`draw_caption_progressive`). The caption text is built
    from the same word tokens upstream, so token N is timing N.
    """
    _, image_module, image_draw, _, _ = _frame_dependencies()
    bx0, by0, bx1, by1 = layout.caption_band

    overlay = image_module.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = image_draw.Draw(overlay, "RGBA")
    overlay_draw.rectangle((bx0, by0, bx1, by1), fill=look.caption_bg)
    image.alpha_composite(overlay)

    pad_x = int(width * CAPTION_PADDING_X_RATIO)
    pad_top = max(8, int((by1 - by0) * 0.12))
    # Raise the text off the bottom edge so a crop-to-fill player can't clip it,
    # while the translucent strip itself may safely run to the frame edge.
    safe_bottom = max(pad_top, int(height * CAPTION_SAFE_BOTTOM_RATIO))
    text_box = (bx0 + pad_x, by0 + pad_top, bx1 - pad_x, by1 - safe_bottom)

    # Page long captions to a bounded chunk around the spoken word so the text
    # never overflows the band; plain (untimed) captions render whole.
    if word_timings:
        active_idx = active_word_timing_index(word_timings, t)
        display_words, local_active = _caption_window(word_timings, active_idx, MAX_CAPTION_WORDS)
        text = " ".join(display_words)
    else:
        text = caption_text
        local_active = None

    font, lines = fit_font_size(
        draw,
        text,
        font_file,
        max_width=text_box[2] - text_box[0],
        max_height=max(20, text_box[3] - text_box[1]),
        start_size=max(16, int(height * CAPTION_FONT_START_RATIO)),
        min_size=max(12, int(height * CAPTION_FONT_MIN_RATIO)),
    )
    spacing = max(4, int(font.size * LINE_SPACING_RATIO))
    if word_timings:
        draw_caption_progressive(
            draw,
            lines,
            font,
            text_box,
            spacing,
            local_active,
            spoken_fill=look.caption_text,
            active_fill=look.caption_active,
            upcoming_fill=look.caption_upcoming,
        )
    else:
        draw_centered_multiline_text(draw, lines, font, text_box, look.caption_text, spacing)


def render_frame_pillow(
    t: float,
    match: dict[str, Any] | None,
    width: int,
    height: int,
    font_file: Path,
    *,
    caption_text: str = "",
    caption_word_timings: list[dict[str, Any]] | None = None,
    title: str = DEFAULT_PLACEHOLDER_TITLE,
    placeholder_subtitle: str = "",
    debug_detected_text: bool = False,
    reserve_caption_band: bool = True,
    look: Look = NIGHT_GOLD,
    base: BaseLayer | None = None,
) -> Any:
    """Render one styled frame as a BGR numpy array for OpenCV.

    The frame has two zones: a centred card showing the active ayah (surah name,
    ayah number and the Qur'an text) — or *title* as a placeholder when no ayah
    has been detected yet — and a bottom band showing the live transcript
    *caption_text* for the current moment. When *reserve_caption_band* is False
    the band is dropped and the card centres in the full frame.

    *look* gives every colour and the background. The background and the card
    panel come from a cached base layer (see :mod:`qurantext.core.backgrounds`),
    so each frame only draws its text on a copy of it. *base* hands in that
    layer (from :func:`frame_base_layer`, for this look, size and band), so a
    whole render draws on the one layer it fetched up front even if another
    surface evicts it from the cache meanwhile.
    """
    np, _, image_draw, _, _ = _frame_dependencies()

    layout = _frame_layout(width, height, reserve_caption_band=reserve_caption_band)
    if base is None:
        from qurantext.core.backgrounds import base_layer

        base = base_layer(look, width, height, layout.card, _card_radius(width, height))
    image = base.image.copy()
    draw = image_draw.Draw(image)

    if match is not None:
        _draw_ayah_card(draw, t, match, layout, height, font_file, debug_detected_text, look=look)
    else:
        _draw_placeholder(
            draw,
            title or DEFAULT_PLACEHOLDER_TITLE,
            layout,
            height,
            font_file,
            subtitle=placeholder_subtitle,
            look=look,
        )

    if caption_text:
        _draw_caption(
            image,
            draw,
            caption_text,
            layout,
            width,
            height,
            font_file,
            word_timings=caption_word_timings,
            t=t,
            look=look,
        )

    rgb = image.convert("RGB")
    frame = np.array(rgb)
    return frame[:, :, ::-1].copy()


def _card_radius(width: int, height: int) -> int:
    return max(18, int(min(width, height) * CARD_RADIUS_RATIO))


def frame_base_layer(
    look: Look, width: int, height: int, *, reserve_caption_band: bool
) -> BaseLayer:
    """The cached background + card this look draws at this size (for the review window)."""
    _frame_dependencies()
    from qurantext.core.backgrounds import base_layer

    layout = _frame_layout(width, height, reserve_caption_band=reserve_caption_band)
    return base_layer(look, width, height, layout.card, _card_radius(width, height))


def _body_pages(
    match: dict[str, Any],
    width: int,
    height: int,
    font_file: Path,
    debug_detected_text: bool,
    *,
    reserve_caption_band: bool = True,
) -> list[list[str]]:
    """Return the paginated body lines a match would fill, without rendering it.

    Mirrors the pagination ``render_frame_pillow`` performs so page counts and
    per-page word counts stay consistent with what is actually drawn.
    """
    _, image_module, image_draw, _, _ = _frame_dependencies()
    probe = image_module.new("RGBA", (width, height))
    draw = image_draw.Draw(probe)

    layout = _frame_layout(width, height, reserve_caption_band=reserve_caption_band)
    content = _card_content(draw, match, layout, height, font_file, debug_detected_text)
    return content.body_pages or [[]]


def _start_frame_encoder(
    audio_path: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    log_handle: Any,
) -> Any:
    """Start FFmpeg reading raw BGR frames on stdin and writing the final MP4.

    Frames go straight from Pillow into the H.264 encoder, so the video is
    encoded exactly once. The previous route wrote an OpenCV ``mp4v`` (MPEG-4
    Part 2) intermediate beside the user's output and then had FFmpeg decode and
    re-encode it, which cost a second full encode, a gigabyte-scale temp file per
    render, and a dependency on an OpenCV build with video support.
    """
    ffmpeg_path = require_binary("ffmpeg", "Install FFmpeg and try again.")
    command = [
        ffmpeg_path,
        "-y",
        # Raw frames on stdin. render_frame_pillow hands back BGR, so declare it
        # rather than paying for a channel swap on every frame.
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{width}x{height}",
        "-framerate",
        str(fps),
        "-i",
        "pipe:0",
        "-i",
        str(audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        # FFmpeg is chatty and a render can run for minutes; send its output to a
        # file rather than a pipe nobody drains, which would eventually block it.
        stdout=log_handle,
        stderr=log_handle,
    )


def write_frame_video(
    matches: list[dict[str, Any]],
    duration: float,
    audio_path: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    font_file: Path,
    *,
    captions: list[dict[str, Any]] | None = None,
    title: str = DEFAULT_PLACEHOLDER_TITLE,
    debug_detected_text: bool = False,
    log_path: Path | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
    look: Look = NIGHT_GOLD,
) -> tuple[str, ...]:
    """Render every frame and stream it into FFmpeg, producing the final MP4.

    The centre ayah card is *latched*: the most recently started match is shown
    and held until the next match starts, so it only changes when a new ayah is
    detected (a placeholder *title* shows before the first one). The bottom band
    shows the live-transcript *captions* segment for the current moment.

    Frames with identical content are rendered once and written multiple times,
    reducing per-frame PIL overhead for long videos with static ayah cards.

    Deliberately single-threaded. On the 13-minute lecture this draws 1,319
    distinct frames of 23,445 at 55 ms each, about 72 s against roughly 39 s for
    the encode, so drawing is no longer dominant. A process pool would also have
    to move 8.2 GB of frames between processes to save that. See
    docs/findings/parallel-rendering.md for when to revisit.
    """
    total_frames = max(1, int(math.ceil(duration * fps)))

    sorted_matches = sorted(matches, key=lambda m: float(m.get("_start_time", math.inf)))
    caption_list = sorted(captions or [], key=lambda c: float(c.get("start", math.inf)))
    # Reserve the bottom caption band only when there are captions to show.
    # Recitation renders have none, so the ayah card centres in the full frame
    # instead of leaving a black strip where the transcript would be.
    reserve_caption_band = bool(caption_list)

    # Lecture intro: when live captions are present the opening placeholder
    # announces the surah and the range of ayat the lecture ponders instead of
    # the generic title. Recitation renders (no captions) keep the plain title.
    placeholder_title, placeholder_subtitle = placeholder_lines(
        sorted_matches, reserve_caption_band=reserve_caption_band, title=title
    )

    # Pre-compute paginated body lines for every unique active match. Caching the
    # pages (not just the count) lets page boundaries be derived from the active
    # word, matching how render_frame_pillow chooses the displayed page.
    page_cache: dict[int, list[list[str]]] = {}

    def _get_pages(match: dict[str, Any] | None) -> list[list[str]]:
        if match is None:
            return [[]]
        mid = id(match)
        if mid not in page_cache:
            page_cache[mid] = _body_pages(
                match,
                width,
                height,
                font_file,
                debug_detected_text,
                reserve_caption_band=reserve_caption_band,
            )
        return page_cache[mid]

    # First pass: scan all frame timestamps and record render-event boundaries.
    # An event boundary occurs when the latched match, the displayed page, the
    # actively highlighted card word, the active caption, or the spoken caption
    # word changes.
    n_matches = len(sorted_matches)
    # (frame, match, caption_segment)
    events: list[tuple[int, dict[str, Any] | None, dict[str, Any] | None]] = []
    last_key: tuple[int | None, int, int | None, int, int | None] = (-2, -1, None, -2, None)
    card_ptr = -1  # index of the latched match, -1 while showing the placeholder
    caption_track = CaptionTrack(caption_spans(caption_list))

    for fi in range(total_frames):
        t = fi / fps
        # Latch: advance to the most recently started match (holds across gaps).
        while card_ptr + 1 < n_matches and float(sorted_matches[card_ptr + 1]["_start_time"]) <= t:
            card_ptr += 1
        match = sorted_matches[card_ptr] if card_ptr >= 0 else None

        # Captions are not latched — they roll with the speech and clear in gaps.
        cap_index = caption_track.index_at(t)
        cap_active = -1 if cap_index is None else cap_index
        caption_seg = caption_list[cap_active] if cap_active >= 0 else None
        # Re-render on each spoken caption word so the karaoke highlight advances.
        _cap_wt = caption_seg.get("word_timings") if caption_seg else None
        cap_word = active_word_timing_index(_cap_wt, t) if _cap_wt else None

        pages = _get_pages(match)
        n_pages = max(1, len(pages))
        # Include the active word index so a re-render fires on each word change.
        _wt = list(match.get("_word_timings") or []) if match is not None else []
        active_word = active_word_timing_index(_wt, t) if _wt else None
        if match is not None and n_pages > 1:
            if active_word is not None:
                page_idx = _page_index_for_word(pages, active_word)
            else:
                _start = float(match.get("_start_time", t))
                _end = float(match.get("_end_time", t + 1.0))
                _dur = max(_end - _start, 0.001)
                _progress = max(0.0, min(1.0, (t - _start) / _dur))
                page_idx = min(int(_progress * n_pages), n_pages - 1)
        else:
            page_idx = 0
        key = (
            id(match) if match is not None else None,
            page_idx,
            active_word,
            cap_active,
            cap_word,
        )
        if key != last_key:
            events.append((fi, match, caption_seg))
            last_key = key

    # Second pass: render once per event and write all frames for that segment.
    t0 = time.monotonic()
    n_events = len(events)
    report_every = max(1, n_events // 10)

    # The layer every frame starts from, built (and any photo decoded) before
    # FFmpeg starts and handed to every frame, so its warnings (a photo that
    # could not be read, say) are the render's, as the frames saw them — even
    # if the review window's preview evicts it from the shared cache meanwhile.
    layer = frame_base_layer(look, width, height, reserve_caption_band=reserve_caption_band)
    layer_warnings = layer.warnings

    encoder_log = log_path or output_path.with_suffix(".ffmpeg.log")
    encoder_log.parent.mkdir(parents=True, exist_ok=True)
    log_handle = encoder_log.open("wb")

    def _encoder_failure(reason: str) -> RuntimeError:
        log_handle.flush()
        try:
            tail = encoder_log.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        except OSError:
            tail = []
        details = "\n".join(tail[-12:]) or "no FFmpeg output was captured"
        return RuntimeError(f"{reason}\n{details}")

    process: Any = None
    completed = False
    try:
        process = _start_frame_encoder(audio_path, output_path, width, height, fps, log_handle)
        for ev_idx, (ev_start, ev_match, ev_caption) in enumerate(events):
            # Checked per event rather than per frame: an event is one Pillow
            # render, so this bounds how long Cancel takes to take effect while
            # costing nothing measurable.
            if cancel is not None:
                cancel.raise_if_cancelled("render")
            ev_end = events[ev_idx + 1][0] if ev_idx + 1 < n_events else total_frames
            ev_caption_text = str(ev_caption["text"]) if ev_caption else ""
            ev_caption_wt = ev_caption.get("word_timings") if ev_caption else None
            frame = render_frame_pillow(
                ev_start / fps,
                ev_match,
                width,
                height,
                font_file,
                caption_text=ev_caption_text,
                caption_word_timings=ev_caption_wt,
                title=placeholder_title,
                placeholder_subtitle=placeholder_subtitle,
                debug_detected_text=debug_detected_text,
                reserve_caption_band=reserve_caption_band,
                look=look,
                base=layer,
            )
            # Serialise once, then hand the encoder the same bytes for every
            # frame this event covers. A latched card with no word highlight can
            # span the whole video as a single event, so cancellation is also
            # checked inside this loop — once per second of video — or a long
            # static card would be uninterruptible however often the outer loop
            # polls.
            payload = frame.tobytes()
            try:
                for offset in range(ev_end - ev_start):
                    if cancel is not None and offset and offset % fps == 0:
                        cancel.raise_if_cancelled("render")
                    process.stdin.write(payload)
            except (BrokenPipeError, OSError) as error:
                raise _encoder_failure("FFmpeg stopped while frames were being written:") from error

            if ev_idx % report_every == 0 or ev_idx == n_events - 1:
                elapsed = time.monotonic() - t0
                pct = (ev_idx + 1) / n_events
                eta = (elapsed / pct - elapsed) if pct > 0 else 0
                report(
                    progress,
                    "render",
                    f"  Segments {ev_idx + 1:>5}/{n_events}"
                    f"  ({ev_end:>6}/{total_frames} frames)"
                    f"  elapsed {elapsed:.0f}s",
                    fraction=pct,
                    eta_seconds=eta,
                    done=ev_idx == n_events - 1,
                )

        # Closing stdin tells FFmpeg the stream ended; it then finalises the
        # container (moov atom, +faststart) before exiting.
        process.stdin.close()
        if process.wait() != 0:
            raise _encoder_failure(
                f"FFmpeg exited with status {process.returncode} while encoding the video:"
            )
        completed = True
    finally:
        if process is not None:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            if process.poll() is None:
                process.kill()
                process.wait()
        log_handle.close()
        # A killed encoder leaves a container it never finalised — a few dozen
        # bytes that no player opens. Cancelling should leave nothing behind
        # rather than a broken file where the user expects their video.
        if not completed:
            output_path.unlink(missing_ok=True)

    return layer_warnings


def render_frame_video(
    audio_path: Path,
    matches: list[dict[str, Any]],
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    font_file: Path,
    keep_temp: bool = False,
    debug_detected_text: bool = False,
    captions: list[dict[str, Any]] | None = None,
    title: str = DEFAULT_PLACEHOLDER_TITLE,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
    look: Look = NIGHT_GOLD,
    look_warnings: list[str] | None = None,
) -> float:
    """Render a styled frame-by-frame video with its audio. Returns the duration.

    *look_warnings*, when given, is extended with the look's warning codes (a
    background photo that could not be used, say), so the caller can show them
    while the return value stays the duration.
    """
    _frame_dependencies()
    _require_raqm_support()
    require_binary("ffmpeg", "Install FFmpeg and try again.")
    require_binary("ffprobe", "Install FFmpeg/ffprobe and try again.")

    duration = get_audio_duration(audio_path)
    # The centre card is latched (holds until the next detection), so gap
    # bridging is unnecessary and would only move the detection boundaries.
    valid_matches = validated_matches(matches, bridge_gaps=False)
    if not valid_matches and matches:
        warn(
            "No valid timed matches remained for the frame renderer; rendering a dark video with audio only."
        )

    total_frames = max(1, int(math.ceil(duration * fps)))
    report(
        progress,
        "render",
        f"  Video: {duration:.1f}s  ×  {fps} fps  =  {total_frames:,} frames  ({width}×{height})",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # The encoder log is the only intermediate left, and it goes to a temp
    # directory so the user's output folder holds deliverables only.
    log_dir = Path(tempfile.mkdtemp(prefix="qurantext-render-"))
    log_path = log_dir / f"{output_path.stem}.ffmpeg.log"

    grand_start = time.monotonic()

    try:
        report(progress, "render", "  Rendering frames and encoding H.264...")
        codes = write_frame_video(
            valid_matches,
            duration,
            audio_path,
            output_path,
            width,
            height,
            fps,
            font_file,
            captions=captions,
            title=title,
            debug_detected_text=debug_detected_text,
            log_path=log_path,
            progress=progress,
            cancel=cancel,
            look=look,
        )
        if look_warnings is not None:
            look_warnings.extend(codes)
    finally:
        if keep_temp:
            report(progress, "render", f"FFmpeg log kept at: {log_path}")
        else:
            log_path.unlink(missing_ok=True)
            with suppress(OSError):
                log_dir.rmdir()

    total_elapsed = time.monotonic() - grand_start
    mins, secs = divmod(int(total_elapsed), 60)
    rendered_fps = total_frames / total_elapsed if total_elapsed > 0 else 0.0
    report(
        progress,
        "render",
        f"  Total render time: {mins}m {secs:02d}s  ({rendered_fps:.1f} fps)",
    )

    return duration


def validate_font_file(font_file: Path) -> None:
    validate_input_file(font_file, "Font file")
    if font_file.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
        warn(
            f"Font file '{font_file.name}' does not use a typical TTF/OTF/TTC extension; attempting to load it anyway."
        )

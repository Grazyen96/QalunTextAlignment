"""Emit the format-neutral edit-spec package (architecture §8).

Every render job must yield TWO outputs: the baked MP4 (``core.video_renderer``)
and an *editable* project. Per §9 the editable project is not an interchange
file (FCP7 XML/OTIO/AAF carry only cuts, not editable captions/graphics/
keyframes) — it is built inside Premiere by a UXP panel that consumes the
edit-spec JSON this module writes. The spec stays free of anything
Premiere-specific so a Resolve generator could consume it later.

What gets emitted, per §8:

``project``
    fps/width/height, resolved with the same precedence as the CLI renderer
    (named preset > explicit values > portrait ``social`` for lecture/
    recitation jobs > ``settings.video``).
``media``
    The job's audio, staged into the package. When the render spliced the
    shipped basmala in front of the recitation (``core.basmala``), the spec
    uses the SAME shifted timeline and the concatenated basmala+recitation
    audio — a throwaway temp for the renderer — is kept as the job's audio.
    The rendered MP4 (when available) is staged as a reference/proxy video.
``tracks``
    * ``captions`` cues — recitation: one cue per AYAH carrying the canonical
      text (captions must stay editable for human correction); lecture: one
      cue per WhisperX subtitle line. Cue ``ref`` (``"surah:ayah"``) is an
      additive extension so generators can drop per-ayah sequence markers.
    * ``graphics`` items — an ``ayah_overlay`` per displayed card page and a
      ``word_highlight`` whose keyframes are keyed by the stable
      ``surah:ayah:word`` IDs (§5). Component packs with pre-shaped SVG assets
      do not exist yet, so as the documented interim each card page is
      rendered to a transparent PNG through the existing
      ``core.frame_renderer`` drawing path and referenced via ``asset``; the
      field names follow §8 so shaped assets can swap in later.

Times in the spec are float seconds (format-neutral); quantizing to frames is
the generators' job. The emitter only VALIDATES against the project fps and
warns about cues shorter than one frame or word keyframes that collide after
rounding.

Timeline semantics mirror the frame renderer exactly: cards are *latched* — a
card displays from its own start until the next card's start (the last card
holds to the end of the audio) — so overlay windows and per-ayah caption cues
tile the recitation gaplessly, just like the rendered MP4.

Word identity: ``word_timings`` carry no per-word ayah refs, so ayah
boundaries are re-derived from the canonical per-ayah word counts in the
SQLite store (``data.quran_db``), which the detection step's timings are
built against (both exclude the inline ayah-number markers). Preamble cards
(istiʿādha/basmala) have no canonical Quran identity; their refs use the
additive ``preamble:<kind>`` scheme and their highlight keyframes are keyed
``preamble:<kind>:<n>``.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qurantext import __version__
from qurantext.config.paths import QURAN_DB_PATH
from qurantext.config.settings import DEFAULT_VIDEO_FONT_FILE, VIDEO_PRESETS, get_settings
from qurantext.core.basmala import load_matches_meta, maybe_prepend_basmala
from qurantext.core.video_common import (
    get_audio_duration,
    load_caption_segments,
    load_matches,
    validate_dimensions,
    validate_fps,
    validate_input_file,
    validated_matches,
    warn,
)
from qurantext.data.quran_db import connect as connect_quran_db
from qurantext.io.writers import write_json, write_text_srt, write_word_srt

SPEC_VERSION = "1.0"
# MOGRT identifiers per the §8 sketch; the panel falls back to placing the
# interim PNG assets directly until these templates are authored (§9).
AYAH_OVERLAY_MOGRT = "ayah_display_v1"
WORD_HIGHLIGHT_MOGRT = "highlight_v1"
OVERLAY_COLOR = "#FFFFFF"

README_TEXT = """Qalun edit-spec package
=======================

This folder is a self-contained working folder for building the editable
Premiere project that matches the rendered MP4.

Contents
  edit_spec.json   format-neutral edit spec (all media paths are relative
                   to this folder; times are float seconds)
  audio/           the job's audio (already includes the prepended basmala
                   when the render spliced one in)
  video/           the rendered MP4, as a reference/proxy track
  overlays/        transparent PNG cards, one per displayed ayah-card page
  captions/        the caption cues as SRT (UTF-8 with BOM for Premiere)

How to use
  1. Open Premiere Pro and the Qalun UXP panel.
  2. In the panel choose "Load edit_spec.json" and pick the file in this
     folder. The panel imports the media, builds the sequence, captions,
     overlays and highlight keyframes, and saves project.prproj.

Manual fallback (no panel)
  1. Import audio/, video/ and overlays/ into a new project.
  2. Create a sequence from the reference video so the settings match.
  3. Import captions/*.srt onto a caption track for editable captions.
  4. Place the overlay PNGs on V2 using the in/out times from
     edit_spec.json (tracks -> graphics -> ayah_overlay items).
"""


@dataclass(frozen=True, slots=True)
class EditSpecExport:
    """Result of writing one edit-spec package."""

    package_dir: Path
    spec_path: Path
    spec: dict[str, Any]
    warnings: list[str]


def resolve_export_format(
    mode: str,
    *,
    preset: str | None = None,
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
) -> tuple[int, int, int]:
    """Resolve (width, height, fps) with the CLI renderer's precedence.

    Mirrors ``cli.main._resolve_preset``: a named preset wins outright, then
    explicit per-dimension values, then the portrait ``social`` preset for
    lecture/recitation jobs (phone-first framing), then ``settings.video``.
    """
    if preset is not None:
        return VIDEO_PRESETS[preset]

    settings = get_settings()
    if mode in ("lecture", "recitation"):
        default_width, default_height, default_fps = VIDEO_PRESETS["social"]
    else:
        default_width = settings.video.width
        default_height = settings.video.height
        default_fps = settings.video.fps

    return (
        width if width is not None else default_width,
        height if height is not None else default_height,
        fps if fps is not None else default_fps,
    )


def card_ref(match: dict[str, Any]) -> str:
    """Return the stable ref for one card: ``25:3``, ``25:1-5``, ``preamble:basmala``."""
    if match.get("kind") == "preamble":
        return f"preamble:{match.get('preamble_kind') or 'unknown'}"
    surah = match.get("surah_num")
    from_ayah = match.get("from_ayah")
    to_ayah = match.get("to_ayah")
    if from_ayah == to_ayah:
        return f"{surah}:{from_ayah}"
    return f"{surah}:{from_ayah}-{to_ayah}"


def _overlay_stem(match: dict[str, Any]) -> str:
    """Filesystem-safe stem for a card's overlay assets."""
    if match.get("kind") == "preamble":
        return f"preamble_{match.get('preamble_kind') or 'unknown'}"
    surah = int(match.get("surah_num") or 0)
    from_ayah = int(match.get("from_ayah") or 0)
    to_ayah = int(match.get("to_ayah") or from_ayah)
    if from_ayah == to_ayah:
        return f"{surah:03d}_{from_ayah:03d}"
    return f"{surah:03d}_{from_ayah:03d}-{to_ayah:03d}"


def latched_card_windows(cards: list[dict[str, Any]], duration: float) -> list[tuple[float, float]]:
    """Return each card's display window under the frame renderer's latching.

    A card holds from its own detected start until the next card's start (the
    renderer never blanks between detections); the last card holds to the end
    of the audio. Consequently the windows tile ``[first_start, duration]``
    with no gaps — matching the rendered MP4 frame for frame.
    """
    windows: list[tuple[float, float]] = []
    for index, card in enumerate(cards):
        start = float(card["_start_time"])
        if index + 1 < len(cards):
            end = float(cards[index + 1]["_start_time"])
        else:
            end = max(duration, float(card["_end_time"]))
        windows.append((start, max(start, end)))
    return windows


def ayah_rows_for_card(
    conn: sqlite3.Connection, surah_num: int, from_ayah: int, to_ayah: int
) -> list[sqlite3.Row]:
    """Fetch canonical (ayah_num, text_raw, word_count) rows for a card's range."""
    rows = conn.execute(
        "SELECT ayah_num, text_raw, word_count FROM ayat"
        " WHERE surah_num = ? AND ayah_num BETWEEN ? AND ? ORDER BY ayah_num",
        (surah_num, from_ayah, to_ayah),
    ).fetchall()
    expected = to_ayah - from_ayah + 1
    if len(rows) != expected:
        raise ValueError(
            f"Quran store returned {len(rows)} ayat for {surah_num}:{from_ayah}-{to_ayah}"
            f" (expected {expected}); rebuild data/quran.sqlite with build-db."
        )
    return rows


def word_ids_for_card(match: dict[str, Any], ayah_rows: list[sqlite3.Row] | None) -> list[str]:
    """Return the ordered ``surah:ayah:word`` IDs covering one card.

    Ayah boundaries are re-derived from the canonical per-ayah word counts —
    ``word_timings`` themselves carry no ayah refs. Preamble cards have no
    canonical identity, so their words use the additive ``preamble:<kind>:<n>``
    scheme.
    """
    if match.get("kind") == "preamble":
        prefix = card_ref(match)
        return [f"{prefix}:{n}" for n in range(1, len(match.get("_word_timings") or []) + 1)]

    surah_num = match.get("surah_num")
    ids: list[str] = []
    for row in ayah_rows or []:
        ids.extend(
            f"{surah_num}:{row['ayah_num']}:{word_num}"
            for word_num in range(1, int(row["word_count"]) + 1)
        )
    return ids


def ayah_caption_cues(
    match: dict[str, Any],
    window: tuple[float, float],
    ayah_rows: list[sqlite3.Row] | None,
) -> list[dict[str, Any]]:
    """Build the per-ayah caption cues for one recitation card.

    One cue per ayah, carrying the CANONICAL text (never the ASR's version).
    Cue boundaries come from the aligned word timings: ayah *k* begins on its
    first word's onset (the card's first ayah begins at the card window start)
    and ends where the next ayah begins, so cues tile the card gaplessly. When
    the card's timings cannot be split (no timings, or a count mismatch versus
    the canonical word counts) one cue spans the whole card instead.
    """
    win_in, win_out = window

    if match.get("kind") == "preamble":
        return [
            {
                "in": round(win_in, 3),
                "out": round(win_out, 3),
                "text": str(match.get("_display_text") or ""),
                "ref": card_ref(match),
            }
        ]

    word_timings = match.get("_word_timings") or []
    rows = ayah_rows or []
    counts = [int(row["word_count"]) for row in rows]
    if not rows:
        return []
    if not word_timings or sum(counts) != len(word_timings):
        warn(
            f"Card {card_ref(match)}: word timings ({len(word_timings)}) do not cover the"
            f" canonical word count ({sum(counts)}); emitting one caption cue for the card."
        )
        return [
            {
                "in": round(win_in, 3),
                "out": round(win_out, 3),
                "text": "\n".join(str(row["text_raw"]) for row in rows),
                "ref": card_ref(match),
            }
        ]

    starts: list[float] = []
    offset = 0
    for index, count in enumerate(counts):
        if index == 0:
            starts.append(win_in)
        else:
            starts.append(float(word_timings[offset]["start"]))
        offset += count

    cues: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        cue_in = starts[index]
        cue_out = starts[index + 1] if index + 1 < len(rows) else win_out
        cues.append(
            {
                "in": round(cue_in, 3),
                "out": round(cue_out, 3),
                "text": str(row["text_raw"]),
                "ref": f"{match.get('surah_num')}:{row['ayah_num']}",
            }
        )
    return cues


def lecture_caption_cues(caption_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One editable cue per WhisperX subtitle line (they always need correction)."""
    return [
        {
            "in": round(float(segment["start"]), 3),
            "out": round(float(segment["end"]), 3),
            "text": str(segment["text"]),
        }
        for segment in caption_segments
    ]


def word_highlight_item(
    match: dict[str, Any], word_ids: list[str], ayah_asset: str
) -> dict[str, Any] | None:
    """Build the §8 ``word_highlight`` item for one card, or ``None``.

    Emits one ``{word, in, out}`` keyframe per aligned word, keyed by the
    stable word ID. When the ID list does not match the timing list the item
    is dropped with a warning rather than mis-attributing highlights.
    """
    word_timings = match.get("_word_timings") or []
    if not word_timings:
        return None
    if len(word_ids) != len(word_timings):
        warn(
            f"Card {card_ref(match)}: cannot key highlights — {len(word_timings)} word"
            f" timings vs {len(word_ids)} canonical words; skipping word_highlight."
        )
        return None
    keyframes = [
        {
            "word": word_id,
            "in": round(float(timing["start"]), 3),
            "out": round(float(timing["end"]), 3),
        }
        for word_id, timing in zip(word_ids, word_timings, strict=True)
    ]
    return {
        "type": "word_highlight",
        "mogrt": WORD_HIGHLIGHT_MOGRT,
        "ayah_asset": ayah_asset,
        "ref": card_ref(match),
        "keyframes": keyframes,
    }


def page_time_windows(
    pages: list[list[str]],
    word_timings: list[dict[str, Any]],
    window: tuple[float, float],
) -> list[tuple[int, float, float]]:
    """Split a card's display window into one (page_idx, in, out) per page.

    Mirrors the renderer's word-driven paging: a page turn happens when the
    first word of the next page starts. Cards without word timings fall back
    to the renderer's clock-proportional paging (equal splits).
    """
    from qurantext.core.frame_renderer import _count_non_marker_words

    win_in, win_out = window
    if len(pages) <= 1:
        return [(0, win_in, win_out)]

    starts: list[float] = [win_in]
    if word_timings:
        cumulative = 0
        for page in pages[:-1]:
            cumulative += sum(_count_non_marker_words(line) for line in page)
            index = min(cumulative, len(word_timings) - 1)
            starts.append(float(word_timings[index]["start"]))
    else:
        span = (win_out - win_in) / len(pages)
        starts.extend(win_in + span * page_num for page_num in range(1, len(pages)))

    windows: list[tuple[int, float, float]] = []
    for page_idx in range(len(pages)):
        page_in = starts[page_idx]
        page_out = starts[page_idx + 1] if page_idx + 1 < len(pages) else win_out
        windows.append((page_idx, page_in, max(page_in, page_out)))
    return windows


def card_body_pages(
    match: dict[str, Any],
    width: int,
    height: int,
    font_file: Path,
    *,
    reserve_caption_band: bool,
) -> list[list[str]]:
    """Paginate a card's body exactly as the frame renderer would draw it."""
    from qurantext.core.frame_renderer import _body_pages

    return _body_pages(
        match,
        width,
        height,
        font_file,
        False,
        reserve_caption_band=reserve_caption_band,
    )


def render_card_overlay_png(
    match: dict[str, Any],
    page_idx: int,
    width: int,
    height: int,
    font_file: Path,
    out_path: Path,
    *,
    reserve_caption_band: bool,
) -> None:
    """Render one card page as a full-frame transparent PNG (interim §8 asset).

    Draws through the same ``core.frame_renderer`` helpers the MP4 render uses
    (card box, header, paginated RTL body — no word highlight, since the
    highlight is keyframed separately), on a transparent background so the
    panel can drop the file on a track above the reference video. Full-frame
    means the §8 ``transform`` is simply the frame centre at scale 1.
    """
    from qurantext.core.frame_renderer import (
        CARD_RADIUS_RATIO,
        COLOUR_BODY_TEXT,
        COLOUR_CARD,
        COLOUR_HEADER_TEXT,
        _card_content,
        _frame_dependencies,
        _frame_layout,
        _require_raqm_support,
        draw_centered_multiline_text,
        draw_rounded_rectangle,
    )

    _require_raqm_support()
    _, image_module, image_draw, _, _ = _frame_dependencies()

    image = image_module.new("RGBA", (width, height), (0, 0, 0, 0))
    layout = _frame_layout(width, height, reserve_caption_band=reserve_caption_band)
    radius = max(18, int(min(width, height) * CARD_RADIUS_RATIO))
    draw_rounded_rectangle(image, layout.card, radius, COLOUR_CARD)
    draw = image_draw.Draw(image)

    content = _card_content(draw, match, layout, height, font_file, False)
    draw_centered_multiline_text(
        draw, [content.header_text], content.header_font, content.header_box, COLOUR_HEADER_TEXT, 0
    )
    pages = content.body_pages or [[]]
    lines = pages[min(page_idx, len(pages) - 1)]
    draw_centered_multiline_text(
        draw, lines, content.body_font, content.body_box, COLOUR_BODY_TEXT, content.body_spacing
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)


def validate_spec_timing(spec: dict[str, Any], fps: int) -> list[str]:
    """Check the float-second spec against the project fps.

    The spec itself stays un-quantized (generators own frame rounding); this
    only flags what will degrade after rounding: cues/overlays shorter than
    one frame, and consecutive highlight keyframes that collapse onto the same
    frame.
    """
    warnings: list[str] = []
    frame = 1.0 / fps

    for track in spec.get("tracks", []):
        if track.get("kind") == "captions":
            for cue in track.get("cues", []):
                if float(cue["out"]) - float(cue["in"]) < frame:
                    warnings.append(
                        f"caption cue at {cue['in']:.3f}s"
                        f"{' (' + cue['ref'] + ')' if cue.get('ref') else ''}"
                        f" is shorter than one frame at {fps} fps"
                    )
        elif track.get("kind") == "graphics":
            for item in track.get("items", []):
                if item.get("type") == "ayah_overlay":
                    if float(item["out"]) - float(item["in"]) < frame:
                        warnings.append(
                            f"ayah_overlay {item.get('ref')} at {item['in']:.3f}s is"
                            f" shorter than one frame at {fps} fps"
                        )
                elif item.get("type") == "word_highlight":
                    keyframes = item.get("keyframes", [])
                    collisions = sum(
                        1
                        for previous, current in zip(keyframes, keyframes[1:], strict=False)
                        if round(float(previous["in"]) * fps) == round(float(current["in"]) * fps)
                    )
                    if collisions:
                        warnings.append(
                            f"word_highlight {item.get('ref')}: {collisions} keyframe(s)"
                            f" collide with their neighbour after rounding to {fps} fps"
                        )
    return warnings


def _quran_data_version(conn: sqlite3.Connection | None) -> str | None:
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'data_version'").fetchone()
    except sqlite3.DatabaseError:
        return None
    return str(row[0]) if row else None


def build_edit_spec(
    *,
    cards: list[dict[str, Any]],
    windows: list[tuple[float, float]],
    caption_segments: list[dict[str, Any]],
    mode: str,
    width: int,
    height: int,
    fps: int,
    duration: float,
    audio_rel_path: str,
    video_rel_path: str | None,
    srt_rel_path: str,
    word_srt_rel_path: str | None,
    conn: sqlite3.Connection | None,
    overlay_pages: dict[int, list[tuple[int, float, float, str]]],
) -> dict[str, Any]:
    """Assemble the edit-spec dict from prepared parts (no filesystem access).

    *overlay_pages* maps ``id(card)`` to its ``(page_idx, in, out, asset)``
    windows — the caller decides how (and whether) page assets were rendered,
    which keeps this function pure and unit-testable.
    """
    media: list[dict[str, Any]] = [
        {
            "id": "aud1",
            "type": "audio",
            "path": audio_rel_path,
            "role": "recitation_audio" if mode == "recitation" else "spoken_audio",
            "duration": round(duration, 3),
        }
    ]
    if video_rel_path is not None:
        media.append(
            {
                "id": "vid1",
                "type": "video",
                "path": video_rel_path,
                "role": "reference_render",
            }
        )

    tracks: list[dict[str, Any]] = []
    if video_rel_path is not None:
        tracks.append(
            {"kind": "video", "clips": [{"media": "vid1", "in": 0.0, "out": round(duration, 3)}]}
        )
    tracks.append(
        {"kind": "audio", "clips": [{"media": "aud1", "in": 0.0, "out": round(duration, 3)}]}
    )

    cues: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for card, window in zip(cards, windows, strict=True):
        ayah_rows: list[sqlite3.Row] | None = None
        if card.get("kind") != "preamble" and card.get("surah_num") is not None:
            try:
                ayah_rows = ayah_rows_for_card(
                    conn, int(card["surah_num"]), int(card["from_ayah"]), int(card["to_ayah"])
                )
            except (ValueError, sqlite3.DatabaseError, TypeError, AttributeError) as error:
                warn(f"Card {card_ref(card)}: canonical lookup failed ({error}).")

        if mode != "lecture":
            cues.extend(ayah_caption_cues(card, window, ayah_rows))

        pages = overlay_pages.get(id(card)) or [(0, window[0], window[1], "")]
        for page_idx, page_in, page_out, asset in pages:
            item: dict[str, Any] = {
                "type": "ayah_overlay",
                "mogrt": AYAH_OVERLAY_MOGRT,
                "asset": asset,
                "ref": card_ref(card),
                "in": round(page_in, 3),
                "out": round(page_out, 3),
                "transform": {"x": width / 2, "y": height / 2, "scale": 1.0},
                "color": OVERLAY_COLOR,
            }
            if len(pages) > 1:
                item["page"] = page_idx + 1
                item["pages"] = len(pages)
            items.append(item)

        word_ids = word_ids_for_card(card, ayah_rows)
        first_asset = pages[0][3] if pages else ""
        highlight = word_highlight_item(card, word_ids, first_asset)
        if highlight is not None:
            items.append(highlight)

    if mode == "lecture":
        cues = lecture_caption_cues(caption_segments)

    captions_track: dict[str, Any] = {"kind": "captions", "srt": srt_rel_path, "cues": cues}
    if word_srt_rel_path is not None:
        captions_track["word_srt"] = word_srt_rel_path
    tracks.append(captions_track)
    tracks.append({"kind": "graphics", "items": items})

    return {
        "spec_version": SPEC_VERSION,
        "project": {"fps": fps, "width": width, "height": height},
        "media": media,
        "tracks": tracks,
        "meta": {
            "generator": {"name": "qurantext", "version": __version__},
            "mode": mode,
            "quran_data_version": _quran_data_version(conn),
        },
    }


def export_edit_spec_package(
    *,
    audio: str | Path,
    matches: str | Path,
    output_dir: str | Path,
    video: str | Path | None = None,
    preset: str | None = None,
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
    font_file: str | Path | None = None,
    db_path: str | Path = QURAN_DB_PATH,
) -> EditSpecExport:
    """Write a complete ``ExportPackage_<basename>`` working folder.

    Stages the job's media into the package (§5: the sidecar stages the files
    a job needs into a local working folder Premiere imports from), renders
    the interim overlay PNGs, writes the SRT review artifacts and the
    edit-spec JSON, and returns the collected fps-validation warnings.
    """
    audio_path = Path(audio).expanduser().resolve()
    matches_path = Path(matches).expanduser().resolve()
    validate_input_file(audio_path, "Audio file")
    validate_input_file(matches_path, "Matches JSON")

    raw_matches = load_matches(matches_path)
    meta = load_matches_meta(matches_path)
    mode = str(meta.get("mode") or "").lower()

    resolved_width, resolved_height, resolved_fps = resolve_export_format(
        mode, preset=preset, width=width, height=height, fps=fps
    )
    validate_dimensions(resolved_width, resolved_height)
    validate_fps(resolved_fps)

    font_path = (
        Path(font_file).expanduser().resolve() if font_file else Path(DEFAULT_VIDEO_FONT_FILE)
    )
    validate_input_file(font_path, "Font file")

    base = audio_path.stem
    package_dir = Path(output_dir).expanduser().resolve() / f"ExportPackage_{base}"
    audio_dir = package_dir / "audio"
    video_dir = package_dir / "video"
    overlays_dir = package_dir / "overlays"
    captions_dir = package_dir / "captions"
    for directory in (package_dir, audio_dir, video_dir, overlays_dir, captions_dir):
        directory.mkdir(parents=True, exist_ok=True)

    # Basmala splice: reproduce EXACTLY what the render did. The renderer
    # treats the concatenated audio as a throwaway temp; here it *is* the
    # job's audio, so it is kept and staged under a stable name.
    basmala_offset = 0.0
    staged_audio = audio_dir / audio_path.name
    if get_settings().video.prepend_basmala:
        prepend = maybe_prepend_basmala(matches_path, raw_matches, audio_path, work_dir=audio_dir)
        if prepend is not None:
            raw_matches = prepend.matches
            basmala_offset = prepend.offset
            staged_audio = audio_dir / f"{audio_path.stem}_basmala{prepend.audio_path.suffix}"
            prepend.audio_path.replace(staged_audio)
            print(
                f"Prepending shipped basmala; recitation timeline shifted by {basmala_offset:.2f}s."
            )
    if not staged_audio.exists():
        shutil.copy2(audio_path, staged_audio)

    staged_video: Path | None = None
    if video is not None:
        video_path = Path(video).expanduser().resolve()
        if video_path.exists():
            staged_video = video_dir / video_path.name
            shutil.copy2(video_path, staged_video)
        else:
            warn(f"Rendered video '{video_path}' not found; packaging without a reference video.")

    duration = get_audio_duration(staged_audio)

    # Same latched timeline as the frame renderer: validated cards sorted by
    # start, each holding until the next card starts.
    cards = sorted(
        validated_matches(raw_matches, bridge_gaps=False),
        key=lambda card: float(card["_start_time"]),
    )
    windows = latched_card_windows(cards, duration)

    caption_segments = load_caption_segments(matches_path)
    reserve_caption_band = bool(caption_segments)

    needs_db = any(
        card.get("kind") != "preamble" and card.get("surah_num") is not None for card in cards
    )
    conn: sqlite3.Connection | None = None
    if needs_db:
        conn = connect_quran_db(db_path)

    try:
        # Interim §8 assets: one transparent PNG per displayed card page,
        # paginated and timed exactly as the renderer pages the card.
        overlay_pages: dict[int, list[tuple[int, float, float, str]]] = {}
        rendered: dict[tuple[str, int], str] = {}
        for card, window in zip(cards, windows, strict=True):
            pages = card_body_pages(
                card,
                resolved_width,
                resolved_height,
                font_path,
                reserve_caption_band=reserve_caption_band,
            )
            timed = page_time_windows(pages, card.get("_word_timings") or [], window)
            stem = _overlay_stem(card)
            entries: list[tuple[int, float, float, str]] = []
            for page_idx, page_in, page_out in timed:
                suffix = f"_p{page_idx + 1:02d}" if len(timed) > 1 else ""
                asset_rel = f"overlays/{stem}{suffix}.png"
                key = (stem, page_idx)
                if key not in rendered:
                    render_card_overlay_png(
                        card,
                        page_idx,
                        resolved_width,
                        resolved_height,
                        font_path,
                        package_dir / asset_rel,
                        reserve_caption_band=reserve_caption_band,
                    )
                    rendered[key] = asset_rel
                entries.append((page_idx, page_in, page_out, rendered[key]))
            overlay_pages[id(card)] = entries

        spec = build_edit_spec(
            cards=cards,
            windows=windows,
            caption_segments=caption_segments,
            mode=mode,
            width=resolved_width,
            height=resolved_height,
            fps=resolved_fps,
            duration=duration,
            audio_rel_path=f"audio/{staged_audio.name}",
            video_rel_path=f"video/{staged_video.name}" if staged_video else None,
            srt_rel_path=f"captions/{base}.srt",
            word_srt_rel_path=None,  # filled below once cue/word data exists
            conn=conn,
            overlay_pages=overlay_pages,
        )
    finally:
        if conn is not None:
            conn.close()

    spec["meta"]["created_from"] = {"matches": matches_path.name, "audio": audio_path.name}
    spec["meta"]["basmala_offset_s"] = basmala_offset

    # SRT review artifacts (and the panel's manual-fallback import path).
    captions_track = next(track for track in spec["tracks"] if track["kind"] == "captions")
    cue_items = [
        {"text": cue["text"], "start": cue["in"], "end": cue["out"]}
        for cue in captions_track["cues"]
    ]
    write_text_srt(cue_items, package_dir / "captions" / f"{base}.srt", bom=True)

    word_items = [
        {"word": keyframe["word"], "start": keyframe["in"], "end": keyframe["out"]}
        for track in spec["tracks"]
        if track["kind"] == "graphics"
        for item in track["items"]
        if item["type"] == "word_highlight"
        for keyframe in item["keyframes"]
    ]
    if not word_items:
        word_items = [
            {"word": timing["word"], "start": timing["start"], "end": timing["end"]}
            for segment in caption_segments
            for timing in (segment.get("word_timings") or [])
        ]
    if word_items:
        word_srt_rel = f"captions/{base}.words.srt"
        write_word_srt(word_items, package_dir / word_srt_rel, bom=True)
        captions_track["word_srt"] = word_srt_rel

    warnings = validate_spec_timing(spec, resolved_fps)
    for message in warnings:
        warn(message)
    spec["meta"]["validation_warnings"] = warnings

    spec_path = package_dir / "edit_spec.json"
    write_json(spec, spec_path)
    (package_dir / "README.txt").write_text(README_TEXT, encoding="utf-8")

    return EditSpecExport(
        package_dir=package_dir, spec_path=spec_path, spec=spec, warnings=warnings
    )

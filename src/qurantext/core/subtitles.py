"""Subtitle cues, and the files they are written to.

Subtitles were only ever burned into the picture or staged for a Premiere
panel. Both are dead ends for someone who wants to correct a line or upload a
caption track. This module builds the cues once and writes them to the formats
that every tool already reads.

Two different things are called subtitles here and they must not be confused:

* **Ayah cues** carry the *canonical* Quran text for a card, split per ayah.
  The text comes from the store and is never the recogniser's version of it.
  The files write its open tanween in standard Unicode (U+08F0-08F2), which any
  font draws; only an ASS file in the Qaloon face keeps the mushaf's own marks.
* **Caption cues** carry recognised speech. They are the ones meant to be
  corrected, and they live in the project file so a correction survives.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any

from qurantext.core.arabic import is_qaloon_face, portable_tanween
from qurantext.core.video_common import warn
from qurantext.utils.time_utils import seconds_to_srt_time

__all__ = [
    "SUBTITLE_FORMATS",
    "Cue",
    "ayah_caption_cues",
    "ayah_rows_for_card",
    "card_ref",
    "latched_card_windows",
    "lecture_caption_cues",
    "write_ass",
    "write_srt",
    "write_subtitles",
    "write_vtt",
]

#: Formats a sidecar can be written in. SRT is universal, WebVTT is what the web
#: wants, ASS keeps styling.
SUBTITLE_FORMATS = ("srt", "vtt", "ass")


@dataclass(frozen=True, slots=True)
class Cue:
    """One subtitle line."""

    start: float
    end: float
    text: str
    #: ``25:7`` for an ayah cue, ``None`` for recognised speech.
    ref: str | None = None


# --- building cues -----------------------------------------------------------


def card_ref(match: dict[str, Any]) -> str:
    """The stable ref for one card: ``25:3``, ``25:1-5``, ``preamble:basmala``."""
    if match.get("kind") == "preamble":
        return f"preamble:{match.get('preamble_kind') or 'unknown'}"
    surah = match.get("surah_num")
    from_ayah = match.get("from_ayah")
    to_ayah = match.get("to_ayah")
    if from_ayah == to_ayah:
        return f"{surah}:{from_ayah}"
    return f"{surah}:{from_ayah}-{to_ayah}"


def latched_card_windows(cards: list[dict[str, Any]], duration: float) -> list[tuple[float, float]]:
    """Each card's display window under the frame renderer's latching.

    A card holds from its own start until the next card's start — the renderer
    never blanks between detections — and the last holds to the end of the
    audio. The windows therefore tile the timeline with no gaps, matching the
    rendered video frame for frame.
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
    """Canonical ``(ayah_num, text_raw, word_count)`` rows for a card's range."""
    rows = conn.execute(
        "SELECT ayah_num, text_raw, word_count FROM ayat"
        " WHERE surah_num = ? AND ayah_num BETWEEN ? AND ? ORDER BY ayah_num",
        (surah_num, from_ayah, to_ayah),
    ).fetchall()
    expected = to_ayah - from_ayah + 1
    if len(rows) != expected:
        raise ValueError(
            f"Quran store returned {len(rows)} ayat for {surah_num}:{from_ayah}-{to_ayah}"
            f" (expected {expected}); rebuild the store with build-db."
        )
    return rows


def ayah_caption_cues(
    match: dict[str, Any],
    window: tuple[float, float],
    ayah_rows: list[sqlite3.Row] | None,
) -> list[dict[str, Any]]:
    """One cue per ayah for a card, carrying the CANONICAL text.

    Boundaries come from the aligned word timings: ayah *k* begins on its first
    word's onset, and ends where the next begins, so the cues tile the card with
    no gap. When the timings cannot be split — none present, or a count mismatch
    against the canonical word counts — one cue spans the whole card instead.
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
            f" canonical word count ({sum(counts)}); emitting one cue for the card."
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
        starts.append(win_in if index == 0 else float(word_timings[offset]["start"]))
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
    """One editable cue per recognised subtitle line (they always need correction)."""
    return [
        {
            "in": round(float(segment["start"]), 3),
            "out": round(float(segment["end"]), 3),
            "text": str(segment["text"]),
        }
        for segment in caption_segments
    ]


# --- writing files -----------------------------------------------------------


def _ordered(cues: list[Cue]) -> list[Cue]:
    usable = [c for c in cues if c.end > c.start and c.text.strip()]
    return sorted(usable, key=lambda c: c.start)


def write_srt(cues: list[Cue], destination: str | PathLike[str], *, bom: bool = False) -> Path:
    """SubRip. The format every player and platform accepts."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for index, cue in enumerate(_ordered(cues), start=1):
        lines.append(str(index))
        lines.append(f"{seconds_to_srt_time(cue.start)} --> {seconds_to_srt_time(cue.end)}")
        lines.append(portable_tanween(cue.text))
        lines.append("")
    # Some editors only detect UTF-8 in an SRT when it carries a byte-order mark,
    # and Arabic arrives as mojibake without it.
    path.write_text("\n".join(lines), encoding="utf-8-sig" if bom else "utf-8")
    return path


def _vtt_time(seconds: float) -> str:
    return seconds_to_srt_time(seconds).replace(",", ".")


def write_vtt(cues: list[Cue], destination: str | PathLike[str]) -> Path:
    """WebVTT, which is what a browser and most upload forms want."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["WEBVTT", ""]
    for cue in _ordered(cues):
        if cue.ref:
            lines.append(cue.ref)
        lines.append(f"{_vtt_time(cue.start)} --> {_vtt_time(cue.end)}")
        lines.append(portable_tanween(cue.text))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_ass(
    cues: list[Cue],
    destination: str | PathLike[str],
    *,
    font_name: str = "Amiri",
    width: int = 1080,
    height: int = 1920,
) -> Path:
    """Advanced SubStation Alpha, which keeps styling the other two cannot."""
    from qurantext.core.video_common import ass_time, escape_ass

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    font_size = max(16, int(height * 0.045))
    margin_lr = max(10, int(width * 0.08))
    margin_v = max(10, int(height * 0.07))
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        (
            f"Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,"
            f"&H99000000,0,0,0,0,100,100,0,0,3,2,0,2,{margin_lr},{margin_lr},{margin_v},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    # The Qaloon face draws the mushaf's own marks and has no U+08F0-08F2.
    keep_marks = is_qaloon_face(font_name)
    for cue in _ordered(cues):
        text = cue.text if keep_marks else portable_tanween(cue.text)
        text = escape_ass(text).replace("\n", "\\N")
        lines.append(
            f"Dialogue: 0,{ass_time(cue.start)},{ass_time(cue.end)},Default,,0,0,0,,{text}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def write_subtitles(
    cues: list[Cue],
    stem: str | PathLike[str],
    formats: tuple[str, ...] = ("srt",),
    *,
    bom: bool = True,
    font_name: str = "Amiri",
    width: int = 1080,
    height: int = 1920,
) -> list[Path]:
    """Write *cues* beside *stem* in each requested format."""
    unknown = [f for f in formats if f not in SUBTITLE_FORMATS]
    if unknown:
        raise ValueError(
            f"Unknown subtitle format(s): {', '.join(unknown)}. "
            f"Choose from: {', '.join(SUBTITLE_FORMATS)}."
        )
    stem_path = Path(stem)
    written: list[Path] = []
    for fmt in formats:
        target = stem_path.with_suffix(f".{fmt}")
        if fmt == "srt":
            written.append(write_srt(cues, target, bom=bom))
        elif fmt == "vtt":
            written.append(write_vtt(cues, target))
        else:
            written.append(write_ass(cues, target, font_name=font_name, width=width, height=height))
    return written

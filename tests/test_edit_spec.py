"""Edit-spec emitter (architecture §8) — package export and pure helpers.

The integration tests build a ~30-second sample recitation package around a
tiny synthetic Quran store (surah 25 with three ayat) and a faked basmala
splice that reuses the REAL shift helpers from ``core.basmala``, so the
"same shifted timeline as the render" guarantee is exercised end to end.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from qurantext.config.paths import PROJECT_ROOT
from qurantext.core.basmala import BasmalaPrepend, basmala_card, offset_matches
from qurantext.pipelines.edit_spec import (
    ayah_caption_cues,
    card_ref,
    export_edit_spec_package,
    latched_card_windows,
    page_time_windows,
    resolve_export_format,
    validate_spec_timing,
    word_ids_for_card,
)
from qurantext.utils.time_utils import seconds_to_srt_time

_BUNDLED_FONT = PROJECT_ROOT / "fonts" / "qaloon.10.ttf"

_BASMALA_OFFSET = 4.0
_AUDIO_DURATION = 34.0

# Synthetic surah 25 fragment: per-ayah word lists the fake store is built from.
_AYAH_WORDS = {
    1: ["تَبَٰرَكَ", "الذِے", "نَزَّلَ", "الْفُرْقَانَ"],
    2: ["عَلَيٰ", "عَبْدِهِ", "لِيَكُونَ"],
    3: ["لِلْعَٰلَمِينَ", "نَذِيراً", "مُلْكُ", "السَّمَٰوَٰتِ", "وَالْأَرْضِ"],
}


def _raqm_available() -> bool:
    try:
        from PIL import features

        return bool(features.check("raqm"))
    except Exception:  # pragma: no cover - Pillow missing entirely
        return False


requires_render_stack = pytest.mark.skipif(
    not _BUNDLED_FONT.exists() or not _raqm_available(),
    reason="bundled font or Pillow/libraqm missing",
)


def _fake_quran_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE ayat (id TEXT PRIMARY KEY, surah_num INTEGER, ayah_num INTEGER,"
        " text_raw TEXT, text_norm TEXT, word_count INTEGER)"
    )
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    for ayah_num, words in _AYAH_WORDS.items():
        text = " ".join(words)
        conn.execute(
            "INSERT INTO ayat VALUES (?, ?, ?, ?, ?, ?)",
            (f"25:{ayah_num}", 25, ayah_num, text, text, len(words)),
        )
    conn.execute("INSERT INTO meta VALUES ('data_version', 'test-data')")
    conn.commit()
    conn.close()


def _word_timings(words: list[str], first_start: float) -> list[dict]:
    return [
        {"word": word, "start": first_start + index * 2.0, "end": first_start + index * 2.0 + 1.8}
        for index, word in enumerate(words)
    ]


def _sample_matches() -> list[dict]:
    """Two ayah cards covering 25:1-2 and 25:3 over ~30 seconds (pre-shift)."""
    card_a_words = _AYAH_WORDS[1] + _AYAH_WORDS[2]
    card_a = {
        "surah_num": 25,
        "surah_name": "سُورَةُ الفُرقَانِ",
        "from_ayah": 1,
        "to_ayah": 2,
        "confidence": 0.95,
        "start_time": 0.5,
        "end_time": 14.3,
        "text": " ".join(_AYAH_WORDS[1]) + " ١ " + " ".join(_AYAH_WORDS[2]) + " ٢",
        "word_timings": _word_timings(card_a_words, 0.5),
    }
    card_b = {
        "surah_num": 25,
        "surah_name": "سُورَةُ الفُرقَانِ",
        "from_ayah": 3,
        "to_ayah": 3,
        "confidence": 0.95,
        "start_time": 15.0,
        "end_time": 30.0,
        "text": " ".join(_AYAH_WORDS[3]) + " ٣",
        "word_timings": _word_timings(_AYAH_WORDS[3], 15.0),
    }
    return [card_a, card_b]


@pytest.fixture()
def sample_package(tmp_path: Path) -> dict:
    """Export a full sample package with the ffmpeg-dependent steps faked.

    ``maybe_prepend_basmala`` is replaced by a fake that performs the REAL
    timeline shift (``offset_matches`` + ``basmala_card``) and just skips the
    ffmpeg concat; ``get_audio_duration`` reports a fixed 34s duration.
    """
    db_path = tmp_path / "quran.sqlite"
    _fake_quran_db(db_path)

    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake-audio")
    video_path = tmp_path / "sample_frame.mp4"
    video_path.write_bytes(b"fake-video")

    matches_path = tmp_path / "sample_recitation.json"
    matches_path.write_text(
        json.dumps(
            {
                "matches": _sample_matches(),
                "meta": {
                    "mode": "recitation",
                    "detected_surah_num": 25,
                    "preamble_segments": [],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_prepend(matches_path_, matches, audio_path_, *, work_dir, **kwargs):
        concat = work_dir / f"{audio_path_.stem}.basmala.fake.m4a"
        concat.write_bytes(b"fake-concat-audio")
        return BasmalaPrepend(
            audio_path=concat,
            matches=[basmala_card(_BASMALA_OFFSET)] + offset_matches(matches, _BASMALA_OFFSET),
            offset=_BASMALA_OFFSET,
        )

    with (
        patch("qurantext.pipelines.edit_spec.maybe_prepend_basmala", side_effect=fake_prepend),
        patch("qurantext.pipelines.edit_spec.get_audio_duration", return_value=_AUDIO_DURATION),
    ):
        result = export_edit_spec_package(
            audio=audio_path,
            matches=matches_path,
            output_dir=tmp_path / "out",
            video=video_path,
            db_path=db_path,
        )

    spec = json.loads(result.spec_path.read_text(encoding="utf-8-sig"))
    return {"result": result, "spec": spec, "package_dir": result.package_dir}


# ---------------------------------------------------------------------------
# integration: the sample package
# ---------------------------------------------------------------------------


@requires_render_stack
def test_package_schema_shape(sample_package) -> None:
    spec = sample_package["spec"]

    assert spec["spec_version"]
    assert set(spec["project"]) == {"fps", "width", "height"}
    # Recitation defaults to the portrait social preset (phone-first framing).
    assert (spec["project"]["width"], spec["project"]["height"], spec["project"]["fps"]) == (
        1080,
        1920,
        30,
    )

    media_by_id = {entry["id"]: entry for entry in spec["media"]}
    assert media_by_id["aud1"]["type"] == "audio"
    assert media_by_id["vid1"]["role"] == "reference_render"

    kinds = [track["kind"] for track in spec["tracks"]]
    assert kinds == ["video", "audio", "captions", "graphics"]

    graphics = next(track for track in spec["tracks"] if track["kind"] == "graphics")
    types = {item["type"] for item in graphics["items"]}
    assert types == {"ayah_overlay", "word_highlight"}
    overlay = next(item for item in graphics["items"] if item["type"] == "ayah_overlay")
    assert set(overlay) >= {"mogrt", "asset", "ref", "in", "out", "transform", "color"}
    assert spec["meta"]["quran_data_version"] == "test-data"


@requires_render_stack
def test_package_gapless_ayah_tiling(sample_package) -> None:
    spec = sample_package["spec"]
    cues = next(track for track in spec["tracks"] if track["kind"] == "captions")["cues"]

    # basmala + 25:1 + 25:2 + 25:3, tiling [0, duration] with no gaps.
    assert [cue.get("ref") for cue in cues] == ["preamble:basmala", "25:1", "25:2", "25:3"]
    assert cues[0]["in"] == 0.0
    for previous, current in zip(cues, cues[1:], strict=False):
        assert previous["out"] == current["in"]
    assert cues[-1]["out"] == _AUDIO_DURATION

    # Ayah boundaries fall on the aligned word onsets (shifted by the basmala):
    # ayah 2 begins on card A's 5th word (0.5 + 4*2.0 + 4.0 shift = 12.5).
    assert cues[1]["in"] == 4.5  # card A start: 0.5 + 4.0 shift
    assert cues[2]["in"] == 12.5
    assert cues[3]["in"] == 19.0  # card B latches at its own start


@requires_render_stack
def test_package_word_ids_at_ayah_boundaries(sample_package) -> None:
    spec = sample_package["spec"]
    graphics = next(track for track in spec["tracks"] if track["kind"] == "graphics")
    highlights = {
        item["ref"]: item for item in graphics["items"] if item["type"] == "word_highlight"
    }

    card_a = highlights["25:1-2"]["keyframes"]
    assert len(card_a) == len(_AYAH_WORDS[1]) + len(_AYAH_WORDS[2])
    # The ayah boundary: word 4 of ayah 1, then word 1 of ayah 2.
    assert card_a[3]["word"] == "25:1:4"
    assert card_a[4]["word"] == "25:2:1"
    # Keyframe times are the aligned (shifted) word spans.
    assert card_a[0]["in"] == 4.5 and card_a[0]["out"] == pytest.approx(6.3)

    card_b = highlights["25:3"]["keyframes"]
    assert [keyframe["word"] for keyframe in card_b] == [f"25:3:{n}" for n in range(1, 6)]


@requires_render_stack
def test_package_basmala_shift_consistency(sample_package) -> None:
    spec = sample_package["spec"]
    package_dir = sample_package["package_dir"]

    assert spec["meta"]["basmala_offset_s"] == _BASMALA_OFFSET
    # The concatenated basmala+recitation audio is KEPT and is the job's audio.
    audio_entry = next(entry for entry in spec["media"] if entry["id"] == "aud1")
    assert "basmala" in audio_entry["path"]
    assert (package_dir / audio_entry["path"]).exists()

    # Every timed element sits on the shifted timeline: nothing (except the
    # injected basmala card itself) may start before the offset.
    graphics = next(track for track in spec["tracks"] if track["kind"] == "graphics")
    for item in graphics["items"]:
        if item.get("ref") == "preamble:basmala":
            assert item["in"] == 0.0
            assert item["out"] == 4.5  # latched until card A starts
        elif item["type"] == "ayah_overlay":
            assert item["in"] >= _BASMALA_OFFSET


@requires_render_stack
def test_package_paths_relative_and_staged(sample_package) -> None:
    spec = sample_package["spec"]
    package_dir = sample_package["package_dir"]

    referenced: list[str] = [entry["path"] for entry in spec["media"]]
    for track in spec["tracks"]:
        if track["kind"] == "captions":
            referenced.append(track["srt"])
            if track.get("word_srt"):
                referenced.append(track["word_srt"])
        if track["kind"] == "graphics":
            referenced.extend(item["asset"] for item in track["items"] if item.get("asset"))
            referenced.extend(
                item["ayah_asset"] for item in track["items"] if item.get("ayah_asset")
            )

    assert referenced
    for path in referenced:
        assert not Path(path).is_absolute(), path
        assert "\\" not in path and not path.startswith(".."), path
        assert (package_dir / path).exists(), path

    assert (package_dir / "edit_spec.json").exists()
    assert (package_dir / "README.txt").exists()


@requires_render_stack
def test_package_overlays_are_transparent_full_frames(sample_package) -> None:
    from PIL import Image

    spec = sample_package["spec"]
    package_dir = sample_package["package_dir"]
    graphics = next(track for track in spec["tracks"] if track["kind"] == "graphics")
    overlay = next(item for item in graphics["items"] if item["ref"] == "25:1-2")

    with Image.open(package_dir / overlay["asset"]) as image:
        assert image.mode == "RGBA"
        assert image.size == (spec["project"]["width"], spec["project"]["height"])
        assert image.getpixel((2, 2))[3] == 0  # frame corner stays transparent

    assert overlay["transform"] == {"x": 540.0, "y": 960.0, "scale": 1.0}


@requires_render_stack
def test_package_srt_agrees_with_spec(sample_package) -> None:
    spec = sample_package["spec"]
    package_dir = sample_package["package_dir"]
    captions = next(track for track in spec["tracks"] if track["kind"] == "captions")

    raw = (package_dir / captions["srt"]).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM for Premiere

    blocks = raw.decode("utf-8-sig").strip().split("\n\n")
    assert len(blocks) == len(captions["cues"])
    for block, cue in zip(blocks, captions["cues"], strict=True):
        lines = block.split("\n")
        expected_timing = f"{seconds_to_srt_time(cue['in'])} --> {seconds_to_srt_time(cue['out'])}"
        assert lines[1] == expected_timing
        assert "\n".join(lines[2:]) == cue["text"]

    # Word-level SRT mirrors the highlight keyframes one to one.
    word_blocks = (
        (package_dir / captions["word_srt"]).read_bytes().decode("utf-8-sig").strip().split("\n\n")
    )
    keyframes = [
        keyframe
        for track in spec["tracks"]
        if track["kind"] == "graphics"
        for item in track["items"]
        if item["type"] == "word_highlight"
        for keyframe in item["keyframes"]
    ]
    assert len(word_blocks) == len(keyframes)


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_resolve_export_format_precedence(monkeypatch) -> None:
    # Named preset wins outright.
    assert resolve_export_format("recitation", preset="high") == (1920, 1080, 30)
    # Explicit values beat the mode default, per dimension.
    assert resolve_export_format("recitation", width=640) == (640, 1920, 30)
    # Lecture/recitation fall back to the portrait social preset.
    assert resolve_export_format("lecture") == (1080, 1920, 30)
    # Anything else falls back to settings.video defaults.
    from qurantext.config.settings import get_settings

    settings = get_settings()
    assert resolve_export_format("") == (
        settings.video.width,
        settings.video.height,
        settings.video.fps,
    )


def test_latched_card_windows_tile_to_duration() -> None:
    cards = [
        {"_start_time": 1.0, "_end_time": 3.0},
        {"_start_time": 6.0, "_end_time": 9.0},  # 3s gap before it: latching bridges it
    ]
    windows = latched_card_windows(cards, 20.0)
    assert windows == [(1.0, 6.0), (6.0, 20.0)]


def test_card_ref_and_preamble_word_ids() -> None:
    assert card_ref({"surah_num": 25, "from_ayah": 3, "to_ayah": 3}) == "25:3"
    assert card_ref({"surah_num": 25, "from_ayah": 1, "to_ayah": 5}) == "25:1-5"

    preamble = {
        "kind": "preamble",
        "preamble_kind": "basmala",
        "_word_timings": [{"start": 0.0, "end": 0.5}, {"start": 0.5, "end": 1.0}],
    }
    assert card_ref(preamble) == "preamble:basmala"
    assert word_ids_for_card(preamble, None) == ["preamble:basmala:1", "preamble:basmala:2"]


def _rows(pairs: list[tuple[int, str, int]]) -> list[sqlite3.Row]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE ayat (ayah_num INTEGER, text_raw TEXT, word_count INTEGER)")
    conn.executemany("INSERT INTO ayat VALUES (?, ?, ?)", pairs)
    return conn.execute("SELECT * FROM ayat ORDER BY ayah_num").fetchall()


def test_ayah_caption_cues_fall_back_on_count_mismatch() -> None:
    rows = _rows([(1, "ا ب", 2), (2, "ت", 1)])
    match = {
        "surah_num": 25,
        "from_ayah": 1,
        "to_ayah": 2,
        "_word_timings": [{"start": 1.0, "end": 2.0}],  # 1 timing for 3 canonical words
    }
    cues = ayah_caption_cues(match, (0.0, 10.0), rows)
    assert len(cues) == 1
    assert cues[0]["text"] == "ا ب\nت"
    assert (cues[0]["in"], cues[0]["out"]) == (0.0, 10.0)


def test_page_time_windows_turn_on_next_pages_first_word() -> None:
    pages = [["ا ب", "ت"], ["ث ج"]]  # 3 words on page 1, 2 on page 2
    timings = [{"start": float(index), "end": index + 0.9} for index in range(5)]
    windows = page_time_windows(pages, timings, (0.0, 10.0))
    assert windows == [(0, 0.0, 3.0), (1, 3.0, 10.0)]

    # Without word timings the split is clock-proportional (renderer fallback).
    windows = page_time_windows(pages, [], (0.0, 10.0))
    assert windows == [(0, 0.0, 5.0), (1, 5.0, 10.0)]


def test_validate_spec_timing_flags_subframe_cues_and_colliding_keyframes() -> None:
    spec = {
        "tracks": [
            {
                "kind": "captions",
                "cues": [
                    {"in": 0.0, "out": 0.01, "text": "x", "ref": "25:1"},  # < one frame @ 25fps
                    {"in": 1.0, "out": 2.0, "text": "y"},
                ],
            },
            {
                "kind": "graphics",
                "items": [
                    {"type": "ayah_overlay", "ref": "25:1", "in": 0.0, "out": 5.0},
                    {
                        "type": "word_highlight",
                        "ref": "25:1",
                        "keyframes": [
                            {"word": "25:1:1", "in": 1.00, "out": 1.01},
                            {"word": "25:1:2", "in": 1.01, "out": 1.50},  # same frame @ 25fps
                            {"word": "25:1:3", "in": 2.00, "out": 2.50},
                        ],
                    },
                ],
            },
        ]
    }
    warnings = validate_spec_timing(spec, 25)
    assert len(warnings) == 2
    assert any("shorter than one frame" in warning for warning in warnings)
    assert any("collide" in warning for warning in warnings)


def test_validate_spec_timing_clean_spec_returns_nothing() -> None:
    spec = {
        "tracks": [
            {"kind": "captions", "cues": [{"in": 0.0, "out": 2.0, "text": "x"}]},
            {"kind": "graphics", "items": []},
        ]
    }
    assert validate_spec_timing(spec, 25) == []

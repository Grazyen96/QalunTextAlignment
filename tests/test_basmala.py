import json
from collections import Counter
from pathlib import Path

from qurantext.config.paths import DEFAULT_QURAN_PATH
from qurantext.core.basmala import (
    basmala_card,
    load_matches_meta,
    maybe_prepend_basmala,
    offset_matches,
    should_prepend_basmala,
)
from qurantext.core.preamble import BASMALA_DISPLAY, BASMALA_LABEL
from qurantext.core.quran_parser import _is_basmala


def _recitation_meta(**overrides) -> dict:
    meta = {"mode": "recitation", "detected_surah_num": 2, "preamble_segments": []}
    meta.update(overrides)
    return meta


def test_should_prepend_for_plain_recitation(tmp_path: Path) -> None:
    basmala = tmp_path / "basmala.mp3"
    basmala.write_bytes(b"stub")
    assert should_prepend_basmala(_recitation_meta(), basmala) is True


def test_skip_when_basmala_already_detected(tmp_path: Path) -> None:
    basmala = tmp_path / "basmala.mp3"
    basmala.write_bytes(b"stub")
    meta = _recitation_meta(preamble_segments=["istiaadha", "basmala"])
    assert should_prepend_basmala(meta, basmala) is False


def test_skip_at_tawbah(tmp_path: Path) -> None:
    basmala = tmp_path / "basmala.mp3"
    basmala.write_bytes(b"stub")
    assert should_prepend_basmala(_recitation_meta(detected_surah_num=9), basmala) is False


def test_al_fatiha_still_prepends_when_none_detected(tmp_path: Path) -> None:
    # Surah 1 only skips because its basmala is already recited (detected); with
    # no basmala detected the rule still prepends (only At-Tawbah is special).
    basmala = tmp_path / "basmala.mp3"
    basmala.write_bytes(b"stub")
    assert should_prepend_basmala(_recitation_meta(detected_surah_num=1), basmala) is True


def test_skip_non_recitation_mode(tmp_path: Path) -> None:
    basmala = tmp_path / "basmala.mp3"
    basmala.write_bytes(b"stub")
    assert should_prepend_basmala(_recitation_meta(mode="lecture"), basmala) is False


def test_skip_when_file_missing(tmp_path: Path) -> None:
    assert should_prepend_basmala(_recitation_meta(), tmp_path / "absent.mp3") is False


def test_basmala_card_is_static_and_spans_duration() -> None:
    card = basmala_card(4.2)
    assert card["start_time"] == 0.0
    assert card["end_time"] == 4.2
    assert card["word_timings"] == []  # no highlight → still frame
    assert card["full_text"] == BASMALA_DISPLAY
    assert card["surah_name"] == BASMALA_LABEL
    assert card["from_ayah"] is None and card["to_ayah"] is None


def test_the_basmala_card_uses_the_shipped_texts_basmala() -> None:
    # The card and its cue show the Qaloon mushaf's own basmala, with its wasl
    # marks, not a Hafs-style one, so they match the ayahs that follow them.
    lines = DEFAULT_QURAN_PATH.read_text(encoding="utf-16").splitlines()
    basmalas = Counter(line.strip() for line in lines if _is_basmala(line))
    assert basmalas.most_common(1)[0][0] == BASMALA_DISPLAY


def test_offset_matches_shifts_cards_and_words() -> None:
    matches = [
        {
            "from_ayah": 1,
            "to_ayah": 1,
            "start_time": 0.0,
            "end_time": 2.0,
            "word_timings": [
                {"word": "الحمد", "start": 0.0, "end": 0.5},
                {"word": "لله", "start": 0.5, "end": 2.0},
            ],
        }
    ]
    shifted = offset_matches(matches, 3.0)
    assert shifted[0]["start_time"] == 3.0
    assert shifted[0]["end_time"] == 5.0
    assert shifted[0]["word_timings"][0] == {"word": "الحمد", "start": 3.0, "end": 3.5}
    assert shifted[0]["word_timings"][1] == {"word": "لله", "start": 3.5, "end": 5.0}
    # Originals untouched.
    assert matches[0]["start_time"] == 0.0
    assert matches[0]["word_timings"][0]["start"] == 0.0


def test_offset_matches_leaves_non_numeric_timings() -> None:
    shifted = offset_matches([{"start_time": None, "end_time": 1.0}], 2.0)
    assert shifted[0]["start_time"] is None
    assert shifted[0]["end_time"] == 3.0


def test_load_matches_meta_reads_meta(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"matches": [], "meta": {"mode": "recitation"}}), encoding="utf-8")
    assert load_matches_meta(path) == {"mode": "recitation"}


def test_load_matches_meta_missing_or_bad(tmp_path: Path) -> None:
    assert load_matches_meta(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert load_matches_meta(bad) == {}


def test_maybe_prepend_returns_none_when_not_applicable(tmp_path: Path) -> None:
    # At-Tawbah → no prepend, so no ffmpeg call and no temp file.
    matches_path = tmp_path / "m.json"
    matches_path.write_text(
        json.dumps({"matches": [], "meta": _recitation_meta(detected_surah_num=9)}),
        encoding="utf-8",
    )
    result = maybe_prepend_basmala(
        matches_path,
        [],
        tmp_path / "audio.mp3",
        work_dir=tmp_path / "work",
        basmala_path=tmp_path / "basmala.mp3",
    )
    assert result is None

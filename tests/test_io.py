import json
from pathlib import Path

from qurantext.io.readers import (
    extract_alignment_words,
    extract_matching_words,
    extract_segments,
    load_json,
)
from qurantext.io.writers import write_json, write_text_srt, write_word_srt


def test_io_helpers_extract_words_segments_and_write_outputs(tmp_path: Path) -> None:
    sample = {
        "segments": [
            {
                "text": "بِسْمِ اللَّهِ",
                "start": 0.0,
                "end": 1.0,
                "words": [
                    {"word": "بِسْمِ", "start": 0.0, "end": 0.4, "score": 0.95},
                    {"word": "اللَّهِ", "start": 0.4, "end": 1.0, "score": 0.9},
                ],
            }
        ]
    }

    alignment_words = extract_alignment_words(sample)
    matching_words = extract_matching_words(sample)
    segments = extract_segments(sample)

    assert alignment_words[0]["word_norm"] == "بسم"
    assert matching_words[1]["score"] == 0.9
    assert segments[0]["text_norm"] == "بسم الله"

    json_path = Path(write_json(sample, tmp_path / "sample.json"))
    assert load_json(json_path) == sample

    word_srt = Path(
        write_word_srt([{"start": 0.0, "end": 0.5, "word": "بسم"}], tmp_path / "word.srt")
    )
    text_srt = Path(
        write_text_srt([{"start": 0.0, "end": 1.0, "text": "بسم الله"}], tmp_path / "text.srt")
    )
    assert "بسم" in word_srt.read_text(encoding="utf-8")
    assert "بسم الله" in text_srt.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["segments"][0]["text"] == "بِسْمِ اللَّهِ"


def test_extract_words_warns_on_missing_timestamps(caplog) -> None:
    import logging

    data = {
        "segments": [
            {
                "words": [
                    {"word": "بِسْمِ", "start": 0.0, "end": 0.4},
                    {"word": "اللَّهِ"},  # missing start/end
                ]
            }
        ]
    }

    with caplog.at_level(logging.WARNING, logger="qurantext.io.readers"):
        alignment = extract_alignment_words(data)
        matching = extract_matching_words(data)

    assert len(alignment) == 1
    assert len(matching) == 1
    assert any("skipped 1 word" in r.message for r in caplog.records)


def test_extract_matching_words_tolerates_malformed_entries() -> None:
    # A non-string word or a non-numeric timestamp must skip that entry, not
    # crash the whole transcript load.
    data = {
        "segments": [
            {
                "words": [
                    {"word": "بِسْمِ", "start": 0.0, "end": 0.4},
                    {"word": 123, "start": 0.4, "end": 0.5},  # non-string word
                    {"word": "اللَّهِ", "start": "oops", "end": 1.0},  # bad timestamp
                ]
            }
        ]
    }

    matching = extract_matching_words(data)
    assert [w["word_norm"] for w in matching] == ["بسم"]

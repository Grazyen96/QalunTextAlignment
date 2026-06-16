from pathlib import Path

from qurantext.core.alignment import (
    align_canonical_word_timings,
    align_segments,
    align_words,
)
from qurantext.core.quran_parser import parse_ayat
from qurantext.io.readers import extract_alignment_words, extract_matching_words


def test_canonical_timings_one_per_canonical_word_on_clean_recitation() -> None:
    transcript = [
        {"word_norm": "الحمد", "start": 0.0, "end": 0.5},
        {"word_norm": "لله", "start": 0.5, "end": 1.0},
        {"word_norm": "رب", "start": 1.0, "end": 1.5},
    ]
    timings = align_canonical_word_timings(transcript, ["الحمد", "لله", "رب"])
    assert [(t["start"], t["end"]) for t in timings] == [
        (0.0, 0.5),
        (0.5, 1.0),
        (1.0, 1.5),
    ]


def test_canonical_timings_absorb_repeated_transcript_word() -> None:
    # Reciter repeats "لله"; the second utterance must not shift "رب" by one.
    transcript = [
        {"word_norm": "الحمد", "start": 0.0, "end": 0.5},
        {"word_norm": "لله", "start": 0.5, "end": 1.0},
        {"word_norm": "لله", "start": 1.0, "end": 1.4},
        {"word_norm": "رب", "start": 1.4, "end": 2.0},
    ]
    timings = align_canonical_word_timings(transcript, ["الحمد", "لله", "رب"])
    assert len(timings) == 3
    assert timings[0]["start"] == 0.0
    # "لله" spans both utterances; "رب" still lands on the genuine word.
    assert timings[1] == {"start": 0.5, "end": 1.4}
    assert timings[2] == {"start": 1.4, "end": 2.0}


def test_canonical_timings_skip_leading_preamble_words() -> None:
    # Transcript opens with basmala words absent from the canonical ayah text;
    # they must be treated as insertions, not consume canonical slots.
    transcript = [
        {"word_norm": "بسم", "start": 0.0, "end": 0.3},
        {"word_norm": "الله", "start": 0.3, "end": 0.6},
        {"word_norm": "الحمد", "start": 0.6, "end": 1.0},
        {"word_norm": "لله", "start": 1.0, "end": 1.5},
    ]
    timings = align_canonical_word_timings(transcript, ["الحمد", "لله"])
    assert timings[0]["start"] == 0.6
    assert timings[1] == {"start": 1.0, "end": 1.5}


def test_canonical_timings_interpolate_dropped_word() -> None:
    # Reciter's middle word missing from transcript -> interpolate, no stall.
    transcript = [
        {"word_norm": "الحمد", "start": 0.0, "end": 0.5},
        {"word_norm": "العالمين", "start": 1.5, "end": 2.0},
    ]
    timings = align_canonical_word_timings(transcript, ["الحمد", "لله", "العالمين"])
    assert len(timings) == 3
    assert timings[0]["start"] == 0.0
    assert timings[2]["end"] == 2.0
    # The dropped middle word gets a span between its neighbours.
    assert 0.5 <= timings[1]["start"] <= timings[1]["end"] <= 1.5


def test_canonical_timings_empty_transcript_yields_none() -> None:
    timings = align_canonical_word_timings([], ["الحمد", "لله"])
    assert timings == [{"start": None, "end": None}, {"start": None, "end": None}]


def test_align_words_and_segments_keep_unmatched_entries_for_manual_review() -> None:
    canon_original = ["الحمد", "لله"]
    canon_norm = ["الحمد", "لله"]

    word_alignment, word_manual = align_words(
        [
            {"word_raw": "الْحَمْدُ", "word_norm": "الحمد", "start": 0.0, "end": 0.4},
            {"word_raw": "غير", "word_norm": "غير", "start": 0.4, "end": 0.7},
        ],
        canon_original,
        canon_norm,
        min_score=0.8,
    )
    segment_alignment, segment_manual = align_segments(
        [
            {"text_raw": "الْحَمْدُ لِلَّهِ", "text_norm": "الحمد لله", "start": 0.0, "end": 1.0},
            {"text_raw": "غير مطابق", "text_norm": "غير مطابق", "start": 1.0, "end": 2.0},
        ],
        ["الْحَمْدُ لِلَّهِ"],
        ["الحمد لله"],
        min_score=0.8,
    )

    assert word_alignment[0]["word"] == "الحمد"
    assert word_alignment[1]["word"] == "غير"
    assert len(word_manual) == 1
    assert word_manual[0]["word_index"] == 1
    assert word_manual[0]["whisperx_word"] == "غير"
    assert word_manual[0]["start"] == 0.4
    assert word_manual[0]["end"] == 0.7
    assert 0.0 <= word_manual[0]["best_score"] < 0.8

    assert segment_alignment[0]["text"] == "الْحَمْدُ لِلَّهِ"
    assert segment_alignment[1]["text"] == "غير مطابق"
    assert len(segment_manual) == 1
    assert segment_manual[0]["segment_index"] == 1
    assert segment_manual[0]["whisperx_text"] == "غير مطابق"
    assert segment_manual[0]["start"] == 1.0
    assert segment_manual[0]["end"] == 2.0
    assert 0.0 <= segment_manual[0]["best_score"] < 0.8


def test_extract_words_supports_flat_list_whisperx_shape() -> None:
    flat_output = [
        {"word": "بِسْمِ", "start": 0.0, "end": 0.4, "score": 0.95},
        {"text": "اللَّهِ", "start": 0.4, "end": 1.0, "score": 0.9},
    ]

    alignment_words = extract_alignment_words(flat_output)
    matching_words = extract_matching_words(flat_output)

    assert [item["word_norm"] for item in alignment_words] == ["بسم", "الله"]
    assert [item["word_raw"] for item in matching_words] == ["بِسْمِ", "اللَّهِ"]
    assert matching_words[1]["score"] == 0.9


def test_parse_ayat_cache_returns_fresh_copies_per_call(tmp_path: Path) -> None:
    quran_file = tmp_path / "sample_quran.txt"
    quran_file.write_text(
        "سُورَةُ الفَاتِحَةِ\nالْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ ١\nالرَّحْمَنِ الرَّحِيمِ ٢\n",
        encoding="utf-8",
    )

    first = parse_ayat(quran_file)
    first[0]["text_raw"] = "mutated"
    first.append({"ayah_num": 999})

    second = parse_ayat(quran_file)

    assert len(second) == 2
    assert second[0]["text_raw"] == "الْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ"

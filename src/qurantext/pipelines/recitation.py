from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from pathlib import Path

from qurantext.config.paths import RECITATION_MATCHING_OUTPUT_DIR, ensure_required_directories
from qurantext.config.settings import get_settings
from qurantext.core.alignment import align_words
from qurantext.core.arabic import normalize_alignment_ar
from qurantext.core.quran_parser import read_quran_text
from qurantext.io.readers import extract_alignment_words
from qurantext.io.writers import write_json, write_word_srt
from qurantext.services.transcription import transcribe_audio


@dataclass(frozen=True, slots=True)
class RecitationOutputPaths:
    """Output paths produced by the recitation alignment pipeline."""

    alignment_json: Path
    raw_output_json: Path
    manual_check_json: Path
    captions_srt: Path


@dataclass(frozen=True, slots=True)
class RecitationAlignmentResult:
    """Result returned by :func:`run_word_alignment`."""

    alignment: list[dict]
    manual_check: list[dict]
    output_paths: RecitationOutputPaths
    raw_output: dict | list | None


def build_recitation_output_paths(
    audio_path: str | PathLike[str],
    *,
    output_dir: str | PathLike[str] = RECITATION_MATCHING_OUTPUT_DIR,
    base_name: str | None = None,
) -> RecitationOutputPaths:
    """Build standard output paths for the recitation alignment pipeline."""
    output_root = Path(output_dir)
    stem = base_name or Path(audio_path).stem
    return RecitationOutputPaths(
        alignment_json=output_root / f"{stem}_word_alignment.json",
        raw_output_json=output_root / f"{stem}_whisperx_raw.json",
        manual_check_json=output_root / f"{stem}_word_manual_check.json",
        captions_srt=output_root / f"{stem}_word.srt",
    )


def run_word_alignment(
    quran_path: str | PathLike[str],
    audio_path: str | PathLike[str],
    *,
    output_paths: RecitationOutputPaths | None = None,
    whisperx_output: dict | list | None = None,
    model_ref: str | None = None,
    engine: str | None = None,
) -> RecitationAlignmentResult:
    """Run the word-level recitation alignment workflow."""
    ensure_required_directories()

    quran_file = Path(quran_path)
    audio_file = Path(audio_path)
    if not quran_file.exists():
        raise FileNotFoundError(f"Text file not found: {quran_file}")
    if whisperx_output is None and not audio_file.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_file}")

    resolved_output_paths = output_paths or build_recitation_output_paths(audio_file)
    # BOM-aware read: the shipped Qalun file is UTF-16, which a plain utf-8 read
    # would turn into mojibake (and produce near-zero alignment).
    quran_text = read_quran_text(quran_file)
    canon_original = quran_text.split()
    canon_norm = [normalize_alignment_ar(word) for word in canon_original]

    raw_output: dict | list | None = whisperx_output
    if raw_output is None:
        transcription = transcribe_audio(
            audio_file,
            save_raw_to=resolved_output_paths.raw_output_json,
            model_ref=model_ref,
            engine=engine,
        )
        raw_output = transcription.output

    words = extract_alignment_words(raw_output)
    if not words:
        raise RuntimeError(
            "No word timestamps were returned by the transcription. Print the raw output to inspect the response shape."
        )

    settings = get_settings()
    alignment, manual_check = align_words(
        words,
        canon_original,
        canon_norm,
        settings.word_match_threshold,
    )

    if whisperx_output is not None:
        write_json(raw_output, resolved_output_paths.raw_output_json)
    write_json(alignment, resolved_output_paths.alignment_json)
    write_json(manual_check, resolved_output_paths.manual_check_json)
    write_word_srt(alignment, resolved_output_paths.captions_srt)

    return RecitationAlignmentResult(
        alignment=alignment,
        manual_check=manual_check,
        output_paths=resolved_output_paths,
        raw_output=raw_output,
    )

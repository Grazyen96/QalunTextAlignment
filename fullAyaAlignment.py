import os
import re
import replicate
import json
from difflib import SequenceMatcher

from env_utils import load_project_env

# ── constants ────────────────────────────────────────────────────────────────
TASHKEEL = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")

TEXT_FILE        = "alFurqan.txt"
AUDIO_FILE       = "alFurqan.mp3"
MODEL_REF        = "victor-upmeet/whisperx:84d2ad2d6194fe98a17d2b60bef1c7f910c46b2f6fd38996ca457afd9c8abfcb"
OUTPUT_FILE        = "full_ayat_alignment.json"
REPLICATE_RAW_FILE = "replicate_raw_output.json"
MANUAL_CHECK_FILE  = "manual_check.json"
SRT_FILE           = "alFurqan.srt"

MATCH_THRESHOLD  = 0.50  # min similarity score to accept a canonical-text match


# ── helpers ──────────────────────────────────────────────────────────────────
def normalize_ar(text: str) -> str:
    text = TASHKEEL.sub("", text)
    text = re.sub("[إأآٱ]", "ا", text)
    text = text.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    text = re.sub(r"[^\u0621-\u064A\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def seconds_to_srt_time(seconds: float) -> str:
    """Convert a float number of seconds to SRT timestamp format HH:MM:SS,mmm."""
    seconds = max(0.0, seconds)
    ms = int(round((seconds % 1) * 1000))
    total_s = int(seconds)
    h  = total_s // 3600
    m  = (total_s % 3600) // 60
    s  = total_s % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ── extraction ───────────────────────────────────────────────────────────────
def extract_segments(output) -> list[dict]:
    """Return a list of {text_raw, text_norm, start, end} dicts from whisperx output."""
    segments = []

    if isinstance(output, dict):
        raw_segments = output.get("segments", [])
    elif isinstance(output, list):
        raw_segments = output
    else:
        raw_segments = []

    for seg in raw_segments:
        if not isinstance(seg, dict):
            continue
        raw_text = seg.get("text") or seg.get("segment") or ""
        start    = seg.get("start")
        end      = seg.get("end")
        norm     = normalize_ar(raw_text)
        if norm and start is not None and end is not None:
            segments.append({
                "text_raw":  raw_text.strip(),
                "text_norm": norm,
                "start":     start,
                "end":       end,
            })

    return segments


# ── fuzzy lookup ─────────────────────────────────────────────────────────────
def find_best_canonical_line(
    seg_norm: str,
    lines_original: list[str],
    lines_norm: list[str],
    min_score: float = MATCH_THRESHOLD,
) -> tuple[str | None, float]:
    """Search all canonical lines for the best fuzzy match.

    Returns (canonical_line, score).  canonical_line is None when the best
    score is below min_score.
    """
    best_line  = None
    best_score = 0.0

    for orig, norm in zip(lines_original, lines_norm):
        score = similarity(seg_norm, norm)
        if score > best_score:
            best_score = score
            best_line  = orig

    if best_score >= min_score:
        return best_line, best_score
    return None, best_score


# ── SRT writer ───────────────────────────────────────────────────────────────
def write_srt(result: list[dict], path: str) -> None:
    """Write an SRT caption file from the result list."""
    with open(path, "w", encoding="utf-8") as f:
        index = 1
        for item in result:
            if item["start"] is None or item["end"] is None:
                continue
            start_ts = seconds_to_srt_time(item["start"])
            end_ts   = seconds_to_srt_time(item["end"])
            f.write(f"{index}\n")
            f.write(f"{start_ts} --> {end_ts}\n")
            f.write(f"{item['text']}\n\n")
            index += 1
    print(f"Saved SRT captions to {path} ({index - 1} entries)")


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    load_project_env()

    if not os.path.exists(TEXT_FILE):
        raise FileNotFoundError(f"Text file not found: {TEXT_FILE}")
    if not os.path.exists(AUDIO_FILE):
        raise FileNotFoundError(f"Audio file not found: {AUDIO_FILE}")
    if not os.getenv("REPLICATE_API_TOKEN"):
        raise RuntimeError(
            "REPLICATE_API_TOKEN is not set. "
            "Set your Replicate API token before running this script."
        )

    # Load canonical reference lines from alFurqan.txt
    with open(TEXT_FILE, encoding="utf-8") as f:
        quran_text = f.read()
    lines_original = [ln.strip() for ln in quran_text.splitlines() if ln.strip()]
    lines_norm     = [normalize_ar(ln) for ln in lines_original]

    # ── call whisperx via Replicate ──────────────────────────────────────────
    try:
        with open(AUDIO_FILE, "rb") as audio_file:
            output = replicate.run(
                MODEL_REF,
                input={
                    "debug":                        False,
                    "language":                     "ar",
                    "vad_onset":                    0.5,
                    "audio_file":                   audio_file,
                    "batch_size":                   64,
                    "vad_offset":                   0.363,
                    "diarization":                  False,
                    "temperature":                  0,
                    "align_output":                 False,
                    "language_detection_min_prob":  0,
                    "language_detection_max_tries": 5,
                }
            )
    except Exception as error:
        error_text = str(error)
        if "status: 404" in error_text:
            raise RuntimeError(
                f"Replicate could not find the model: {MODEL_REF}\n"
                "Check that the model exists and that your account has access to it."
            ) from error
        raise

    print("Raw whisperx output:", output)

    # ── persist raw Replicate output immediately ─────────────────────────────
    try:
        with open(REPLICATE_RAW_FILE, "w", encoding="utf-8") as raw_out:
            json.dump(
                output if isinstance(output, (dict, list)) else {"raw": str(output)},
                raw_out,
                ensure_ascii=False,
                indent=2,
            )
        if isinstance(output, dict):
            raw_count = len(output.get("segments", []))
        elif isinstance(output, list):
            raw_count = len(output)
        else:
            raw_count = 0
        print(f"Raw Replicate output saved to {REPLICATE_RAW_FILE} ({raw_count} segments)")
    except Exception as e:
        print("Failed to save raw Replicate output:", e)

    segments = extract_segments(output)
    if not segments:
        raise RuntimeError(
            "No segments (with timestamps) were returned by the Replicate model. "
            "Print the raw output to inspect the response shape."
        )

    # ── fuzzy match each whisperx segment against the canonical text ─────────
    result        = []   # final alignment: [{text, start, end}, ...]
    manual_check  = []   # segments that could not be matched

    for i, seg in enumerate(segments):
        canonical, score = find_best_canonical_line(
            seg["text_norm"], lines_original, lines_norm
        )

        if canonical is not None:
            # Replace whisperx text with the canonical Quranic line
            display_text = canonical
        else:
            # Keep whisperx transcription as fallback
            display_text = seg["text_raw"]
            manual_check.append({
                "segment_index":   i,
                "whisperx_text":   seg["text_raw"],
                "start":           seg["start"],
                "end":             seg["end"],
                "best_score":      round(score, 4),
            })

        result.append({
            "text":  display_text,
            "start": seg["start"],
            "end":   seg["end"],
        })

    # ── save alignment JSON ──────────────────────────────────────────────────
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
            json.dump(result, out, ensure_ascii=False, indent=2)
        print(f"Saved alignment to {OUTPUT_FILE} ({len(result)} segments)")
    except Exception as e:
        print("Failed to save alignment output:", e)

    # ── save manual-check list ───────────────────────────────────────────────
    try:
        with open(MANUAL_CHECK_FILE, "w", encoding="utf-8") as out:
            json.dump(manual_check, out, ensure_ascii=False, indent=2)
        if manual_check:
            print(
                f"⚠  {len(manual_check)} segment(s) could not be matched — "
                f"see {MANUAL_CHECK_FILE} for manual review."
            )
        else:
            print("All segments matched successfully — no manual review needed.")
    except Exception as e:
        print("Failed to save manual-check file:", e)

    # ── write SRT captions ───────────────────────────────────────────────────
    try:
        write_srt(result, SRT_FILE)
    except Exception as e:
        print("Failed to write SRT file:", e)


if __name__ == "__main__":
    main()


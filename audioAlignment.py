import os
import re
import replicate
import json
from difflib import SequenceMatcher

from env_utils import load_project_env

# ── constants ────────────────────────────────────────────────────────────────
TASHKEEL = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")

TEXT_FILE          = "alFurqan.txt"
AUDIO_FILE         = "alFurqan.mp3"
MODEL_REF          = "victor-upmeet/whisperx:84d2ad2d6194fe98a17d2b60bef1c7f910c46b2f6fd38996ca457afd9c8abfcb"
OUTPUT_DIR         = "output_word"
OUTPUT_FILE        = os.path.join(OUTPUT_DIR, "word_alignment.json")
REPLICATE_RAW_FILE = os.path.join(OUTPUT_DIR, "replicate_word_raw_output.json")
MANUAL_CHECK_FILE  = os.path.join(OUTPUT_DIR, "word_manual_check.json")
SRT_FILE           = os.path.join(OUTPUT_DIR, "alFurqan_word.srt")

MATCH_THRESHOLD    = 0.80   # min similarity score to accept a canonical-word match


# ── helpers ──────────────────────────────────────────────────────────────────
def normalize_ar(text: str) -> str:
    text = TASHKEEL.sub("", text)
    text = re.sub("[إأآٱ]", "ا", text)
    text = text.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي").replace("ے", "ي")
    text = re.sub(r"[^\u0621-\u064A\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def seconds_to_srt_time(seconds: float) -> str:
    """Convert a float number of seconds to SRT timestamp HH:MM:SS,mmm."""
    seconds = max(0.0, seconds)
    ms = int(round((seconds % 1) * 1000))
    total_s = int(seconds)
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ── extraction ───────────────────────────────────────────────────────────────
def extract_whisper_words(output) -> list[dict]:
    """Return a list of {word_raw, word_norm, start, end} dicts from whisperx output."""
    words = []

    if isinstance(output, dict):
        segments = output.get("segments", [])
        for segment in segments:
            for word_data in segment.get("words", []):
                raw_word = word_data.get("word") or word_data.get("text") or ""
                start    = word_data.get("start")
                end      = word_data.get("end")
                norm     = normalize_ar(raw_word)
                if norm and start is not None and end is not None:
                    words.append({
                        "word_raw":  raw_word.strip(),
                        "word_norm": norm,
                        "start":     start,
                        "end":       end,
                    })

    elif isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            raw_word = item.get("word") or item.get("text") or ""
            start    = item.get("start")
            end      = item.get("end")
            norm     = normalize_ar(raw_word)
            if norm and start is not None and end is not None:
                words.append({
                    "word_raw":  raw_word.strip(),
                    "word_norm": norm,
                    "start":     start,
                    "end":       end,
                })

    return words


def _count_raw_words(output) -> int:
    """Count total words in the raw Replicate output."""
    if isinstance(output, dict):
        return sum(len(s.get("words", [])) for s in output.get("segments", []))
    if isinstance(output, list):
        return len(output)
    return 0


# ── fuzzy lookup ─────────────────────────────────────────────────────────────
def find_best_canonical_word(
    word_norm: str,
    canon_original: list[str],
    canon_norm: list[str],
    min_score: float = MATCH_THRESHOLD,
) -> tuple[str | None, float]:
    """Search all canonical words for the best fuzzy match.

    Returns (canonical_word, score). canonical_word is None when best score
    is below min_score.
    """
    best_word  = None
    best_score = 0.0

    for orig, norm in zip(canon_original, canon_norm):
        score = similarity(word_norm, norm)
        if score > best_score:
            best_score = score
            best_word  = orig

    if best_score >= min_score:
        return best_word, best_score
    return None, best_score


# ── SRT writer ───────────────────────────────────────────────────────────────
def write_srt(result: list[dict], path: str) -> None:
    """Write a word-level SRT caption file from the result list."""
    with open(path, "w", encoding="utf-8") as f:
        index = 1
        for item in result:
            if item["start"] is None or item["end"] is None:
                continue
            start_ts = seconds_to_srt_time(item["start"])
            end_ts   = seconds_to_srt_time(item["end"])
            f.write(f"{index}\n")
            f.write(f"{start_ts} --> {end_ts}\n")
            f.write(f"{item['word']}\n\n")
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

    # Load canonical words from alFurqan.txt
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(TEXT_FILE, encoding="utf-8") as f:
        quran_text = f.read()
    canon_original = quran_text.split()
    canon_norm     = [normalize_ar(w) for w in canon_original]

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
                    "align_output":                 True,   # word-level alignment
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
        raw_count = _count_raw_words(output)
        print(f"Raw Replicate output saved to {REPLICATE_RAW_FILE} ({raw_count} words)")
    except Exception as e:
        print("Failed to save raw Replicate output:", e)

    words = extract_whisper_words(output)
    if not words:
        raise RuntimeError(
            "No word timestamps were returned by the Replicate model. "
            "Print the raw output to inspect the response shape."
        )

    # ── fuzzy match each whisperx word against the canonical text ────────────
    result       = []
    manual_check = []

    for i, w in enumerate(words):
        canonical, score = find_best_canonical_word(
            w["word_norm"], canon_original, canon_norm
        )

        if canonical is not None:
            display_word = canonical
        else:
            display_word = w["word_raw"]
            manual_check.append({
                "word_index":   i,
                "whisperx_word": w["word_raw"],
                "start":        w["start"],
                "end":          w["end"],
                "best_score":   round(score, 4),
            })

        result.append({
            "word":  display_word,
            "start": w["start"],
            "end":   w["end"],
        })

    # ── save alignment JSON ──────────────────────────────────────────────────
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
            json.dump(result, out, ensure_ascii=False, indent=2)
        print(f"Saved alignment to {OUTPUT_FILE} ({len(result)} words)")
    except Exception as e:
        print("Failed to save alignment output:", e)

    # ── save manual-check list ───────────────────────────────────────────────
    try:
        with open(MANUAL_CHECK_FILE, "w", encoding="utf-8") as out:
            json.dump(manual_check, out, ensure_ascii=False, indent=2)
        if manual_check:
            print(
                f"⚠  {len(manual_check)} word(s) could not be matched — "
                f"see {MANUAL_CHECK_FILE} for manual review."
            )
        else:
            print("All words matched successfully — no manual review needed.")
    except Exception as e:
        print("Failed to save manual-check file:", e)

    # ── write SRT captions ───────────────────────────────────────────────────
    try:
        write_srt(result, SRT_FILE)
    except Exception as e:
        print("Failed to write SRT file:", e)


if __name__ == "__main__":
    main()


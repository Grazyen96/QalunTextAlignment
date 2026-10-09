"""NVIDIA FastConformer Arabic through sherpa-onnx: the runtime the app will ship.

    python run_sherpa.py AUDIO OUT.json --model-dir DIR --label sherpa-int8
"""

import argparse
import os
import time

import sherpa_onnx

from common import SR, chunk_at_pauses, load_audio, write_whisperx_json

WORD_MARK = "▁"
# sherpa-onnx's Python result.tokens already turns the SentencePiece mark into a
# leading space (" وقال", "وا"), so a token starts a word on either.
WORD_STARTS = (WORD_MARK, " ")
MAX_TAIL = 0.5
PUNCT = frozenset(".,،؛;:!?؟\"'«»()[]-…")


def tokens_to_words(tokens, times, *, window_end, offset):
    pieces, pending = [], False
    for tok, t in zip(tokens, times, strict=True):
        starts = tok.startswith(WORD_STARTS)
        text = tok.replace(WORD_MARK, "").strip()
        if not text:
            pending = pending or starts
            continue
        if all(ch in PUNCT for ch in text):
            if pieces:
                pieces[-1][0] += text
            continue
        if starts or pending or not pieces:
            pieces.append([text, t, t])
            pending = False
        else:
            pieces[-1][0] += text
            pieces[-1][2] = t
    words = []
    for i, (text, start, last) in enumerate(pieces):
        nxt = pieces[i + 1][1] if i + 1 < len(pieces) else window_end
        end = max(start, min(nxt, last + MAX_TAIL))
        words.append(
            {"word": text, "start": round(offset + start, 3), "end": round(offset + end, 3), "score": 1.0}
        )
    return words


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("out")
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--label", required=True)
    args = ap.parse_args()

    d = args.model_dir
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=f"{d}/encoder.onnx",
        decoder=f"{d}/decoder.onnx",
        joiner=f"{d}/joiner.onnx",
        tokens=f"{d}/tokens.txt",
        num_threads=max(1, (os.cpu_count() or 1) - 2),
        sample_rate=SR,
        feature_dim=80,
        decoding_method="greedy_search",
        model_type="nemo_transducer",
    )

    audio = load_audio(args.audio)
    windows = list(chunk_at_pauses(audio))
    t0 = time.time()
    segments = []
    for i in range(0, len(windows), 4):
        batch = windows[i : i + 4]
        streams = []
        for a, b in batch:
            s = recognizer.create_stream()
            s.accept_waveform(SR, audio[a:b])
            streams.append(s)
        recognizer.decode_streams(streams)
        for (a, b), s in zip(batch, streams, strict=True):
            r = s.result
            words = tokens_to_words(
                list(r.tokens), list(r.timestamps), window_end=(b - a) / SR, offset=a / SR
            )
            if words:
                segments.append(
                    {
                        "start": words[0]["start"],
                        "end": words[-1]["end"],
                        "text": " ".join(w["word"] for w in words),
                        "words": words,
                    }
                )
    t_asr = time.time() - t0
    write_whisperx_json(
        segments,
        args.out,
        {"engine": args.label, "model_dir": d, "audio_s": round(len(audio) / SR, 1), "asr_s": round(t_asr, 1)},
    )
    print(f"{args.audio}: {sum(len(s['words']) for s in segments)} words, asr {t_asr:.0f}s")


if __name__ == "__main__":
    main()

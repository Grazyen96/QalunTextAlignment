"""Turn the recogniser's sub-word tokens and their times into timed words.

The model emits SentencePiece tokens: a token beginning with the word mark
starts a new word and the tokens after it continue that word. sherpa-onnx's
Python API renders the mark ``▁`` as a leading space (``" وقال"``, and a bare
``" "``), so a token starts a word on either; this mirrors
``prototypes/asr_bakeoff/run_sherpa.py`` exactly. Each token carries only a start
time, so a word ends where the next one starts, capped half a second after its
last token so a long pause does not stretch the word across it. Punctuation the
model writes belongs to the word before it. The rule is the one the ASR bake-off's
parity gate accepted (``prototypes/asr_bakeoff/run_sherpa.py``).
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["MAX_TAIL_SECONDS", "WORD_MARK", "WORD_STARTS", "tokens_to_words"]

WORD_MARK = "▁"
WORD_STARTS = (WORD_MARK, " ")
MAX_TAIL_SECONDS = 0.5
_PUNCT = frozenset(".,،؛;:!?؟\"'«»()[]-…")


def tokens_to_words(
    tokens: Sequence[str],
    times: Sequence[float],
    *,
    window_end: float,
    offset: float = 0.0,
) -> list[dict]:
    """Words with absolute start/end seconds, from one window's tokens."""
    if len(tokens) != len(times):
        raise ValueError(f"{len(tokens)} tokens but {len(times)} times")
    pieces: list[list] = []  # [text, start, last token time]
    pending = False
    for token, t in zip(tokens, times, strict=True):
        starts = token.startswith(WORD_STARTS)
        text = token.replace(WORD_MARK, "").strip()
        if not text:
            pending = pending or starts
            continue
        if text.startswith("<") and text.endswith(">"):  # <unk>, <blk>: not speech
            pending = pending or starts
            continue
        if all(ch in _PUNCT for ch in text):
            if pieces:
                pieces[-1][0] += text
            pending = pending or starts
            continue
        if starts or pending or not pieces:
            pieces.append([text, float(t), float(t)])
            pending = False
        else:
            pieces[-1][0] += text
            pieces[-1][2] = float(t)

    words = []
    for i, (text, start, last) in enumerate(pieces):
        following = pieces[i + 1][1] if i + 1 < len(pieces) else window_end
        end = max(start, min(following, last + MAX_TAIL_SECONDS))
        words.append(
            {
                "word": text,
                "start": round(offset + start, 3),
                "end": round(offset + end, 3),
                "score": 1.0,
            }
        )
    return words

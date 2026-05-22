from __future__ import annotations

import json
from os import PathLike
from pathlib import Path
from typing import Any

from qurantext.utils.time_utils import seconds_to_srt_time


def write_json(data: Any, destination: str | PathLike[str]) -> str:
    """Write JSON data to disk and return the resulting path."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return str(path)


def write_word_srt(result: list[dict], destination: str | PathLike[str]) -> str:
    """Write a word-level SRT caption file."""
    return _write_srt(result, destination, text_key="word")


def write_text_srt(result: list[dict], destination: str | PathLike[str]) -> str:
    """Write a text-level SRT caption file."""
    return _write_srt(result, destination, text_key="text")


def _write_srt(
    result: list[dict],
    destination: str | PathLike[str],
    *,
    text_key: str,
) -> str:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        index = 1
        for item in result:
            if item["start"] is None or item["end"] is None:
                continue
            start_ts = seconds_to_srt_time(item["start"])
            end_ts = seconds_to_srt_time(item["end"])
            fh.write(f"{index}\n")
            fh.write(f"{start_ts} --> {end_ts}\n")
            fh.write(f"{item[text_key]}\n\n")
            index += 1
    return str(path)

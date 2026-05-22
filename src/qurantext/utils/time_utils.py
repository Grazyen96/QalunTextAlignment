from __future__ import annotations


def seconds_to_srt_time(seconds: float) -> str:
    """Convert a float number of seconds to an SRT timestamp."""
    seconds = max(0.0, seconds)
    ms = int(round((seconds % 1) * 1000))
    total_s = int(seconds)
    hours = total_s // 3600
    minutes = (total_s % 3600) // 60
    whole_seconds = total_s % 60
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{ms:03d}"

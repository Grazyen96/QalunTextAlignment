from __future__ import annotations


def seconds_to_srt_time(seconds: float) -> str:
    """Convert a float number of seconds to an SRT timestamp ``HH:MM:SS,mmm``.

    Rounding is done on the total millisecond count so a value like ``3.9996``
    rolls over into the next whole second instead of emitting an invalid
    ``,1000`` fraction.
    """
    total_ms = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"

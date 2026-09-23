"""The window's words, in one table per language.

Every string a person reads in the window comes from here, so adding a
language means adding a table, not editing widgets. English is the fallback for
a key a newer build added before its translation; the key itself is the last
resort, and a test fails the build long before that shows.
"""

from __future__ import annotations

__all__ = ["LANGUAGES", "STRINGS", "current_language", "set_language", "t"]

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # Tasks 3–9 add their keys here, grouped by widget.
        "player.unavailable": "Playback is off on this machine: {details}",
        "waveform.reading": "Reading the recording…",
    },
}
LANGUAGES = tuple(STRINGS)

_current = "en"


def current_language() -> str:
    return _current


def set_language(code: str) -> None:
    global _current
    if code not in STRINGS:
        raise ValueError(f"Unknown language {code!r}; choose from {', '.join(LANGUAGES)}.")
    _current = code


def t(key: str, **fmt: object) -> str:
    text = STRINGS.get(_current, {}).get(key) or STRINGS["en"].get(key) or key
    return text.format(**fmt) if fmt else text

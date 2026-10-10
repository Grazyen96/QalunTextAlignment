"""The home window's remembered choices, over an injectable QSettings.

Tests pass a QSettings on an INI file in a temporary folder, so they never
read or write the person's real settings.

An INI file only holds strings: ``QSettings`` recovers native types for a
value it wrote itself and is still holding in memory, but a value read back
in a fresh process — or hand-edited — comes back as plain text, and a
one-element list collapses to a bare string rather than a list of one. Every
getter here normalises what it reads and falls back to the default for
anything it does not recognise, so a stale or hand-edited settings file can
never crash the window.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from qurantext.config.settings import ENGINES, VIDEO_PRESETS
from qurantext.core.subtitles import SUBTITLE_FORMATS
from qurantext.gui.i18n import LANGUAGES
from qurantext.jobs.project import SUBTITLE_CHOICES

__all__ = ["Prefs"]

_MODES = ("recitation", "lecture")

#: How many surahs there are: a remembered surah outside 1..114 is not one.
_SURAH_COUNT = 114


def _as_positive_int(value: object, highest: int | None = None) -> int | None:
    """Normalise a stored count: an int, or the digits INI wrote; else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value.isdigit():
            return None
        value = int(value)
    if not isinstance(value, int) or value < 1:
        return None
    if highest is not None and value > highest:
        return None
    return value


def _as_str_list(value: object) -> list[str]:
    """Normalise a stored list: missing, a bare string, or a real list."""
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item)]
    return []


def _as_bool(value: object, default: bool) -> bool:
    """Normalise a stored bool: a real bool, or the ``"true"``/``"false"`` INI wrote.

    ``QVariant``'s own string-to-bool conversion (what ``QSettings.value(...,
    type=bool)`` uses) treats any non-empty string other than ``"0"``/``"false"``
    as true, which would read a hand-edited typo as true. Anything else falls
    back to *default* instead.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return default


class Prefs:
    """The home window's remembered choices, over an injectable QSettings.

    Tests pass a QSettings on an INI file in a temporary folder, so they never
    read or write the person's real settings.
    """

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings if settings is not None else QSettings()

    # -- language ---------------------------------------------------------------
    # None until the person picks one: until then the window follows the
    # system's language, so a machine switched to Arabic later still gets it.

    @property
    def language(self) -> str | None:
        value = self._settings.value("language", "")
        return value if isinstance(value, str) and value in LANGUAGES else None

    @language.setter
    def language(self, value: str | None) -> None:
        if value is None:
            self._settings.remove("language")
        elif value in LANGUAGES:
            self._settings.setValue("language", value)
        else:
            raise ValueError(f"Unknown language {value!r}; choose from {', '.join(LANGUAGES)}.")
        self._settings.sync()

    # -- mode -----------------------------------------------------------------

    @property
    def mode(self) -> str:
        value = self._settings.value("mode", "recitation")
        return value if value in _MODES else "recitation"

    @mode.setter
    def mode(self, value: str) -> None:
        self._settings.setValue("mode", value)
        self._settings.sync()

    # -- preset -----------------------------------------------------------------

    @property
    def preset(self) -> str:
        value = self._settings.value("preset", "social")
        return value if isinstance(value, str) and value in VIDEO_PRESETS else "social"

    @preset.setter
    def preset(self, value: str) -> None:
        self._settings.setValue("preset", value)
        self._settings.sync()

    # -- subtitles --------------------------------------------------------------

    @property
    def subtitles(self) -> str:
        value = self._settings.value("subtitles", "burn")
        return value if value in SUBTITLE_CHOICES else "burn"

    @subtitles.setter
    def subtitles(self, value: str) -> None:
        self._settings.setValue("subtitles", value)
        self._settings.sync()

    # -- transcription engine ----------------------------------------------------

    @property
    def engine(self) -> str:
        value = self._settings.value("engine", "local")
        return value if isinstance(value, str) and value in ENGINES else "local"

    @engine.setter
    def engine(self, value: str) -> None:
        self._settings.setValue("engine", value)
        self._settings.sync()

    # -- formats ------------------------------------------------------------

    @property
    def formats(self) -> tuple[str, ...]:
        raw = _as_str_list(self._settings.value("formats"))
        chosen = tuple(dict.fromkeys(item for item in raw if item in SUBTITLE_FORMATS))
        return chosen or ("srt",)

    @formats.setter
    def formats(self, value: tuple[str, ...]) -> None:
        self._settings.setValue("formats", list(value))
        self._settings.sync()

    # -- render_right_away ----------------------------------------------------

    @property
    def render_right_away(self) -> bool:
        return _as_bool(self._settings.value("render_right_away"), False)

    @render_right_away.setter
    def render_right_away(self, value: bool) -> None:
        self._settings.setValue("render_right_away", bool(value))
        self._settings.sync()

    # -- output_dir -----------------------------------------------------------

    @property
    def output_dir(self) -> Path | None:
        value = self._settings.value("output_dir", "")
        return Path(value).resolve() if isinstance(value, str) and value else None

    @output_dir.setter
    def output_dir(self, value: Path | None) -> None:
        if value is None:
            self._settings.setValue("output_dir", "")
        else:
            resolved = Path(value).expanduser().resolve()
            self._settings.setValue("output_dir", str(resolved))
            self._add_job_dir(resolved)
        self._settings.sync()

    # -- quran_override ---------------------------------------------------------

    @property
    def quran_override(self) -> Path | None:
        value = self._settings.value("quran_override", "")
        return Path(value).resolve() if isinstance(value, str) and value else None

    @quran_override.setter
    def quran_override(self, value: Path | None) -> None:
        if value is None:
            self._settings.setValue("quran_override", "")
        else:
            self._settings.setValue("quran_override", str(Path(value).expanduser().resolve()))
        self._settings.sync()

    # -- more_options_open --------------------------------------------------

    @property
    def more_options_open(self) -> bool:
        return _as_bool(self._settings.value("more_options_open"), False)

    @more_options_open.setter
    def more_options_open(self, value: bool) -> None:
        self._settings.setValue("more_options_open", bool(value))
        self._settings.sync()

    # -- the last surah and range --------------------------------------------
    # Restored by the new-job panel once the surah list has loaded, clamped to
    # that surah's ayah count, so a hand-edited range cannot run past its end.

    @property
    def surah_num(self) -> int | None:
        return _as_positive_int(self._settings.value("surah_num"), _SURAH_COUNT)

    @surah_num.setter
    def surah_num(self, value: int | None) -> None:
        self._write_optional_int("surah_num", value)

    @property
    def from_ayah(self) -> int | None:
        return _as_positive_int(self._settings.value("from_ayah"))

    @from_ayah.setter
    def from_ayah(self, value: int | None) -> None:
        self._write_optional_int("from_ayah", value)

    @property
    def to_ayah(self) -> int | None:
        return _as_positive_int(self._settings.value("to_ayah"))

    @to_ayah.setter
    def to_ayah(self, value: int | None) -> None:
        self._write_optional_int("to_ayah", value)

    def _write_optional_int(self, key: str, value: int | None) -> None:
        self._settings.setValue(key, "" if value is None else int(value))
        self._settings.sync()

    # -- hidden_jobs ----------------------------------------------------------

    @property
    def hidden_jobs(self) -> set[Path]:
        raw = _as_str_list(self._settings.value("hidden_jobs"))
        return {Path(item).resolve() for item in raw}

    @hidden_jobs.setter
    def hidden_jobs(self, value: set[Path]) -> None:
        self._write_hidden({Path(path).resolve() for path in value})

    def hide_job(self, path: Path) -> None:
        """Add *path* to the hidden set, without touching the file it names."""
        self._write_hidden(self.hidden_jobs | {Path(path).resolve()})

    def unhide_job(self, path: Path) -> None:
        """Remove *path* from the hidden set. Fine when it was never hidden."""
        self._write_hidden(self.hidden_jobs - {Path(path).resolve()})

    def _write_hidden(self, hidden: set[Path]) -> None:
        self._settings.setValue("hidden_jobs", [str(path) for path in sorted(hidden)])
        self._settings.sync()

    # -- job_dirs ---------------------------------------------------------------

    @property
    def job_dirs(self) -> list[Path]:
        raw = _as_str_list(self._settings.value("job_dirs"))
        seen: set[Path] = set()
        dirs: list[Path] = []
        for item in raw:
            resolved = Path(item).resolve()
            if resolved not in seen:
                seen.add(resolved)
                dirs.append(resolved)
        return dirs

    @job_dirs.setter
    def job_dirs(self, value: list[Path]) -> None:
        self._write_job_dirs(value)

    def _add_job_dir(self, folder: Path) -> None:
        """Remember *folder* as an extra place to scan, unless it already is one."""
        current = self.job_dirs
        if folder not in current:
            self._write_job_dirs([*current, folder])

    def _write_job_dirs(self, dirs: list[Path]) -> None:
        seen: set[Path] = set()
        ordered: list[Path] = []
        for folder in dirs:
            resolved = Path(folder).resolve()
            if resolved not in seen:
                seen.add(resolved)
                ordered.append(resolved)
        self._settings.setValue("job_dirs", [str(path) for path in ordered])
        self._settings.sync()

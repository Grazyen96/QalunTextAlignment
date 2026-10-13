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

import json
import threading
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings

from qurantext.config.paths import redirect_retired_quran, user_data_dir
from qurantext.config.settings import ENGINES, VIDEO_PRESETS
from qurantext.core.looks import NIGHT_GOLD, Look, look_from_style
from qurantext.core.subtitles import SUBTITLE_FORMATS
from qurantext.gui.i18n import LANGUAGES
from qurantext.gui.theme import MODES as THEME_MODES
from qurantext.jobs.episode_assets import EPISODE_SUFFIXES, GeneratedIntro, GeneratedOutro
from qurantext.jobs.look_assets import copy_by_content
from qurantext.jobs.project import SUBTITLE_CHOICES

__all__ = ["KEEP_DEFAULT", "Prefs"]

_MODES = ("recitation", "lecture")

#: How many surahs there are: a remembered surah outside 1..114 is not one.
_SURAH_COUNT = 114

#: Default clips a running job was started with (``hold_default_clips``), each
#: with how many jobs hold it. A new lecture's matching copies its default
#: intro and outro beside it only when matching ends, so a default replaced
#: meanwhile must stay on disk until then. Shared by every ``Prefs``: the
#: window and its reviews may hold different ones over the same folder.
_HELD_CLIPS: Counter[Path] = Counter()
_HELD_LOCK = threading.Lock()


#: Passed to ``save_default_episode`` for a part to leave as it is stored.
KEEP_DEFAULT = object()


def _held_clips() -> set[str]:
    with _HELD_LOCK:
        return {str(path) for path, count in _HELD_CLIPS.items() if count > 0}


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

    # -- theme ------------------------------------------------------------------

    @property
    def theme(self) -> str:
        """``system`` (follow the desktop), ``light`` or ``dark``; anything else reads as ``system``."""
        value = self._settings.value("theme", "system")
        return value if isinstance(value, str) and value in THEME_MODES else "system"

    @theme.setter
    def theme(self, value: str) -> None:
        if value not in THEME_MODES:
            raise ValueError(f"Unknown theme {value!r}; choose from {', '.join(THEME_MODES)}.")
        self._settings.setValue("theme", value)
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
        """The chosen Quran text, or None for the bundled one.

        A saved choice of a text an earlier version bundled, now gone, reads as
        None: the bundled text that replaced it is the default.
        """
        value = self._settings.value("quran_override", "")
        if not (isinstance(value, str) and value):
            return None
        path = Path(value).resolve()
        return None if redirect_retired_quran(path) != path else path

    @quran_override.setter
    def quran_override(self, value: Path | None) -> None:
        if value is None:
            self._settings.setValue("quran_override", "")
        else:
            self._settings.setValue("quran_override", str(Path(value).expanduser().resolve()))
        self._settings.sync()

    # -- default_look -----------------------------------------------------------
    # The look new videos start with. Stored with an absolute image path into the
    # app's own folder, so deleting the original photo does not lose it.

    @property
    def default_look(self) -> Look:
        raw = self._settings.value("default_look", "")
        if not isinstance(raw, str) or not raw:
            return NIGHT_GOLD
        try:
            return look_from_style(json.loads(raw))
        except ValueError:  # json.JSONDecodeError is a ValueError
            return NIGHT_GOLD

    @default_look.setter
    def default_look(self, look: Look) -> None:
        self.save_default_look(look)

    def save_default_look(self, look: Look) -> Look:
        """Remember *look* for new videos; return the look as stored.

        An image is copied into the app's own ``looks`` folder, named by its
        content, and the stored look points there. Raises what
        :func:`~qurantext.jobs.look_assets.copy_by_content` raises (``ValueError``,
        ``OSError``) when the image cannot be copied; nothing is stored then.
        """
        bg = look.background
        if bg.kind == "image" and bg.image is not None:
            copied = copy_by_content(bg.image, user_data_dir() / "looks")
            look = replace(look, background=replace(bg, image=copied))
        self._settings.setValue("default_look", json.dumps(look.to_dict()))
        self._settings.sync()
        return look

    def default_look_style(self) -> dict:
        """The default look as a project style (empty for Night gold)."""
        look = self.default_look
        return {} if look == NIGHT_GOLD else look.to_dict()

    # -- default_episode --------------------------------------------------------
    # The intro and outro new lectures start with: each a clip or generated
    # settings, never both. A clip is stored as an absolute path into the app's
    # own folder, so deleting or moving the original clip does not lose it.
    # The recitation is never a default: it differs per lecture.
    # Each part's generated settings are also remembered apart from its kind
    # ("<part>_remembered"): a part set to None or a clip keeps its channel
    # name, phrase and link for when it is Generated again.

    def _default_episode_data(self) -> dict:
        """The stored default episode as a dict; empty when unset or unreadable."""
        raw = self._settings.value("default_episode", "")
        if not isinstance(raw, str) or not raw:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:  # json.JSONDecodeError is a ValueError
            return {}
        return data if isinstance(data, dict) else {}

    def _default_episode_parts(self) -> dict[str, tuple[Path, str | None]]:
        """The stored default clips, each as (path, original name), by part; tolerant.

        A part with generated settings has no clip, whatever else is stored for it.
        """
        data = self._default_episode_data()
        parts: dict[str, tuple[Path, str | None]] = {}
        for key in ("intro", "outro"):
            if isinstance(data.get(f"{key}_generated"), dict):
                continue
            value = data.get(key)
            if not isinstance(value, str) or not value:
                continue
            path = Path(value)
            if not path.is_absolute() or path.suffix.lower() not in EPISODE_SUFFIXES:
                continue
            name = data.get(f"{key}_name")
            parts[key] = (path, name if isinstance(name, str) and name.strip() else None)
        return parts

    @property
    def default_episode(self) -> tuple[Path | None, Path | None]:
        """The default intro and outro clips; ``(None, None)`` when unset or unreadable."""
        parts = self._default_episode_parts()
        intro, outro = parts.get("intro"), parts.get("outro")
        return (intro[0] if intro else None, outro[0] if outro else None)

    @property
    def default_episode_names(self) -> tuple[str | None, str | None]:
        """The default clips' original file names (their copies are named by content)."""
        parts = self._default_episode_parts()
        intro, outro = parts.get("intro"), parts.get("outro")
        return (intro[1] if intro else None, outro[1] if outro else None)

    @property
    def default_intro_generated(self) -> GeneratedIntro | None:
        """The default generated intro's settings; None when the default is a clip or none."""
        return GeneratedIntro.from_dict(self._default_episode_data().get("intro_generated"))

    @property
    def default_outro_generated(self) -> GeneratedOutro | None:
        """The default generated outro's settings; None when the default is a clip or none."""
        return GeneratedOutro.from_dict(self._default_episode_data().get("outro_generated"))

    @property
    def remembered_intro_generated(self) -> GeneratedIntro | None:
        """The intro's generated settings last kept, whatever its default kind is now."""
        return self._remembered("intro", GeneratedIntro)  # type: ignore[return-value]

    @property
    def remembered_outro_generated(self) -> GeneratedOutro | None:
        """The outro's generated settings last kept, whatever its default kind is now."""
        return self._remembered("outro", GeneratedOutro)  # type: ignore[return-value]

    def _remembered(self, key: str, kind: type) -> GeneratedIntro | GeneratedOutro | None:
        data = self._default_episode_data()
        made = data.get(f"{key}_generated")
        return kind.from_dict(made if isinstance(made, dict) else data.get(f"{key}_remembered"))

    @property
    def default_episode_kinds(self) -> tuple[str, str]:
        """Each default part's kind: ``"none"``, ``"clip"`` or ``"generated"``."""
        clips = self.default_episode
        generated = (self.default_intro_generated, self.default_outro_generated)
        return tuple(  # type: ignore[return-value]
            "generated" if made is not None else "clip" if clip is not None else "none"
            for clip, made in zip(clips, generated, strict=True)
        )

    def save_default_episode(
        self,
        intro: Path | None | object,
        outro: Path | None | object,
        *,
        names: tuple[str | None, str | None] = (None, None),
        intro_generated: GeneratedIntro | None | object = KEEP_DEFAULT,
        outro_generated: GeneratedOutro | None | object = KEEP_DEFAULT,
        intro_remembered: GeneratedIntro | object = KEEP_DEFAULT,
        outro_remembered: GeneratedOutro | object = KEEP_DEFAULT,
    ) -> None:
        """Remember *intro* and *outro* for new lectures; None clears that part.

        :data:`KEEP_DEFAULT` for a part leaves it as it is stored (the Episode
        dialog changes only the part the person changed). Each new clip is
        copied into the app's own ``episode`` folder, named by its content,
        and the stored path points there; its original name (*names*, else the
        clip's own file name) is kept beside it, for showing. Raises what
        :func:`~qurantext.jobs.look_assets.copy_by_content` raises
        (``ValueError``, ``OSError``) when a clip cannot be copied; nothing is
        stored then.

        A part is a clip or generated, so for each part:

        - generated settings (*intro_generated*) are stored, and its clip goes;
        - else a clip or None (not :data:`KEEP_DEFAULT`) decides the part, and
          its generated settings go;
        - else None for its generated settings removes them, keeping its clip;
        - else (both kept) the part stays as it is.

        Generated settings that stop being the default stay remembered
        (:attr:`remembered_intro_generated`). *intro_remembered* replaces the
        remembered settings without changing the part's kind; when the part is
        generated by default, its default follows them (the Episode dialog
        keeps there only the fields the person changed).

        Raises ``TypeError`` for settings of the other part's type.
        """
        folder = user_data_dir() / "episode"
        current = self._default_episode_parts()
        data = self._default_episode_data()
        value: dict[str, object] = {}
        for key, clip, name, generated, remembered, kind in (
            ("intro", intro, names[0], intro_generated, intro_remembered, GeneratedIntro),
            ("outro", outro, names[1], outro_generated, outro_remembered, GeneratedOutro),
        ):
            for label, given in (
                (f"{key}_generated", generated),
                (f"{key}_remembered", remembered),
            ):
                if given is not KEEP_DEFAULT and given is not None and not isinstance(given, kind):
                    # An outro's settings given as the intro's would read back empty.
                    raise TypeError(
                        f"{label} must be a {kind.__name__}, not {type(given).__name__}"
                    )
            kept_settings = data.get(f"{key}_generated")
            kept_settings = kept_settings if isinstance(kept_settings, dict) else None
            kept_memory = data.get(f"{key}_remembered")
            memory = kept_settings or (kept_memory if isinstance(kept_memory, dict) else None)
            if isinstance(remembered, kind):
                memory = remembered.to_dict()
                if kept_settings is not None:
                    kept_settings = memory  # generated by default: the default follows
            if isinstance(generated, kind):
                clip = None
                value[f"{key}_generated"] = memory = generated.to_dict()
            elif clip is KEEP_DEFAULT and generated is KEEP_DEFAULT:
                value[f"{key}_generated"] = kept_settings
            else:
                value[f"{key}_generated"] = None
            value[f"{key}_remembered"] = memory
            if clip is KEEP_DEFAULT:
                kept = current.get(key)
                value[key] = str(kept[0]) if kept else None
                value[f"{key}_name"] = kept[1] if kept else None
            elif clip is None:
                value[key] = value[f"{key}_name"] = None
            else:
                clip = Path(clip)  # type: ignore[arg-type]
                copy = copy_by_content(clip, folder, suffixes=EPISODE_SUFFIXES).resolve()
                value[key] = str(copy)
                value[f"{key}_name"] = name or clip.name
        self._settings.setValue("default_episode", json.dumps(value))
        self._settings.sync()
        kept_paths = {value[key] for key in ("intro", "outro") if value[key] is not None}
        _remove_clips_but(folder, kept_paths | _held_clips())  # type: ignore[arg-type]

    def hold_default_clips(self, clips: Iterable[Path | None]) -> Callable[[], None]:
        """Keep *clips* (a job's ``episode_defaults``) on disk until the returned call.

        A job started with these defaults copies them later; another default
        chosen meanwhile replaces them in the settings but does not delete
        them. The returned function lets go (once; a second call does nothing)
        and removes what no default and no other job names any more.
        """
        held = [Path(clip).resolve() for clip in clips if clip]
        with _HELD_LOCK:
            _HELD_CLIPS.update(held)
        released = False

        def release() -> None:
            nonlocal released
            if released:
                return
            released = True
            with _HELD_LOCK:
                _HELD_CLIPS.subtract(held)
                for path in held:
                    if _HELD_CLIPS[path] <= 0:
                        del _HELD_CLIPS[path]
            if held:
                defaults = {str(clip.resolve()) for clip in self.default_episode if clip}
                _remove_clips_but(user_data_dir() / "episode", defaults | _held_clips())

        return release

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

    # -- the last studied surah ------------------------------------------------
    # Its own key: a lecture's "Detect automatically" or chosen surah must not
    # move the recitation's surah and range, nor they it.

    @property
    def lecture_surah(self) -> int | None:
        """The surah a new lecture's cards keep to; None is "Detect automatically"."""
        return _as_positive_int(self._settings.value("lecture_surah"), _SURAH_COUNT)

    @lecture_surah.setter
    def lecture_surah(self, value: int | None) -> None:
        self._write_optional_int("lecture_surah", value)

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


def _remove_clips_but(folder: Path, kept: set[str]) -> None:
    """Delete the clips in *folder* other than *kept*: earlier defaults no one names now.

    The folder is the app's own, written only by ``save_default_episode``, and
    an intro can be hundreds of megabytes; trying a few must not leave them
    all behind. A clip that will not go is left for the next save.
    """
    if not folder.is_dir():
        return
    keep = {Path(path).resolve() for path in kept}
    for clip in folder.iterdir():
        if clip.suffix.lower() in EPISODE_SUFFIXES and clip.resolve() not in keep:
            try:
                clip.unlink()
            except OSError:
                continue

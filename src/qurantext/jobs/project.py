"""The project file: the job's own record of what to render.

Captions used to be derived at render time. ``load_caption_segments`` reached
through the match file's metadata to the raw recognition JSON and rebuilt the
cues from scratch on every render, so there was nowhere for a correction to
live: fix a misheard word and the next render would silently discard it.

A project makes that data the job's own. Recognition output is turned into cues
once, written here, and read back from here; after that the file is the source
of truth and nothing re-derives it. That is the whole prerequisite for editing
subtitles in an application, and it is why this lands before any window.

The Quran text is deliberately NOT editable through this file. A card records
*which* ayah and *when*, and the canonical text is looked up from the store at
render time. Correcting a detection means changing the reference or the timing,
never the characters.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from os import PathLike
from pathlib import Path
from typing import Any

from qurantext.core.video_common import load_caption_segments, load_matches

__all__ = [
    "PROJECT_VERSION",
    "CaptionCue",
    "Project",
    "load_project",
    "save_project",
]

#: Bumped when the on-disk shape changes incompatibly.
PROJECT_VERSION = "1"


@dataclass(slots=True)
class CaptionCue:
    """One editable subtitle line.

    *text* is recognised speech and is meant to be corrected. *words* carries
    the per-word timings the karaoke highlight needs; an editor that rewrites
    *text* should drop them rather than leave them disagreeing with it, which
    is what :meth:`edited` does.
    """

    start: float
    end: float
    text: str
    words: list[dict[str, Any]] = field(default_factory=list)

    def edited(self, text: str) -> CaptionCue:
        """Return this cue with corrected *text* and stale word timings dropped."""
        if text == self.text:
            return self
        return replace(self, text=text, words=[])

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "start": round(float(self.start), 3),
            "end": round(float(self.end), 3),
            "text": self.text,
        }
        if self.words:
            data["words"] = self.words
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaptionCue:
        return cls(
            start=float(data["start"]),
            end=float(data["end"]),
            text=str(data.get("text") or ""),
            words=list(data.get("words") or []),
        )


@dataclass(slots=True)
class Project:
    """Everything one render job needs, in a form a person can edit."""

    audio: Path
    mode: str = "recitation"
    #: Detected ayah cards. Reference and timing are editable; the text is not.
    cards: list[dict[str, Any]] = field(default_factory=list)
    #: Recognised subtitle cues, fully editable.
    captions: list[CaptionCue] = field(default_factory=list)
    #: Render style tokens. Phase 5 fills this in; unknown keys are preserved.
    style: dict[str, Any] = field(default_factory=dict)
    #: Export choices (burn-in, sidecar files, formats). Preserved verbatim.
    export: dict[str, Any] = field(default_factory=dict)
    #: Where this project was loaded from, when it was.
    path: Path | None = None

    # -- construction ---------------------------------------------------------

    @classmethod
    def from_match_file(
        cls,
        matches: str | PathLike[str],
        audio: str | PathLike[str],
        *,
        mode: str | None = None,
    ) -> Project:
        """Derive a project from a match result, once.

        This is the only place recognition output is turned into cues. After the
        project is saved, rendering reads the cues from it, so corrections
        survive.
        """
        matches_path = Path(matches).expanduser().resolve()
        raw = load_matches(matches_path)
        cues = [
            CaptionCue(
                start=float(segment["start"]),
                end=float(segment["end"]),
                text=str(segment["text"]),
                words=list(segment.get("word_timings") or []),
            )
            for segment in load_caption_segments(matches_path)
        ]

        resolved_mode = mode
        if resolved_mode is None:
            try:
                payload = json.loads(matches_path.read_text(encoding="utf-8"))
                resolved_mode = str((payload.get("meta") or {}).get("mode") or "recitation")
            except (OSError, json.JSONDecodeError, AttributeError):
                resolved_mode = "recitation"

        return cls(
            audio=Path(audio).expanduser().resolve(),
            mode=resolved_mode,
            cards=raw,
            captions=cues,
        )

    # -- serialisation --------------------------------------------------------

    def to_dict(self, *, relative_to: Path | None = None) -> dict[str, Any]:
        return {
            "project_version": PROJECT_VERSION,
            "audio": _store_path(self.audio, relative_to),
            "mode": self.mode,
            "cards": self.cards,
            "captions": [cue.to_dict() for cue in self.captions],
            "style": self.style,
            "export": self.export,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, base_dir: Path | None = None) -> Project:
        version = str(data.get("project_version") or "")
        if version and version != PROJECT_VERSION:
            raise ValueError(
                f"Project file version {version!r} is not supported by this build "
                f"(expected {PROJECT_VERSION!r})."
            )
        return cls(
            audio=_resolve_path(str(data["audio"]), base_dir),
            mode=str(data.get("mode") or "recitation"),
            cards=list(data.get("cards") or []),
            captions=[CaptionCue.from_dict(cue) for cue in (data.get("captions") or [])],
            style=dict(data.get("style") or {}),
            export=dict(data.get("export") or {}),
        )

    def caption_segments(self) -> list[dict[str, Any]]:
        """Cues in the shape the renderer's caption band expects."""
        return [
            {
                "text": cue.text,
                "start": float(cue.start),
                "end": float(cue.end),
                "word_timings": list(cue.words),
            }
            for cue in self.captions
        ]


def save_project(project: Project, destination: str | PathLike[str]) -> Path:
    """Write *project* as JSON, with media paths relative to it where possible."""
    path = Path(destination).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = project.to_dict(relative_to=path.parent)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    project.path = path
    return path


def load_project(source: str | PathLike[str]) -> Project:
    """Read a project, resolving its media paths against its own directory."""
    path = Path(source).expanduser().resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Project file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Failed to parse project file '{path}': {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Project file '{path}' does not contain a JSON object.")

    project = Project.from_dict(data, base_dir=path.parent)
    project.path = path
    return project


def _store_path(value: Path, relative_to: Path | None) -> str:
    """Prefer a relative path so a project folder can be moved or shared."""
    resolved = Path(value).expanduser().resolve()
    if relative_to is not None:
        try:
            return resolved.relative_to(Path(relative_to).resolve()).as_posix()
        except ValueError:
            pass
    return resolved.as_posix()


def _resolve_path(value: str, base_dir: Path | None) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or base_dir is None:
        return candidate.resolve()
    return (Path(base_dir) / candidate).resolve()

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

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass, field, replace
from datetime import datetime
from os import PathLike
from pathlib import Path
from typing import Any

from qurantext.core.video_common import load_caption_segments, load_matches

__all__ = [
    "PROJECT_VERSION",
    "REVIEW_STATES",
    "SUPPORTED_VERSIONS",
    "CaptionCue",
    "Project",
    "load_project",
    "project_path_for",
    "save_project",
]

#: Bumped when the on-disk shape changes incompatibly.
PROJECT_VERSION = "2"
#: Versions this build reads. Version 1 is upgraded on the next save.
SUPPORTED_VERSIONS = ("1", "2")
REVIEW_STATES = ("needs_review", "reviewed")

_KNOWN_KEYS = frozenset(
    {
        "project_version",
        "audio",
        "mode",
        "matches",
        "cards",
        "captions",
        "style",
        "export",
        "review",
        "render",
    }
)


def _default_review() -> dict[str, Any]:
    return {"state": "needs_review", "reviewed_at": None}


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
        """Return this cue with corrected *text*.

        Fixing a misheard word keeps the word count, so the timings still
        describe the words and are kept, relabelled in order. A rewrite that
        changes the count drops them rather than leave a karaoke highlight
        disagreeing with the line.
        """
        if text == self.text:
            return self
        tokens = text.split()
        if self.words and len(tokens) == len(self.words):
            words = [
                {**word, "word": token} for word, token in zip(self.words, tokens, strict=True)
            ]
        else:
            words = []
        return replace(self, text=text, words=words)

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
    #: The match file this project was derived from. The basmala splice reads
    #: its metadata at render time.
    matches: Path | None = None
    #: ``{"state": "needs_review" | "reviewed", "reviewed_at": iso | None}``.
    review: dict[str, Any] = field(default_factory=_default_review)
    #: The last successful render, or None. See :meth:`record_render`.
    render: dict[str, Any] | None = None
    #: Top-level keys this build does not know, written back untouched.
    extra: dict[str, Any] = field(default_factory=dict)
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
            matches=matches_path,
        )

    # -- serialisation --------------------------------------------------------

    def to_dict(self, *, relative_to: Path | None = None) -> dict[str, Any]:
        data: dict[str, Any] = dict(self.extra)
        render = None
        if self.render is not None:
            render = dict(self.render)
            if render.get("video"):
                render["video"] = _store_path(Path(render["video"]), relative_to)
        data.update(
            {
                "project_version": PROJECT_VERSION,
                "audio": _store_path(self.audio, relative_to),
                "matches": _store_path(self.matches, relative_to) if self.matches else None,
                "mode": self.mode,
                "cards": self.cards,
                "captions": [cue.to_dict() for cue in self.captions],
                "style": self.style,
                "export": self.export,
                "review": self.review,
                "render": render,
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, base_dir: Path | None = None) -> Project:
        version = str(data.get("project_version") or "")
        if version and version not in SUPPORTED_VERSIONS:
            raise ValueError(
                f"Project file version {version!r} is not supported by this build "
                f"(expected one of {', '.join(SUPPORTED_VERSIONS)})."
            )
        render = data.get("render")
        if isinstance(render, dict):
            render = dict(render)
            if render.get("video"):
                render["video"] = _resolve_path(str(render["video"]), base_dir)
        else:
            render = None
        review = data.get("review")
        cards = _list_of_dicts(data, "cards")
        captions = _list_of_dicts(data, "captions")
        return cls(
            audio=_resolve_path(str(data["audio"]), base_dir),
            mode=str(data.get("mode") or "recitation"),
            cards=cards,
            captions=[CaptionCue.from_dict(cue) for cue in captions],
            style=dict(data.get("style") or {}),
            export=dict(data.get("export") or {}),
            matches=_resolve_path(str(data["matches"]), base_dir) if data.get("matches") else None,
            review=dict(review) if isinstance(review, dict) else _default_review(),
            render=render,
            extra={k: v for k, v in data.items() if k not in _KNOWN_KEYS},
        )

    def content_hash(self) -> str:
        """A digest of what a render depends on: the cards and the captions."""
        payload = json.dumps(
            {"cards": self.cards, "captions": [cue.to_dict() for cue in self.captions]},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def record_render(
        self,
        video: Path,
        *,
        preset: str | None,
        basmala_offset_s: float,
        when: datetime | None = None,
        content_hash: str | None = None,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
    ) -> None:
        """Remember a successful render and the content it was made from.

        Pass *content_hash* when the render was made from a snapshot taken
        before it started: an edit made while it ran must leave it stale, which
        hashing the project as it is now would hide. *width*, *height* and
        *fps* are the geometry actually rendered, which the subtitle export
        reuses so an ASS file matches the video.
        """
        self.render = {
            "video": Path(video).expanduser().resolve(),
            "preset": preset,
            "width": width,
            "height": height,
            "fps": fps,
            "basmala_offset_s": round(float(basmala_offset_s), 3),
            "rendered_at": (when or datetime.now()).isoformat(timespec="seconds"),
            "content_hash": content_hash if content_hash is not None else self.content_hash(),
        }

    @property
    def render_is_stale(self) -> bool:
        """True when the cards or captions changed after the last render."""
        return self.render is not None and self.render.get("content_hash") != self.content_hash()

    def mark_reviewed(self, when: datetime | None = None) -> None:
        """Record that a person has reviewed this project's content."""
        self.review = {
            "state": "reviewed",
            "reviewed_at": (when or datetime.now()).isoformat(timespec="seconds"),
        }

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


def project_path_for(match_path: str | PathLike[str]) -> Path:
    """Where a job's project lives: beside its match file.

    The one rule every writer follows, so the window, the command line and the
    job list all find the same file.
    """
    return Path(match_path).with_suffix(".qalun.json")


def save_project(project: Project, destination: str | PathLike[str]) -> Path:
    """Write *project* as JSON, with media paths relative to it where possible.

    The file holds a person's corrections, so it is written to a temporary file
    beside it and moved into place: a crash or a full disk mid-write leaves the
    previous version, never half of the new one.
    """
    path = Path(destination).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = project.to_dict(relative_to=path.parent)
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        # A temporary file is private to its owner; the project should not become so.
        os.chmod(handle.name, _mode_for(path))
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise
    project.path = path
    return path


def _mode_for(path: Path) -> int:
    """The existing file's permissions, or the usual ones for a new file."""
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return 0o644


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


def _list_of_dicts(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Refuse a hand-edited or truncated shape here, by name, not later with an AttributeError."""
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Project field '{key}' must be a list of objects.")
    return list(value)


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

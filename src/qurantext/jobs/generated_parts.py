"""A lecture's generated intro and outro: their specs, read from the lecture, and their clips.

The intro's title line is not stored with its settings: it is read from the
lecture's on-screen cards each time (``title_for``), so a correction in the
review shows in the next render. The outro's link is tracked
(:func:`~qurantext.core.tracked_link.tracked_link`) with the platform the
person publishes on and a campaign naming the lecture's surah and ayat.

A clip is made in the project's episode folder, named by a hash of all it is
made from (``generated-intro-<hash12>.mp4``): its spec, the look's colours and
background (a background photo by its content, so a photo that was missing
when a clip was made, and is back, makes a new one; moving the project folder
does not), the size and the frame rate. A render that changes none of them
reuses the clip; one that changes any makes a new one and removes the earlier
ones of that part.

Which edge "reveal" uncovers from (the spec's ``rtl``) is taken from the
clip's own text, not from the window's language: the clip is read by the
video's viewers, whose script is the text's, and a person switching the
window to English must not remake (or mirror) a clip of Arabic words. The
title line is always Arabic, so only a name or phrase that starts with a
Latin letter uncovers from the left. A caller may still say otherwise.
"""

from __future__ import annotations

import hashlib
import logging
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from qurantext.core.arabic import surah_title
from qurantext.core.looks import Look
from qurantext.core.title_cards import (
    IntroSpec,
    OutroSpec,
    qr_fits,
    render_title_clip,
)
from qurantext.core.tracked_link import campaign_for, readable_link, tracked_link
from qurantext.core.video_common import cards_on_screen, is_drawable_card, lecture_span
from qurantext.jobs.episode import EpisodeError
from qurantext.jobs.episode_assets import GeneratedIntro, GeneratedOutro, episode_dir_for
from qurantext.jobs.project import Project, job_settings
from qurantext.utils.progress import CancelToken, JobCancelled, ProgressCallback

__all__ = [
    "KINDS",
    "ensure_generated_part",
    "generated_part_path",
    "intro_spec_for",
    "outro_spec_for",
    "remove_generated_parts",
    "title_for",
]

_log = logging.getLogger(__name__)

#: The parts that can be generated.
KINDS = ("intro", "outro")

_ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
_SURAH = "سورة"
#: The title's separator: the Arabic comma. Amiri draws a middle dot between
#: Arabic words like an Arabic zero.
_COMMA = "،"
_DASH = "–"


def _digits(number: int) -> str:
    return str(number).translate(_ARABIC_DIGITS)


def _surah_title(surah: int | str, names: Mapping[int, str], cards: list[dict[str, Any]]) -> str:
    """«سورة الفرقان»: the store's name, else the cards' own, else the surah's number.

    Written in plain letters (:func:`~qurantext.core.arabic.surah_title`): the
    store spells names with their vowel marks («سُورَةُ آلِ عِمْرَانَ»).
    """
    if isinstance(surah, str):
        return surah_title(surah)
    name = names.get(surah) or next(
        (
            str(card.get("surah_name"))
            for card in cards
            if card.get("surah_num") == surah and str(card.get("surah_name") or "").strip()
        ),
        "",
    )
    return surah_title(str(name)) or f"{_SURAH} {_digits(surah)}"


def title_for(
    project: Project, surah_names: Mapping[int, str]
) -> tuple[str, int | None, int | None, int | None]:
    """The intro's title line and what it names: ``(text, surah, from, to)``.

    The surah and range are the ones the lecture's own opening card announces
    (:func:`~qurantext.core.video_common.lecture_span` over the cards the video
    draws): the studied surah the person chose, else the automatic guess the
    cards keep to, in which a hand-made card does not vote; the range is the
    lowest and highest ayah of that surah's cards, hand-made ones included.
    The intro, its link's campaign and the lecture's opening card therefore
    always name the same surah.

    The text is «سورة الفرقان، الآيات ٤٤–٤٩» in Arabic-Indic digits, «سورة
    الفرقان، الآية ٧» for one ayah, the surah's name alone without ayat, and ""
    without a surah. *surah_names* are the store's
    (``data.quran_db.stored_surah_names``); a surah missing from them is named
    as its cards name it. A surah its cards know only by name gives that name
    and no number (the campaign is then ``qalun-lecture``).
    """
    studied = job_settings(project).studied_surah
    cards = [card for card in project.cards if isinstance(card, dict) and is_drawable_card(card)]
    shown = cards_on_screen(cards, project.mode, studied)
    surah, low, high = lecture_span(shown, studied)
    if surah is None:
        return "", None, None, None
    name = _surah_title(surah, surah_names, shown)
    number = surah if isinstance(surah, int) else None
    if low is None or high is None:
        return name, number, None, None
    if low == high:
        return f"{name}{_COMMA} الآية {_digits(low)}", number, low, high
    return f"{name}{_COMMA} الآيات {_digits(low)}{_DASH}{_digits(high)}", number, low, high


def _reads_right_to_left(*texts: str) -> bool:
    """Whether the first of *texts* with a strong letter starts with a right-to-left one."""
    for text in texts:
        for char in text:
            kind = unicodedata.bidirectional(char)
            if kind in ("R", "AL"):
                return True
            if kind == "L":
                return False
    return True


def intro_spec_for(
    project: Project,
    settings: GeneratedIntro,
    surah_names: Mapping[int, str],
    *,
    rtl: bool | None = None,
) -> IntroSpec:
    """The intro *settings* make for *project*: its name above the lecture's title line.

    *rtl* (the edge "reveal" uncovers from) is the name's direction, else the
    title's, unless given.
    """
    name = " ".join(settings.name.split())
    title = title_for(project, surah_names)[0]
    return IntroSpec(
        name=name,
        title=title,
        style=settings.style,
        seconds=settings.seconds,
        rtl=_reads_right_to_left(name, title) if rtl is None else rtl,
    )


def outro_spec_for(
    project: Project,
    settings: GeneratedOutro,
    surah_names: Mapping[int, str],
    *,
    rtl: bool | None = None,
) -> OutroSpec:
    """The outro *settings* make for *project*: the phrase, and the tracked link's QR code.

    With no link, ``qr_url`` and ``link_text`` are both None. The link's
    campaign names the lecture's surah and ayat (:func:`title_for`), and its
    source is the platform the settings name. Raises
    :class:`~qurantext.core.tracked_link.LinkError` (a ``ValueError``) for a
    link that is not one; the dialog refuses those first, so only a
    hand-edited project reaches it. *rtl* is the phrase's direction unless given.
    """
    phrase = " ".join(settings.phrase.split())
    link = settings.link.strip()
    qr_url = link_text = None
    if link:
        _, surah, first, last = title_for(project, surah_names)
        qr_url = tracked_link(
            link, platform=settings.platform, campaign=campaign_for(surah, first, last)
        )
        link_text = readable_link(link)
    return OutroSpec(
        phrase=phrase,
        link_text=link_text,
        qr_url=qr_url,
        style=settings.style,
        seconds=settings.seconds,
        rtl=_reads_right_to_left(phrase) if rtl is None else rtl,
    )


#: The look's fields a title clip's pixels depend on, besides its background: the
#: frame and card colours and the text and QR colours. A caption colour is not one.
_DRAWN_LOOK_FIELDS = (
    "frame_bg",
    "card",
    "card_border",
    "header_text",
    "body_text",
    "placeholder_text",
    "base_preset",
)


def _file_digest(path: Path) -> str:
    """The sha256 of the file at *path*.

    Read each time, not cached by size and time: a file rewritten within one
    tick of the file system's clock keeps both. A look's photo is a few
    megabytes, read twice a render.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _image_key(look: Look) -> str:
    """The background photo by its content: ``none``, ``unreadable`` or its sha256.

    Not its path: the same photo in a moved project folder is the same clip,
    and a photo that could not be read (the clip shows the preset's background
    instead) is not the photo.
    """
    background = look.background
    if background.kind != "image" or background.image is None:
        return "none"
    try:
        return _file_digest(Path(background.image))
    except (OSError, ValueError):  # missing, unreadable, a NUL in a hand-edited path
        return "unreadable"


def _look_key(look: Look) -> str:
    """Everything of *look* a title clip draws, as stable text."""
    background = look.background
    drawn = [(name, getattr(look, name)) for name in _DRAWN_LOOK_FIELDS]
    drawn.append(
        (
            "background",
            (
                background.kind,
                background.colour,
                background.colour2,
                background.dim,
                background.blur,
            ),
        )
    )
    drawn.append(("image", _image_key(look)))
    return repr(drawn)


def generated_part_path(
    project_path: Path,
    kind: str,
    spec: IntroSpec | OutroSpec,
    look: Look,
    *,
    width: int,
    height: int,
    fps: int,
) -> Path:
    """Where the clip of *spec* in *look* at this size and rate lives, made or not.

    Named by the first 12 hex digits of a sha256 of all it is made from; never
    Python's ``hash()``, which differs from one run of the app to the next.
    The spec's key covers the generator's version; the look counts by what a
    clip draws of it (a background photo by its content).
    """
    made_from = spec.cache_key() + _look_key(look) + f"{width}x{height}@{fps}"
    key12 = hashlib.sha256(made_from.encode("utf-8")).hexdigest()[:12]
    return episode_dir_for(project_path) / f"generated-{kind}-{key12}.mp4"


def remove_generated_parts(project_path: Path, kind: str, *, keep: Path | None = None) -> None:
    """Remove *kind*'s generated clips beside the project, other than *keep*.

    Made from something that has since changed, or for a part that is no
    longer generated. A clip that will not go is left for the next time.
    """
    folder = episode_dir_for(project_path)
    if not folder.is_dir():
        return
    for earlier in folder.glob(f"generated-{kind}-*.mp4"):
        if earlier != keep:
            try:
                earlier.unlink()
            except OSError:
                continue


def _is_empty(spec: IntroSpec | OutroSpec) -> bool:
    """Whether *spec* would draw an empty panel: no words and no QR code."""
    if isinstance(spec, IntroSpec):
        return not (spec.name.strip() or spec.title.strip())
    return not (spec.phrase.strip() or spec.qr_url or spec.link_text)


def ensure_generated_part(
    project: Project,
    kind: str,
    spec: IntroSpec | OutroSpec,
    look: Look,
    *,
    width: int,
    height: int,
    fps: int,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> Path:
    """The clip of *spec* for *project*'s episode: reused when it is there, else made.

    *kind* is ``intro`` or ``outro``. After a new clip is made, the part's
    earlier clips are removed: they were made from something that has since
    changed. Raises :class:`EpisodeError`: ``episode.error.qr_too_big`` when
    the link's QR code cannot be drawn large enough for phones at this size
    (the dialog says so first), ``episode.error.generate_empty`` when the
    part has no words and no link to show, else ``episode.error.generate``;
    each names the part as its i18n key (``part="episode.part.intro"``), and
    the cause of a failure is logged. A cancel raises ``JobCancelled`` and
    leaves no partial file.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown generated part {kind!r}; expected one of {KINDS}")
    part = f"episode.part.{kind}"
    if project.path is None:
        raise EpisodeError("episode.error.generate", part=part)
    if _is_empty(spec):
        raise EpisodeError("episode.error.generate_empty", part=part)
    output = generated_part_path(
        project.path, kind, spec, look, width=width, height=height, fps=fps
    )
    if output.is_file():
        return output
    try:
        fits = qr_fits(spec, width, height)
    except Exception as error:  # noqa: BLE001 — a text the font cannot lay out, say
        _log.warning("The %s could not be laid out", kind, exc_info=True)
        raise EpisodeError("episode.error.generate", part=part) from error
    if not fits:
        raise EpisodeError("episode.error.qr_too_big", size=f"{width}×{height}")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        render_title_clip(
            spec,
            look,
            output,
            width=width,
            height=height,
            fps=fps,
            progress=progress,
            cancel=cancel,
        )
    except JobCancelled:
        raise
    except Exception as error:  # noqa: BLE001 — FFmpeg, the font, the disk: all one sentence
        _log.warning("The %s could not be made", kind, exc_info=True)
        raise EpisodeError("episode.error.generate", part=part) from error
    remove_generated_parts(project.path, kind, keep=output)
    return output

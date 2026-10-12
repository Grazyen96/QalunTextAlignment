"""The outro's link: what the QR code opens, and what is written under it.

An organisation rule says every link put in front of viewers must be
measurable. So the QR code opens the person's link with UTM parameters naming
the platform the video is published on, the medium (a video), the lecture
(campaign) and the spot (``utm_content``): the outro's QR code, or the video's
description for the same link copied there, so scans and description clicks
are counted apart. A campaign the person set in the link themselves is theirs
and stays; every other parameter they had stays too, exactly as they wrote it.

A dead link measures nothing, so a link is checked strictly before any of this
(:func:`normalise_link`): a web address with a real host, nothing else. What
the QR code encodes is plain ASCII (an IDN host in punycode, an Arabic path
percent-encoded), which every scanner reads the same way.

The words under the code are the bare address, without the tracking, decoded
for people (:func:`readable_link`): typed visits then show as direct traffic,
apart from the QR code's and the description's visits.

An address can be honest and still look like another one: a Cyrillic «а» among
Latin letters, or a name spelled wholly in Cyrillic or Greek letters that look
Latin. :func:`lookalike_host` says so, for the dialog to warn; such a link is
not refused, since a real site may be named that way.
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from urllib.parse import quote, unquote, unquote_plus, urlsplit, urlunsplit

import idna

__all__ = [
    "CONTENTS",
    "LINK_ERRORS",
    "PLATFORMS",
    "LinkError",
    "campaign_for",
    "lookalike_host",
    "normalise_link",
    "readable_link",
    "tracked_link",
]

PLATFORMS = ("youtube", "instagram", "facebook", "tiktok", "telegram", "whatsapp")

#: Why a link was refused, as :attr:`LinkError.code`; the dialog words each one.
LINK_ERRORS = ("empty", "spaces", "scheme", "slashes", "userinfo", "host", "port")

_TRACKING = ("utm_source", "utm_medium", "utm_content")
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):(.*)$", re.DOTALL)
_HOST_PORT = re.compile(r"^\d+(?:[/?#]|$)")
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
# Characters kept as they are when the path, query or fragment is made ASCII:
# RFC 3986's reserved and unreserved characters, and "%" so escapes stay escapes.
_SAFE_PATH = "/%:@!$&'()*+,;=-._~"
_SAFE_QUERY = _SAFE_PATH + "?"


class LinkError(ValueError):
    """A link that cannot go in front of viewers; *code* is one of :data:`LINK_ERRORS`."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text!r} is not a web link Qalun can use")
        self.code = code


def _invisible_or_space(char: str) -> bool:
    return char.isspace() or unicodedata.category(char) in ("Cc", "Cf", "Zl", "Zp")


def _ascii_host(host: str, text: str) -> str:
    """The host as ASCII (punycode for an IDN), or :class:`LinkError` ``host``.

    IDNA 2008 with UTS #46 non-transitional mapping, as browsers do: «straße.de»
    is ``xn--strae-oqa.de``. Python's own ``idna`` codec is IDNA 2003, which maps
    ß to ss and ς to σ, and so would send the viewer to a different domain.
    """
    host = host.rstrip(".")
    if not host:
        raise LinkError("host", text)
    try:
        return f"[{ipaddress.IPv6Address(host)}]"
    except ValueError:
        pass
    try:
        return str(ipaddress.IPv4Address(host))
    except ValueError:
        pass
    try:
        ascii_host = idna.encode(host, uts46=True, transitional=False).decode("ascii").lower()
        labels = ascii_host.split(".")
        for label in labels:
            if label.startswith("xn--"):
                idna.decode(label)  # valid punycode, or IDNAError (a UnicodeError)
    except UnicodeError as error:
        raise LinkError("host", text) from error
    if not all(_LABEL.match(label) for label in labels):
        raise LinkError("host", text)
    if len(ascii_host) > 253 or all(label.isdigit() for label in labels):
        raise LinkError("host", text)  # too long, or a broken IPv4 address
    if len(labels) < 2 and ascii_host != "localhost":
        raise LinkError("host", text)
    return ascii_host


def normalise_link(text: str) -> str:
    """*text* as a checked web link, in the ASCII form the QR code encodes.

    Adds ``https://`` when there is no scheme (``example.org/dars``,
    ``localhost:8000``). Raises :class:`LinkError` (a ``ValueError``) for an
    empty link; spaces or invisible characters; a scheme other than http or
    https; a mistyped one (``https:/x``, ``https//x``, ``https:x``); a user
    name or password; a host that is not a real host name; or a bad port.
    """
    text = (text or "").strip()
    if not text:
        raise LinkError("empty", text)
    if any(_invisible_or_space(char) for char in text):
        raise LinkError("spaces", text)
    low = text.lower()
    for name in ("https", "http"):
        if low.startswith(name):
            rest = low[len(name) :]
            if not rest.startswith("://") and rest[:1] in (":", "/"):
                raise LinkError("slashes", text)
            break
    scheme = _SCHEME.match(text)
    if scheme is None or _HOST_PORT.match(scheme.group(2)):
        text = "https://" + text  # no scheme: a bare host, perhaps with a port
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https"):
        raise LinkError("scheme", text)
    if "@" in parts.netloc:
        raise LinkError("userinfo", text)
    try:
        port = parts.port
    except ValueError as error:
        raise LinkError("port", text) from error
    if port == 0:
        raise LinkError("port", text)
    netloc = _ascii_host(parts.hostname or "", text)
    if port is not None:
        netloc += f":{port}"
    return urlunsplit(
        (
            parts.scheme.lower(),
            netloc,
            quote(parts.path, safe=_SAFE_PATH),
            quote(parts.query, safe=_SAFE_QUERY),
            quote(parts.fragment, safe=_SAFE_QUERY),
        )
    )


def campaign_for(surah: int | None, from_ayah: int | None, to_ayah: int | None) -> str:
    if surah is None:
        return "qalun-lecture"
    if from_ayah is None or to_ayah is None:
        return f"qalun-{surah:03d}"
    return f"qalun-{surah:03d}-{from_ayah:03d}-{to_ayah:03d}"


#: Where the viewer met the link (``utm_content``): the outro's QR code, or the
#: video's description, where the person pastes the link Copy gives.
CONTENTS = ("outro-qr", "description")


def tracked_link(url: str, *, platform: str, campaign: str, content: str = "outro-qr") -> str:
    """*url* with the four UTM parameters; everything else in it kept byte for byte.

    The query is split on ``&`` and each piece kept as written (its encoding,
    a bare ``flag``, a ``;``); only its key is decoded, to find the tracking
    parameters. Source, medium and content are replaced; a campaign the person
    set stays, unless it is empty. *content* is where the link is shown (one of
    :data:`CONTENTS`): the QR code's and the description's links differ only
    there, so scans and description clicks are counted apart.
    """
    if platform not in PLATFORMS:
        raise ValueError(f"unknown platform {platform!r}")
    if content not in CONTENTS:
        raise ValueError(f"unknown content {content!r}; expected one of {CONTENTS}")
    parts = urlsplit(normalise_link(url))
    keep: list[str] = []
    has_campaign = False
    for piece in parts.query.split("&"):
        if not piece:
            continue
        key, _, value = piece.partition("=")
        key = unquote_plus(key)
        if key in _TRACKING:
            continue
        if key == "utm_campaign":
            if not unquote_plus(value).strip():
                continue  # an empty campaign measures nothing: the automatic one replaces it
            has_campaign = True
        keep.append(piece)
    if not has_campaign:
        keep.append("utm_campaign=" + quote(campaign, safe=""))
    keep += [f"utm_source={platform}", "utm_medium=video", f"utm_content={content}"]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(keep), parts.fragment))


def _for_people(text: str) -> str:
    """*text* with %-escapes decoded, except where that would hide or break something."""
    try:
        decoded = unquote(text, errors="strict")
    except UnicodeDecodeError:
        return text  # not UTF-8: the escapes are the only honest way to show it
    return "".join(quote(char, safe="") if _invisible_or_space(char) else char for char in decoded)


def readable_link(url: str) -> str:
    """The address to write under the QR code: host and path, decoded for people.

    No scheme, query, fragment, user name or trailing ``/``. An IDN host shows
    in its own script and a percent-encoded path as the words it encodes, so
    «example.org/دروس» rather than ``example.org/%D8%AF…``. Display only: the
    QR code keeps the encoded link.
    """
    parts = urlsplit(normalise_link(url))
    host = parts.hostname or ""
    if not host.startswith("[") and ":" not in host:
        try:
            host = idna.decode(host)
        except UnicodeError:
            pass
    else:
        host = f"[{host.strip('[]')}]"
    if parts.port is not None:
        host += f":{parts.port}"
    return (host + _for_people(parts.path)).rstrip("/")


#: Scripts counted as one when a host name mixes them: Japanese mixes kana and
#: kanji, Korean hangul and hanja, as their own domains do.
_SCRIPT_GROUPS = {"HIRAGANA": "CJK", "KATAKANA": "CJK", "HANGUL": "CJK"}
#: Cyrillic and Greek small letters that read as Latin ones in most fonts.
_LOOK_LATIN = frozenset("аеорсухіјѕһԁԛԝӏοανικρτυχ")


def _script(char: str) -> str | None:
    """The script of the letter *char* (``LATIN``, ``CYRILLIC``…); None for a digit or ``-``."""
    if not char.isalpha():
        return None
    name = unicodedata.name(char, "")
    word = name.split(" ", 1)[0]
    return _SCRIPT_GROUPS.get(word, word) or None


def lookalike_host(url: str) -> str | None:
    """Whether the address of *url* could pass for another one: ``mixed``, ``confusable`` or None.

    ``mixed``: one name of the host mixes alphabets («pаypal.com» with a
    Cyrillic «а»). ``confusable``: a name written wholly in Cyrillic or Greek
    letters that look Latin («рау.com»). Raises :class:`LinkError` as
    :func:`normalise_link` does.
    """
    host = urlsplit(normalise_link(url)).hostname or ""
    if host.startswith("[") or ":" in host:
        return None
    try:
        host = idna.decode(host)
    except UnicodeError:
        return None
    confusable = False
    for label in host.split("."):
        scripts = {script for char in label if (script := _script(char))}
        if len(scripts) > 1:
            return "mixed"
        if scripts & {"CYRILLIC", "GREEK"} and all(
            char in _LOOK_LATIN for char in label if char.isalpha()
        ):
            confusable = True
    return "confusable" if confusable else None

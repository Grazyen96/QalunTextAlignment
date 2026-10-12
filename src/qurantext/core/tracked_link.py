"""The outro's link: what the QR code opens, and what is written under it.

An organisation rule says every link put in front of viewers must be
measurable. So the QR code opens the person's link with UTM parameters naming
the platform the video is published on, the medium (a video), the lecture
(campaign) and the spot (the outro's QR code). A campaign the person set in the
link themselves is theirs and stays; every other parameter they had stays too.

The words under the code are the bare address, without the tracking: typed
visits then show as direct traffic, which tells the person how many viewers
typed it rather than scanned it.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

__all__ = ["PLATFORMS", "campaign_for", "normalise_link", "readable_link", "tracked_link"]

PLATFORMS = ("youtube", "instagram", "facebook", "tiktok", "telegram", "whatsapp")


def normalise_link(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty link")
    if "://" not in text and not text.lower().startswith(("javascript:", "data:", "mailto:")):
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError(f"not a web link: {text}")
    return text


def campaign_for(surah: int | None, from_ayah: int | None, to_ayah: int | None) -> str:
    if surah is None:
        return "qalun-lecture"
    if from_ayah is None or to_ayah is None:
        return f"qalun-{surah:03d}"
    return f"qalun-{surah:03d}-{from_ayah:03d}-{to_ayah:03d}"


def tracked_link(url: str, *, platform: str, campaign: str) -> str:
    if platform not in PLATFORMS:
        raise ValueError(f"unknown platform {platform!r}")
    parts = urlsplit(normalise_link(url))
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    keep = [(k, v) for k, v in query if k not in ("utm_source", "utm_medium", "utm_content")]
    if not any(k == "utm_campaign" for k, _ in keep):
        keep.append(("utm_campaign", campaign))
    keep += [("utm_source", platform), ("utm_medium", "video"), ("utm_content", "outro-qr")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(keep), parts.fragment))


def readable_link(url: str) -> str:
    parts = urlsplit(normalise_link(url))
    return (parts.netloc + parts.path).rstrip("/")

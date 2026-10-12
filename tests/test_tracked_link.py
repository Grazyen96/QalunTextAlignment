from urllib.parse import parse_qs, urlsplit

import pytest

from qurantext.core.tracked_link import (
    PLATFORMS,
    campaign_for,
    normalise_link,
    readable_link,
    tracked_link,
)


def _q(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def test_plain_link_gets_all_four_parameters():
    url = tracked_link("https://example.org/dars", platform="youtube", campaign="qalun-025-044-049")
    assert url.startswith("https://example.org/dars?")
    assert _q(url) == {
        "utm_source": "youtube",
        "utm_medium": "video",
        "utm_campaign": "qalun-025-044-049",
        "utm_content": "outro-qr",
    }


def test_existing_campaign_query_and_fragment_survive():
    url = tracked_link(
        "https://ex.org/d?ref=yt&utm_campaign=ramadan&utm_source=old#top",
        platform="telegram",
        campaign="qalun-025",
    )
    q = _q(url)
    assert q["ref"] == "yt" and q["utm_campaign"] == "ramadan"
    assert q["utm_source"] == "telegram" and q["utm_medium"] == "video"
    assert urlsplit(url).fragment == "top"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_every_platform_is_its_source(platform):
    assert (
        _q(tracked_link("https://a.b", platform=platform, campaign="c"))["utm_source"] == platform
    )


def test_unknown_platform_is_refused():
    with pytest.raises(ValueError):
        tracked_link("https://a.b", platform="myspace", campaign="c")


@pytest.mark.parametrize(
    "surah, a, b, expected",
    [
        (25, 44, 49, "qalun-025-044-049"),
        (25, 7, 7, "qalun-025-007-007"),
        (25, None, None, "qalun-025"),
        (None, None, None, "qalun-lecture"),
    ],
)
def test_campaign_names(surah, a, b, expected):
    assert campaign_for(surah, a, b) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("example.org/dars", "https://example.org/dars"),
        ("http://example.org", "http://example.org"),
        ("  https://example.org/x  ", "https://example.org/x"),
    ],
)
def test_normalise_link(text, expected):
    assert normalise_link(text) == expected


@pytest.mark.parametrize("bad", ["ftp://x.org", "javascript:alert(1)", "https://", ""])
def test_normalise_refuses(bad):
    with pytest.raises(ValueError):
        normalise_link(bad)


@pytest.mark.parametrize(
    "url, text",
    [
        ("https://example.org/dars/?a=1#x", "example.org/dars"),
        ("https://www.example.org", "www.example.org"),
        ("http://ex.org/a/b", "ex.org/a/b"),
    ],
)
def test_readable_link(url, text):
    assert readable_link(url) == text

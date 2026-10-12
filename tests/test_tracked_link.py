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


# --- The fix wave (phase-1 review I1, I2, m3, m4, m5) --------------------------------

from qurantext.core.tracked_link import LINK_ERRORS, LinkError  # noqa: E402


@pytest.mark.parametrize(
    "bad, code",
    [
        ("", "empty"),
        ("   ", "empty"),
        ("https:/example.org", "slashes"),
        ("https//example.org", "slashes"),
        ("http//example.org", "slashes"),
        ("https:example.org", "slashes"),
        ("HTTPS:/Example.org", "slashes"),
        ("tel:+491234", "scheme"),
        ("file:/etc/passwd", "scheme"),
        ("vbscript:msgbox(1)", "scheme"),
        ("javascript:alert(1)", "scheme"),
        ("mailto:a@b.org", "scheme"),
        ("ftp://x.org", "scheme"),
        ("https://exa mple.org/x", "spaces"),
        ("https://ex.org/a b", "spaces"),
        ("java\nscript:alert(1)", "spaces"),
        ("https://ex.org/\u200fx", "spaces"),
        ("https://ex.org:abc/x", "port"),
        ("https://ex.org:99999/x", "port"),
        ("https://ex.org:0/x", "port"),
        ("https://:80", "host"),
        ("https://", "host"),
        ("https://ex_ample.org", "host"),
        ("https://-ex.org", "host"),
        ("https://exampleorg/x", "host"),
        ("https://999.1.1.1/x", "host"),
        ("https://xn--zz.org", "host"),
        ("https://user:pass@ex.org/d", "userinfo"),
        ("https://youtube.com@evil.org/x", "userinfo"),
        ("user@ex.org", "userinfo"),
    ],
)
def test_malformed_links_are_refused_with_a_reason(bad, code):
    with pytest.raises(LinkError) as caught:
        normalise_link(bad)
    assert caught.value.code == code and code in LINK_ERRORS
    assert isinstance(caught.value, ValueError)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Example.ORG/Dars", "https://example.org/Dars"),
        ("localhost:8000/x", "https://localhost:8000/x"),
        ("example.org:8080", "https://example.org:8080"),
        ("https://ex.org:/x", "https://ex.org/x"),
        ("http://192.168.1.10:8000/d", "http://192.168.1.10:8000/d"),
        ("https://[::1]:8000/d", "https://[::1]:8000/d"),
        ("httpbin.org/get", "https://httpbin.org/get"),
        ("https://example.org./x", "https://example.org/x"),
        ("https://example.org/#/route?x=1", "https://example.org/#/route?x=1"),
    ],
)
def test_good_links_are_kept(text, expected):
    assert normalise_link(text) == expected


def test_the_qr_content_is_ascii():
    url = tracked_link("مثال.com/دروس/تفسير#قسم", platform="youtube", campaign="c")
    assert url.isascii()
    parts = urlsplit(url)
    assert parts.hostname == "xn--mgbh0fb.com"
    assert parts.path == "/%D8%AF%D8%B1%D9%88%D8%B3/%D8%AA%D9%81%D8%B3%D9%8A%D8%B1"


def test_existing_parameters_are_kept_exactly_as_written():
    url = tracked_link(
        "https://ex.org/d?q=%E9&s=a%20b&flag&a=1;b=2&utm_source=x&utm_source=y",
        platform="whatsapp",
        campaign="c",
    )
    query = urlsplit(url).query
    assert query.startswith("q=%E9&s=a%20b&flag&a=1;b=2&")
    assert query.count("utm_source") == 1 and "utm_source=whatsapp" in query


@pytest.mark.parametrize("empty", ["utm_campaign=", "utm_campaign=%20", "utm_campaign"])
def test_an_empty_campaign_gets_the_automatic_one(empty):
    url = tracked_link(f"https://ex.org/d?{empty}", platform="youtube", campaign="qalun-025")
    assert _q(url)["utm_campaign"] == "qalun-025"
    assert urlsplit(url).query.count("utm_campaign") == 1


def test_readable_link_decodes_for_people():
    copied = "https://example.org/%D8%AF%D8%B1%D9%88%D8%B3/%D8%AA%D9%81%D8%B3%D9%8A%D8%B1/"
    assert readable_link(copied) == "example.org/دروس/تفسير"
    assert readable_link("https://xn--mgbh0fb.com/dars") == "مثال.com/dars"
    assert readable_link("https://ex.org:8080/a") == "ex.org:8080/a"
    # Not UTF-8 stays escaped; an encoded newline is not drawn as one.
    assert readable_link("https://ex.org/%E9t%C3%A9") == "ex.org/%E9t%C3%A9"
    assert readable_link("https://ex.org/a%0Ab") == "ex.org/a%0Ab"


def test_readable_link_never_shows_credentials():
    with pytest.raises(LinkError):
        readable_link("https://user:pass@ex.org/d")


@pytest.mark.parametrize(
    "host, ascii_host",
    [
        ("straße.de", "xn--strae-oqa.de"),
        ("βόλος.gr", "xn--nxasmm1c.gr"),
        ("مثال.com", "xn--mgbh0fb.com"),
    ],
)
def test_international_hosts_are_encoded_as_browsers_do(host, ascii_host):
    """IDNA 2008 with UTS #46 non-transitional mapping, as browsers do. Python's own
    codec (IDNA 2003) maps ß to ss and final ς to σ: a different domain."""
    url = tracked_link(f"https://{host}/x", platform="youtube", campaign="c")
    assert urlsplit(url).hostname == ascii_host
    assert readable_link(url).split("/")[0] == host.lower()

"""The app's own links carry UTM parameters, so every click can be counted."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from qurantext.config.links import GITHUB_URL, README_URL, app_link


@pytest.mark.parametrize(
    ("url", "campaign", "fragment"),
    [(GITHUB_URL, "about", ""), (README_URL, "help", "readme")],
)
def test_each_link_parses_to_the_app_s_tracking_query(url, campaign, fragment) -> None:
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc) == ("https", "github.com")
    assert parts.path == "/Grazyen96/QalunTextAlignment"
    assert parse_qs(parts.query, strict_parsing=True) == {
        "utm_source": ["qalun-app"],
        "utm_medium": ["app"],
        "utm_campaign": [campaign],
    }
    assert parts.fragment == fragment  # the query comes before the fragment


def test_a_query_already_there_is_kept_ahead_of_the_tracking() -> None:
    url = app_link("https://example.org/a?lang=ar#top", "help")
    parts = urlsplit(url)
    assert parts.query.startswith("lang=ar&utm_source=qalun-app")
    assert parts.fragment == "top"


def test_the_windows_use_the_tracked_links() -> None:
    pytest.importorskip("PySide6")
    from qurantext.gui import main_window
    from qurantext.gui.home import settings_dialog

    assert main_window.README_URL is README_URL
    assert settings_dialog.GITHUB_URL is GITHUB_URL

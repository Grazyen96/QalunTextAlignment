"""The web addresses the app opens, each tracked so a click can be counted.

Every link the app hands out must be measurable, so each carries UTM
parameters naming where it was clicked: ``utm_source=qalun-app``,
``utm_medium=app`` and a campaign for the place in the app (``help`` for the
header's Help, ``about`` for Settings → About). They live here, in one place,
so a redirect under the owner's own domain can replace github.com later
without touching the windows.

Built with :mod:`urllib.parse`, not ``core.tracked_link.tracked_link``: that
helper is for a video's outro, and fixes the medium to ``video`` and the
source and content to a platform and a spot on the video.
"""

from __future__ import annotations

from urllib.parse import urlencode, urlsplit, urlunsplit

__all__ = ["APP_SOURCE", "GITHUB_URL", "GUIDE_URL", "app_link"]

#: Who sent the click: this desktop app.
APP_SOURCE = "qalun-app"
#: The project's home on GitHub, untracked.
_REPOSITORY = "https://github.com/Grazyen96/QalunTextAlignment"


def app_link(url: str, campaign: str) -> str:
    """*url* with the app's UTM parameters, the query before any fragment.

    ``app_link("https://x.org/a#readme", "help")`` is
    ``https://x.org/a?utm_source=qalun-app&utm_medium=app&utm_campaign=help#readme``.
    A query already on *url* is kept ahead of them.
    """
    parts = urlsplit(url)
    tracking = urlencode({"utm_source": APP_SOURCE, "utm_medium": "app", "utm_campaign": campaign})
    query = f"{parts.query}&{tracking}" if parts.query else tracking
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


#: Settings → About's link to the project.
GITHUB_URL = app_link(_REPOSITORY, "about")
#: Where the header's Help goes: the user guide, which says how to use the app in plain words.
GUIDE_URL = app_link(f"{_REPOSITORY}/blob/master/USER_GUIDE.md", "help")

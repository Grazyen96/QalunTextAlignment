"""The banner under the toolbar: notices, coverage gaps and a finished render, never moving the body."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from qurantext.core.coverage import UncoveredSpeech  # noqa: E402
from qurantext.gui import theme  # noqa: E402
from qurantext.gui.i18n import t, tn  # noqa: E402
from qurantext.gui.jobs import JobOutcome  # noqa: E402
from qurantext.gui.review.banner import Banner  # noqa: E402


@pytest.fixture()
def banner(qt_app):
    theme.apply_theme(qt_app, "light")
    made = Banner()
    made.show()
    yield made
    made.deleteLater()


def _gap(start: float, end: float) -> UncoveredSpeech:
    return UncoveredSpeech(start=start, end=end, mean_db=-20.0)


def test_empty_it_keeps_a_four_pixel_rule(banner) -> None:
    assert banner.kind() == ""
    assert banner.lines() == []
    assert banner.sizeHint().height() == Banner.EMPTY_HEIGHT
    assert banner.isVisibleTo(banner.parentWidget() or banner)


def test_notices_are_lines_once_each_and_make_it_info(banner) -> None:
    banner.add_notice("FFmpeg failed")
    banner.add_notice("FFmpeg failed")
    assert banner.lines() == ["FFmpeg failed"]
    assert banner.text().count("FFmpeg failed") == 1
    assert banner.kind() == "info"


def test_gaps_collapse_behind_a_count_and_expand(banner) -> None:
    banner.set_gaps([_gap(4.0, 6.0), _gap(10.0, 11.0)])
    assert banner.kind() == "attention"
    assert tn("review.gaps_toggle", 2) in banner.text()
    assert not banner.gaps_expanded
    assert "Jump" not in banner.text()
    banner.toggle_gaps()
    assert banner.gaps_expanded and "2.0 s at 00:04.0–00:06.0" in banner.text()
    seen = []
    banner.jump_requested.connect(seen.append)
    banner.jump_to("4.000")
    assert seen == [4.0]


def test_five_gaps_are_listed_then_the_rest_counted(banner) -> None:
    banner.set_gaps([_gap(i, i + 1) for i in range(7)])
    banner.toggle_gaps()
    assert banner.text().count("Jump") == 5
    assert tn("review.more_gaps", 2) in banner.text()


def test_checking_shows_until_the_first_result(banner) -> None:
    banner.set_checking(True)
    assert t("review.checking") in banner.text()
    banner.set_gaps([])
    assert t("review.checking") not in banner.text() and t("review.covered") in banner.text()


def test_a_finished_render_adds_a_success_line_with_two_actions(banner, tmp_path) -> None:
    video = tmp_path / "a.mp4"
    outcome = JobOutcome(matches=tmp_path / "m.json", video=video, cards=1)
    played, revealed = [], []
    banner.play_requested.connect(played.append)
    banner.reveal_requested.connect(revealed.append)
    banner.set_render_done(outcome, 96.0)
    assert banner.kind() == "success"
    assert t("render.done_banner_timed", name="a.mp4", duration="01:36") in banner.text()
    banner.play_button.click()
    banner.reveal_button.click()
    assert played == [video] and revealed == [video]
    banner.set_render_done(outcome, None)
    assert t("render.done_banner", name="a.mp4") in banner.text()
    banner.clear_render()
    assert "a.mp4" not in banner.text() and not banner.play_button.isVisibleTo(banner)


def test_dismiss_clears_news_but_keeps_state(banner, tmp_path) -> None:
    """Review Focus 2: a render finishing over coverage gaps; dismiss keeps the gaps."""
    banner.set_gaps([_gap(4.0, 6.0)])
    banner.set_surah_notice("no card")
    banner.add_notice("plain news")
    outcome = JobOutcome(matches=tmp_path / "m.json", video=tmp_path / "a.mp4", cards=1)
    banner.set_render_done(outcome, 10.0)
    assert banner.kind() == "success"
    banner.dismiss_button.click()
    assert "a.mp4" not in banner.text() and "plain news" not in banner.text()
    assert "no card" in banner.text() and tn("review.gaps_toggle", 1) in banner.text()
    assert banner.kind() == "attention"


def test_look_surah_and_episode_notices_come_and_go(banner) -> None:
    banner.set_look_notices(["image gone"])
    banner.set_surah_notice("no card")
    banner.set_episode_notice("no intro")
    assert banner.lines() == ["image gone", "no card", "no intro"]
    banner.set_look_notices([])
    banner.set_surah_notice(None)
    banner.set_episode_notice(None)
    assert banner.lines() == []

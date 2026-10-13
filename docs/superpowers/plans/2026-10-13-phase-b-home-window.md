# Phase B: Home Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure Qalun's home window: a header bar with theme toggle, Settings and Help; a five-tab Settings dialog that takes every machine-level setting out of the form; a 560 px form column with the progress bar in Start's slot; job cards with thumbnails, status chips and dates; a folder watcher; and an empty state that explains the two kinds of job.

**Architecture:** Three new modules (`gui/home/header.py`, `gui/home/settings_dialog.py`, `jobs/thumbnails.py`) and reshaped versions of `gui/home/new_job.py`, `gui/home/job_list.py` and `gui/main_window.py`. The Settings dialog writes `Prefs` directly as controls change; the window tells the form and the list to reload afterwards. Thumbnails are rendered by the existing frame renderer inside the catalog's worker-thread read and cached as PNGs under the user cache directory. `JobSpec`, `Prefs` keys, project files and the CLI do not change.

**Tech Stack:** Python 3.12, PySide6 6.11 (QtCore `QFileSystemWatcher`, `QLocale`, `QDesktopServices`; QtWidgets `QTabWidget`), Pillow 12, numpy, pytest, ruff 0.15.13. Phase A's `gui/theme.py`, `gui/icons.py` (`set_icon`, `icon`), `gui/widgets.py` (`make_primary`, `SectionHeader`, `Card`, `StatusChip`).

**Spec:** `docs/superpowers/specs/2026-10-13-phase-b-home-window-design.md`

## Global Constraints

- Run every command with `venv/bin/python` from the worktree root; GUI tests with `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest <files> -q`. Lint before each commit: `venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools`.
- Never wait on the event loop with `QTest.qWait`; use `tests.qt_helpers.spin` / `wait_for` / `wait_until_listed`. Worker `QObject`s are deleted on the UI thread.
- Every `t("…")` key exists in both `STRINGS["en"]` and `STRINGS["ar"]` (`tests/test_i18n.py` enforces it). An Arabic line that starts with a value needs a leading `‏`.
- Every widget attribute a test reaches keeps its name and class except where this plan names the move: `language_combo`, `theme_combo`, `log_link`, `quran_label`, `quran_choose_button`, `quran_reset_button`, `output_label`, `output_choose_button`, `output_reset_button`, `engine_buttons`, `no_token_label` move to `SettingsDialog` under the same names. `new_job.progress_bar` stays a `QProgressBar`; `new_job.start_button` stays a plain `QPushButton`; `job_list.empty_label` stays a `QLabel`.
- `JobSpec`, project files, `Prefs` keys and the CLI are unchanged. `set_language` keeps its refusal while a review window or a job is busy.
- The stylesheet rules from phase A are not extended to `QComboBox`, `QSpinBox`, `QSlider`, `QScrollBar`, `QCheckBox`, `QRadioButton`, `QTabWidget`, `QTabBar`.
- Lucide names at tag 1.56.0; the four new ones are `upload`, `file-music`, `circle-alert`, `triangle-alert`. Help URL: `https://github.com/Grazyen96/QalunTextAlignment#readme`.
- The window fits 1024×680 in English and Arabic with More options open and a job running (`tests/test_gui.py` fit test, extended to Arabic in Task 7).
- Commit messages: one sentence for a reader of `git log` (see `git log --oneline -12`), ending with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **A job folder on an unplugged drive** in `Prefs.job_dirs`: the watcher must skip it, the read must still list the other folders, Settings must still show it with Remove. Test in Task 6 (watcher skips a missing dir) and Task 4 (list shows a missing dir).
2. **A project whose look names a missing image**: the thumbnail must still be made (the renderer's base layer falls back) or the tile shown; never a damaged row. Test in Task 1.
3. **Choosing Arabic in Settings while a review window is open**: refused, combo snaps back, reason shown in the dialog, window unchanged. Test in Task 7.
4. **Changing the Quran text in Settings while the form has a surah selected**: the form refills its surahs and keeps the remembered surah if it exists in the new store. Test in Task 5.
5. **Twenty files landing in a job folder within a second** (a render writing several outputs): one refresh, not twenty. Test in Task 6.

---

### Task 1: Thumbnails, rendered and cached on the worker

**Files:**
- Create: `src/qurantext/jobs/thumbnails.py`
- Modify: `src/qurantext/jobs/catalog.py:41-56` (`JobEntry`), `:114-165` (`_entry_for`), `:166-205` (`list_jobs`)
- Create: `tests/test_thumbnails.py`
- Modify: `tests/test_catalog.py` (one test)

**Interfaces:**
- Consumes: `qurantext.core.frame_renderer.render_frame_pillow`, `qurantext.core.looks.look_from_style`, `qurantext.jobs.project.job_settings`, `qurantext.config.settings.VIDEO_PRESETS`, `qurantext.config.paths.DEFAULT_FONT_PATH`.
- Produces: `thumbnail_for(project: Project, cache_dir: Path | None) -> Path | None`; `cache_key(project: Project) -> str`; `LONG_SIDE = 96`; `JobEntry.thumbnail: Path | None = None`, `JobEntry.background: tuple[int, int, int] | None = None`; `list_jobs(..., thumbnail_cache: Path | None = None)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_thumbnails.py
"""A job's thumbnail: the first card at the job's look, cached by path, time and style."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PIL import Image

from qurantext.jobs import thumbnails
from qurantext.jobs.project import Project, save_project

_CARD = {
    "surah_num": 25, "surah_name": "الفرقان", "from_ayah": 7, "to_ayah": 7,
    "start_time": 1.0, "end_time": 4.0,
    "word_timings": [{"word": "وَقَالُوا", "start": 1.0, "end": 2.0}],
}  # fmt: skip


def _project(tmp_path: Path, *, cards=None, style=None, preset="social") -> Project:
    project = Project(audio=str(tmp_path / "a.mp3"), mode="recitation", cards=cards if cards is not None else [dict(_CARD)], captions=[])
    project.style = style or {}
    project.export = {"preset": preset, "subtitles": "burn"}
    path = tmp_path / "a_recitation.qalun.json"
    save_project(project, path)
    return Project.load(path) if hasattr(Project, "load") else __import__("qurantext.jobs.project", fromlist=["load_project"]).load_project(path)


def test_a_portrait_job_gets_a_portrait_png_96_tall(tmp_path) -> None:
    png = thumbnails.thumbnail_for(_project(tmp_path), tmp_path / "cache")
    assert png is not None and png.is_file()
    with Image.open(png) as image:
        assert image.size == (54, 96)


def test_a_landscape_job_gets_a_landscape_png_96_wide(tmp_path) -> None:
    png = thumbnails.thumbnail_for(_project(tmp_path, preset="high"), tmp_path / "cache")
    with Image.open(png) as image:
        assert image.size == (96, 54)


def test_the_key_follows_the_file_time_and_the_style_only(tmp_path, monkeypatch) -> None:
    project = _project(tmp_path)
    first = thumbnails.cache_key(project)
    assert thumbnails.cache_key(project) == first  # time passing changes nothing
    project.style = {"preset": "emerald"}
    assert thumbnails.cache_key(project) != first
    project.style = {}
    later = time.time() + 100
    import os
    os.utime(project.path, (later, later))
    assert thumbnails.cache_key(project) != first


def test_a_hit_does_not_render_again(tmp_path, monkeypatch) -> None:
    project = _project(tmp_path)
    calls = []
    real = thumbnails.render_frame_pillow

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(thumbnails, "render_frame_pillow", counting)
    thumbnails.thumbnail_for(project, tmp_path / "cache")
    thumbnails.thumbnail_for(project, tmp_path / "cache")
    assert len(calls) == 1


def test_no_cards_means_no_thumbnail(tmp_path) -> None:
    assert thumbnails.thumbnail_for(_project(tmp_path, cards=[]), tmp_path / "cache") is None


def test_a_renderer_failure_means_no_thumbnail_and_no_exception(tmp_path, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("no font")

    monkeypatch.setattr(thumbnails, "render_frame_pillow", boom)
    assert thumbnails.thumbnail_for(_project(tmp_path), tmp_path / "cache") is None


def test_a_missing_look_image_still_yields_a_thumbnail(tmp_path) -> None:
    """Review Focus 2: the base layer falls back when the image is gone."""
    style = {"preset": "night_gold", "background": {"kind": "image", "image": "gone.jpg"}}
    png = thumbnails.thumbnail_for(_project(tmp_path, style=style), tmp_path / "cache")
    assert png is not None


def test_no_cache_dir_renders_in_memory_to_a_temp_file(tmp_path) -> None:
    png = thumbnails.thumbnail_for(_project(tmp_path), None)
    assert png is None  # nothing to keep it in: the row draws the tile


def test_background_is_the_looks_frame_colour(tmp_path) -> None:
    project = _project(tmp_path, style={"preset": "sand"})
    from qurantext.core.looks import PRESETS

    assert thumbnails.background_for(project) == PRESETS["sand"].frame_bg[:3]
```

Append to `tests/test_catalog.py`:

```python
def test_entries_carry_a_thumbnail_when_a_cache_is_given(tmp_path) -> None:
    from qurantext.jobs.catalog import list_jobs
    from tests.test_thumbnails import _project

    project = _project(tmp_path)
    entries = list_jobs([tmp_path], thumbnail_cache=tmp_path / "cache")
    assert len(entries) == 1
    assert entries[0].thumbnail is not None and entries[0].thumbnail.is_file()
    assert entries[0].background is not None
    plain = list_jobs([tmp_path])
    assert plain[0].thumbnail is None and plain[0].background is not None
```

If `Project` has no `load`, the helper's last line already falls back to `load_project`; keep whichever the module offers (check `tests/test_review_window.py::_project` for the constructor fields and `save_project`'s signature in `src/qurantext/jobs/project.py`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_thumbnails.py tests/test_catalog.py -q`
Expected: FAIL with `ImportError: cannot import name 'thumbnails'`

- [ ] **Step 3: Write `jobs/thumbnails.py`**

```python
# src/qurantext/jobs/thumbnails.py
"""A small picture of each job for the home list: its first card at its own look.

Made where the list is read, on the worker thread, with the same renderer the
preview and the export use, so the picture matches the video before any
render exists. Cached as a PNG under the user's cache directory, keyed by the
project's path, its modification time and its style: a save or a look change
redraws it, nothing else does. No pruning: a few KB each, in a folder the
person may delete at any time.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import numpy as np
from PIL import Image

from qurantext.config.paths import DEFAULT_FONT_PATH
from qurantext.config.settings import VIDEO_PRESETS
from qurantext.core.frame_renderer import render_frame_pillow
from qurantext.core.looks import look_from_style
from qurantext.jobs.project import Project, job_settings

__all__ = ["LONG_SIDE", "background_for", "cache_key", "thumbnail_for"]

_log = logging.getLogger(__name__)

#: The thumbnail's long side, in pixels.
LONG_SIDE = 96
#: Rendered this many times larger, then shrunk: the renderer's text is laid
#: out for a frame, and a 54 px frame would set it in 2 px letters.
_OVERSAMPLE = 4


def cache_key(project: Project) -> str:
    """A name that changes when the file or its look does, and never otherwise."""
    path = project.path
    mtime = path.stat().st_mtime_ns if path is not None and path.exists() else 0
    raw = f"{path}|{mtime}|{json.dumps(project.style or {}, sort_keys=True)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()  # noqa: S324 - a cache name, not security


def _look(project: Project):
    base_dir = project.path.parent if project.path is not None else None
    return look_from_style(project.style, base_dir=base_dir)


def background_for(project: Project) -> tuple[int, int, int]:
    """The look's frame colour, for the tile drawn when there is no picture."""
    r, g, b, _a = _look(project).frame_bg
    return (r, g, b)


def _size(project: Project) -> tuple[int, int]:
    width, height = VIDEO_PRESETS[job_settings(project).preset][:2]
    if height >= width:
        return (round(LONG_SIDE * width / height), LONG_SIDE)
    return (LONG_SIDE, round(LONG_SIDE * height / width))


def thumbnail_for(project: Project, cache_dir: Path | None) -> Path | None:
    """The PNG for *project*, made if it is not cached; None when it cannot be.

    None for a project with no cards, no *cache_dir*, a cache that cannot be
    written, or a renderer that raises: the row then draws a plain tile.
    """
    if cache_dir is None or not project.cards:
        return None
    try:
        folder = Path(cache_dir) / "thumbs"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{cache_key(project)}.png"
        if target.is_file():
            return target
        width, height = _size(project)
        card = min(project.cards, key=lambda c: float(c.get("start_time") or 0.0))
        at = float(card.get("start_time") or 0.0)
        frame = render_frame_pillow(
            at,
            card,
            width * _OVERSAMPLE,
            height * _OVERSAMPLE,
            DEFAULT_FONT_PATH,
            reserve_caption_band=False,
            look=_look(project),
        )
        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        image = Image.fromarray(rgb).resize((width, height), Image.Resampling.LANCZOS)
        image.save(target, "PNG")
        return target
    except Exception as error:  # noqa: BLE001 - a picture is never worth a damaged row
        _log.debug("No thumbnail for %s: %s", project.path, error)
        return None
```

- [ ] **Step 4: Carry it on the entry**

In `src/qurantext/jobs/catalog.py`: add to `JobEntry` after `error`:

```python
    #: The cached picture of the first card, when one could be made.
    thumbnail: Path | None = None
    #: The look's frame colour, for the tile drawn without a picture.
    background: tuple[int, int, int] | None = None
```

Give `_entry_for` a keyword `thumbnail_cache: Path | None = None` and, in its final `return JobEntry(...)`, add:

```python
        thumbnail=thumbnail_for(project, thumbnail_cache),
        background=_background(project),
```

with, at module level:

```python
from qurantext.jobs.thumbnails import background_for, thumbnail_for


def _background(project: Project) -> tuple[int, int, int] | None:
    try:
        return background_for(project)
    except Exception:  # noqa: BLE001 - a look that cannot be read is not a damaged job
        return None
```

Give `list_jobs` the keyword `thumbnail_cache: Path | None = None` and pass it: `entry = _entry_for(path, thumbnail_cache=thumbnail_cache)`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_thumbnails.py tests/test_catalog.py -q`
Expected: PASS

- [ ] **Step 6: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/jobs/thumbnails.py src/qurantext/jobs/catalog.py tests/test_thumbnails.py tests/test_catalog.py
git commit -m "Give each job a small picture of its first card at its own look, made once and cached

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Four more icons, every new string, and the notices path

**Files:**
- Modify: `tools/fetch_icons.py` (`ICON_NAMES`), `src/qurantext/gui/icons.py` (`NAMES`), `src/qurantext/assets/icons/` (4 new SVGs via the tool)
- Modify: `src/qurantext/gui/i18n.py` (`en` block near line 199–207; `ar` block near line 667–673)
- Modify: `src/qurantext/config/paths.py` (append `notices_path`)
- Modify: `tests/test_packaging_spec.py` (count 31 → 35), `tests/test_paths.py` (append)

**Interfaces:**
- Produces: icons `upload`, `file-music`, `circle-alert`, `triangle-alert` in the bundle and `icons.NAMES`; `notices_path() -> Path`; the i18n keys listed below, used by Tasks 3–7.

- [ ] **Step 1: Write the failing tests**

Change `assert len(ICON_NAMES) == 31` in `tests/test_packaging_spec.py` to `== 35`. Append to `tests/test_paths.py`:

```python
def test_the_notices_file_is_found_in_a_checkout_and_in_a_bundle(monkeypatch, tmp_path) -> None:
    import sys

    from qurantext.config.paths import notices_path

    assert notices_path().name == "THIRD_PARTY_NOTICES.md"
    assert notices_path().is_file()  # the checkout's own copy
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert notices_path() == tmp_path / "THIRD_PARTY_NOTICES.md"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_packaging_spec.py tests/test_paths.py -q`
Expected: FAIL (`assert 31 == 35`; `ImportError: cannot import name 'notices_path'`)

- [ ] **Step 3: Icons**

Append `"upload", "file-music", "circle-alert", "triangle-alert"` to `ICON_NAMES` in `tools/fetch_icons.py` and to `NAMES` in `src/qurantext/gui/icons.py`. Run `venv/bin/python tools/fetch_icons.py` (downloads all 35; the 31 existing files are rewritten unchanged).

- [ ] **Step 4: The notices path**

Append to `src/qurantext/config/paths.py`:

```python
def notices_path() -> Path:
    """The third-party notices file: beside the bundle's data in a build, at the repo root in a checkout."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "THIRD_PARTY_NOTICES.md"
    return Path(__file__).resolve().parents[3] / "THIRD_PARTY_NOTICES.md"
```

(`sys` is already imported there; add it if not.)

- [ ] **Step 5: Strings**

In `STRINGS["en"]`, after `"home.open_log_failed": …,` add:

```python
        "home.header.theme_to_dark": "Switch to the dark theme",
        "home.header.theme_to_light": "Switch to the light theme",
        "home.header.settings": "Settings",
        "home.header.help": "Help",
        "home.help_failed": "Could not open the help page in your browser.",
        "home.mode.recitation.desc": "Times the ayat of a recitation, word by word.",
        "home.mode.lecture.desc": "Finds the ayat quoted in a lecture and shows them as cards.",
        "home.engine.note": "Transcribes online with WhisperX, which uploads the recording.",
        "home.engine.change": "Change in Settings",
        "home.empty.title": "No jobs yet",
        "home.empty.hint": "Drop a recording on the right to start one.",
        "home.detail": "{mode} · {scope}",
        "settings.title": "Settings",
        "settings.tab.general": "General",
        "settings.tab.transcription": "Transcription",
        "settings.tab.files": "Files",
        "settings.tab.videos": "Videos",
        "settings.tab.about": "About",
        "settings.job_dirs": "Also look for jobs in",
        "settings.add_dir": "Add folder…",
        "settings.add_dir.dialog_title": "Choose a folder with jobs",
        "settings.remove_dir": "Remove",
        "settings.look": "Default look for new videos",
        "settings.look.based_on": "Based on {preset}",
        "settings.look.reset": "Reset to Night gold",
        "settings.episode": "Default episode for new lectures",
        "settings.episode.intro": "Intro",
        "settings.episode.outro": "Outro",
        "settings.episode.none": "None",
        "settings.episode.generated": "Generated",
        "settings.episode.clear": "Clear",
        "settings.version": "Qalun {version}",
        "settings.notices": "Third-party notices",
        "settings.notices.missing": "The notices file is not in this build.",
        "settings.github": "Qalun on GitHub",
        "settings.close": "Close",
```

In `STRINGS["ar"]`, after `"home.open_log_failed": …,` add:

```python
        "home.header.theme_to_dark": "بدِّل إلى المظهر الداكن",
        "home.header.theme_to_light": "بدِّل إلى المظهر الفاتح",
        "home.header.settings": "الإعدادات",
        "home.header.help": "مساعدة",
        "home.help_failed": "تعذّر فتح صفحة المساعدة في المتصفح.",
        "home.mode.recitation.desc": "يوقّت آيات التلاوة كلمةً كلمة.",
        "home.mode.lecture.desc": "يجد الآيات المذكورة في المحاضرة ويعرضها في بطاقات.",
        "home.engine.note": "ينسخ الصوت عبر الإنترنت بواسطة WhisperX، وهذا يرفع التسجيل.",
        "home.engine.change": "غيِّر ذلك في الإعدادات",
        "home.empty.title": "لا مهام بعد",
        "home.empty.hint": "أفلت تسجيلًا على اليسار لتبدأ مهمة.",
        "home.detail": "{mode} · {scope}",
        "settings.title": "الإعدادات",
        "settings.tab.general": "عام",
        "settings.tab.transcription": "النسخ الصوتي",
        "settings.tab.files": "الملفات",
        "settings.tab.videos": "الفيديوهات",
        "settings.tab.about": "حول",
        "settings.job_dirs": "ابحث عن المهام أيضًا في",
        "settings.add_dir": "أضف مجلدًا…",
        "settings.add_dir.dialog_title": "اختر مجلدًا يحوي مهامًا",
        "settings.remove_dir": "أزل",
        "settings.look": "المظهر الافتراضي للفيديوهات الجديدة",
        "settings.look.based_on": "مبني على {preset}",
        "settings.look.reset": "أعد إلى ذهبي ليلي",
        "settings.episode": "الحلقة الافتراضية للمحاضرات الجديدة",
        "settings.episode.intro": "المقدمة",
        "settings.episode.outro": "الخاتمة",
        "settings.episode.none": "بلا",
        "settings.episode.generated": "مولَّدة",
        "settings.episode.clear": "امسح",
        "settings.version": "‏قالون {version}",
        "settings.notices": "إشعارات الطرف الثالث",
        "settings.notices.missing": "ملف الإشعارات ليس في هذه النسخة.",
        "settings.github": "قالون على GitHub",
        "settings.close": "أغلق",
```

(`home.empty.hint` says "on the left" in Arabic because the form mirrors to the left there.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_packaging_spec.py tests/test_paths.py tests/test_icons.py tests/test_i18n.py -q`
Expected: PASS (`test_i18n` only checks keys the code uses; the new keys are unused until Tasks 3–7, which is allowed)

- [ ] **Step 7: Lint and commit**

```bash
venv/bin/ruff check src tests tools && venv/bin/ruff format src tests tools
git add tools/fetch_icons.py src/qurantext/gui/icons.py src/qurantext/assets/icons src/qurantext/gui/i18n.py src/qurantext/config/paths.py tests/test_packaging_spec.py tests/test_paths.py
git commit -m "Add the four icons, every string and the notices path the home window's redesign needs

The Arabic strings await a native speaker's review, with the rest.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: The header bar

**Files:**
- Create: `src/qurantext/gui/home/header.py`
- Create: `tests/test_header.py`

**Interfaces:**
- Consumes: `theme.font("title")`, `theme.SP_*`, `icons.set_icon`, `bundled_asset("icon/qalun-256.png")` (from `gui.app.APP_ICON_PNG`).
- Produces: `HeaderBar(QWidget)` with `icon_label`, `title_label`, `theme_button`, `settings_button`, `help_button` (`QToolButton`s), signals `theme_toggle_requested`, `settings_requested`, `help_requested`, and `show_theme(tokens_name: str) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_header.py
"""The home window's header: icon, name, and the three buttons at its far end."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from PySide6.QtCore import Qt  # noqa: E402

from qurantext.gui import theme  # noqa: E402
from qurantext.gui.home.header import HeaderBar  # noqa: E402
from qurantext.gui.i18n import t  # noqa: E402


@pytest.fixture()
def header(qt_app):
    theme.apply_theme(qt_app, "light")
    bar = HeaderBar()
    yield bar
    bar.deleteLater()


def test_it_shows_the_icon_and_the_name_in_the_title_font(header) -> None:
    assert not header.icon_label.pixmap().isNull()
    assert header.title_label.text() == "Qalun"
    assert header.title_label.font().pointSizeF() == theme.font("title").pointSizeF()
    assert header.sizeHint().height() <= 48


def test_the_three_buttons_carry_icons_tooltips_and_signals(header) -> None:
    seen = []
    header.theme_toggle_requested.connect(lambda: seen.append("theme"))
    header.settings_requested.connect(lambda: seen.append("settings"))
    header.help_requested.connect(lambda: seen.append("help"))
    for button, name, key in (
        (header.theme_button, "moon", "home.header.theme_to_dark"),
        (header.settings_button, "settings", "home.header.settings"),
        (header.help_button, "circle-question-mark", "home.header.help"),
    ):
        assert button.property("qalun.icon")[0] == name
        assert button.toolTip() == t(key)
        assert button.autoRaise()
        button.click()
    assert seen == ["theme", "settings", "help"]


def test_show_theme_flips_the_toggles_icon_and_tooltip(header) -> None:
    header.show_theme("dark")
    assert header.theme_button.property("qalun.icon")[0] == "sun"
    assert header.theme_button.toolTip() == t("home.header.theme_to_light")
    header.show_theme("light")
    assert header.theme_button.property("qalun.icon")[0] == "moon"


def test_the_buttons_sit_at_the_trailing_edge(qt_app, header) -> None:
    header.resize(800, 48)
    header.show()
    from tests.qt_helpers import spin

    spin(50)
    assert header.help_button.x() > header.title_label.x()
    qt_app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    try:
        mirrored = HeaderBar()
        mirrored.resize(800, 48)
        mirrored.show()
        spin(50)
        assert mirrored.help_button.x() < mirrored.title_label.x()
        mirrored.deleteLater()
    finally:
        qt_app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_header.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'qurantext.gui.home.header'`

- [ ] **Step 3: Write `gui/home/header.py`**

```python
# src/qurantext/gui/home/header.py
"""The strip across the top of the home window: who this is, and the three things that are not a job."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from qurantext.config.paths import bundled_asset
from qurantext.gui import theme
from qurantext.gui.i18n import t
from qurantext.gui.icons import set_icon

__all__ = ["HeaderBar"]

_ICON_PX = 24
_HEIGHT = 48


class HeaderBar(QWidget):
    """App icon and name at the leading edge; theme, Settings and Help at the trailing one."""

    theme_toggle_requested = Signal()
    settings_requested = Signal()
    help_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_HEIGHT)
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SP_12, 0, theme.SP_12, 0)
        row.setSpacing(theme.SP_8)

        self.icon_label = QLabel()
        pixmap = QPixmap(str(bundled_asset("icon/qalun-256.png")))
        self.icon_label.setPixmap(
            pixmap.scaled(_ICON_PX, _ICON_PX, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )
        self.icon_label.setFixedSize(QSize(_ICON_PX, _ICON_PX))
        row.addWidget(self.icon_label)

        self.title_label = QLabel("Qalun")  # the product's name, never translated
        self.title_label.setFont(theme.font("title"))
        row.addWidget(self.title_label)
        row.addStretch(1)

        self.theme_button = self._tool("moon", t("home.header.theme_to_dark"))
        self.settings_button = self._tool("settings", t("home.header.settings"))
        self.help_button = self._tool("circle-question-mark", t("home.header.help"))
        for button in (self.theme_button, self.settings_button, self.help_button):
            row.addWidget(button)
        self.theme_button.clicked.connect(self.theme_toggle_requested)
        self.settings_button.clicked.connect(self.settings_requested)
        self.help_button.clicked.connect(self.help_requested)

    @staticmethod
    def _tool(icon_name: str, tip: str) -> QToolButton:
        button = QToolButton()
        button.setAutoRaise(True)
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        set_icon(button, icon_name, size=20)
        return button

    def show_theme(self, tokens_name: str) -> None:
        """Offer the opposite of the theme in force: a sun on dark, a moon on light."""
        dark = tokens_name == "dark"
        set_icon(self.theme_button, "sun" if dark else "moon", size=20)
        tip = t("home.header.theme_to_light" if dark else "home.header.theme_to_dark")
        self.theme_button.setToolTip(tip)
        self.theme_button.setAccessibleName(tip)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_header.py -q`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/home/header.py tests/test_header.py
git commit -m "Add the home window's header bar: the app's icon and name, and a theme toggle, Settings and Help

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: The Settings dialog

**Files:**
- Create: `src/qurantext/gui/home/settings_dialog.py`
- Create: `tests/test_settings_dialog.py`
- Modify: `tests/test_home_panels.py` (move: `test_a_quran_override_that_is_gone_falls_back_to_the_default`, `test_a_quran_override_that_exists_wins_over_the_default`, `test_the_engine_row_defaults_to_this_computer`, `test_choosing_whisperx_is_remembered_and_reaches_the_spec` (its spec half stays in Task 5), `test_whisperx_without_a_token_says_where_to_put_it`, `test_whisperx_with_a_token_needs_no_note`)

**Interfaces:**
- Consumes: `Prefs` (`language`, `theme`, `engine`, `quran_override`, `output_dir`, `job_dirs`, `default_look`, `save_default_look`, `default_episode_names`, `default_episode_kinds`, `save_default_episode`, `KEEP_DEFAULT`), `theme.MODES`, `i18n.LANGUAGES`, `i18n.LANGUAGE_NAMES`, `config.settings.ENGINES`, `env_dir`, `get_settings`, `config.paths.user_log_dir`, `notices_path`, `QURAN_INPUT_DIR`, `gui.files.open_folder`, `qurantext.__version__`.
- Produces: `SettingsDialog(prefs, *, parent=None, quran_default: Path | None, tab: str | None = None)`; `TABS = ("general", "transcription", "files", "videos", "about")`; signals `language_requested(str)`, `theme_requested(str)`; method `language_refused(reason: str)`; attribute `changed_files: bool`; the widget attributes named in the spec §3.2; `current_tab() -> str`; `set_quran(path | None)`, `set_output_dir(path | None)` (public, as the form had).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_settings_dialog.py
"""The Settings dialog: five tabs, every control writes prefs as it changes."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="the window needs Qt: pip install 'qurantext[gui]'")

from qurantext.gui import theme  # noqa: E402
from qurantext.gui.home.settings_dialog import TABS, SettingsDialog  # noqa: E402
from qurantext.gui.i18n import t  # noqa: E402
from tests.media_helpers import QURAN_FILE  # noqa: E402


@pytest.fixture()
def dialog(qt_app, prefs, tmp_path):
    theme.apply_theme(qt_app, "light")
    made = SettingsDialog(prefs, quran_default=QURAN_FILE)
    yield made
    made.deleteLater()


def test_it_has_five_tabs_and_opens_on_the_one_asked_for(qt_app, prefs) -> None:
    dialog = SettingsDialog(prefs, quran_default=QURAN_FILE, tab="transcription")
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == [
        t(f"settings.tab.{name}") for name in TABS
    ]
    assert dialog.current_tab() == "transcription"
    assert dialog.windowTitle().strip("‎‏") == t("settings.title")
    dialog.deleteLater()


def test_general_asks_for_language_and_theme_through_signals(dialog, prefs) -> None:
    languages, themes = [], []
    dialog.language_requested.connect(languages.append)
    dialog.theme_requested.connect(themes.append)
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("ar"))
    dialog.language_combo.activated.emit(dialog.language_combo.currentIndex())
    assert languages == ["ar"]
    dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData("dark"))
    dialog.theme_combo.activated.emit(dialog.theme_combo.currentIndex())
    assert themes == ["dark"]
    assert prefs.theme == "dark"  # the dialog writes it; the window applies it


def test_a_refused_language_snaps_back_and_says_why(dialog) -> None:
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("ar"))
    dialog.language_refused("busy")
    assert dialog.language_combo.currentData() == "en"
    assert dialog.language_note.isVisible() is False or dialog.language_note.text() == "busy"
    assert dialog.language_note.text() == "busy"


def test_transcription_engine_round_trips_and_notes_a_missing_token(dialog, prefs, monkeypatch) -> None:
    from qurantext.gui.home import settings_dialog as module

    monkeypatch.setattr(module, "_token_missing", lambda: True)
    assert dialog.engine_buttons["local"].isChecked()
    dialog.engine_buttons["whisperx"].setChecked(True)
    assert prefs.engine == "whisperx"
    assert dialog.no_token_label.isVisibleTo(dialog)
    assert str(module.env_dir()) in dialog.no_token_label.text() or "QURANTEXT" in dialog.no_token_label.text()
    dialog.engine_buttons["local"].setChecked(True)
    assert not dialog.no_token_label.isVisibleTo(dialog)


def test_files_quran_and_output_round_trip_and_flag_the_change(dialog, prefs, tmp_path) -> None:
    assert dialog.changed_files is False
    custom = tmp_path / "my.txt"
    custom.write_text("x", encoding="utf-8")
    dialog.set_quran(custom)
    assert prefs.quran_override == custom and dialog.changed_files
    assert str(custom) in dialog.quran_label.text() or custom.name in dialog.quran_label.text()
    dialog.set_quran(None)
    assert prefs.quran_override is None
    assert dialog.quran_label.text() == t("home.quran_override.default")
    dialog.set_output_dir(tmp_path)
    assert prefs.output_dir == tmp_path
    dialog.set_output_dir(None)
    assert dialog.output_label.text() == t("home.output_dir.default")


def test_a_quran_override_that_is_gone_falls_back_to_the_default(dialog, prefs, tmp_path) -> None:
    prefs.quran_override = tmp_path / "gone.txt"
    again = SettingsDialog(prefs, quran_default=QURAN_FILE)
    assert again.quran_label.text() == t("home.quran_override.default")
    assert prefs.quran_override == tmp_path / "gone.txt"  # kept for when the drive is back
    again.deleteLater()


def test_job_folders_list_add_and_remove(dialog, prefs, tmp_path, monkeypatch) -> None:
    """Review Focus 1: a folder that is not there is still listed, with Remove."""
    gone = tmp_path / "unplugged"
    prefs.job_dirs = [gone]
    again = SettingsDialog(prefs, quran_default=QURAN_FILE)
    assert again.job_dirs_list.count() == 1 and str(gone) in again.job_dirs_list.item(0).text()
    from qurantext.gui.home import settings_dialog as module

    monkeypatch.setattr(module.QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    again.add_dir_button.click()
    assert prefs.job_dirs == [gone, tmp_path] and again.changed_files
    again.job_dirs_list.setCurrentRow(0)
    again.remove_dir_button.click()
    assert prefs.job_dirs == [tmp_path]
    again.deleteLater()


def test_videos_shows_and_resets_the_default_look_and_clears_the_episode(dialog, prefs) -> None:
    from qurantext.core.looks import NIGHT_GOLD, PRESETS

    assert t("look.preset.night_gold") in dialog.look_label.text()
    prefs.save_default_look(PRESETS["sand"])
    again = SettingsDialog(prefs, quran_default=QURAN_FILE)
    assert t("look.preset.sand") in again.look_label.text()
    again.look_reset_button.click()
    assert prefs.default_look == NIGHT_GOLD
    assert again.intro_label.text() == t("settings.episode.none")
    assert not again.intro_clear_button.isEnabled()
    again.deleteLater()


def test_about_names_the_version_and_links_the_log_folder(dialog, monkeypatch, tmp_path) -> None:
    import qurantext
    from qurantext.gui.home import settings_dialog as module

    assert qurantext.__version__ in dialog.version_label.text()
    opened = []
    monkeypatch.setattr(module, "open_folder", lambda folder: opened.append(folder) or True)
    dialog.log_link.linkActivated.emit("logs")
    assert opened and opened[0].name == "logs"
    assert dialog.github_link.text().count("github.com") == 1
```

Move the six listed tests out of `tests/test_home_panels.py` (delete them there; their behaviour is now covered above). `test_choosing_whisperx_is_remembered_and_reaches_the_spec` keeps its "reaches the spec" half in Task 5.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_settings_dialog.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'qurantext.gui.home.settings_dialog'`

- [ ] **Step 3: Write `gui/home/settings_dialog.py`**

```python
# src/qurantext/gui/home/settings_dialog.py
"""Everything that is about this machine or every job, in one place.

The form keeps only a job's own choices. Each control here writes ``Prefs``
as it changes, as the form always has; the window applies a language or
theme (which touch every window) and, after the dialog closes, tells the
form and the list what to reload when ``changed_files`` is set.
"""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import qurantext
from qurantext.config.paths import QURAN_INPUT_DIR, notices_path, user_log_dir, user_log_file
from qurantext.config.settings import ENGINES, env_dir, get_settings
from qurantext.core.looks import NIGHT_GOLD
from qurantext.gui import i18n, theme
from qurantext.gui.files import open_folder
from qurantext.gui.i18n import path_text, plain_title, t
from qurantext.gui.icons import set_icon
from qurantext.gui.prefs import KEEP_DEFAULT, Prefs
from qurantext.gui.widgets import SectionHeader

__all__ = ["GITHUB_URL", "TABS", "SettingsDialog"]

TABS = ("general", "transcription", "files", "videos", "about")
GITHUB_URL = "https://github.com/Grazyen96/QalunTextAlignment"


def _token_missing() -> bool:
    """True when no Replicate token is set; False when the settings cannot be read."""
    try:
        return not get_settings().replicate_api_token
    except ValueError:
        return False


def _file_filter(name: str, suffixes: list[str]) -> str:
    patterns = " ".join(f"*{suffix}" for suffix in suffixes)
    return f"{name} ({patterns});;{t('home.filter.all')} (*)"


class SettingsDialog(QDialog):
    """Five tabs; see the module docstring for who applies what."""

    language_requested = Signal(str)
    theme_requested = Signal(str)

    def __init__(
        self,
        prefs: Prefs,
        *,
        parent: QWidget | None = None,
        quran_default: Path | None,
        tab: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._prefs = prefs
        self._quran_default = quran_default
        #: Set once the Quran text, the output folder or the job folders changed.
        self.changed_files = False
        self.setWindowTitle(plain_title(t("settings.title")))
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._general(), t("settings.tab.general"))
        self.tabs.addTab(self._transcription(), t("settings.tab.transcription"))
        self.tabs.addTab(self._files(), t("settings.tab.files"))
        self.tabs.addTab(self._videos(), t("settings.tab.videos"))
        self.tabs.addTab(self._about(), t("settings.tab.about"))
        layout.addWidget(self.tabs, 1)
        buttons = QDialogButtonBox(self)
        self.close_button = buttons.addButton(t("settings.close"), QDialogButtonBox.ButtonRole.RejectRole)
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(buttons)
        if tab in TABS:
            self.tabs.setCurrentIndex(TABS.index(tab))

    def current_tab(self) -> str:
        return TABS[self.tabs.currentIndex()]

    # -- General ------------------------------------------------------------------

    def _general(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.language_combo = QComboBox()
        for code in i18n.LANGUAGES:
            self.language_combo.addItem(i18n.LANGUAGE_NAMES[code], code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(i18n.current_language()))
        self.language_combo.activated.connect(
            lambda index: self.language_requested.emit(self.language_combo.itemData(index))
        )
        form.addRow(t("home.language"), self.language_combo)
        self.language_note = QLabel()
        self.language_note.setWordWrap(True)
        self.language_note.setVisible(False)
        form.addRow(self.language_note)
        self.theme_combo = QComboBox()
        for code in theme.MODES:
            self.theme_combo.addItem(t(f"home.theme.{code}"), code)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(self._prefs.theme))
        self.theme_combo.activated.connect(self._theme_chosen)
        form.addRow(t("home.theme"), self.theme_combo)
        return page

    def _theme_chosen(self, index: int) -> None:
        code = self.theme_combo.itemData(index)
        self._prefs.theme = code
        self.theme_requested.emit(code)

    def language_refused(self, reason: str) -> None:
        """The window would not switch: put the combo back and say why."""
        self.language_combo.setCurrentIndex(self.language_combo.findData(i18n.current_language()))
        self.language_note.setText(reason)
        self.language_note.setVisible(True)

    # -- Transcription ------------------------------------------------------------

    def _transcription(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        self._engine_group = QButtonGroup(self)
        self._engine_group.setExclusive(True)
        self.engine_buttons: dict[str, QRadioButton] = {}
        for value in ENGINES:
            button = QRadioButton(t(f"home.engine.{value}"))
            self.engine_buttons[value] = button
            self._engine_group.addButton(button)
            column.addWidget(button)
        self.engine_buttons[self._prefs.engine].setChecked(True)
        self.no_token_label = QLabel()
        self.no_token_label.setWordWrap(True)
        column.addWidget(self.no_token_label)
        column.addStretch(1)
        self._engine_group.buttonToggled.connect(self._engine_changed)
        self._show_token_note()
        return page

    def _current_engine(self) -> str:
        for value, button in self.engine_buttons.items():
            if button.isChecked():
                return value
        return "local"

    def _engine_changed(self) -> None:
        self._prefs.engine = self._current_engine()
        self._show_token_note()

    def _show_token_note(self) -> None:
        missing = self._current_engine() == "whisperx" and _token_missing()
        self.no_token_label.setText(t("home.engine.no_token", folder=path_text(env_dir())) if missing else "")
        self.no_token_label.setVisible(missing)

    # -- Files --------------------------------------------------------------------

    def _files(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.quran_label = QLabel()
        self.quran_label.setWordWrap(True)
        self.quran_choose_button = QPushButton(t("home.choose"))
        self.quran_choose_button.clicked.connect(self._choose_quran)
        self.quran_reset_button = QPushButton(t("home.quran_override.reset"))
        self.quran_reset_button.clicked.connect(lambda: self.set_quran(None))
        form.addRow(t("home.quran_text"), self._value_row(self.quran_label, self.quran_choose_button, self.quran_reset_button))
        self.output_label = QLabel()
        self.output_label.setWordWrap(True)
        self.output_choose_button = QPushButton(t("home.choose"))
        self.output_choose_button.clicked.connect(self._choose_output_dir)
        self.output_reset_button = QPushButton(t("home.output_dir.reset"))
        self.output_reset_button.clicked.connect(lambda: self.set_output_dir(None))
        form.addRow(t("home.output_dir"), self._value_row(self.output_label, self.output_choose_button, self.output_reset_button))
        self.job_dirs_list = QListWidget()
        self.job_dirs_list.setMaximumHeight(120)
        for folder in self._prefs.job_dirs:
            self.job_dirs_list.addItem(path_text(folder))
        dirs = QWidget()
        dirs_column = QVBoxLayout(dirs)
        dirs_column.setContentsMargins(0, 0, 0, 0)
        dirs_column.addWidget(self.job_dirs_list)
        dir_buttons = QHBoxLayout()
        self.add_dir_button = QPushButton(t("settings.add_dir"))
        self.remove_dir_button = QPushButton(t("settings.remove_dir"))
        set_icon(self.add_dir_button, "folder-open", size=16)
        set_icon(self.remove_dir_button, "x", size=16)
        self.add_dir_button.clicked.connect(self._add_dir)
        self.remove_dir_button.clicked.connect(self._remove_dir)
        dir_buttons.addWidget(self.add_dir_button)
        dir_buttons.addWidget(self.remove_dir_button)
        dir_buttons.addStretch(1)
        dirs_column.addLayout(dir_buttons)
        form.addRow(t("settings.job_dirs"), dirs)
        self.job_dirs_list.currentRowChanged.connect(lambda *_: self._update_dir_buttons())
        self._update_dir_buttons()
        self._update_quran_label()
        self._update_output_label()
        return page

    @staticmethod
    def _value_row(label: QLabel, *buttons: QPushButton) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label, 1)
        for button in buttons:
            layout.addWidget(button)
        return row

    def _usable_override(self) -> Path | None:
        override = self._prefs.quran_override
        return override if override is not None and override.is_file() else None

    def _choose_quran(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, plain_title(t("home.quran_override.dialog_title")), str(QURAN_INPUT_DIR), _file_filter(t("home.filter.text"), [".txt"])
        )
        if name:
            self.set_quran(Path(name))

    def set_quran(self, path: Path | None) -> None:
        self._prefs.quran_override = path
        self.changed_files = True
        self._update_quran_label()

    def _update_quran_label(self) -> None:
        override = self._usable_override()
        if override is not None:
            self.quran_label.setText(t("home.quran_override.custom", path=path_text(override)))
        elif self._quran_default is not None:
            self.quran_label.setText(t("home.quran_override.default"))
        else:
            self.quran_label.setText(t("home.quran_missing"))

    def _choose_output_dir(self) -> None:
        name = QFileDialog.getExistingDirectory(self, plain_title(t("home.output_dir.dialog_title")), str(Path.home()))
        if name:
            self.set_output_dir(Path(name))

    def set_output_dir(self, path: Path | None) -> None:
        self._prefs.output_dir = path
        self.changed_files = True
        self._update_output_label()

    def _update_output_label(self) -> None:
        folder = self._prefs.output_dir
        self.output_label.setText(
            t("home.output_dir.custom", path=path_text(folder)) if folder is not None else t("home.output_dir.default")
        )

    def _add_dir(self) -> None:
        name = QFileDialog.getExistingDirectory(self, plain_title(t("settings.add_dir.dialog_title")), str(Path.home()))
        if not name:
            return
        folder = Path(name)
        dirs = list(self._prefs.job_dirs)
        if folder not in dirs:
            dirs.append(folder)
            self._prefs.job_dirs = dirs
            self.job_dirs_list.addItem(path_text(folder))
            self.changed_files = True
        self._update_dir_buttons()

    def _remove_dir(self) -> None:
        row = self.job_dirs_list.currentRow()
        if row < 0:
            return
        dirs = list(self._prefs.job_dirs)
        if row < len(dirs):
            del dirs[row]
            self._prefs.job_dirs = dirs
            self.changed_files = True
        self.job_dirs_list.takeItem(row)
        self._update_dir_buttons()

    def _update_dir_buttons(self) -> None:
        self.remove_dir_button.setEnabled(self.job_dirs_list.currentRow() >= 0)

    # -- Videos -------------------------------------------------------------------

    def _videos(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.look_label = QLabel()
        self.look_reset_button = QPushButton(t("settings.look.reset"))
        set_icon(self.look_reset_button, "refresh-cw", size=16)
        self.look_reset_button.clicked.connect(self._reset_look)
        form.addRow(t("settings.look"), self._value_row(self.look_label, self.look_reset_button))
        self.intro_label = QLabel()
        self.intro_clear_button = QPushButton(t("settings.episode.clear"))
        self.intro_clear_button.clicked.connect(lambda: self._clear_part("intro"))
        self.outro_label = QLabel()
        self.outro_clear_button = QPushButton(t("settings.episode.clear"))
        self.outro_clear_button.clicked.connect(lambda: self._clear_part("outro"))
        form.addRow(SectionHeader(t("settings.episode")))
        form.addRow(t("settings.episode.intro"), self._value_row(self.intro_label, self.intro_clear_button))
        form.addRow(t("settings.episode.outro"), self._value_row(self.outro_label, self.outro_clear_button))
        self._show_look()
        self._show_episode()
        return page

    def _show_look(self) -> None:
        look = self._prefs.default_look
        name = t(f"look.preset.{look.base_preset}") if f"look.preset.{look.base_preset}" in i18n.STRINGS["en"] else look.base_preset
        self.look_label.setText(name if look.is_preset else t("settings.look.based_on", preset=name))
        self.look_reset_button.setEnabled(look != NIGHT_GOLD)

    def _reset_look(self) -> None:
        self._prefs.save_default_look(NIGHT_GOLD)
        self._show_look()

    def _show_episode(self) -> None:
        kinds = self._prefs.default_episode_kinds
        names = self._prefs.default_episode_names
        for kind, name, label, button in zip(
            kinds, names, (self.intro_label, self.outro_label), (self.intro_clear_button, self.outro_clear_button), strict=True
        ):
            if kind == "generated":
                label.setText(t("settings.episode.generated"))
            elif kind == "clip":
                label.setText(name or t("settings.episode.none"))
            else:
                label.setText(t("settings.episode.none"))
            button.setEnabled(kind != "none")

    def _clear_part(self, part: str) -> None:
        if part == "intro":
            self._prefs.save_default_episode(None, KEEP_DEFAULT, intro_generated=None)
        else:
            self._prefs.save_default_episode(KEEP_DEFAULT, None, outro_generated=None)
        self._show_episode()

    # -- About --------------------------------------------------------------------

    def _about(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        self.version_label = QLabel(t("settings.version", version=qurantext.__version__))
        self.version_label.setFont(theme.font("section"))
        column.addWidget(self.version_label)
        self.log_link = QLabel(f'<a href="logs">{html.escape(t("home.open_log_folder"))}</a>')
        self.log_link.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.log_link.setToolTip(t("home.open_log_folder.tip", path=path_text(user_log_file())))
        self.log_link.linkActivated.connect(lambda _link: open_folder(user_log_dir()))
        column.addWidget(self.log_link)
        notices = notices_path()
        self.notices_link = QLabel(f'<a href="notices">{html.escape(t("settings.notices"))}</a>')
        self.notices_link.setTextInteractionFlags(self.log_link.textInteractionFlags())
        if notices.is_file():
            self.notices_link.linkActivated.connect(lambda _link: QDesktopServices.openUrl(QUrl.fromLocalFile(str(notices))))
        else:
            self.notices_link.setEnabled(False)
            self.notices_link.setToolTip(t("settings.notices.missing"))
        column.addWidget(self.notices_link)
        self.github_link = QLabel(f'<a href="{GITHUB_URL}">{html.escape(t("settings.github"))}</a>')
        self.github_link.setTextInteractionFlags(self.log_link.textInteractionFlags())
        self.github_link.setOpenExternalLinks(True)
        column.addWidget(self.github_link)
        column.addStretch(1)
        return page
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_settings_dialog.py tests/test_home_panels.py tests/test_i18n.py -q`
Expected: PASS (the six moved tests are gone from `test_home_panels`; the form still has its rows until Task 5, so the remaining form tests pass)

- [ ] **Step 5: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/home/settings_dialog.py tests/test_settings_dialog.py tests/test_home_panels.py
git commit -m "Gather every machine-level setting into a Settings dialog with five tabs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: The form as a column of the job's own choices

**Files:**
- Modify: `src/qurantext/gui/home/new_job.py` (`_build`, `_apply_prefs`, `_show_engine_notes`, `set_running`, `set_progress`, `spec`, the Quran/output/engine methods, `_align_label_columns`)
- Modify: `tests/test_home_panels.py`

**Interfaces:**
- Consumes: `Prefs.engine / quran_override / output_dir`, `widgets.make_primary`, `icons.set_icon`, `theme.font("secondary")`, `theme.SP_*`.
- Produces: `NewJobPanel.column: QWidget` (max width 560), `description_label: QLabel`, `engine_note: QLabel` (rich text, link emits `settings_requested`), signal `settings_requested`, `reload_settings() -> None`, `select_mode(mode: str) -> None`; `progress_bar` in Start's slot with `setTextVisible(True)`; `set_progress(fraction, text)` semantics below. Removed: `quran_row`, `quran_label`, `quran_choose_button`, `quran_reset_button`, `output_row`, `output_label`, `output_choose_button`, `output_reset_button`, `engine_row`, `engine_buttons`, `no_token_label`, `engine_hint_label`, `set_quran`, `set_output_dir`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_home_panels.py`:

```python
def test_the_form_is_a_column_of_the_jobs_own_choices(qt_app, prefs, store) -> None:
    from PySide6.QtWidgets import QFormLayout

    from qurantext.gui.i18n import t

    panel = _panel(prefs, store)
    try:
        assert panel.column.maximumWidth() == 560
        labels = [
            panel.more_form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget().text()
            for row in range(panel.more_form.rowCount())
            if panel.more_form.itemAt(row, QFormLayout.ItemRole.LabelRole) is not None
        ]
        assert labels == [t("home.subtitles"), t("home.formats")]
        assert not hasattr(panel, "quran_row") and not hasattr(panel, "engine_row")
        assert panel.description_label.text() == t("home.mode.recitation.desc")
        panel.lecture_button.setChecked(True)
        assert panel.description_label.text() == t("home.mode.lecture.desc")
        assert panel.start_button.property("primary") is True
        assert panel.problem_label.isVisibleTo(panel)  # no file yet: the reason sits under Start
    finally:
        panel.deleteLater()


def test_the_engine_note_shows_for_whisperx_and_links_to_settings(qt_app, prefs, store, monkeypatch) -> None:
    from qurantext.gui.home import new_job as module
    from qurantext.gui.i18n import t

    monkeypatch.setattr(module, "_token_missing", lambda: True)
    panel = _panel(prefs, store)
    try:
        assert not panel.engine_note.isVisibleTo(panel)
        prefs.engine = "whisperx"
        panel.reload_settings()
        assert panel.engine_note.isVisibleTo(panel)
        assert t("home.engine.note") in panel.engine_note.text()
        assert t("home.engine.change") in panel.engine_note.text()
        asked = []
        panel.settings_requested.connect(lambda: asked.append(1))
        panel.engine_note.linkActivated.emit("settings")
        assert asked == [1]
        assert panel.spec().engine == "whisperx"
        prefs.engine = "local"
        panel.reload_settings()
        assert not panel.engine_note.isVisibleTo(panel)
    finally:
        panel.deleteLater()


def test_the_spec_reads_the_machine_settings_from_prefs(qt_app, prefs, store, tmp_path) -> None:
    panel = _panel(prefs, store)
    try:
        prefs.output_dir = tmp_path
        custom = tmp_path / "my.txt"
        custom.write_text("x", encoding="utf-8")
        prefs.quran_override = custom
        panel.reload_settings()
        spec = panel.spec()
        assert spec.output_dir == tmp_path and spec.quran == custom
    finally:
        panel.deleteLater()


def test_reload_keeps_the_remembered_surah_when_the_store_still_has_it(qt_app, prefs, store) -> None:
    """Review Focus 4: a Quran change refills the surahs and keeps the choice."""
    panel = _panel(prefs, store)
    try:
        index = next(i for i in range(panel.surah_box.count()) if panel.surah_box.itemData(i)["surah_num"] == 25)
        panel.surah_box.setCurrentIndex(index)
        panel.from_spin.setValue(7)
        prefs.quran_override = None
        panel.reload_settings()
        assert panel.surah_box.currentData()["surah_num"] == 25
        assert panel.from_spin.value() == 7
    finally:
        panel.deleteLater()


def test_while_running_the_bar_takes_starts_slot_and_says_the_stage(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    try:
        panel.set_running(True)
        assert not panel.start_button.isVisibleTo(panel)
        assert panel.progress_bar.isVisibleTo(panel) and panel.cancel_button.isVisibleTo(panel)
        assert panel.progress_bar.isTextVisible()
        assert panel.progress_bar.height() >= 32
        panel.set_progress(0.42, "Transcribing — 42%")
        assert panel.progress_bar.format() == "Transcribing — 42%"
        assert panel.progress_bar.value() == 42
        assert not panel.status_label.isVisibleTo(panel)
        panel.set_progress(None, "Starting…")  # a busy bar draws no text: the line says it
        assert panel.status_label.text() == "Starting…"
        panel.set_running(False)
        assert panel.start_button.isVisibleTo(panel) and not panel.progress_bar.isVisibleTo(panel)
    finally:
        panel.deleteLater()


def test_select_mode_checks_the_button_and_focuses_choose(qt_app, prefs, store) -> None:
    panel = _panel(prefs, store)
    try:
        panel.show()
        panel.select_mode("lecture")
        assert panel.lecture_button.isChecked()
        assert panel.choose_button.hasFocus() or panel.focusWidget() is panel.choose_button
    finally:
        panel.deleteLater()
```

Update existing tests in the same file: `test_more_options_open_and_closed_persists`, `test_the_more_options_are_labelled_rows_that_hide_together`, `test_the_value_texts_no_longer_repeat_their_labels`, `test_the_two_forms_share_one_label_column`, `test_the_form_reads_top_down_with_choose_inside_the_drop_zone`, `test_set_running_true_disables_inputs` (drop the removed widgets from their expectations), `test_spec_reflects_every_control` and `test_choosing_whisperx_is_remembered_and_reaches_the_spec` (set `prefs.engine`/`prefs.output_dir`/`prefs.quran_override` then `panel.reload_settings()` instead of clicking form controls), `test_the_progress_bar_leaves_the_words_to_the_status_line` (replace with the running-state test above), and delete `test_a_folded_whisperx_choice_without_a_token_is_still_said`, `test_a_folded_whisperx_choice_says_the_recording_goes_online`, `test_the_folded_hint_does_not_widen_the_panel`, `test_a_folded_local_choice_needs_no_hint` (the engine note test above replaces them). Any test in `tests/test_gui.py` that sets the engine through `home.new_job.engine_buttons` sets `prefs.engine` and calls `home.new_job.reload_settings()` instead.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_home_panels.py -q -k "column or engine_note or machine_settings or remembered_surah or starts_slot or select_mode"`
Expected: FAIL with `AttributeError: 'NewJobPanel' object has no attribute 'column'`

- [ ] **Step 3: Reshape `_build`**

In `src/qurantext/gui/home/new_job.py`:

1. Imports: drop `QURAN_INPUT_DIR`, `ENGINES`, `env_dir`, `get_settings` if no longer used after the edits below (keep `get_settings` for `_token_missing`, which stays); add `from qurantext.gui import theme`.
2. `_build` starts:

```python
    def _build(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        # One column, no wider than a form reads well; the stretch keeps it at
        # the leading edge (the layout mirrors it in Arabic).
        self.column = QWidget()
        self.column.setMaximumWidth(_COLUMN_WIDTH)
        outer.addWidget(self.column, 1)
        outer.addStretch(0)
        layout = QVBoxLayout(self.column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SP_12)
```

with `_COLUMN_WIDTH = 560` at module level; everything that was added to `layout` stays added to this `layout`.

3. Drop zone: give the drop label an icon line above it:

```python
        self.drop_icon = QLabel()
        self.drop_icon.setPixmap(icon("upload", "secondary").pixmap(QSize(24, 24)))
        self.drop_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(self.drop_icon)
```

(`from qurantext.gui.icons import icon, set_icon`; `QSize` from QtCore) and in `_show_audio_lines`, once a file is set, swap it to `icon("file-music", "text")`. Raise `_DROP_ZONE_HEIGHT` to 112.

4. After `layout.addLayout(mode_row)` add:

```python
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.description_label.setFont(theme.font("secondary"))
        self.description_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        layout.addWidget(self.description_label)
```

(`QPalette` from QtGui) and in `_mode_changed` / `_set_mode_visibility` set its text to `t("home.mode.recitation.desc")` or `t("home.mode.lecture.desc")`.

5. Delete the `engine_hint_label` block, the `quran_row`, `output_row` and `engine_row` blocks (and `_choose_quran_override`, `set_quran`, `_choose_output_dir`, `set_output_dir`, `_update_quran_label`, `_update_output_dir_label`, `_current_engine`, `_engine_changed`, `_show_engine_notes`, and the `_quran_override` / `_output_dir` fields). `more_form` keeps Subtitles, Files and Render right away.

6. After `layout.addWidget(self.more_group)` add the engine note:

```python
        # Said here, not chosen here: the engine is a machine setting now.
        self.engine_note = QLabel()
        self.engine_note.setWordWrap(True)
        self.engine_note.setTextFormat(Qt.TextFormat.RichText)
        self.engine_note.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.engine_note.linkActivated.connect(lambda _link: self.settings_requested.emit())
        self.engine_note.setVisible(False)
        layout.addWidget(self.engine_note)
```

with `settings_requested = Signal()` on the class, and:

```python
    def _show_engine_note(self) -> None:
        whisperx = self._prefs.engine == "whisperx"
        if not whisperx:
            self.engine_note.setVisible(False)
            return
        parts = [html.escape(t("home.engine.note"))]
        if _token_missing():
            parts.append(html.escape(t("home.engine.no_token", folder=path_text(env_dir()))))
        parts.append(f'<a href="settings">{html.escape(t("home.engine.change"))}</a>')
        self.engine_note.setText(" ".join(parts))
        self.engine_note.setVisible(True)
```

(`import html`; keep `env_dir`).

7. Replace the buttons row and progress bar with:

```python
        start_row = QHBoxLayout()
        self.start_button = QPushButton(t("home.start"))
        self.start_button.setDefault(True)
        make_primary(self.start_button)
        self.start_button.clicked.connect(lambda: self.start_requested.emit(self.spec()))
        # While a job runs the bar stands where Start stood, as tall, and says the stage.
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedHeight(max(36, self.start_button.sizeHint().height()))
        self.progress_bar.setVisible(False)
        self.cancel_button = QPushButton(t("home.cancel"))
        set_icon(self.cancel_button, "x", size=16)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.cancel_button.setVisible(False)
        start_row.addWidget(self.start_button, 1)
        start_row.addWidget(self.progress_bar, 1)
        start_row.addWidget(self.cancel_button)
        layout.addLayout(start_row)
        # What stops Start is said under it, in a quieter voice.
        self.problem_label = QLabel()
        self.problem_label.setWordWrap(True)
        self.problem_label.setFont(theme.font("secondary"))
        layout.addWidget(self.problem_label)
```

8. `_apply_prefs`: delete the engine and `_show_engine_notes` lines; call `self._show_engine_note()` at its end. `spec()` reads:

```python
            engine=self._prefs.engine,
            output_dir=self._prefs.output_dir,
```

and `_usable_override` / `_effective_quran` read `self._prefs.quran_override` directly.

9. New methods:

```python
    def reload_settings(self) -> None:
        """The Settings dialog changed something this form shows or sends: read it again."""
        self._load_surahs()  # refills from the (possibly new) store and puts the remembered surah back
        self._show_engine_note()
        self._refresh()

    def select_mode(self, mode: str) -> None:
        """Choose *mode* for the person (the empty state's cards) and move them to the file."""
        (self.recitation_button if mode == "recitation" else self.lecture_button).setChecked(True)
        self.choose_button.setFocus(Qt.FocusReason.OtherFocusReason)
```

`_load_surahs` already restores the remembered surah and range from prefs (`_restore_range`), so Review Focus 4 holds.

10. `set_running`: drop the removed widgets from the loop; after it:

```python
        self.start_button.setVisible(not running)
        self.progress_bar.setVisible(running)
        self.cancel_button.setVisible(running)
        if running:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("")
            self.status_label.setVisible(False)
        else:
            self._refresh()
```

(the status line is shown again by `show_status` with the outcome.) `set_progress`:

```python
    def set_progress(self, fraction: float | None, text: str | None) -> None:
        """Show how far the job is: on the bar when it knows a fraction, on the line when it does not.

        A busy bar draws no text, so a stage without a fraction says its
        sentence on the status line; a stage with one says it on the bar and
        the line goes quiet. *text* None leaves whatever is said as it is: the
        window keeps an answer to the person up there while the bar moves on.
        """
        if fraction is None:
            self.progress_bar.setRange(0, 0)
            if text is not None:
                self.show_status(text)
            return
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(int(max(0.0, min(1.0, fraction)) * 100))
        if text is not None:
            self.progress_bar.setFormat(text)
            self.show_status("")
```

11. `_align_label_columns` keeps working over `self._form` and `self.more_form`.

- [ ] **Step 4: Run the tests, fix the updated ones, verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_home_panels.py tests/test_gui.py tests/test_rtl.py -q`
Expected: PASS. If a `test_gui` test asserts the status line shows a percentage (`"40%" in home.new_job.status_label.text()` at about line 1303), change it to read `home.new_job.progress_bar.format()`.

- [ ] **Step 5: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/home/new_job.py tests/test_home_panels.py tests/test_gui.py
git commit -m "Make the form a column of the job's own choices, with the progress bar in Start's place

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Job cards, the empty state and the folder watcher

**Files:**
- Modify: `src/qurantext/gui/home/job_list.py` (`JobListPanel.__init__`, `refresh`, `stop_reading`, `_read_jobs`, `_update_empty_state`, `_JobRow`, `_detail_text`; add `EmptyState`)
- Modify: `tests/test_home_panels.py`

**Interfaces:**
- Consumes: `JobEntry.thumbnail / background` (Task 1), `widgets.StatusChip`, `widgets.Card`, `icons.icon`, `theme.font`, `config.paths.user_cache_dir`.
- Produces: `JobListPanel.mode_requested = Signal(str)`, `JobListPanel.empty_state: EmptyState`, `empty_label` (= `empty_state.hint_label`), `JobListPanel.watcher: QFileSystemWatcher`, `JobListPanel._watch_timer: QTimer` (500 ms), `_JobRow.thumb_label`, `_JobRow.chip`, `_JobRow.date_label`; `EmptyState(QWidget)` with `title_label`, `hint_label`, `recitation_card`, `lecture_card`, signal `mode_chosen(str)`, `set_reading(bool)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_home_panels.py`:

```python
def _listed_rows(panel):
    from tests.qt_helpers import wait_until_listed

    wait_until_listed(panel)
    return [panel.list.itemWidget(panel.list.item(i)) for i in range(panel.list.count())]


def test_rows_are_cards_with_a_chip_a_date_and_a_tile(qt_app, prefs, tmp_path, no_default_job_dirs) -> None:
    from qurantext.gui.home.job_list import JobListPanel
    from qurantext.gui.i18n import t
    from tests.test_thumbnails import _project

    _project(tmp_path)
    prefs.job_dirs = [tmp_path]
    panel = JobListPanel(prefs)
    try:
        (row,) = _listed_rows(panel)
        assert row.chip.text_label.text() == t("home.status.needs_review")
        assert row.chip.property("kind") == "attention"
        assert row.detail_label.text() == t("home.detail", mode=t("home.mode.recitation"), scope="25:7")
        assert row.date_label.text()  # the locale's short date
        assert not row.thumb_label.pixmap().isNull()
        assert row.thumb_label.size().width() == 48 and row.thumb_label.size().height() == 48
    finally:
        panel.stop_reading()
        panel.deleteLater()


def test_a_damaged_row_gets_an_alert_chip_and_the_fallback_tile(qt_app, prefs, tmp_path, no_default_job_dirs) -> None:
    from qurantext.gui.home.job_list import JobListPanel
    from qurantext.gui.i18n import t

    (tmp_path / "bad.qalun.json").write_text("{not json", encoding="utf-8")
    prefs.job_dirs = [tmp_path]
    panel = JobListPanel(prefs)
    try:
        (row,) = _listed_rows(panel)
        assert row.chip.text_label.text() == t("home.status.damaged")
        assert row.chip.property("kind") == "attention"
        assert not row.thumb_label.pixmap().isNull()  # the tile, drawn in code
    finally:
        panel.stop_reading()
        panel.deleteLater()


def test_the_empty_state_explains_the_modes_and_chooses_one(qt_app, prefs, no_default_job_dirs) -> None:
    from qurantext.gui.home.job_list import JobListPanel
    from qurantext.gui.i18n import t
    from tests.qt_helpers import wait_until_listed

    panel = JobListPanel(prefs)
    try:
        wait_until_listed(panel)
        assert panel.empty_state.isVisibleTo(panel) and not panel.list.isVisibleTo(panel)
        assert panel.empty_state.title_label.text() == t("home.empty.title")
        assert panel.empty_label.text() == t("home.empty.hint")
        chosen = []
        panel.mode_requested.connect(chosen.append)
        panel.empty_state.lecture_card.click()
        assert chosen == ["lecture"]
    finally:
        panel.stop_reading()
        panel.deleteLater()


def test_the_watcher_refreshes_once_for_a_burst_of_changes(qt_app, prefs, tmp_path, no_default_job_dirs, monkeypatch) -> None:
    """Review Focus 5: twenty files landing in a second mean one read, not twenty."""
    from qurantext.gui.home.job_list import JobListPanel
    from tests.qt_helpers import spin, wait_until_listed

    prefs.job_dirs = [tmp_path, tmp_path / "unplugged"]  # Review Focus 1: the missing one is skipped
    panel = JobListPanel(prefs)
    try:
        wait_until_listed(panel)
        assert panel.watcher.directories() == [str(tmp_path)]
        reads = []
        monkeypatch.setattr(panel, "refresh", lambda: reads.append(1))
        for _ in range(20):
            panel.watcher.directoryChanged.emit(str(tmp_path))
        spin(700)
        assert reads == [1]
    finally:
        panel.stop_reading()
        panel.deleteLater()
```

Update `test_rows_on_screen_take_the_new_amber_when_the_theme_switches` to read the chip's colour (`row.chip.text_label.palette().color(row.chip.text_label.foregroundRole())`) instead of `detail_label`'s, and any test reading `_detail_text` or the detail line's status part to use the chip.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_home_panels.py -q -k "cards_with or damaged_row or empty_state_explains or watcher"`
Expected: FAIL with `AttributeError: '_JobRow' object has no attribute 'chip'`

- [ ] **Step 3: Rows as cards**

In `job_list.py`, replace `_JobRow.__init__` and `_detail_text`:

```python
_CHIP_FOR_STATUS = {
    NEEDS_REVIEW: ("attention", "circle-alert"),
    CHANGED_SINCE_RENDER: ("attention", "circle-alert"),
    RENDERED: ("accent", "film"),
    REVIEWED: ("neutral", "circle-check"),
    DAMAGED: ("attention", "triangle-alert"),
}
_THUMB_PX = 48


class _JobRow(QWidget):
    """One job as a card: its picture, its name, a status chip, the detail line and the date."""

    def __init__(self, entry: JobEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SP_8, theme.SP_8, theme.SP_8, theme.SP_8)
        row.setSpacing(theme.SP_12)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(_THUMB_PX, _THUMB_PX)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setPixmap(_thumbnail_pixmap(entry))
        row.addWidget(self.thumb_label, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(theme.SP_4)
        self.name_label = QLabel(entry.name)
        self.name_label.setAlignment(_leading_edge(self))
        bold_font = self.name_label.font()
        bold_font.setBold(True)
        self.name_label.setFont(bold_font)
        text.addWidget(self.name_label)
        kind, icon_name = _CHIP_FOR_STATUS.get(entry.status, ("neutral", None))
        self.chip = StatusChip(t(_STATUS_KEYS[entry.status]), icon_name=icon_name, kind=kind)
        chip_row = QHBoxLayout()
        chip_row.addWidget(self.chip)
        chip_row.addStretch(1)
        text.addLayout(chip_row)
        self.detail_label = QLabel(_detail_text(entry))
        self.detail_label.setAlignment(_leading_edge(self))
        self.detail_label.setFont(theme.font("secondary"))
        self.detail_label.setVisible(entry.status != DAMAGED)
        text.addWidget(self.detail_label)
        row.addLayout(text, 1)

        self.date_label = QLabel(_date_text(entry.modified))
        self.date_label.setFont(theme.font("secondary"))
        self.date_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        row.addWidget(self.date_label, 0, Qt.AlignmentFlag.AlignTop)

        self._warning = entry.status in _WARNING_STATUSES
        self._selected = False
        for label in (self.name_label, self.detail_label, self.date_label):
            label.setForegroundRole(QPalette.ColorRole.Text)
            label.installEventFilter(self)
        self._paint_labels()
```

`_paint_labels` keeps its selected-row branch for `name_label`, `detail_label` and `date_label`; its warning branch now calls `self.chip.set_kind(self.chip.property("kind"))` (which re-reads the amber) instead of colouring the detail line. Add:

```python
def _date_text(modified: float) -> str:
    if modified <= 0:
        return ""
    stamp = QDateTime.fromSecsSinceEpoch(int(modified))
    return QLocale().toString(stamp, QLocale.FormatType.ShortFormat)


def _thumbnail_pixmap(entry: JobEntry) -> QPixmap:
    """The cached picture, scaled into the tile; else a tile in the look's colour with the mode's icon."""
    if entry.thumbnail is not None:
        pixmap = QPixmap(str(entry.thumbnail))
        if not pixmap.isNull():
            return pixmap.scaled(_THUMB_PX, _THUMB_PX, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    tile = QPixmap(_THUMB_PX, _THUMB_PX)
    background = QColor(*entry.background) if entry.background else QColor(theme.current_tokens().border)
    tile.fill(background)
    name = "triangle-alert" if entry.status == DAMAGED else ("book-open" if entry.mode == "lecture" else "mic")
    role = "on_accent" if background.lightness() < 128 and theme.current_tokens().name == "light" else "text"
    glyph = icon(name, role).pixmap(QSize(24, 24))
    painter = QPainter(tile)
    painter.drawPixmap((_THUMB_PX - 24) // 2, (_THUMB_PX - 24) // 2, glyph)
    painter.end()
    return tile


def _detail_text(entry: JobEntry) -> str:
    if entry.status == DAMAGED:
        return ""
    mode_text = t("home.mode.recitation") if entry.mode == "recitation" else t("home.mode.lecture")
    scope = entry.ayah_range or tn("home.cards", entry.card_count)
    return t("home.detail", mode=mode_text, scope=scope)
```

Imports to add: `QDateTime, QLocale, QSize, QTimer` from QtCore; `QColor, QPainter, QPixmap` from QtGui; `QFileSystemWatcher` from QtCore; `from qurantext.gui import theme`; `from qurantext.gui.icons import icon, set_icon`; `from qurantext.gui.widgets import Card, SectionHeader, StatusChip`; `from qurantext.config.paths import user_cache_dir`. On a dark-background tile in the dark theme the text colour is light, so `"text"` reads; on a dark tile in the light theme `"on_accent"` is white. The `home.row_detail` key stays in `i18n` for the running row only if it still uses it; otherwise remove it from both languages.

- [ ] **Step 4: Thumbnails from the worker**

In `_read_jobs`, pass the cache: `entries = list_jobs(job_dirs_for(extra), hidden=hidden, cancel=cancel, thumbnail_cache=user_cache_dir())`.

- [ ] **Step 5: The empty state**

```python
class EmptyState(QWidget):
    """What the list shows before there is a job: who this is for, and the two ways in."""

    mode_chosen = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(theme.SP_16, theme.SP_24, theme.SP_16, theme.SP_24)
        column.setSpacing(theme.SP_12)
        column.addStretch(1)
        self.icon_label = QLabel()
        pixmap = QPixmap(str(bundled_asset("icon/qalun-256.png")))
        self.icon_label.setPixmap(pixmap.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.icon_label)
        self.title_label = QLabel(t("home.empty.title"))
        self.title_label.setFont(theme.font("section"))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.title_label)
        self.hint_label = QLabel(t("home.empty.hint"))
        self.hint_label.setWordWrap(True)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.hint_label)
        self.recitation_card = _ModeCard("mic", t("home.mode.recitation"), t("home.mode.recitation.desc"))
        self.lecture_card = _ModeCard("book-open", t("home.mode.lecture"), t("home.mode.lecture.desc"))
        self.recitation_card.clicked.connect(lambda: self.mode_chosen.emit("recitation"))
        self.lecture_card.clicked.connect(lambda: self.mode_chosen.emit("lecture"))
        column.addWidget(self.recitation_card)
        column.addWidget(self.lecture_card)
        column.addStretch(2)

    def set_reading(self, reading: bool) -> None:
        """While the folders are read, say so and hold the cards back: the emptiness is a guess."""
        self.hint_label.setText(t("home.reading") if reading else t("home.empty.hint"))
        for widget in (self.icon_label, self.title_label, self.recitation_card, self.lecture_card):
            widget.setVisible(not reading)


class _ModeCard(Card):
    """A clickable card naming one kind of job; Enter or Space works too."""

    clicked = Signal()

    def __init__(self, icon_name: str, title: str, description: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(title)
        self.body.setContentsMargins(theme.SP_12, theme.SP_8, theme.SP_12, theme.SP_8)
        row = QHBoxLayout()
        self.icon_label = QLabel()
        self.icon_label.setPixmap(icon(icon_name, "accent").pixmap(QSize(20, 20)))
        row.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        self.title_label = QLabel(title)
        bold = self.title_label.font()
        bold.setBold(True)
        self.title_label.setFont(bold)
        self.description_label = QLabel(description)
        self.description_label.setWordWrap(True)
        self.description_label.setFont(theme.font("secondary"))
        text.addWidget(self.title_label)
        text.addWidget(self.description_label)
        row.addLayout(text, 1)
        self.body.addLayout(row)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)

    def click(self) -> None:
        self.clicked.emit()
```

In `JobListPanel.__init__`, replace the `empty_label` block with:

```python
        self.empty_state = EmptyState()
        self.empty_label = self.empty_state.hint_label  # its words are set by _update_empty_state
        self.empty_state.mode_chosen.connect(self.mode_requested)
        layout.addWidget(self.empty_state, 1)
```

(`mode_requested = Signal(str)` on the class; `from qurantext.config.paths import bundled_asset, user_cache_dir`), and `_update_empty_state`:

```python
    def _update_empty_state(self) -> None:
        has_rows = self.list.count() > 0
        self.empty_state.set_reading(self.reading)
        self.list.setVisible(has_rows)
        self.empty_state.setVisible(not has_rows)
```

- [ ] **Step 6: The watcher**

In `__init__`, before the first `self.refresh()`:

```python
        # The folders tell the list when a job appears, goes or is renamed; a
        # burst of files (a render writing several) is read once, half a second
        # after the last of them.
        self.watcher = QFileSystemWatcher(self)
        self._watch_timer = QTimer(self)
        self._watch_timer.setSingleShot(True)
        self._watch_timer.setInterval(_WATCH_DEBOUNCE_MS)
        self._watch_timer.timeout.connect(self.refresh)
        self.watcher.directoryChanged.connect(lambda _path: self._watch_timer.start())
```

with `_WATCH_DEBOUNCE_MS = 500`. In `refresh`, after bumping the generation, `self._arm_watcher()`:

```python
    def _arm_watcher(self) -> None:
        """Watch every job folder that is there; one on an unplugged drive is simply not watched."""
        wanted = [str(folder) for folder in job_dirs_for(list(self._prefs.job_dirs)) if folder.is_dir()]
        current = self.watcher.directories()
        gone = [path for path in current if path not in wanted]
        new = [path for path in wanted if path not in current]
        if gone:
            self.watcher.removePaths(gone)
        if new:
            self.watcher.addPaths(new)  # a path it cannot watch is returned, and left unwatched
```

In `stop_reading`, add `self._watch_timer.stop()`.

- [ ] **Step 7: Run the tests, update the amber-row test, verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_home_panels.py tests/test_gui.py tests/test_rtl.py -q`
Expected: PASS

- [ ] **Step 8: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/home/job_list.py src/qurantext/gui/i18n.py tests/test_home_panels.py
git commit -m "Show each job as a card with its picture, a status chip and its date, explain the two kinds of job when there are none, and follow the folders

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: The window: header on top, footer gone, Settings wired

**Files:**
- Modify: `src/qurantext/gui/main_window.py` (`_build`, the language section, `set_theme`; add `_open_settings`, `make_settings_dialog`, `_after_settings`, `_toggle_theme`, `_open_help`, `changeEvent`)
- Modify: `tests/test_gui.py` (the fit test; the `log_link` / `language_combo` tests near lines 2120–2225), `tests/test_home_panels.py` (`test_the_footer_offers_the_theme_and_applies_it` → header), `tests/test_rtl.py` (append)

**Interfaces:**
- Consumes: `HeaderBar` (Task 3), `SettingsDialog` (Task 4), `NewJobPanel.settings_requested / reload_settings / select_mode` (Task 5), `JobListPanel.mode_requested` (Task 6), `theme.apply_theme / current_tokens`.
- Produces: `MainWindow.header: HeaderBar`, `make_settings_dialog(tab: str | None = None) -> SettingsDialog`, `_after_settings(dialog) -> None`, `open_settings(tab=None) -> None` (exec + after), `toggle_theme() -> None`, `README_URL`.

- [ ] **Step 1: Write the failing tests**

Replace `test_the_footer_offers_the_theme_and_applies_it` in `tests/test_home_panels.py` with:

```python
def test_the_header_toggles_the_theme_and_opens_settings(qt_app, prefs, no_default_job_dirs) -> None:
    from PySide6.QtGui import QPalette

    from qurantext.gui import theme
    from qurantext.gui.main_window import MainWindow

    theme.apply_theme(qt_app, "light")
    prefs.theme = "system"
    window = MainWindow(prefs=prefs)
    try:
        assert not hasattr(window, "theme_combo") and not hasattr(window, "log_link")
        assert window.header.theme_button.property("qalun.icon")[0] == "moon"
        window.header.theme_toggle_requested.emit()
        assert prefs.theme == "dark"
        assert qt_app.palette().color(QPalette.ColorRole.Window).name().upper() == theme.DARK.window
        assert window.header.theme_button.property("qalun.icon")[0] == "sun"
        dialog = window.make_settings_dialog("files")
        assert dialog.current_tab() == "files"
        dialog.deleteLater()
    finally:
        theme.apply_theme(qt_app, "light")
        window.close()
        window.deleteLater()
```

In `tests/test_gui.py`: the fit test (about line 1160) becomes parametrised over `("en", "ar")`, applying the language with `apply_language(qt_app, code)` before building `home` (or using the `_arabic` pattern from `tests/test_rtl.py`) and resetting after; it also asserts `home.header.height() == 48`. The `log_link` tests (2120–2175) open `dialog = home.make_settings_dialog("about")` and use `dialog.log_link`; `test_open_log_folder_leaves_the_arabic_footer_its_height` is deleted (no footer). The language tests (2200–2225) use `dialog = home.make_settings_dialog()` and `dialog.language_combo`, then `home._language_from_dialog(dialog, "ar")`. Add:

```python
def test_a_language_refused_while_a_review_is_open_snaps_the_dialog_back(qt_app, home, reviews, tmp_path) -> None:
    """Review Focus 3."""
    from qurantext.gui.i18n import t

    review = reviews.open_one(tmp_path)  # use whatever helper this module has for an open review
    dialog = home.make_settings_dialog()
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("ar"))
    home._language_from_dialog(dialog, "ar")
    assert dialog.language_combo.currentData() == "en"
    assert dialog.language_note.text() == t("home.language_busy")
    assert home.windowTitle() == "Qalun"
    dialog.deleteLater()
    review.close()


def test_closing_settings_after_a_file_change_reloads_the_form_and_the_list(qt_app, home, tmp_path, monkeypatch) -> None:
    dialog = home.make_settings_dialog("files")
    reloaded, refreshed = [], []
    monkeypatch.setattr(home.new_job, "reload_settings", lambda: reloaded.append(1))
    monkeypatch.setattr(home.job_list, "refresh", lambda: refreshed.append(1))
    dialog.set_output_dir(tmp_path)
    home._after_settings(dialog)
    assert reloaded == [1] and refreshed == [1]
    dialog.deleteLater()


def test_help_opens_the_readme(qt_app, home, desktop) -> None:
    from qurantext.gui.main_window import README_URL

    home.header.help_requested.emit()
    assert [url.toString() for url in desktop.opened] == [README_URL]
```

(`reviews` and `desktop` are fixtures this module already has; adapt the review-opening call to the helper that exists there.) Append to `tests/test_rtl.py`:

```python
def test_the_header_and_the_form_column_mirror(qt_app, tmp_path, no_default_job_dirs) -> None:
    from tests.qt_helpers import spin, wait_until_listed

    main = MainWindow(prefs=_prefs(tmp_path))
    main.resize(1024, 680)
    main.show()
    wait_until_listed(main.job_list)
    spin(100)
    assert main.header.help_button.x() < main.header.title_label.x()
    column_right = main.new_job.column.mapTo(main, main.new_job.column.rect().topRight()).x()
    panel_right = main.new_job.mapTo(main, main.new_job.rect().topRight()).x()
    assert panel_right - column_right <= 2  # the column hugs the right edge
    main.close()
    main.deleteLater()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_home_panels.py tests/test_gui.py tests/test_rtl.py -q -k "header or settings or readme or refused or mirror"`
Expected: FAIL with `AttributeError: 'MainWindow' object has no attribute 'header'`

- [ ] **Step 3: Rebuild `_build` and add the slots**

In `main_window.py`: imports `from PySide6.QtCore import QEvent, Qt, QUrl`, `from PySide6.QtGui import QCloseEvent, QDesktopServices`, `from qurantext.gui.home.header import HeaderBar`, `from qurantext.gui.home.settings_dialog import SettingsDialog`, `from qurantext.gui.theme import apply_theme, current_tokens`; drop `html`, `QComboBox`, `user_log_dir`, `user_log_file`, `open_folder`, `THEME_MODES` if unused. Module constant `README_URL = "https://github.com/Grazyen96/QalunTextAlignment#readme"`. `_build` after the splitter:

```python
        self.header = HeaderBar()
        self.header.show_theme(current_tokens().name)
        self.header.theme_toggle_requested.connect(self.toggle_theme)
        self.header.settings_requested.connect(lambda: self.open_settings())
        self.header.help_requested.connect(self._open_help)
        self.new_job.settings_requested.connect(lambda: self.open_settings("transcription"))
        self.job_list.mode_requested.connect(self.new_job.select_mode)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.addWidget(splitter, 1)
        layout.addWidget(body, 1)
        self.setCentralWidget(root)
        splitter.setSizes([_JOB_LIST_WIDTH, max(0, self.width() - _JOB_LIST_WIDTH)])
```

Delete the footer, `language_combo`, `log_link`, `theme_combo`, `_language_chosen`, `_theme_chosen`, `_select_language_in_combo`, `_update_language_combo` and `_open_log_folder` (the dialog does that now); where `_update_language_combo()` was called, call nothing. `set_language` no longer touches a combo; after `self._build()` it keeps the splitter sizes and the audio as today. Add:

```python
    # -- the header ---------------------------------------------------------------

    def toggle_theme(self) -> None:
        """Pin the opposite of the theme in force (System becomes an explicit choice)."""
        self.set_theme("light" if current_tokens().name == "dark" else "dark")

    def set_theme(self, code: str) -> None:
        self._prefs.theme = code
        apply_theme(QApplication.instance(), code)
        self.header.show_theme(current_tokens().name)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        super().changeEvent(event)
        if event.type() == QEvent.Type.ApplicationPaletteChange:
            self.header.show_theme(current_tokens().name)  # System followed the desktop

    def _open_help(self) -> None:
        if not QDesktopServices.openUrl(QUrl(README_URL)):
            self._answer(_Said("home.help_failed"))

    # -- settings -----------------------------------------------------------------

    def make_settings_dialog(self, tab: str | None = None) -> SettingsDialog:
        dialog = SettingsDialog(self._prefs, parent=self, quran_default=_default_quran_file(), tab=tab)
        dialog.language_requested.connect(partial(self._language_from_dialog, dialog))
        dialog.theme_requested.connect(self.set_theme)
        return dialog

    def open_settings(self, tab: str | None = None) -> None:
        dialog = self.make_settings_dialog(tab)
        try:
            dialog.exec()
            self._after_settings(dialog)
        finally:
            dialog.deleteLater()

    def _after_settings(self, dialog: SettingsDialog) -> None:
        """What the dialog changed that the form shows or the list reads."""
        if dialog.changed_files:
            self.new_job.reload_settings()
            self.job_list.refresh()

    def _language_from_dialog(self, dialog: SettingsDialog, code: str) -> None:
        """Switch, or tell the dialog why not; a switch rebuilds this window under a dialog in the old words, so it closes."""
        if self.set_language(code):
            dialog.accept()
        else:
            dialog.language_refused(t("home.language_busy"))
```

`set_language` stays as it is but its refusal branch no longer calls `_select_language_in_combo` or `_answer` for the combo; it returns False. The `set_theme` from phase A is replaced by the one above.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_home_panels.py tests/test_gui.py tests/test_rtl.py tests/test_language.py tests/test_settings_dialog.py -q`
Expected: PASS, including the fit test in both languages (the shorter More options brings the Arabic form under 680 px; if it does not, lower `_DROP_ZONE_HEIGHT` to 104 and report the measured minimum).

- [ ] **Step 5: Lint and commit**

```bash
venv/bin/ruff check src tests && venv/bin/ruff format src tests
git add src/qurantext/gui/main_window.py tests/test_gui.py tests/test_home_panels.py tests/test_rtl.py
git commit -m "Put the header on the home window, drop the footer, and open Settings from the gear and the engine note

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Screenshots, README, the whole suite

**Files:**
- Modify: `tools/screenshots.py` (`shoot`), `tests/test_screenshots_tool.py`, `README.md` ("The window" section), `docs/release-checklist.md`

**Interfaces:**
- Consumes: everything above.
- Produces: images `settings-<tab>-<lang>-<theme>.png` and `home-empty-<lang>-<theme>.png`.

- [ ] **Step 1: Extend the tool's test**

In `tests/test_screenshots_tool.py`, add to the expected set: `"home-empty-en-light.png"`, `"settings-general-en-light.png"`, `"settings-about-en-light.png"`.

- [ ] **Step 2: Run it to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests/test_screenshots_tool.py -q`
Expected: FAIL (names missing)

- [ ] **Step 3: Extend `shoot`**

Inside the per-theme loop of `tools/screenshots.py`, after the home image:

```python
            from qurantext.gui.home.settings_dialog import TABS
            from qurantext.jobs import catalog

            for tab in TABS:
                dialog = home.make_settings_dialog(tab)
                written.append(_grab(dialog, out_dir / f"settings-{tab}-{tag}.png"))
                dialog.close()
                dialog.deleteLater()
            # The first launch: no jobs anywhere.
            real_dirs = catalog.default_job_dirs
            catalog.default_job_dirs = lambda: []
            try:
                empty_prefs = Prefs(QSettings(str(out_dir / f"prefs-empty-{tag}.ini"), QSettings.Format.IniFormat))
                empty_prefs.job_dirs = []
                empty = MainWindow(prefs=empty_prefs)
                empty.resize(1024, 680)
                _spin(600)
                written.append(_grab(empty, out_dir / f"home-empty-{tag}.png"))
                empty.job_list.stop_reading()
                empty.close()
                empty.deleteLater()
            finally:
                catalog.default_job_dirs = real_dirs
```

(the tool already builds `home` with job folders that hold projects, so the main `home-*` image shows cards; make sure the tool's project has a card so a thumbnail renders).

- [ ] **Step 4: Run the tool and look**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python tools/screenshots.py output/shots-phase-b`
Open `home-en-light.png`, `home-empty-en-light.png`, `home-ar-dark.png`, `settings-files-en-light.png` with the Read tool and confirm: header with icon, name and three buttons; form column no wider than 560 px; a job card with a thumbnail, chip and date; the empty state with two mode cards; Arabic mirrored; the Files tab with its three rows. Record what you see in the report.

- [ ] **Step 5: README and checklist**

In `README.md` "The window": replace the sentence about Theme in the footer with "**Settings** (the gear in the header) holds the language, theme, transcription engine, Quran text, output and job folders, default look and episode defaults; the sun/moon button beside it switches the theme." In `docs/release-checklist.md`, under the screenshot item, add "including the Settings tabs and the empty first launch".

- [ ] **Step 6: Whole suite and linters**

Run: `QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest -q --ignore=tests/test_local_engine_slow.py -p no:cacheprovider`
Expected: every test passes. Then `venv/bin/ruff check src tests tools && venv/bin/ruff format --check src tests tools` → clean.

- [ ] **Step 7: Commit**

```bash
git add tools/screenshots.py tests/test_screenshots_tool.py README.md docs/release-checklist.md
git commit -m "Photograph the Settings tabs and the empty first launch too, and say in the README where the settings went

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

- Spec §2.1 header → Task 3 + 7; §2.2 form, note, running state → Task 5; §2.3 cards, watcher → Tasks 1 + 6; §2.4 empty state → Task 6; §2.5 dialog → Task 4 (+ Task 7 wiring); §3.5 thumbnails → Task 1; §3.7 strings and the four icons → Task 2; §5 errors: watcher skip (Task 6 test), thumbnail fallbacks (Task 1 tests), language refusal (Task 4 + 7 tests), missing notices file (Task 4 code), help URL failure (Task 7 code); §6 tests → each task; screenshot tool → Task 8.
- Names used across tasks: `JobEntry.thumbnail/background`, `list_jobs(thumbnail_cache=)`, `HeaderBar.show_theme`, `SettingsDialog.changed_files / language_refused / current_tab / set_quran / set_output_dir / TABS`, `NewJobPanel.column / description_label / engine_note / settings_requested / reload_settings / select_mode`, `JobListPanel.mode_requested / empty_state / watcher / _watch_timer`, `_JobRow.chip / thumb_label / date_label`, `MainWindow.header / make_settings_dialog / open_settings / _after_settings / _language_from_dialog / toggle_theme / set_theme / README_URL` — consistent.
- Review Focus 1 → Tasks 4 and 6; 2 → Task 1; 3 → Task 7; 4 → Task 5; 5 → Task 6.
- Known soft spots an implementer must check against the code: the exact `Project` constructor and `save_project` signature (Task 1 helper), the `reviews`/`desktop` fixture names in `tests/test_gui.py` (Task 7), and whether `home.row_detail` is still used after Task 6 (remove from both languages if not).

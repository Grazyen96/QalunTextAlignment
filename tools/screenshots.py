"""Render every window and dialog offscreen, light and dark, English and Arabic, as PNGs.

For the phase reviews: run it before and after a visual change and look at
the pairs. It builds its own project from four Al-Furqan words, so it needs
no media on disk; the home window lists whatever jobs the checkout has.

    QT_QPA_PLATFORM=offscreen venv/bin/python tools/screenshots.py output/shots
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QCoreApplication, QEvent, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

_CARD = {
    "surah_num": 25, "surah_name": "الفرقان", "from_ayah": 7, "to_ayah": 7,
    "full_text": "وَقَالُوا مَالِ هَٰذَا الرَّسُولِ", "confidence": 1.0,
    "start_time": 0.0, "end_time": 4.0,
    "word_timings": [
        {"word": "وَقَالُوا", "start": 0.0, "end": 1.0},
        {"word": "مَالِ", "start": 1.0, "end": 1.6},
        {"word": "هَٰذَا", "start": 1.6, "end": 2.3},
        {"word": "الرَّسُولِ", "start": 2.3, "end": 4.0},
    ],
}  # fmt: skip


def _spin(ms: int) -> None:
    """Run the event loop for *ms* milliseconds, deleting what was let go."""
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.005)


def _grab(widget: QWidget, path: Path) -> Path:
    widget.show()
    _spin(300)
    widget.grab().save(str(path))
    return path


def _project(tmp: Path, mode: str):
    from qurantext.jobs.project import CaptionCue, Project

    captions = []
    if mode == "lecture":
        captions = [CaptionCue(start=4.0, end=8.0, text="وهم يملكون عقلا", words=[])]
    return Project(audio=tmp / "recording.mp3", mode=mode, cards=[dict(_CARD)], captions=captions)


def shoot(out_dir: Path, *, themes=("light", "dark"), languages=("en", "ar")) -> list[Path]:
    """Write one PNG per screen, theme and language into *out_dir*; return their paths."""
    from qurantext.config.paths import DEFAULT_QURAN_PATH, QURAN_DB_PATH
    from qurantext.data.quran_db import ensure_quran_db
    from qurantext.gui import theme
    from qurantext.gui.language import apply_language
    from qurantext.gui.main_window import MainWindow
    from qurantext.gui.prefs import Prefs
    from qurantext.gui.review.ayah_picker import AyahPicker
    from qurantext.gui.review.episode_dialog import EpisodeDialog
    from qurantext.gui.review.export_dialog import ExportDialog
    from qurantext.gui.review.player import FakePlayer
    from qurantext.gui.review.window import ReviewWindow

    # The ayah picker reads the real store; build it if this checkout has none yet.
    ensure_quran_db(DEFAULT_QURAN_PATH, QURAN_DB_PATH).close()
    app = QApplication.instance() or QApplication(sys.argv)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="qalun-shots-") as scratch:
        tmp = Path(scratch)
        for language in languages:
            for name in themes:
                apply_language(app, language)
                theme.apply_theme(app, name)
                tag = f"{language}-{name}"
                # Fresh settings per pass, never the person's own.
                prefs = Prefs(QSettings(str(tmp / f"prefs-{tag}.ini"), QSettings.Format.IniFormat))
                home = MainWindow(prefs=prefs)
                home.resize(1024, 680)
                _spin(300)
                written.append(_grab(home, out_dir / f"home-{tag}.png"))
                home.job_list.stop_reading()
                home.close()
                home.deleteLater()
                for mode in ("recitation", "lecture"):
                    review = ReviewWindow(_project(tmp, mode), player=FakePlayer(60.0), prefs=prefs)
                    review.resize(1280, 800)
                    review.seek(1.2)
                    written.append(_grab(review, out_dir / f"review-{mode}-{tag}.png"))
                    if mode == "recitation":
                        export = ExportDialog(review.session, review)
                        written.append(_grab(export, out_dir / f"export-{tag}.png"))
                        export.close()
                        export.deleteLater()
                        picker = AyahPicker(review, surah=25, from_ayah=7, to_ayah=11)
                        written.append(_grab(picker, out_dir / f"ayah-picker-{tag}.png"))
                        picker.close()
                        picker.deleteLater()
                    else:
                        episode = EpisodeDialog(review.session, prefs=prefs, parent=review)
                        written.append(_grab(episode, out_dir / f"episode-{tag}.png"))
                        episode.close()
                        episode.deleteLater()
                    review.close()
                    review.deleteLater()
                _spin(100)
    apply_language(app, "en")
    theme.apply_theme(app, "light")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--themes", nargs="+", default=("light", "dark"))
    parser.add_argument("--languages", nargs="+", default=("en", "ar"))
    args = parser.parse_args(argv)
    paths = shoot(args.out_dir, themes=tuple(args.themes), languages=tuple(args.languages))
    print(f"{len(paths)} images in {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

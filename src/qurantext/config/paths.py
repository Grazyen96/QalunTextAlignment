"""Where the app's files live, on a checkout and on an installed machine.

Every path used to hang off ``Path(__file__).resolve().parents[3]``, which walks
``config -> qurantext -> src -> repository root``. That is correct only when the
code is running from the source tree. Installed as a wheel it resolves to a
directory inside the Python installation, so the bundled font, the Quran store
and the basmala audio all pointed at places that do not exist — verified by
building the wheel and importing it.

So there are two modes, decided once at import:

* **Running from a checkout** — keep the repository layout exactly as before, so
  an existing working tree with its ``input/``, ``output/`` and ``data/`` keeps
  working unchanged.
* **Installed** — user files go to the platform's own directories, and assets
  that ship with the code are read from inside the package.

``QURANTEXT_DATA_DIR`` and ``QURANTEXT_OUTPUT_DIR`` override either mode, which
is what a desktop app will set once the user picks a working folder.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

APP_NAME = "Qalun"
_APP_DIR_POSIX = "qalun"

__all__ = [
    "APP_NAME",
    "BASMALA_AUDIO_PATH",
    "BASMALA_INPUT_DIR",
    "DATA_DIR",
    "DEFAULT_FONT_PATH",
    "EXPORT_PACKAGES_OUTPUT_DIR",
    "INPUT_DIR",
    "LECTURES_INPUT_DIR",
    "LECTURE_MATCHING_OUTPUT_DIR",
    "OUTPUT_DIR",
    "PROJECT_ROOT",
    "QURAN_DB_PATH",
    "QURAN_INPUT_DIR",
    "RANGE_MATCHING_OUTPUT_DIR",
    "RECITATIONS_INPUT_DIR",
    "RECITATION_MATCHING_OUTPUT_DIR",
    "REQUIRED_DIRECTORIES",
    "VIDEOS_OUTPUT_DIR",
    "WHISPERX_TRANSCRIPTS_OUTPUT_DIR",
    "bundled_asset",
    "checkout_root",
    "ensure_required_directories",
    "user_data_dir",
]


@lru_cache(maxsize=1)
def checkout_root() -> Path | None:
    """The repository root when running from source, otherwise ``None``.

    Identified by the marker files rather than by position alone, so an
    installed package inside a directory that happens to be three levels deep
    is not mistaken for a checkout.
    """
    candidate = Path(__file__).resolve().parents[3]
    if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "qurantext").is_dir():
        return candidate
    return None


def user_data_dir() -> Path:
    """The platform's directory for this application's own files."""
    override = os.getenv("QURANTEXT_DATA_DIR")
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        return Path(base).expanduser() / APP_NAME if base else Path.home() / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    # Linux and the rest follow the XDG base directory specification.
    base = os.getenv("XDG_DATA_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "share"
    return root / _APP_DIR_POSIX


def bundled_asset(relative: str) -> Path:
    """Resolve a file that ships inside the package.

    Reads from ``qurantext/assets/`` so the file travels with the wheel instead
    of being looked for next to a source checkout that will not be there.
    """
    return Path(__file__).resolve().parent.parent / "assets" / relative


def _output_root() -> Path:
    override = os.getenv("QURANTEXT_OUTPUT_DIR")
    if override:
        return Path(override).expanduser()
    root = checkout_root()
    return (root / "output") if root is not None else (user_data_dir() / "output")


def _input_root() -> Path:
    root = checkout_root()
    return (root / "input") if root is not None else (user_data_dir() / "input")


def _store_root() -> Path:
    override = os.getenv("QURANTEXT_DATA_DIR")
    if override:
        return Path(override).expanduser()
    root = checkout_root()
    return (root / "data") if root is not None else user_data_dir()


#: Repository root when running from source, else the user's data directory.
#: Prefer the specific paths below; this remains for callers that need a base.
PROJECT_ROOT = checkout_root() or user_data_dir()

INPUT_DIR = _input_root()
QURAN_INPUT_DIR = INPUT_DIR / "quran"
LECTURES_INPUT_DIR = INPUT_DIR / "lectures"
RECITATIONS_INPUT_DIR = INPUT_DIR / "recitations"
# User-supplied basmala spliced before each recitation (see core.basmala).
BASMALA_INPUT_DIR = INPUT_DIR / "basmala"
BASMALA_AUDIO_PATH = BASMALA_INPUT_DIR / "basmala.mp3"

OUTPUT_DIR = _output_root()
VIDEOS_OUTPUT_DIR = OUTPUT_DIR / "videos"
# Edit-spec packages staged for the Premiere UXP panel (architecture §8/§9).
EXPORT_PACKAGES_OUTPUT_DIR = OUTPUT_DIR / "export_packages"

# On-device data store (versioned SQLite build of the certified Qalun text).
DATA_DIR = _store_root()
QURAN_DB_PATH = DATA_DIR / "quran.sqlite"
RECITATION_MATCHING_OUTPUT_DIR = OUTPUT_DIR / "recitation_matching"
LECTURE_MATCHING_OUTPUT_DIR = OUTPUT_DIR / "lecture_matching"
WHISPERX_TRANSCRIPTS_OUTPUT_DIR = OUTPUT_DIR / "whisperx_transcripts"
RANGE_MATCHING_OUTPUT_DIR = OUTPUT_DIR / "range_matching"

#: The Qalun font that ships with the package.
DEFAULT_FONT_PATH = bundled_asset("fonts/qaloon.10.ttf")

REQUIRED_DIRECTORIES = (
    INPUT_DIR,
    QURAN_INPUT_DIR,
    LECTURES_INPUT_DIR,
    RECITATIONS_INPUT_DIR,
    BASMALA_INPUT_DIR,
    OUTPUT_DIR,
    VIDEOS_OUTPUT_DIR,
    RECITATION_MATCHING_OUTPUT_DIR,
    LECTURE_MATCHING_OUTPUT_DIR,
    WHISPERX_TRANSCRIPTS_OUTPUT_DIR,
    RANGE_MATCHING_OUTPUT_DIR,
)


def ensure_required_directories() -> None:
    """Create the standard input/output directory tree when requested."""
    for directory in REQUIRED_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)

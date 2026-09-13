"""Check that this machine can actually render, and say what to do if not.

Everything here failed for someone at some point, in a way that only showed up
deep inside a job:

* **Arabic shaping.** The renderer raises if Pillow reports no raqm support, and
  Pillow's own documentation says raqm needs FriBiDi installed separately. On a
  developer's Linux box it resolves from a system library; on a clean Windows or
  Mac there may be nothing to resolve, and the message the renderer raises then
  is not one a non-developer can act on. This is the single most likely reason a
  packaged build fails to draw anything.
* **FFmpeg.** Located by searching PATH, so an installed app that assumes it is
  there fails at the encode rather than at startup.
* **The store and the font.** Both resolve differently from a checkout than from
  an installed copy.

Each check answers three questions: is it usable, what exactly is wrong, and
what should the person do. The last one is the point — "libraqm missing" is not
an instruction.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass

from qurantext.config.paths import (
    DEFAULT_FONT_PATH,
    DEFAULT_QURAN_PATH,
    OUTPUT_DIR,
    QURAN_DB_PATH,
    checkout_root,
    user_data_dir,
)

__all__ = ["CheckResult", "Status", "format_report", "run_checks"]


class Status:
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: str
    detail: str
    #: What to do about it. Empty when there is nothing to do.
    remedy: str = ""

    @property
    def blocking(self) -> bool:
        return self.status == Status.FAIL


def _ffmpeg_binary(name: str) -> CheckResult:
    found = shutil.which(name)
    if not found:
        return CheckResult(
            name,
            Status.FAIL,
            "not found on PATH",
            f"Install FFmpeg, which provides {name}. A packaged build should ship "
            "it beside the application rather than rely on PATH.",
        )
    try:
        out = subprocess.run(
            [found, "-version"], check=False, capture_output=True, text=True, timeout=15
        ).stdout.splitlines()
        version = out[0] if out else found
    except (OSError, subprocess.SubprocessError) as error:
        return CheckResult(
            name,
            Status.FAIL,
            f"found but would not run: {error}",
            "Reinstall FFmpeg, or point PATH at a working build.",
        )
    return CheckResult(name, Status.OK, version.strip())


def _arabic_shaping() -> CheckResult:
    """The blocker. Without raqm the renderer refuses to draw at all."""
    try:
        from PIL import __version__ as pillow_version
        from PIL import features
    except ModuleNotFoundError:
        return CheckResult(
            "Arabic shaping",
            Status.FAIL,
            "Pillow is not installed",
            "pip install Pillow",
        )

    if not features.check("raqm"):
        have = [n for n in ("harfbuzz", "fribidi") if features.check(n)]
        missing = [n for n in ("harfbuzz", "fribidi") if not features.check(n)]
        return CheckResult(
            "Arabic shaping",
            Status.FAIL,
            f"Pillow {pillow_version} has no raqm support"
            + (f" (has {', '.join(have)}; missing {', '.join(missing)})" if missing else ""),
            "Arabic will not render. Pillow's wheels need FriBiDi installed "
            "separately: on Debian/Ubuntu `apt install libfribidi0`, on macOS "
            "`brew install fribidi`, on Windows ship fribidi.dll beside the "
            "application. Then reinstall Pillow.",
        )

    parts = [
        f"{name} {features.version(name)}"
        for name in ("raqm", "harfbuzz", "fribidi")
        if features.check(name)
    ]
    return CheckResult("Arabic shaping", Status.OK, ", ".join(parts))


def _bundled_font() -> CheckResult:
    if DEFAULT_FONT_PATH.is_file():
        size_kb = DEFAULT_FONT_PATH.stat().st_size // 1024
        return CheckResult("Bundled font", Status.OK, f"{DEFAULT_FONT_PATH.name} ({size_kb} KB)")
    return CheckResult(
        "Bundled font",
        Status.FAIL,
        f"missing at {DEFAULT_FONT_PATH}",
        "The font ships inside the package. A build missing it was packaged "
        "without its data files; check that assets/ is included.",
    )


def _bundled_quran() -> CheckResult:
    if DEFAULT_QURAN_PATH.is_file():
        size_kb = DEFAULT_QURAN_PATH.stat().st_size // 1024
        return CheckResult("Quran text", Status.OK, f"{DEFAULT_QURAN_PATH.name} ({size_kb} KB)")
    return CheckResult(
        "Quran text",
        Status.FAIL,
        f"missing at {DEFAULT_QURAN_PATH}",
        "The certified Qalun text ships inside the package. A build missing it "
        "was packaged without its data files; check that assets/ is included.",
    )


def _quran_store() -> CheckResult:
    if QURAN_DB_PATH.is_file():
        size_mb = QURAN_DB_PATH.stat().st_size / 1e6
        return CheckResult("Quran store", Status.OK, f"{QURAN_DB_PATH} ({size_mb:.0f} MB)")
    return CheckResult(
        "Quran store",
        Status.WARN,
        f"not built yet at {QURAN_DB_PATH}",
        "Built automatically the first time it is needed, from the bundled text. "
        "To build it now: `qurantext build-db`.",
    )


def _writable_output() -> CheckResult:
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        probe = OUTPUT_DIR / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        return CheckResult(
            "Output folder",
            Status.FAIL,
            f"{OUTPUT_DIR} is not writable: {error}",
            "Choose a different folder with QURANTEXT_OUTPUT_DIR, or fix the "
            "permissions on this one.",
        )
    return CheckResult("Output folder", Status.OK, str(OUTPUT_DIR))


def _window() -> CheckResult:
    try:
        from PySide6 import QtCore
    except ModuleNotFoundError:
        return CheckResult(
            "Window",
            Status.WARN,
            "Qt is not installed, so only the command line is available",
            "pip install 'qurantext[gui]'",
        )
    return CheckResult("Window", Status.OK, f"Qt {QtCore.qVersion()}")


def run_checks() -> list[CheckResult]:
    """Every check, in the order a person would want to read them."""
    return [
        _arabic_shaping(),
        _ffmpeg_binary("ffmpeg"),
        _ffmpeg_binary("ffprobe"),
        _bundled_font(),
        _bundled_quran(),
        _quran_store(),
        _writable_output(),
        _window(),
    ]


def format_report(results: list[CheckResult]) -> str:
    """The checks as text, with the remedies for anything that needs one."""
    marks = {Status.OK: "ok  ", Status.WARN: "note", Status.FAIL: "FAIL"}
    lines = [
        f"Qalun on {sys.platform}",
        f"  running from {'a checkout' if checkout_root() else 'an installed copy'}",
        f"  app data in {user_data_dir()}",
        "",
    ]
    width = max(len(r.name) for r in results)
    for result in results:
        lines.append(f"  [{marks[result.status]}] {result.name:<{width}}  {result.detail}")
    remedies = [r for r in results if r.remedy and r.status != Status.OK]
    if remedies:
        lines.append("")
        for result in remedies:
            lines.append(f"  {result.name}: {result.remedy}")
    blocking = [r for r in results if r.blocking]
    lines.append("")
    lines.append(
        "Ready to render."
        if not blocking
        else f"Cannot render yet: {len(blocking)} problem(s) above must be fixed."
    )
    return "\n".join(lines)

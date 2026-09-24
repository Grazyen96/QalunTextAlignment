"""Compatibility surface for the renderer modules.

This module used to carry a second, complete argparse CLI that duplicated the
flags ``qurantext generate-video`` already declared, with its own drifting
defaults. Rendering is now a callable job — see
:mod:`qurantext.jobs.render` — and the package CLI is the only parser.

What remains here is the re-export surface older imports rely on. It stops at
the renderer modules: ``RenderRequest``, ``RenderResult`` and ``render_video``
live in :mod:`qurantext.jobs.render` and are imported from there, because
``core/`` never imports ``jobs/`` (``tests/test_layering.py``).
"""

from __future__ import annotations

from qurantext.core.ass_renderer import build_ass, render_ass_video, validate_font_name
from qurantext.core.basmala import maybe_prepend_basmala
from qurantext.core.frame_renderer import (
    DEFAULT_PLACEHOLDER_TITLE,
    ActiveMatchTracker,
    active_match_at,
    render_frame_pillow,
    render_frame_video,
    validate_font_file,
    write_frame_video,
)
from qurantext.core.video_common import (
    ass_time,
    ayah_label,
    escape_ass,
    load_caption_segments,
    load_matches,
    validate_dimensions,
    validate_fps,
    validate_input_file,
    warn,
)

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_FRAME_RATE = 25

__all__ = [
    "DEFAULT_FRAME_RATE",
    "DEFAULT_HEIGHT",
    "DEFAULT_PLACEHOLDER_TITLE",
    "DEFAULT_WIDTH",
    "ActiveMatchTracker",
    "active_match_at",
    "ass_time",
    "ayah_label",
    "build_ass",
    "escape_ass",
    "load_caption_segments",
    "load_matches",
    "maybe_prepend_basmala",
    "render_ass_video",
    "render_frame_pillow",
    "render_frame_video",
    "validate_dimensions",
    "validate_font_file",
    "validate_font_name",
    "validate_fps",
    "validate_input_file",
    "warn",
    "write_frame_video",
]

"""QR codes drawn with Pillow from segno's module matrix.

segno only encodes; drawing here keeps the code in the video's own colours and
at an exact pixel size, so it stays sharp and scannable in the encoded frame.

Error correction is level M (15 % of the code can be damaged and still read),
with the standard quiet zone of 4 modules on every side, and every module a
whole number of pixels, at least 4: a phone filming a screen needs all three.
"""

from __future__ import annotations

import segno
from PIL import Image, ImageDraw

__all__ = ["qr_image", "qr_modules"]

_QUIET = 4
_MIN_MODULE_PX = 4

RGB = tuple[int, int, int]


def _encode(data: str) -> segno.QRCode:
    try:
        # boost_error=False keeps the level at M: a higher level would grow the
        # code for the same link, and the size check below assumes M.
        return segno.make_qr(data, error="m", boost_error=False)
    except segno.DataOverflowError as error:
        raise ValueError("link too long for a QR code") from error


def qr_modules(data: str) -> int:
    """The modules along one side of the code for ``data``, without the quiet zone."""
    return _encode(data).symbol_size(border=0)[0]


def qr_image(data: str, side_px: int, dark: RGB, light: RGB) -> Image.Image:
    """An RGB square of exactly ``side_px`` with the code for ``data`` centred in it.

    The light colour fills the square, so the quiet zone is at least 4 modules on
    every side (more when ``side_px`` is not an exact multiple of the module).
    Raises ``ValueError`` when ``data`` does not fit at level M, or when the square
    is too small for modules of 4 px.
    """
    code = _encode(data)
    modules = code.symbol_size(border=0)[0]
    module = side_px // (modules + 2 * _QUIET)
    if module < _MIN_MODULE_PX:
        raise ValueError("QR code too small to scan")
    img = Image.new("RGB", (side_px, side_px), tuple(light))
    offset = (side_px - module * modules) // 2
    draw = ImageDraw.Draw(img)
    fill = tuple(dark)
    for y, row in enumerate(code.matrix):  # segno's matrix has no border
        for x, bit in enumerate(row):
            if bit:
                x0, y0 = offset + x * module, offset + y * module
                draw.rectangle((x0, y0, x0 + module - 1, y0 + module - 1), fill=fill)
    return img

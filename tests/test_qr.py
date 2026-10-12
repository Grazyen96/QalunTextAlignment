import numpy as np
import pytest

from qurantext.config.paths import TEXT_FONT_BOLD_PATH, TEXT_FONT_PATH
from qurantext.core.qr import qr_image, qr_modules

cv2 = pytest.importorskip("cv2")


def _decode(img) -> str:
    data, _points, _ = cv2.QRCodeDetector().detectAndDecode(
        np.array(img.convert("RGB"))[:, :, ::-1]
    )
    return data


URL = "https://example.org/dars?utm_campaign=qalun-025-044-049&utm_source=youtube&utm_medium=video&utm_content=outro-qr"


@pytest.mark.parametrize(
    "dark, light", [((0, 0, 0), (255, 255, 255)), ((20, 20, 24), (252, 250, 244))]
)
def test_qr_decodes(dark, light):
    img = qr_image(URL, 400, dark, light)
    assert img.size == (400, 400) and _decode(img) == URL


def test_too_small_is_refused():
    with pytest.raises(ValueError):
        qr_image(URL, 60, (0, 0, 0), (255, 255, 255))


def test_too_long_is_refused():
    with pytest.raises(ValueError):
        qr_image("https://x.org/" + "a" * 5000, 2000, (0, 0, 0), (255, 255, 255))


def test_module_count_grows_with_length():
    assert qr_modules("https://a.b") < qr_modules(URL)


def test_text_fonts_are_bundled_and_cover_latin_and_arabic():
    """A missing glyph draws the font's .notdef box, which has a width too, so the
    check compares each character's mask with the mask of one Amiri lacks."""
    from PIL import ImageFont

    for path in (TEXT_FONT_PATH, TEXT_FONT_BOLD_PATH):
        font = ImageFont.truetype(str(path), 40)
        tofu = font.getmask("\ue000")

        def drawn(char, font=font, tofu=tofu):
            mask = font.getmask(char)
            return (mask.size, bytes(mask)) != (tofu.size, bytes(tofu))

        assert not drawn("Д")  # the check does see a missing glyph
        for char in "DarsAhmdé…،–٤٩دروسمحمدجزاكمخيرًا":
            assert drawn(char), (path.name, char)

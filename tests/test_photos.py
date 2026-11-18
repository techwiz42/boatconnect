"""What an owner may upload as a boat's photo, and what comes out: always a small, valid JPEG with no camera data."""
import io

import pytest
from PIL import Image

from boatconnect import photos


def encode(image, fmt, **kw):
    out = io.BytesIO()
    image.save(out, format=fmt, **kw)
    return out.getvalue()


def opened(data):
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def test_a_png_with_transparency_becomes_a_jpeg_on_white():
    source = Image.new("RGBA", (50, 40), (255, 0, 0, 0))                                  # fully transparent red
    result = opened(photos.process_photo(encode(source, "PNG")))
    assert result.format == "JPEG" and result.mode == "RGB" and result.size == (50, 40)
    assert min(result.getpixel((10, 10))) > 240                                           # transparent became white, not black


def test_a_big_photo_is_scaled_down_and_keeps_its_shape():
    result = opened(photos.process_photo(encode(Image.new("RGB", (3000, 2000), (10, 80, 140)), "JPEG")))
    assert result.size == (1200, 800)


def test_a_small_photo_is_not_enlarged():
    assert opened(photos.process_photo(encode(Image.new("RGB", (300, 200), "navy"), "JPEG"))).size == (300, 200)


def test_webp_is_accepted():
    assert opened(photos.process_photo(encode(Image.new("RGB", (80, 60), "teal"), "WEBP"))).format == "JPEG"


def test_the_cameras_location_and_other_exif_data_are_dropped():
    exif = Image.Exif()
    exif[0x010F] = "Acme Camera Co"                                                       # Make
    exif[0x0110] = "Model 9"
    exif[0x0132] = "2026:11:18 09:00:00"                                                  # when it was taken
    exif[0x8825] = {1: "N", 2: (33.0, 59.0, 30.0), 3: "W", 4: (118.0, 27.0, 0.0)}        # GPS: a marina's position
    source = encode(Image.new("RGB", (60, 60), "red"), "JPEG", exif=exif)
    assert Image.open(io.BytesIO(source)).getexif(), "the test photo must carry exif for this check to mean anything"
    out = photos.process_photo(source)
    result = Image.open(io.BytesIO(out))
    assert dict(result.getexif()) == {} and result.getexif().get_ifd(0x8825) == {}
    assert b"Acme" not in out and b"Exif" not in out


def test_a_sideways_phone_photo_is_turned_the_right_way_up():
    exif = Image.Exif()
    exif[0x0112] = 6                                                                      # "rotate 90 degrees to view": the pixels are stored sideways
    result = opened(photos.process_photo(encode(Image.new("RGB", (80, 40), "red"), "JPEG", exif=exif)))
    assert result.size == (40, 80)


@pytest.mark.parametrize("junk", [b"", b"not an image at all", b"<html><script>alert(1)</script></html>", b"\xff\xd8\xff\xe0 truncated jpeg", b"GIF89a" + b"\x00" * 40])
def test_something_that_is_not_a_picture_is_refused(junk):
    with pytest.raises(photos.PhotoError):
        photos.process_photo(junk)


def test_a_gif_is_refused_even_though_it_is_a_real_picture():
    with pytest.raises(photos.PhotoError, match="JPEG, PNG or WebP"):
        photos.process_photo(encode(Image.new("P", (20, 20)), "GIF"))


def test_a_small_file_that_claims_to_be_enormous_is_refused_before_it_is_decoded():
    bomb = encode(Image.new("1", (6000, 6000)), "PNG")                                    # 36 megapixels, a few KB
    assert len(bomb) < 100_000
    with pytest.raises(photos.PhotoError, match="too large"):
        photos.process_photo(bomb)

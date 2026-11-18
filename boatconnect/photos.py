"""A boat's photo: whatever image an owner uploads is checked and re-encoded as a plain JPEG, so what is stored and served is always a small, valid image.

Re-encoding is the safeguard: a file that is not really a JPEG, PNG or WebP picture is refused; the camera's location and other EXIF data are dropped (a photo of a boat at its
berth should not publish where its owner lives); a rotated phone photo is turned the right way up first; and a huge image is scaled down. Pillow is the only dependency.
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 1200                     # the longest side of the stored picture, in pixels
MAX_PIXELS = 25_000_000             # an upload larger than this is refused before it is decoded (a small file can claim to be enormous)
QUALITY = 85
ALLOWED = ["JPEG", "PNG", "WEBP"]


class PhotoError(Exception):
    """An upload that is refused; the message is safe to show the user."""


def process_photo(data: bytes) -> bytes:
    if not data:
        raise PhotoError("choose a photo to upload")
    try:
        image = Image.open(io.BytesIO(data), formats=ALLOWED)
        width, height = image.size
        if width * height > MAX_PIXELS:
            raise PhotoError("that picture is too large; choose one under about 25 megapixels")
        image.load()
    except PhotoError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise PhotoError("that file is not a JPEG, PNG or WebP picture")
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        flat = Image.new("RGB", image.size, (255, 255, 255))
        flat.paste(image, mask=image.getchannel("A"))
        image = flat
    elif image.mode != "RGB":
        image = image.convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=QUALITY, optimize=True)                     # no exif= argument: none is written
    return out.getvalue()

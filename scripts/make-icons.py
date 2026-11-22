"""Draw boatconnect's app icons (web/public/icon-*.png, apple-touch-icon.png) from the same shapes as favicon.svg. Run with the project's Python (it needs Pillow):
    .venv/bin/python scripts/make-icons.py
The "maskable" icon fills the whole square and keeps the boat inside the middle 80%, because phones crop that one to a circle or a rounded square."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "web" / "public"
NAVY, WHITE, RED = (11, 79, 124), (255, 255, 255), (232, 72, 63)
SCALE = 4                                                                    # drawn four times larger, then shrunk, for smooth edges


def draw(size: int, margin: float, rounded: bool) -> Image.Image:
    big = size * SCALE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * 12 / 64) if rounded else 0, fill=NAVY)
    inner = big * (1 - 2 * margin)
    k, o = inner / 64, big * margin                                          # the 64x64 drawing of favicon.svg, placed inside the margin
    p = lambda pts: [(o + x * k, o + y * k) for x, y in pts]
    d.polygon(p([(32, 8), (32, 44), (12, 44)]), fill=WHITE)
    d.polygon(p([(36, 14), (36, 44), (52, 44)]), fill=RED)
    d.polygon(p([(8, 48), (56, 48), (50, 56), (14, 56)]), fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    draw(192, 0.0, True).save(OUT / "icon-192.png")
    draw(512, 0.0, True).save(OUT / "icon-512.png")
    draw(512, 0.1, False).save(OUT / "icon-maskable-512.png")                 # full-bleed, boat inside the safe zone
    draw(180, 0.0, False).convert("RGB").save(OUT / "apple-touch-icon.png")    # iOS rounds the corners itself
    print("icons written to", OUT)

"""Generate simple placeholder PWA icons (no external assets needed)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "icons"
OUT.mkdir(parents=True, exist_ok=True)

BG = (11, 18, 32)       # matches theme_color
ACCENT = (56, 189, 248)  # a boat-race-ish cyan


def make_icon(size: int, maskable: bool, name: str):
    img = Image.new("RGBA", (size, size), BG + (255,))
    draw = ImageDraw.Draw(img)
    pad = size * 0.22 if maskable else size * 0.08
    # simple boat-wake glyph: a few curved-ish lines + a triangle "boat"
    cx, cy = size / 2, size / 2
    r = (size - 2 * pad) / 2
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ACCENT, width=max(2, size // 40))
    boat_w, boat_h = r * 1.1, r * 0.55
    draw.polygon([
        (cx - boat_w / 2, cy + boat_h / 3),
        (cx + boat_w / 2, cy + boat_h / 3),
        (cx, cy - boat_h * 0.9),
    ], fill=ACCENT)
    img.save(OUT / name)


make_icon(192, maskable=False, name="icon-192.png")
make_icon(512, maskable=False, name="icon-512.png")
make_icon(512, maskable=True, name="icon-512-maskable.png")
print("icons written to", OUT)

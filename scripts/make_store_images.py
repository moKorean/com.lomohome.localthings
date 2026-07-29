"""Build the app and driver store images from assets/icon.svg.

    python3 scripts/make_store_images.py

Run it after editing the icon. The images are generated rather than drawn so they
cannot drift from the icon, and the three app sizes come from one artwork rendered at
three resolutions rather than three compositions — that is what makes them identical
instead of merely similar.


The icon is stroke-based and colours itself through a <style> block with element
selectors (`path, rect, line, circle { stroke: #000 }`). CSS inside an SVG is not
scoped by nesting, so embedding that block in a composite image would also restyle the
background rect — turning it into an unfilled white-stroked outline. So the shapes are
re-emitted with the equivalent presentation attributes instead, and the icon file
itself is left exactly as authored.
"""

import re
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
# Intermediate SVGs go somewhere disposable; only the PNGs are committed.
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/localthings-store-images")
OUT.mkdir(parents=True, exist_ok=True)

BLUE = "#1428A0"
DEEP = "#0B1668"
WORDMARK = "LocalThings Community"
TAGLINE = "Samsung appliances, no cloud"

ICON = (APP / "assets/icon.svg").read_text()

# viewBox, so the glyph can be centred and scaled without assuming 512 or 960.
viewbox = re.search(r'viewBox="([\d.\s-]+)"', ICON)
VB = [float(n) for n in viewbox.group(1).split()]
SPAN = max(VB[2], VB[3])

# class -> stroke-width, read from the icon's own style block rather than hardcoded, so
# editing the icon's weights carries through here.
WIDTHS = {
    name: width
    for name, width in re.findall(r"\.(\w+)\s*\{[^}]*stroke-width:\s*([\d.]+)", ICON)
}
DEFAULT_WIDTH = re.search(r"stroke-width:\s*([\d.]+)", ICON)
DEFAULT_WIDTH = DEFAULT_WIDTH.group(1) if DEFAULT_WIDTH else "40"


def glyph() -> str:
    """The icon's shapes with white strokes, as presentation attributes."""
    out = []
    for tag, attrs in re.findall(r"<(path|rect|line|circle|polyline|polygon)\s([^/>]*)/?>", ICON):
        klass = re.search(r'class="(\w+)"', attrs)
        width = WIDTHS.get(klass.group(1) if klass else "", DEFAULT_WIDTH)
        cleaned = re.sub(r'\sclass="\w+"', "", attrs).strip()
        out.append(
            f'<{tag} {cleaned} fill="none" stroke="#FFFFFF" stroke-width="{width}"'
            f' stroke-linecap="round" stroke-linejoin="round"/>'
        )
    return "\n    ".join(out)


GLYPH = glyph()


def scene(width: int, height: int, *, wordmark: bool, glyph_height: float,
          glyph_cy: float) -> str:
    """One store image.

    `glyph_height` is the glyph's height as a fraction of the image height, so the
    composition is defined in proportions and survives being rendered at any size.
    """
    scale = (height * glyph_height) / SPAN
    x = width / 2 - SPAN * scale / 2 - VB[0] * scale
    y = glyph_cy - SPAN * scale / 2 - VB[1] * scale
    words = ""
    if wordmark:
        title = height * 0.105
        sub = height * 0.058
        # Baselines sit just under the glyph: the wordmark reads as part of the mark
        # rather than as a separate block at the bottom of the frame.
        title_y = glyph_cy + SPAN * scale / 2 + title * 0.92
        words = f"""
  <text x="{width / 2}" y="{title_y}" text-anchor="middle"
        font-family="Helvetica Neue, Helvetica, Arial, sans-serif"
        font-size="{title}" font-weight="600" fill="#FFFFFF">{WORDMARK}</text>
  <text x="{width / 2}" y="{title_y + sub * 1.5}" text-anchor="middle"
        font-family="Helvetica Neue, Helvetica, Arial, sans-serif"
        font-size="{sub}" fill="#FFFFFF" opacity="0.76">{TAGLINE}</text>"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"
     viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{BLUE}"/>
      <stop offset="1" stop-color="{DEEP}"/>
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" fill="url(#bg)"/>
  <g transform="translate({x} {y}) scale({scale})">
    {GLYPH}
  </g>{words}
</svg>
"""


def render(svg: str, width: int, height: int, destination: Path) -> None:
    source = OUT / f"{destination.parent.parent.parent.name}-{destination.stem}.svg"
    source.write_text(svg)
    subprocess.run(
        ["rsvg-convert", "-w", str(width), "-h", str(height), str(source),
         "-o", str(destination)],
        check=True,
    )
    print(f"  {destination.relative_to(APP)}  {width}x{height}")


print(f"glyph: {len(GLYPH.splitlines())} shapes, widths {WIDTHS}")
print("app images (landscape cards):")
app_dir = APP / "assets/images"
# All three app sizes are 10:7, so one artwork is rendered at three resolutions
# rather than composed three times. That is what makes them genuinely identical
# instead of merely similar.
# glyph_cy chosen so the glyph-plus-text block is optically centred: text carries
# more visual weight than an outline, so the block sits a little above true centre.
ART = scene(1000, 700, wordmark=True, glyph_height=0.44, glyph_cy=283)
for name, (w, h) in {
    "small": (250, 175),
    "large": (500, 350),
    "xlarge": (1000, 700),
}.items():
    render(ART, w, h, app_dir / f"{name}.png")

print("driver images (square):")
driver_dir = APP / "drivers/appliance/assets/images"
render(scene(75, 75, wordmark=False, glyph_height=0.76, glyph_cy=37.5),
       75, 75, driver_dir / "small.png")
render(scene(500, 500, wordmark=False, glyph_height=0.72, glyph_cy=250),
       500, 500, driver_dir / "large.png")
render(scene(1000, 1000, wordmark=False, glyph_height=0.72, glyph_cy=500),
       1000, 1000, driver_dir / "xlarge.png")

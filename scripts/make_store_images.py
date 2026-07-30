"""Build the app store images.

    python3 scripts/make_store_images.py

The three app sizes are all 10:7, so one artwork is rendered at three resolutions
rather than composed three times — that is what makes them identical instead of
merely similar. Driver images are a different shape and rule; see
make_driver_images.py.

The card shows the appliance group and nothing else. Guideline 1.4 rejects an app
image that is "a single flat shape or icon on a plain, monochrome or transparent
background" and says to avoid "logos, clipart, or icon-type images", which the
original icon-on-gradient version was exactly.

**No text.** An earlier version set the app name and a tagline into the artwork, and
review rejected it: rendered text makes the image read as a marketing card rather
than as a representative picture of what the app does. The name is already shown
beside the image by the store. The group is shared with the driver images so the two
cannot drift apart.
"""

import subprocess
import sys
from pathlib import Path

from appliances_svg import DEFS, GROUP, INK_BOTTOM, INK_HEIGHT, INK_LEFT, INK_TOP, INK_WIDTH

APP = Path(__file__).resolve().parent.parent
# Intermediate SVGs go somewhere disposable; only the PNGs are committed.
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/localthings-store-images")
OUT.mkdir(parents=True, exist_ok=True)

BLUE = "#1428A0"
DEEP = "#0B1668"

SIZES = {"small": (250, 175), "large": (500, 350), "xlarge": (1000, 700)}

# Proportions of the frame height, so the composition survives any render size. With
# the text gone the group is the whole subject, so it takes most of the frame instead
# of sharing it — a small illustration floating in a large gradient reads as a logo,
# which is the other thing 1.4 rejects.
GROUP_HEIGHT = 0.74
GROUP_TOP = 0.13


def card(width: int, height: int) -> str:
    group_height = height * GROUP_HEIGHT
    scale = group_height / INK_HEIGHT
    top = height * GROUP_TOP
    # Place the group's *ink* rather than its 1000x1000 canvas: the canvas has uneven
    # margins, so centring it would leave the group visibly off-centre.
    x = width / 2 - (INK_LEFT + INK_WIDTH / 2) * scale
    y = top - INK_TOP * scale

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"
     viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{BLUE}"/>
      <stop offset="1" stop-color="{DEEP}"/>
    </linearGradient>{DEFS}  </defs>
  <rect width="{width}" height="{height}" fill="url(#bg)"/>
  <g transform="translate({x:.2f} {y:.2f}) scale({scale:.5f})">{GROUP}  </g>
</svg>
"""


def render(svg: str, width: int, height: int, destination: Path) -> None:
    source = OUT / f"app-{destination.stem}.svg"
    source.write_text(svg)
    subprocess.run(
        ["rsvg-convert", "-w", str(width), "-h", str(height), str(source),
         "-o", str(destination)],
        check=True,
    )
    print(f"  {destination.relative_to(APP)}  {width}x{height}")


if __name__ == "__main__":
    print("app images (landscape cards):")
    art = card(1000, 700)
    for name, (w, h) in SIZES.items():
        render(art, w, h, APP / "assets/images" / f"{name}.png")
    print(f"  ink placed from y={INK_TOP} to y={INK_BOTTOM} of the shared group")

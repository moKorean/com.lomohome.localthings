"""Build the app store images.

    python3 scripts/make_store_images.py

The three app sizes are all 10:7, so one artwork is rendered at three resolutions
rather than composed three times — that is what makes them identical instead of
merely similar. Driver images are a different shape and rule; see
make_driver_images.py.

The card shows the appliance group, not the app's mark. Guideline 1.4 rejects an
app image that is "a single flat shape or icon on a plain, monochrome or
transparent background" and says to avoid "logos, clipart, or icon-type images" —
which the earlier icon-on-gradient version was exactly. The group is shared with
the driver images so the two cannot drift apart.
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
WORDMARK = "LocalThings Community"
TAGLINE = "Samsung appliances, no cloud"

SIZES = {"small": (250, 175), "large": (500, 350), "xlarge": (1000, 700)}

# Proportions of the frame height, so the composition survives any render size.
GROUP_HEIGHT = 0.545   # appliance group
TITLE_SIZE = 0.105
TAGLINE_SIZE = 0.058
GROUP_TOP = 0.121
TITLE_GAP = 0.92       # multiples of the title size below the group's baseline
TAGLINE_GAP = 1.5      # multiples of the tagline size below the title baseline


def card(width: int, height: int) -> str:
    group_height = height * GROUP_HEIGHT
    scale = group_height / INK_HEIGHT
    top = height * GROUP_TOP
    # Place the group's *ink* rather than its 1000x1000 canvas: the canvas has
    # uneven margins, so centring it would leave the group visibly off-centre.
    x = width / 2 - (INK_LEFT + INK_WIDTH / 2) * scale
    y = top - INK_TOP * scale

    title = height * TITLE_SIZE
    tagline = height * TAGLINE_SIZE
    # Baselines sit just under the group, so the text reads as part of the image
    # rather than as a separate block at the bottom of the frame.
    title_y = top + group_height + title * TITLE_GAP
    tagline_y = title_y + tagline * TAGLINE_GAP

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"
     viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{BLUE}"/>
      <stop offset="1" stop-color="{DEEP}"/>
    </linearGradient>{DEFS}  </defs>
  <rect width="{width}" height="{height}" fill="url(#bg)"/>
  <g transform="translate({x:.2f} {y:.2f}) scale({scale:.5f})">{GROUP}  </g>
  <text x="{width / 2}" y="{title_y:.1f}" text-anchor="middle"
        font-family="Helvetica Neue, Helvetica, Arial, sans-serif"
        font-size="{title:.1f}" font-weight="600" fill="#FFFFFF">{WORDMARK}</text>
  <text x="{width / 2}" y="{tagline_y:.1f}" text-anchor="middle"
        font-family="Helvetica Neue, Helvetica, Arial, sans-serif"
        font-size="{tagline:.1f}" fill="#FFFFFF" opacity="0.78">{TAGLINE}</text>
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

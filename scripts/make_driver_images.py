#!/usr/bin/env python3
"""Build the driver store images: a group of appliances on white.

    python3 scripts/make_driver_images.py

App Store guideline 1.4: "Driver images should have white background with
recognizable device pictures." The group itself is in appliances_svg, shared with
the app images so the two cannot drift apart.

One artwork rendered at the three required sizes rather than three compositions,
which is what makes them genuinely identical instead of merely similar.
"""

import subprocess
import sys
from pathlib import Path

from appliances_svg import DEFS, GROUP, SHADOW

APP = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/localthings-driver-images")
OUT.mkdir(parents=True, exist_ok=True)

SIZES = {"small": 75, "large": 500, "xlarge": 1000}

ARTWORK = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000"
     viewBox="0 0 1000 1000">
  <defs>{DEFS}</defs>
  <rect width="1000" height="1000" fill="#FFFFFF"/>
  <!-- Contact shadow, drawn before the units so they stand on it. -->
  {SHADOW}
{GROUP}
</svg>
"""


def render(size: int, destination: Path) -> None:
    source = OUT / "driver-artwork.svg"
    source.write_text(ARTWORK)
    subprocess.run(
        ["rsvg-convert", "-w", str(size), "-h", str(size), str(source),
         "-o", str(destination)],
        check=True,
    )
    print(f"  {destination.relative_to(APP)}  {size}x{size}")


if __name__ == "__main__":
    print("driver images (appliances on white):")
    directory = APP / "drivers/appliance/assets/images"
    for name, size in SIZES.items():
        render(size, directory / f"{name}.png")

"""LocalThings — local control of Samsung appliances from Homey.

Copyright 2026, Geunwon Mo (mokorean@gmail.com)

A Homey port of the LocalThings Home Assistant integration
(https://github.com/mbillow/localthings). Talks CoAP-over-DTLS straight to
the appliance on the LAN, so nothing round-trips through SmartThings.

The transport layer comes from the `smartthings-local` package declared in
app.json's `pythonPackages`; see docs/PORTING.md for the design.
"""

import sys
from pathlib import Path

# The Homey runner may not put the app directory on sys.path.
sys.path.insert(0, str(Path(__file__).parent))

from homey import app as homey_app  # noqa: E402


class LocalThingsApp(homey_app.App):
    async def on_init(self) -> None:
        self.log("LocalThings app is running...")


homey_export = LocalThingsApp

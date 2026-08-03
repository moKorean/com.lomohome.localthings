"""LocalThings — local control of Samsung appliances from Homey.

Copyright 2026, Geunwon Mo (mokorean@gmail.com)

A Homey port of the LocalThings Home Assistant integration
(https://github.com/mbillow/localthings). Talks CoAP-over-DTLS straight to
the appliance on the LAN, so nothing round-trips through SmartThings.

The transport layer comes from the `smartthings-local` package declared in
app.json's `pythonPackages`; see docs/PORTING.md for the design.
"""

import json
import sys
from pathlib import Path

# The Homey runner may not put the app directory on sys.path.
sys.path.insert(0, str(Path(__file__).parent))

from homey import app as homey_app

from lib import cert, compat, credentials, selfcheck
from lib.const import SETTING_PAIR_ENV, SETTING_UI_LANGUAGE


class LocalThingsApp(homey_app.App):
    async def on_init(self) -> None:
        selfcheck.run(self.log)
        await self._seed_ui_language()
        await self._ensure_credentials()
        self.log("LocalThings app is running...")

    async def _ensure_credentials(self) -> None:
        """Issue a client certificate on first run, so setup needs no other machine.

        Only when nothing is stored. A certificate the user pasted is never
        replaced by one issued here — that is what `SETTING_CERT_SOURCE` is for,
        and the appliance prefers neither, since what it checks is the UUID.

        Never fatal. The UUID comes from Samsung's gateway over the internet, so
        this fails on a Homey that has no route out yet; the settings page can
        issue one on demand later, and pasting still works regardless.
        """
        try:
            if await credentials.stored(self.homey):
                return
            self.log("No client certificate stored — issuing one")
            uuid = await compat.run(cert.fetch_samsung_uuid)
            info = await credentials.issue(self.homey, uuid)
            self.log(
                f"Client certificate issued for uuid:{info['uuid']} "
                f"(expires {info['expires']})"
            )
        except Exception as exc:
            self.log(
                f"Could not issue a client certificate ({type(exc).__name__}: {exc}). "
                "Open the app settings to issue one or paste your own."
            )

    async def _seed_ui_language(self) -> None:
        """Recover the UI language from an earlier pairing session if it is unset.

        Messages raised from Python need the user's language, and Homey's Python i18n
        reports the app's instead, so a webview has to tell us. Without this the first
        message after an upgrade would be in English until some view happened to be
        opened — but the language a view already resolved is sitting in the stored
        pairing-environment report, so use that.
        """
        if await compat.setting_get(self.homey, SETTING_UI_LANGUAGE):
            return
        raw = await compat.setting_get(self.homey, SETTING_PAIR_ENV)
        if not raw:
            return
        try:
            reported = json.loads(raw).get("resolved")
        except Exception:
            return
        if reported:
            await compat.remember_ui_language(self.homey, reported)
            self.log(f"UI language recovered from a previous session: {reported}")


homey_export = LocalThingsApp

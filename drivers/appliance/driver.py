"""Pairing for Samsung appliances.

Mirrors the reference integration's config flow: the CA is asked for once and
stored app-wide, every appliance after that needs only an IP. The app mints that
device's own leaf cert from the stored CA, sweeps for the live DTLS port, and
confirms the device answers /device/0 before creating anything.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from homey import driver  # noqa: E402

from lib import cert, probe, registry  # noqa: E402
from lib.const import (  # noqa: E402
    SETTING_CA_CERT,
    SETTING_CA_KEY,
    STORE_HOST,
    STORE_LEAF_CERT,
    STORE_LEAF_KEY,
    STORE_PORT,
    STORE_SERIAL,
)
from lib.resources import read_identity  # noqa: E402


class Driver(driver.Driver):

    async def on_init(self) -> None:
        self.log("LocalThings appliance driver init")

    # --- pairing ----------------------------------------------------------

    async def on_pair(self, session) -> None:
        session.set_handler("get_state", self._on_get_state)
        session.set_handler("save_ca", self._on_save_ca)
        session.set_handler("probe", self._on_probe)

    async def _on_get_state(self, data=None, **_) -> dict:
        """Tell the view whether the CA is already stored, so it can skip
        straight to asking for an IP for every appliance after the first."""
        return {
            "has_ca": bool(self._stored_ca()[0] and self._stored_ca()[1]),
            "language": self.homey.i18n.get_language(),
        }

    def _stored_ca(self) -> tuple[str, str]:
        return (
            self.homey.settings.get(SETTING_CA_CERT) or "",
            self.homey.settings.get(SETTING_CA_KEY) or "",
        )

    async def _on_save_ca(self, data=None, **_) -> dict:
        """Validate the pasted CA before storing it.

        Validating here means a mistyped or mismatched paste is reported as such,
        instead of surfacing later as an opaque DTLS handshake failure.
        """
        ca_cert = (data or {}).get("ca_cert_pem", "").strip()
        ca_key = (data or {}).get("ca_key_pem", "").strip()
        if not ca_cert or not ca_key:
            raise ValueError("Both the CA certificate and the CA private key are required")

        await self._run(cert.validate_ca, ca_cert, ca_key)

        self.homey.settings.set(SETTING_CA_CERT, ca_cert)
        self.homey.settings.set(SETTING_CA_KEY, ca_key)
        self.log("CA credentials stored")
        return {"ok": True}

    async def _on_probe(self, data=None, **_) -> dict:
        """Mint a leaf for this host, find the port, read /device/0."""
        host = (data or {}).get("host", "").strip()
        if not host:
            raise ValueError("An IP address is required")

        ca_cert, ca_key = self._stored_ca()
        if not ca_cert or not ca_key:
            raise ValueError("No CA credentials stored yet")

        self.log(f"probing {host}")
        uuid = await self._run(cert.fetch_samsung_uuid)
        leaf_cert, leaf_key = await self._run(cert.mint_leaf, ca_cert, ca_key, uuid)
        result = await self._run(probe.probe, host, leaf_cert, leaf_key)

        resources = result["resources"]
        reg = registry.resolve(resources)
        identity = read_identity(resources)
        model = identity["model"].split("|")[0] or identity["description"]

        if reg is None:
            # Deliberately not a hard failure: the device is reachable and its
            # dump is what a maintainer needs to add support. Report the model so
            # the user can file it rather than seeing a bare "unsupported".
            gaps = sorted(resources)
            self.log(f"unrecognised appliance {model}; {len(gaps)} resources")
            return {
                "recognised": False,
                "model": model,
                "resource_count": len(gaps),
            }

        capabilities = reg.capabilities(resources)
        unbound = registry.unbound_hrefs(resources, reg)
        self.log(
            f"{model} -> {reg.name}, {len(capabilities)} capabilities, "
            f"{len(unbound)} unbound resources"
        )

        return {
            "recognised": True,
            "model": model,
            "registry": reg.name,
            "capability_count": len(capabilities),
            "device": {
                "name": f"Samsung {reg.name.replace('_', ' ').title()} ({host})",
                "data": {"id": result["serial"]},
                "store": {
                    STORE_HOST: host,
                    STORE_PORT: result["port"],
                    STORE_SERIAL: result["serial"],
                    STORE_LEAF_CERT: leaf_cert,
                    STORE_LEAF_KEY: leaf_key,
                },
                "settings": {
                    "host": host,
                    "port": str(result["port"]),
                    "model": model,
                    "poll_interval": 30,
                },
                "capabilities": capabilities,
                "class": reg.device_class,
            },
        }

    async def _run(self, fn, *args):
        """Everything in lib/ is blocking; keep it off the event loop."""
        import asyncio

        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


homey_export = Driver

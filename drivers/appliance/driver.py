"""Pairing for Samsung appliances.

The client certificate is configured once in the app settings, so pairing only
needs an IP address. Before creating anything, the driver sweeps for the live DTLS
port and confirms the appliance answers /device/0 — a device that appears in Homey
has demonstrably been talked to.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from homey import driver  # noqa: E402

from lib import compat, probe, registry  # noqa: E402
from lib.const import (  # noqa: E402
    SETTING_LEAF_CERT,
    SETTING_LEAF_KEY,
    STORE_HOST,
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
        session.set_handler("probe", self._on_probe)

    async def _credentials(self) -> tuple[str, str]:
        return (
            await compat.setting_get(self.homey, SETTING_LEAF_CERT),
            await compat.setting_get(self.homey, SETTING_LEAF_KEY),
        )

    async def _on_get_state(self, data=None, **_) -> dict:
        """Lets the view send the user to app settings instead of failing at
        Connect when no certificate has been configured yet."""
        cert_pem, key_pem = await self._credentials()
        language = await compat.language(self.homey)
        # Logged because "the certificate is stored but pairing says otherwise"
        # is otherwise indistinguishable from "it was never stored".
        self.log(
            f"pair get_state: cert={len(cert_pem)}B key={len(key_pem)}B "
            f"language={language}"
        )
        return {
            "has_credentials": bool(cert_pem and key_pem),
            "language": language,
        }

    async def _on_probe(self, data=None, **_) -> dict:
        host = (data or {}).get("host", "").strip()
        if not host:
            raise ValueError("An IP address is required")

        cert_pem, key_pem = await self._credentials()
        if not cert_pem or not key_pem:
            raise ValueError(
                "No client certificate configured. Set one up in "
                "Settings -> Apps -> LocalThings first."
            )

        self.log(f"probing {host}")
        result = await self._run(probe.probe, host, cert_pem, key_pem)

        resources = result["resources"]
        reg = registry.resolve(resources)
        identity = read_identity(resources)
        model = identity["model"].split("|")[0] or identity["description"]

        if reg is None:
            # Deliberately not a hard error: the appliance is reachable, and its
            # model number is what adding support needs. Report it instead of a
            # bare failure.
            self.log(f"unrecognised appliance {model}, {len(resources)} resources")
            return {
                "recognised": False,
                "model": model,
                "resource_count": len(resources),
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
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


homey_export = Driver

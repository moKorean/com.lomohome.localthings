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

from lib import compat, discovery, probe, registry  # noqa: E402
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
        self._log_sdk_surface()
        await self._log_language_probe()

    def _log_sdk_surface(self) -> None:
        """One-time dump of what this SDK build actually exposes.

        The Python SDK's surface is only partly documented and the i18n accessor
        guessed at in lib/compat.py resolves to nothing on this firmware, so log
        the real attribute names instead of guessing again.
        """
        try:
            names = sorted(a for a in dir(self.homey) if not a.startswith("_"))
            self.log(f"sdk homey: {names}")
            for attr in ("i18n", "settings", "app", "arp", "discovery", "api"):
                target = getattr(self.homey, attr, None)
                if target is None:
                    self.log(f"sdk homey.{attr}: absent")
                    continue
                members = sorted(a for a in dir(target) if not a.startswith("_"))
                self.log(f"sdk homey.{attr}: {members}")
        except Exception as exc:
            self.log(f"sdk surface dump failed: {exc}")

    async def _log_language_probe(self) -> None:
        """Log what each language accessor actually returns.

        get_language exists on this build, yet compat.language() still fell back
        to English — so the accessor is returning something unexpected rather than
        being absent, and only the raw value shows which.
        """
        import inspect as _inspect

        for label, get in (
            ("i18n.get_language", lambda: self.homey.i18n.get_language()),
            ("i18n.get_strings", lambda: self.homey.i18n.get_strings()),
            ("manifest.name", lambda: self.homey.manifest.get("name")),
        ):
            try:
                raw = get()
                awaited = None
                if _inspect.isawaitable(raw):
                    awaited = await raw
                self.log(
                    f"lang probe {label}: raw={type(raw).__name__} {raw!r:.120} "
                    f"awaited={type(awaited).__name__} {awaited!r:.120}"
                )
            except Exception as exc:
                self.log(f"lang probe {label}: raised {type(exc).__name__}: {exc}")

    # --- pairing ----------------------------------------------------------

    async def on_pair(self, session) -> None:
        session.set_handler("get_state", self._on_get_state)
        session.set_handler("discover", self._on_discover)
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

    def _paired_hosts(self) -> set:
        """Addresses already paired, so discovery doesn't offer them again."""
        hosts = set()
        try:
            for device in self.get_devices():
                try:
                    host = (device.get_store() or {}).get(STORE_HOST)
                except Exception:
                    host = None
                if host:
                    hosts.add(host)
        except Exception:
            # Not worth failing discovery over; worst case is offering something
            # that is already added.
            pass
        return hosts

    async def _on_discover(self, data=None, **_) -> dict:
        """Sweep the subnet, then identify each responder.

        Two stages because they cost very differently: the sweep rules out a whole
        /24 in seconds, while identifying one device needs a full DTLS handshake
        and a /device/0 read. Only addresses that answered get that treatment.
        """
        cert_pem, key_pem = await self._credentials()
        if not cert_pem or not key_pem:
            raise ValueError(
                "No client certificate configured. Set one up in "
                "Settings -> Apps -> LocalThings community first."
            )
        language = ((data or {}).get("language") or "").strip() or await compat.language(
            self.homey
        )

        paired = self._paired_hosts()
        base, own = discovery.local_subnet()
        self.log(
            f"discovery sweeping {base}.0/24 (own {own}, {len(paired)} already paired)"
        )
        candidates = await discovery.sweep(skip=paired)
        self.log(f"discovery: {len(candidates)} responded: {[h for h, _ in candidates]}")

        if not candidates:
            return {"appliances": [], "scanned": f"{base}.0/24"}

        # Identified one at a time: each is a separate DTLS handshake to a
        # different appliance, and the firmware is rate-limit sensitive enough
        # that parallelising isn't worth the saved seconds.
        appliances = []
        for host, port in candidates:
            try:
                appliances.append(
                    await self._identify(host, cert_pem, key_pem, language)
                )
            except Exception as exc:
                self.log(f"discovery: {host}:{port} not identified: {exc}")

        self.log(f"discovery identified {len(appliances)} of {len(candidates)}")
        return {"appliances": appliances, "scanned": f"{base}.0/24"}

    async def _identify(self, host: str, cert_pem: str, key_pem: str,
                        language: str) -> dict:
        """Probe one address and describe what it is."""
        result = await self._run(probe.probe, host, cert_pem, key_pem)
        resources = result["resources"]
        reg = registry.resolve(resources)
        identity = read_identity(resources)
        entry = {
            "host": host,
            "port": result["port"],
            "model": identity["model"].split("|")[0] or identity["description"],
            "recognised": reg is not None,
            "resource_count": len(resources),
        }
        if reg is not None:
            entry["registry"] = reg.name
            entry["title"] = reg.title(language)
            entry["capability_count"] = len(reg.capabilities(resources))
            entry["device"] = self._device_payload(host, result, reg, language)
        return entry

    def _device_payload(self, host: str, result: dict, reg, language: str) -> dict:
        """The createDevice payload. Shared by discovery and manual entry so the
        two cannot drift apart."""
        resources = result["resources"]
        identity = read_identity(resources)
        model = identity["model"].split("|")[0] or identity["description"]
        return {
            "name": f"{reg.title(language)} ({host})",
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
            "capabilities": reg.capabilities(resources),
            "class": reg.device_class,
        }

    async def _on_probe(self, data=None, **_) -> dict:
        data = data or {}
        host = (data.get("host") or "").strip()
        if not host:
            raise ValueError("An IP address is required")

        # The view resolves the language from its own Homey object, which works;
        # the Python i18n accessors do not on this firmware (see
        # _log_sdk_surface). Prefer what the view reports and keep the Python
        # lookup as the fallback.
        language = (data.get("language") or "").strip() or await compat.language(self.homey)

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
            "device": self._device_payload(host, result, reg, language),
        }

    async def _run(self, fn, *args):
        """Everything in lib/ is blocking; keep it off the event loop."""
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


homey_export = Driver

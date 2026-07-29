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

from homey import driver

from lib import cert, compat, discovery, probe, registry
from lib.const import (
    SETTING_LEAF_CERT,
    SETTING_LEAF_KEY,
    SETTING_PAIR_ENV,
    STORE_HOST,
    STORE_PORT,
    STORE_SERIAL,
)
from lib.resources import read_identity


class Driver(driver.Driver):

    async def on_init(self) -> None:
        self.log("LocalThings appliance driver init")
        try:
            card = self.homey.flow.get_condition_card("is_pushing")
            card.register_run_listener(self._on_is_pushing)
        except Exception as exc:
            self.log(f"registering flow cards failed: {exc}")

    async def _on_is_pushing(self, card_arguments, **_) -> bool:
        device = (card_arguments or {}).get("device")
        return bool(device is not None and device.is_pushing())

    # --- pairing ----------------------------------------------------------

    async def on_pair(self, session) -> None:
        self._session = session
        session.set_handler("get_state", self._on_get_state)
        session.set_handler("report_env", self._on_report_env)
        session.set_handler("discover_start", self._on_discover_start)
        session.set_handler("discover_status", self._on_discover_status)
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

    def _paired_identity(self) -> tuple[set, set]:
        """(hosts, serials) already paired.

        Both are needed. The host skips the sweep cheaply, but a device whose
        address changed via DHCP would still answer on a new one, and the serial is
        what actually identifies it — it is the device's data id, so pairing the
        same unit twice is impossible anyway; offering it is just misleading.
        """
        hosts, serials = set(), set()
        try:
            devices = self.get_devices()
        except Exception:
            return hosts, serials
        for device in devices:
            try:
                store = device.get_store() or {}
            except Exception:
                store = {}
            host = store.get(STORE_HOST)
            if host:
                hosts.add(str(host))
            serial = store.get(STORE_SERIAL)
            if serial:
                serials.add(str(serial))
            try:
                data_id = (device.get_data() or {}).get("id")
            except Exception:
                data_id = None
            if data_id:
                serials.add(str(data_id))
        return hosts, serials

    # Discovery runs as a background job polled by the view, not as one call.
    # Homey.emit has a hard 30s timeout and a full scan takes one to two minutes,
    # so a synchronous handler cannot finish — the same constraint the reference
    # Python app hits with its settings API. Polling also lets appliances appear as
    # they are identified instead of all at once at the end.

    def _reset_discovery(self) -> None:
        self._discovery = {
            "running": True,
            "phase": "sweeping",
            "host": None,
            "index": 0,
            "total": 0,
            "appliances": [],
            "unidentified": [],
            "scanned": None,
            "error": None,
        }

    async def _on_discover_start(self, data=None, **_) -> dict:
        state = getattr(self, "_discovery", None)
        if state and state.get("running"):
            # Already scanning — hand back the live state rather than starting a
            # second sweep over the same subnet.
            return self._snapshot()

        cert_pem, key_pem = await self._credentials()
        if not cert_pem or not key_pem:
            raise ValueError(
                "No client certificate configured. Set one up in "
                "Settings -> Apps -> LocalThings community first."
            )
        language = ((data or {}).get("language") or "").strip() or await compat.language(
            self.homey
        )
        self._reset_discovery()
        # Held in an attribute: a task referenced only by the loop's transient set can
        # be garbage-collected, which would abandon a scan halfway with the view still
        # polling a job that no longer runs.
        self._discovery_task = asyncio.create_task(
            self._run_discovery(cert_pem, key_pem, language)
        )
        return self._snapshot()

    async def _on_discover_status(self, data=None, **_) -> dict:
        return self._snapshot()

    def _snapshot(self) -> dict:
        state = getattr(self, "_discovery", None) or {"running": False}
        return dict(state)

    async def _run_discovery(self, cert_pem: str, key_pem: str, language: str) -> None:
        state = self._discovery
        try:
            paired, paired_serials = self._paired_identity()
            base, own = discovery.local_subnet()
            state["scanned"] = f"{base}.0/24"
            self.log(
                f"discovery sweeping {base}.0/24 "
                f"(own {own}, {len(paired)} already paired)"
            )
            candidates = await discovery.sweep(skip=paired)
            self.log(
                f"discovery: {len(candidates)} responded: {[h for h, _ in candidates]}"
            )

            state["phase"] = "identifying"
            state["total"] = len(candidates)

            for index, (host, port) in enumerate(candidates, start=1):
                state["index"] = index
                state["host"] = host
                try:
                    entry = await self._identify(host, cert_pem, key_pem, language)
                except Exception as exc:
                    self.log(f"discovery: {host}:{port} not identified: {exc}")
                    # Reported rather than dropped. A responder that will not complete
                    # a handshake is usually another vendor's DTLS device, but it can
                    # also be a Samsung appliance this app cannot talk to, and the
                    # user can only tell those apart with the hint.
                    state["unidentified"].append({
                        "host": host,
                        "port": port,
                        "reason": str(exc)[:200],
                        **await self._vendor_hint(host),
                    })
                    continue
                # Re-checked here rather than trusting the pre-sweep host list: a
                # device created moments ago may not be back from get_devices() yet,
                # which is how an already-added appliance can reappear in a repeat
                # scan. The serial settles it.
                if entry.get("serial") and entry["serial"] in paired_serials:
                    self.log(f"discovery: {host} already paired ({entry['serial']})")
                    continue
                # Appended as it lands, so the view can show it immediately.
                state["appliances"].append(entry)

            self.log(
                f"discovery identified {len(state['appliances'])} of {len(candidates)}"
            )
        except Exception as exc:
            state["error"] = str(exc)
            self.log(f"discovery failed: {exc}")
        finally:
            state["phase"] = "done"
            state["host"] = None
            state["running"] = False

    async def _vendor_hint(self, host: str) -> dict:
        """MAC prefix for a host, via Homey's ARP lookup. Best effort."""
        try:
            mac = self.homey.arp.get_mac(host)
            if hasattr(mac, "__await__"):
                mac = await mac
        except Exception:
            return {"oui": "", "is_samsung": None}
        return discovery.vendor_hint(mac)

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
            "serial": result["serial"],
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
                "serial": str(result["serial"]),
                "status": "",
                "poll_interval": 30,
            },
            "capabilities": reg.capabilities(resources),
            "capabilitiesOptions": reg.capability_options(resources, language),
            "class": reg.device_class,
        }

    # --- repair -----------------------------------------------------------
    #
    # Three things break a working device and none of them should need re-pairing,
    # because the appliance is the same appliance: the certificate expires, the
    # address changes in a way automatic relocation could not resolve, or the unit
    # was simply unreachable when Homey last tried.

    async def on_repair(self, session, device=None) -> None:
        self._repair_device = device
        session.set_handler("repair_state", self._on_repair_state)
        session.set_handler("repair_test", self._on_repair_test)
        session.set_handler("repair_find", self._on_repair_find)
        session.set_handler("repair_host", self._on_repair_host)

    def _repair_target(self, data=None):
        """The device being repaired.

        Taken from on_repair where the SDK provides it, and from the handler payload
        otherwise — the argument's presence is not something this app can rely on
        across SDK versions.
        """
        device = getattr(self, "_repair_device", None)
        if device is not None:
            return device
        device_id = (data or {}).get("device_id")
        if device_id:
            for candidate in self.get_devices():
                try:
                    if candidate.get_data().get("id") == device_id:
                        return candidate
                except Exception:
                    continue
        raise ValueError("Could not tell which device is being repaired")

    async def _on_repair_state(self, data=None, **_) -> dict:
        device = self._repair_target(data)
        store = device.get_store() or {}
        cert_pem, key_pem = await self._credentials()
        certificate = {"configured": bool(cert_pem and key_pem)}
        if certificate["configured"]:
            try:
                certificate.update(await self._run(cert.inspect_leaf, cert_pem, key_pem))
                certificate["valid"] = True
            except cert.InvalidCredentials as exc:
                certificate.update({"valid": False, "error": str(exc)})
        return {
            "language": await compat.language(self.homey),
            "name": device.get_name(),
            "host": store.get(STORE_HOST),
            "port": store.get(STORE_PORT),
            "serial": store.get(STORE_SERIAL),
            "available": bool(device.get_available()),
            "certificate": certificate,
        }

    async def _on_repair_test(self, data=None, **_) -> dict:
        """Read /device/0 at the stored address and confirm it is still this unit.

        Reporting a serial mismatch matters as much as reporting a failure: it is the
        case where everything looks connected but the device is driving a different
        appliance.
        """
        device = self._repair_target(data)
        store = device.get_store() or {}
        host = store.get(STORE_HOST)
        cert_pem, key_pem = await self._credentials()
        if not cert_pem or not key_pem:
            return {"ok": False, "reason": "no_credentials"}
        try:
            result = await self._run(probe.probe, host, cert_pem, key_pem)
        except Exception as exc:
            return {"ok": False, "reason": "unreachable", "detail": str(exc)[:200]}

        expected = str(store.get(STORE_SERIAL) or "")
        found = str(result["serial"])
        if expected and ":" not in expected and found != expected:
            return {"ok": False, "reason": "wrong_device",
                    "expected": expected, "found": found, "host": host}
        return {"ok": True, "host": host, "port": result["port"], "serial": found}

    async def _on_repair_find(self, data=None, **_) -> dict:
        """Sweep for this appliance by serial and re-point the device at it."""
        device = self._repair_target(data)
        store = device.get_store() or {}
        serial = str(store.get(STORE_SERIAL) or "")
        if not serial or ":" in serial:
            return {"ok": False, "reason": "no_serial"}
        cert_pem, key_pem = await self._credentials()
        if not cert_pem or not key_pem:
            return {"ok": False, "reason": "no_credentials"}

        for host, _port in await discovery.sweep():
            try:
                result = await self._run(probe.probe, host, cert_pem, key_pem)
            except Exception:
                continue
            if str(result["serial"]) != serial:
                continue
            await self._repoint(device, host, result["port"])
            return {"ok": True, "host": host, "port": result["port"]}
        return {"ok": False, "reason": "not_found"}

    async def _on_repair_host(self, data=None, **_) -> dict:
        """Re-point at an address the user supplies, after checking it is this unit."""
        device = self._repair_target(data)
        host = ((data or {}).get("host") or "").strip()
        if not host:
            raise ValueError("An IP address is required")
        cert_pem, key_pem = await self._credentials()
        if not cert_pem or not key_pem:
            return {"ok": False, "reason": "no_credentials"}
        try:
            result = await self._run(probe.probe, host, cert_pem, key_pem)
        except Exception as exc:
            return {"ok": False, "reason": "unreachable", "detail": str(exc)[:200]}

        expected = str((device.get_store() or {}).get(STORE_SERIAL) or "")
        found = str(result["serial"])
        if expected and ":" not in expected and found != expected:
            # Pointing a device at a different appliance would silently make it
            # control the wrong thing, so this is refused rather than confirmed.
            return {"ok": False, "reason": "wrong_device",
                    "expected": expected, "found": found}
        await self._repoint(device, host, result["port"])
        return {"ok": True, "host": host, "port": result["port"]}

    async def _repoint(self, device, host: str, port: int) -> None:
        for key, value in ((STORE_HOST, host), (STORE_PORT, port)):
            setter = getattr(device, "set_store_value", None)
            if callable(setter):
                try:
                    result = setter(key, value)
                    if hasattr(result, "__await__"):
                        await result
                except Exception as exc:
                    self.log(f"repair: storing {key} failed: {exc}")
        self.log(f"repair: {device.get_name()} re-pointed at {host}:{port}")

    async def _on_report_env(self, data=None, **_) -> dict:
        """Record what the pairing webview sees, so it can be inspected without a
        dev session.

        `homey app run` replaces the installed app and removes it when the run
        ends, which costs the user their paired devices — too expensive a price for
        reading one log line. This lands in app settings and is surfaced by the
        diagnostics endpoint instead.
        """
        import json

        try:
            await compat.setting_set(
                self.homey, SETTING_PAIR_ENV, json.dumps(data or {})[:2000]
            )
        except Exception as exc:
            self.log(f"storing pair env failed: {exc}")
        self.log(f"pair env: {data}")
        return {"ok": True}

    async def _on_probe(self, data=None, **_) -> dict:
        data = data or {}
        host = (data.get("host") or "").strip()
        if not host:
            raise ValueError("An IP address is required")

        # Prefer the language the view reports. Both paths work, but the view's is
        # the UI language directly, while the Python side resolves the *app's*
        # i18n language — which only matches once locales/<lang>.json exists (see
        # docs/PORTING.md).
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

"""Pairing for Samsung appliances.

The client certificate is configured once in the app settings, so pairing only
needs an IP address. Before creating anything, the driver sweeps for the live DTLS
port and confirms the appliance answers /device/0 — a device that appears in Homey
has demonstrably been talked to.
"""

import asyncio

from homey import driver

from lib import cert, compat, discovery, i18n, probe, registry, support
from lib.const import (
    SETTING_LEAF_CERT,
    SETTING_LEAF_KEY,
    SETTING_PAIR_ENV,
    STORE_HOST,
    STORE_PORT,
    STORE_SERIAL,
)
from lib.resources import read_identity

# _repair_target is synchronous and raises before the handler can await anything, so
# this one message is resolved in English. It only appears if the SDK gives neither a
# device on the session nor an id in the payload, which no observed version does.
_REPAIR_NO_DEVICE = i18n.translate("error.repair_no_device")

# Where an unsupported appliance gets reported. Kept next to the manifest's
# `bugs.url` rather than derived from it: the view shows it as text a user has to
# be able to read and retype, so it must not silently become undefined.
_ISSUE_URL = "https://github.com/moKorean/com.lomohome.localthings/issues/new"

# The capability the light Flow cards drive. Named once so the cards, the
# listeners and the registry cannot drift apart.
CAPABILITY_LIGHT = "localthings_display_light"


class ApplianceDriver(driver.Driver):

    async def on_init(self) -> None:
        self.log("LocalThings appliance driver init")
        registered = 0
        for kind, card_id, listener in self._flow_cards():
            # Registered one at a time: a card that fails to resolve must not take
            # the others down with it, which a single try block around the lot does.
            try:
                getter = (self.homey.flow.get_condition_card if kind == "condition"
                          else self.homey.flow.get_action_card)
                getter(card_id).register_run_listener(listener)
                registered += 1
            except Exception as exc:
                self.log(f"registering {kind} card {card_id} failed: {exc}")
        self.log(f"registered {registered} flow card listeners")

    def _flow_cards(self):
        """(kind, card id, listener) for every card this driver backs.

        The per-capability cards are generated — 96 of them — so their listeners are
        generated here too, from the same manifest the cards came from. Writing one
        listener per card would be a hundred near-identical functions, and the first
        one to drift from its card would fail only for whoever owned that appliance.
        """
        yield ("condition", "is_pushing", self._on_is_pushing)
        yield ("condition", "light_is_on", self._on_light_is_on)
        yield ("action", "set_light", self._on_set_light)
        yield ("action", "set_ac_settings", self._on_set_ac_settings)

        for capability in self._custom_capabilities():
            stem = capability[len("localthings_"):]
            yield ("condition", f"{stem}_is", self._condition_for(capability))
            yield ("action", f"set_{stem}", self._action_for(capability))

    def _custom_capabilities(self) -> list:
        """Every capability this app defines, read from the running manifest.

        Taken from the manifest rather than from a list in the code: the cards were
        generated from the same source, so the two cannot disagree about what exists.
        Cards the generator chose not to emit simply fail to resolve, and the loop
        above logs that one and carries on.
        """
        try:
            declared = (self.homey.manifest or {}).get("capabilities") or {}
        except Exception as exc:
            self.log(f"reading capabilities from the manifest failed: {exc}")
            return []
        return [c for c in declared if c.startswith("localthings_")]

    # Generic listeners. Each closes over one capability id, so a card knows which
    # value it reads or writes without the listener having to be written out.

    def _condition_for(self, capability: str):
        async def listener(card_arguments, **_) -> bool:
            args = card_arguments or {}
            device = args.get("device")
            if device is None:
                return False
            current = device.get_capability_value(capability)
            if current is None:
                return False
            # No `state` branch here, unlike _action_for. Not one of the generated
            # condition cards declares that argument: their titles use Homey's own
            # `!{{is|is not}}` inversion, so a boolean condition reports the value and
            # Homey negates it when the user picks the second form. Reading a `state`
            # argument would have been answering a question no card asks.
            wanted = args.get("value")
            if isinstance(current, bool):
                return bool(current)
            if isinstance(current, (int, float)) and not isinstance(current, bool):
                try:
                    # "at least", matching the card's own wording.
                    return float(current) >= float(wanted)
                except (TypeError, ValueError):
                    return False
            return str(current) == str(wanted)

        return listener

    def _action_for(self, capability: str):
        async def listener(card_arguments, **_) -> None:
            args = card_arguments or {}
            device = args.get("device")
            if device is None:
                raise ValueError(_REPAIR_NO_DEVICE)
            # `state` is the boolean cards' argument; everything else carries `value`.
            value = (str(args["state"]).lower() == "on" if "state" in args
                     else args.get("value"))
            # Through the capability listener, not set_capability_value: that would
            # move Homey's copy and never touch the appliance, and it would not raise
            # when the appliance refuses.
            await device.trigger_capability_listener(capability, value)

        return listener

    async def _on_is_pushing(self, card_arguments, **_) -> bool:
        device = (card_arguments or {}).get("device")
        return bool(device is not None and device.is_pushing())

    # The light is a custom capability, so Homey generates no Flow cards for it —
    # only system capabilities like `onoff` get those. Declared and wired here.

    async def _on_light_is_on(self, card_arguments, **_) -> bool:
        device = (card_arguments or {}).get("device")
        if device is None:
            return False
        return bool(device.get_capability_value(CAPABILITY_LIGHT))

    async def _on_set_light(self, card_arguments, **_) -> None:
        """Set the light, letting a refusal fail the Flow.

        set_capability_value alone would only move Homey's copy. Going through the
        capability listener is what actually writes to the appliance and raises when
        it rejects the change, so a Flow does not report a success it did not get.
        """
        args = card_arguments or {}
        device = args.get("device")
        if device is None:
            raise ValueError(_REPAIR_NO_DEVICE)
        wanted = str(args.get("state") or "").strip().lower() == "on"
        await device.trigger_capability_listener(CAPABILITY_LIGHT, wanted)

    # The order settings are applied in. Power first, because the rest of the
    # appliance's surface only means anything once it is on. Mode next, because it
    # decides whether the others are even accepted. Temperature after mode for the
    # same reason. Air purify and the comfort mode last: both are independent of
    # the rest and neither disturbs it.
    _AC_STEPS = (
        ("power", "onoff", lambda v: v == "on"),
        ("mode", "localthings_ac_mode", str),
        ("temperature", "target_temperature", float),
        ("air_purify", "localthings_air_purify", lambda v: v == "on"),
        ("convenient", "localthings_convenient_mode", str),
    )

    async def _on_set_ac_settings(self, card_arguments, **_) -> None:
        """Apply several air-conditioner settings in one card.

        Chaining the separate cards is what this replaces, and the reason it is
        needed is that they race with the appliance rather than with each other.
        Each card decides what to send from this app's cached copy of
        `/device/0`, which is refreshed by polling — up to five minutes apart once
        the device is on push. A card that runs right after another therefore acts
        on the state from *before* the previous one, and Samsung units change what
        they report as they go.

        One measured contributor: a write payload for a list-shaped resource sends
        only the entry id and the field being changed, and folding that into the
        cache used to replace the whole list — so straight after a setpoint write
        the cached entry had lost `current`, `minimum`, `maximum` and `increment`.
        That is fixed in `_fold_write_into`, but it is why a step deciding from the
        cache left by the previous one could misbehave.

        This card refreshes the appliance before it starts and again after every
        step, so each decides from what the appliance holds now, and applies them in
        an order the appliance accepts.
        """
        args = card_arguments or {}
        device = args.get("device")
        if device is None:
            raise ValueError(_REPAIR_NO_DEVICE)

        wanted = []
        for name, capability, convert in self._AC_STEPS:
            raw = args.get(name)
            if raw in (None, "", "keep"):
                continue
            if name == "temperature" and not float(raw):
                # There is no "unset" for a number argument — Homey always sends
                # one — so zero is the skip, which the argument title states.
                continue
            wanted.append((name, capability, convert(raw)))
        if not wanted:
            return

        # One refresh up front, so the first step is not deciding from a cache that
        # may be five minutes old.
        await device.refresh_now()

        for _name, capability, value in wanted:
            await self._apply_step(device, capability, value)

    # A write the appliance accepts and then undoes needs re-sending, and the only
    # way to know is to look. Measured on the reporting unit: turn it on and set the
    # mode about three seconds later, and the write is acknowledged and then
    # overwritten by the mode the appliance restores for itself as it starts. That is
    # the setting the reported Flow lost — it is the one that runs first after
    # "turn on".
    _AC_SETTLE_S = 2.5
    _AC_ATTEMPTS = 3

    async def _apply_step(self, device, capability: str, value) -> None:
        """Write one setting and confirm the appliance kept it, re-sending if not.

        Preferred over waiting a fixed time after powering on: how long a unit takes
        to finish restoring itself is not something this app can know, and a delay
        long enough to be safe would be charged to every Flow that does not need it.
        """
        language = await compat.ui_language(self.homey)
        for attempt in range(self._AC_ATTEMPTS):
            await device.trigger_capability_listener(capability, value)
            await asyncio.sleep(self._AC_SETTLE_S)
            # Re-read before deciding, and before the next step: both need to see
            # what the appliance actually holds, not what was asked for.
            await device.refresh_now()
            if self._value_matches(device.get_capability_value(capability), value):
                return
            self.log(
                f"{capability}={value!r} did not stick "
                f"(attempt {attempt + 1}/{self._AC_ATTEMPTS}); re-sending"
            )
        raise RuntimeError(i18n.translate(
            "error.setting_not_applied", language,
            capability=capability, value=value))

    @staticmethod
    def _value_matches(current, wanted) -> bool:
        if current is None:
            return False
        if isinstance(wanted, bool) or isinstance(current, bool):
            return bool(current) == bool(wanted)
        if isinstance(wanted, (int, float)):
            try:
                return abs(float(current) - float(wanted)) < 0.01
            except (TypeError, ValueError):
                return False
        return str(current) == str(wanted)

    # --- pairing ----------------------------------------------------------

    async def on_pair(self, session) -> None:
        self._session = session
        session.set_handler("get_state", self._on_get_state)
        session.set_handler("report_env", self._on_report_env)
        session.set_handler("discover_start", self._on_discover_start)
        session.set_handler("discover_status", self._on_discover_status)
        session.set_handler("probe", self._on_probe)
        session.set_handler("resolve_name", self._on_resolve_name)

    async def _language(self, data=None) -> str:
        """The UI language, preferring what the view just reported.

        A view resolves it from its own Homey object, which knows the user's language;
        the Python i18n manager reports the *app's* and answers 'en' regardless. What
        the view reports is also remembered, so messages raised later — from a poll
        loop, with no view in sight — can still be in the right language.
        """
        reported = ((data or {}).get("language") or "").strip()
        if reported:
            await compat.remember_ui_language(self.homey, reported)
            return reported[:2].lower()
        return await compat.ui_language(self.homey)

    async def _credentials(self) -> tuple[str, str]:
        return (
            await compat.setting_get(self.homey, SETTING_LEAF_CERT),
            await compat.setting_get(self.homey, SETTING_LEAF_KEY),
        )

    async def _on_get_state(self, data=None, **_) -> dict:
        """Lets the view send the user to app settings instead of failing at
        Connect when no certificate has been configured yet."""
        cert_pem, key_pem = await self._credentials()
        language = await compat.ui_language(self.homey)
        # Logged because "the certificate is stored but pairing says otherwise"
        # is otherwise indistinguishable from "it was never stored".
        self.log(
            f"pair get_state: cert={len(cert_pem)}B key={len(key_pem)}B "
            f"language={language}"
        )
        # The subnet base lets the manual-entry field prefill everything but the
        # last octet. Resolved here rather than in the view, which has no way to
        # ask: a webview sees Homey's address, not the Homey's own LAN interface.
        # A failure must not block pairing, so it falls back to no prefix and the
        # view asks for a whole address.
        try:
            subnet, _own = discovery.local_subnet()
        except Exception as exc:
            self.log(f"subnet detection failed: {exc}")
            subnet = ""

        return {
            "has_credentials": bool(cert_pem and key_pem),
            "language": language,
            "subnet": subnet,
        }

    def _taken_names(self) -> set:
        """Names already in use by this driver's devices.

        Homey does not disambiguate duplicate names and a device cannot rename itself
        — there is no set_name — so this is where it has to happen.
        """
        names = set()
        try:
            devices = self.get_devices()
        except Exception:
            return names
        for device in devices:
            try:
                name = device.get_name()
            except Exception:
                continue
            if name:
                names.add(str(name))
        return names

    def _unique_name(self, base: str) -> str:
        """`base`, or `base 2`, `base 3`, ... if that name is taken.

        Only a collision gets a suffix: someone with one air conditioner should not
        have to look at a number. Four of them, added in a row, need telling apart
        long enough to be renamed, and a count does that without embedding an address
        that stops being true the moment DHCP moves the appliance.
        """
        taken = self._taken_names()
        if base not in taken:
            return base
        # Bounded: a house with 99 of one appliance type is not the case to optimise
        # for, and an unbounded loop here would hang pairing rather than fail it.
        for index in range(2, 100):
            candidate = f"{base} {index}"
            if candidate not in taken:
                return candidate
        return base

    async def _on_resolve_name(self, data=None, **_) -> dict:
        """A unique name, resolved now rather than when the appliance was found.

        Discovery builds each device payload while scanning, before anything has been
        created, so every air conditioner in one sweep would carry the same name. The
        view asks for the name immediately before creating the device, when what
        already exists is known.
        """
        base = str((data or {}).get("name") or "").strip()
        if not base:
            return {"name": ""}
        return {"name": self._unique_name(base)}

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

        language = await self._language(data)
        cert_pem, key_pem = await self._credentials()
        if not cert_pem or not key_pem:
            raise ValueError(i18n.translate("error.no_credentials", language))
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
        reg = registry.resolve(resources, result.get("device_types") or ())
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
            # The appliance type alone. The address used to be appended to keep four
            # air conditioners apart in the list, but it is the wrong thing to carry
            # in a name the user then lives with — it is already on the device's
            # advanced settings, kept current when DHCP moves the appliance, and a
            # name containing a stale address is worse than no address at all.
            "name": self._unique_name(reg.title(language)),
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
        # The device is bound to *this* session rather than parked on the driver.
        # It used to live in self._repair_device, which two repair sessions open at
        # once would share: the second to open would win, and the first webview's
        # "set the address by hand" would then move the second appliance to it.
        for name, handler in (
            ("repair_state", self._on_repair_state),
            ("repair_test", self._on_repair_test),
            ("repair_find", self._on_repair_find),
            ("repair_host", self._on_repair_host),
        ):
            session.set_handler(name, self._for_session(handler, device))

    def _for_session(self, handler, device):
        async def run(data=None, **_):
            return await handler(self._repair_target(data, device), data)

        return run

    def _repair_target(self, data=None, device=None):
        """The device being repaired.

        Taken from on_repair where the SDK provides it, and from the handler payload
        otherwise — the argument's presence is not something this app can rely on
        across SDK versions.
        """
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
        raise ValueError(_REPAIR_NO_DEVICE)

    async def _on_repair_state(self, device, data=None) -> dict:
        await self._language(data)
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
            "language": await compat.ui_language(self.homey),
            "name": device.get_name(),
            "host": store.get(STORE_HOST),
            "port": store.get(STORE_PORT),
            "serial": store.get(STORE_SERIAL),
            "available": bool(device.get_available()),
            "certificate": certificate,
        }

    async def _on_repair_test(self, device, data=None) -> dict:
        """Read /device/0 at the stored address and confirm it is still this unit.

        Reporting a serial mismatch matters as much as reporting a failure: it is the
        case where everything looks connected but the device is driving a different
        appliance.
        """
        store = device.get_store() or {}
        host = store.get(STORE_HOST)
        cert_pem, key_pem = await self._credentials()
        if not cert_pem or not key_pem:
            return {"ok": False, "reason": "no_credentials"}
        try:
            result = await device.check_now()
        except Exception as exc:
            return {"ok": False, "reason": "unreachable", "detail": str(exc)[:200]}

        expected = str(store.get(STORE_SERIAL) or "")
        found = str(result["serial"])
        if expected and ":" not in expected and found != expected:
            return {"ok": False, "reason": "wrong_device",
                    "expected": expected, "found": found, "host": host}
        return {"ok": True, "host": host, "port": result["port"], "serial": found}

    async def _on_repair_find(self, device, data=None) -> dict:
        """Sweep for this appliance by serial and re-point the device at it."""
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

    async def _on_repair_host(self, device, data=None) -> dict:
        """Re-point at an address the user supplies, after checking it is this unit."""
        host = ((data or {}).get("host") or "").strip()
        if not host:
            raise ValueError(i18n.translate(
                "error.host_required", await compat.ui_language(self.homey)))
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
        """Move the device, session and all, not just its stored address.

        This used to write the two store keys directly and report success. Nothing
        re-reads the store — the SDK has no store-change hook and `Device.on_init`
        reads it once — so the running device kept polling the old address and kept
        showing it in the advanced settings, and the repair only took effect on the
        next app restart. `Device.move_to` is what the automatic relocation already
        used; both paths now go through it.

        Failures are raised rather than logged. A repair that could not move the
        device but said it had is worse than one that says it failed.
        """
        await device.move_to(host, port)
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
        await compat.remember_ui_language(self.homey, (data or {}).get("resolved"))
        self.log(f"pair env: {data}")
        return {"ok": True}

    async def _on_probe(self, data=None, **_) -> dict:
        data = data or {}
        language = await self._language(data)
        host = (data.get("host") or "").strip()
        if not host:
            raise ValueError(i18n.translate("error.host_required", language))

        cert_pem, key_pem = await self._credentials()
        if not cert_pem or not key_pem:
            raise ValueError(
                "No client certificate configured. Set one up in "
                "Settings -> Apps -> LocalThings first."
            )

        self.log(f"probing {host}")
        result = await self._run(probe.probe, host, cert_pem, key_pem)

        resources = result["resources"]
        reg = registry.resolve(resources, result.get("device_types") or ())
        identity = read_identity(resources)
        model = identity["model"].split("|")[0] or identity["description"]

        if reg is None:
            # Deliberately not a hard error: the appliance is reachable, and its
            # /device/0 is exactly what adding support needs. Hand the user a
            # ready-to-send report rather than asking them to describe the device —
            # a model number alone is not enough to map anything, which is why the
            # range hood shipped with every field name guessed wrong.
            self.log(f"unrecognised appliance {model}, {len(resources)} resources")
            return {
                "recognised": False,
                "model": model,
                "resource_count": len(resources),
                "report": support.report(
                    resources,
                    model=model,
                    port=result.get("port"),
                    app_version=(self.homey.manifest or {}).get("version"),
                ),
                "issue_url": _ISSUE_URL,
            }

        # The search list filters out what is already paired; entering an address by
        # hand skipped that check, so Homey was left to reject the duplicate at
        # createDevice — and its rejection is a structured object, which the view
        # could only render as an unattributed error. Say it here instead.
        _, paired_serials = self._paired_identity()
        if str(result["serial"]) in paired_serials:
            raise ValueError(i18n.translate(
                "error.already_paired", language, host=host, model=model))

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


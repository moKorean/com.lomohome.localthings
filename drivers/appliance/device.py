"""One paired Samsung appliance.

Holds a sustained DTLS session, keeps capability values current, and writes
changes straight to the appliance — the equivalent of the reference integration's
coordinator plus its observe manager.

State arrives by CoAP OBSERVE (push) once the device proves it actually notifies,
and by polling until then. Push is earned rather than assumed: a device can accept
a subscription and never notify, which would look healthy while going stale. A slow
summary sweep continues even on push, because a missed notification is otherwise
invisible.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from homey import device  # noqa: E402

from lib import compat, discovery, probe, registry  # noqa: E402
from lib.const import (  # noqa: E402
    OBSERVE_GRACE_S,
    RELOCATE_AFTER_FAILURES,
    STORE_SERIAL,
    PUSH_HEALTH_WINDOW_S,
    OBSERVE_REFRESH_S,
    OBSERVE_RETRY_S,
    OBSERVE_SUCCESS_FRACTION,
    OBSERVE_SWEEP_INTERVAL_S,
    POLL_INTERVAL_S,
    SETTING_LEAF_CERT,
    SETTING_LEAF_KEY,
    STORE_HOST,
    STORE_PORT,
    WRITE_SETTLE_S,
)
from lib.resources import read_serial  # noqa: E402
from lib.session import Session  # noqa: E402


class Device(device.Device):

    async def on_init(self) -> None:
        store = self.get_store()
        self._host = store.get(STORE_HOST)
        self._port = int(store.get(STORE_PORT))
        self._serial = str(store.get(STORE_SERIAL) or "")
        self._failures = 0
        self._registry = None
        self._resources: dict = {}
        self._poll_task = None

        # Push state. Starts in poll mode; observe is entered only once enough
        # initial notifications have actually arrived.
        self._observing = False
        self._notified: set = set()
        self._observe_hrefs: set = set()
        self._observe_attempted_at = 0.0
        self._subscribed_at = 0.0
        self._observe_pending = False
        self._observe_failed = 0
        self._last_notify_at = 0.0
        # href -> monotonic deadline. A just-written resource ignores incoming
        # notifications briefly, so a slow-settling device can't revert the value
        # that was just set.
        self._settling: dict = {}

        # The certificate lives at app level, not in the device store, so
        # rotating it repairs every paired appliance at once instead of needing
        # each one re-paired.
        self._session = Session(
            self._host,
            self._port,
            await compat.setting_get(self.homey, SETTING_LEAF_CERT),
            await compat.setting_get(self.homey, SETTING_LEAF_KEY),
            log=self.log,
            on_notification=self._on_notification,
        )

        for capability in self.get_capabilities():
            self.register_capability_listener(
                capability, self._make_listener(capability)
            )

        self.log(f"{self.get_name()} init ({self._host}:{self._port})")
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def on_uninit(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
        await self._session.close()

    # --- polling ----------------------------------------------------------

    def _poll_interval(self) -> float:
        if self._observing:
            return OBSERVE_SWEEP_INTERVAL_S
        try:
            return float(self.get_settings().get("poll_interval") or POLL_INTERVAL_S)
        except (TypeError, ValueError):
            return POLL_INTERVAL_S

    # --- push -------------------------------------------------------------

    def _observable_hrefs(self) -> list:
        """The distinct resources any bound capability reads from.

        Subscribing to exactly these keeps the subscription count proportional to
        what the device actually drives, rather than observing resources nothing
        reads.
        """
        own = set(self.get_capabilities())
        return sorted({
            spec.href for spec in self._registry.specs
            if spec.capability in own and spec.href in self._resources
        })

    async def _try_observe(self) -> None:
        """Subscribe, then let a later poll judge whether push actually works.

        The judgment is deliberately not made here. Subscribing 22 resources takes
        over four seconds on its own — the library paces CON sends at 5/s — and the
        initial notifications keep arriving after that, so deciding from inside a
        fixed sleep both blocks the poll loop and reaches its verdict before the
        evidence is in. That is what made a device with 21 of 22 resources notifying
        get recorded as push-unavailable.
        """
        now = time.monotonic()
        if self._observe_pending:
            return
        if self._observing:
            if now - self._subscribed_at < OBSERVE_REFRESH_S:
                return
        elif self._observe_attempted_at and now - self._observe_attempted_at < OBSERVE_RETRY_S:
            return

        hrefs = self._observable_hrefs()
        if not hrefs:
            return

        self._observe_attempted_at = now
        self._notified.clear()
        self._observe_hrefs = set(hrefs)
        failed = 0
        for href in hrefs:
            try:
                await self._session.subscribe(href.strip("/").split("/"))
            except Exception as exc:
                failed += 1
                self.log(f"subscribe {href} failed: {exc}")
        self._subscribed_at = time.monotonic()
        self._observe_pending = True
        self._observe_failed = failed
        self.log(f"subscribed to {len(hrefs) - failed}/{len(hrefs)} resources")

    def _evaluate_observe(self) -> None:
        """Decide push vs poll once the grace period has actually elapsed."""
        if not self._observe_pending:
            return
        if time.monotonic() - self._subscribed_at < OBSERVE_GRACE_S:
            return

        hrefs = self._observe_hrefs
        got = len(self._notified & hrefs)
        needed = max(1, int(len(hrefs) * OBSERVE_SUCCESS_FRACTION))
        self._observe_pending = False

        if got >= needed:
            if not self._observing:
                self._observing = True
                self.log(
                    f"push mode: {got}/{len(hrefs)} resources notified; "
                    f"summary sweep every {OBSERVE_SWEEP_INTERVAL_S:.0f}s"
                )
        else:
            if self._observing:
                self.log(f"push lost ({got}/{len(hrefs)} notified); back to polling")
            else:
                self.log(
                    f"push unavailable ({got}/{len(hrefs)} notified, "
                    f"{self._observe_failed} subscribe errors); polling"
                )
            self._observing = False

    def _push_is_healthy(self) -> bool:
        """Whether anything has been pushed recently enough to trust the channel.

        A resource that simply never changes sends nothing, so silence across the
        whole device — not per resource — is the signal worth acting on.
        """
        if not self._last_notify_at:
            return False
        return time.monotonic() - self._last_notify_at < PUSH_HEALTH_WINDOW_S

    def _on_notification(self, href: str, rep: dict) -> None:
        """A pushed resource update. Called on the event loop by Session."""
        self._notified.add(href)
        self._last_notify_at = time.monotonic()
        deadline = self._settling.get(href)
        if deadline and time.monotonic() < deadline:
            # Mid-settle after a write: the device may still be reporting the old
            # value, which would undo the optimistic one.
            return
        merged = self._resources.setdefault(href, {})
        merged.update(rep)
        # Fire and forget: this is a callback, not a coroutine the loop awaits.
        asyncio.create_task(self._apply_href(href))

    async def _apply_href(self, href: str) -> None:
        if self._registry is None:
            return
        try:
            await self._apply(self._resources, only_href=href)
        except Exception as exc:
            self.log(f"applying pushed update for {href} failed: {exc}")

    async def _poll_loop(self) -> None:
        # Back off on repeated failure rather than hammering a device that is
        # unplugged or asleep; the appliance firmware drops requests when hit
        # faster than its ceiling.
        failures = 0
        while True:
            try:
                await self._poll_once()
                self._failures = 0
                delay = self._poll_interval()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._failures += 1
                delay = min(self._poll_interval() * min(self._failures, 6), 300)
                self.log(
                    f"poll failed ({self._failures}): {exc}; retrying in {delay:.0f}s"
                )
                await self.set_unavailable(str(exc))
                # Repeated failure is what a DHCP move looks like from here, so
                # search for the appliance by serial before settling into backoff.
                if self._failures == RELOCATE_AFTER_FAILURES:
                    try:
                        if await self._relocate():
                            delay = 1.0
                            self._failures = 0
                    except Exception as relocate_error:
                        self.log(f"relocation failed: {relocate_error}")
            await asyncio.sleep(delay)

    def _identity_is_verifiable(self) -> bool:
        """Whether the stored serial can actually prove identity.

        read_serial falls back to "host:port" for firmware that reports a
        placeholder serial, and that fallback stops being meaningful the moment the
        address changes — so those devices are relocated but not identity-checked.
        """
        return bool(self._serial) and ":" not in self._serial

    async def _remember_location(self, host: str, port: int) -> None:
        """Persist a new address and reflect it in the settings the user sees."""
        self._host, self._port = host, port
        for setter, args in (
            ("set_store_value", (STORE_HOST, host)),
            ("set_store_value", (STORE_PORT, port)),
        ):
            method = getattr(self, setter, None)
            if callable(method):
                try:
                    result = method(*args)
                    if hasattr(result, "__await__"):
                        await result
                except Exception as exc:
                    self.log(f"storing {args[0]} failed: {exc}")

    async def _sync_settings(self) -> None:
        """Keep the advanced settings showing what is actually in use.

        They were previously written only at pairing, so after an address change the
        panel would keep showing the old one — the value a user goes there to check.
        """
        mode = "push" if self._observing else "polling"
        detail = f"{mode}, {self._session.subscription_count} subscriptions" \
            if self._observing else mode
        wanted = {
            "host": str(self._host),
            "port": str(self._port),
            "serial": self._serial,
            "status": detail,
        }
        try:
            current = self.get_settings() or {}
        except Exception:
            current = {}
        changed = {k: v for k, v in wanted.items() if str(current.get(k, "")) != v}
        if not changed:
            return
        try:
            result = self.set_settings(changed)
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:
            self.log(f"updating settings failed: {exc}")

    async def _relocate(self) -> bool:
        """Find this appliance again after its address changed.

        Identity is the serial, not the address, so a DHCP move is recoverable
        without re-pairing. Sweeping is cheap; the handshake per candidate is not, so
        candidates already known to be paired elsewhere are not re-probed here —
        being wrong about that would only cost time, whereas skipping the serial
        check would risk binding to the wrong appliance.
        """
        cert_pem = await compat.setting_get(self.homey, SETTING_LEAF_CERT)
        key_pem = await compat.setting_get(self.homey, SETTING_LEAF_KEY)
        if not cert_pem or not key_pem:
            return False
        if not self._identity_is_verifiable():
            self.log("cannot relocate: this appliance reports no usable serial")
            return False

        self.log(f"looking for {self._serial} after losing {self._host}")
        try:
            candidates = await discovery.sweep()
        except Exception as exc:
            self.log(f"relocation sweep failed: {exc}")
            return False

        loop = asyncio.get_running_loop()
        for host, port in candidates:
            if host == self._host:
                continue
            try:
                result = await loop.run_in_executor(
                    None, probe.probe, host, cert_pem, key_pem
                )
            except Exception:
                continue
            if str(result["serial"]) != self._serial:
                continue
            self.log(f"found at {host}:{result['port']}; updating")
            await self._session.close()
            await self._remember_location(host, result["port"])
            self._session = Session(
                self._host, self._port, cert_pem, key_pem,
                log=self.log, on_notification=self._on_notification,
            )
            # Subscriptions belonged to the old session.
            self._observing = False
            self._observe_pending = False
            self._observe_attempted_at = 0.0
            await self._sync_settings()
            return True

        self.log(f"{self._serial} not found on the network")
        return False

    async def _poll_once(self) -> None:
        if not await compat.setting_get(self.homey, SETTING_LEAF_CERT):
            # Distinct from a network failure, and fixable in one place, so say
            # where rather than reporting a bare connection error.
            raise RuntimeError(
                "No client certificate configured. Set one up in "
                "Settings -> Apps -> LocalThings."
            )
        self._resources = await self._session.read_device0()

        # Confirm this is still the appliance we were paired with. Two devices
        # swapping addresses over DHCP would otherwise leave each one silently
        # driving the other — worse than being unavailable.
        if self._identity_is_verifiable():
            seen = read_serial(self._resources, self._host, self._port)
            if seen != self._serial:
                self._resources = {}
                raise RuntimeError(
                    f"{self._host} is a different appliance now "
                    f"(expected {self._serial}, found {seen})"
                )

        if self._registry is None:
            self._registry = registry.resolve(self._resources)
            if self._registry is None:
                raise RuntimeError("appliance type no longer recognised")
            unbound = registry.unbound_hrefs(self._resources, self._registry)
            self.log(
                f"registry {self._registry.name}, "
                f"{len(unbound)} unbound resources: {unbound}"
            )
        await self._apply(self._resources)
        await self.set_available()
        self._evaluate_observe()
        await self._try_observe()
        await self._sync_settings()

    async def _apply(self, resources: dict, only_href: str = None) -> None:
        """Push every readable value into its capability.

        A spec returning None is skipped rather than written as null: a missing
        field or a stub rep must not overwrite a good value with a wrong one.
        `only_href` limits the work to one resource, for pushed updates.
        """
        for spec in self._registry.specs:
            if only_href is not None and spec.href != only_href:
                continue
            if spec.capability not in self.get_capabilities():
                continue
            rep = resources.get(spec.href)
            if not rep:
                continue
            try:
                value = spec.read(rep, resources)
            except Exception as exc:
                self.log(f"read {spec.capability} failed: {exc}")
                continue
            if value is None:
                continue
            if self.get_capability_value(spec.capability) != value:
                await self.set_capability_value(spec.capability, value)

    # --- writes -----------------------------------------------------------

    def _make_listener(self, capability: str):
        async def listener(value, **_):
            await self._write(capability, value)

        return listener

    async def _write(self, capability: str, value) -> None:
        spec = self._registry.spec_for(capability) if self._registry else None
        if spec is None or not spec.writable:
            raise RuntimeError(f"{capability} is not writable on this appliance")

        rep = self._resources.get(spec.href) or {}
        payload = spec.write(value, rep)
        if payload is None:
            # The device didn't advertise this value; refuse rather than send
            # something it will silently drop.
            raise RuntimeError(f"{value!r} is not supported by this appliance")

        # A write asking for the value the device already holds is refused
        # ("controlResponse result False"), which surfaced as a spurious error
        # whenever the requested value happened to match. Nothing needs sending.
        try:
            current = spec.read(rep, self._resources) if rep else None
        except Exception:
            current = None
        if current is not None and current == value:
            await self.set_capability_value(capability, value)
            return

        path_segs, body = payload
        # Guard before sending: the notification for this write can arrive while
        # the device is still reporting the old value.
        self._settling["/" + "/".join(path_segs)] = time.monotonic() + WRITE_SETTLE_S
        self.log(f"write {capability}={value!r} -> /{'/'.join(path_segs)} {body}")
        response = await self._session.write(path_segs, body)
        if not Session.write_accepted(response):
            self.log(f"write {capability} refused, device said: {response}")
            raise RuntimeError(f"The appliance rejected {capability}={value!r}")

        # Optimistic apply, so the tile reflects the change before the next poll.
        # Merge the body actually sent and re-read it through the spec, so the tile
        # shows what the device received rather than what was requested — the two
        # differ whenever the value had to be snapped to the increment.
        merged = self._resources.setdefault(spec.href, {})
        merged.update(body)
        try:
            applied = spec.read(merged, self._resources)
        except Exception:
            applied = None
        await self.set_capability_value(
            capability, value if applied is None else applied
        )


homey_export = Device

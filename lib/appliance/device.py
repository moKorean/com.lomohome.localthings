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
import time

from homey import device

from lib import compat, discovery, i18n, probe, registry
from lib.const import (
    OBSERVE_GRACE_S,
    OBSERVE_REFRESH_S,
    OBSERVE_RETRY_S,
    OBSERVE_SUCCESS_FRACTION,
    OBSERVE_SWEEP_INTERVAL_S,
    POLL_INTERVAL_S,
    PUSH_HEALTH_WINDOW_S,
    RELOCATE_AFTER_FAILURES,
    SETTING_LEAF_CERT,
    SETTING_LEAF_KEY,
    STORE_HOST,
    STORE_PORT,
    STORE_SERIAL,
    WRITE_SETTLE_S,
)
from lib.resources import read_serial
from lib.session import Session


class ApplianceDevice(device.Device):

    async def on_init(self) -> None:
        store = self.get_store()
        self._host = store.get(STORE_HOST)
        self._port = int(store.get(STORE_PORT))
        self._serial = str(store.get(STORE_SERIAL) or "")
        self._failures = 0
        self._registry = None
        self._resources: dict = {}
        # Resolved once at start: messages are raised from the poll loop and from
        # capability listeners, where awaiting a settings read on every failure would
        # be wasteful and would run during the failure it is describing.
        self._language = await compat.ui_language(self.homey)
        self._poll_task = None
        # Retained so the event loop keeps a strong reference: a task held only by
        # the loop's transient set can be garbage-collected mid-flight, which would
        # silently drop a pushed update.
        self._tasks: set = set()

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

        # Previous values, so flow triggers fire on a transition rather than on every
        # poll that happens to see the same state.
        self._previous: dict = {}
        # capability -> the options last handed to Homey, so re-pushing an unchanged
        # set every poll can be skipped.
        self._applied_options: dict = {}

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
        # A callback, not a coroutine the loop awaits — so the task is kept in a set
        # and discarded on completion rather than left unreferenced.
        task = asyncio.create_task(self._apply_href(href))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _apply_href(self, href: str) -> None:
        if self._registry is None:
            return
        try:
            await self._apply(self._resources, only_href=href)
        except Exception as exc:
            self.log(f"applying pushed update for {href} failed: {exc}")

    async def _poll_loop(self) -> None:
        # Back off on repeated failure rather than hammering a device that is
        # unplugged or asleep; the appliance firmware drops requests when hit faster
        # than its ceiling. The counter lives on the instance because relocation
        # reads it too.
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
        for host, _port in candidates:
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
            raise RuntimeError(i18n.translate("error.no_credentials", self._language))
        self._resources = await self._session.read_device0()

        # Confirm this is still the appliance we were paired with. Two devices
        # swapping addresses over DHCP would otherwise leave each one silently
        # driving the other — worse than being unavailable.
        if self._identity_is_verifiable():
            seen = read_serial(self._resources, self._host, self._port)
            if seen != self._serial:
                self._resources = {}
                raise RuntimeError(i18n.translate(
                    "error.wrong_device", self._language,
                    host=self._host, expected=self._serial, found=seen))

        if self._registry is None:
            self._registry = registry.resolve(self._resources)
            if self._registry is None:
                raise RuntimeError(i18n.translate("error.not_recognised", self._language))
            unbound = registry.unbound_hrefs(self._resources, self._registry)
            self.log(
                f"registry {self._registry.name}, "
                f"{len(unbound)} unbound resources: {unbound}"
            )
            await self._sync_device_class()
        # Outside the block above on purpose: the resource surface changes while the
        # app is running, not only between versions. A convertible refrigerator
        # switched from fridge to freezer moves its setpoint to the other
        # compartment; a cooktop's Bluetooth probe appears when it is paired. Both
        # were invisible until the next app restart when this ran once per start.
        # Both calls compare before acting, so the steady-state cost is a comparison.
        await self._sync_capabilities()
        await self._sync_capability_options()
        await self._apply(self._resources)
        await self.set_available()
        self._evaluate_observe()
        await self._try_observe()
        await self._sync_settings()

    async def _sync_capabilities(self) -> None:
        """Bring the device's capability list in line with what the registry now maps.

        Homey fixes a device's capabilities at creation, so a registry correction
        reaches only appliances paired afterwards. That is how it should not work
        here: the range hood's mapping was wrong in its first release, and once
        fixed, the already-paired hood kept the seven broken capabilities it was
        created with and gained none of the working ones. The only remedy was to
        delete and re-add the appliance, losing its flows and history.

        Both directions matter. Adding is what delivers a fix; removing is what
        retires a capability that turned out to read nothing, and leaving those
        behind is what made the hood look supported when it was not.

        add_capability is documented as expensive, so nothing is touched unless the
        sets actually differ — on an unchanged device this costs one comparison.
        """
        # Registry order, not a set: the order a device holds its capabilities in is
        # the order Homey shows them, and the registry declares power first for every
        # appliance type. Adding alphabetically put `onoff` after everything on the
        # range hood, so the tile led with the light instead.
        ordered = self._registry.capabilities(self._resources)
        wanted = set(ordered)
        current = set(self.get_capabilities() or ())
        if wanted == current:
            return

        # add_capability appends, so this only fixes the relative order of what is
        # added now — a device created before a capability existed keeps it at the end
        # until it is re-paired. There is no reorder call in the SDK, and rebuilding
        # the whole list means removing capabilities, which breaks any Flow using them.
        for capability in [c for c in ordered if c in wanted - current]:
            try:
                await self.add_capability(capability)
                self.log(f"capability added: {capability}")
            except Exception as exc:
                self.log(f"adding {capability} failed: {exc}")

        # Removals last: a device briefly holding both sets is harmless, whereas a
        # device that has had everything removed and then fails to add is not.
        for capability in sorted(current - wanted):
            try:
                await self.remove_capability(capability)
                self.log(f"capability removed: {capability}")
            except Exception as exc:
                self.log(f"removing {capability} failed: {exc}")

        # Listeners are registered in on_init against the capability list as it was
        # then, so anything added since has no listener and would accept a write
        # that goes nowhere.
        for capability in [c for c in ordered if c in wanted - current]:
            try:
                self.register_capability_listener(
                    capability, self._make_listener(capability)
                )
            except Exception as exc:
                self.log(f"listener for {capability} failed: {exc}")

    async def _sync_device_class(self) -> None:
        """Adopt the class the registry declares for what this appliance turned out
        to be.

        One driver covers every appliance type, so driver.compose.json can only
        declare a single class and declares the neutral `other`. The actual type is
        not known until /device/0 has been read, which is here — so the class the
        registry carries (a thermostat for an air conditioner, a fan for a purifier
        or hood) has to be applied at runtime or it never takes effect and Homey
        shows every appliance as a generic device.

        Cheap and idempotent, so it runs on every start rather than only at
        creation: that is what lets a device paired before this existed pick its
        class up, and what corrects one whose registry mapping later changes.
        """
        wanted = getattr(self._registry, "device_class", None)
        if not wanted or self.get_class() == wanted:
            return
        try:
            await self.set_class(wanted)
            self.log(f"device class -> {wanted}")
        except Exception as exc:
            # A wrong class is a cosmetic problem; refusing to start over it is not.
            self.log(f"device class {wanted} rejected: {exc}")

    async def _sync_capability_options(self) -> None:
        """Push per-device capability options (ranges, sub-capability titles).

        Done here rather than only at creation so a device paired before a fix picks
        the corrected bounds up on its next start — a slider whose range came from
        Homey's defaults instead of the appliance offers values the device refuses.
        """
        setter = getattr(self, "set_capability_options", None)
        if not callable(setter):
            return
        language = await compat.language(self.homey)
        options = self._registry.capability_options(self._resources, language)
        own = set(self.get_capabilities())
        for capability, values in options.items():
            if capability not in own:
                continue
            # Skip what is already applied. This runs on every poll so that a range
            # the appliance changes is followed, and re-pushing 30-odd unchanged
            # option sets every 30 seconds would be pure waste.
            if self._applied_options.get(capability) == values:
                continue
            try:
                result = setter(capability, values)
                if hasattr(result, "__await__"):
                    await result
                self._applied_options[capability] = values
            except Exception as exc:
                self.log(f"capability options for {capability} failed: {exc}")

    async def _apply(self, resources: dict, only_href: str | None = None) -> None:
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
            await self._maybe_trigger(spec.capability, value)

    async def _maybe_trigger(self, capability: str, value) -> None:
        """Fire the flow triggers this capability drives, on change only.

        Anchored on the previous value rather than the capability's current one: a
        capability that is set to the same value still returns it, so comparing
        against Homey's copy would fire nothing, while firing unconditionally would
        fire on every poll.
        """
        previous = self._previous.get(capability, "__unset__")
        self._previous[capability] = value
        if previous == "__unset__" or previous == value:
            return

        base = capability.split(".")[0]
        try:
            if base == "localthings_alarm_code":
                await self._trigger("alarm_raised", {"code": str(value)})
            elif base == "localthings_alarm_filter" and value:
                await self._trigger("filter_needs_attention", {})
            elif base == "localthings_display_light":
                # Two cards rather than one "changed" card: a Flow that wants the
                # light coming on should not need a condition to filter out the
                # other half of the transitions.
                await self._trigger(
                    "light_turned_on" if value else "light_turned_off", {})
            elif base == "localthings_cycle_active" and previous and not value:
                # The transition out of running is the interesting one; a device
                # sitting idle must not keep announcing that it finished.
                await self._trigger("cycle_finished", {})
            elif base.startswith("localthings_"):
                # The generated "<x> changed" triggers, fired by convention. Only a
                # curated set of capabilities has one — checked rather than attempted,
                # because resolving a card that does not exist raises, and that would
                # log a failure on every change of every other capability.
                card_id = f"{base[len('localthings_'):]}_changed"
                if card_id in self._trigger_cards():
                    await self._trigger(card_id, {"value": str(value)})
        except Exception as exc:
            self.log(f"trigger for {capability} failed: {exc}")

    def _trigger_cards(self) -> set:
        """Device trigger card ids this app declares, read once from the manifest."""
        cached = getattr(self, "_trigger_card_ids", None)
        if cached is not None:
            return cached
        ids = set()
        try:
            flow = (self.homey.manifest or {}).get("flow") or {}
            for card in flow.get("triggers") or ():
                card_id = (card or {}).get("id")
                if card_id:
                    ids.add(card_id)
        except Exception as exc:
            self.log(f"reading trigger cards from the manifest failed: {exc}")
        self._trigger_card_ids = ids
        return ids

    async def _trigger(self, card_id: str, tokens: dict) -> None:
        card = self.homey.flow.get_device_trigger_card(card_id)
        result = card.trigger(self, tokens, {})
        if hasattr(result, "__await__"):
            await result

    def _label(self, capability: str) -> str:
        """A capability's own title where the device carries one, else its id.

        A message naming 'localthings_ac_mode' is technically accurate and useless to
        read; the sub-capability titles already exist for exactly this.
        """
        if self._registry is None:
            return capability
        spec = self._registry.spec_for(capability)
        if spec and spec.titles:
            return spec.titles.get(self._language) or spec.titles.get("en") or capability
        return capability

    def is_pushing(self) -> bool:
        """Backs the 'state is arriving by push' flow condition."""
        return bool(self._observing)

    # --- writes -----------------------------------------------------------

    def _make_listener(self, capability: str):
        async def listener(value, **_):
            await self._write(capability, value)

        return listener

    async def _write(self, capability: str, value) -> None:
        # Pass the resources: a capability declared in both an OCF and a vendor
        # form must resolve to the one this appliance actually reports, or the
        # write goes to a path it does not have and is silently dropped.
        spec = (self._registry.spec_for(capability, self._resources)
                if self._registry else None)
        if spec is None or not spec.writable:
            raise RuntimeError(i18n.translate(
                "error.not_writable", self._language, capability=self._label(capability)))

        rep = self._resources.get(spec.href) or {}
        payload = spec.write(value, rep)
        if payload is None:
            # The device didn't advertise this value; refuse rather than send
            # something it will silently drop.
            raise RuntimeError(i18n.translate(
                "error.value_unsupported", self._language, value=value))

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
            raise RuntimeError(i18n.translate(
                "error.write_rejected", self._language,
                capability=self._label(capability), value=value))

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


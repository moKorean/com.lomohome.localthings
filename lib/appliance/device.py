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
import contextlib
import time

from homey import device

from lib import compat, discovery, i18n, probe, registry
from lib.const import (
    OBSERVE_GRACE_S,
    OBSERVE_REFRESH_S,
    OBSERVE_RETRY_S,
    OBSERVE_SUBSCRIBE_SPACING_S,
    OBSERVE_SUCCESS_FRACTION,
    OBSERVE_SWEEP_INTERVAL_S,
    POLL_INTERVAL_S,
    RELOCATE_AFTER_FAILURES,
    SETTING_LEAF_CERT,
    SETTING_LEAF_KEY,
    STORE_HOST,
    STORE_PORT,
    STORE_SERIAL,
    UNAVAILABLE_AFTER_FAILURES,
    WRITE_SETTLE_S,
)
from lib.resources import read_serial
from lib.session import Session

ITEMS_FIELD = "x.com.samsung.da.items"
ITEM_ID = "x.com.samsung.da.id"


def _replaces_on_notify(href: str) -> bool:
    """Whether a pushed update for `href` replaces the cached rep instead of
    merging into it.

    Merging is the right default: a notification can carry only the fields that
    changed, so an absent key means "unchanged, keep what we had". `/alarms/vs/0`
    is the resource where that reasoning runs backwards, because **its empty state
    is an empty rep**. Measured here, not inferred: all three refrigerators report

        "/alarms/vs/0": {}

    with nothing wrong, so `{}` is what the board says when it has no alarm to
    report. Merged, that is a no-op — the alarm that was there stays in the cache
    for as long as the app runs, surviving the appliance clearing it and every
    power cycle, because only a poll rebuilds the rep wholesale and a device on
    push polls just a summary sweep.

    Deliberately narrow. "An empty rep always replaces" would be the tempting
    generalisation and it is not supported: nothing has been measured about what an
    empty notification means on any other resource, and guessing would blank a tile
    on the strength of a keep-alive. One resource, one measurement, one rule.

    Matched on the whole `alarms` segment rather than a suffix. A suffix test reads
    the same and quietly claims anything ending in those letters — no
    `/kimchialarms/vs/0` exists on any dump, so that would have been a misfire
    waiting for a resource nobody has measured, on the one code path whose job is
    to throw the cache away.
    """
    segments = href.strip("/").split("/")
    return len(segments) >= 3 and segments[-3:-1] == ["alarms", "vs"]


def _fold_write_into(cached: dict, body: dict) -> None:
    """Apply a write payload to the cached representation, in place, without
    discarding the fields the payload did not mention.

    A plain `dict.update` looks right and silently truncates. Samsung's
    list-shaped resources are written by sending one entry carrying only the id
    and the field being changed — a setpoint write sends

        {"...items": [{"...id": "0", "...desired": "28.0"}]}

    and `update` replaces the whole list with that, so until the next poll the
    cached entry has lost `current`, `minimum`, `maximum` and `increment`.
    Measured consequences on the air conditioner: `measure_temperature` reads
    None so the current-temperature tile goes blank, and the setpoint's options
    collapse to `{}` so the slider loses its range and step. A second write in the
    same Flow is then formatted with no increment to snap to.

    Entries are matched on their id rather than by position: nothing guarantees a
    write payload lists them in the order the device reports them.
    """
    for key, value in body.items():
        current = cached.get(key)
        if key == ITEMS_FIELD and isinstance(value, list) and isinstance(current, list):
            cached[key] = _fold_items(current, value)
        else:
            cached[key] = value


def _fold_items(cached: list, written: list) -> list:
    merged = [dict(item) if isinstance(item, dict) else item for item in cached]
    for patch in written:
        if not isinstance(patch, dict):
            continue
        target = next(
            (item for item in merged
             if isinstance(item, dict) and item.get(ITEM_ID) == patch.get(ITEM_ID)),
            None,
        )
        if target is None:
            merged.append(dict(patch))
        else:
            target.update(patch)
    return merged


class ApplianceDevice(device.Device):

    async def on_init(self) -> None:
        store = self.get_store()
        self._host = store.get(STORE_HOST)
        self._port = int(store.get(STORE_PORT))
        self._serial = str(store.get(STORE_SERIAL) or "")
        self._failures = 0
        self._registry = None
        self._resources: dict = {}
        # /oic/d's `rt`. Read once per session rather than per poll: it is a
        # static declaration of what the appliance is, and it costs a GET the
        # batch response cannot fold in.
        self._device_types: tuple = ()
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
        # Consecutive attempts that produced no notification at all. Widens the
        # retry interval, so a device whose push channel is simply dead is not
        # re-subscribed every ten minutes forever.
        self._observe_silent_rounds = 0
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

The judgment is deliberately not made here. The initial notifications keep
        arriving after the subscribes are sent, so deciding from inside a fixed sleep
        reaches a verdict before the evidence is in. That is what made a device with
        21 of 22 resources notifying get recorded as push-unavailable.

        This used to add that the subscribes themselves take over four seconds
        because "the library paces CON sends at 5/s". They do not: `subscribe()` is
        fire-and-forget and the library's `pace()` has a single call site, inside the
        Block2 loop for block index > 0. Twenty-seven subscribes leave in
        microseconds — which is its own problem, since they arrive back-to-back at an
        appliance with a minimum send interval, but it is not a delay here.
        """
        now = time.monotonic()
        if self._observe_pending:
            return
        if self._observing:
            if now - self._subscribed_at < OBSERVE_REFRESH_S:
                return
        elif (self._observe_attempted_at
              and now - self._observe_attempted_at < self._observe_retry_after()):
            return

        hrefs = self._observable_hrefs()
        if not hrefs:
            return

        self._observe_attempted_at = now
        self._notified.clear()
        self._observe_hrefs = set(hrefs)
        failed = 0
        for index, href in enumerate(hrefs):
            if index:
                # Spaced, because the appliance drops the initial notifications when
                # the registrations arrive back to back — see
                # OBSERVE_SUBSCRIBE_SPACING_S. `asyncio.sleep`, not the library's
                # `time.sleep`: this must not hold an executor thread, since all nine
                # appliances subscribe at once when the app starts.
                await asyncio.sleep(OBSERVE_SUBSCRIBE_SPACING_S)
            try:
                await self._session.subscribe(href.strip("/").split("/"))
            except Exception as exc:
                failed += 1
                self.log(f"subscribe {href} failed: {exc}")
        self._subscribed_at = time.monotonic()
        self._observe_pending = True
        self._observe_failed = failed
        self.log(f"subscribed to {len(hrefs) - failed}/{len(hrefs)} resources")

    async def _drop_to_polling(self) -> None:
        """Stop claiming push, and make the settings say so.

        Deliberately does not touch `_observe_silent_rounds` or
        `_observe_attempted_at`: the backoff those drive is about a channel that
        subscribes and then stays quiet, which is a different fault from a device
        that cannot be reached at all. Widening the retry window because the
        appliance was unplugged would leave it polling long after it came back.
        """
        if not (self._observing or self._observe_pending):
            return
        self._observing = False
        self._observe_pending = False
        await self._sync_settings()

    def _observe_retry_after(self) -> float:
        """How long to wait before subscribing again after giving up.

        A device that answers *some* notifications is worth retrying on the normal
        cadence — the channel works and only fell under the threshold. One that
answers none is a different case, and the living-room air conditioner here
        is it: 27 resources subscribed, not one notification, ever. Retrying that
        every ten minutes costs 27 CON subscribes each time and leaves another 27
        observer registrations on an appliance the library already warns remembers
        them across sessions. Left alone that is roughly 3,900 pointless requests a
        day.

        The cost used to be described as "over five seconds of exclusive session time
        while polls queue behind it". That was wrong — `Session.subscribe` takes the
        lock per href and the library does not pace subscribes at all, so nothing
        queues for seconds. The waste is the requests and the registrations, not a
        held lock.

        So silence doubles the wait, up to the refresh interval. Any notification
        at all resets it, as does a rebuilt session.
        """
        if not self._observe_silent_rounds:
            return OBSERVE_RETRY_S
        widened = OBSERVE_RETRY_S * (2 ** min(self._observe_silent_rounds, 8))
        return min(widened, OBSERVE_REFRESH_S)

    def _evaluate_observe(self) -> None:
        """Decide push vs poll once the grace period has actually elapsed."""
        if not self._observe_pending:
            return
        if time.monotonic() - self._subscribed_at < OBSERVE_GRACE_S:
            return

        hrefs = self._observe_hrefs
        got = len(self._notified & hrefs)
        # `got` counts two things at once, and comparing it across devices without
        # allowing for that has been wrong twice. A registration's response *is* its
        # first notification — two switched-off units read 27/27 shortly after an
        # install, which nothing else explains — so on a healthy channel a quorum is
        # a fair test. But `_notified` is only cleared at re-subscribe, so it also
        # accumulates real changes: an idle unit went 0 -> 7 in 70s when switched on,
        # with `_observe_silent_rounds` and the retry window untouched.
        #
        # So two devices' counts mean the same thing only at the same offset from
        # their last re-subscribe. Both earlier attempts to tune this ignored that:
        # requiring one notification, then restoring 0.8 on the strength of four
        # switched-off units reading 27, 26, 3 and 6 of 27 — a spread that is about
        # where each sat in a six-hour cycle, not about the channel.
        #
        # Left alone deliberately, and the threshold is not what is worth fixing:
        # delivery of the initial notifications is variable enough that no single
        # round decides anything. One switched-off unit, sampled at the same offset
        # after four app starts, read 27/27, 27/27, 27/27 and 8/27 — so this verdict
        # can flip with nothing having changed. Failing it costs polling, never
        # correctness. docs/BACKLOG.md has the rounds and the miss-detection metric
        # that would judge push without depending on registration-time delivery.
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
                    f"{self._observe_failed} subscribe errors); polling, "
                    f"next attempt in {self._observe_retry_after():.0f}s"
                )
            self._observing = False

        # Keyed on the verdict, not on "anything at all". `if got:` was truthy for a
        # round that delivered 3 of 27, so the backoff reset every time and the retry
        # stayed at OBSERVE_RETRY_S forever — which is the re-subscribe churn that
        # was mistakenly attributed to the threshold and then fixed at the wrong end.
        # A round that misses the quorum is not evidence the channel works.
        if got >= needed:
            self._observe_silent_rounds = 0
        else:
            self._observe_silent_rounds += 1

    def _on_notification(self, href: str, rep: dict) -> None:
        """A pushed resource update. Called on the event loop by Session."""
        self._notified.add(href)
        self._last_notify_at = time.monotonic()
        deadline = self._settling.get(href)
        if deadline and time.monotonic() < deadline:
            # Mid-settle after a write: the device may still be reporting the old
            # value, which would undo the optimistic one.
            return
        if _replaces_on_notify(href):
            self._resources[href] = dict(rep)
        else:
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
                # A failed poll never reaches `_evaluate_observe` or
                # `_sync_settings`, so an appliance that drops off the network — off
                # at the breaker, Wi-Fi down — used to keep claiming push for as long
                # as it stayed away: the advanced settings read "push, 27
                # subscriptions" and the `is_pushing` Flow condition stayed true,
                # hours after the session it counted had gone. Nothing can be
                # arriving by push down a channel whose reads are failing, so say so.
                # No resubscribe is attempted here; there is no live session to
                # register on, and `_try_observe` picks it up once polling recovers.
                await self._drop_to_polling()
                # Only a persistent failure reaches the user. The first few are
                # retried quietly: a restarted app leaves the appliance holding an
                # orphaned DTLS association and the first handshake into it is
                # refused, which the app recovers from on its own. Reporting that
                # put protocol internals on a tile for something self-healing.
                if self._failures >= UNAVAILABLE_AFTER_FAILURES:
                    await self.set_unavailable(self._unavailable_reason(exc))
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

    def _unavailable_reason(self, exc: Exception) -> str:
        """What to tell the user when the appliance stays unreachable.

        Never `str(exc)`. That is where "DTLS handshake error (SSL routines, tlsv1
        alert decode error)" came from — accurate, and no help to someone looking at
        a greyed-out tile. The two causes a user can act on are told apart: an
        appliance that will not complete a handshake, and one that is not answering
        at all.
        """
        if probe.peer_holds_stale_session(exc):
            return i18n.translate("error.handshake_refused", self._language)
        return i18n.translate("error.unreachable", self._language,
                              host=str(self._host))

    def _identity_is_verifiable(self) -> bool:
        """Whether the stored serial can actually prove identity.

        read_serial falls back to "host:port" for firmware that reports a
        placeholder serial, and that fallback stops being meaningful the moment the
        address changes — so those devices are relocated but not identity-checked.
        """
        return bool(self._serial) and ":" not in self._serial

    async def refresh_now(self) -> None:
        """Re-read the appliance and apply what it reports, without waiting for the
        next poll.

        For a Flow card that applies several settings in sequence: each step has to
        decide from what the appliance holds *now*, not from a cache that is up to
        OBSERVE_SWEEP_INTERVAL_S old once the device is on push. Raises what the
        poll would have raised, so a card fails rather than acting on nothing.

        Deliberately not `_poll_once`: that also advances the push lifecycle, which a
        Flow card has no business doing. See `_poll_once`.
        """
        await self._read_and_apply()

    async def check_now(self) -> dict:
        """Read `/device/0` over this device's own session, for Repair to test with.

        Deliberately not a fresh `probe.probe` at the stored address. This app pins
        one UDP source port per appliance so that a reconnect reuses the same
        5-tuple and the appliance evicts any orphaned association (RFC 6347 §4.2.8)
        — which is exactly what a second session to the same address would trigger
        against the *live* one. Testing a healthy device would then destroy its
        subscriptions, and nothing would tell it: `_observing` stays True, so
        `_try_observe` does not resubscribe until OBSERVE_REFRESH_S (six hours) has
        passed, leaving it silently degraded to the five-minute sweep.

        Using the live session also tests the path the device actually uses, and it
        reconnects on its own if the session had dropped.
        """
        resources = await self._session.read_device0()
        return {
            "host": self._host,
            "port": self._port,
            "serial": read_serial(resources, self._host, self._port),
        }

    async def move_to(self, host: str, port: int) -> None:
        """Point this device at a new address, taking the live session with it.

        The single entry point for relocation, called both by the automatic sweep
        below and by Repair in the driver. Repair used to write only the store,
        which looks equivalent and is not: nothing re-reads the store. There is no
        store-change hook in the SDK — `on_init` reads it once — so the running
        device kept its old address, kept polling it, and kept showing it in the
        advanced settings, while Repair reported success. The change took effect
        only on the next app restart.

        Every step here matters. The old session is closed first so its socket and
        the appliance's association go away rather than lingering — this app pins a
        source port per device, so a session left open holds the port the new one
        needs. The observe flags are cleared because the subscriptions belonged to
        the session that just closed.
        """
        cert_pem = await compat.setting_get(self.homey, SETTING_LEAF_CERT)
        key_pem = await compat.setting_get(self.homey, SETTING_LEAF_KEY)
        if not cert_pem or not key_pem:
            raise RuntimeError(i18n.translate("error.no_credentials", self._language))

        with contextlib.suppress(Exception):
            await self._session.close()
        await self._remember_location(host, port)
        self._session = Session(
            self._host, self._port, cert_pem, key_pem,
            log=self.log, on_notification=self._on_notification,
        )
        self._observing = False
        self._observe_pending = False
        self._observe_attempted_at = 0.0
        # A new session is a new channel: whatever was wrong with the old one is
        # not evidence about this one.
        self._observe_silent_rounds = 0
        await self._sync_settings()

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
            await self.move_to(host, result["port"])
            return True

        self.log(f"{self._serial} not found on the network")
        return False

    async def _poll_once(self) -> None:
        """One scheduled poll: read the appliance, then advance the push lifecycle."""
        await self._read_and_apply()
        # The lifecycle belongs to the poll loop and to nothing else. It used to sit
        # in the same method the Flow card calls through `refresh_now`, so applying a
        # setting could fire a 27-resource subscribe round and flip the device between
        # push and polling **in the middle of the card** — `_try_observe` is only
        # time-gated, so it fires mid-card exactly when the retry window has elapsed,
        # which is the state a device with a struggling channel lives in.
        self._evaluate_observe()
        await self._try_observe()
        await self._sync_settings()

    async def _read_and_apply(self) -> None:
        """Read `/device/0` and push every value into its capability.

        Shared by the poll loop and by `refresh_now`, rather than duplicated, so the
        two cannot drift apart — drift is how the observe lifecycle ended up running
        inside a Flow card in the first place.

        `_sync_capabilities` stays here deliberately. Leaving it to the poll loop
        would mean a card could ask to write a capability the device has not been
        given yet and raise, and it is the same call that let an already-paired range
        hood pick up a corrected mapping without being deleted and re-added. It
        compares before acting, so a card run costs a comparison.
        """
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
            self._device_types = await self._read_device_types()
            self._registry = registry.resolve(self._resources, self._device_types)
            if self._registry is None:
                raise RuntimeError(i18n.translate("error.not_recognised", self._language))
            unbound = registry.unbound_hrefs(self._resources, self._registry)
            self.log(
                f"registry {self._registry.name}, "
                f"oic.d {list(self._device_types) or 'absent'}, "
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

    async def _read_device_types(self) -> tuple:
        """`/oic/d`'s `rt`, or an empty tuple if this appliance will not give it.

        Every failure here is swallowed on purpose. This is an *additional* signal —
        the board-token path resolved every appliance in this house without it — so a
        board that answers 4.04, times out, or returns something unexpected must fall
        back to the way that already worked. Letting this raise would turn a
        supplementary read into a new way for pairing to fail, on exactly the
        unfamiliar hardware it exists to help.
        """
        try:
            rep = await self._session.read_resource(["oic", "d"])
        except Exception as exc:
            self.log(f"/oic/d unavailable ({type(exc).__name__}: {exc})")
            return ()
        types = (rep or {}).get("rt")
        if isinstance(types, str):
            types = [types]
        if not isinstance(types, (list, tuple)):
            return ()
        # 'oic.wk.d' is on every device and names nothing; keeping it would only
        # make the log noisier.
        return tuple(str(t) for t in types if str(t) != "oic.wk.d")

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
            previous = self.get_capability_value(spec.capability)
            if previous != value:
                await self.set_capability_value(spec.capability, value)
                await self._note_on_timeline(spec.capability, previous, value)
            await self._maybe_trigger(spec.capability, value)

    # Homey writes its own timeline line whenever a *boolean* capability with
    # insight titles changes — that is how power and the absence sensor get there,
    # and why auto dry and the self check now do. It cannot do the same for these
    # two: a number becomes a chart and nothing else, and no capability of type
    # string anywhere in Homey's own library sets `insights`, so a mode change
    # leaves no trace at all. These are written explicitly, and only these.
    _TIMELINE_CAPABILITIES = ("localthings_ac_mode", "target_temperature")

    async def _note_on_timeline(self, capability: str, previous, value) -> None:
        """Write a line to Homey's timeline for a change it cannot log itself.

        Off unless the device's `timeline_changes` setting is on. A house with
        several appliances generates a lot of these, and a timeline nobody wants is
        worse than no timeline — so the ones Homey handles natively stay native, and
        this covers only what it cannot express.

        Never raises: a failure here must not interrupt a poll, since the value has
        already been applied by this point.
        """
        if capability not in self._TIMELINE_CAPABILITIES:
            return
        if previous is None:
            # The first reading after a restart is not a change the user made.
            return
        try:
            if not (self.get_settings() or {}).get("timeline_changes"):
                return
            message = i18n.translate(
                f"timeline.{capability}", self._language,
                name=self.get_name(), value=self._label_value(capability, value),
                previous=self._label_value(capability, previous))
            await self.homey.notifications.create_notification(message)
        except Exception as exc:
            self.log(f"timeline note for {capability} failed: {exc}")

    def _label_value(self, capability: str, value) -> str:
        """The value as a user would recognise it, not as the wire spells it."""
        if capability == "target_temperature":
            return f"{value}"
        return str(i18n.translate(f"ac_mode.{value}", self._language) or value)

    async def _maybe_trigger(self, capability: str, value) -> None:
        """Fire a trigger for a *sub*-capability. Homey handles the rest itself.

        Homey runs a Flow trigger named for the capability whenever
        set_capability_value changes a custom one — `<capability>_true` /
        `<capability>_false` for a boolean, `<capability>_changed` otherwise — so
        plain capabilities need no code here at all, and the cards are named to match.

        Sub-capabilities are the exception. Homey would look for a card called
        `localthings_alarm_hot_surface.2_true`, which cannot exist, so a cooktop's
        per-burner residual-heat alarm and a purifier's per-filter alarm would never
        trigger anything. Those fire the base capability's card from here.

        Change-gated on the previous value: this runs on every poll, and the
        capability's current value is already the new one by the time it is called, so
        comparing against Homey's copy would fire nothing.
        """
        if "." not in capability:
            return                      # Homey's convention covers it

        previous = self._previous.get(capability, "__unset__")
        self._previous[capability] = value
        if previous == "__unset__" or previous == value:
            return

        base = capability.split(".")[0]
        card_id = f"{base}_true" if value else f"{base}_false"
        if not isinstance(value, bool):
            card_id = f"{base}_changed"
        if card_id not in self._trigger_cards():
            return
        try:
            tokens = {} if isinstance(value, bool) else {base: str(value)}
            await self._trigger(card_id, tokens)
        except Exception as exc:
            self.log(f"trigger {card_id} for {capability} failed: {exc}")

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
        _fold_write_into(merged, body)
        try:
            applied = spec.read(merged, self._resources)
        except Exception:
            applied = None
        await self.set_capability_value(
            capability, value if applied is None else applied
        )


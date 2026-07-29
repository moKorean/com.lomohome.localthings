"""One paired Samsung appliance.

Holds a sustained DTLS session, polls /device/0 on an interval, and writes
capability changes straight to the appliance. The equivalent of the reference
integration's coordinator, minus the OBSERVE path (docs/PORTING.md milestone 6) —
so state is poll-driven for now.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from homey import device  # noqa: E402

from lib import compat, registry  # noqa: E402
from lib.const import (  # noqa: E402
    POLL_INTERVAL_S,
    SETTING_LEAF_CERT,
    SETTING_LEAF_KEY,
    STORE_HOST,
    STORE_PORT,
)
from lib.session import Session  # noqa: E402


class Device(device.Device):

    async def on_init(self) -> None:
        store = self.get_store()
        self._host = store.get(STORE_HOST)
        self._port = int(store.get(STORE_PORT))
        self._registry = None
        self._resources: dict = {}
        self._poll_task = None

        # The certificate lives at app level, not in the device store, so
        # rotating it repairs every paired appliance at once instead of needing
        # each one re-paired.
        self._session = Session(
            self._host,
            self._port,
            await compat.setting_get(self.homey, SETTING_LEAF_CERT),
            await compat.setting_get(self.homey, SETTING_LEAF_KEY),
            log=self.log,
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
        try:
            return float(self.get_settings().get("poll_interval") or POLL_INTERVAL_S)
        except (TypeError, ValueError):
            return POLL_INTERVAL_S

    async def _poll_loop(self) -> None:
        # Back off on repeated failure rather than hammering a device that is
        # unplugged or asleep; the appliance firmware drops requests when hit
        # faster than its ceiling.
        failures = 0
        while True:
            try:
                await self._poll_once()
                failures = 0
                delay = self._poll_interval()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                delay = min(self._poll_interval() * min(failures, 6), 300)
                self.log(f"poll failed ({failures}): {exc}; retrying in {delay:.0f}s")
                await self.set_unavailable(str(exc))
            await asyncio.sleep(delay)

    async def _poll_once(self) -> None:
        if not await compat.setting_get(self.homey, SETTING_LEAF_CERT):
            # Distinct from a network failure, and fixable in one place, so say
            # where rather than reporting a bare connection error.
            raise RuntimeError(
                "No client certificate configured. Set one up in "
                "Settings -> Apps -> LocalThings."
            )
        self._resources = await self._session.read_device0()
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

    async def _apply(self, resources: dict) -> None:
        """Push every readable value into its capability.

        A spec returning None is skipped rather than written as null: a missing
        field or a stub rep must not overwrite a good value with a wrong one.
        """
        for spec in self._registry.specs:
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

        path_segs, body = payload
        self.log(f"write {capability}={value!r} -> /{'/'.join(path_segs)} {body}")
        response = await self._session.write(path_segs, body)
        if not Session.write_accepted(response):
            raise RuntimeError(f"The appliance rejected {capability}={value!r}")

        # Optimistic apply, so the tile reflects the change before the next
        # poll. The device confirmed the write, so this is not a guess.
        self._resources.setdefault(spec.href, {}).update(body)
        await self.set_capability_value(capability, value)


homey_export = Device

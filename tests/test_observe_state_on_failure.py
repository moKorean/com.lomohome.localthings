"""An unreachable appliance must stop claiming push.

`_poll_once` advances the push lifecycle *after* it reads the appliance, so a read
that raises skips both the verdict and the settings sync. An appliance that drops
off the network — off at the breaker, Wi-Fi down, moved by DHCP — therefore kept
`_observing` true for as long as it stayed away: the advanced settings went on
reporting "push, 27 subscriptions" and the `is_pushing` Flow condition went on
answering true, for a channel whose every read was failing.

The count is what makes this more than cosmetic. `Session._subscribed` survives a
close on purpose, because `_connect_unlocked` replays it to re-register after a
reconnect — so `subscription_count` keeps reporting the intent even when there is
no session at all, and nothing else contradicts it.

Tested against the source for `_poll_loop`, as the other device tests are: no
fixture can stand in for a DTLS session, and a stubbed poll loop would be testing
the stub.
"""

import ast
import asyncio
import sys
import types
from pathlib import Path

import pytest

DEVICE_SOURCE = Path(__file__).parent.parent / "lib" / "appliance" / "device.py"


@pytest.fixture
def Device():
    """The real Device class with the runtime-provided `homey` module stubbed —
    the same trick test_repair.py uses for the driver. `homey` only exists inside
    Homey's own container, so importing the module is the whole difficulty here."""
    stub = types.ModuleType("homey")
    device_module = types.ModuleType("homey.device")

    class HomeyDevice:
        def log(self, *args):
            pass

    device_module.Device = HomeyDevice
    stub.device = device_module
    saved = {name: sys.modules.get(name) for name in ("homey", "homey.device")}
    sys.modules["homey"], sys.modules["homey.device"] = stub, device_module
    try:
        from lib.appliance.device import ApplianceDevice as real
        yield real
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _function(name):
    tree = ast.parse(DEVICE_SOURCE.read_text())
    return next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and node.name == name
    )


class _Stub:
    """Just the attributes `_drop_to_polling` touches."""

    def __init__(self, observing=False, pending=False):
        self._observing = observing
        self._observe_pending = pending
        self._observe_silent_rounds = 3
        self._observe_attempted_at = 123.0
        self.synced = 0

    async def _sync_settings(self):
        self.synced += 1


def _drop(Device, stub):
    asyncio.run(Device._drop_to_polling(stub))


def test_a_failed_poll_stops_claiming_push():
    handler = next(
        node for node in ast.walk(_function("_poll_loop"))
        if isinstance(node, ast.ExceptHandler)
        and "Exception" in ast.unparse(node.type or ast.Constant(None))
    )
    assert "_drop_to_polling" in ast.unparse(handler), (
        "a poll failure leaves the device reporting push"
    )


def test_dropping_to_polling_clears_the_state_and_tells_the_settings(Device):
    stub = _Stub(observing=True)
    _drop(Device, stub)
    assert stub._observing is False
    assert stub.synced == 1, "the settings still show the old mode"


def test_a_pending_verdict_is_abandoned_too(Device):
    """A subscribe burst that was still awaiting its verdict when the device went
    away has nothing left to judge — its notifications cannot arrive on a session
    that is gone, and leaving it pending blocks the next attempt."""
    stub = _Stub(pending=True)
    _drop(Device, stub)
    assert stub._observe_pending is False


def test_the_backoff_is_left_alone(Device):
    """The widening retry window is for a channel that subscribes and then stays
    quiet. An appliance that was simply unplugged is a different fault, and
    widening its window would leave it polling long after it came back."""
    stub = _Stub(observing=True)
    _drop(Device, stub)
    assert stub._observe_silent_rounds == 3
    assert stub._observe_attempted_at == 123.0


def test_a_device_already_polling_is_not_re_synced(Device):
    """`_sync_settings` compares before writing, but the poll loop calls this on
    every failure of a device that may be down for hours."""
    stub = _Stub()
    _drop(Device, stub)
    assert stub.synced == 0


# --- silent hrefs keep the poll fast --------------------------------------
#
# Push mode drops polling to a 300s summary sweep, which is only safe for
# resources that actually push. Entering push on a quorum means up to a fifth of
# the subscribed set can be silent and still pass the verdict, and those readings
# were then refreshed only by the sweep. Upstream hit the same thing as issue #92
# with a 30s window; ours was ten times worse.


class _Cadence:
    """Just what _poll_interval and silent_hrefs touch."""

    def __init__(self, observing, subscribed, notified):
        self._observing = observing
        self._observe_hrefs = set(subscribed)
        self._notified = set(notified)

    def get_settings(self):
        return {"poll_interval": 30}


def _interval(Device, observing, subscribed, notified):
    stub = _Cadence(observing, subscribed, notified)
    stub.silent_hrefs = lambda: Device.silent_hrefs(stub)
    return Device._poll_interval(stub)


def test_push_slows_the_poll_only_when_every_href_answered(Device):
    fast = _interval(Device, True, {"/a", "/b"}, {"/a", "/b"})
    from lib.const import OBSERVE_SWEEP_INTERVAL_S
    assert fast == OBSERVE_SWEEP_INTERVAL_S


def test_a_silent_href_keeps_the_normal_cadence(Device):
    """The bug: subscribed, never notified, so nothing refreshed it for up to the
    whole sweep — on values like power and the setpoint."""
    assert _interval(Device, True, {"/a", "/b"}, {"/a"}) == 30


def test_polling_mode_is_unaffected(Device):
    assert _interval(Device, False, {"/a"}, {"/a"}) == 30


def test_the_silent_set_is_the_subscribed_set_minus_what_answered(Device):
    stub = _Cadence(True, {"/a", "/b", "/c"}, {"/b"})
    assert sorted(Device.silent_hrefs(stub)) == ["/a", "/c"]


def test_nothing_subscribed_yet_does_not_look_silent(Device):
    """Before the first subscribe round there is no evidence either way, and an
    empty subscribed set must not read as "everything is silent" and pin a
    pushing device to the fast cadence forever."""
    stub = _Cadence(True, set(), set())
    assert Device.silent_hrefs(stub) == set()
    from lib.const import OBSERVE_SWEEP_INTERVAL_S
    assert _interval(Device, True, set(), set()) == OBSERVE_SWEEP_INTERVAL_S

"""A refused write during power-on must not abort the combined card.

`_apply_step` already re-sent a setting the appliance accepted and then undid. It
did not re-send one the appliance *refused*, because a rejected write raises out of
the capability listener — so the first refusal ended the card.

That is exactly what a unit that has just been switched on does. Measured
2026-08-09 on the 손님방 air conditioner: writing `Speed` while it was off answered
`controlResponse result False`, and three units that succeeded in the same minute
did so 6-8 seconds after their power write was acknowledged. So the combined card's
most ordinary use — "turn it on and put it in Speed" — failed on a combination the
appliance accepts a moment later.

Nothing on the wire predicts it. `/mode/convenient/vs/0` advertises all six comfort
modes whether the unit is on or off and keeps advertising them through the
transition, so the supported list cannot be consulted first; `_write_enum`'s gate
sees a mode the device claims to support and sends it. Retrying is the only thing
left, which is why the attempt budget rather than a lookup is what fixes this.

The last two tests are the boundary: retrying forever would turn a write the
appliance will never take into a hang, and the induction cooktop is the standing
proof that such writes exist.
"""

import asyncio
import sys
import types

import pytest


@pytest.fixture
def driver():
    """The real driver class with the runtime-provided `homey` module stubbed, the
    way test_repair.py does it."""
    stub = types.ModuleType("homey")
    driver_module = types.ModuleType("homey.driver")

    class Driver:
        def log(self, *args):
            pass

    driver_module.Driver = Driver
    stub.driver = driver_module
    saved = {name: sys.modules.get(name) for name in ("homey", "homey.driver")}
    sys.modules["homey"], sys.modules["homey.driver"] = stub, driver_module
    try:
        from lib.appliance.driver import ApplianceDriver
        instance = object.__new__(ApplianceDriver)
        instance.log = lambda *args: None
        instance.homey = object()
        yield instance
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class FakeDevice:
    """Refuses the first `refusals` writes, then accepts and holds the value."""

    def __init__(self, refusals=0, never_accepts=False):
        self.refusals = refusals
        self.never_accepts = never_accepts
        self.attempts = 0
        self.value = None

    async def trigger_capability_listener(self, capability, value):
        self.attempts += 1
        if self.never_accepts or self.attempts <= self.refusals:
            raise RuntimeError("write rejected: 쾌적 모드")
        self.value = value

    async def refresh_now(self):
        pass

    def get_capability_value(self, capability):
        return self.value


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """The settle sleep is real time and there is nothing to wait for here."""
    async def instant(_seconds):
        return None
    monkeypatch.setattr(asyncio, "sleep", instant)


@pytest.fixture(autouse=True)
def language(monkeypatch):
    from lib import compat
    async def ui_language(_homey):
        return "en"
    monkeypatch.setattr(compat, "ui_language", ui_language)


def apply(driver, device, strict=True):
    return asyncio.run(driver._apply_step(
        device, "localthings_convenient_mode", "Speed", strict=strict))


@pytest.mark.parametrize("refusals", [1, 2, 3])
def test_a_refusal_inside_the_budget_is_retried(driver, refusals):
    device = FakeDevice(refusals=refusals)
    assert apply(driver, device) is True
    assert device.attempts == refusals + 1
    assert device.value == "Speed"


def test_the_power_on_window_fits_in_the_budget(driver):
    """The measured window is 6-8s and attempts leave ~2.5s apart, so a unit that
    refuses for three attempts still gets its setting on the fourth. If the budget
    is ever reduced, this is the test that should stop it."""
    assert driver._AC_ATTEMPTS * driver._AC_SETTLE_S >= 8.0


def test_a_write_the_appliance_never_takes_still_fails(driver):
    """Bounded, not a loop. The induction cooktop refuses every write it is sent,
    and a card that retried forever would hang instead of reporting it."""
    device = FakeDevice(never_accepts=True)
    with pytest.raises(RuntimeError):
        apply(driver, device)
    assert device.attempts == driver._AC_ATTEMPTS


def test_reconciliation_reports_rather_than_raises(driver):
    """`strict=False` is how the reconcile pass calls this: a setting that will not
    hold is a conflict for the caller to name, not an error from here."""
    device = FakeDevice(never_accepts=True)
    assert apply(driver, device, strict=False) is False
    assert device.attempts == driver._AC_ATTEMPTS

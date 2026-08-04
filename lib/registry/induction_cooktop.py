"""Induction-cooktop registry (Samsung TP1X_DA-KS-COOKTOP class).

Verified against a live NV9000D-/KO4 (3 burners); its dump is in tests/fixtures/.
Field names follow the reference integration's capabilities/range.py, whose
cooktop half has the same resource shape, so other units of this board family
should bind without changes.

**Everything here is read-only, because this appliance accepts no writes at all.**
Measured 2026-08-04 with the owner at the cooktop: a POST to `/cooktop/status/vs/0`
answers **4.05 Method Not Allowed** for `power` and for `childLock` alike, with the hob
off and again with a burner running, while `smartControlState` reads `on` and GET works
throughout. A POST to the range hood in the same minute was accepted, so the transport
is fine and the refusal is this appliance's policy.

**`supportedFeatureList` is not a write contract.** `/cooktop/spec/vs/0` advertises
`[kitchenService, remoteChildLock, remotePowerOff]`, and 1.0.3 briefly shipped a power
toggle on the strength of it, reasoning that `remoteChildLock` was in the list and the
child-lock write was known to work. Both halves were wrong: the toggle failed on the
owner's first try, and the child-lock write it leaned on fails too. Whatever those
entries mean — most likely the feature is reachable through Samsung's cloud — they do
not mean this resource takes a POST. Do not rebuild a control from that list.

Heat control stays out for the separate reason the reference gives for cooktops: an
automation must not ignite one. That rule is unaffected by the above, and now moot.

**Reopening condition**: an appliance of this family that answers something other than
4.05. The payloads are recorded in docs/BACKLOG.md, so nothing needs rediscovering —
`{"power": "off"}` and `{"childLock": "on"|"off"}` on `/cooktop/status/vs/0`.
"""

import math

from . import shared
from .base import Registry, Spec, as_float, as_int

HREF_STATUS = "/cooktop/status/vs/0"
HREF_SPEC = "/cooktop/spec/vs/0"
HREF_SAFETY = "/cooktop/settings/status/vs/0"
HREF_PROBE = "/bluetooth/probe/status/vs/0"
HREF_ENERGY = "/energy/consumption/vs/0"

# Observed 3; the reference has seen 4 and users report 5. Declared generously and
# gated by presence, so an unused slot simply never binds.
MAX_BURNERS = 6


def _burner(rep: dict, index: int):
    for burner in rep.get("burnerList") or ():
        if isinstance(burner, dict) and burner.get("burnerNumber") == index:
            return burner
    return None


def _burner_exists(index: int):
    return lambda rep, _resources: _burner(rep, index) is not None


_BURNER_IDLE = {"ready", "off", "none", "stop", ""}


def _burner_running(burner: dict) -> bool:
    return str(burner.get("operationState") or "").strip().lower() not in _BURNER_IDLE


def _burner_field(index: int, field: str):
    def read(rep, _resources):
        burner = _burner(rep, index)
        return None if burner is None else burner.get(field)

    return read


def _burner_hot_surface(index: int):
    def read(rep, _resources):
        burner = _burner(rep, index)
        if burner is None:
            return None
        state = burner.get("hotSurfaceState")
        return None if state is None else str(state).lower() != "normal"

    return read


def _burner_pan(index: int):
    """Cookware detected on a burner that is running, and False when none is.

    An idle hob reports `panDetection: true` on **every** burner — the captured dump,
    a live read six days later, and a third reading all show it with the appliance off
    and every burner at 0. An induction coil can only sense a ferrous load while it is
    energised, so an idle `true` is not a measurement.

    The gate first returned None while idle, which was worse: None means "leave the
    capability alone", so the owner's burner 2 sat at "pan detected" long after the
    cooking finished — the exact display the gate existed to prevent, arrived at from
    the other side. Reported: it turns to yes when a burner starts and never clears.

    So the reading is now explicitly False whenever no measurement is being made, and
    the capability means "a running burner has cookware on it". A stale True claims
    something about right now; a False claims nothing is being detected right now,
    which is true.
    """

    def read(rep, _resources):
        burner = _burner(rep, index)
        if burner is None:
            return None
        if not _burner_running(burner):
            return False
        detected = burner.get("panDetection")
        return None if detected is None else bool(detected)

    return read


def _burner_remaining_minutes(index: int):
    """Minutes left on a burner's own timer, and 0 when none is set.

    `timer.remainingTime` is in **seconds — confirmed on the appliance**, not assumed:
    the owner set a burner timer and the capability read the right number of minutes
    and counted down with it. That closes the question this docstring used to leave
    open, and the assumption it was based on (`safetyAlert.settingTime` is 3600 for the
    one-hour shutoff, so durations on this board are seconds) held.
    """

    def read(rep, _resources):
        burner = _burner(rep, index)
        if burner is None:
            return None
        timer = burner.get("timer")
        if not isinstance(timer, dict):
            return None
        seconds = as_int(timer.get("remainingTime"))
        if seconds is None or seconds < 0:
            return None
        # 0 rather than None when no timer is set. None means "leave the capability
        # alone", which left a cancelled timer showing its last count forever —
        # reported by the owner after cancelling one.
        return math.ceil(seconds / 60)

    return read


def _on_off(field: str):
    def read(rep, _resources):
        value = rep.get(field)
        return None if value is None else str(value).lower() == "on"

    return read


def _read_safety_shutoff(rep, _resources):
    alert = rep.get("safetyAlert")
    if not isinstance(alert, dict):
        return None
    state = alert.get("state")
    return None if state is None else str(state).lower() == "on"


def _read_power_watts(rep, _resources):
    """Instantaneous draw, or None when the device isn't reporting one.

    The verified unit reports -500 W while idle, which is not a measurement.
    Negative values are treated as absent rather than published as a reading.
    """
    watts = as_float(rep.get("x.com.samsung.da.instantaneousPower"))
    if watts is None or watts < 0:
        return None
    return watts


def _read_meter_kwh(rep, _resources):
    total = as_float(rep.get("x.com.samsung.da.cumulativePower"))
    if total is None:
        return None
    unit = str(rep.get("x.com.samsung.da.cumulativeUnit") or "Wh").strip().lower()
    return total / 1000.0 if unit == "wh" else total


def _read_probe_connected(rep, _resources):
    state = rep.get("connectionState")
    return None if state is None else str(state).lower() == "connected"


def _probe_temperature(field: str):
    """Probe temperatures read 0 while disconnected, which is a sentinel rather
    than a reading — publishing it would show a 0 °C meat probe."""

    def read(rep, _resources):
        if str(rep.get("connectionState", "")).lower() != "connected":
            return None
        return as_float(rep.get(field))

    return read


def _read_probe_battery(rep, _resources):
    if str(rep.get("connectionState", "")).lower() != "connected":
        return None
    return as_int(rep.get("batteryPercentage"))


def _burner_specs():
    for index in range(MAX_BURNERS):
        number = index + 1
        titles = {"en": f"Burner {number}", "ko": f"{number}구"}
        exists = _burner_exists(index)
        yield Spec(
            f"localthings_burner_level.{index}", HREF_STATUS,
            _burner_field(index, "powerLevel"), exists=exists,
            titles={k: f"{v} — level" if k == "en" else f"{v} 화력" for k, v in titles.items()},
        )
        yield Spec(
            f"localthings_burner_state.{index}", HREF_STATUS,
            _burner_field(index, "operationState"), exists=exists,
            titles={k: f"{v} — state" if k == "en" else f"{v} 상태" for k, v in titles.items()},
        )
        yield Spec(
            f"localthings_alarm_hot_surface.{index}", HREF_STATUS,
            _burner_hot_surface(index), exists=exists,
            titles={k: f"{v} — hot" if k == "en" else f"{v} 잔열" for k, v in titles.items()},
        )
        yield Spec(
            f"localthings_pan_detected.{index}", HREF_STATUS,
            _burner_pan(index), exists=exists,
            titles={k: f"{v} — pan" if k == "en" else f"{v} 냄비" for k, v in titles.items()},
        )
        yield Spec(
            f"localthings_remaining_minutes.{index}", HREF_STATUS,
            _burner_remaining_minutes(index), exists=exists,
            titles={k: f"{v} — timer" if k == "en" else f"{v} 타이머" for k, v in titles.items()},
        )


REGISTRY = Registry(
    name="induction_cooktop",
    device_class="other",
    titles={"en": "Samsung Induction Cooktop", "ko": "삼성 인덕션"},
    specs=(
        Spec("localthings_power_state", HREF_STATUS, _on_off("power")),
        Spec("localthings_operation_state", HREF_STATUS,
             lambda rep, _r: rep.get("operationState")),
        # Read-only, like everything else here. See the module docstring: this
        # appliance answers 4.05 to a POST on this resource whatever the field.
        Spec("localthings_child_lock_state", HREF_STATUS, _on_off("childLock")),
        Spec("localthings_smart_control", HREF_STATUS, _on_off("smartControlState")),
        *_burner_specs(),
        Spec("localthings_safety_shutoff", HREF_SAFETY, _read_safety_shutoff),
        # The one verified type that was missing this. `CT_E_OFF` is the cooktop's
        # own idle code and shared.read_active_alarm already treats it as idle, so
        # this reads 'none' until something real is raised.
        *shared.ALARMS,
        Spec("measure_power", HREF_ENERGY, _read_power_watts),
        Spec("meter_power", HREF_ENERGY, _read_meter_kwh),
        Spec("localthings_probe_connected", HREF_PROBE, _read_probe_connected),
        Spec("measure_temperature.probe", HREF_PROBE,
             _probe_temperature("currentTemperature"),
             titles={"en": "Probe", "ko": "온도 프로브"}),
        Spec("measure_battery.probe", HREF_PROBE, _read_probe_battery,
             titles={"en": "Probe battery", "ko": "프로브 배터리"}),
    ),
)

# 'COOKTOP' is the induction/standalone board family. The reference deliberately
# keeps it distinct from its 'cooktop' registry, which is the unrelated legacy gas
# family whose burner state lives in /mode/vs/0's options array.
BOARD_TOKENS = ("COOKTOP",)

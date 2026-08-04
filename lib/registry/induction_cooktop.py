"""Induction-cooktop registry (Samsung TP1X_DA-KS-COOKTOP class).

Verified against a live NV9000D-/KO4 (3 burners); its dump is in tests/fixtures/.
Field names follow the reference integration's capabilities/range.py, whose
cooktop half has the same resource shape, so other units of this board family
should bind without changes.

**Heat controls are read-only on purpose.** The reference exposes a burner
power-level write but marks it unverified, and its gas-cooktop module states the
principle plainly: a cooktop must not be remotely ignited by an automation. Burner
levels are therefore reported and not settable here. Child lock *is* writable —
per the reference, a lock toggle is not a heat control. Adding heat control is a
decision for the app's owner, not a default.

**The appliance publishes what it accepts remotely**, in `/cooktop/spec/vs/0`'s
`supportedFeatureList`. The verified unit lists `remoteChildLock` and
`remotePowerOff` and nothing else, which is why power off is writable and power on
is not — see `_remote_feature`. The reference left `cooktop_power` read-only for
want of a live device to confirm that remote power-on would not leave a burner
running unattended; the answer here is that the appliance refuses to be switched
on at all, so only the safe direction was ever on offer.
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
    """Cookware on the burner, but only while the burner is running.

    An idle hob reports `panDetection: true` on **every** burner: both the captured
    dump and a live read six days later show all three true with the appliance off
    and all burners at level 0. An induction coil can only sense a ferrous load
    while it is energised, so treating an idle burner's `true` as a measurement
    would publish "pan present" on three burners forever.

    Unresolved: whether an idle burner ever reports false. Removing every pan and
    re-reading settles it, and would let this gate go — docs/BACKLOG.md.
    """

    def read(rep, _resources):
        burner = _burner(rep, index)
        if burner is None or not _burner_running(burner):
            return None
        detected = burner.get("panDetection")
        return None if detected is None else bool(detected)

    return read


def _burner_remaining_minutes(index: int):
    """Minutes left on a burner's own timer, or None when no timer is set.

    `timer.remainingTime` is an int and 0 on every reading taken so far, so its
    **unit is unverified**. Seconds is assumed, because the one duration on this
    appliance whose meaning is known — `safetyAlert.settingTime`, 3600 for the
    one-hour shutoff — is in seconds. One observation settles it: set a burner timer
    for a known number of minutes and read this back. 10 minutes showing 10 confirms
    seconds; showing 600 means the field was already minutes. docs/BACKLOG.md.
    """

    def read(rep, _resources):
        burner = _burner(rep, index)
        if burner is None:
            return None
        timer = burner.get("timer")
        if not isinstance(timer, dict):
            return None
        seconds = as_int(timer.get("remainingTime"))
        if not seconds or seconds < 0:
            return None
        return math.ceil(seconds / 60)

    return read


def _on_off(field: str):
    def read(rep, _resources):
        value = rep.get(field)
        return None if value is None else str(value).lower() == "on"

    return read


def _remote_feature(name: str):
    """Gate on the appliance's own list of remotely accepted features.

    `/cooktop/spec/vs/0`'s `supportedFeatureList` reads
    `[kitchenService, remoteChildLock, remotePowerOff]` on the verified unit. That
    list is trustworthy as a gate for one concrete reason rather than by assumption:
    `remoteChildLock` is in it and our child-lock write is the one write on this
    appliance already proven to work, while nothing resembling burner control is in
    it and burner writes do not work. A unit that omits an entry simply never gets
    the control, which is the point — a switch that always fails is worse than no
    switch.
    """

    def supported(_rep, resources):
        features = (resources.get(HREF_SPEC) or {}).get("supportedFeatureList")
        return isinstance(features, list) and name in features

    return supported


_supports_remote_power_off = _remote_feature("remotePowerOff")


def _write_power(value, _rep):
    # Off only. `remotePowerOn` is absent from supportedFeatureList and the owner
    # confirms the appliance ignores a remote power-on, so a power-on request is
    # refused here rather than sent — these appliances acknowledge writes they will
    # not honour, so sending it would look like it worked. Spec.refusal supplies the
    # message that says which direction is available.
    if value:
        return None
    return ["cooktop", "status", "vs", "0"], {"power": "off"}


def _write_child_lock(value, _rep):
    # A lone scalar, so a single-field POST is enough — unlike burnerList, which
    # would need the sibling entries preserved.
    return ["cooktop", "status", "vs", "0"], {"childLock": "on" if value else "off"}


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
        # Two forms of the same reading, mutually exclusive: a toggle where the
        # appliance advertises remotePowerOff, a plain reading where it does not.
        # shared.py's CHILD_LOCK split makes the same call for the same reason.
        Spec("localthings_power", HREF_STATUS, _on_off("power"), _write_power,
             refusal="error.no_remote_power_on",
             exists=_supports_remote_power_off),
        Spec("localthings_power_state", HREF_STATUS, _on_off("power"),
             exists=lambda rep, resources: not _supports_remote_power_off(rep, resources)),
        Spec("localthings_operation_state", HREF_STATUS,
             lambda rep, _r: rep.get("operationState")),
        Spec("localthings_child_lock", HREF_STATUS, _on_off("childLock"),
             _write_child_lock),
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

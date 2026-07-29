"""Specs shared across appliance types.

Almost every registry in the reference composes `common.UNIVERSAL` and
`common.POWER` before adding anything of its own, and several share
`operational.OPERATIONAL_STATE`, the laundry sound settings and the water
resources. Mirroring that here means a new type costs its distinctive resources
only, and a fix to a shared reading reaches every type at once.

Field names come from the reference's capabilities/{common,operational,laundry}.py.
Where a resource exists in both an OCF-standard and a vendor form, both are declared
and presence-gated: a given board carries one or the other, so only one binds.
"""

from .base import Spec, as_float, as_int

# --- helpers ---------------------------------------------------------------


def flag(field: str, on: str = "On"):
    """Read a `<field>: "On"|"Off"` boolean."""

    def read(rep, _resources):
        value = rep.get(field)
        return None if value is None else str(value) == on

    return read


def boolean(field: str):
    """Read a genuinely boolean field, as the OCF-standard resources use."""

    def read(rep, _resources):
        value = rep.get(field)
        return None if value is None else bool(value)

    return read


def text(field: str):
    def read(rep, _resources):
        value = rep.get(field)
        return None if value is None else str(value)

    return read


def write_flag(path: list, field: str, on="On", off="Off"):
    def write(value, _rep):
        return path, {field: on if value else off}

    return write


def write_boolean(path: list, field: str):
    def write(value, _rep):
        return path, {field: bool(value)}

    return write


# --- power -----------------------------------------------------------------
# The OCF form carries a real boolean in `value`; the vendor form an On/Off string.

POWER = (
    Spec("onoff", "/power/0", boolean("value"),
         write_boolean(["power", "0"], "value")),
    Spec("onoff", "/power/vs/0", flag("x.com.samsung.da.power"),
         write_flag(["power", "vs", "0"], "x.com.samsung.da.power")),
)

# --- child lock ------------------------------------------------------------

CHILD_LOCK = (
    Spec("localthings_child_lock", "/kidslock/0", boolean("value"),
         write_boolean(["kidslock", "0"], "value")),
    Spec("localthings_child_lock", "/kidslock/vs/0",
         flag("x.com.samsung.da.kidsLock"),
         write_flag(["kidslock", "vs", "0"], "x.com.samsung.da.kidsLock")),
)

# --- remote control -------------------------------------------------------
# Read-only everywhere: it is the device's own gate on accepting writes, not a
# setting to flip from here.

REMOTE_CONTROL = (
    Spec("localthings_smart_control", "/remotectrl/0", boolean("value")),
    Spec("localthings_smart_control", "/remotectrl/vs/0",
         flag("x.com.samsung.da.remoteControlEnabled", on="true")),
)

# --- alarms ---------------------------------------------------------------

_ALARM_IDLE = {"errorcode_off", "ct_e_off", "none", ""}
_ALARM_CLEARED = {"deleted", "cleared"}


def read_active_alarm(rep, _resources):
    """First alarm the device still considers active, or 'none'.

    Cleared entries stay in the array, so items[0] would report a stale code as
    current — observed directly on the air conditioner.
    """
    items = rep.get("x.com.samsung.da.items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("x.com.samsung.da.state", "")).strip().lower() in _ALARM_CLEARED:
            continue
        code = str(item.get("x.com.samsung.da.code", "")).strip()
        if code and code.lower() not in _ALARM_IDLE:
            return code
    return "none"


ALARMS = (Spec("localthings_alarm_code", "/alarms/vs/0", read_active_alarm),)

# --- energy ---------------------------------------------------------------

HREF_ENERGY = "/energy/consumption/vs/0"


def read_power_watts(rep, _resources):
    """Instantaneous draw, or None when the device is not reporting one.

    Negative values are a not-measuring sentinel, seen as -500 W on an idle
    induction cooktop; publishing them would put nonsense in energy history.
    """
    watts = as_float(rep.get("x.com.samsung.da.instantaneousPower"))
    return None if watts is None or watts < 0 else watts


def _kwh(field: str):
    def read(rep, _resources):
        total = as_float(rep.get(field))
        if total is None:
            return None
        unit = str(rep.get("x.com.samsung.da.cumulativeUnit") or "Wh").strip().lower()
        return total / 1000.0 if unit == "wh" else total

    return read


ENERGY = (
    # Not every appliance meters instantaneous draw — a range hood reports only a
    # cumulative total. Offering the capability anyway left a power tile that could
    # never show a number, which reads as a broken app rather than as an appliance
    # without the sensor.
    Spec("measure_power", HREF_ENERGY, read_power_watts,
         exists=lambda rep, _r: "x.com.samsung.da.instantaneousPower" in rep),
    Spec("meter_power", HREF_ENERGY, _kwh("x.com.samsung.da.cumulativePower")),
    # A second, independently varying running total that some boards report
    # alongside cumulativePower — the refrigerator gives 15496 against 884883, so
    # they are counting different things rather than duplicating one figure. The
    # reference exposes both for the same reason. Presence-gated: most appliances
    # have only the first.
    Spec("meter_power.consumption", HREF_ENERGY,
         _kwh("x.com.samsung.da.cumulativeConsumption"),
         exists=lambda rep, _r: "x.com.samsung.da.cumulativeConsumption" in rep,
         titles={"en": "Consumption", "ko": "소비 전력량"}),
)

# --- water ---------------------------------------------------------------

WATER_METER = (
    Spec("localthings_water_total", "/water/consumption/vs/0",
         lambda rep, _r: as_float(rep.get("x.com.samsung.da.cumulativeWater"))),
)


def _filter_percent(rep, _resources):
    """Filter life used, as the percentage the device already reports.

    `filterUsage` is a percentage, not a running total to be divided by
    `filterCapacity` — that division was this function's original guess and it was
    wrong on every device checked. `filterCapacity` is the filter's rated life in
    `filterCapacityUnit`, which is `Hour` on all of them, so it is a duration and
    not a denominator for a percentage.

    The evidence: an air conditioner reporting usage 100 with capacity 180 also
    reports `filterStatus: wash`. Dividing gives 56%, which would not be a filter
    due for washing; 100% is. Two more filters on the same unit (27 of 2400) and a
    range hood (80 of 60 — usage above capacity, which a fraction cannot even
    express) agree.
    """
    used = as_float(rep.get("x.com.samsung.da.filterUsage"))
    if used is None:
        return None
    return round(min(max(used, 0.0), 100.0), 1)


def read_filter_alarm(rep, _resources):
    status = rep.get("x.com.samsung.da.filterStatus")
    if status is None:
        return None
    return str(status).strip().lower() not in ("normal", "")


WATER_FILTER = (
    Spec("localthings_filter_usage.water", "/filter/waterfilter/vs/0",
         _filter_percent, titles={"en": "Water filter", "ko": "정수 필터"}),
    Spec("localthings_alarm_filter.water", "/filter/waterfilter/vs/0",
         read_filter_alarm, titles={"en": "Water filter", "ko": "정수 필터"}),
)

# --- firmware / self check ------------------------------------------------

FIRMWARE = (
    Spec("localthings_firmware_update", "/otninformation/vs/0",
         flag("x.com.samsung.da.newVersionAvailable", on="true")),
)

SELF_CHECK = (
    Spec("localthings_selfcheck", "/selfcheck/vs/0",
         text("x.com.samsung.da.status")),
)

# --- operational state ---------------------------------------------------
# The cycle-driven types (washer, dryer, dishwasher, air dresser) all report here.

HREF_OPERATIONAL = "/operational/state/vs/0"

# The vendor state vocabulary, mapped to whether a cycle is actually running.
_ACTIVE_STATES = {"run", "running", "start", "started", "active"}


def _machine_state(rep, _resources):
    return text("x.com.samsung.da.state")(rep, _resources)


def _cycle_active(rep, _resources):
    state = str(rep.get("x.com.samsung.da.state") or "").strip().lower()
    if not state:
        return None
    # 'Finish' in progress means the cycle ended even while state still reads run.
    if str(rep.get("x.com.samsung.da.progress") or "") == "Finish":
        return False
    return state in _ACTIVE_STATES


def _progress_percent(rep, _resources):
    if str(rep.get("x.com.samsung.da.progress") or "") == "Finish":
        return 100
    return as_int(rep.get("x.com.samsung.da.progressPercentage"))


def _remaining_minutes(rep, _resources):
    """`remainingTime` is HHMMSS-ish or minutes depending on board; both appear as
    digit strings, so anything longer than four digits is treated as HHMMSS."""
    raw = str(rep.get("x.com.samsung.da.remainingTime")
              or rep.get("remainingTime") or "").strip()
    if not raw.isdigit():
        return None
    if len(raw) > 4:
        padded = raw.zfill(6)
        return int(padded[:2]) * 60 + int(padded[2:4])
    return int(raw)


OPERATIONAL = (
    Spec("localthings_machine_state", HREF_OPERATIONAL, _machine_state),
    Spec("localthings_cycle_active", HREF_OPERATIONAL, _cycle_active),
    Spec("localthings_progress", HREF_OPERATIONAL, _progress_percent),
    Spec("localthings_remaining_minutes", HREF_OPERATIONAL, _remaining_minutes),
)

# --- sound ---------------------------------------------------------------

def _sound_volume_options(rep, _resources) -> dict:
    """Volume bounds from the appliance, not from Homey's number defaults.

    The verified air conditioners report 0-3 in steps of 1. A slider inheriting a
    wider default range would show positions the appliance has no value for.
    """
    options = {}
    low = as_int(rep.get("minLevel"))
    high = as_int(rep.get("maxLevel"))
    step = as_int(rep.get("resolution"))
    if low is not None:
        options["min"] = low
    if high is not None:
        options["max"] = high
    if step:
        options["step"] = step
    return options


# Unusually for this codebase, these two resources use plain OCF field names with
# no vendor prefix (`mode`, `level`). That is what three air conditioners actually
# report, so the names are confirmed rather than assumed.
#
# Both stay read-only. The volume resource advertises min/max/resolution, which
# looks like an invitation to write it, but no write has been observed and the
# reference exposes neither as writable — a control that looks settable and is
# silently refused is worse than a reading.
SOUND = (
    Spec("localthings_sound_mode", "/settings/sound/mode/vs/0", text("mode")),
    Spec("localthings_sound_volume", "/settings/sound/volume/vs/0",
         lambda rep, _r: as_int(rep.get("level")),
         options=_sound_volume_options),
)

# --- doors ---------------------------------------------------------------


def _any_door_open(rep, _resources):
    """True when any compartment in the items array reports open."""
    items = rep.get("x.com.samsung.da.items")
    if not isinstance(items, list):
        return None
    seen = False
    for item in items:
        if not isinstance(item, dict):
            continue
        state = item.get("x.com.samsung.da.openState") or item.get("openState")
        if state is None:
            continue
        seen = True
        if str(state).strip().lower() in ("open", "opened", "true"):
            return True
    return False if seen else None


def read_open_state(rep):
    """A single door resource's open state.

    Both spellings are checked: most /door/* resources report a bare `openState`,
    while the family that also carries /door/onedoorfreezer/vs/0 reports it
    vendor-prefixed. Looking up only one name leaves the capability bound and
    permanently blank.
    """
    state = rep.get("openState")
    if state is None:
        state = rep.get("x.com.samsung.da.openState")
    if state is None:
        return None
    return str(state).strip().lower() in ("open", "opened", "true")


DOORS = (Spec("alarm_contact", "/doors/vs/0", _any_door_open),)


# --- the set every type starts from --------------------------------------
UNIVERSAL = ALARMS + ENERGY + FIRMWARE + SELF_CHECK + REMOTE_CONTROL + CHILD_LOCK

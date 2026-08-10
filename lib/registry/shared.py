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

FIELD_KIDS_LOCK = "x.com.samsung.da.kidsLock"


def _read_vendor_kids_lock(rep, _resources):
    """The vendor kids-lock, which reports `Ready`/`Run` — not `On`/`Off`.

    This was read through the generic On/Off `flag` helper, which meant a locked
    appliance reported unlocked: `Run` is not `On`, so the value was False either
    way and the capability could never be true. Reference #181/#183 name the
    vocabulary; every dump in their corpus reports one of those two.
    """
    value = rep.get(FIELD_KIDS_LOCK)
    return None if value is None else str(value) != "Ready"


# Both kids-lock surfaces are read-only. Reference #181/#183 measured it: the
# write sent `Enable`, a value no dump has ever reported back, and the reporter
# confirmed that writing the *correct* value (`Run`) still answered 4.05. The
# SmartThings app offers no control for it either — the resource is genuinely
# read-only on this hardware, not merely wrong-valued. Offering a switch that
# always fails is worse than offering a reading.
#
#
# Hence a capability of its own rather than the writable `localthings_child_lock`.
#
# Both examples this comment used to give for keeping the writable form have since
# been disproved, which is worth stating plainly. The induction cooktop's `childLock`
# on `/cooktop/status/vs/0` was described here as "verified on the unit here"; it
# answers 4.05 to a POST, measured with the owner at the appliance, and that cooktop
# now uses the read-only form. The water purifier's lock was given as `/lock/vs/0`,
# a resource that does not exist on that family at all.
#
# The split still earns its keep: the water purifier really does lock, through three
# separate fields on `/status/lock/vs/0` with a write contract the reference carries,
# and one shared capability would force a choice between a toggle that errors on every
# kids-lock appliance and no control on the purifier. Both forms carry the same title,
# so the split is invisible: one appliance shows a switch, another a reading.
CHILD_LOCK = (
    Spec("localthings_child_lock_state", "/kidslock/0", boolean("value")),
    Spec("localthings_child_lock_state", "/kidslock/vs/0", _read_vendor_kids_lock,
         # Only when the OCF form is absent, or an appliance carrying both would
         # bind the same capability twice.
         exists=lambda rep, resources: "/kidslock/0" not in resources),
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
    """Minutes left on the cycle.

    **`HH:MM:SS` is the only form any dump actually uses** — all twenty in the
    reference's fixtures, across washers, dryers, dishwashers, AirDressers, ovens and
    microwaves, from `00:00:00` idle to `04:09:00` running. This used to accept digit
    strings only, so it returned None on every one of them: a washer with 3h35m left
    published nothing at all, and the failure was invisible because None means "leave
    the capability alone" rather than raising.

    The bare-digit branch is kept because it costs one line and some board may yet
    send it, but nothing has been seen to.
    """
    raw = str(rep.get("x.com.samsung.da.remainingTime")
              or rep.get("remainingTime") or "").strip()
    if not raw:
        return None
    if ":" in raw:
        try:
            parts = [int(p) for p in raw.split(":")]
        except ValueError:
            return None
        if len(parts) == 3:
            hours, minutes, seconds = parts
        elif len(parts) == 2:
            hours, minutes, seconds = 0, *parts
        else:
            return None
        return round((hours * 3600 + minutes * 60 + seconds) / 60)
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


def _open_states(resources) -> list:
    """Every door state this appliance reports, from wherever it reports it.

    Samsung fridges expose doors twice: an aggregate at /doors/vs/0 with an items[]
    array, and per-door resources at /door/<name>/vs/0. Which of the two actually
    tracks the door is *per model*, and an earlier version of this code assumed the
    per-door resource always won:

      - the one-door convertible cabinets keep /door/onedoorfreezer/vs/0 current and
        leave the aggregate stuck at Close
      - the plain fridge is the other way round. Its door lives in the aggregate;
        /door/onedoorfreezer/vs/0 exists but never moves, which stands to reason on a
        unit that is not a one-door freezer at all

    Binding only the per-door resource therefore fixed one model and broke the other.
    So every source is read and any of them reporting Open counts. That is safe
    against the staleness actually observed — a stale source sits at Close — and it
    needs no per-model knowledge of which resource is the live one.
    """
    states = []
    for href, rep in (resources or {}).items():
        if not isinstance(rep, dict):
            continue
        if href == "/doors/vs/0":
            for item in rep.get("x.com.samsung.da.items") or ():
                if isinstance(item, dict):
                    state = item.get("x.com.samsung.da.openState") or item.get("openState")
                    if state is not None:
                        states.append(state)
        elif href.startswith("/door/") or href.startswith("/kimchidoors/"):
            # `/kimchidoors/<slot>/vs/0` is a third spelling, on the
            # three-compartment kimchi refrigerators. It was missed until
            # 2026-08-10: the one-door variant reports `/door/onedoorkimchi/vs/0`
            # and matched the prefix above, so the door looked covered on that
            # family while the three-compartment one lost its only contact switch.
            # Only the top compartment reports one; the other two appear to have
            # none, which is why nothing here assumes a door per slot.
            state = rep.get("openState")
            if state is None:
                state = rep.get("x.com.samsung.da.openState")
            if state is not None:
                states.append(state)
    return states


def read_any_door_open(_rep, resources):
    """True when any door this appliance reports is open."""
    states = _open_states(resources)
    if not states:
        return None
    return any(str(s).strip().lower() in ("open", "opened", "true") for s in states)


def read_open_state(rep):
    """A single door resource's open state, checking both field spellings.

    Most /door/* resources report a bare `openState`; the family that carries
    /door/onedoorfreezer/vs/0 reports it vendor-prefixed. Looking up one name only
    leaves the capability bound and permanently blank.
    """
    state = rep.get("openState")
    if state is None:
        state = rep.get("x.com.samsung.da.openState")
    if state is None:
        return None
    return str(state).strip().lower() in ("open", "opened", "true")


# One capability, every source. Anchored on the aggregate because all three verified
# refrigerators carry it; the second spec covers a unit that has only a per-door
# resource. Both read the union, so whichever binds gives the same answer.
DOORS = (
    Spec("alarm_contact", "/doors/vs/0", read_any_door_open),
    Spec("alarm_contact", "/door/onedoorfreezer/vs/0", read_any_door_open,
         exists=lambda _rep, resources: "/doors/vs/0" not in resources),
)


# --- the set every type starts from --------------------------------------
UNIVERSAL = ALARMS + ENERGY + FIRMWARE + SELF_CHECK + REMOTE_CONTROL + CHILD_LOCK

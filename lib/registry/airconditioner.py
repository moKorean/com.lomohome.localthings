"""Air-conditioner registry.

Verified against a live TP1X_DA-AC-CAC-01001 (Korean ceiling/commercial unit);
resource shapes are in tests/fixtures/. Field names come from the reference
integration's capabilities/airconditioner.py, so other AC board families should
bind without changes.

Write payloads send only the field being changed — the device merges the rest of
the resource itself. Echoing the untouched fields back is what the reference
explicitly avoids.
"""

from . import shared
from .base import Registry, Spec, ValueNotAdvertised, as_float, as_int, first_item

HREF_POWER = "/power/vs/0"
HREF_MODE = "/mode/vs/0"
HREF_TEMPS = "/temperatures/vs/0"
HREF_HUMIDITY = "/humidity/vs/0"
HREF_ENERGY = "/energy/consumption/vs/0"
HREF_WIND_STRENGTH = "/wind/strength/vs/0"
# Only the legacy ARTIK051 generation carries this; newer families use
# HREF_WIND_STRENGTH above. Nothing reads it directly — its presence is the
# discriminator between the two generations (see is_legacy_board).
HREF_AIRFLOW = "/airflow/vs/0"
HREF_AIRPURIFY = "/option/airpurify/vs/0"
HREF_AIR_FILTER = "/filter/airdustfilter/vs/0"
HREF_PM1_FILTER = "/filter/airdustPM1filter/vs/0"
HREF_AUTOCLEAN = "/option/autoclean/vs/0"
HREF_MUTEONCE = "/option/muteonce/vs/0"
HREF_LIGHT = "/light/stateful/vs/0"
HREF_EDGE_LIGHT = "/edgelighting/vs/0"
HREF_ABSENCE_SAVING = "/mds/absencepowersaving/vs/0"
HREF_ABSENCE_CLEAN = "/mds/absenceclean/vs/0"
HREF_MOTION_WIND = "/option/motiondetectwind/stateful/vs/0"
HREF_CONVENIENT = "/mode/convenient/vs/0"
HREF_WIND_DIRECTION = "/wind/direction/vs/0"
HREF_UVLED = "/uvled/vs/0"
HREF_SMART_COOLING = "/smartsensingcooling/vs/0"
HREF_ALARMS = "/alarms/vs/0"
HREF_SELFCHECK = "/selfcheck/vs/0"
HREF_SENSORS = "/sensors/vs/0"
HREF_AIRLEVEL = "/airlevelcheck/vs/0"

HREF_ABSENCE_STATE = "/mds/absencestate/vs/0"
HREF_ABSENCE_MONITORING = "/mds/absencemonitoring/vs/0"


FIELD_POWER = "x.com.samsung.da.power"
FIELD_MODES = "x.com.samsung.da.modes"
FIELD_SUPPORTED = "x.com.samsung.da.supportedModes"
FIELD_MODES_NAME = "x.com.samsung.da.modesName"

# Homey enum values must be declared statically in the manifest, unlike HA's
# device-reported options. These are the union of modes seen across AC board
# families in the reference; a unit that doesn't support one simply never
# reports it, and a write of an unsupported mode is rejected by the device.
AC_MODES = ("AIComfort", "Auto", "Cool", "Dry", "Fan", "Heat", "Wind")

# Fan strength is a numeric code whose human names the device supplies in
# `modesName` alongside `supportedModes`. Map through those names rather than
# assuming 0..3 means auto/low/mid/high everywhere — the ordering is per-board.
FAN_ALIASES = {
    "auto": "auto",
    "low": "low",
    "mid": "mid",
    "medium": "mid",
    "high": "high",
    "turbo": "high",
}


def _fan_name_to_code(rep: dict) -> dict[str, str]:
    """{'auto': '0', 'low': '1', ...} from the device's own parallel arrays."""
    codes = rep.get(FIELD_SUPPORTED)
    names = rep.get(FIELD_MODES_NAME)
    if not isinstance(codes, list) or not isinstance(names, list):
        return {}
    if len(codes) != len(names):
        # Parallel arrays of different lengths mean the pairing is unknowable; a
        # truncating zip would silently map some speeds to the wrong code.
        return {}
    mapping = {}
    for code, name in zip(codes, names, strict=True):
        alias = FAN_ALIASES.get(str(name).strip().lower())
        if alias:
            mapping[alias] = str(code)
    return mapping


# The motion-detection sensor's *settings*, not its readings — MDS is Samsung's own
# abbreviation for the sensor, and these two resources look at first like a presence
# feed. They are not, and the evidence is direct: across four units, an occupied room
# and an empty room both reported status Off, while a room whose occupant was asleep
# reported status On with absenceTime 30. Occupancy does not correlate.
#
# What fits is a threshold pair. `supportedTimes` is exactly the shape of an option
# list for `absenceTime` (0/30/60/120 minutes), the two values move together
# (On paired with 30, Off with 0), and /mds/absencemonitoring/vs/0 is a third
# independent on/off. So: "treat the room as empty after N minutes without motion".
#
# There is no live motion readout on this firmware. The reference mentions a
# `motionState` field with its own supportedMotionState list, and none of the four
# units reports it anywhere. The only actual sensor data is `maxDetectCount`, a
# 48-slot daily profile whose indexing is not yet established — see docs/BACKLOG.md.
#
# Read-only. The reference ignores both hrefs outright, so there is no confirmed
# write, and these change how the appliance manages its own compressor.


# `/option/autoclean/vs/0` and `/selfcheck/vs/0` share a shape: a `settingStatus`
# or equivalent that says whether the feature is enabled, plus a `status` naming
# whether a cycle is running right now and a `progress` counting it out. Only the
# first was mapped, here and in the reference, so "auto dry" reported that the
# feature was switched on and never that it was actually drying.
#
# `progress` is a percentage: the owner watched the appliance's own display pass
# 55% during a cycle. `status` is Start/Stop, and the resource advertises exactly
# those two in `supportedStatus`.

FIELD_STATUS = "x.com.samsung.da.status"
FIELD_PROGRESS = "x.com.samsung.da.progress"


def _read_cycle_running(rep, _resources):
    value = rep.get(FIELD_STATUS)
    if value is None:
        return None
    # Autoclean says Start/Stop; selfcheck says Ready when idle. Anything that is
    # not one of the idle words counts as running, rather than listing every word
    # a board might use for "busy".
    return str(value) not in ("Stop", "Ready", "Cancel", "None")


def _read_cycle_progress(rep, _resources):
    return as_int(rep.get(FIELD_PROGRESS))


def _has_field(field):
    return lambda rep, _resources: field in rep


def _option_token(rep, name: str):
    """The value half of a `<name>_<value>` entry in `/mode/vs/0`'s options list.

    The list is a flat array of `Token_Value` strings — 25 to 26 of them on the
    four units here — so a token is read by prefix rather than by a field of its
    own. Returns None when the appliance does not advertise it at all, which is
    what gates the capabilities below: absence of the token is the only signal
    that a board lacks the feature.
    """
    options = rep.get("x.com.samsung.da.options")
    if not isinstance(options, list):
        return None
    prefix = f"{name}_"
    for option in options:
        if isinstance(option, str) and option.startswith(prefix):
            return option[len(prefix):]
    return None


def _read_odor_controller(rep, _resources):
    """Smart Cool Clean, the odor-controller self-clean cycle.

    Read-only: no write contract is confirmed for it, and the reference reached
    the same conclusion. Measured on all four air conditioners here, every one
    reporting `SmartCoolClean_Off`.
    """
    token = _option_token(rep, "SmartCoolClean")
    return None if token is None else token == "On"


def _read_odor_progress(rep, _resources):
    """0-100 progress of that cycle, from `ProgressSmartClean_<n>`."""
    return as_int(_option_token(rep, "ProgressSmartClean"))


def _read_absence_minutes(rep, _resources):
    return as_float(rep.get("absenceTime"))


def _read_power(rep, _resources):
    value = rep.get(FIELD_POWER)
    if value is None:
        return None
    return str(value) == "On"


def _write_power(value, _rep):
    return ["power", "vs", "0"], {FIELD_POWER: "On" if value else "Off"}


def _read_mode(rep, _resources):
    modes = rep.get(FIELD_MODES)
    if isinstance(modes, (list, tuple)):
        modes = modes[0] if modes else None
    return str(modes) if modes in AC_MODES else None


def _write_mode(value, rep):
    """Reject a mode this unit doesn't advertise.

    AC_MODES is the union across board families, so it necessarily contains values a
    given unit lacks — 'Heat' on a cooling-only Korean model, for instance. Sending
    one is silently dropped by the device, which reads as the tile being stuck.
    """
    if value not in AC_MODES:
        return None
    supported = (rep or {}).get(FIELD_SUPPORTED)
    if isinstance(supported, list) and supported and value not in supported:
        return None
    return ["mode", "vs", "0"], {FIELD_MODES: [value]}


# Outdoor temperature, from `/mode/vs/0`'s `OutdoorTemp_<n>` token minus 55.
#
# The offset is the reference's, which field-validated it over 48 hours against a
# weather feed (r=0.92) on boards declaring Celsius. Ours declare Celsius, so the
# gate below holds, and the four units here read 84-87 → 29-32°C.
#
# **The one independent check available did not confirm it and is recorded rather
# than buried.** A spot query to wttr.in for Seoul answered 13°C at the same
# moment, which cannot be reconciled with a -55 offset (that would need about
# -72). Two things argue the appliances rather than the feed: all four units were
# actively cooling rooms sitting at 28.5-30.5°C, which is not what a 13°C day looks
# like, and r=0.92 is a correlation, so it would not by itself have caught a
# constant offset error upstream either. Treated as unresolved: the reading is
# exposed because a wrong constant still tracks the real curve and is obvious to a
# user who compares it with a window, and docs/BACKLOG.md carries the experiment
# that would settle it.
#
# Enabled without the reference's opt-in. It disables this by default because a
# multi-split reports one condenser's token on every indoor head, which would make
# N identical sensors. That is not this hardware: the four units read 87/85/84/85
# at one moment, so they are not echoing a single shared value.
_OUTDOOR_TEMP_OFFSET = 55


def _reports_celsius(resources) -> bool:
    """Whether the board declares Celsius on its own `/temperatures/vs/0`.

    Guards the offset rather than the token. The constant was validated on
    Celsius-locale boards only, and nothing says a Fahrenheit board uses the same
    additive constant — or reports degrees F through it at all.
    """
    unit = first_item(resources.get(HREF_TEMPS) or {}).get("x.com.samsung.da.unit")
    return unit is None or str(unit).strip().lower().startswith("celsius")


def _read_outdoor_temp(rep, resources):
    if not _reports_celsius(resources):
        return None
    raw = as_float(_option_token(rep, "OutdoorTemp"))
    return None if raw is None else raw - _OUTDOOR_TEMP_OFFSET


def _has_outdoor_temp(rep, resources):
    return _read_outdoor_temp(rep, resources) is not None


def _read_target_temp(rep, _resources):
    return as_float(first_item(rep).get("x.com.samsung.da.desired"))


def _format_setpoint(value, item) -> str:
    """Setpoint string, snapped to the increment the device reports.

    Sent with one decimal rather than as a whole number: this board advertises
    increment 0.5 and was verified to accept "28.5" (controlResponse result True,
    and it then reports 28.5). Rounding to an integer here — as the reference does
    for this vendor channel — both loses half degrees and turns a genuine change
    into a no-op write, which the device refuses.
    """
    number = float(value)
    step = as_float(item.get("x.com.samsung.da.increment")) or 0.5
    if step > 0:
        number = round(number / step) * step
    return f"{number:.1f}"


def _write_target_temp(value, rep):
    # The vendor items[] array; only entry id '0' has ever been observed on an
    # AC. Sends just id + desired, leaving current/minimum/maximum/unit to the
    # device.
    return (
        ["temperatures", "vs", "0"],
        {
            "x.com.samsung.da.items": [
                {
                    "x.com.samsung.da.id": "0",
                    "x.com.samsung.da.desired": _format_setpoint(value, first_item(rep)),
                }
            ]
        },
    )


def _setpoint_options(rep, _resources) -> dict:
    """Slider bounds taken from the appliance rather than Homey's defaults.

    The verified unit allows 18-30 in 0.5 steps; Homey's default target_temperature
    range is wider, so without this the slider offers values the device refuses and
    the app looks broken.
    """
    item = first_item(rep)
    options = {}
    minimum = as_float(item.get("x.com.samsung.da.minimum"))
    maximum = as_float(item.get("x.com.samsung.da.maximum"))
    step = as_float(item.get("x.com.samsung.da.increment"))
    if minimum is not None:
        options["min"] = minimum
    if maximum is not None:
        options["max"] = maximum
    if step:
        options["step"] = step
        options["decimals"] = 1 if step < 1 else 0
    return options


def _read_current_temp(rep, _resources):
    return as_float(first_item(rep).get("x.com.samsung.da.current"))


def _read_humidity(rep, _resources):
    """Relative humidity, preferring the 5%-rounded field where it exists.

    Follows the reference's rule exactly. `fivepercentHumidity` passes 0 through
    as a genuine reading; the plain `humidity` fallback does not, because on the
    boards that only have it the unit measures briefly and then zeroes the field —
    so 0 there means "not measuring" and publishing it would poison history.
    """
    if "x.com.samsung.da.fivepercentHumidity" in rep:
        return as_float(rep["x.com.samsung.da.fivepercentHumidity"])
    if "x.com.samsung.da.humidity" in rep:
        value = as_float(rep["x.com.samsung.da.humidity"])
        return value or None
    return None


def _read_power_watts(rep, _resources):
    return as_float(rep.get("x.com.samsung.da.instantaneousPower"))


def is_legacy_board(resources) -> bool:
    """True for the board generation whose airflow lives in /airflow/vs/0.

    Newer families carry a dedicated /wind/strength/vs/0 instead. The reference
    uses exactly this test to gate the handful of behaviours that differ between
    generations, so it is reproduced rather than re-derived.
    """
    return HREF_AIRFLOW in resources and HREF_WIND_STRENGTH not in resources


def _read_meter_kwh(rep, resources):
    total = as_float(rep.get("x.com.samsung.da.cumulativePower"))
    if total is None:
        return None
    # The legacy ARTIK051 generation reports this in centiwatt-hours, not the Wh
    # every other family reports — and it still labels the unit 'Wh', so the label
    # cannot be trusted to tell them apart. The reference established the factor
    # against a reporter's own SmartThings reading: raw 117430000 against an
    # authoritative 1,174.30 kWh is /100000 exactly, a further /100 on top of the
    # usual /1000 (reference issue #193).
    #
    # Not verified here — no legacy board was available to test. The gate is
    # narrow enough that being wrong affects only that generation, and leaving it
    # unhandled is certainly wrong for those users: they see a figure 100x too
    # large.
    if is_legacy_board(resources):
        return round(total / 100000.0, 2)
    # cumulativeUnit is 'Wh' on every dump seen, but honour it rather than
    # hardcoding the divisor.
    unit = str(rep.get("x.com.samsung.da.cumulativeUnit") or "Wh").strip().lower()
    return total / 1000.0 if unit == "wh" else total


def _read_fan(rep, _resources):
    current = str(rep.get(FIELD_MODES, "")).strip()
    for alias, code in _fan_name_to_code(rep).items():
        if code == current:
            return alias
    return None


def _write_fan(value, rep):
    code = _fan_name_to_code(rep).get(value)
    if code is None:
        return None
    return ["wind", "strength", "vs", "0"], {FIELD_MODES: code}


def _read_airpurify(rep, _resources):
    value = rep.get(FIELD_MODES)
    if value is None:
        return None
    return str(value) == "On"


def _write_airpurify(value, _rep):
    return ["option", "airpurify", "vs", "0"], {FIELD_MODES: "On" if value else "Off"}


# Third copy of the same wrong division. The value it produced for the verified unit
# was 56% for a filter the appliance itself reports as `wash`.
_read_filter_usage = shared._filter_percent


def _read_filter_alarm(rep, _resources):
    status = rep.get("x.com.samsung.da.filterStatus")
    if status is None:
        return None
    # 'normal' while fine; 'wash'/'replace' once the device wants attention.
    return str(status).strip().lower() not in ("normal", "")


# --- expanded coverage -----------------------------------------------------
#
# Which of these may be written follows the reference's own judgments rather than
# a guess of ours: a bare On/Off status field on an option resource is treated as
# safe ("worst case a wrong token no-ops"), while an enum on a resource nobody has
# verified a write against stays read-only under its don't-guess rule.


def _read_flag(field: str, on: str = "On"):
    def read(rep, _resources):
        value = rep.get(field)
        return None if value is None else str(value) == on

    return read


def _write_flag(path: list, field: str):
    def write(value, _rep):
        return path, {field: "On" if value else "Off"}

    return write


def _read_enum(field: str, allowed: tuple):
    def read(rep, _resources):
        value = rep.get(field)
        return str(value) if value in allowed else None

    return read


def _write_enum(path: list, field: str, allowed: tuple, supported_field=FIELD_SUPPORTED):
    def write(value, rep):
        # Two gates. The static list catches a value this app never declared; the
        # device's own supportedModes catches one it declared for other boards but
        # this unit doesn't have. Sending either would be silently dropped, leaving
        # the tile looking stuck rather than reporting a refusal.
        if value not in allowed:
            return None
        supported = (rep or {}).get(supported_field)
        if isinstance(supported, list) and supported and value not in supported:
            # Raise rather than return None so the message can name the list this
            # saw. The two gates are indistinguishable after the fact otherwise,
            # and a refused write leaves no log line to fall back on.
            raise ValueNotAdvertised(value, supported)
        return path, {field: value}

    return write


# The first six are what this house's four units advertise. The rest were counted
# across the 21 reference dumps that carry /mode/convenient/vs/0, because a value
# missing from this tuple reads as None — which means "leave the capability alone",
# so a unit sitting in one of them shows an empty tile forever and cannot be put
# back into it either:
#
#     Off 21   Sleep 20   Quiet 16   Speed 16   Nano 14   NanoSleep 14
#     Smart 9  MotionIndirect 4   MotionDirect 3   LongWind 2   DryComfort 2
#
# Quiet is on more boards than Nano, and on more than eight times as many as
# LongWind, both of which were already here. Adding a code only widens what is
# accepted: `_write_enum` still gates every write on the unit's own supportedModes,
# so a board without Quiet refuses it exactly as before.
#
# Note the shape. On this resource `x.com.samsung.da.modes` is a bare string, not
# the list the field name suggests and not what it is on /mode/vs/0 — 19 of 19
# dumps that populate it, no exceptions. `_read_enum` compares the value directly,
# so it reads a string correctly and would silently read a list as nothing.
CONVENIENT_MODES = (
    "Off", "Nano", "LongWind", "Speed", "Sleep", "NanoSleep",
    "Quiet", "Smart", "MotionDirect", "MotionIndirect", "DryComfort",
)
# 'Fix' is what the verified unit reports while absent from its own
# supportedModes, so it has to be accepted on read as well as offered.
WIND_DIRECTIONS = ("Fix", "Left_And_Right", "All")
POWER_SAVE_MODES = ("Eco", "Normal", "Comfort")
WIND_TARGETS = ("Direct", "Indirect")
LIGHT_MODES = ("Smart", "Low", "High")
# /edgelighting/vs/0 keeps its own supported lists under plain OCF names rather
# than the vendor-prefixed supportedModes the rest of this file uses, and the two
# lists are ordered differently from /light/stateful/vs/0's — read them from the
# device rather than assuming either matches LIGHT_MODES.
EDGE_LIGHT_MODES = ("Smart", "High", "Low")
EDGE_LIGHT_COLORS = ("3000K", "4000K", "6500K")

# Codes the device reports while nothing is wrong, and the state it uses for a
# cleared alarm.
_ALARM_IDLE_CODES = {"errorcode_off", "ct_e_off", "none", ""}
_ALARM_CLEARED_STATES = {"deleted", "cleared"}


def _read_active_alarm(rep, _resources):
    """The first alarm the device still considers active, or 'none'.

    The items array keeps cleared entries around — the verified unit lists a
    deleted ErrorCode_OFF alongside a live FilterAlarm — so reporting items[0]
    blindly would show a stale or idle code as if it were current.
    """
    items = rep.get("x.com.samsung.da.items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        state = str(item.get("x.com.samsung.da.state", "")).strip().lower()
        code = str(item.get("x.com.samsung.da.code", "")).strip()
        if state in _ALARM_CLEARED_STATES:
            continue
        if code.lower() in _ALARM_IDLE_CODES:
            continue
        if code:
            return code
    return "none"


# The third alarm slot on the CAC boards, which carries a `DA_SAC_M_*` family of
# its own. Named for what it is rather than what it means: what it means is not
# known, and the three explanations tried so far were all refuted by measurement
# (2026-08-07, four units).
#
#   mute            all four units muted, only the one without the code differed
#   powered on      turning the odd unit on left the slot at _OFF
#   Wind-Free set   that unit was already in Wind-Free; the write came back
#                   `errorCode: "unchanged"` and the slot still did not move
#
# What it does track is whether the unit is running. Logged every 12 minutes over
# eight hours across the four units — 152 unit-samples, 2026-08-07/08:
#
#   _OFF     onoff False   110 of 110
#   a number onoff True     58 of 58
#
# with no exception either way. An earlier reading of this comment claimed the
# number also required the room to have reached its setpoint; the log refutes it,
# carrying twelve samples with a number while the room was above setpoint. That
# claim came from one timepoint, which is the third time this slot has punished
# exactly that.
#
# One case is unresolved: a unit switched on read `_OFF` about two and a half
# minutes later, twice. Nothing in the log covers a power-on transition, so
# whether the slot simply lags the switch is untested.
#
# The number itself is 0003 or 0004 and moves slowly and per unit — one sat at
# 0003 for eight hours while another went 0004, 0003, 0004 — and nothing logged
# (operating mode, fan, setpoint delta, watts) separates the two values. That it
# moves at all is the plainest evidence this is not a fault code.
#
# It is exposed as a number with Insights so Homey keeps the history beside
# measure_power and measure_temperature, which is what the correlation needs;
# `_OFF` reads 0. docs/BACKLOG.md carries the experiment that would settle it.
#
# The appliance's own error channel is a different slot and reads ErrorCode_OFF
# throughout, which is why SmartThings calls the same appliance healthy.
_STATE_CODE_PREFIX = "DA_SAC_M"


def _has_state_code(rep, _resources) -> bool:
    items = rep.get("x.com.samsung.da.items")
    if not isinstance(items, list):
        return False
    return any(
        isinstance(item, dict)
        and str(item.get("x.com.samsung.da.code", "")).startswith(_STATE_CODE_PREFIX)
        for item in items
    )


def _read_state_code(rep, _resources):
    """The numeric half of the `DA_SAC_M_*` entry, with its idle form as 0.

    A suffix that is neither `OFF` nor a number returns None — the appliance has
    only ever reported those two, and inventing a value for a third would be the
    guess this file exists to avoid.
    """
    items = rep.get("x.com.samsung.da.items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        code = str(item.get("x.com.samsung.da.code", "")).strip()
        if not code.startswith(_STATE_CODE_PREFIX):
            continue
        suffix = code[len(_STATE_CODE_PREFIX):].lstrip("_")
        if suffix.upper() == "OFF":
            return 0
        return as_int(suffix)
    return None


def _sensor_value(sensor_type: str):
    """A reading out of /sensors/vs/0's items array, which keys by `type` rather
    than position and wraps each value in a single-element list."""

    def read(rep, _resources):
        for item in rep.get("x.com.samsung.da.items") or ():
            if not isinstance(item, dict):
                continue
            if str(item.get("x.com.samsung.da.type")) != sensor_type:
                continue
            value = item.get("x.com.samsung.da.value")
            if isinstance(value, list):
                value = value[0] if value else None
            return as_float(value)
        return None

    return read


# A second copy of the same wrong division lived here, so fixing shared._filter_percent
# left the air conditioner — the one appliance most users of this app own — still
# reporting 56% for a filter the device itself flags as due for washing. There is no
# reason for two implementations; the shared one carries the reasoning.
_filter_usage_percent = shared._filter_percent


REGISTRY = Registry(
    name="airconditioner",
    device_class="thermostat",
    titles={"en": "Samsung Air Conditioner", "ko": "삼성 에어컨"},
    specs=(
        Spec("onoff", HREF_POWER, _read_power, _write_power),
        Spec("target_temperature", HREF_TEMPS, _read_target_temp, _write_target_temp,
             options=_setpoint_options),
        Spec("measure_temperature", HREF_TEMPS, _read_current_temp),
        Spec("measure_temperature.outdoor", HREF_MODE, _read_outdoor_temp,
             exists=_has_outdoor_temp,
             titles={"en": "Outdoor", "ko": "실외"}),
        Spec("localthings_ac_mode", HREF_MODE, _read_mode, _write_mode),
        # Smart Cool Clean, the odor-controller self-clean. Both tokens are
        # present on all four units here (SmartCoolClean_Off,
        # ProgressSmartClean_0), and each capability is gated on its own token
        # so a board without the feature binds neither.
        Spec("localthings_odor_controller", HREF_MODE, _read_odor_controller,
             exists=lambda rep, _r: _option_token(rep, "SmartCoolClean") is not None),
        Spec("localthings_odor_progress", HREF_MODE, _read_odor_progress,
             exists=lambda rep, _r: _option_token(rep, "ProgressSmartClean") is not None),
        Spec("localthings_fan_mode", HREF_WIND_STRENGTH, _read_fan, _write_fan),
        Spec("measure_humidity", HREF_HUMIDITY, _read_humidity),
        # Present and populated on all three verified units, but unbound until
        # now — the shared specs were only wired into the appliances that were
        # ported later. Field names confirmed against those units.
        *shared.SOUND,
        Spec("localthings_absence_detect", HREF_ABSENCE_STATE,
             shared.flag("status")),
        Spec("localthings_absence_minutes", HREF_ABSENCE_STATE,
             _read_absence_minutes),
        Spec("localthings_absence_monitoring", HREF_ABSENCE_MONITORING,
             shared.flag("status")),
        Spec("measure_power", HREF_ENERGY, _read_power_watts),
        Spec("meter_power", HREF_ENERGY, _read_meter_kwh),
        Spec("localthings_air_purify", HREF_AIRPURIFY, _read_airpurify, _write_airpurify),
        Spec("localthings_filter_usage", HREF_AIR_FILTER, _read_filter_usage),
        Spec("localthings_alarm_filter", HREF_AIR_FILTER, _read_filter_alarm),

        # Writable options — bare On/Off status fields, per the reference.
        Spec("localthings_auto_clean", HREF_AUTOCLEAN,
             _read_flag("x.com.samsung.da.settingStatus"),
             _write_flag(["option", "autoclean", "vs", "0"],
                         "x.com.samsung.da.settingStatus")),
        # The cycle itself, as opposed to whether the feature is enabled above.
        Spec("localthings_auto_clean_active", HREF_AUTOCLEAN, _read_cycle_running,
             exists=_has_field(FIELD_STATUS)),
        Spec("localthings_auto_clean_progress", HREF_AUTOCLEAN, _read_cycle_progress,
             exists=_has_field(FIELD_PROGRESS)),
        # Self check has the same shape and was not bound on this type at all —
        # /selfcheck/vs/0 sat in the unbound list while other appliance types read it.
        Spec("localthings_selfcheck", HREF_SELFCHECK,
             shared.text("x.com.samsung.da.status")),
        Spec("localthings_selfcheck_active", HREF_SELFCHECK, _read_cycle_running,
             exists=_has_field(FIELD_STATUS)),
        Spec("localthings_selfcheck_progress", HREF_SELFCHECK, _read_cycle_progress,
             exists=_has_field(FIELD_PROGRESS)),
        Spec("localthings_mute_once", HREF_MUTEONCE, _read_flag("muteonce"),
             _write_flag(["option", "muteonce", "vs", "0"], "muteonce")),
        Spec("localthings_display_light", HREF_LIGHT, _read_flag("status"),
             _write_flag(["light", "stateful", "vs", "0"], "status")),
        Spec("localthings_edge_light", HREF_EDGE_LIGHT, _read_flag("status"),
             _write_flag(["edgelighting", "vs", "0"], "status")),
        Spec("localthings_absence_power_saving", HREF_ABSENCE_SAVING,
             _read_flag("status"),
             _write_flag(["mds", "absencepowersaving", "vs", "0"], "status")),
        Spec("localthings_absence_clean", HREF_ABSENCE_CLEAN, _read_flag("mode"),
             _write_flag(["mds", "absenceclean", "vs", "0"], "mode")),
        Spec("localthings_motion_detect_wind", HREF_MOTION_WIND,
             _read_flag("status"),
             _write_flag(["option", "motiondetectwind", "stateful", "vs", "0"],
                         "status")),
        Spec("localthings_smart_sensing_cooling", HREF_SMART_COOLING,
             _read_flag("status"),
             _write_flag(["smartsensingcooling", "vs", "0"], "status")),
        Spec("localthings_uvled", HREF_UVLED, _read_flag(FIELD_MODES),
             _write_flag(["uvled", "vs", "0"], FIELD_MODES)),

        # Writable pickers the reference drives from its climate entity.
        Spec("localthings_convenient_mode", HREF_CONVENIENT,
             _read_enum(FIELD_MODES, CONVENIENT_MODES),
             _write_enum(["mode", "convenient", "vs", "0"], FIELD_MODES,
                         CONVENIENT_MODES)),
        Spec("localthings_wind_direction", HREF_WIND_DIRECTION,
             _read_enum(FIELD_MODES, WIND_DIRECTIONS),
             _write_enum(["wind", "direction", "vs", "0"], FIELD_MODES,
                         WIND_DIRECTIONS)),

        # Read-only: enums on resources with no verified write contract.
        Spec("localthings_power_save_mode", HREF_ABSENCE_SAVING,
             _read_enum("switchPowerSaveMode", POWER_SAVE_MODES)),
        Spec("localthings_wind_target", HREF_MOTION_WIND,
             _read_enum("modes", WIND_TARGETS)),
        Spec("localthings_light_mode", HREF_LIGHT,
             _read_enum("mode", LIGHT_MODES)),
        # Both confirmed on the hardware here 2026-08-08, not inferred from the
        # resource advertising a supported list — this app has been burned by that
        # once, on the induction cooktop. Written and read back on two units:
        # 손님방 Smart->Low and 3000K->6500K, 거실 4000K->6500K, every original
        # value restored afterwards.
        #
        # The colour needs the delayed read to see it. Its own write echoed
        # `result: true` while the immediate read-back still showed the old value,
        # and only the check 25s later showed it had taken — so a caller that
        # believes the echo *or* the first read draws opposite wrong conclusions
        # from the same working write. WRITE_SETTLE_S already covers this for the
        # capability path.
        Spec("localthings_edge_light_mode", HREF_EDGE_LIGHT,
             _read_enum("mode", EDGE_LIGHT_MODES),
             _write_enum(["edgelighting", "vs", "0"], "mode", EDGE_LIGHT_MODES,
                         supported_field="modeSupportedList")),
        Spec("localthings_edge_light_color", HREF_EDGE_LIGHT,
             _read_enum("colorOption", EDGE_LIGHT_COLORS),
             _write_enum(["edgelighting", "vs", "0"], "colorOption",
                         EDGE_LIGHT_COLORS,
                         supported_field="colorSupportedList")),

        # Read-only sensors.
        Spec("localthings_alarm_code", HREF_ALARMS, _read_active_alarm),
        Spec("localthings_operation_state_code", HREF_ALARMS, _read_state_code,
             exists=_has_state_code),
        Spec("localthings_air_quality", HREF_SENSORS, _sensor_value("CleanLevel")),
        Spec("measure_pm25", HREF_SENSORS, _sensor_value("FineDust")),
        Spec("localthings_dust_pm10", HREF_SENSORS, _sensor_value("Dust")),
        Spec("localthings_dust_pm1", HREF_SENSORS, _sensor_value("SuperFineDust")),
        Spec("localthings_filter_usage.pm1", HREF_PM1_FILTER, _filter_usage_percent,
             exists=_has_field("x.com.samsung.da.filterUsage"),
             titles={"en": "PM1.0 filter", "ko": "PM1.0 필터"}),
        # The second filter had its wear published and its own wash/replace flag
        # dropped, so a PM1 filter asking for attention said nothing while the main
        # one did. Gated on the field, because the reference has seen boards that
        # report this href with capacity metadata and no live status at all
        # (TP1X_FAC_TIME_23K) — ours reports it, theirs does not, and a capability
        # that can never have a value is worse than none.
        Spec("localthings_alarm_filter.pm1", HREF_PM1_FILTER, _read_filter_alarm,
             exists=_has_field("x.com.samsung.da.filterStatus"),
             titles={"en": "PM1.0 filter", "ko": "PM1.0 필터"}),
        # Periodic air-quality sensing, the same four read-only fields the hood and
        # the purifier bind. A divergence from the reference, which exposes this
        # resource on neither air conditioner family and calls it scheduler
        # plumbing there — measured 2026-08-05 against that, by reading raw
        # /device/0 off all four units here in one call:
        #
        #   periodicSensingActivationState  On          (4/4)
        #   sensingState                    NonProcessing
        #   lastSensingLevel                Kr2, Kr2, Kr2, Kr1
        #   autoExeState                    Alarm       (4/4)
        #   supportedAutoExeState           [Airpurify, Alarm, Sensing]
        #
        # Not plumbing on this family: the schedule is what samples the dust and
        # air-quality readings already bound above, and every unit here has an
        # action configured rather than sitting at the inert default the
        # reference's own CAC dump would suggest.
        #
        # Read-only, like both other copies. The action looks writable — this is
        # the one family whose reported value is in its own supported list — but a
        # write to it has never been tried on these units, and this appliance
        # answers writes it does not honour, so the list stays a hint. Free-form
        # strings for the same reason the hood's are: the hood reports a value its
        # own supported list omits, so a picker built from that list is not safe
        # to share across the three.
        Spec("localthings_air_sensing", HREF_AIRLEVEL,
             shared.flag("x.com.samsung.da.periodicSensingActivationState")),
        Spec("localthings_air_sensing_state", HREF_AIRLEVEL,
             shared.text("x.com.samsung.da.sensingState")),
        Spec("localthings_air_sensing_level", HREF_AIRLEVEL,
             shared.text("x.com.samsung.da.lastSensingLevel")),
        Spec("localthings_air_sensing_action", HREF_AIRLEVEL,
             shared.text("x.com.samsung.da.autoExeState")),
    ),
)

# Board-family tokens routed to this registry, mirroring the reference's table.
# 'CAC' (Korean ceiling/commercial) was added here first, from the unit at
# 192.168.1.90, and contributed upstream as mbillow/localthings#194; the
# reference reached the same token independently as #191 and carries it as of
# v0.17.0, so this is no longer a local-only addition — see docs/PORTING.md.
BOARD_TOKENS = ("RAC", "PRAC", "KRAC", "CAC", "WAC", "FAC", "CAWW", "ARA")

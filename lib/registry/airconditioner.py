"""Air-conditioner registry.

Verified against a live TP1X_DA-AC-CAC-01001 (Korean ceiling/commercial unit);
resource shapes are in tests/fixtures/. Field names come from the reference
integration's capabilities/airconditioner.py, so other AC board families should
bind without changes.

Write payloads send only the field being changed — the device merges the rest of
the resource itself. Echoing the untouched fields back is what the reference
explicitly avoids.
"""

from .base import Registry, Spec, as_float, first_item

HREF_POWER = "/power/vs/0"
HREF_MODE = "/mode/vs/0"
HREF_TEMPS = "/temperatures/vs/0"
HREF_HUMIDITY = "/humidity/vs/0"
HREF_ENERGY = "/energy/consumption/vs/0"
HREF_WIND_STRENGTH = "/wind/strength/vs/0"
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
HREF_SENSORS = "/sensors/vs/0"

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
    mapping = {}
    for code, name in zip(codes, names):
        alias = FAN_ALIASES.get(str(name).strip().lower())
        if alias:
            mapping[alias] = str(code)
    return mapping


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


def _write_mode(value, _rep):
    return ["mode", "vs", "0"], {FIELD_MODES: [value]}


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


def _read_meter_kwh(rep, _resources):
    total = as_float(rep.get("x.com.samsung.da.cumulativePower"))
    if total is None:
        return None
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


def _read_filter_usage(rep, _resources):
    """Percent of the filter's rated life consumed."""
    used = as_float(rep.get("x.com.samsung.da.filterUsage"))
    capacity = as_float(rep.get("x.com.samsung.da.filterCapacity"))
    if used is None or not capacity:
        return None
    return round(min(used / capacity * 100.0, 100.0), 1)


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


def _write_enum(path: list, field: str, allowed: tuple):
    def write(value, _rep):
        # Refuse rather than send a token the capability doesn't declare; the
        # device would silently drop it and the tile would look stuck.
        return (path, {field: value}) if value in allowed else None

    return write


CONVENIENT_MODES = ("Off", "Nano", "LongWind", "Speed", "Sleep", "NanoSleep")
# 'Fix' is what the verified unit reports while absent from its own
# supportedModes, so it has to be accepted on read as well as offered.
WIND_DIRECTIONS = ("Fix", "Left_And_Right", "All")
POWER_SAVE_MODES = ("Eco", "Normal", "Comfort")
WIND_TARGETS = ("Direct", "Indirect")
LIGHT_MODES = ("Smart", "Low", "High")

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


def _filter_usage_percent(rep, _resources):
    used = as_float(rep.get("x.com.samsung.da.filterUsage"))
    capacity = as_float(rep.get("x.com.samsung.da.filterCapacity"))
    if used is None or not capacity:
        return None
    return round(min(used / capacity * 100.0, 100.0), 1)


REGISTRY = Registry(
    name="airconditioner",
    device_class="thermostat",
    titles={"en": "Samsung Air Conditioner", "ko": "삼성 에어컨"},
    specs=(
        Spec("onoff", HREF_POWER, _read_power, _write_power),
        Spec("target_temperature", HREF_TEMPS, _read_target_temp, _write_target_temp),
        Spec("measure_temperature", HREF_TEMPS, _read_current_temp),
        Spec("localthings_ac_mode", HREF_MODE, _read_mode, _write_mode),
        Spec("localthings_fan_mode", HREF_WIND_STRENGTH, _read_fan, _write_fan),
        Spec("measure_humidity", HREF_HUMIDITY, _read_humidity),
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

        # Read-only sensors.
        Spec("localthings_alarm_code", HREF_ALARMS, _read_active_alarm),
        Spec("localthings_air_quality", HREF_SENSORS, _sensor_value("CleanLevel")),
        Spec("measure_pm25", HREF_SENSORS, _sensor_value("FineDust")),
        Spec("localthings_dust_pm10", HREF_SENSORS, _sensor_value("Dust")),
        Spec("localthings_dust_pm1", HREF_SENSORS, _sensor_value("SuperFineDust")),
        Spec("localthings_filter_usage.pm1", HREF_PM1_FILTER, _filter_usage_percent,
             titles={"en": "PM1.0 filter", "ko": "PM1.0 필터"}),
    ),
)

# Board-family tokens routed to this registry. 'CAC' (Korean ceiling/commercial)
# is absent from the reference's table as of v0.16.0 — see docs/PORTING.md; the
# rest mirror it.
BOARD_TOKENS = ("RAC", "PRAC", "KRAC", "CAC", "WAC", "FAC", "CAWW", "ARA")

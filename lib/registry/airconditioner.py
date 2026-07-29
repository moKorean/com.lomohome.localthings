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
    """`humidity` reads a flat 0 on the verified unit while
    `fivepercentHumidity` carries the real value, so prefer the latter and only
    fall back when it is absent."""
    value = as_float(rep.get("x.com.samsung.da.fivepercentHumidity"))
    if value is None:
        value = as_float(rep.get("x.com.samsung.da.humidity"))
    return value


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
    ),
)

# Board-family tokens routed to this registry. 'CAC' (Korean ceiling/commercial)
# is absent from the reference's table as of v0.16.0 — see docs/PORTING.md; the
# rest mirror it.
BOARD_TOKENS = ("RAC", "PRAC", "KRAC", "CAC", "WAC", "FAC", "CAWW", "ARA")

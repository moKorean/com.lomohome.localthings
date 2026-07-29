"""The remaining appliance types.

Ported from the reference integration's registries: board tokens, resource hrefs and
field names all come from `by_type/*.py` and `capabilities/*.py`, which is the
authority for them.

**None of these has been verified against real hardware.** Only the air conditioner
and induction cooktop, which live in their own modules, have. The rest were built
from the reference's field definitions, so a wrong reading is possible where its
comments left a shape ambiguous. What is safe to say is that each type is recognised
rather than reported as unsupported, and that the shared core — power, child lock,
alarms, energy, cycle state — is the same code already working on two device types.

Writes follow the reference's judgments. Where it exposes a bare On/Off option as a
switch, so does this; where it deliberately leaves something read-only under its
don't-guess rule, so does this. Nothing that applies heat is writable.
"""

from . import shared
from .base import Registry, Spec, as_float, as_int, first_item

# --- washer ---------------------------------------------------------------

HREF_WASHER = "/washer/vs/0"

WASHER = Registry(
    name="washer",
    device_class="other",
    titles={"en": "Samsung Washer", "ko": "삼성 세탁기"},
    specs=(
        *shared.POWER,
        *shared.UNIVERSAL,
        *shared.OPERATIONAL,
        *shared.WATER_METER,
        Spec("localthings_wash_temperature", HREF_WASHER,
             shared.text("x.com.samsung.da.waterTemperature")),
        Spec("localthings_spin_speed", HREF_WASHER,
             shared.text("x.com.samsung.da.spinLevel")),
        Spec("localthings_rinse_cycles", HREF_WASHER,
             lambda rep, _r: as_int(rep.get("x.com.samsung.da.rinseCycles"))),
    ),
)

# --- dryer ----------------------------------------------------------------

DRYER = Registry(
    name="dryer",
    device_class="other",
    titles={"en": "Samsung Dryer", "ko": "삼성 건조기"},
    specs=(
        *shared.POWER,
        *shared.UNIVERSAL,
        *shared.OPERATIONAL,
        Spec("localthings_dry_level", HREF_WASHER,
             shared.text("x.com.samsung.da.dryLevel")),
        # A wrinkle-prevention tumble, not a heat control — writable per the
        # reference, which exposes it as a switch.
        Spec("localthings_wrinkle_prevent", HREF_WASHER,
             shared.flag("x.com.samsung.da.wrinklePrevent"),
             shared.write_flag(["washer", "vs", "0"],
                               "x.com.samsung.da.wrinklePrevent")),
    ),
)

# --- dishwasher -----------------------------------------------------------

HREF_DISHWASHER = "/dishwasher/vs/0"

DISHWASHER = Registry(
    name="dishwasher",
    device_class="other",
    titles={"en": "Samsung Dishwasher", "ko": "삼성 식기세척기"},
    specs=(
        *shared.POWER,
        *shared.UNIVERSAL,
        *shared.OPERATIONAL,
        *shared.WATER_METER,
        *shared.SOUND,
        Spec("localthings_sanitize", HREF_DISHWASHER,
             shared.flag("x.com.samsung.da.sanitize"),
             shared.write_flag(["dishwasher", "vs", "0"],
                               "x.com.samsung.da.sanitize")),
        Spec("localthings_heated_dry", HREF_DISHWASHER,
             shared.text("x.com.samsung.da.heatedDry")),
    ),
)

# --- refrigerator ---------------------------------------------------------
#
# The fridge has by far the widest surface in the reference — per-compartment
# temperatures and doors on pattern hrefs, ice makers, flex/pantry/beverage zones.
# Only the whole-appliance resources are bound here; per-compartment values need a
# dump to get the href pattern right, and guessing would put wrong temperatures on a
# tile rather than leave a gap.

REFRIGERATOR = Registry(
    name="refrigerator",
    device_class="other",
    titles={"en": "Samsung Refrigerator", "ko": "삼성 냉장고"},
    specs=(
        *shared.POWER,
        *shared.UNIVERSAL,
        *shared.WATER_FILTER,
        *shared.DOORS,
        Spec("localthings_rapid_fridge", "/refrigeration/vs/0",
             shared.flag("x.com.samsung.da.rapidFridge"),
             shared.write_flag(["refrigeration", "vs", "0"],
                               "x.com.samsung.da.rapidFridge")),
        Spec("localthings_rapid_freeze", "/refrigeration/vs/0",
             shared.flag("x.com.samsung.da.rapidFreezing"),
             shared.write_flag(["refrigeration", "vs", "0"],
                               "x.com.samsung.da.rapidFreezing")),
        Spec("localthings_ice_maker", "/icemaker/status/vs/0",
             shared.flag("x.com.samsung.da.iceMaker"),
             shared.write_flag(["icemaker", "status", "vs", "0"],
                               "x.com.samsung.da.iceMaker")),
        Spec("localthings_autofill", "/autofill/vs/0",
             shared.flag("x.com.samsung.da.autofill"),
             shared.write_flag(["autofill", "vs", "0"],
                               "x.com.samsung.da.autofill")),
        Spec("localthings_cabinet_light", "/cabinet/light/total/vs/0",
             shared.flag("x.com.samsung.da.lightControl"),
             shared.write_flag(["cabinet", "light", "total", "vs", "0"],
                               "x.com.samsung.da.lightControl")),
        Spec("localthings_sabbath", "/sabbath/vs/0",
             shared.flag("x.com.samsung.da.sabbathMode"),
             shared.write_flag(["sabbath", "vs", "0"],
                               "x.com.samsung.da.sabbathMode")),
        Spec("localthings_welcome_light", "/proximity/vs/0",
             shared.flag("status"),
             shared.write_flag(["proximity", "vs", "0"], "status")),
        # Freezer/fridge temperatures on boards that report the vendor array.
        Spec("measure_temperature.freezer", "/temperatures/vs/0",
             lambda rep, _r: _fridge_temp(rep, "Freezer"),
             titles={"en": "Freezer", "ko": "냉동실"}),
        Spec("measure_temperature.fridge", "/temperatures/vs/0",
             lambda rep, _r: _fridge_temp(rep, "Fridge"),
             titles={"en": "Fridge", "ko": "냉장실"}),
    ),
)


def _fridge_temp(rep, compartment: str):
    """Current temperature for a named compartment in the vendor items array."""
    for item in rep.get("x.com.samsung.da.items") or ():
        if not isinstance(item, dict):
            continue
        description = str(item.get("x.com.samsung.da.description") or "")
        if compartment.lower() in description.lower():
            return as_float(item.get("x.com.samsung.da.current"))
    return None


# --- air purifier ---------------------------------------------------------

AIR_PURIFIER = Registry(
    name="air_purifier",
    device_class="fan",
    titles={"en": "Samsung Air Purifier", "ko": "삼성 공기청정기"},
    specs=(
        *shared.POWER,
        *shared.UNIVERSAL,
        *shared.SOUND,
        Spec("localthings_display_light", "/display/vs/0", shared.flag("mode"),
             shared.write_flag(["display", "vs", "0"], "mode")),
        Spec("localthings_filter_usage.hepa", "/filter/hepafilter/vs/0",
             shared._filter_percent, titles={"en": "HEPA filter", "ko": "HEPA 필터"}),
        Spec("localthings_alarm_filter.hepa", "/filter/hepafilter/vs/0",
             shared.read_filter_alarm,
             titles={"en": "HEPA filter", "ko": "HEPA 필터"}),
        Spec("localthings_pet_filter", "/petfilteractivation/vs/0",
             shared.flag("status"),
             shared.write_flag(["petfilteractivation", "vs", "0"], "status")),
        Spec("localthings_fan_speed_level", "/airflow/vs/0",
             lambda rep, _r: as_int(rep.get("x.com.samsung.da.speedLevel"))),
        Spec("localthings_air_quality", "/sensors/vs/0",
             lambda rep, _r: _sensor(rep, "CleanLevel")),
        Spec("measure_pm25", "/sensors/vs/0", lambda rep, _r: _sensor(rep, "FineDust")),
        Spec("localthings_dust_pm10", "/sensors/vs/0",
             lambda rep, _r: _sensor(rep, "Dust")),
        Spec("localthings_dust_pm1", "/sensors/vs/0",
             lambda rep, _r: _sensor(rep, "SuperFineDust")),
    ),
)


def _sensor(rep, sensor_type: str):
    """A reading from /sensors/vs/0, which keys by `type` and wraps values in a
    single-element list."""
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


# --- dehumidifier ---------------------------------------------------------

DEHUMIDIFIER = Registry(
    name="dehumidifier",
    device_class="other",
    titles={"en": "Samsung Dehumidifier", "ko": "삼성 제습기"},
    specs=(
        *shared.POWER,
        *shared.UNIVERSAL,
        Spec("measure_humidity", "/humidity/vs/0",
             lambda rep, _r: as_float(rep.get("x.com.samsung.da.humidity")) or None),
        Spec("localthings_target_humidity", "/humidity/vs/0",
             lambda rep, _r: as_float(rep.get("x.com.samsung.da.desiredHumidity")),
             lambda value, _rep: (
                 ["humidity", "vs", "0"],
                 {"x.com.samsung.da.desiredHumidity": str(int(round(float(value))))},
             )),
        Spec("localthings_filter_usage", "/filter/airdustfilter/vs/0",
             shared._filter_percent),
        Spec("localthings_alarm_filter", "/filter/airdustfilter/vs/0",
             shared.read_filter_alarm),
    ),
)

# --- oven, range, microwave ----------------------------------------------
#
# Heat controls are read-only throughout, for the reason the reference gives for
# cooktops: an automation must not start a heating appliance. The setpoint and mode
# are reported, not settable.

HREF_OVEN = "/oven/vs/0"


def _oven_specs():
    return (
        Spec("localthings_operation_state", HREF_OVEN,
             shared.text("x.com.samsung.da.operationState")),
        Spec("localthings_oven_mode", HREF_OVEN,
             shared.text("x.com.samsung.da.mode")),
        Spec("measure_temperature.cavity", HREF_OVEN,
             lambda rep, _r: as_float(rep.get("x.com.samsung.da.temperature")),
             titles={"en": "Cavity", "ko": "내부"}),
        Spec("localthings_target_temperature_readonly", HREF_OVEN,
             lambda rep, _r: as_float(rep.get("x.com.samsung.da.desiredTemperature")),
             titles={"en": "Set temperature", "ko": "설정 온도"}),
        Spec("alarm_contact", "/door/vs/0", shared.flag("openState", on="Open")),
    )


OVEN = Registry(
    name="oven", device_class="other",
    titles={"en": "Samsung Oven", "ko": "삼성 오븐"},
    specs=(*shared.POWER, *shared.UNIVERSAL, *shared.OPERATIONAL, *_oven_specs()),
)

MICROWAVE = Registry(
    name="microwave", device_class="other",
    titles={"en": "Samsung Microwave", "ko": "삼성 전자레인지"},
    specs=(*shared.POWER, *shared.UNIVERSAL, *shared.OPERATIONAL, *_oven_specs()),
)

RANGE = Registry(
    name="range", device_class="other",
    titles={"en": "Samsung Range", "ko": "삼성 레인지"},
    specs=(*shared.POWER, *shared.UNIVERSAL, *shared.OPERATIONAL, *_oven_specs()),
)

# --- gas cooktop ----------------------------------------------------------
#
# A different family from the induction cooktop: burner state is embedded in
# /mode/vs/0's options array. Read-only in the reference and here.

GAS_COOKTOP = Registry(
    name="cooktop",
    device_class="other",
    titles={"en": "Samsung Gas Cooktop", "ko": "삼성 가스쿡탑"},
    specs=(
        *shared.ALARMS,
        *shared.FIRMWARE,
        Spec("localthings_power_state", "/power/vs/0",
             shared.flag("x.com.samsung.da.power")),
        Spec("localthings_burner_any_active", "/mode/vs/0", lambda rep, _r:
             _any_burner_active(rep)),
    ),
)

_BURNER_IDLE = {"off", "ready"}


def _any_burner_active(rep):
    """True when any `OperationState<n>_<value>` option is not idle."""
    options = rep.get("x.com.samsung.da.options")
    if not isinstance(options, list):
        return None
    seen = False
    for option in options:
        if not isinstance(option, str) or not option.startswith("OperationState"):
            continue
        _, _, value = option.partition("_")
        if not value:
            continue
        seen = True
        if value.strip().lower() not in _BURNER_IDLE:
            return True
    return False if seen else None


# --- range hood -----------------------------------------------------------

RANGE_HOOD = Registry(
    name="range_hood",
    device_class="fan",
    titles={"en": "Samsung Range Hood", "ko": "삼성 주방 후드" },
    specs=(
        *shared.ALARMS,
        *shared.ENERGY,
        *shared.FIRMWARE,
        Spec("localthings_fan_speed_level", "/hood/fanspeed/vs/0",
             lambda rep, _r: as_int(rep.get("fanSpeed") or rep.get("speed"))),
        Spec("localthings_display_light", "/hood/lamp/vs/0", shared.flag("status"),
             shared.write_flag(["hood", "lamp", "vs", "0"], "status")),
        Spec("localthings_filter_usage", "/hood/filter/vs/0", shared._filter_percent),
        Spec("localthings_alarm_filter", "/hood/filter/vs/0",
             shared.read_filter_alarm),
        Spec("localthings_air_quality", "/sensors/vs/0",
             lambda rep, _r: _sensor(rep, "CleanLevel")),
    ),
)

# --- water purifier -------------------------------------------------------

WATER_PURIFIER = Registry(
    name="water_purifier",
    device_class="other",
    titles={"en": "Samsung Water Purifier", "ko": "삼성 정수기"},
    specs=(
        *shared.UNIVERSAL,
        *shared.WATER_FILTER,
        *shared.WATER_METER,
        Spec("localthings_child_lock", "/lock/vs/0", shared.flag("status"),
             shared.write_flag(["lock", "vs", "0"], "status")),
        Spec("localthings_operation_state", "/status/vs/0",
             shared.text("x.com.samsung.da.status")),
    ),
)

# --- vacuum station -------------------------------------------------------

VACUUM_STATION = Registry(
    name="vacuum_station",
    device_class="other",
    titles={"en": "Samsung Clean Station", "ko": "삼성 청정스테이션"},
    specs=(
        *shared.POWER,
        *shared.UNIVERSAL,
        Spec("localthings_operation_state", "/cleanstation/status/vs/0",
             shared.text("status")),
        Spec("localthings_dustbag_usage", "/dustbag/vs/0",
             lambda rep, _r: as_float(rep.get("usage") or rep.get("dustBagUsage"))),
        Spec("localthings_alarm_dustbag", "/dustbag/vs/0",
             lambda rep, _r: _dustbag_full(rep)),
    ),
)


def _dustbag_full(rep):
    status = rep.get("status") or rep.get("dustBagStatus")
    return None if status is None else str(status).strip().lower() not in ("normal", "")


# --- air dresser ----------------------------------------------------------

AIR_DRESSER = Registry(
    name="air_dresser",
    device_class="other",
    titles={"en": "Samsung AirDresser", "ko": "삼성 에어드레서"},
    specs=(
        *shared.POWER,
        *shared.UNIVERSAL,
        *shared.OPERATIONAL,
        Spec("localthings_sanitize", "/airdresser/vs/0",
             shared.flag("x.com.samsung.da.sanitize"),
             shared.write_flag(["airdresser", "vs", "0"],
                               "x.com.samsung.da.sanitize")),
    ),
)


# --- board tokens ---------------------------------------------------------
# Straight from the reference's _BOARD_TOKEN_TO_KEY and _CONSUMER_PREFIX_TO_KEY.

BOARD_TOKENS = {
    "REF": REFRIGERATOR,
    "ADW": DISHWASHER,
    "AHD": RANGE_HOOD,
    "AIR": AIR_PURIFIER,
    "TVTL": AIR_PURIFIER,
    "VTWW": AIR_PURIFIER,
    "DHM": DEHUMIDIFIER,
    "OVEN": OVEN,
    "MICROWAVE": MICROWAVE,
    "RANGE": RANGE,
    "CT": GAS_COOKTOP,
    "WATERPURIFIER": WATER_PURIFIER,
    "VSKR": VACUUM_STATION,
    "DF": AIR_DRESSER,
}

# Consumer-model prefixes, matched against the *start* of a '_'-delimited segment of
# `description`. Deliberately separate from the board tokens and consulted only
# after them: 'WAC' (window air conditioner) also starts with 'WA' (top-load
# washer), so a two-letter prefix must never outrank a specific board token.
CONSUMER_PREFIXES = {
    "WW": WASHER,
    "WD": WASHER,
    "WF": WASHER,
    "WV": WASHER,
    "WA": WASHER,
    "DV": DRYER,
    "DW": DISHWASHER,
}

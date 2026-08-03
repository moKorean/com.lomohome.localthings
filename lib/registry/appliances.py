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
from .base import Registry, Spec, as_float, as_int

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

# Samsung fridges report temperature twice: per-compartment OCF resources
# (/temperature/current/<c>/0, /temperature/desired/<c>/0, each carrying its own
# `range`) and one vendor aggregate (/temperatures/vs/0) that repeats the same
# numbers. Where both exist the per-compartment resources are the live ones and the
# aggregate is second-class — this firmware demonstrably does not keep the aggregate
# current, which is how a door reported through /doors/vs/0 stayed shut forever while
# the same door read through /door/onedoorfreezer/vs/0 worked. So the aggregate is
# used only by units that have nothing else, exactly as the reference does.
#
# OCF compartment segment -> the description used in the vendor aggregate.
_COMPARTMENTS = {"cooler": "Fridge", "freezer": "Freezer"}


def _ocf_current(compartment: str) -> str:
    return f"/temperature/current/{compartment}/0"


def _ocf_desired(compartment: str) -> str:
    return f"/temperature/desired/{compartment}/0"


def has_ocf_temperatures(resources) -> bool:
    """Whether this unit reports per-compartment temperature resources."""
    return any(href.startswith("/temperature/") for href in resources)


def _in_ocf_range(rep: dict):
    """`temperature`, or None when it falls outside the resource's own `range`.

    A convertible cabinet parks 253 in the compartment it is not using — see
    _in_range below for the evidence that this is a marker and not an encoding.
    """
    value = as_float(rep.get("temperature"))
    bounds = rep.get("range")
    if value is None:
        return None
    if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
        low, high = as_float(bounds[0]), as_float(bounds[1])
        if low is not None and high is not None and not low <= value <= high:
            return None
    return value


def _ocf_reading(rep, _resources):
    """A current temperature, reported even when outside the setpoint range.

    Those bounds describe the setpoints the compartment accepts, not what its sensor
    can read: a cabinet running as kimchi storage reports 2 °C against a freezer
    range of -23..-17, and 2 °C is genuinely its temperature.
    """
    return as_float(rep.get("temperature"))


def _ocf_setpoint(rep, _resources):
    return _in_ocf_range(rep)


def _ocf_active(rep, _resources) -> bool:
    """Whether the compartment is in use, so an idle one is offered nothing.

    Both compartments of a convertible cabinet report the same current temperature,
    because there is one physical compartment. Only the one whose setpoint is
    believable is bound.
    """
    return _in_ocf_range(rep) is not None


def _ocf_compartment_in_use(compartment: str):
    """Whether the compartment is in use, judged from its *setpoint* resource.

    A current-temperature resource cannot tell: both compartments of a convertible
    cabinet report the same reading. The sibling /temperature/desired/<c>/0 is what
    carries the idle marker.
    """

    def exists(_rep, resources):
        desired = resources.get(_ocf_desired(compartment))
        return bool(desired) and _in_ocf_range(desired) is not None

    return exists


def _ocf_options(rep, _resources) -> dict:
    bounds = rep.get("range")
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
        return {}
    low, high = as_float(bounds[0]), as_float(bounds[1])
    if low is None or high is None:
        return {}
    return {"min": low, "max": high, "step": 1, "decimals": 0}


def _write_ocf_setpoint(compartment: str):
    """Write the setpoint on the resource it was read from.

    Deliberately not the vendor aggregate. The reference notes that on some models
    only the vendor path commits and prefers it for that reason, but on this firmware
    the aggregate is the stale copy, and a write whose result is then read back from a
    different resource cannot be confirmed either way. Writing and reading one
    resource makes the outcome visible.

    The body carries only `temperature`; `range` and `units` are the device's to
    report. That also keeps the optimistic local merge honest — the vendor body would
    have replaced the whole items[] array with a single partial entry, briefly
    erasing the other compartment's bounds.
    """
    segments = ["temperature", "desired", compartment, "0"]

    def write(value, rep):
        try:
            target = round(float(value))
        except (TypeError, ValueError):
            return None
        bounds = rep.get("range")
        if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
            low, high = as_float(bounds[0]), as_float(bounds[1])
            if low is not None and high is not None and not low <= target <= high:
                return None
        return segments, {"temperature": target}

    return write


def _fridge_item(rep, compartment: str) -> dict:
    """The vendor items[] entry for a named compartment, or {}."""
    for item in rep.get("x.com.samsung.da.items") or ():
        if not isinstance(item, dict):
            continue
        description = str(item.get("x.com.samsung.da.description") or "")
        if compartment.lower() in description.lower():
            return item
    return {}


def _fridge_temp(rep, compartment: str):
    """Current temperature from the vendor aggregate. See _ocf_reading on why this
    is reported even outside the compartment's setpoint bounds."""
    return as_float(_fridge_item(rep, compartment).get("x.com.samsung.da.current"))


def _in_range(item: dict):
    """The item's `desired`, or None when it is outside the bounds it advertises.

    A convertible cabinet leaves a marker in the idle compartment's `desired`: units
    of the same model in opposite modes report Freezer(desired 253)/Fridge(desired 2)
    when cooling and Freezer(desired -20)/Fridge(desired 253) when freezing, so 253
    marks the compartment not in use. It is not an encoding of -20 °C — the unit
    actually freezing reports -20 there directly.
    """
    value = as_float(item.get("x.com.samsung.da.desired"))
    low = as_float(item.get("x.com.samsung.da.minimum"))
    high = as_float(item.get("x.com.samsung.da.maximum"))
    if value is None:
        return None
    if low is not None and high is not None and not low <= value <= high:
        return None
    return value


def _compartment_active(compartment: str):
    """Whether this unit is using the named compartment, per the vendor aggregate."""

    def exists(rep, resources):
        if has_ocf_temperatures(resources):
            return False       # the per-compartment resources cover it
        item = _fridge_item(rep, compartment)
        return bool(item) and _in_range(item) is not None

    return exists


def _fridge_setpoint(compartment: str):
    def read(rep, _resources):
        return _in_range(_fridge_item(rep, compartment))

    return read


def _fridge_setpoint_options(compartment: str):
    def options(rep, _resources) -> dict:
        item = _fridge_item(rep, compartment)
        low = as_float(item.get("x.com.samsung.da.minimum"))
        high = as_float(item.get("x.com.samsung.da.maximum"))
        if low is None or high is None:
            return {}
        return {"min": low, "max": high, "step": 1, "decimals": 0}

    return options


# Item ids follow Samsung's convention, which the reference states and the verified
# units confirm: "0" is the freezer, "1" the fridge/cooler.
_FRIDGE_ITEM_IDS = {"Freezer": "0", "Fridge": "1"}


def _write_fridge_setpoint(compartment: str):
    def write(value, rep):
        item = _fridge_item(rep, compartment)
        low = as_float(item.get("x.com.samsung.da.minimum"))
        high = as_float(item.get("x.com.samsung.da.maximum"))
        try:
            target = round(float(value))
        except (TypeError, ValueError):
            return None
        if low is not None and high is not None and not low <= target <= high:
            return None
        return (
            ["temperatures", "vs", "0"],
            {"x.com.samsung.da.items": [{
                "x.com.samsung.da.id": _FRIDGE_ITEM_IDS[compartment],
                "x.com.samsung.da.desired": str(target),
            }]},
        )

    return write


# The convertible ("변온") compartment's current function, from /mode/vs/0's modes
# list. That list holds several orthogonal flags — CVN_KIMCHI_STORAGE says the
# compartment *can* store kimchi, CV_NULL is an unused slot — and only the
# MULTIROOM_ member tracks what the user selected. Two units of this model in
# opposite modes established the mapping: the one set to 냉장 reports
# MULTIROOM_COOLER, the one set to 냉동 reports MULTIROOM_FREEZER. The fridge-only
# variant has no `modes` at all, so nothing binds there.
#
# Read-only, and reported as a plain string rather than an enum. Only those two
# values have been observed; the appliance also offers a kimchi setting whose token
# is unknown, and an enum missing it would go blank the moment someone selected it.
# Selecting by prefix rather than position means an unseen value still reads through
# as itself. No write: the reference has no confirmed write for this resource on
# this family either, and switching a cabinet between fridge and freezer is not
# something to fire blind.
_MULTIROOM_PREFIX = "MULTIROOM_"
_MULTIROOM_NAMES = {"COOLER": "Cooler", "FREEZER": "Freezer"}


def _read_convertible_mode(rep, _resources):
    for mode in rep.get("x.com.samsung.da.modes") or ():
        token = str(mode)
        if token.startswith(_MULTIROOM_PREFIX):
            suffix = token[len(_MULTIROOM_PREFIX):]
            return _MULTIROOM_NAMES.get(suffix.upper(), suffix.title())
    return None


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
                               "x.com.samsung.da.rapidFridge"),
             exists=lambda rep, _r: "x.com.samsung.da.rapidFridge" in rep),
        # Absent on the fridge-only variant, which carries /refrigeration/vs/0 for
        # rapidFridge alone — an ungated switch there wrote a field the appliance
        # does not have.
        Spec("localthings_rapid_freeze", "/refrigeration/vs/0",
             shared.flag("x.com.samsung.da.rapidFreezing"),
             shared.write_flag(["refrigeration", "vs", "0"],
                               "x.com.samsung.da.rapidFreezing"),
             exists=lambda rep, _r: "x.com.samsung.da.rapidFreezing" in rep),
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
        # Gated on the compartment actually being in that array: the same model
        # ships as a fridge-only variant whose items[] carries the Fridge entry
        # alone, and an ungated spec gave it a freezer thermometer that could only
        # ever be blank.
        # Per-compartment resources first — the live copy on hardware that has them.
        Spec("measure_temperature.fridge", _ocf_current("cooler"), _ocf_reading,
             exists=_ocf_compartment_in_use("cooler"),
             titles={"en": "Fridge", "ko": "냉장실"}),
        Spec("measure_temperature.freezer", _ocf_current("freezer"), _ocf_reading,
             exists=_ocf_compartment_in_use("freezer"),
             titles={"en": "Freezer", "ko": "냉동실"}),
        Spec("target_temperature.fridge", _ocf_desired("cooler"),
             _ocf_setpoint, _write_ocf_setpoint("cooler"),
             exists=_ocf_active, options=_ocf_options,
             titles={"en": "Fridge", "ko": "냉장실"}),
        Spec("target_temperature.freezer", _ocf_desired("freezer"),
             _ocf_setpoint, _write_ocf_setpoint("freezer"),
             exists=_ocf_active, options=_ocf_options,
             titles={"en": "Freezer", "ko": "냉동실"}),
        # The vendor aggregate, for units that report nothing more precise. Gated on
        # the per-compartment resources being absent so the two never both bind.
        Spec("measure_temperature.freezer", "/temperatures/vs/0",
             lambda rep, _r: _fridge_temp(rep, "Freezer"),
             exists=_compartment_active("Freezer"),
             titles={"en": "Freezer", "ko": "냉동실"}),
        Spec("measure_temperature.fridge", "/temperatures/vs/0",
             lambda rep, _r: _fridge_temp(rep, "Fridge"),
             exists=_compartment_active("Fridge"),
             titles={"en": "Fridge", "ko": "냉장실"}),
        Spec("target_temperature.freezer", "/temperatures/vs/0",
             _fridge_setpoint("Freezer"), _write_fridge_setpoint("Freezer"),
             exists=_compartment_active("Freezer"),
             titles={"en": "Freezer", "ko": "냉동실"},
             options=_fridge_setpoint_options("Freezer")),
        Spec("target_temperature.fridge", "/temperatures/vs/0",
             _fridge_setpoint("Fridge"), _write_fridge_setpoint("Fridge"),
             exists=_compartment_active("Fridge"),
             titles={"en": "Fridge", "ko": "냉장실"},
             options=_fridge_setpoint_options("Fridge")),
        Spec("localthings_convertible_mode", "/mode/vs/0", _read_convertible_mode,
             exists=lambda rep, _r: _read_convertible_mode(rep, _r) is not None),
    ),
)


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
                 {"x.com.samsung.da.desiredHumidity": str(round(float(value)))},
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
#
# Verified against an AHD-WW-TP1-22-COMMON. Every field name and every supported
# value below was read off that unit, because the first version of this registry
# guessed them (`fanSpeed`, `status`, `/hood/filter/vs/0`) and guessed wrong: not
# one of them matched, so the hood paired and then sat there with no working
# control at all. Nothing here is inferred from the field's name.

HREF_HOOD_FAN = "/hood/fanspeed/vs/0"
HREF_HOOD_LAMP = "/hood/lamp/vs/0"
HREF_HOOD_FILTER = "/filter/hoodfilter/vs/0"

FIELD_FAN_SPEED = "x.com.samsung.da.hood.fanSpeed"
FIELD_FAN_SUPPORTED = "x.com.samsung.da.hood.supportedFanSpeed"
# Reference #201: the form used by boards that omit supportedFanSpeed entirely.
FIELD_FAN_MIN = "x.com.samsung.da.hood.settableMinFanSpeed"
FIELD_FAN_MAX = "x.com.samsung.da.hood.settableMaxFanSpeed"
FIELD_AUTO_OPERATION = "x.com.samsung.da.hood.autoOperation"
FIELD_LAMP_POWER = "x.com.samsung.lamp.power"
FIELD_LAMP_CURRENT = "x.com.samsung.lamp.current"
FIELD_LAMP_RANGE = "x.com.samsung.lamp.range"


def _codes(rep, field) -> list:
    """The device's supported values for `field`, in the order it reports them."""
    return [str(code) for code in (rep.get(field) or ()) if str(code) != ""]


def _field_codes(field):
    """Codes read straight from a supported-values list."""
    return lambda rep: _codes(rep, field)


def _fan_codes(rep) -> list:
    """The hood's fan-speed codes, from whichever form the board reports.

    The verified AHD-WW-TP1-22 lists them in `supportedFanSpeed`, but reference
    #201 found boards that omit that field and advertise a
    `settableMinFanSpeed`/`settableMaxFanSpeed` pair instead. Without this those
    hoods bound the capability and then had no codes at all: nothing to read, a
    write that could never resolve, and an empty slider.

    The range is only used as a fallback. Where both forms are present the
    explicit list wins, because it is the one that can describe a
    non-contiguous set — which the verified hood's 14-18 happens not to be, but
    which nothing guarantees.
    """
    supported = _codes(rep, FIELD_FAN_SUPPORTED)
    if supported:
        return supported
    low, high = as_int(rep.get(FIELD_FAN_MIN)), as_int(rep.get(FIELD_FAN_MAX))
    if low is None or high is None or low > high:
        return []
    return [str(code) for code in range(low, high + 1)]


def _read_level(value_field, codes_of):
    """Report a device code as its 1-based position in the supported list.

    The verified hood calls its five fan speeds "14" through "18" and its two lamp
    levels "1" and "2". Surfacing the raw codes would put a slider from 14 to 18 in
    front of the user, and would break outright on a unit whose codes are not
    contiguous. The position is stable, reads as a level, and needs no assumption
    about what the codes mean — only that the device lists them in order.
    """

    def read(rep, _resources):
        codes = codes_of(rep)
        current = rep.get(value_field)
        if current is None or not codes:
            return None
        try:
            return codes.index(str(current)) + 1
        except ValueError:
            # A current value outside the advertised list: report nothing rather
            # than a position that would be wrong.
            return None

    return read


def _write_level(path, value_field, codes_of):
    def write(value, rep):
        codes = codes_of(rep)
        index = as_int(value)
        if not codes or index is None or not 1 <= index <= len(codes):
            return None
        return path, {value_field: codes[index - 1]}

    return write


def _level_options(codes_of):
    def options(rep, _resources) -> dict:
        codes = codes_of(rep)
        return {"min": 1, "max": len(codes), "step": 1} if codes else {}

    return options


def _has_codes(codes_of):
    """Bind a level capability only where the device advertises the levels.

    Without this a board that reports neither form gets a slider it cannot
    honour. The reference reaches the same place from the other direction — it
    drops the SET_SPEED feature when `speed_count` is 0 — but a Homey capability
    is all-or-nothing, so the gate has to be on the capability itself.
    """
    return lambda rep, _resources: bool(codes_of(rep))


def _has(field):
    return lambda rep, _resources: field in rep


def _read_filter_status_alarm(rep, _resources):
    """The hood reports filter state as a word, not as an alarm row."""
    status = rep.get("x.com.samsung.da.filterStatus")
    if status is None:
        return None
    return str(status).strip().lower() not in ("normal", "", "none")


RANGE_HOOD = Registry(
    name="range_hood",
    device_class="fan",
    titles={"en": "Samsung Range Hood", "ko": "삼성 주방 후드"},
    specs=(
        # The hood answers on both power forms; POWER was missing entirely before,
        # which is why the appliance could not be switched on or off.
        *shared.POWER,
        *shared.ALARMS,
        *shared.ENERGY,
        *shared.FIRMWARE,
        Spec("localthings_hood_fan_speed", HREF_HOOD_FAN,
             _read_level(FIELD_FAN_SPEED, _fan_codes),
             _write_level(["hood", "fanspeed", "vs", "0"],
                          FIELD_FAN_SPEED, _fan_codes),
             exists=_has_codes(_fan_codes),
             options=_level_options(_fan_codes)),
        Spec("localthings_auto_ventilation", HREF_HOOD_FAN,
             shared.flag(FIELD_AUTO_OPERATION),
             exists=_has(FIELD_AUTO_OPERATION)),
        # Titled per device: the shared capability is the air conditioner's panel
        # indicator, which "표시등" describes correctly, but on a hood the same
        # capability drives the light over the cooktop.
        Spec("localthings_display_light", HREF_HOOD_LAMP,
             shared.flag(FIELD_LAMP_POWER),
             shared.write_flag(["hood", "lamp", "vs", "0"], FIELD_LAMP_POWER),
             titles={"en": "Light", "ko": "조명"}),
        Spec("localthings_lamp_brightness", HREF_HOOD_LAMP,
             _read_level(FIELD_LAMP_CURRENT, _field_codes(FIELD_LAMP_RANGE)),
             _write_level(["hood", "lamp", "vs", "0"],
                          FIELD_LAMP_CURRENT, _field_codes(FIELD_LAMP_RANGE)),
             exists=_has(FIELD_LAMP_RANGE),
             options=_level_options(_field_codes(FIELD_LAMP_RANGE))),
        Spec("localthings_filter_usage", HREF_HOOD_FILTER, shared._filter_percent),
        Spec("localthings_alarm_filter", HREF_HOOD_FILTER,
             _read_filter_status_alarm),
        Spec("localthings_air_quality", "/sensors/vs/0",
             lambda rep, _r: _sensor(rep, "CleanLevel")),
        Spec("localthings_dust_pm10", "/sensors/vs/0",
             lambda rep, _r: _sensor(rep, "Dust")),
        Spec("measure_pm25", "/sensors/vs/0",
             lambda rep, _r: _sensor(rep, "FineDust")),
        Spec("localthings_dust_pm1", "/sensors/vs/0",
             lambda rep, _r: _sensor(rep, "SuperFineDust")),
    ),
)

# --- EHS heat pump ---------------------------------------------------------

# Samsung's Eco Heating System, an air-to-water heat pump (TP1X_DA_AC_EHS).
# Shares the DA_AC_ board prefix with the room air conditioners but not their
# resource shape: two independent loops, zone1 for space heating and dhw for
# domestic hot water, each with its own mode and temperature hrefs.
#
# Only the parts that map onto capabilities this app already defines are bound.
# The zone mode, the whole hot-water loop and the away switch need capabilities
# and icons of their own, and there is no EHS here to check any of it against —
# see docs/BACKLOG.md rather than guessing at a heat pump's controls.
#
# The setpoint is leaving-water temperature, not room temperature, which is why
# the reference notes its `type=Water` field is not a literal water reading.

HREF_EHS_TEMPERATURES = "/temperatures/indoor/vs/0"

EHS = Registry(
    name="ehs",
    device_class="heater",
    titles={"en": "Samsung Heat Pump", "ko": "삼성 열펌프"},
    specs=(
        *shared.POWER,
        *shared.UNIVERSAL,
        Spec("measure_temperature", HREF_EHS_TEMPERATURES,
             lambda rep, _r: as_float(rep.get("x.com.samsung.da.current"))),
        Spec("target_temperature", HREF_EHS_TEMPERATURES,
             lambda rep, _r: as_float(rep.get("x.com.samsung.da.desired")),
             lambda value, _rep: (["temperatures", "indoor", "vs", "0"],
                                  {"x.com.samsung.da.desired": str(float(value))}),
             options=lambda rep, _r: _ehs_setpoint_options(rep)),
    ),
)


def _ehs_setpoint_options(rep) -> dict:
    """Bounds from the resource, falling back to the range the reference uses.

    Its defaults are 5-30 in half degrees; a board that reports its own minimum,
    maximum or increment overrides them.
    """
    low = as_float(rep.get("x.com.samsung.da.minimum"))
    high = as_float(rep.get("x.com.samsung.da.maximum"))
    step = as_float(rep.get("x.com.samsung.da.increment"))
    return {
        "min": 5.0 if low is None else low,
        "max": 30.0 if high is None else high,
        "step": 0.5 if step is None else step,
        "decimals": 1,
    }


# --- air quality monitor ---------------------------------------------------

# Reference #210 (ASM-KR-TP1-22 board): a battery-powered air-quality puck with
# no controllable state at all, so this is sensors only. No POWER — the board has
# no /power/* resource, only /energy/battery/vs/0.
#
# Built entirely from readings this app already maps for the air purifier, so it
# adds no capability definitions of its own. Two of the reference's resources are
# left out rather than guessed at: /dnd/vs/0 is a start/end time pair with no
# matching Homey capability type, and /airqualitystandard/vs/0 is a free-text
# standard name. Neither is verifiable here — see docs/BACKLOG.md.

AIR_MONITOR = Registry(
    name="air_monitor",
    device_class="sensor",
    titles={"en": "Samsung Air Monitor", "ko": "삼성 에어모니터"},
    specs=(
        *shared.UNIVERSAL,
        Spec("localthings_air_quality", "/sensors/vs/0",
             lambda rep, _r: _sensor(rep, "CleanLevel")),
        Spec("measure_pm25", "/sensors/vs/0", lambda rep, _r: _sensor(rep, "FineDust")),
        Spec("localthings_dust_pm10", "/sensors/vs/0",
             lambda rep, _r: _sensor(rep, "Dust")),
        Spec("localthings_dust_pm1", "/sensors/vs/0",
             lambda rep, _r: _sensor(rep, "SuperFineDust")),
        Spec("measure_co2", "/sensors/vs/0", lambda rep, _r: _sensor(rep, "CO2")),
        Spec("measure_humidity", "/humidity/vs/0",
             lambda rep, _r: as_float(rep.get("x.com.samsung.da.humidity"))),
        Spec("measure_battery", "/energy/battery/vs/0",
             lambda rep, _r: as_float(rep.get("x.com.samsung.da.battery"))),
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
        # Reference #196 (AILITE_DA-REF-WATERPURIFIER, RWP70F15ANW) found these
        # two hrefs on this family, at the same paths the air conditioner and
        # air purifier already read. Its own note is worth keeping: this board's
        # supportedModes are voice/fixedTone/mute, which match neither of the
        # other two families' value sets. That is only a hazard for a writer
        # choosing from a hardcoded list — our sound mode is a free-form
        # read-only string, so an unfamiliar value reports rather than rejects.
        *shared.SOUND,
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
    # A next-gen BESPOKE Cube Air board, AVT-WW-TP1-23-AXX500. Same lineage and
    # the same resource surface as VTWW, but the "-WW-" delimiter falls one letter
    # to the left ("A-VTWW-" became "AVT-WW-"), which splits into a token the VTWW
    # entry cannot see. Reference issue #190.
    "AVT": AIR_PURIFIER,
    "DHM": DEHUMIDIFIER,
    "OVEN": OVEN,
    "MICROWAVE": MICROWAVE,
    "RANGE": RANGE,
    "CT": GAS_COOKTOP,
    "WATERPURIFIER": WATER_PURIFIER,
    "VSKR": VACUUM_STATION,
    # Reference #219 — the same stick-vacuum clean station as VSKR on a different
    # regional board. Two tokens, one family.
    "VSWW": VACUUM_STATION,
    "DF": AIR_DRESSER,
    "ASM": AIR_MONITOR,             # reference #210 — Air Monitor Plus
    "EHS": EHS,                     # air-to-water heat pump
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

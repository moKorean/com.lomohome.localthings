"""Registry regression against a real /device/0 dump.

The fixture is a live capture, so these assertions pin the mapping to hardware
behaviour rather than to assumptions about it.
"""

import json
from pathlib import Path

import pytest

from lib import registry
from lib.registry import airconditioner

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "airconditioner_TP1X_DA-AC-CAC-01001.json"
)


@pytest.fixture(scope="module")
def resources():
    return json.loads(FIXTURE.read_text())["resources"]


def test_resolves_to_airconditioner(resources):
    """The CAC board family must route, which is what the reference misses."""
    assert registry.resolve(resources) is airconditioner.REGISTRY


def test_resolve_is_none_for_unknown_board():
    assert registry.resolve({"/information/vs/0": {
        "x.com.samsung.da.modelNum": "TP1X_DA-XX-NOPE-00001|1|2",
    }}) is None


def test_bare_ac_token_does_not_swallow_its_siblings():
    """'DA-AC-' prefixes the dehumidifier and air purifier as well as the air
    conditioner, so routing must key on the specific token. A bare 'AC' entry would
    make all three air conditioners."""
    for token, expected in (
        ("DHM", "dehumidifier"),
        ("AIR", "air_purifier"),
        ("CAC", "airconditioner"),
    ):
        resolved = registry.resolve({"/information/vs/0": {
            "x.com.samsung.da.modelNum": f"TP1X_DA-AC-{token}-01001|1|2",
        }})
        assert resolved is not None and resolved.name == expected, token


def test_capabilities_present(resources):
    reg = registry.resolve(resources)
    caps = reg.capabilities(resources)
    for expected in (
        "onoff",
        "target_temperature",
        "measure_temperature",
        "measure_humidity",
        "measure_power",
        "meter_power",
        "localthings_ac_mode",
        "localthings_fan_mode",
        "localthings_air_purify",
        "localthings_filter_usage",
        "localthings_alarm_filter",
    ):
        assert expected in caps, expected


def reg_of(resources):
    return registry.resolve(resources)


def _read(reg, resources, capability):
    spec = reg.spec_for(capability)
    return spec.read(resources[spec.href], resources)


def test_reads_match_the_captured_device_state(resources):
    reg = registry.resolve(resources)
    assert _read(reg, resources, "onoff") is True
    assert _read(reg, resources, "measure_temperature") == 29.0
    assert _read(reg, resources, "target_temperature") == 27.0
    assert _read(reg, resources, "localthings_ac_mode") == "AIComfort"
    assert _read(reg, resources, "localthings_fan_mode") == "auto"
    assert _read(reg, resources, "measure_power") == 99.0
    assert _read(reg, resources, "meter_power") == pytest.approx(146.497)
    assert _read(reg, resources, "localthings_air_purify") is True
    # This line asserted 55.6 for a long time, which was the app dividing usage by
    # capacity. The two assertions contradicted each other: 56% of a filter's life is
    # not a filter the appliance flags for washing. The device reports usage as a
    # percentage already — 100, hence `wash`.
    air_filter = resources["/filter/airdustfilter/vs/0"]
    assert air_filter["x.com.samsung.da.filterUsage"] == "100"
    assert air_filter["x.com.samsung.da.filterStatus"] == "wash"
    assert _read(reg, resources, "localthings_filter_usage") == pytest.approx(100.0, abs=0.1)
    assert _read(reg, resources, "localthings_alarm_filter") is True


def test_humidity_prefers_fivepercent_field(resources):
    """The plain `humidity` field reads a flat 0 on this board while
    fivepercentHumidity carries the real value."""
    assert resources["/humidity/vs/0"]["x.com.samsung.da.humidity"] == "0"
    assert _read(reg_of(resources), resources, "measure_humidity") == 49.0



def test_write_payloads_send_only_the_changed_field(resources):
    reg = registry.resolve(resources)

    spec = reg.spec_for("onoff")
    assert spec.write(False, resources[spec.href]) == (
        ["power", "vs", "0"], {"x.com.samsung.da.power": "Off"},
    )

    spec = reg.spec_for("target_temperature")
    path, body = spec.write(24.0, resources[spec.href])
    assert path == ["temperatures", "vs", "0"]
    assert body["x.com.samsung.da.items"] == [
        {"x.com.samsung.da.id": "0", "x.com.samsung.da.desired": "24.0"}
    ]

    spec = reg.spec_for("localthings_ac_mode")
    assert spec.write("Cool", resources[spec.href]) == (
        ["mode", "vs", "0"], {"x.com.samsung.da.modes": ["Cool"]},
    )


def test_fan_write_maps_through_device_reported_names(resources):
    """Numeric fan codes are per-board, so the mapping must come from the
    device's own modesName array, not a hardcoded order."""
    reg = registry.resolve(resources)
    spec = reg.spec_for("localthings_fan_mode")
    rep = resources[spec.href]
    assert rep["x.com.samsung.da.modesName"] == ["Auto", "Low", "Mid", "High"]
    assert spec.write("high", rep) == (
        ["wind", "strength", "vs", "0"], {"x.com.samsung.da.modes": "3"},
    )
    # A mode this board doesn't offer must be refused rather than guessed.
    assert spec.write("nonexistent", rep) is None


def test_unbound_hrefs_are_reported(resources):
    """Coverage gaps must stay visible; silently dropping them is how a port
    looks complete while missing controls."""
    reg = registry.resolve(resources)
    gaps = registry.unbound_hrefs(resources, reg)
    # Sound settings and AI sleep are real features still unmapped; they must keep
    # showing up rather than being quietly dropped once coverage grows.
    assert "/settings/sound/volume/vs/0" in gaps
    assert "/aisleep/vs/0" in gaps
    assert "/power/vs/0" not in gaps
    assert "/uvled/vs/0" not in gaps


def _desired(spec, rep, value):
    return spec.write(value, rep)[1]["x.com.samsung.da.items"][0][
        "x.com.samsung.da.desired"
    ]


def test_setpoint_keeps_half_degrees_and_snaps_to_the_increment(resources):
    """The device advertises increment 0.5 and was verified to accept "28.5".
    Rounding to whole degrees both lost half steps and turned a real change into a
    no-op write, which the device refuses."""
    reg = registry.resolve(resources)
    spec = reg.spec_for("target_temperature")
    rep = resources[spec.href]
    assert rep["x.com.samsung.da.items"][0]["x.com.samsung.da.increment"] == "0.5"

    assert _desired(spec, rep, 28.5) == "28.5"
    assert _desired(spec, rep, 27.5) == "27.5"
    assert _desired(spec, rep, 27) == "27.0"
    # Off-step requests snap to the nearest supported step rather than being sent
    # as-is or truncated downward.
    assert _desired(spec, rep, 28.3) == "28.5"
    assert _desired(spec, rep, 28.7) == "28.5"


def test_setpoint_falls_back_to_half_steps_without_an_increment(resources):
    """A board that reports no increment must not silently become integer-only."""
    reg = registry.resolve(resources)
    spec = reg.spec_for("target_temperature")
    rep = {"x.com.samsung.da.items": [{"x.com.samsung.da.id": "0"}]}
    assert _desired(spec, rep, 28.5) == "28.5"


# --- expanded coverage ----------------------------------------------------


def test_expanded_coverage_binds_the_features_worth_controlling(resources):
    reg = registry.resolve(resources)
    caps = reg.capabilities(resources)
    for expected in (
        "localthings_auto_clean", "localthings_mute_once",
        "localthings_display_light", "localthings_edge_light",
        "localthings_absence_power_saving", "localthings_absence_clean",
        "localthings_motion_detect_wind", "localthings_smart_sensing_cooling",
        "localthings_uvled", "localthings_convenient_mode",
        "localthings_wind_direction", "localthings_power_save_mode",
        "localthings_wind_target", "localthings_light_mode",
        "localthings_alarm_code", "localthings_air_quality",
        "measure_pm25", "localthings_dust_pm10", "localthings_dust_pm1",
        "localthings_filter_usage.pm1",
    ):
        assert expected in caps, expected


def test_active_alarm_skips_cleared_and_idle_entries(resources):
    """The items array keeps cleared alarms around — the unit lists a deleted
    ErrorCode_OFF alongside a live FilterAlarm — so items[0] would report a stale
    code as current."""
    items = resources["/alarms/vs/0"]["x.com.samsung.da.items"]
    assert items[0]["x.com.samsung.da.code"] == "ErrorCode_OFF"
    assert items[0]["x.com.samsung.da.state"] == "Deleted"
    assert _read(reg_of(resources), resources, "localthings_alarm_code") == "FilterAlarm"


def test_no_active_alarm_reads_as_none():
    reg = registry.resolve({"/information/vs/0": {
        "x.com.samsung.da.modelNum": "TP1X_DA-AC-CAC-01001|1|2"}})
    spec = reg.spec_for("localthings_alarm_code")
    rep = {"x.com.samsung.da.items": [
        {"x.com.samsung.da.code": "ErrorCode_OFF", "x.com.samsung.da.state": "Deleted"},
    ]}
    assert spec.read(rep, {}) == "none"


def test_dust_sensors_are_read_by_type_not_position(resources):
    """/sensors/vs/0 keys its items by `type` and wraps each value in a
    single-element list, so positional access would mis-assign the readings."""
    reg = reg_of(resources)
    assert _read(reg, resources, "localthings_dust_pm10") == 16.0
    assert _read(reg, resources, "measure_pm25") == 10.0
    assert _read(reg, resources, "localthings_dust_pm1") == 8.0
    assert _read(reg, resources, "localthings_air_quality") == 1.0


def test_wind_direction_accepts_a_value_absent_from_supported_modes(resources):
    """The unit reports 'Fix' while advertising only Left_And_Right and All.
    Dropping it would leave the capability blank on a working device."""
    rep = resources["/wind/direction/vs/0"]
    assert "Fix" not in rep["x.com.samsung.da.supportedModes"]
    assert _read(reg_of(resources), resources, "localthings_wind_direction") == "Fix"


def test_enum_writes_refuse_undeclared_values(resources):
    """Sending a token the capability doesn't declare would be dropped silently by
    the device and leave the tile looking stuck."""
    reg = reg_of(resources)
    spec = reg.spec_for("localthings_convenient_mode")
    rep = resources[spec.href]
    assert spec.write("Sleep", rep) == (
        ["mode", "convenient", "vs", "0"], {"x.com.samsung.da.modes": "Sleep"})
    assert spec.write("Nonsense", rep) is None


def test_read_only_enums_stay_read_only(resources):
    """The reference leaves these unwritten under its don't-guess rule; matching
    that keeps us from writing to an unverified contract on live HVAC."""
    reg = reg_of(resources)
    for capability in ("localthings_power_save_mode", "localthings_wind_target",
                       "localthings_light_mode", "localthings_alarm_code",
                       "measure_pm25", "localthings_filter_usage.pm1"):
        assert not reg.spec_for(capability).writable, capability


def test_humidity_zero_is_a_reading_but_only_on_the_five_percent_field():
    reg = registry.resolve({"/information/vs/0": {
        "x.com.samsung.da.modelNum": "TP1X_DA-AC-CAC-01001|1|2"}})
    spec = reg.spec_for("measure_humidity")
    # A genuine 0% on the rounded field must pass through.
    assert spec.read({"x.com.samsung.da.fivepercentHumidity": "0"}, {}) == 0.0
    # On boards that only have the plain field, 0 means "not measuring".
    assert spec.read({"x.com.samsung.da.humidity": "0"}, {}) is None
    assert spec.read({"x.com.samsung.da.humidity": "51"}, {}) == 51.0


def test_pm1_filter_gets_its_own_title(resources):
    reg = reg_of(resources)
    options = reg.capability_options(resources, "ko")
    assert options["localthings_filter_usage.pm1"]["title"] == "PM1.0 필터"

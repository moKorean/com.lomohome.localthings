"""The range hood, pinned against a real AHD-WW-TP1-22-COMMON.

The first version of this registry guessed its field names — `fanSpeed` instead of
`x.com.samsung.da.hood.hoodFanSpeed`, `status` instead of `x.com.samsung.lamp.power`,
`/hood/filter/vs/0` instead of `/filter/hoodfilter/vs/0` — and had no power spec at
all. Every guess was wrong, so the hood paired, showed a handful of capabilities that
all read null, and controlled nothing.

None of that was catchable by the other tests: they check that capabilities have
definitions and that setable ones have writes, which a consistently wrong mapping
satisfies perfectly. Only real device data catches it, so the unit's own /device/0 is
committed as a fixture and the mapping is asserted against it.
"""

import json
from pathlib import Path

import pytest

from lib import registry
from lib.registry import appliances

FIXTURE = Path(__file__).parent / "fixtures/range_hood_AHD-WW-TP1-22.json"


@pytest.fixture
def resources() -> dict:
    return json.loads(FIXTURE.read_text())


def test_the_fixture_routes_to_the_hood(resources):
    assert registry.resolve(resources) is appliances.RANGE_HOOD


def test_power_is_readable_and_writable(resources):
    """The symptom the user reported first: the hood could not be switched on or
    off, because the registry had no power spec."""
    reg = appliances.RANGE_HOOD
    power = [s for s in reg.specs if s.capability == "onoff" and s.applies(resources)]
    assert power, "no onoff spec applies to the hood"
    assert any(s.writable for s in power), "onoff is read-only on the hood"

    for spec in power:
        rep = resources[spec.href]
        assert spec.read(rep, resources) is False, f"{spec.href} should read Off"
        path, body = spec.write(True, rep)
        assert path[0] == "power" and body, (path, body)


def test_fan_speed_reads_as_a_level_not_a_raw_code(resources):
    """The unit calls its five speeds "14".."18". A slider from 14 to 18 is what the
    user would otherwise see, and a non-contiguous list would break outright."""
    spec = _spec("localthings_hood_fan_speed", resources)
    rep = resources[spec.href]
    assert rep["x.com.samsung.da.hood.supportedFanSpeed"] == ["14", "15", "16", "17", "18"]
    assert rep["x.com.samsung.da.hood.fanSpeed"] == "14"
    assert spec.read(rep, resources) == 1, "lowest supported speed is level 1"
    assert spec.options(rep, resources) == {"min": 1, "max": 5, "step": 1}


def test_fan_speed_writes_the_device_code_for_the_level(resources):
    spec = _spec("localthings_hood_fan_speed", resources)
    rep = resources[spec.href]
    assert spec.write(1, rep) == (
        ["hood", "fanspeed", "vs", "0"],
        {"x.com.samsung.da.hood.fanSpeed": "14"},
    )
    assert spec.write(5, rep) == (
        ["hood", "fanspeed", "vs", "0"],
        {"x.com.samsung.da.hood.fanSpeed": "18"},
    )


@pytest.mark.parametrize("level", [0, 6, 99, -1, None, "high"])
def test_fan_speed_refuses_a_level_the_device_does_not_advertise(resources, level):
    """Returning None is what makes the device layer report a rejected write rather
    than POST a value the hood would refuse."""
    spec = _spec("localthings_hood_fan_speed", resources)
    assert spec.write(level, resources[spec.href]) is None


def test_lamp_power_reads_and_writes_the_lamp_field(resources):
    """The second symptom: the light could not be controlled, because the spec read
    `status` on a resource whose field is `x.com.samsung.lamp.power`."""
    spec = _spec("localthings_display_light", resources)
    rep = resources[spec.href]
    assert spec.href == "/hood/lamp/vs/0"
    assert rep["x.com.samsung.lamp.power"] == "Off"
    assert spec.read(rep, resources) is False
    assert spec.write(True, rep) == (
        ["hood", "lamp", "vs", "0"], {"x.com.samsung.lamp.power": "On"}
    )


def test_lamp_brightness_follows_the_advertised_range(resources):
    spec = _spec("localthings_lamp_brightness", resources)
    rep = resources[spec.href]
    assert rep["x.com.samsung.lamp.range"] == ["1", "2"]
    assert spec.read(rep, resources) == 2, "current '2' is the second of two levels"
    assert spec.options(rep, resources) == {"min": 1, "max": 2, "step": 1}
    assert spec.write(1, rep) == (
        ["hood", "lamp", "vs", "0"], {"x.com.samsung.lamp.current": "1"}
    )


def test_filter_is_read_from_the_href_the_device_actually_uses(resources):
    usage = _spec("localthings_filter_usage", resources)
    assert usage.href == "/filter/hoodfilter/vs/0"
    assert usage.read(resources[usage.href], resources) == 80

    alarm = _spec("localthings_alarm_filter", resources)
    rep = resources[alarm.href]
    assert rep["x.com.samsung.da.filterStatus"] == "normal"
    assert alarm.read(rep, resources) is False


@pytest.mark.parametrize(
    ("status", "expected"),
    [("normal", False), ("wash", True), ("replace", True), ("Normal", False)],
)
def test_filter_alarm_tracks_the_status_word(status, expected):
    alarm = next(
        s for s in appliances.RANGE_HOOD.specs
        if s.capability == "localthings_alarm_filter"
    )
    rep = {"x.com.samsung.da.filterStatus": status}
    assert alarm.read(rep, {}) is expected


def test_auto_operation_is_reported(resources):
    spec = _spec("localthings_auto_ventilation", resources)
    assert spec.read(resources[spec.href], resources) is False
    assert not spec.writable, "the hood advertises no write for auto operation"


def test_every_capability_the_hood_gets_actually_produces_a_value(resources):
    """A capability bound but permanently null is indistinguishable, to the user,
    from a broken app — it was the entire failure mode here. Anything that cannot
    read a value from real data should not be offered."""
    reg = appliances.RANGE_HOOD
    dead = []
    for spec in reg.specs:
        if not spec.applies(resources):
            continue
        rep = resources.get(spec.href) or {}
        try:
            value = spec.read(rep, resources)
        except Exception as exc:
            dead.append(f"{spec.capability}@{spec.href} raised {exc!r}")
            continue
        if value is None:
            dead.append(f"{spec.capability}@{spec.href} reads None")
    assert not dead, "capabilities offered but unreadable: " + "; ".join(dead)


def test_the_previous_wrong_mapping_cannot_come_back(resources):
    """Guard the specific mistakes, by name. Each read null on this hardware."""
    for spec in appliances.RANGE_HOOD.specs:
        assert spec.href != "/hood/filter/vs/0", "the hood has no /hood/filter/vs/0"
    assert "/hood/filter/vs/0" not in resources
    fan = _spec("localthings_hood_fan_speed", resources)
    rep = resources[fan.href]
    assert "fanSpeed" not in rep, "bare 'fanSpeed' is not a field on this device"
    assert "status" not in resources["/hood/lamp/vs/0"]


def _spec(capability: str, resources: dict):
    matches = [
        s for s in appliances.RANGE_HOOD.specs
        if s.capability == capability and s.applies(resources)
    ]
    assert len(matches) == 1, f"{capability}: {len(matches)} applicable specs"
    return matches[0]

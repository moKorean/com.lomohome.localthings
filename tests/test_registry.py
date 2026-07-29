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


def test_bare_ac_token_does_not_route():
    """'DA-AC-' prefixes the dehumidifier and air purifier too, so a bare AC
    token must not match — otherwise those mis-bind once ported."""
    assert registry.resolve({"/information/vs/0": {
        "x.com.samsung.da.modelNum": "TP1X_DA-AC-DHM-01001|1|2",
    }}) is None


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
    assert _read(reg, resources, "localthings_filter_usage") == pytest.approx(55.6, abs=0.1)
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
        {"x.com.samsung.da.id": "0", "x.com.samsung.da.desired": "24"}
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
    assert "/uvled/vs/0" in gaps
    assert "/power/vs/0" not in gaps

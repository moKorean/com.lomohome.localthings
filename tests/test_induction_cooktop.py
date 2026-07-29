"""Induction-cooktop regression against a live /device/0 dump."""

import json
from pathlib import Path

import pytest

from lib import registry
from lib.registry import induction_cooktop

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "induction_cooktop_TP1X_DA-KS-COOKTOP-01011.json"
)


@pytest.fixture(scope="module")
def resources():
    return json.loads(FIXTURE.read_text())["resources"]


def _read(reg, resources, capability):
    spec = reg.spec_for(capability)
    return spec.read(resources[spec.href], resources)


def test_resolves_by_board_token(resources):
    assert registry.resolve(resources) is induction_cooktop.REGISTRY


def test_cooktop_token_does_not_collide_with_air_conditioner(resources):
    """Both families are TP1X boards; only the specific token may decide."""
    assert registry.resolve({"/information/vs/0": {
        "x.com.samsung.da.modelNum": "TP1X_DA-AC-CAC-01001|1|2",
    }}).name == "airconditioner"
    assert registry.resolve(resources).name == "induction_cooktop"


def test_reads_match_the_captured_state(resources):
    reg = registry.resolve(resources)
    assert _read(reg, resources, "localthings_power_state") is False
    assert _read(reg, resources, "localthings_operation_state") == "ready"
    assert _read(reg, resources, "localthings_child_lock") is False
    assert _read(reg, resources, "localthings_smart_control") is False
    assert _read(reg, resources, "localthings_safety_shutoff") is True
    assert _read(reg, resources, "meter_power") == pytest.approx(43.8)


def test_only_the_burners_the_device_reports_are_exposed(resources):
    """The unit has three burners; MAX_BURNERS declares six. Slots the device
    never reports must not turn into dead capabilities."""
    reg = registry.resolve(resources)
    caps = reg.capabilities(resources)
    for index in (0, 1, 2):
        assert f"localthings_burner_level.{index}" in caps
        assert f"localthings_burner_state.{index}" in caps
        assert f"localthings_alarm_hot_surface.{index}" in caps
    for index in (3, 4, 5):
        assert f"localthings_burner_level.{index}" not in caps


def test_burner_values_are_read_per_burner(resources):
    reg = registry.resolve(resources)
    assert _read(reg, resources, "localthings_burner_level.0") == "0"
    assert _read(reg, resources, "localthings_burner_state.1") == "ready"
    assert _read(reg, resources, "localthings_alarm_hot_surface.2") is False


def test_sub_capabilities_get_per_instance_titles(resources):
    """Without these every burner row would read identically in the UI."""
    reg = registry.resolve(resources)
    options = reg.capability_options(resources, "ko")
    assert options["localthings_burner_level.0"]["title"] == "1구 화력"
    assert options["localthings_alarm_hot_surface.2"]["title"] == "3구 잔열"
    assert "localthings_burner_level.3" not in options
    assert reg.capability_options(resources, "en")["localthings_burner_state.1"][
        "title"
    ] == "Burner 2 — state"


def test_idle_power_sentinel_is_not_published_as_a_reading(resources):
    """The unit reports -500 W while idle, which is not a measurement."""
    assert (
        resources["/energy/consumption/vs/0"]["x.com.samsung.da.instantaneousPower"]
        == "-500"
    )
    assert _read(registry.resolve(resources), resources, "measure_power") is None


def test_disconnected_probe_reports_nothing_rather_than_zero(resources):
    """Probe temperatures read 0 while disconnected; publishing that would show a
    0 °C meat probe."""
    reg = registry.resolve(resources)
    assert resources["/bluetooth/probe/status/vs/0"]["connectionState"] == "disconnected"
    assert _read(reg, resources, "localthings_probe_connected") is False
    assert _read(reg, resources, "measure_temperature.probe") is None
    assert _read(reg, resources, "measure_battery.probe") is None


def test_heat_controls_are_not_writable(resources):
    """A cooktop must not be remotely ignited by an automation. Only the child
    lock — a lock toggle, not a heat control — may be written."""
    reg = registry.resolve(resources)
    writable = [s.capability for s in reg.specs if s.writable]
    assert writable == ["localthings_child_lock"]


def test_child_lock_write_sends_one_field(resources):
    reg = registry.resolve(resources)
    spec = reg.spec_for("localthings_child_lock")
    assert spec.write(True, resources[spec.href]) == (
        ["cooktop", "status", "vs", "0"], {"childLock": "on"},
    )

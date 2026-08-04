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
    assert _read(reg, resources, "localthings_power") is False
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
        assert f"localthings_pan_detected.{index}" in caps
        assert f"localthings_remaining_minutes.{index}" in caps
    for index in (3, 4, 5):
        assert f"localthings_burner_level.{index}" not in caps
        assert f"localthings_pan_detected.{index}" not in caps
        assert f"localthings_remaining_minutes.{index}" not in caps


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
    """A cooktop must not be remotely ignited by an automation. Only the child lock
    — a lock toggle, not a heat control — and power *off* may be written."""
    reg = registry.resolve(resources)
    writable = [s.capability for s in reg.specs if s.writable]
    assert writable == ["localthings_power", "localthings_child_lock"]


def test_power_off_is_writable_and_power_on_is_refused(resources):
    """The appliance advertises remotePowerOff and no remotePowerOn."""
    reg = registry.resolve(resources)
    spec = reg.spec_for("localthings_power", resources)
    rep = resources[spec.href]
    assert spec.write(False, rep) == (
        ["cooktop", "status", "vs", "0"], {"power": "off"},
    )
    assert spec.write(True, rep) is None
    assert spec.refusal == "error.no_remote_power_on"


def test_the_power_toggle_is_gated_on_the_appliance_saying_it_accepts_off():
    """The gate is supportedFeatureList, so a unit of this family that does not
    advertise remotePowerOff keeps the reading and never grows a dead toggle."""
    without = {
        "/information/vs/0": {
            "x.com.samsung.da.modelNum": "TP1X_DA-KS-COOKTOP-01011|1|2",
        },
        "/cooktop/spec/vs/0": {"supportedFeatureList": ["kitchenService"]},
        "/cooktop/status/vs/0": {"power": "on", "burnerList": []},
    }
    reg = registry.resolve(without)
    caps = reg.capabilities(without)
    assert "localthings_power" not in caps
    assert "localthings_power_state" in caps
    assert _read(reg, without, "localthings_power_state") is True


def test_the_two_power_forms_are_never_both_bound(resources):
    """Both read the same field; binding both would show the value twice."""
    caps = registry.resolve(resources).capabilities(resources)
    assert "localthings_power" in caps
    assert "localthings_power_state" not in caps


def test_a_missing_spec_resource_leaves_no_power_control(resources):
    """No spec resource means no evidence the appliance accepts anything, so the
    gate must fail closed rather than assume the verified unit's feature list."""
    stripped = {k: v for k, v in resources.items() if k != "/cooktop/spec/vs/0"}
    reg = registry.resolve(stripped)
    caps = reg.capabilities(stripped)
    assert "localthings_power" not in caps
    assert "localthings_power_state" in caps


def test_pan_detection_is_ignored_while_the_burner_is_idle(resources):
    """Every burner of the idle hob reports a pan — twice, six days apart — so an
    idle reading is a sentinel and not a measurement."""
    reg = registry.resolve(resources)
    burners = resources["/cooktop/status/vs/0"]["burnerList"]
    assert [b["panDetection"] for b in burners] == [True, True, True]
    assert [b["operationState"] for b in burners] == ["ready", "ready", "ready"]
    for index in (0, 1, 2):
        assert _read(reg, resources, f"localthings_pan_detected.{index}") is None


def test_pan_detection_is_reported_once_the_burner_runs(resources):
    reg = registry.resolve(resources)
    running = json.loads(FIXTURE.read_text())["resources"]
    burners = running["/cooktop/status/vs/0"]["burnerList"]
    burners[1]["operationState"] = "running"
    burners[2]["operationState"] = "running"
    burners[2]["panDetection"] = False
    spec = reg.spec_for("localthings_pan_detected.1")
    assert spec.read(running[spec.href], running) is True
    spec = reg.spec_for("localthings_pan_detected.2")
    assert spec.read(running[spec.href], running) is False


def test_burner_timer_reports_nothing_when_no_timer_is_set(resources):
    reg = registry.resolve(resources)
    assert resources["/cooktop/status/vs/0"]["burnerList"][0]["timer"] == {
        "cookingTime": 0, "operationState": "ready", "remainingTime": 0,
    }
    for index in (0, 1, 2):
        assert _read(reg, resources, f"localthings_remaining_minutes.{index}") is None


def test_burner_timer_is_published_in_minutes(resources):
    """Seconds is an assumption — see _burner_remaining_minutes. This pins the
    conversion so changing it after the observation is a deliberate edit."""
    reg = registry.resolve(resources)
    timed = json.loads(FIXTURE.read_text())["resources"]
    timed["/cooktop/status/vs/0"]["burnerList"][0]["timer"]["remainingTime"] = 600
    timed["/cooktop/status/vs/0"]["burnerList"][1]["timer"]["remainingTime"] = 90
    spec = reg.spec_for("localthings_remaining_minutes.0")
    assert spec.read(timed[spec.href], timed) == 10
    spec = reg.spec_for("localthings_remaining_minutes.1")
    assert spec.read(timed[spec.href], timed) == 2


def test_the_cooktops_idle_alarm_code_is_not_reported_as_an_alarm(resources):
    """CT_E_OFF is this appliance's idle code, not a fault."""
    reg = registry.resolve(resources)
    items = resources["/alarms/vs/0"]["x.com.samsung.da.items"]
    assert items[0]["x.com.samsung.da.code"] == "CT_E_OFF"
    assert _read(reg, resources, "localthings_alarm_code") == "none"


def test_child_lock_write_sends_one_field(resources):
    reg = registry.resolve(resources)
    spec = reg.spec_for("localthings_child_lock")
    assert spec.write(True, resources[spec.href]) == (
        ["cooktop", "status", "vs", "0"], {"childLock": "on"},
    )

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
    assert _read(reg, resources, "localthings_child_lock_state") is False
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


def test_nothing_on_this_appliance_is_writable(resources):
    """Measured with the owner at the cooktop on 2026-08-04: a POST to
    /cooktop/status/vs/0 answers 4.05 Method Not Allowed for `power` and for
    `childLock` alike, with the hob off and again with a burner running, while
    smartControlState reads on and GET works throughout. A POST to the range hood in
    the same minute was accepted, so the transport was not the problem.

    1.0.3 briefly shipped a power-off toggle here, reasoning from
    /cooktop/spec/vs/0's supportedFeatureList — which advertises remotePowerOff and
    remoteChildLock. That list is not a write contract, and the child-lock write it
    leaned on turned out not to work either. A control that always errors is worse
    than a reading, so there are none."""
    reg = registry.resolve(resources)
    assert [s.capability for s in reg.specs if s.writable] == []


def test_the_withdrawn_power_toggle_cannot_come_back_quietly(resources):
    """The capability, its card and the generator policy were removed with it."""
    caps = registry.resolve(resources).capabilities(resources)
    assert "localthings_power_state" in caps, "the reading stays"
    assert "localthings_power" not in caps
    root = Path(__file__).parent.parent
    assert not (root / ".homeycompose/capabilities/localthings_power.json").exists()
    assert not (root / ".homeycompose/flow/actions/set_power.json").exists()
    generator = (root / "scripts/make_flow_cards.py").read_text()
    assert "OFF_ONLY" not in generator


def test_the_feature_list_is_not_treated_as_a_write_contract(resources):
    """It still reads remoteChildLock and remotePowerOff. Nothing may gate a write on
    that again without new evidence — the reopening condition is an appliance that
    answers something other than 4.05."""
    features = resources["/cooktop/spec/vs/0"]["supportedFeatureList"]
    assert features == ["kitchenService", "remoteChildLock", "remotePowerOff"]
    source = (Path(__file__).parent.parent
              / "lib/registry/induction_cooktop.py").read_text()
    assert "supportedFeatureList" not in source.split('"""', 2)[2], \
        "the feature list is referenced outside the docstring — is it gating again?"


def test_pan_detection_reads_no_while_the_burner_is_idle(resources):
    """Every burner of the idle hob reports a pan — three readings now — so an idle
    reading is a sentinel, not a measurement.

    It must be an explicit False rather than None. None means "leave the capability
    alone", which left the owner's burner 2 showing "pan detected" long after the
    cooking ended: the display this gate exists to prevent, reached from the other
    side."""
    reg = registry.resolve(resources)
    burners = resources["/cooktop/status/vs/0"]["burnerList"]
    assert [b["panDetection"] for b in burners] == [True, True, True]
    assert [b["operationState"] for b in burners] == ["ready", "ready", "ready"]
    for index in (0, 1, 2):
        assert _read(reg, resources, f"localthings_pan_detected.{index}") is False


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


def test_burner_timer_reads_zero_when_no_timer_is_set(resources):
    """0, not None: a cancelled timer used to keep showing its last count, because
    None tells Homey to leave the value alone. Reported by the owner."""
    reg = registry.resolve(resources)
    assert resources["/cooktop/status/vs/0"]["burnerList"][0]["timer"] == {
        "cookingTime": 0, "operationState": "ready", "remainingTime": 0,
    }
    for index in (0, 1, 2):
        assert _read(reg, resources, f"localthings_remaining_minutes.{index}") == 0


def test_burner_timer_is_published_in_minutes(resources):
    """Seconds is confirmed on the appliance: the owner set a timer and this read the
    right minutes and counted down with it. Pinned so a later edit is deliberate."""
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



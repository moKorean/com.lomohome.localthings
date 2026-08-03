"""What lands in Homey's timeline, and what cannot.

Homey writes a timeline line itself whenever a **boolean** capability carrying
insight titles changes — that is why power and the absence sensor already appear
there. It cannot do the same for the other two shapes:

  - a **number** with `insights` becomes a chart and produces no line, which is why
    a target-temperature change was invisible even though the capability is logged;
  - a **string** cannot be logged at all. Not one capability of type string in
    Homey's own library sets `insights`.

So booleans are left to Homey, and only the mode and the setpoint are written
explicitly.
"""

import ast
import asyncio
import json
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).parent.parent
CAPS = APP_ROOT / ".homeycompose/capabilities"
FLOW = APP_ROOT / ".homeycompose/flow"
DEVICE = APP_ROOT / "lib/appliance/device.py"


@pytest.fixture(autouse=True)
def _homey_stub():
    """`lib.appliance.device` imports the runtime-provided module at import time."""
    import sys
    import types
    stub = types.ModuleType("homey")
    module = types.ModuleType("homey.device")

    class Device:
        pass

    module.Device = Device
    stub.device = module
    saved = {name: sys.modules.get(name) for name in ("homey", "homey.device")}
    sys.modules.setdefault("homey", stub)
    sys.modules.setdefault("homey.device", module)
    yield
    for name, previous in saved.items():
        if previous is not None:
            sys.modules[name] = previous


def _capability(name):
    return json.loads((CAPS / f"{name}.json").read_text())


@pytest.mark.parametrize("name", [
    "localthings_auto_clean_active",
    "localthings_selfcheck_active",
    "localthings_absence_detect",
])
def test_the_cycle_sensors_reach_the_timeline_natively(name):
    """Boolean plus insight titles is the whole mechanism — no code needed."""
    d = _capability(name)
    assert d["type"] == "boolean", "only booleans produce a timeline line"
    assert d.get("insights") is True, f"{name} is not logged at all"
    for key in ("insightsTitleTrue", "insightsTitleFalse"):
        assert d.get(key), f"{name} has no {key}, so the line has no wording"
        assert set(d[key]) >= {"en", "ko"}, f"{name}.{key} is not translated"


def test_the_two_states_read_as_a_start_and_an_end():
    """A timeline is read as events. "Auto dry" on both transitions says nothing."""
    d = _capability("localthings_auto_clean_active")
    assert d["insightsTitleTrue"]["ko"] != d["insightsTitleFalse"]["ko"]
    assert "시작" in d["insightsTitleTrue"]["ko"]
    assert "종료" in d["insightsTitleFalse"]["ko"]


@pytest.mark.parametrize("card,capability", [
    ("absence_detect_is", "localthings_absence_detect"),
    ("auto_clean_active_is", "localthings_auto_clean_active"),
])
def test_both_are_usable_as_a_flow_condition(card, capability):
    """Asked for directly: can a Flow test these?"""
    d = json.loads((FLOW / "conditions" / f"{card}.json").read_text())
    device = next(a for a in d["args"] if a["type"] == "device")
    assert capability in device["filter"], (
        "the card is offered for appliances that do not have the capability"
    )
    assert "!{{" in d["title"]["en"], (
        "no negative form, so the Flow can only test one direction"
    )


# --- the two Homey cannot express -----------------------------------------


def _device_source():
    return ast.parse(DEVICE.read_text())


def test_only_the_mode_and_the_setpoint_are_written_by_hand():
    """Writing a line for something Homey already logs would double it."""
    from lib.appliance import device as module
    assert set(module.ApplianceDevice._TIMELINE_CAPABILITIES) == {
        "localthings_ac_mode", "target_temperature"
    }


def test_a_boolean_this_app_defines_is_not_in_that_list():
    """Booleans are Homey's job. onoff and the cycle sensors must not be here."""
    from lib.appliance import device as module
    for capability in ("onoff", "localthings_auto_clean_active",
                       "localthings_absence_detect"):
        assert capability not in module.ApplianceDevice._TIMELINE_CAPABILITIES


def test_the_timeline_note_never_interrupts_a_poll():
    """The value is already applied by the time it runs, so a failure to describe
    it must not fail the poll that applied it."""
    function = next(
        node for node in ast.walk(_device_source())
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_note_on_timeline"
    )
    handlers = [n for n in ast.walk(function) if isinstance(n, ast.ExceptHandler)]
    assert any(isinstance(h.type, ast.Name) and h.type.id == "Exception"
               for h in handlers), "an unguarded notification can break polling"


class _Device:
    """Just enough ApplianceDevice to exercise _note_on_timeline."""

    def __init__(self, enabled=True):
        from lib.appliance.device import ApplianceDevice
        self._note = ApplianceDevice._note_on_timeline.__get__(self)
        self._label_value = ApplianceDevice._label_value.__get__(self)
        self._TIMELINE_CAPABILITIES = ApplianceDevice._TIMELINE_CAPABILITIES
        self._language = "ko"
        self.enabled = enabled
        self.written = []
        outer = self

        class _Notifications:
            async def create_notification(self, message):
                outer.written.append(message)

        class _Homey:
            notifications = _Notifications()

        self.homey = _Homey()

    def get_settings(self):
        return {"timeline_changes": self.enabled}

    def get_name(self):
        return "1.안방 에어컨"

    def log(self, *args):
        pass


def test_a_mode_change_is_written_in_words_the_user_recognises():
    device = _Device()
    asyncio.run(device._note("localthings_ac_mode", "Cool", "AIComfort"))
    assert len(device.written) == 1
    line = device.written[0]
    assert "냉방" in line and "AI 쾌적" in line, line
    assert "Cool" not in line and "AIComfort" not in line, (
        "the wire spelling reached the timeline"
    )


def test_a_setpoint_change_names_both_ends():
    device = _Device()
    asyncio.run(device._note("target_temperature", 28, 26.5))
    assert "28" in device.written[0] and "26.5" in device.written[0]


def test_nothing_is_written_when_the_setting_is_off():
    device = _Device(enabled=False)
    asyncio.run(device._note("localthings_ac_mode", "Cool", "AIComfort"))
    assert device.written == []


def test_the_first_reading_after_a_restart_is_not_a_change():
    """Every capability goes from None to its value when the app starts. Those are
    not changes anyone made, and a restart would otherwise fill the timeline."""
    device = _Device()
    asyncio.run(device._note("localthings_ac_mode", None, "Cool"))
    assert device.written == []


def test_a_capability_outside_the_list_writes_nothing():
    device = _Device()
    asyncio.run(device._note("measure_temperature", 20, 21))
    assert device.written == []


def test_the_setting_that_gates_it_exists_and_defaults_off():
    """On a house full of appliances this adds up, so it is opt-in."""
    driver = json.loads(
        (APP_ROOT / "drivers/appliance/driver.compose.json").read_text())
    field = next(
        child for group in driver["settings"] for child in group.get("children", [])
        if child["id"] == "timeline_changes"
    )
    assert field["type"] == "checkbox"
    assert field["value"] is False
    assert set(field["label"]) >= {"en", "ko"}

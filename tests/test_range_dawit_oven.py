"""The DAWIT 3.0 generation's oven half, on a range.

The OS70H30E (TP1X_DA-KS-RANGE-0103X, reference #726) reports its oven only as
the bare-field `/oven/status/vs/0` and `/oven/settings/status/vs/0` the ME80H
microwave uses — no `/oven/vs/0`, `/mode/vs/0`, `/temperatures/vs/0` or
`/doors/vs/0`. It therefore bound the cooktop and nothing of the oven at all:
the state, door, cavity and setpoint were all declared against hrefs this board
does not serve, which is the failure mode `test_no_dead_mappings` exists for and
which no structural check can see on a dump that simply lacks the resource.

175 °F is the trap here. Read straight through it would publish a 79 °C cavity
on an oven that is Ready, which is a sentinel presented as a measurement — the
mistake the range hood shipped once.
"""

import json
from pathlib import Path

import pytest

from lib import registry

REF_FIXTURES = Path(__file__).parent.parent.parent / "localthings-reference" / "tests" / "fixtures"
FIXTURE = "range_os70h30e_device.json"

pytestmark = pytest.mark.skipif(
    not (REF_FIXTURES / FIXTURE).is_file(), reason="reference dump not present"
)


def _resources():
    out: dict = {}

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("href"), str) and isinstance(node.get("rep"), dict):
                out[node["href"]] = node["rep"]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(json.loads((REF_FIXTURES / FIXTURE).read_text()))
    return out


def _reg(resources):
    reg = registry.resolve(resources)
    assert reg is not None and reg.name == "range"
    return reg


def test_the_premise_none_of_the_older_oven_hrefs_are_served():
    resources = _resources()
    for href in ("/oven/vs/0", "/mode/vs/0", "/temperatures/vs/0", "/doors/vs/0",
                 "/operational/state/vs/0"):
        assert href not in resources, href
    assert "/oven/status/vs/0" in resources
    assert "/oven/settings/status/vs/0" in resources


@pytest.mark.parametrize("capability,expected", [
    ("localthings_operation_state", "ready"),
    ("localthings_oven_mode", "NoOperation"),
    ("localthings_child_lock_state", False),
    ("alarm_contact", False),
    ("localthings_remaining_minutes", 0),
    ("localthings_oven_lamp", False),
    ("localthings_smart_control", True),
    ("localthings_beep", True),
    ("localthings_display_time_sync", True),
    ("localthings_energy_saving", True),
])
def test_the_oven_half_reads(capability, expected):
    resources = _resources()
    reg = _reg(resources)
    assert capability in reg.capabilities(resources), capability
    spec = reg.spec_for(capability, resources)
    assert spec.read(resources[spec.href], resources) == expected


def test_the_idle_cavity_is_not_published_as_a_reading():
    """`current` is 175 °F while Ready — Bake's own minimum, not the cavity. The
    setpoint is 0, so both halves of the idle test hold and the reading is
    withheld rather than published as 79.4 °C."""
    resources = _resources()
    status = resources["/oven/status/vs/0"]
    assert status["temperature"] == {"unit": "fahrenheit", "target": 0, "current": 175}
    reg = _reg(resources)
    for capability in ("measure_temperature.cavity", "localthings_target_temperature_readonly"):
        spec = reg.spec_for(capability, resources)
        assert spec.href == "/oven/status/vs/0"
        assert spec.read(status, resources) is None


def test_a_running_cook_does_read():
    """The other half of that rule: once there is a setpoint the floor stops
    applying, so a KeepWarm cook at exactly 175 °F is not silenced."""
    resources = _resources()
    reg = _reg(resources)
    status = dict(resources["/oven/status/vs/0"])
    status["temperature"] = {"unit": "fahrenheit", "target": 175, "current": 175}
    assert reg.spec_for("measure_temperature.cavity", resources).read(status, resources) == 79.4
    assert reg.spec_for(
        "localthings_target_temperature_readonly", resources
    ).read(status, resources) == 79.4


def test_the_cooktop_half_is_a_declared_gap_and_not_an_oversight():
    """This board's burners are a `burnerList` on `/cooktop/status/vs/0`, which
    only the induction registry reads here. They stay unbound for now, and that
    is a decision rather than a miss.

    The induction burner readings cannot simply be pointed at a range. Two of
    the five are induction-specific in a way that would invent readings: the pan
    detector answers False for any burner that is not running — right for a coil
    that can only sense a ferrous load while energised, and a claim about a
    sensor this range does not have — and `hotSurfaceState` is absent here
    entirely. `powerLevel` and `timer` are missing too; the four entries carry
    `burnerNumber` and `operationState` and nothing else.

    So binding them needs its own reading set, not a reused one.
    docs/BACKLOG.md carries it. Delete this test when that lands.
    """
    resources = _resources()
    burners = resources["/cooktop/status/vs/0"]["burnerList"]
    assert [sorted(b) for b in burners] == [["burnerNumber", "operationState"]] * 4
    assert "/cooktop/status/vs/0" in registry.unbound_hrefs(resources, _reg(resources))


def test_nothing_here_is_writable():
    """`availableSettingList` names seven settings, which is a list of features
    and not a write contract. The induction cooktop made that mistake once."""
    resources = _resources()
    reg = _reg(resources)
    for spec in reg.specs:
        if spec.href in ("/oven/status/vs/0", "/oven/settings/status/vs/0"):
            assert spec.write is None, spec.capability

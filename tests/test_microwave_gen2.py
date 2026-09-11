"""The DAWIT 3.0 microwave answers none of the older family's hrefs.

A `TP1X_DA-KS-MICROWAVE-0102X` combi board (reference #433, `OT80H30-/AA0`) has no
`/oven/vs/0`, `/mode/vs/0`, `/temperatures/vs/0`, `/doors/vs/0` or
`/operational/state/vs/0` — the five resources the microwave registry was entirely
built on. It bound four capabilities on its whole dump: an alarm code, two energy
readings and a firmware flag. Nothing that makes it a microwave read anything, and
nothing failed, because a resource that is absent simply does not bind.

Its cavity is one flat `/oven/status/vs/0` and its vent hood is `/hood/status/vs/0`,
both carrying bare nested fields rather than the `x.com.samsung.da.*` flat ones.

The second test is the one that protects the older boards: the two generations are
declared together, so a mistake in the new specs could shadow the old readings on a
unit that has both capabilities bound from different resources.
"""

import json
from pathlib import Path

import pytest

from lib import registry

REF_FIXTURES = Path(__file__).parent.parent.parent / "localthings-reference" / "tests" / "fixtures"

pytestmark = pytest.mark.skipif(
    not REF_FIXTURES.is_dir(), reason="reference checkout not present"
)

GEN2 = "microwave_me80h2160raa_device.json"


def _resources(name: str) -> dict:
    out: dict = {}

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("href"), str) and isinstance(node.get("rep"), dict):
                out[node["href"]] = node["rep"]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads((REF_FIXTURES / name).read_text()))
    return out


def _readings(name: str) -> dict:
    resources = _resources(name)
    reg = registry.resolve(resources)
    assert reg is not None
    return {
        c: reg.spec_for(c, resources).read(
            resources[reg.spec_for(c, resources).href], resources
        )
        for c in reg.capabilities(resources)
    }


def test_the_older_hrefs_really_are_absent():
    """The premise. If a future dump of this board grows them, the two generations
    would both bind and this file's reasoning needs revisiting."""
    resources = _resources(GEN2)
    for href in ("/oven/vs/0", "/mode/vs/0", "/temperatures/vs/0",
                 "/doors/vs/0", "/operational/state/vs/0"):
        assert href not in resources, href
    assert "/oven/status/vs/0" in resources
    assert "/hood/status/vs/0" in resources


def test_the_cavity_and_vent_hood_now_read():
    readings = _readings(GEN2)
    assert readings["localthings_operation_state"] == "ready"
    assert readings["localthings_oven_mode"] == "NoOperation"
    assert readings["localthings_child_lock_state"] is False
    assert readings["alarm_contact"] is False          # door.state == "closed"
    assert readings["localthings_remaining_minutes"] == 0
    assert readings["localthings_alarm_filter"] is False  # greaseFilter alarm off


def test_an_open_door_and_a_dirty_filter_read_the_other_way():
    """Constructed: the dump is idle with everything clean, so the False readings
    above would pass just as well against a reader stuck at False."""
    resources = _resources(GEN2)
    resources["/oven/status/vs/0"] = {
        **resources["/oven/status/vs/0"],
        "door": {"state": "open"},
        "childLock": "on",
        "time": {"remaining": 630},
    }
    resources["/hood/status/vs/0"] = {
        **resources["/hood/status/vs/0"],
        "filter": [{"filterType": "greaseFilter", "alarm": "on"}],
    }
    reg = registry.resolve(resources)
    read = {c: reg.spec_for(c, resources).read(
        resources[reg.spec_for(c, resources).href], resources)
        for c in reg.capabilities(resources)}
    assert read["alarm_contact"] is True
    assert read["localthings_child_lock_state"] is True
    assert read["localthings_alarm_filter"] is True
    # 630 s of cook time is ten and a half minutes, not 630.
    assert read["localthings_remaining_minutes"] == 10


@pytest.mark.parametrize("name", ["microwave_me7500d_device.json", "oven_device.json"])
def test_the_older_generation_is_untouched(name):
    """Both generations are declared on the same registry, so the older boards have
    to keep reading from their own resources."""
    readings = _readings(name)
    assert readings["localthings_operation_state"] == "Ready"
    assert readings["localthings_oven_mode"] == "NoOperation"
    assert readings["localthings_machine_state"] == "Ready"

"""An idle oven's parked cavity value is not a temperature.

The corpus made this look settled in the wrong direction for a while. Four range
dumps — `range_device`, `range_ne63a6511`, `range_nx60t8311ss`, `range_ne8300d` —
all report `current=175`, `desired=0`, `state=Ready`, in Fahrenheit. That was read
here as "the only dump with a live cavity reading", and 79.4 °C was pinned as the
expected value. Four different kitchens do not independently rest at 79.4 °C: 175 °F
is Bake's own minimum, which the firmware parks `current` at while nothing is
cooking. Wall ovens park it at 0 instead. The reference reached the same conclusion
on its own hardware and this rule follows it (2026-09-12).

The two halves of the idle test are each guarding a different real reading, and only
the first two cases below come from dumps. The last two are **constructed** from the
rule rather than measured — no dump in the corpus has an oven that is actually
cooking, which is exactly why the sentinel was mistakable for a reading in the first
place. They are written here so that a future change that collapses the rule to a
bare `value <= floor` comparison fails loudly.
"""

import json
from pathlib import Path

import pytest

from lib import registry

REF_FIXTURES = Path(__file__).parent.parent.parent / "localthings-reference" / "tests" / "fixtures"

pytestmark = pytest.mark.skipif(
    not REF_FIXTURES.is_dir(), reason="reference checkout not present"
)

HREF = "/temperatures/vs/0"
CAVITY = "measure_temperature.cavity"


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


def _cavity_spec(resources: dict, ocf_type: str):
    # The OCF type is supplied the way the app supplies it — read from /oic/d,
    # separately from /device/0 — and each dump is given its own. It is not
    # cosmetic for `range_ne63a6511`, which carries no /information/vs/0 at all:
    # for that board the OCF type is the only signal, and resolving without it
    # returns None. Passing the *right* one per dump also keeps this test honest,
    # since oven and range happen to share these specs and a wrong type would pass.
    reg = registry.resolve(resources, (ocf_type,))
    assert reg is not None, f"{ocf_type} did not resolve"
    spec = next(s for s in reg.specs if s.capability == CAVITY)
    return spec, resources[spec.href]


PARKED_AT_BAKE_MINIMUM = [
    "range_device.json",
    "range_ne63a6511_device.json",
    "range_nx60t8311ss_device.json",
    "range_ne8300d_device.json",
]


@pytest.mark.parametrize("name", PARKED_AT_BAKE_MINIMUM)
def test_idle_range_parks_at_the_floor_and_reads_nothing(name):
    resources = _resources(name)
    item = resources[HREF]["x.com.samsung.da.items"][0]
    # The premise, asserted rather than assumed: if a future dump stops parking at
    # 175/0 this test should fail and be re-derived, not quietly keep passing.
    assert item["x.com.samsung.da.current"] == "175"
    assert item["x.com.samsung.da.desired"] == "0"
    assert str(item["x.com.samsung.da.unit"]).lower().startswith("f")

    spec, rep = _cavity_spec(resources, "oic.d.range")
    assert spec.read(rep, resources) is None


def test_idle_wall_oven_parks_at_zero_and_reads_nothing():
    resources = _resources("oven_device.json")
    item = resources[HREF]["x.com.samsung.da.items"][0]
    assert item["x.com.samsung.da.current"] == "0"
    spec, rep = _cavity_spec(resources, "oic.d.oven")
    assert spec.read(rep, resources) is None


def test_a_cooldown_above_the_floor_still_reads():
    """Constructed, not measured. `desired` is 0 — the oven is off — but the cavity
    is still hot at 300 °F. Suppressing this would lose the whole tail of every
    cool-down, which is why the rule needs the floor as well as the idle test."""
    resources = _resources("range_device.json")
    spec, _ = _cavity_spec(resources, "oic.d.range")
    rep = {"x.com.samsung.da.items": [{
        "x.com.samsung.da.current": "300",
        "x.com.samsung.da.desired": "0",
        "x.com.samsung.da.unit": "Fahrenheit",
    }]}
    assert spec.read(rep, resources) == pytest.approx(148.9, abs=0.1)


def test_a_keepwarm_cook_at_exactly_the_floor_still_reads():
    """Constructed, not measured. 175 °F with a setpoint of 175 is a KeepWarm cook,
    not an idle board — the setpoint is what separates them, and a rule keyed on the
    value alone would silence it."""
    resources = _resources("range_device.json")
    spec, _ = _cavity_spec(resources, "oic.d.range")
    rep = {"x.com.samsung.da.items": [{
        "x.com.samsung.da.current": "175",
        "x.com.samsung.da.desired": "175",
        "x.com.samsung.da.unit": "Fahrenheit",
    }]}
    assert spec.read(rep, resources) == pytest.approx(79.4, abs=0.1)

"""An air purifier's fan speed, on each of the three resources boards use.

A user could switch their purifier on and off but not change its speed. The
mapping explains it exactly: the only fan reading declared was `speedLevel` on
the vendor `/airflow/vs/0`, one of six dumps reports it, and it was read-only.
Five of six boards had no fan control at all and the sixth could not be set.

That field is also the one the reference deliberately avoids for this — measured
on two units in one round it collided Low with Medium on one and sat at 0 on the
other. It is no longer bound.

The three real paths disagree about nearly everything, which is what these tests
pin: `/mode/vs/0` wants a one-element **list** of a self-describing name,
`/wind/strength/vs/0` wants a **bare string** of an opaque numeric code, and
`/airflow/0` wants an **integer**. Sending the wrong shape is accepted and
ignored, which is the failure mode this repository keeps re-learning.
"""

import json
from pathlib import Path

import pytest

from lib import registry
from lib.registry.base import ValueNotAdvertised

REF_FIXTURES = Path(__file__).parent.parent.parent / "localthings-reference" / "tests" / "fixtures"
PRESET = "localthings_purifier_fan_mode"
LEVEL = "localthings_fan_speed_level"

pytestmark = pytest.mark.skipif(
    not REF_FIXTURES.is_dir(), reason="reference checkout not present"
)


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


def _fan_spec(resources):
    reg = registry.resolve(resources)
    assert reg is not None
    for capability in (PRESET, LEVEL):
        spec = reg.spec_for(capability, resources)
        if spec is not None and spec.applies(resources):
            return capability, spec
    return None, None


ALL_PURIFIERS = sorted(p.name for p in REF_FIXTURES.glob("air_purifier*device.json")) \
    if REF_FIXTURES.is_dir() else []


@pytest.mark.parametrize("name", ALL_PURIFIERS)
def test_every_purifier_can_set_its_fan(name):
    resources = _resources(name)
    capability, spec = _fan_spec(resources)
    assert capability is not None, f"{name}: no fan control bound"
    assert spec.writable, f"{name}: {capability} bound read-only"


def test_the_vendor_speedlevel_is_not_bound():
    """It is unreliable, and binding it beside a writable capability would put a
    control on the tile that does nothing."""
    reg = registry.resolve(_resources("air_purifier_device.json"))
    assert not [s for s in reg.specs if s.href == "/airflow/vs/0"]


def test_the_self_describing_board_writes_a_list():
    resources = _resources("air_purifier_tp1x_da_ac_air_device.json")
    capability, spec = _fan_spec(resources)
    assert capability == PRESET and spec.href == "/mode/vs/0"
    rep = resources[spec.href]
    assert spec.read(rep, resources) == "smart"
    path, body = spec.write("windfree", rep)
    assert path == ["mode", "vs", "0"]
    assert body == {"x.com.samsung.da.modes": ["WindFree"]}, "must be a one-element list"


def test_the_coded_board_writes_a_bare_code():
    """`modes` here is a scalar, and the value is an opaque code tied to its name
    only by position in the parallel `modesName` array."""
    resources = _resources("air_purifier_avt_ww_device.json")
    capability, spec = _fan_spec(resources)
    assert capability == PRESET and spec.href == "/wind/strength/vs/0"
    rep = resources[spec.href]
    assert rep["x.com.samsung.da.supportedModes"] == ["87", "89", "90", "91"]
    assert rep["x.com.samsung.da.modesName"] == ["SMART", "MAX", "WINDFREE", "Sleep"]

    assert spec.read(rep, resources) == "smart"
    assert spec.write("windfree", rep)[1] == {"x.com.samsung.da.modes": "90"}
    assert spec.write("sleep", rep)[1] == {"x.com.samsung.da.modes": "91"}


def test_two_boards_spell_the_same_preset_differently():
    """'SMART' and 'Smart' are the same preset and must reach the same value, or
    one picker cannot serve both families."""
    coded = _resources("air_purifier_avt_ww_device.json")
    named = _resources("air_purifier_tp1x_da_ac_air_device.json")
    _, coded_spec = _fan_spec(coded)
    _, named_spec = _fan_spec(named)
    assert coded_spec.read(coded[coded_spec.href], coded) == "smart"
    assert named_spec.read(named[named_spec.href], named) == "smart"


def test_a_preset_the_board_never_advertised_is_refused_by_name():
    """The AVT board has no Turbo. Refusing names the list, so the message can say
    what the appliance actually offers — a silently dropped write cannot."""
    resources = _resources("air_purifier_avt_ww_device.json")
    _, spec = _fan_spec(resources)
    with pytest.raises(ValueNotAdvertised):
        spec.write("turbo", resources[spec.href])


def test_the_numeric_board_writes_an_integer_speed():
    resources = _resources("air_purifier_device.json")
    capability, spec = _fan_spec(resources)
    assert capability == LEVEL and spec.href == "/airflow/0"
    rep = resources[spec.href]
    assert spec.read(rep, resources) == 0
    assert spec.write(3, rep) == (["airflow", "0"], {"speed": 3})

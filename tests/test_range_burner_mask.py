"""A range's lit-burner bitmask is decoded only where it has been verified.

`/cooktopmonitoring/vs/0` carries one bit per knob. Six dumps in the reference's
corpus have the field and exactly one has ever read non-zero: the gas
NX60T8311SS/AA at 31, every burner lit. The five electric NE boards read 0.

That asymmetry is the whole design. A permanent 0 cannot be distinguished from a
field the board does not implement, so decoding it everywhere would publish "no
burner is on" as a measurement drawn from a sentinel — the failure mode this
registry has shipped before. `Fuel_Gas` in `/mode/vs/0`'s options[] is the
discriminator, and an electric owner reporting a non-zero mask is what would lift
the gate.
"""

import json
from pathlib import Path

import pytest

from lib import registry

REF_FIXTURES = Path(__file__).parent.parent.parent / "localthings-reference" / "tests" / "fixtures"

pytestmark = pytest.mark.skipif(
    not REF_FIXTURES.is_dir(), reason="reference checkout not present"
)

MASK_HREF = "/cooktopmonitoring/vs/0"


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


def _burner_readings(resources: dict) -> dict:
    reg = registry.resolve(resources, ("oic.d.range",))
    assert reg is not None
    out = {}
    for capability in reg.capabilities(resources):
        if "burner" not in capability:
            continue
        spec = reg.spec_for(capability, resources)
        out[capability] = spec.read(resources[spec.href], resources)
    return out


ELECTRIC_WITH_THE_FIELD = [
    "range_ne63a6511_device.json",
    "range_ne6516a_device.json",
    "range_ne8300d_device.json",
    "range_no_info_device.json",
    "range_tp1x_da_ks_range_0101x_device.json",
]


def test_the_gas_board_decodes_every_bit():
    resources = _resources("range_nx60t8311ss_device.json")
    # The premise, asserted rather than assumed.
    assert resources[MASK_HREF]["x.com.samsung.da.cooktopMonitoring"] == "31"
    assert "Fuel_Gas" in resources["/mode/vs/0"]["x.com.samsung.da.options"]

    readings = _burner_readings(resources)
    assert readings == {
        "localthings_burner_state.1": "On",
        "localthings_burner_state.2": "On",
        "localthings_burner_state.3": "On",
        "localthings_burner_state.4": "On",
        "localthings_burner_state.5": "On",
        "localthings_burner_any_active": True,
    }


@pytest.mark.parametrize("name", ELECTRIC_WITH_THE_FIELD)
def test_an_electric_board_gets_nothing_rather_than_all_off(name):
    """These boards carry the field and read 0. Binding them would publish five
    'Off' readings and a False that nothing has ever confirmed."""
    resources = _resources(name)
    assert resources[MASK_HREF]["x.com.samsung.da.cooktopMonitoring"] == "0"
    assert not [
        o for o in (resources.get("/mode/vs/0") or {}).get("x.com.samsung.da.options", [])
        if isinstance(o, str) and o.startswith("Fuel")
    ]
    assert _burner_readings(resources) == {}


def test_a_burnerlist_board_keeps_its_own_burners():
    """Precautionary: no dump carries both today. A board that did would otherwise
    list every burner twice, and burnerList wins — it has state, level and a timer
    per burner where the mask has one bit. Spliced rather than found, and labelled
    as such."""
    resources = _resources("range_nx60t8311ss_device.json")
    resources["/cooktop/status/vs/0"] = {
        "x.com.samsung.da.burnerList": [{"x.com.samsung.da.burnerID": "1"}]
    }
    assert _burner_readings(resources) == {}


def test_an_unparsable_mask_binds_nothing():
    resources = _resources("range_nx60t8311ss_device.json")
    resources[MASK_HREF] = {"x.com.samsung.da.cooktopMonitoring": "not a number"}
    assert _burner_readings(resources) == {}

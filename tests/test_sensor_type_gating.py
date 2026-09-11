"""A board is only given the air-quality tiles it actually lists.

`/sensors/vs/0` is one resource carrying a variable items[] array, so binding on
the resource's presence is the wrong question — it gave every purifier the full set
of dust, fine-dust, super-fine-dust and CO2 readings whether or not the board
mentioned them. They then read `None` forever, which means "leave the capability
alone" rather than raising, so nothing failed and nothing looked wrong.

`tests/test_no_dead_mappings.py` cannot catch this one: it asks whether a spec is
blank across *every* dump of a type, and these specs read fine on most boards. The
defect is per-unit, and only a dump listing fewer types than its siblings exposes
it — which is what the reference's #414 report provided.

The two directions both matter, and the second is the one that would bite: the gate
must remove a tile the board never mentions, and must not remove one it does.
"""

import json
from pathlib import Path

import pytest

from lib import registry

REF_FIXTURES = Path(__file__).parent.parent.parent / "localthings-reference" / "tests" / "fixtures"

pytestmark = pytest.mark.skipif(
    not REF_FIXTURES.is_dir(), reason="reference checkout not present"
)

SENSORS = "/sensors/vs/0"
AIR_QUALITY = {
    "localthings_air_quality": "CleanLevel",
    "measure_pm25": "FineDust",
    "localthings_dust_pm10": "Dust",
    "localthings_dust_pm1": "SuperFineDust",
    "measure_co2": "CO2",
}


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


def _listed_types(resources: dict) -> set[str]:
    items = (resources.get(SENSORS) or {}).get("x.com.samsung.da.items") or ()
    return {
        str(item.get("x.com.samsung.da.type"))
        for item in items
        if isinstance(item, dict)
    }


def _bound_air_quality(resources: dict) -> set[str]:
    reg = registry.resolve(resources)
    assert reg is not None
    return {c for c in reg.capabilities(resources) if c in AIR_QUALITY}


def test_a_board_listing_one_sensor_gets_one_tile():
    """The #414 purifier: it lists a CleanLevel and nothing else, and used to be
    given four readings, three of them permanently blank."""
    resources = _resources("air_purifier_avt_ww_touchotn_device.json")
    assert _listed_types(resources) == {"CleanLevel"}
    assert _bound_air_quality(resources) == {"localthings_air_quality"}


def test_the_air_monitor_keeps_its_co2():
    """The one dump in the corpus that does list CO2. If the gate ever drops this,
    it has started removing real readings rather than phantom ones."""
    resources = _resources("air_monitor_device.json")
    assert "CO2" in _listed_types(resources)
    assert "measure_co2" in _bound_air_quality(resources)


# Every dump carrying /sensors/vs/0 that resolves to a type we route.
SENSOR_DUMPS = [
    "air_purifier_avt_ww_device.json",
    "air_purifier_avt_ww_touchotn_device.json",
    "air_purifier_ax100db900edd_device.json",
    "air_purifier_device.json",
    "air_purifier_tp1x_da_ac_air_device.json",
    "air_purifier_vtww_device.json",
    "air_monitor_device.json",
]


@pytest.mark.parametrize("name", SENSOR_DUMPS)
def test_bound_readings_are_exactly_the_listed_ones(name):
    """The invariant behind both cases above, over the whole corpus: a tile exists
    if and only if the board named its sensor type. Odor is listed by most of these
    boards and mapped by none of them, so the comparison is one-directional on
    purpose — every bound capability must be listed, not every listed type bound."""
    resources = _resources(name)
    listed = _listed_types(resources)
    for capability in _bound_air_quality(resources):
        assert AIR_QUALITY[capability] in listed, (
            f"{name}: {capability} is bound but the board never lists "
            f"{AIR_QUALITY[capability]}"
        )

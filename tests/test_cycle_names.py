"""Which wash, dry or dishwasher cycle is running, by name.

The appliance reports it as a hex code, and **the code alone is meaningless**: a
washer and a dryer share twenty codes and not one of them agrees — `01` is Normal
wash or Normal dry, `1d` is Super Speed or Towels. So the code has to be read
together with the course table it belongs to, which the appliance names itself.

The one-body washer-dryer is what makes that concrete rather than theoretical. It
reports both `/st/washercourse/vs/0` (Table_02_Course_01) and `/st/dryercourse/vs/0`
(Table_03_Course_01): two independent units whose codes coincide and whose names do
not. `/course/vs/0` carries a single `Course_01` for the pair, so anything reading
that has to guess which unit it belongs to — and the first draft of this feature
guessed wrong, labelling the machine's dry cycle from the washer catalog. Reading
the self-describing `Table_XX_Course_YY` fields removes the guess.

No washer, dryer or dishwasher exists here, so the reference's dumps are the
hardware: fifteen of them carry `/course/vs/0`. Everything below is asserted
against those.
"""

import json
from pathlib import Path

import pytest

from lib import registry
from lib.registry import courses

REFERENCE = Path(__file__).parent.parent.parent / "localthings-reference"
FIXTURES = REFERENCE / "tests" / "fixtures"

pytestmark = pytest.mark.skipif(
    not FIXTURES.is_dir(), reason="reference checkout not present")

CATALOGS = {
    "localthings_wash_cycle": courses.WASHER_TABLE_02,
    "localthings_dry_cycle": courses.DRYER_TABLE_03,
    "localthings_dish_cycle": courses.DISHWASHER,
}


def _flatten(name):
    out = {}

    def walk(node):
        if isinstance(node, dict):
            if "href" in node and isinstance(node.get("rep"), dict):
                out[node["href"].rstrip("/")] = node["rep"]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads((FIXTURES / name).read_text()))
    return out


def _cycles(name):
    """{capability: code} for whatever cycle capabilities bind on this dump."""
    resources = _flatten(name)
    reg = registry.resolve(resources, ())
    if reg is None:
        return {}
    return {
        spec.capability: spec.read(resources.get(spec.href), resources)
        for spec in reg.specs
        if spec.capability in CATALOGS and spec.applies(resources)
    }


@pytest.mark.parametrize("dump,capability,korean", [
    ("washer_device.json", "localthings_wash_cycle", "에코 40-60"),
    ("washer_wa55a7700av_device.json", "localthings_wash_cycle", "표준세탁"),
    ("dryer_device.json", "localthings_dry_cycle", "면의류"),
    ("dryer_dve50a8600_device.json", "localthings_dry_cycle", "표준건조"),
    ("dishwasher_device.json", "localthings_dish_cycle", "AI 맞춤 세척"),
    ("dishwasher_dw5000c_cloud_device.json", "localthings_dish_cycle", "급속 60분"),
])
def test_the_running_cycle_reads_with_its_own_name(dump, capability, korean):
    code = _cycles(dump)[capability]
    assert code is not None
    assert CATALOGS[capability][code]["ko"] == korean


def test_the_one_body_machine_reads_both_of_its_units():
    """Both report course `01` and they are not the same cycle. This is the case
    that a single `/course/vs/0` reading cannot get right."""
    got = _cycles("washer_dryer_onebody_awm_device.json")
    assert got["localthings_wash_cycle"] == "01"
    assert got["localthings_dry_cycle"] == "01"
    assert courses.WASHER_TABLE_02["01"]["ko"] == "표준세탁"
    assert courses.DRYER_TABLE_03["01"]["ko"] == "표준건조"


def test_an_untranslated_table_shows_nothing_rather_than_a_borrowed_name():
    """FlexWash reports Table_00, which nobody has labelled. Its code A5 exists in
    Table_02 as a different cycle entirely, so falling back to the washer catalog
    would put a confident, wrong name on the tile."""
    assert _cycles("washer_flexwash_device.json") == {}
    resources = _flatten("washer_flexwash_device.json")
    assert resources["/st/washercourse/vs/0"][
        "x.com.samsung.da.st.washerMode"].startswith("Table_00_")


def test_the_two_sources_agree_wherever_both_exist():
    """The self-describing field is preferred over `/course/vs/0`'s bare token, so
    this pins that the preference costs nothing — if they ever disagree on a future
    dump, that is a finding and not a detail."""
    checked = 0
    for path in sorted(FIXTURES.glob("*.json")):
        resources = _flatten(path.name)
        course = resources.get("/course/vs/0")
        if not course:
            continue
        bare = next(
            (o.split("_", 1)[1] for o in course.get("x.com.samsung.da.options") or ()
             if isinstance(o, str) and o.startswith("Course_")), None)
        for href, field in (
            ("/st/washercourse/vs/0", "x.com.samsung.da.st.washerMode"),
            ("/st/dryercourse/vs/0", "x.com.samsung.da.st.dryerMode"),
        ):
            raw = (resources.get(href) or {}).get(field)
            if not isinstance(raw, str) or bare is None:
                continue
            # The one-body is the documented exception: two units, one shared
            # token, so only one of its two can match.
            if path.name.startswith("washer_dryer_onebody"):
                continue
            assert raw.endswith(f"_Course_{bare}"), f"{path.name}: {raw} vs {bare}"
            checked += 1
    assert checked >= 8, f"only {checked} dumps compared"


@pytest.mark.parametrize("capability", sorted(CATALOGS))
def test_every_catalogued_code_is_declared_in_the_manifest(capability):
    """The catalog is what the reader maps through; the manifest is what Homey will
    accept as a value. A code in one and not the other reads as nothing."""
    declared = {
        v["id"] for v in json.loads(
            (Path(__file__).parent.parent / ".homeycompose" / "capabilities"
             / f"{capability}.json").read_text())["values"]
    }
    assert set(CATALOGS[capability]) == declared


def test_the_catalogs_do_not_share_a_meaning():
    """The premise of keying by table. If washer and dryer agreed on every shared
    code, one capability would do and this would be over-built.

    Asserted on the Korean names, because the English ones are not decisive: the
    twenty shared codes disagree nineteen times in English and twenty in Korean.
    The odd one out is `01`, which English calls "Normal" for both while Korean
    distinguishes 표준세탁 from 표준건조 — the same-looking label is a shortcoming of
    the English catalog, not evidence the two tables mean the same thing, and on a
    one-body machine it would put "Normal" on both tiles.
    """
    shared = set(courses.WASHER_TABLE_02) & set(courses.DRYER_TABLE_03)
    assert len(shared) == 20, f"expected 20 shared codes, got {len(shared)}"
    same = [c for c in shared
            if courses.WASHER_TABLE_02[c]["ko"] == courses.DRYER_TABLE_03[c]["ko"]]
    assert not same, f"codes that mean the same on both tables: {same}"

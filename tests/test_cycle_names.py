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
    "localthings_wash_cycle_t00": courses.WASHER_TABLE_00,
    "localthings_dry_cycle": courses.DRYER_TABLE_03,
    "localthings_dry_cycle_t00": courses.DRYER_TABLE_00,
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


def test_a_code_only_the_dryer_catalog_has_is_not_borrowed_for_a_washer():
    """The two families share table ids, so pooling by id alone would name a
    washer's cycle out of a dryer's list.

    The FlexWash used to be this test's live case: it reports
    `Table_00_Course_A5` on its washer resource and no dryer-course resource at
    all, and `a5` existed only in the dryer Table_00 catalog, so it read blank.
    The reference has since named washer Table_00's own `a5`, so that device now
    reads from the right catalog — see the test below. The trap itself is
    unchanged, so it is pinned here on a code the dryer catalog still has alone.
    """
    dry_only = sorted(set(courses.DRYER_TABLE_00) - set(courses.WASHER_TABLE_00))
    assert dry_only, "the two Table_00 catalogs no longer differ — re-derive this test"
    code = "7f"
    assert code in dry_only and courses.DRYER_TABLE_00[code]["en"] == "Time Dry"

    resources = {"/st/washercourse/vs/0": _rep(WASHER_MODE, f"Table_00_Course_{code.upper()}")}
    for capability in ("localthings_wash_cycle_t00", "localthings_dry_cycle_t00"):
        spec = _spec(capability, resources)
        assert not spec.applies(resources), f"{capability} bound to a washer's {code}"


def test_the_flexwash_now_reads_from_the_washer_catalog():
    """It reports Table_00_Course_A5 on the washer resource and carries no dryer
    course resource, so the washer catalog is the right one to read — which only
    became possible when washer Table_00 gained its own a5."""
    resources = _flatten("washer_flexwash_device.json")
    assert resources["/st/washercourse/vs/0"][
        "x.com.samsung.da.st.washerMode"] == "Table_00_Course_A5"
    assert "/st/dryercourse/vs/0" not in resources

    assert _cycles("washer_flexwash_device.json") == {"localthings_wash_cycle_t00": "a5"}


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
            # `AutoLinkCycle_<code>` is a second shape, and not a disagreement.
            # The AWM-US-M64 washer-dryer (reference #784) names its washer side
            # `Table_02_Course_A1` and its dryer side `AutoLinkCycle_A1`: the
            # dryer is running whatever the washer's cycle links to, so the
            # prefix names that linkage rather than a course table. The code
            # still agrees, which is what this test is about; BY_TABLE has no
            # `autolinkcycle` entry, so the dryer simply reads no cycle, which
            # is the right answer for a cycle the board never names.
            if raw.startswith("AutoLinkCycle_"):
                assert raw == f"AutoLinkCycle_{bare}", f"{path.name}: {raw} vs {bare}"
            else:
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

    Asserted on the Korean names, because the English ones are not decisive: `01`
    is "Normal" on both in English while Korean distinguishes 표준세탁 from 표준건조.
    The same-looking label is a shortcoming of the English catalog, not evidence the
    tables agree, and on a one-body machine it would put "Normal" on both tiles.

    The size of the overlap is deliberately not pinned. It was, at twenty, and the
    next upstream sync took it to thirty-nine and failed the test for saying so —
    which is noise: the catalogs grow whenever somebody reports codes, and none of
    that bears on whether the two tables mean different things. Only a floor, so
    that a catalog failing to load cannot pass this by having nothing to compare.
    """
    shared = set(courses.WASHER_TABLE_02) & set(courses.DRYER_TABLE_03)
    assert len(shared) >= 20, f"only {len(shared)} shared codes — did a catalog load?"
    same = [c for c in shared
            if courses.WASHER_TABLE_02[c]["ko"] == courses.DRYER_TABLE_03[c]["ko"]]
    assert not same, f"codes that mean the same on both tables: {same}"


# --- Table_00 -------------------------------------------------------------
#
# No dump on record uses it, so these are synthetic reps built from the field the
# real dumps do carry. The catalog itself is not synthetic: the reference confirmed
# it by having a reporter select each cycle on a WF45R6300 washer and DVE45R6300
# dryer and read back the raw code.


def _spec(capability, resources):
    from lib.registry.appliances import WASHER
    return next(s for s in WASHER.specs if s.capability == capability)


def _rep(field, value):
    return {field: value}


WASHER_MODE = "x.com.samsung.da.st.washerMode"
DRYER_MODE = "x.com.samsung.da.st.dryerMode"


def test_a_table_00_washer_reads_from_the_table_00_catalog():
    resources = {"/st/washercourse/vs/0": _rep(WASHER_MODE, "Table_00_Course_70")}
    spec = _spec("localthings_wash_cycle_t00", resources)
    assert spec.applies(resources)
    assert spec.read(resources[spec.href], resources) == "70"
    assert courses.WASHER_TABLE_00["70"]["ko"] == "강력세탁"


def test_the_same_code_is_a_different_cycle_on_the_two_washer_tables():
    """The reason each table gets its own capability. `70` is Heavy Duty on Table_00
    and Towels on Table_02 — one enum id could not carry both names, and a machine
    labelled from the wrong generation would be confidently wrong."""
    assert courses.WASHER_TABLE_00["70"]["ko"] != courses.WASHER_TABLE_02["70"]["ko"]

    for table, capability, other in (
        ("Table_00", "localthings_wash_cycle_t00", "localthings_wash_cycle"),
        ("Table_02", "localthings_wash_cycle", "localthings_wash_cycle_t00"),
    ):
        resources = {"/st/washercourse/vs/0": _rep(WASHER_MODE, f"{table}_Course_70")}
        mine = _spec(capability, resources)
        theirs = _spec(other, resources)
        assert mine.read(resources[mine.href], resources) == "70"
        assert theirs.read(resources[theirs.href], resources) is None, (
            f"{other} claimed a {table} cycle")


def test_an_unconfirmed_table_still_reads_nothing():
    """Table_00 being named does not mean every table is. A board reporting one
    nobody has confirmed must stay blank rather than fall back to a neighbour."""
    resources = {"/st/washercourse/vs/0": _rep(WASHER_MODE, "Table_99_Course_01")}
    for capability in ("localthings_wash_cycle", "localthings_wash_cycle_t00"):
        spec = _spec(capability, resources)
        assert not spec.applies(resources)

"""Washes remaining before the appliance asks for a drum clean.

Two counters in `/course/vs/0`'s options[]: `DrumCleanProposal_<n>` is the
recommended interval and `WashingTimes_<n>` the count since the last clean. The
difference is the figure the appliance's own app shows — the reference verified
40 - 3 == 37 against a live app screenshot, and `washer_device.json` is that dump.

Present on twelve dumps spanning washers, dryers, a dishwasher and air dressers,
which is why it binds on all four families rather than the one it was reported
against. No such appliance exists here, so those dumps are the hardware.
"""

import json
from pathlib import Path

import pytest

from lib import registry
from lib.registry import appliances

REFERENCE = Path(__file__).parent.parent.parent / "localthings-reference"
FIXTURES = REFERENCE / "tests" / "fixtures"
CAPABILITY = "localthings_drum_clean_remaining"

pytestmark = pytest.mark.skipif(
    not FIXTURES.is_dir(), reason="reference checkout not present")


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


def _read(name):
    resources = _flatten(name)
    reg = registry.resolve(resources, ())
    spec = reg.spec_for(CAPABILITY, resources)
    if spec is None or not spec.applies(resources):
        return None
    return spec.read(resources[spec.href], resources)


@pytest.mark.parametrize("dump,expected", [
    # The reference's own verified case: DrumCleanProposal_40, WashingTimes_3.
    ("washer_device.json", 37),
    ("dishwasher_device.json", 2),
    ("washer_wa8000t_device.json", 1),
    # 25 of 25 washes done — due now, not a negative and not None.
    ("dryer_tp1_21_drum_clean_device.json", 0),
])
def test_the_remaining_count_is_the_difference(dump, expected):
    assert _read(dump) == expected


def test_an_overdue_appliance_reads_zero_rather_than_a_negative():
    """The air dresser is why this is clamped: 58 washes against a 30-cycle
    interval. "Overdue by 28" and "due now" are the same instruction, and a
    negative count of things remaining reads as a bug rather than as urgency."""
    resources = _flatten("air_dresser_device.json")
    options = resources["/course/vs/0"]["x.com.samsung.da.options"]
    assert "WashingTimes_58" in options
    assert "DrumCleanProposal_30" in options
    assert _read("air_dresser_device.json") == 0


def test_it_binds_on_every_family_whose_dumps_carry_it():
    """Bound from the tokens rather than from the appliance type, so a family
    nobody thought to wire in is not silently left out — which is exactly what the
    reference had to fix for dishwashers."""
    families = set()
    for path in sorted(FIXTURES.glob("*.json")):
        resources = _flatten(path.name)
        if "/course/vs/0" not in resources:
            continue
        reg = registry.resolve(resources, ())
        if reg is None:
            continue
        spec = reg.spec_for(CAPABILITY, resources)
        if spec is not None and spec.applies(resources):
            families.add(reg.name)
    assert families == {"washer", "dryer", "dishwasher", "air_dresser"}, families


def test_a_board_missing_either_counter_reads_nothing():
    """One counter alone says nothing: an interval with no count, or a count with
    no interval, cannot be subtracted into anything meaningful."""
    for options in (["DrumCleanProposal_40"], ["WashingTimes_3"], [], ["Course_1C"]):
        rep = {"x.com.samsung.da.options": options}
        assert appliances._read_drum_clean_remaining(rep, None) is None


def test_no_capability_reads_the_clean_log():
    """The reference bound `DrumCleanLog_` and then dropped it (#398): a live dump
    showed its newest entry moving every 30-90 seconds on its own, long after any
    cycle had finished. The dumps do carry the field, and one of them holds ten
    plausible-looking timestamps, so it reads as usable — this asserts no spec has
    been wired to it since.

    Checked against the specs rather than the source text, because the source is
    allowed to discuss the field; an earlier version of this test grepped for the
    token and failed on its own explanatory comment.
    """
    from lib.registry.appliances import AIR_DRESSER, DISHWASHER, DRYER, WASHER

    log_dumps = [
        name for name in ("washer_device.json", "dishwasher_device.json")
        if any("DrumCleanLog_" in o
               for o in _flatten(name)["/course/vs/0"]["x.com.samsung.da.options"])
    ]
    assert log_dumps, "no dump carries DrumCleanLog_ — has the corpus changed?"

    for reg in (WASHER, DRYER, DISHWASHER, AIR_DRESSER):
        for name in ("washer_device.json", "dishwasher_device.json"):
            resources = _flatten(name)
            for spec in reg.specs:
                if not spec.applies(resources):
                    continue
                value = spec.read(resources.get(spec.href), resources)
                assert not (isinstance(value, str) and value.count("-") >= 2
                            and "T" in value), (
                    f"{spec.capability} looks like it is reading a clean-log "
                    f"timestamp: {value!r}"
                )

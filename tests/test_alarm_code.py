"""What counts as an alarm, and why one slot must not hide another.

Both defects here were recorded in docs/BACKLOG.md as unfixed and were found by a
user report, not by this suite — the suite could not see them because it never ran
the reader over the reference corpus.

1. **`_OFF` sentinels read as faults.** Samsung marks a slot idle by suffixing the
   family name with `_OFF`, and the reader knew two of those spellings by hand. Of
   49 dumps that bind this capability, 18 reported an alarm and 13 of those were
   sentinels: `OV_E_OFF` on every oven, range and microwave dump, plus
   `AC_V_0002_OFF` and `FilterAlarm_OFF`. Our own units escaped only because they
   also set `state: Deleted`; boards that send no state did not.

2. **Unrelated slots hid each other.** Only the first active code was reported, so
   what the tile showed depended on slots with nothing to do with each other.

The suffix rule is safe because of the bare `FilterAlarm` dumps: same family, no
suffix, a genuine alarm. The suffix is the discriminator, not the family name.
"""

import json
from pathlib import Path

import pytest

from lib import registry
from lib.registry import shared

REFERENCE = Path(__file__).parent.parent.parent / "localthings-reference"
FIXTURES = REFERENCE / "tests" / "fixtures"
CAPABILITY = "localthings_alarm_code"


def _items(*entries):
    return {"x.com.samsung.da.items": [
        {"x.com.samsung.da.code": code, "x.com.samsung.da.state": state}
        for code, state in entries
    ]}


@pytest.mark.parametrize("code", [
    "OV_E_OFF", "AC_V_0002_OFF", "FilterAlarm_OFF", "ErrorCode_OFF",
    "CT_E_OFF", "DA_SAC_M_OFF", "SomeFamilyNobodyHasSeen_OFF",
])
def test_an_off_sentinel_is_not_an_alarm_whatever_family_it_names(code):
    """Keyed on the suffix, so a family this app has never seen is covered too --
    which is the point, since the failure was a hardcoded list of two."""
    assert shared.read_active_alarm(_items((code, "Created")), None) == "none"


def test_a_bare_family_name_is_still_an_alarm():
    """The discriminator. Four dumps report `FilterAlarm` with no suffix and mean
    it, so suppressing the family rather than the suffix would have hidden a real
    alarm on every one of them."""
    assert shared.read_active_alarm(_items(("FilterAlarm", "Created")), None) == "FilterAlarm"


def test_the_running_state_code_is_not_reported_as_a_fault():
    """The user-visible bug. `DA_SAC_M_<n>` tracks whether the unit is running --
    110 of 110 samples `_OFF` while off, 58 of 58 a number while on -- and it has
    its own capability. Reported here it made a healthy running air conditioner
    look like it was alarming, which is exactly what got reported."""
    assert shared.read_active_alarm(_items(("DA_SAC_M_0004", "Created")), None) == "none"


def test_one_slot_cannot_hide_another():
    """Defect 2. The dishwasher dump is the live case: it reported SNSF_Reached and
    said nothing about its open door until this changed."""
    got = shared.read_active_alarm(
        _items(("SNSF_Reached", "Created"), ("DoorA_Opened", "Created")), None)
    assert got == "SNSF_Reached, DoorA_Opened"


def test_a_cleared_entry_is_still_ignored():
    """The array keeps cleared entries, which is why items[0] was never right."""
    got = _items(("FilterAlarm", "Deleted"), ("DoorA_Opened", "Created"))
    assert shared.read_active_alarm(got, None) == "DoorA_Opened"


def test_a_duplicate_code_is_reported_once():
    """Two slots naming the same fault is one fault, not a repeated string."""
    got = _items(("DoorA_Opened", "Created"), ("DoorA_Opened", "Created"))
    assert shared.read_active_alarm(got, None) == "DoorA_Opened"


def test_a_resource_that_reports_no_items_leaves_the_capability_alone():
    """None means "do not touch", which is not the same as "no alarm"."""
    assert shared.read_active_alarm({}, None) is None
    assert shared.read_active_alarm(_items(), None) == "none"


@pytest.mark.skipif(not FIXTURES.is_dir(), reason="reference checkout not present")
def test_no_dump_reports_a_sentinel_as_an_alarm():
    """The regression the backlog asked for, run over the whole corpus rather than
    over the families somebody thought to check.

    Asserts the shape of what survives, not a count: a growing corpus should not
    fail this, but a sentinel or a state code reappearing must.
    """
    def flatten(path):
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

        walk(json.loads(path.read_text()))
        return out

    reported, bound = {}, 0
    for path in sorted(FIXTURES.glob("*.json")):
        resources = flatten(path)
        if "/alarms/vs/0" not in resources:
            continue
        reg = registry.resolve(resources, ())
        if reg is None:
            continue
        spec = reg.spec_for(CAPABILITY, resources)
        if spec is None or not spec.applies(resources):
            continue
        bound += 1
        value = spec.read(resources[spec.href], resources)
        if value not in (None, "none"):
            reported[path.name] = value

    assert bound >= 40, f"only {bound} dumps bound the capability — corpus problem?"
    for name, value in reported.items():
        for code in (c.strip() for c in value.split(",")):
            assert not code.upper().endswith("_OFF"), f"{name}: sentinel {code}"
            assert not code.startswith("DA_SAC_M"), f"{name}: state code {code}"
    # And the genuine ones are still there, so this did not pass by suppressing
    # everything.
    assert sum("FilterAlarm" in v for v in reported.values()) >= 4, reported

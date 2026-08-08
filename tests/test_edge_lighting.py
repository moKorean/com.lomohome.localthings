"""The edge light's brightness and colour, and the write that proves them.

`/edgelighting/vs/0` was bound for its `status` flag only, so four air conditioners
reported a light that was on or off and nothing about how it was lit — while the
same resource carried a live `mode` and `colorOption` with the appliance's own
supported lists beside them.

Both writes are **measured, not inferred from those lists**. A supported list is
what to try, never what will work: the induction cooktop advertises three remote
features and answers 4.05 to all of them, which is how 1.0.3 shipped a control that
failed on the owner's first attempt. So, on 2026-08-08, on the hardware here:

    손님방  mode Smart -> Low      accepted, read back Low
    손님방  colour 3000K -> 6500K  accepted, read back 3000K, then 6500K at +25s
    거실    colour 4000K -> 6500K  accepted, read back 6500K immediately

Every original value was restored afterwards, and the unit chosen for the first two
had its light off, so nothing in the house changed while the contract was settled.

The colour line is the one worth keeping. Its write echoed `result: true` and the
immediate read-back still showed the old value — the appliance took it, and said so,
and had not applied it yet. An immediate read-back is therefore not a verdict on
this field: believing the echo and believing the first read give opposite wrong
answers about the same working write.

Two boards would have made this cheaper still: 손님방 reports the colour at 3000K
where the other three sit at 4000K, so the field was known to move per-unit before
anything was written at all.
"""

import json
from pathlib import Path

import pytest

from lib.registry.airconditioner import REGISTRY

FIXTURE = (
    Path(__file__).parent / "fixtures" / "airconditioner_TP1X_DA-AC-CAC-01001.json"
)
HREF = "/edgelighting/vs/0"


@pytest.fixture(scope="module")
def resources():
    return json.loads(FIXTURE.read_text())["resources"]


def spec(capability):
    return next(s for s in REGISTRY.specs if s.capability == capability)


@pytest.mark.parametrize("capability,expected", [
    ("localthings_edge_light_mode", "Smart"),
    ("localthings_edge_light_color", "4000K"),
])
def test_the_dump_s_values_are_read(resources, capability, expected):
    assert spec(capability).read(resources[HREF], resources) == expected


@pytest.mark.parametrize("capability,value,field", [
    ("localthings_edge_light_mode", "Low", "mode"),
    ("localthings_edge_light_color", "6500K", "colorOption"),
])
def test_the_write_goes_where_the_measurement_says(resources, capability, value, field):
    path, body = spec(capability).write(value, resources[HREF])
    assert path == ["edgelighting", "vs", "0"]
    assert body == {field: value}


@pytest.mark.parametrize("capability,value", [
    ("localthings_edge_light_mode", "Medium"),
    ("localthings_edge_light_color", "2700K"),
])
def test_a_value_this_board_does_not_list_is_refused(resources, capability, value):
    """Refusing here surfaces as an error the user can see. Sending it instead
    would be accepted and dropped, which is the failure that looks like a stuck
    tile."""
    assert spec(capability).write(value, resources[HREF]) is None


def test_each_field_reads_its_own_supported_list():
    """The two lists are ordered differently — modeSupportedList is
    Smart/High/Low, colorSupportedList is 3000K/4000K/6500K — and neither is the
    vendor-prefixed supportedModes the rest of this registry uses. Crossing them
    would gate each field on the other's vocabulary and refuse every write."""
    rep = {
        "mode": "Smart",
        "colorOption": "4000K",
        "modeSupportedList": ["Smart"],
        "colorSupportedList": ["4000K"],
    }
    assert spec("localthings_edge_light_mode").write("Low", rep) is None
    assert spec("localthings_edge_light_color").write("6500K", rep) is None
    assert spec("localthings_edge_light_mode").write("Smart", rep) is not None
    assert spec("localthings_edge_light_color").write("4000K", rep) is not None


def test_a_board_that_lists_nothing_is_not_blocked():
    """Absent list means unknown, not empty: the static tuple is still checked, so
    a board that reports the field without advertising its options is not locked
    out of a value this app knows the family has."""
    rep = {"mode": "Smart", "colorOption": "4000K"}
    assert spec("localthings_edge_light_mode").write("High", rep) is not None

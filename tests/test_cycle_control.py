"""Starting, pausing and stopping a cycle.

A user asked whether a dryer program could be started from a Flow (2026-08-25).
It could not: `/operational/state/vs/0` was bound four times and every one of them
read only. The reference has driven this resource's writes all along —
`OPERATIONAL_STATE` posts `x.com.samsung.da.state` = Run / Pause / Ready, and its
`STOP_BUTTON` is shared with the oven family — so the payload is not a guess.

**No appliance here runs a cycle.** No washer, dryer, dishwasher, air dresser,
oven or microwave, which means nothing in this file is a read-back off hardware:
it pins the mapping against the reference's committed dumps and against the
reference's own payloads, and that is all it can do. The induction cooktop is the
standing reminder of the difference — `tests/test_induction_cooktop.py` — so what
these tests are really for is making sure the *shape* stays what the reference
verified, and that the oven family's narrower surface does not quietly widen.

The split is the reference's, reproduced rather than smoothed over:

  washer, dryer, dishwasher, air dresser   start, pause and stop
  oven, range, microwave                   stop alone
"""

import json
from pathlib import Path

import pytest

from lib import registry
from lib.registry import shared

REFERENCE = Path(__file__).parent.parent.parent / "localthings-reference"
FIXTURES = REFERENCE / "tests" / "fixtures"
CAPABILITY = "localthings_cycle_control"
HREF = "/operational/state/vs/0"

FULL_CONTROL = {"washer", "dryer", "dishwasher", "air_dresser"}
STOP_ONLY = {"oven", "range", "microwave"}

# Only the dump-driven tests below need the reference checkout. The mapping tests
# do not, and marking the whole module would have hidden them on a machine without
# it — which is where a wrong payload is most likely to be introduced.
needs_reference = pytest.mark.skipif(
    not FIXTURES.is_dir(), reason="reference checkout not present")


# --- the mapping, with no fixtures involved --------------------------------

@pytest.mark.parametrize("state,expected", [
    # Every spelling the reference's _SAMSUNG_STATE_TO_OCF calls active.
    ("Run", "start"),
    ("Running", "start"),
    ("Pause", "pause"),
    ("Paused", "pause"),
    ("Ready", "stop"),
    ("End", "stop"),
    ("Stop", "stop"),
])
def test_the_vendor_state_reads_as_the_value_that_would_restore_it(state, expected):
    assert shared._read_cycle_control({shared.FIELD_STATE: state}, {}) == expected


def test_an_unknown_state_reads_as_stopped_rather_than_as_nothing():
    """None would mean "leave the capability alone", which on a picker means it
    keeps showing whatever it held last — a machine reported as running long after
    it stopped. A state this table has not seen is still not a running cycle."""
    assert shared._read_cycle_control({shared.FIELD_STATE: "Weighing"}, {}) == "stop"


def test_a_finished_cycle_reads_stopped_even_while_the_state_says_run():
    """The firmware quirk `_cycle_active` already guards: `state` stays Run after
    `progress` reaches Finish. Without this, a finished load would sit at 'Start'
    and a Flow asking "is it still running" would never get its answer."""
    rep = {shared.FIELD_STATE: "Run", "x.com.samsung.da.progress": "Finish"}
    assert shared._read_cycle_control(rep, {}) == "stop"


def test_a_resource_with_no_state_field_reads_nothing():
    assert shared._read_cycle_control({}, {}) is None
    assert shared._read_cycle_control({shared.FIELD_STATE: ""}, {}) is None


@pytest.mark.parametrize("value,state", [
    ("start", "Run"),
    ("pause", "Pause"),
    # Ready, not Stop. Ready is what the reference posts; `Stop` appears in its
    # table only as a state some boards report back.
    ("stop", "Ready"),
])
def test_each_control_posts_the_reference_payload(value, state):
    path, body = shared._write_cycle_control(value, {})
    assert path == ["operational", "state", "vs", "0"]
    assert body == {shared.FIELD_STATE: state}


def test_a_value_this_app_never_declared_is_refused_rather_than_sent():
    """None reaches the write path as "this appliance does not support X". Sending
    an invented state instead would be answered with an acknowledgement that means
    nothing — these appliances accept writes they will not honour."""
    assert shared._write_cycle_control("resume", {}) is None


def test_the_oven_family_writer_sends_stop_and_nothing_else():
    """The reference gives ovens, ranges and microwaves `STOP_BUTTON` alone. That
    is the whole of the evidence for this family, so start and pause are refused by
    name rather than sent on the theory that the resource is the same one."""
    assert shared._write_cycle_stop_only("stop", {}) == (
        ["operational", "state", "vs", "0"], {shared.FIELD_STATE: "Ready"})
    assert shared._write_cycle_stop_only("start", {}) is None
    assert shared._write_cycle_stop_only("pause", {}) is None


# --- what each type actually binds, against the reference's dumps ----------

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


def _bound():
    """{type: writer} for every type whose dumps bind the capability."""
    found = {}
    for path in sorted(FIXTURES.glob("*.json")):
        resources = _flatten(path.name)
        if HREF not in resources:
            continue
        reg = registry.resolve(resources, ())
        if reg is None:
            continue
        spec = reg.spec_for(CAPABILITY, resources)
        if spec is not None and spec.applies(resources):
            found[reg.name] = spec.write
    return found


@needs_reference
def test_it_binds_on_exactly_the_types_the_reference_gives_it():
    """Driven by the resource the dump reports, so a family nobody thought to wire
    in is not silently left out — the mistake the reference had to fix for
    dishwashers on the drum-clean counter."""
    assert set(_bound()) == FULL_CONTROL | STOP_ONLY, sorted(_bound())


@needs_reference
def test_the_laundry_family_can_start_and_the_oven_family_cannot():
    """The one invariant worth holding onto: this is where a later edit that
    "tidied up" the two writers into one would show itself."""
    bound = _bound()
    for name in FULL_CONTROL:
        assert bound[name]("start", {}) is not None, name
    for name in STOP_ONLY:
        assert bound[name]("start", {}) is None, name
        assert bound[name]("stop", {}) is not None, name


@needs_reference
def test_every_dump_that_binds_it_reads_a_value():
    """The blank-mapping check in general form, stated here too because this
    capability is a picker: a blank picker offers three positions and shows none of
    them, which looks like a broken device rather than a missing reading."""
    for path in sorted(FIXTURES.glob("*.json")):
        resources = _flatten(path.name)
        if HREF not in resources:
            continue
        reg = registry.resolve(resources, ())
        if reg is None:
            continue
        spec = reg.spec_for(CAPABILITY, resources)
        if spec is None or not spec.applies(resources):
            continue
        value = spec.read(resources[HREF], resources)
        assert value in {"start", "pause", "stop"}, (path.name, value)


def test_the_capability_declares_the_three_values_the_writers_send():
    """The manifest and the writers have to agree: a picker position with no
    payload behind it is a control that fails when used."""
    definition = json.loads(
        (Path(__file__).parent.parent
         / ".homeycompose/capabilities/localthings_cycle_control.json").read_text())
    assert [entry["id"] for entry in definition["values"]] == ["start", "pause", "stop"]
    for entry in definition["values"]:
        assert shared._write_cycle_control(entry["id"], {}) is not None

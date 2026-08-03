"""The refrigerator, pinned against three real TP2X_REF_21K units.

Three units of the same model, which is what makes this testable rather than
guessable:

  convertible_cooler   — a switchable ("변온") cabinet in use as a fridge
  convertible_freezer  — the same model in use as a freezer
  fridge_only          — a variant with no switchable compartment at all

The pair in opposite modes decides two questions that one dump alone leaves
ambiguous. It shows that 253 in a compartment's `desired` marks that compartment as
idle rather than encoding a temperature, since the unit actually freezing reports
-20 there directly. And it shows which token in /mode/vs/0's `modes` tracks the
user's selection, since only the MULTIROOM_ member differs between them.

The fridge-only variant is the guard against phantom capabilities: it reports one
compartment and no rapid-freeze field, and the registry offered both before these
tests existed.
"""

import json
from pathlib import Path

import pytest

from lib import registry
from lib.registry import appliances

FIXTURES = Path(__file__).parent / "fixtures"
COOLER = "refrigerator_TP2X_REF_21K_convertible_cooler"
FREEZER = "refrigerator_TP2X_REF_21K_convertible_freezer"
FRIDGE_ONLY = "refrigerator_TP2X_REF_21K_fridge_only"
ALL = (COOLER, FREEZER, FRIDGE_ONLY)


def load(stem: str) -> dict:
    return json.loads((FIXTURES / f"{stem}.json").read_text())


@pytest.fixture(params=ALL)
def any_unit(request) -> dict:
    return load(request.param)


def _bound(resources: dict) -> dict:
    reg = registry.resolve(resources)
    return {
        spec.capability: spec.read(resources.get(spec.href) or {}, resources)
        for spec in reg.specs
        if spec.applies(resources)
    }


# --- routing ---------------------------------------------------------------


def test_every_unit_routes_to_the_refrigerator(any_unit):
    assert registry.resolve(any_unit) is appliances.REFRIGERATOR


def test_all_three_are_the_same_model():
    """If they were not, the comparisons below would prove nothing."""
    models = {
        load(stem)["/information/vs/0"]["x.com.samsung.da.modelNum"].split("|")[0]
        for stem in ALL
    }
    assert models == {"TP2X_REF_21K"}, models


# --- no capability may be permanently blank -------------------------------


def test_no_unit_is_offered_a_capability_it_cannot_fill(any_unit):
    """The failure mode this whole file exists for: a bound capability that reads
    None looks, to the user, exactly like a broken app."""
    blank = [name for name, value in _bound(any_unit).items() if value is None]
    assert not blank, f"offered but unreadable: {blank}"


# --- the 253 sentinel ------------------------------------------------------


def test_the_idle_compartment_is_the_one_holding_253():
    """253 is in the freezer on the cooler-mode unit and in the fridge on the
    freezer-mode unit — always the compartment not in use."""
    def desired(stem, compartment):
        rep = load(stem)["/temperatures/vs/0"]
        return appliances._fridge_item(rep, compartment)["x.com.samsung.da.desired"]

    assert desired(COOLER, "Freezer") == "253"
    assert desired(COOLER, "Fridge") == "2"
    assert desired(FREEZER, "Fridge") == "253"
    assert desired(FREEZER, "Freezer") == "-20"


def test_253_is_not_an_encoding_of_minus_twenty():
    """It is tempting to read 253 as 253 K = -20 °C, and that reading is wrong: the
    unit that really is at -20 reports -20. Decoding it would have put a plausible
    temperature on an idle compartment."""
    rep = load(FREEZER)["/temperatures/vs/0"]
    freezer = appliances._fridge_item(rep, "Freezer")
    assert freezer["x.com.samsung.da.desired"] == "-20"
    assert freezer["x.com.samsung.da.current"] == "-20"


def test_the_idle_compartment_gets_no_thermometer_and_no_setpoint():
    """Both compartments report the same `current`, because there is one physical
    compartment. Binding both would show one sensor twice."""
    cooler = _bound(load(COOLER))
    assert "measure_temperature.fridge" in cooler
    assert "target_temperature.fridge" in cooler
    assert "measure_temperature.freezer" not in cooler
    assert "target_temperature.freezer" not in cooler

    freezer = _bound(load(FREEZER))
    assert "measure_temperature.freezer" in freezer
    assert "target_temperature.freezer" in freezer
    assert "measure_temperature.fridge" not in freezer
    assert "target_temperature.fridge" not in freezer


def test_the_active_compartment_reports_the_cabinet_temperature():
    assert _bound(load(COOLER))["measure_temperature.fridge"] == 2.0
    assert _bound(load(FREEZER))["measure_temperature.freezer"] == -20.0


# --- convertible compartment mode -----------------------------------------


def test_the_convertible_mode_follows_the_multiroom_token():
    assert _bound(load(COOLER))["localthings_convertible_mode"] == "Cooler"
    assert _bound(load(FREEZER))["localthings_convertible_mode"] == "Freezer"


def test_only_the_multiroom_token_differs_between_the_two_modes():
    """The rest of `modes` is orthogonal flags, which is why position is not a safe
    way to pick the one that matters."""
    modes = {
        stem: load(stem)["/mode/vs/0"]["x.com.samsung.da.modes"]
        for stem in (COOLER, FREEZER)
    }
    differing = set(modes[COOLER]) ^ set(modes[FREEZER])
    assert differing == {"MULTIROOM_COOLER", "MULTIROOM_FREEZER"}, differing


def test_an_unseen_multiroom_value_still_reads_through():
    """The appliance also offers a kimchi setting whose token has not been seen. The
    capability is a free-form string, so an unknown token can be shown as itself
    rather than dropped — the owner confirms kimchi is a real third position."""
    rep = {"x.com.samsung.da.modes": ["CVN_KIMCHI_STORAGE", "MULTIROOM_KIMCHI"]}
    assert appliances._read_convertible_mode(rep, {}) == "Kimchi"


def test_the_fridge_only_variant_has_no_convertible_mode():
    assert "localthings_convertible_mode" not in _bound(load(FRIDGE_ONLY))
    assert "x.com.samsung.da.modes" not in load(FRIDGE_ONLY)["/mode/vs/0"]



def test_the_convertible_mode_is_read_only():
    """1.0.1 made this settable and 1.0.2 took it back out: the owner reports that
    switching fridge/freezer fails from Samsung's own app too, so these units do not
    accept the change remotely at all.

    The payload was not the problem — writing each unit's current mode back was
    accepted and preserved the other flags in `x.com.samsung.da.modes`. Shipping a
    control that the appliance ignores is worse than shipping none, so this stays
    read-only until an appliance is found that honours it. docs/BACKLOG.md has the
    detail; do not re-add a writer from the reference's flex-zone capability without
    new evidence.
    """
    spec = appliances.REFRIGERATOR.spec_for("localthings_convertible_mode")
    assert not spec.writable
    assert not hasattr(appliances, "_write_convertible_mode")


def test_the_capability_is_not_offered_as_settable():
    """The Flow generator emits an action card for every setable capability, so a
    stale `setable` here would put a card in front of users that cannot work."""
    definition = json.loads(
        (Path(__file__).parent.parent / ".homeycompose" / "capabilities"
         / "localthings_convertible_mode.json").read_text(encoding="utf-8"))
    assert definition["setable"] is False
    assert definition["type"] == "string"
    generated = Path(__file__).parent.parent / ".homeycompose" / "flow" / "actions"
    assert not (generated / "set_convertible_mode.json").exists()




# --- fridge-only variant --------------------------------------------------


def test_the_fridge_only_variant_gets_no_freezer_thermometer():
    """It lists one compartment; an ungated spec gave it a second, always blank."""
    bound = _bound(load(FRIDGE_ONLY))
    assert bound["measure_temperature.fridge"] == 2.0
    assert "measure_temperature.freezer" not in bound
    items = load(FRIDGE_ONLY)["/temperatures/vs/0"]["x.com.samsung.da.items"]
    assert [i["x.com.samsung.da.description"] for i in items] == ["Fridge"]


def test_rapid_freeze_is_only_offered_where_the_field_exists():
    bound = _bound(load(FRIDGE_ONLY))
    assert "localthings_rapid_fridge" in bound
    assert "localthings_rapid_freeze" not in bound
    assert "x.com.samsung.da.rapidFreezing" not in load(FRIDGE_ONLY)["/refrigeration/vs/0"]


def test_the_convertible_units_have_no_refrigeration_resource_at_all():
    for stem in (COOLER, FREEZER):
        resources = load(stem)
        assert "/refrigeration/vs/0" not in resources
        bound = _bound(resources)
        assert "localthings_rapid_fridge" not in bound
        assert "localthings_rapid_freeze" not in bound


# --- setpoint writes ------------------------------------------------------


def _applicable(capability: str, resources: dict):
    """The one spec for `capability` that applies to these resources.

    Two exist for each temperature capability — the per-compartment resource and the
    vendor aggregate — and exactly one may ever bind.
    """
    matches = [
        s for s in appliances.REFRIGERATOR.specs
        if s.capability == capability and s.applies(resources)
    ]
    assert len(matches) == 1, f"{capability}: {len(matches)} applicable specs"
    return matches[0]


def test_setpoint_writes_go_to_the_resource_they_were_read_from():
    """Not the vendor aggregate. A write confirmed by reading a *different* resource
    cannot be confirmed at all, and on this firmware the aggregate is the stale copy —
    the same copy that reported a door shut while it was open."""
    resources = load(COOLER)
    spec = _applicable("target_temperature.fridge", resources)
    assert spec.href == "/temperature/desired/cooler/0"
    assert spec.write(4, resources[spec.href]) == (
        ["temperature", "desired", "cooler", "0"], {"temperature": 4},
    )

    resources = load(FREEZER)
    spec = _applicable("target_temperature.freezer", resources)
    assert spec.href == "/temperature/desired/freezer/0"
    assert spec.write(-18, resources[spec.href]) == (
        ["temperature", "desired", "freezer", "0"], {"temperature": -18},
    )


def test_the_write_body_carries_only_the_field_being_changed():
    """`range` and `units` are the device's to report. The vendor body also replaced
    the whole items[] array with one partial entry, which briefly erased the other
    compartment's bounds from the local copy after every write."""
    resources = load(COOLER)
    spec = _applicable("target_temperature.fridge", resources)
    _segments, body = spec.write(4, resources[spec.href])
    assert set(body) == {"temperature"}


def test_the_vendor_aggregate_never_binds_alongside_the_per_compartment_resource():
    """Both are declared, for units that have only the aggregate. On these units the
    per-compartment resources exist, so the aggregate specs must stand down."""
    for stem in ALL:
        resources = load(stem)
        assert appliances.has_ocf_temperatures(resources), stem
        for capability in ("measure_temperature.fridge", "measure_temperature.freezer",
                           "target_temperature.fridge", "target_temperature.freezer"):
            bound = [
                s for s in appliances.REFRIGERATOR.specs
                if s.capability == capability and s.applies(resources)
            ]
            assert len(bound) <= 1, f"{stem}/{capability}: {[s.href for s in bound]}"
            for spec in bound:
                assert spec.href != "/temperatures/vs/0", f"{stem}/{capability}"


@pytest.mark.parametrize(("stem", "capability", "value"), [
    (COOLER, "target_temperature.fridge", 9),
    (COOLER, "target_temperature.fridge", -5),
    (FREEZER, "target_temperature.freezer", 0),
    (FREEZER, "target_temperature.freezer", -30),
])
def test_a_setpoint_outside_the_advertised_bounds_is_refused(stem, capability, value):
    resources = load(stem)
    spec = _applicable(capability, resources)
    assert spec.write(value, resources[spec.href]) is None


def test_setpoint_bounds_come_from_the_appliance():
    resources = load(COOLER)
    spec = _applicable("target_temperature.fridge", resources)
    assert resources[spec.href]["range"] == [0, 5]
    assert spec.options(resources[spec.href], resources) == {
        "min": 0.0, "max": 5.0, "step": 1, "decimals": 0,
    }
    resources = load(FREEZER)
    spec = _applicable("target_temperature.freezer", resources)
    assert resources[spec.href]["range"] == [-23, -17]
    assert spec.options(resources[spec.href], resources) == {
        "min": -23.0, "max": -17.0, "step": 1, "decimals": 0,
    }


# --- energy ---------------------------------------------------------------


def test_both_running_totals_are_reported_and_differ(any_unit):
    """cumulativeConsumption is a second, independently varying counter — not a
    duplicate of cumulativePower."""
    bound = _bound(any_unit)
    assert bound["meter_power"] > 0
    assert bound["meter_power.consumption"] > 0
    assert bound["meter_power"] != bound["meter_power.consumption"]

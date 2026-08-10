"""Kimchi refrigerators, asserted against the reference's dumps.

A standalone kimchi refrigerator already routed to the fridge registry on its
board token — it just read almost nothing. Measured 2026-08-10 before any of this
existed: of the capabilities the registry declares, a kimchi unit filled five, and
they were the door contact and three power readings. No temperature, no mode, no
ripening. Nothing failed, because a spec whose href is absent simply does not
apply, which is the quiet shape this repo has been caught by before.

`test_no_dead_mappings` could not catch it either. Its second invariant is "no spec
is blank on *every* dump of its type", and ordinary refrigerator dumps fill those
specs — so a whole sub-family reading nothing passes.

There is no kimchi refrigerator here, so these dumps are the hardware: two layouts
that do not overlap, one compartment against three. What they can prove is that
every field is read from the resource that carries it, and that the write is
refused for a mode the compartment does not advertise. What they cannot prove is
that the write works at all — see `test_the_write_is_declared_unverified`.
"""

import json
from pathlib import Path

import pytest

from lib import registry

REFERENCE = Path(__file__).parent.parent.parent / "localthings-reference"
FIXTURES = REFERENCE / "tests" / "fixtures"

pytestmark = pytest.mark.skipif(
    not FIXTURES.is_dir(), reason="reference checkout not present")

ONEDOOR = "refrigerator_tp1x_ref_21k_kimchi_device.json"
THREE = "refrigerator_tp2x_ref_20k_kimchi_device.json"


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


@pytest.fixture(scope="module")
def onedoor():
    return _flatten(ONEDOOR)


@pytest.fixture(scope="module")
def three():
    return _flatten(THREE)


def _read(resources, capability):
    reg = registry.resolve(resources, ())
    spec = reg.spec_for(capability, resources)
    assert spec is not None, f"{capability} is not declared"
    assert spec.applies(resources), f"{capability} does not bind on this dump"
    return spec.read(resources.get(spec.href), resources)


def test_both_layouts_still_route_to_the_refrigerator(onedoor, three):
    for resources in (onedoor, three):
        assert registry.resolve(resources, ()).name == "refrigerator"


@pytest.mark.parametrize("capability,expected", [
    ("localthings_kimchi_mode", "KIMCHI_STORAGE_NORMAL"),
    ("localthings_kimchi_ripening", "Off"),
    ("localthings_kimchi_ripening_remaining", 0),
    ("localthings_kimchi_rack_count", 8),
])
def test_the_one_door_layout_reads_its_compartment(onedoor, capability, expected):
    """One compartment, so it takes the bare capability: there is nothing to tell
    it apart from, and a lone tile labelled "Kimchi — Kimchi" reads badly."""
    assert _read(onedoor, capability) == expected


@pytest.mark.parametrize("slot,mode,racks", [
    ("top", "STORAGE_FREEZER_NORMAL", 6),
    ("middle", "KIMCHI_STORAGE_NORMAL", 4),
    ("bottom", "KIMCHI_STORAGE_NORMAL", 2),
])
def test_each_of_the_three_compartments_reads_its_own_state(three, slot, mode, racks):
    """The compartments genuinely differ — the top one is in a freezer mode while
    the other two hold kimchi, and all three report a different rack count. Reading
    one resource for all three would look plausible and be wrong."""
    assert _read(three, f"localthings_kimchi_mode.{slot}") == mode
    assert _read(three, f"localthings_kimchi_rack_count.{slot}") == racks


def test_a_compartment_only_binds_where_the_appliance_reports_one(onedoor, three):
    """The two layouts do not overlap, so neither unit may be given the other's
    compartments — that is what would put three empty tiles on a one-door unit."""
    reg = registry.resolve(onedoor, ())
    one_caps = set(reg.capabilities(onedoor))
    three_caps = set(reg.capabilities(three))

    assert "localthings_kimchi_mode" in one_caps
    assert not [c for c in one_caps if c.startswith("localthings_kimchi_mode.")]

    assert "localthings_kimchi_mode" not in three_caps
    assert {f"localthings_kimchi_mode.{s}" for s in ("top", "middle", "bottom")} <= three_caps


def test_an_ordinary_refrigerator_gets_no_kimchi_tiles():
    """The specs live on the shared fridge registry, so this is what stops the
    three units in this house from growing four blank compartments."""
    # This repo's own fridge dumps are flat {href: rep}, not wrapped the way the
    # air-conditioner fixture is.
    ours = json.loads(
        (Path(__file__).parent / "fixtures"
         / "refrigerator_TP2X_REF_21K_fridge_only.json").read_text())
    reg = registry.resolve(ours, ())
    assert not [c for c in reg.capabilities(ours) if "kimchi" in c]


@pytest.mark.parametrize("slot,supported,refused", [
    ("top", "STORAGE_FREEZER_NORMAL", "KIMCHI_STORAGE_CRUNFCH"),
    ("middle", "KIMCHI_STORAGE_COLD", "STORAGE_FREEZER_NORMAL"),
])
def test_a_mode_the_compartment_does_not_advertise_is_refused(three, slot, supported, refused):
    """`supportMode` is per compartment and really differs: the top slot offers
    freezer modes the middle one does not, and vice versa. The manifest has to
    declare the union of every board's vocabulary, so without this gate each picker
    would offer modes that compartment silently drops."""
    reg = registry.resolve(three, ())
    spec = reg.spec_for(f"localthings_kimchi_mode.{slot}", three)
    rep = three[spec.href]

    assert spec.write(refused, rep) is None
    path, body = spec.write(supported, rep)
    assert path == ["status", "kimchi", slot, "vs", "0"]
    assert body == {"x.com.samsung.da.currentMode": supported}


def test_every_mode_the_dumps_offer_is_declared_in_the_manifest(onedoor, three):
    """The gate above only helps if the value can be selected in the first place.
    A code a compartment advertises but the capability never declares is a mode the
    user simply cannot reach."""
    declared = {
        v["id"] for v in json.loads(
            (Path(__file__).parent.parent / ".homeycompose" / "capabilities"
             / "localthings_kimchi_mode.json").read_text())["values"]
    }
    offered = set()
    for resources in (onedoor, three):
        for href, rep in resources.items():
            if href.startswith("/status/kimchi/"):
                offered |= set(rep.get("x.com.samsung.da.supportMode") or ())
    assert offered <= declared, f"undeclared modes: {sorted(offered - declared)}"


def test_the_kimchi_drawer_can_raise_the_door_alarm(three):
    """`/kimchidoors/<slot>/vs/0` is a third spelling for a door and was missed
    until 2026-08-10: the one-door variant reports `/door/onedoorkimchi/vs/0`, which
    already matched the `/door/` prefix, so the door looked covered while this
    family's only contact switch was being ignored.

    Asserted by opening the drawer rather than by reading the dump as it stands.
    Every door on this dump is closed, so `alarm_contact` is False whether or not
    the resource is read at all — the first version of this test passed against
    the unfixed code and proved nothing.
    """
    from lib.registry import shared

    assert "/kimchidoors/top/vs/0" in three
    assert _read(three, "alarm_contact") is False

    opened = dict(three)
    opened["/kimchidoors/top/vs/0"] = {"x.com.samsung.da.openState": "Open"}
    assert shared.read_any_door_open(None, opened) is True


def test_the_write_is_declared_unverified():
    """No kimchi refrigerator exists here and the reference marks its own write
    path unconfirmed, so this ships under this module's stated rule — writes follow
    the reference's judgments — and not because anything was demonstrated.

    Pinned so that a later "verified" claim has to come with a measurement. If a
    report says a mode change does nothing, this is the first thing to suspect.
    """
    from lib.registry import appliances
    assert "unverified" in appliances._write_kimchi_mode.__doc__.lower()

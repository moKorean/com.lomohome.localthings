"""The 8888 bridge's envelope translation, against real captures.

This is the half of 8888 support that can be finished without the hardware,
and these tests are what make that claim true rather than hopeful. Upstream
committed twenty-five captures of appliances on that bridge — four of them as
*pairs*, the raw bodies the appliance answered and the canonical hrefs its own
translator produced from them — so the mapping is checkable end to end against
an appliance's own words.

That is the same standard as the fourteen CoAP types nobody here owns, and it
is deliberately not a claim about the transport. Nothing here opens a socket.
Whether a handshake completes, whether a token can be obtained and whether a
write is honoured are separate questions that need a unit; docs/BACKLOG.md
says so and says what would settle them.
"""

import json
from pathlib import Path

import pytest

from lib import legacy_bridge as bridge
from lib import registry

FIXTURES = Path(__file__).parent.parent.parent / "localthings-reference" / "tests" / "fixtures"

pytestmark = pytest.mark.skipif(not FIXTURES.is_dir(), reason="reference checkout not present")


def _captures():
    return sorted(FIXTURES.glob("*_8888.json"))


def _bodies_and_type(path: Path):
    """A capture's wrapper-keyed bodies and the type its record reported.

    Captures record that type in one of two places — inside the bodies as the
    record's own `type`, or beside them as `device_type` — so both are read.
    On the wire it is always the record's, which is what `resources_for`
    defaults to.
    """
    raw = json.loads(path.read_text())
    bodies = raw.get("bodies")
    if bodies is None:
        bodies = bridge.unwrap(*[v for v in raw.values() if isinstance(v, dict)])
    return bodies, bodies.get("type") or raw.get("device_type")


def _translated(path: Path):
    """The committed `{href: rep}` for a capture, where it has one."""
    pair = FIXTURES / f"{path.stem}_device.json"
    if not pair.is_file():
        return None
    return {entry["href"]: entry["rep"] for entry in json.loads(pair.read_text())["device0"]}


def test_there_are_captures_to_check_against():
    """A parse that silently found nothing reads as a pass. This file is worth
    nothing without the corpus, so it says how much of one it expects."""
    captures = _captures()
    assert len(captures) >= 10, [p.name for p in captures]
    assert sum(1 for p in captures if _translated(p) is not None) >= 4


@pytest.mark.parametrize("path", [p for p in _captures() if _translated(p) is not None],
                         ids=lambda p: p.stem)
def test_translation_matches_the_appliances_own_hrefs(path):
    """Every href and every rep, against the committed translation of the same
    capture. This is the whole mapping claim in one assertion.

    `with_record_type` is part of it, not setup: three of these four boards
    name no `deviceSubType` at all and the committed translation carries one,
    filled in from the record's own `type`. Without it they are unroutable.
    """
    bodies, device_type = _bodies_and_type(path)
    filled = bridge.with_record_type(bodies, device_type)
    assert bridge.to_resources(filled, bridge.table_for(device_type)) == _translated(path)


# What each capture is, by the name upstream gave its file. A routing table
# that changed under us would otherwise show up as nothing at all.
_EXPECTED = {
    "air_purifier_tp6x_vtl_16k_8888": "air_purifier",
    "airconditioner_tp6x_rac_16k_8888": "airconditioner",
    "airconditioner_tp6x_rac_16k_heat_8888": "airconditioner",
    "airconditioner_tp6x_rac_17k_8888": "airconditioner",
    "dryer_dongle_dv45k6500ex_8888": "dryer",
    "dryer_tp6x_dv80m8214aw_cooling_8888": "dryer",
    "oven_lcd_ov_wall_16k_8888": "oven",
    "oven_lcd_ov_wall_16k_divided_8888": "oven",
    "oven_lcd_ov_wall_16k_nw9300md_8888": "oven",
    "refrigerator_dongle_0260_8888": "refrigerator",
    "refrigerator_dongle_0281_8888": "refrigerator",
    "refrigerator_tp6x_ref_16k_8888": "refrigerator",
    "washer_dongle_wf7500_8888": "washer",
    "washer_tp6x_ww6500_8888": "washer",
}


def _resources(path: Path):
    bodies, device_type = _bodies_and_type(path)
    return bridge.resources_for(bodies, device_type)


@pytest.mark.parametrize("path", _captures(), ids=lambda p: p.stem)
def test_every_capture_routes_to_the_right_registry(path):
    assert path.stem in _EXPECTED, f"new capture {path.stem}; name what it is"
    reg = registry.resolve(_resources(path))
    assert reg is not None, "unrouted"
    assert reg.name == _EXPECTED[path.stem]


# Capabilities that bind on a capture and read nothing, with the reason. Blank
# is ordinary — a board that does not report a field should not publish one —
# but blank *with no reason written down* is how six appliance types once
# shipped reading nothing at all.
_ALLOWED_BLANK = {
    ("oven_lcd_ov_wall_16k_8888", "measure_temperature.cavity"): "idle oven, no reading",
    ("oven_lcd_ov_wall_16k_8888", "localthings_target_temperature_readonly"): "idle, no setpoint",
    ("oven_lcd_ov_wall_16k_nw9300md_8888", "measure_temperature.cavity"): "idle oven",
    ("oven_lcd_ov_wall_16k_nw9300md_8888", "localthings_target_temperature_readonly"): "idle",
    ("oven_lcd_ov_wall_16k_nw9300md_8888", "alarm_contact"): "this slot reports no Doors",
    ("oven_lcd_ov_wall_16k_divided_8888", "alarm_contact"): "this slot reports no Doors",
    ("dryer_tp6x_dv80m8214aw_cooling_8888", "localthings_drying_temperature"):
        "this board reports no waterTemperature",
    ("washer_dongle_wf7500_8888", "localthings_rinse_cycles"): "not reported by this board",
}


@pytest.mark.parametrize("path", _captures(), ids=lambda p: p.stem)
def test_nothing_binds_and_then_reads_nothing(path):
    resources = _resources(path)
    reg = registry.resolve(resources)
    blank = []
    for capability in reg.capabilities(resources):
        spec = reg.spec_for(capability, resources)
        if (spec.read(resources.get(spec.href) or {}, resources) is None
                and (path.stem, capability) not in _ALLOWED_BLANK):
            blank.append(capability)
    assert not blank, f"bound and permanently blank, with no reason recorded: {blank}"


@pytest.mark.parametrize("path", _captures(), ids=lambda p: p.stem)
def test_every_capture_actually_reads_something(path):
    """The other direction. A translation that produced empty reps would pass
    every test above — each href present, nothing contradicted — and deliver an
    appliance with blank tiles, which is exactly what this project shipped once."""
    resources = _resources(path)
    reg = registry.resolve(resources)
    alive = []
    for capability in reg.capabilities(resources):
        spec = reg.spec_for(capability, resources)
        if spec.read(resources.get(spec.href) or {}, resources) is not None:
            alive.append(capability)
    assert len(alive) >= 5, alive


def test_a_region_only_configuration_is_not_read_as_smart_control_off():
    """The trap the per-type override table exists for.

    These boards serve a Configuration holding only `region`. On
    `/remotectrl/vs/0` — where Configuration lands by default — the absent
    `remoteControlEnabled` is not a missing reading: it is the flag this whole
    app checks before touching an appliance. The air purifier, air conditioner
    and refrigerator tables move it to `/configuration/vs/0` for that reason.
    """
    path = FIXTURES / "air_purifier_tp6x_vtl_16k_8888.json"
    bodies, device_type = _bodies_and_type(path)
    assert (bodies.get("Configuration") or {}) == {"region": "000"}

    wrong = bridge.to_resources(bodies, bridge.table_for(None))
    assert "/remotectrl/vs/0" in wrong
    reg = registry.resolve(bridge.resources_for(bodies, None))
    assert "localthings_smart_control" in reg.capabilities(wrong)

    right = bridge.resources_for(bodies, device_type)
    assert "/remotectrl/vs/0" not in right
    assert "/configuration/vs/0" in right
    assert "localthings_smart_control" not in registry.resolve(right).capabilities(right)


def test_a_laundry_mode_is_a_cycle_and_not_an_operating_mode():
    """Mode means different things per family. On a washer it carries
    `Course_XX`, which belongs on `/course/vs/0`; leaving it on `/mode/vs/0`
    would hand the registry a cycle token where it looks for a mode."""
    path = FIXTURES / "washer_tp6x_ww6500_8888.json"
    resources = _resources(path)
    assert "/course/vs/0" in resources
    assert "/mode/vs/0" not in resources
    options = resources["/course/vs/0"]["x.com.samsung.da.options"]
    assert any(str(o).startswith("Course_") for o in options), options


def test_the_combi_cabinet_is_split_by_the_modes_it_offers():
    """`CombiOven` names a cabinet, not a type — the same subtype covers an
    oven cavity and a microwave. The mode list is what tells them apart."""
    oven = _resources(FIXTURES / "oven_lcd_ov_wall_16k_nw9300md_8888.json")
    assert oven["/information/vs/0"]["x.com.samsung.da.deviceSubType"] == "CombiOven"
    assert registry.resolve(oven).name == "oven"

    microwave = {
        entry["href"]: entry["rep"]
        for entry in json.loads(
            (FIXTURES / "microwave_tp6x_ov_17k_8888_device.json").read_text()
        )["device0"]
    }
    assert microwave["/information/vs/0"]["x.com.samsung.da.deviceSubType"] == "CombiOven"
    assert registry.resolve(microwave).name == "microwave"


def test_an_unmapped_wrapper_is_named_rather_than_silently_dropped():
    """A wrapper with no table row translates nothing. That is allowed — it is
    not allowed to be invisible, which is what this reports."""
    path = FIXTURES / "washer_tp6x_ww6500_8888.json"
    bodies, device_type = _bodies_and_type(path)
    unmapped = bridge.unmapped_wrappers(bodies, bridge.table_for(device_type))
    assert unmapped == ["EnergyConsumption"], unmapped


def test_a_joined_list_is_split_and_deduplicated():
    """This firmware packs list fields into one comma-joined string where the
    OCF side carries one value per entry."""
    assert bridge._split_joined(["a,b, a ,c"]) == ["a", "b", "c"]
    assert bridge._split_joined(["a", "b"]) == ["a", "b"]
    assert bridge._split_joined("not a list") == "not a list"


def test_the_course_table_is_declared_only_where_the_dial_was_walked():
    """These boards serve no `/st/washercourse/vs/0`. Borrowing another
    generation's catalog would name a cycle out of the wrong list — the two
    laundry tables share ids and disagree on most of them."""
    assert bridge.course_table("TP6X_WASHER_16K") == {
        bridge.COURSE_TABLE_HREF: {bridge.PREFIX + "st.courseTable": "Table_00"}
    }
    assert bridge.course_table("TP6X_DRYER") == {}
    assert bridge.course_table(None) == {}

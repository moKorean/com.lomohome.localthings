"""A mapping that reads nothing must not pass silently.

This is the check that was missing, and it found six broken appliance types. A wrong
mapping is invisible: the device pairs, the capability exists, the suite passes, and
the tile is simply blank forever — because a read returning None means "leave this
alone" rather than raising. It is how the range hood shipped once with every field
name guessed, and it had happened five more times since:

  vacuum_station   /cleanstation/status/vs/0 and /dustbag/vs/0 for the real
                   /status/cleanstation/vs/0 and two /component/station/ resources,
                   with all three field names wrong too — the whole type read nothing
  water_purifier   /lock/vs/0 and /status/vs/0 for /status/lock/vs/0 (three locks,
                   Locked/Unlocked) and /status/waterpurifier/vs/0
  air_dresser      /airdresser/vs/0, which does not exist; sanitize is on its own
                   option resource and the settings are on /washer/vs/0
  oven/microwave/   operationState, mode, temperature and desiredTemperature as
  range            fields of /oven/vs/0, where none of them live
  every laundry    remainingTime parsed as a digit string when all twenty dumps that
  appliance        carry it use HH:MM:SS

Two invariants, both measured against the reference's committed dumps of real
hardware, which is the closest thing to hardware for the fourteen types nobody here
owns:

1. No registry binds a resource path that nothing has ever reported.
2. No spec is blank on *every* dump of its type. Blank on some dumps is ordinary — a
   board that does not report that field — but blank on all of them means the mapping
   is wrong, or that nothing can confirm it, and either way it needs saying out loud.

Skipped when the reference checkout is absent, as the other reference tests are. CI
clones it.
"""

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from lib import registry

APP_ROOT = Path(__file__).parent.parent
REFERENCE = APP_ROOT.parent / "localthings-reference"
REF_FIXTURES = REFERENCE / "tests" / "fixtures"
OUR_FIXTURES = Path(__file__).parent / "fixtures"

# Paths we bind that no dump and no reference source mentions. Keep this empty if you
# can: an entry is a promise the path came from somewhere real, and "the reference has
# a similar one" is not a reason.
ALLOWED_UNSEEN: dict[str, str] = {}

# (type, capability) pairs that legitimately read nothing on every dump, each with the
# reason. Anything not listed here is a bug — that is the point of the list.
ALLOWED_BLANK: dict[tuple[str, str], str] = {
    ("air_dresser", "measure_power"): "dumps carry cumulativePower only, no instantaneous",
    ("dishwasher", "measure_power"): "dumps carry cumulativePower only",
    ("dryer", "measure_power"): "dumps carry cumulativePower only",
    ("washer", "measure_power"): "dumps carry cumulativePower only",
    ("microwave", "measure_power"): "dumps carry cumulativePower only",
    ("oven", "measure_power"): "dumps carry cumulativePower only",
    ("induction_cooktop", "measure_power"):
        "the idle unit reports -500 W, which is a sentinel, not a measurement",
    ("induction_cooktop", "localthings_smart_control"):
        "absent from the reference dump; confirmed live on the owner's unit instead",
    ("induction_cooktop", "measure_temperature.probe"):
        "the probe is disconnected in the dump and reads 0, which is gated out",
    ("induction_cooktop", "measure_battery.probe"): "same disconnected probe",
    ("oven", "localthings_target_temperature_readonly"):
        "every dump is idle with desired 0, which is treated as no setpoint",
    ("microwave", "localthings_target_temperature_readonly"): "same idle 0",
    ("range", "localthings_target_temperature_readonly"): "same idle 0",
    ("refrigerator", "localthings_alarm_code"):
        "the dumps that carry /alarms/vs/0 at all carry it as an empty stub",
}


def _resources_from(path: Path) -> dict:
    """The reference stores a nested /device/0 response; we key resources by href."""
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

    walk(json.loads(path.read_text()))
    return out


@pytest.fixture(scope="module")
def dumps() -> list[tuple[str, dict]]:
    if not REF_FIXTURES.is_dir():
        pytest.skip("reference checkout not present")
    loaded = [(path.name, _resources_from(path))
              for path in sorted(REF_FIXTURES.glob("*_device.json"))]
    loaded = [(name, res) for name, res in loaded if res]
    # A converter that silently produced nothing would make every test here pass.
    assert len(loaded) > 20, f"only {len(loaded)} dumps parsed — the walker broke"
    return loaded


@pytest.fixture(scope="module")
def known_hrefs() -> set[str]:
    if not (REFERENCE / "custom_components").is_dir():
        pytest.skip("reference checkout not present")
    found: set[str] = set()
    for path in (REFERENCE / "custom_components").rglob("*.py"):
        text = path.read_text()
        found |= set(re.findall(r'"(/[a-zA-Z0-9_./]+/0)"', text))
        found |= set(re.findall(r"'(/[a-zA-Z0-9_./]+/0)'", text))
    for path in REF_FIXTURES.rglob("*.json"):
        found |= set(re.findall(r'"href"\s*:\s*"([^"]+)"', path.read_text()))
    assert len(found) > 100, f"only {len(found)} reference hrefs — the parse broke"
    for path in OUR_FIXTURES.glob("*.json"):
        found |= set(json.loads(path.read_text()).get("resources") or {})
    return found


def test_no_registry_binds_a_path_nothing_reports(known_hrefs):
    invented: dict[str, set[str]] = {}
    for name, reg in sorted(registry._REGISTRY_BY_KEY.items()):
        for spec in reg.specs:
            # Compartment paths are built per unit from a template; the refrigerator's
            # own fixtures cover them under their concrete names.
            if spec.href.startswith("/temperature/"):
                continue
            if spec.href in known_hrefs or spec.href in ALLOWED_UNSEEN:
                continue
            invented.setdefault(spec.href, set()).add(name)
    assert not invented, "paths bound here that nothing reports: " + ", ".join(
        f"{href} ({', '.join(sorted(types))})" for href, types in sorted(invented.items())
    )


def test_no_spec_is_blank_on_every_dump_of_its_type(dumps):
    present, alive = Counter(), Counter()
    for _name, resources in dumps:
        reg = registry.resolve(resources)
        if reg is None:
            continue
        for capability in reg.capabilities(resources):
            spec = reg.spec_for(capability, resources)
            rep = resources.get(spec.href)
            if not rep:
                continue
            key = (reg.name, capability)
            present[key] += 1
            try:
                value = spec.read(rep, resources)
            except Exception:
                value = None
            if value is not None:
                alive[key] += 1

    assert present, "no capability was exercised — resolution or the walker broke"
    dead = sorted(key for key in present if not alive[key] and key not in ALLOWED_BLANK)
    assert not dead, (
        "these read nothing on every dump of their type, so the field or path is "
        "probably wrong: " + ", ".join(f"{t}:{c}" for t, c in dead)
    )


def test_the_blank_allow_list_has_no_stale_entries(dumps):
    """An entry that no longer applies is a claim about the code that has stopped being
    true, and it hides the next real one."""
    present, alive = Counter(), Counter()
    for _name, resources in dumps:
        reg = registry.resolve(resources)
        if reg is None:
            continue
        for capability in reg.capabilities(resources):
            spec = reg.spec_for(capability, resources)
            rep = resources.get(spec.href)
            if not rep:
                continue
            present[(reg.name, capability)] += 1
            try:
                value = spec.read(rep, resources)
            except Exception:
                value = None
            if value is not None:
                alive[(reg.name, capability)] += 1
    stale = [key for key in ALLOWED_BLANK if key not in present or alive[key]]
    assert not stale, f"allow-list entries that no longer apply: {stale}"


def test_every_allow_list_entry_carries_a_reason():
    for key, reason in ALLOWED_BLANK.items():
        assert reason.strip(), key
    for href, reason in ALLOWED_UNSEEN.items():
        assert reason.strip(), href


def test_the_six_broken_types_now_read_their_real_resources(dumps):
    """Named, because the invariants above prove a path exists somewhere and a field
    reads *something* — not that these particular six are wired correctly."""
    expected = {
        "vacuum_station_device.json": {
            "localthings_operation_state": "Ready",
            "localthings_alarm_dustbag": False,
            "localthings_dustbag_usage": 506.0,
        },
        "water_purifier_device.json": {
            "localthings_child_lock.hotwater": False,
            "localthings_child_lock.coldwater": False,
            "localthings_child_lock.buzzer": False,
            "localthings_operation_state": "Ready",
            "alarm_contact": False,
        },
        "air_dresser_tp2_20_device.json": {
            "localthings_sanitize": False,
            "localthings_wrinkle_prevent": False,
        },
        "oven_device.json": {
            "localthings_operation_state": "Ready",
            "localthings_oven_mode": "NoOperation",
            "alarm_contact": False,
        },
        # The Fahrenheit board, and the only dump with a live cavity reading: 175 °F.
        "range_device.json": {"measure_temperature.cavity": 79.4},
        # 03:02:00 — the form that used to return None for every appliance.
        "dryer_device.json": {"localthings_remaining_minutes": 182},
    }
    by_name = dict(dumps)
    for dump_name, wanted in expected.items():
        resources = by_name.get(dump_name)
        assert resources, f"{dump_name} missing from the reference fixtures"
        reg = registry.resolve(resources)
        assert reg is not None, dump_name
        for capability, value in wanted.items():
            spec = reg.spec_for(capability, resources)
            assert spec is not None, f"{dump_name}: {capability} not bound"
            assert spec.read(resources[spec.href], resources) == value, \
                f"{dump_name}: {capability}"

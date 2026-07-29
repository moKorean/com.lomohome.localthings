"""Cross-cutting checks over every appliance type.

Most of these types have no dump to test against, so what can be verified is
structural: that every board token the reference routes also routes here, that every
capability a registry names actually exists in the manifest, and that the safety
rules hold across all of them at once. Those are the failure modes that a
retyped-from-the-reference port is most likely to have.
"""

import json
import re
from pathlib import Path

import pytest

from lib import registry
from lib.registry import appliances

APP_ROOT = Path(__file__).parent.parent
CAPABILITY_DIR = APP_ROOT / ".homeycompose" / "capabilities"

# Capabilities Homey provides itself, so they need no definition here.
SYSTEM_CAPABILITIES = {
    "onoff", "target_temperature", "measure_temperature", "measure_humidity",
    "measure_power", "meter_power", "measure_pm25", "measure_battery",
    "alarm_contact",
}


def _identity(model="", description=""):
    return {"/information/vs/0": {
        "x.com.samsung.da.modelNum": model,
        "x.com.samsung.da.description": description,
    }}


def _reference_tokens() -> dict:
    """The reference's board-token table, read from its source.

    Importing by_type would drag in Home Assistant, and the table is a plain literal.
    """
    source = (
        APP_ROOT.parent / "localthings-reference" / "custom_components" / "localthings"
        / "registry" / "by_type" / "__init__.py"
    )
    if not source.is_file():
        pytest.skip("reference checkout not present")
    text = source.read_text()
    match = re.search(r"^_BOARD_TOKEN_TO_KEY[^=]*=\s*\{(.*?)^\}", text, re.S | re.M)
    body = re.sub(r"#[^\n]*", "", match.group(1))
    return dict(re.findall(r"'([^']+)'\s*:\s*'([^']+)'", body))


def test_every_reference_board_token_routes():
    """A token the reference recognises must not leave a device unsupported here."""
    for token, expected in _reference_tokens().items():
        resolved = registry.resolve(_identity(model=f"TP1X_DA-XX-{token}-01001|1|2"))
        assert resolved is not None, f"{token} routes nowhere"
        assert resolved.name == expected, f"{token} -> {resolved.name}, not {expected}"


def test_every_capability_has_a_definition():
    """A capability named by a registry but missing from the manifest would fail at
    device creation, and only for whoever owns that appliance type."""
    defined = {p.stem for p in CAPABILITY_DIR.glob("*.json")}
    for name, reg in registry._REGISTRY_BY_KEY.items():
        for spec in reg.specs:
            base = spec.capability.split(".")[0]
            assert base in defined or base in SYSTEM_CAPABILITIES, (
                f"{name} names {spec.capability} with no definition"
            )


def test_every_definition_is_used():
    """An unused definition means a capability was renamed and left behind."""
    used = {
        spec.capability.split(".")[0]
        for reg in registry._REGISTRY_BY_KEY.values()
        for spec in reg.specs
    }
    for path in CAPABILITY_DIR.glob("*.json"):
        assert path.stem in used, f"{path.stem} is defined but unused"


def test_capability_icons_exist():
    for path in CAPABILITY_DIR.glob("*.json"):
        icon = json.loads(path.read_text()).get("icon")
        if not icon:
            continue
        assert (APP_ROOT / icon.lstrip("/")).is_file(), f"{path.stem}: {icon} missing"


def test_setable_capabilities_have_a_write_and_the_reverse():
    """A picker the device can't accept is worse than no picker: it looks like it
    works and silently does nothing."""
    defined = {
        p.stem: json.loads(p.read_text()) for p in CAPABILITY_DIR.glob("*.json")
    }
    for name, reg in registry._REGISTRY_BY_KEY.items():
        for spec in reg.specs:
            base = spec.capability.split(".")[0]
            if base not in defined:
                continue
            setable = bool(defined[base].get("setable"))
            assert setable == spec.writable, (
                f"{name}.{spec.capability}: capability setable={setable} "
                f"but spec writable={spec.writable}"
            )


def test_no_heat_control_is_writable():
    """A cooking appliance must not be started by an automation. The reference states
    the rule for cooktops; it applies to every heat-producing type here."""
    forbidden = (
        "burner", "oven_mode", "target_temperature_readonly", "power_state",
    )
    for name in ("cooktop", "induction_cooktop", "oven", "range", "microwave"):
        reg = registry._REGISTRY_BY_KEY[name]
        for spec in reg.specs:
            if any(token in spec.capability for token in forbidden):
                assert not spec.writable, f"{name}.{spec.capability} is writable"
        # onoff would let a flow switch the appliance on.
        assert not any(
            s.capability == "onoff" and s.writable for s in reg.specs
        ) or name not in ("cooktop", "induction_cooktop"), (
            f"{name} exposes a writable onoff"
        )


def test_every_type_has_a_korean_title():
    for name, reg in registry._REGISTRY_BY_KEY.items():
        assert reg.titles, f"{name} has no titles"
        assert reg.titles.get("ko"), f"{name} has no Korean title"
        assert reg.title("ko") != name, f"{name} falls back to its key in Korean"


def test_consumer_prefixes_never_outrank_a_board_token():
    """'WAC' (window air conditioner) starts with 'WA' (top-load washer). The board
    token has to win or window units become washers."""
    resolved = registry.resolve(_identity(
        model="TP1X_DA-AC-WAC-01001|1|2", description="TP1X_DA-AC-WAC_WA8000T"))
    assert resolved.name == "airconditioner"


def test_consumer_prefix_resolves_when_no_board_token_matches():
    resolved = registry.resolve(_identity(description="TIZEN_WM_WW90DG6U25LEU4"))
    assert resolved.name == "washer"


def test_dryer_description_with_two_model_numbers():
    """The reference documents '..._DVE50A8800_8600', where the real token sits one
    segment before the last."""
    resolved = registry.resolve(_identity(description="TIZEN_WM_DVE50A8800_8600"))
    assert resolved.name == "dryer"


def test_shared_operational_state_reads_a_cycle():
    reg = registry._REGISTRY_BY_KEY["washer"]
    rep = {
        "x.com.samsung.da.state": "Run",
        "x.com.samsung.da.progressPercentage": "42",
        "x.com.samsung.da.remainingTime": "013000",
    }
    resources = {"/operational/state/vs/0": rep}
    reads = {s.capability: s.read(rep, resources) for s in reg.specs
             if s.href == "/operational/state/vs/0"}
    assert reads["localthings_machine_state"] == "Run"
    assert reads["localthings_cycle_active"] is True
    assert reads["localthings_progress"] == 42
    assert reads["localthings_remaining_minutes"] == 90


def test_finished_cycle_is_not_reported_as_running():
    """`state` can still read Run after a cycle ends; `progress` is what settles it."""
    reg = registry._REGISTRY_BY_KEY["washer"]
    rep = {"x.com.samsung.da.state": "Run", "x.com.samsung.da.progress": "Finish"}
    spec = next(s for s in reg.specs if s.capability == "localthings_cycle_active")
    assert spec.read(rep, {}) is False
    progress = next(s for s in reg.specs if s.capability == "localthings_progress")
    assert progress.read(rep, {}) == 100


def test_power_binds_only_the_form_the_board_reports():
    """Both the OCF and vendor power resources are declared; a board has one."""
    reg = registry._REGISTRY_BY_KEY["washer"]
    ocf = {"/power/0": {"value": True}}
    vendor = {"/power/vs/0": {"x.com.samsung.da.power": "On"}}
    assert reg.capabilities(ocf).count("onoff") == 1
    assert reg.capabilities(vendor).count("onoff") == 1
    assert "onoff" not in reg.capabilities({})


def test_negative_power_is_not_published_as_a_reading():
    """Seen as -500 W on an idle cooktop; it is a sentinel, not a measurement."""
    assert appliances.shared.read_power_watts(
        {"x.com.samsung.da.instantaneousPower": "-500"}, {}) is None
    assert appliances.shared.read_power_watts(
        {"x.com.samsung.da.instantaneousPower": "99"}, {}) == 99.0

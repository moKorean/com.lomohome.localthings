"""Laundry tile alias: preserve old Flows and reconcile already-paired devices."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from lib.registry import _REGISTRY_BY_KEY, appliances, shared

ROOT = Path(__file__).parent.parent
OLD = "localthings_remaining_minutes"
NEW = "measure_remaining_minutes"


def _device_method(name):
    # Execute the real methods without importing Homey's container-only SDK.
    tree = ast.parse((ROOT / "lib/appliance/device.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == "ApplianceDevice")
    method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<device method>", "exec"),
         namespace)
    return namespace[name]


@pytest.mark.parametrize("reg", [appliances.WASHER, appliances.DRYER])
@pytest.mark.parametrize(("rep", "expected"), [
    ({"x.com.samsung.da.remainingTime": "03:35:00"}, 215),
    ({"remainingTime": "00:44:00"}, 44),
    ({"x.com.samsung.da.remainingTime": "00:01:00",
      "x.com.samsung.da.progress": "Finish"}, 0),
    ({}, None),
    ({"remainingTime": "invalid"}, None),
])
def test_indicator_matches_legacy_reading(reg, rep, expected):
    resources = {shared.HREF_OPERATIONAL: rep}
    for capability in (OLD, NEW):
        spec = reg.spec_for(capability)
        assert spec.read(rep, resources) == expected
        assert spec.write is None


def test_only_laundry_gets_the_indicator():
    for reg in _REGISTRY_BY_KEY.values():
        caps = reg.capabilities({shared.HREF_OPERATIONAL: {"remainingTime": "00:44:00"}})
        assert (NEW in caps) == (reg.name in {"washer", "dryer"})


def test_manifest_defines_a_numeric_tile_indicator_without_duplicate_history():
    definition = json.loads(
        (ROOT / ".homeycompose/capabilities" / f"{NEW}.json").read_text())
    assert NEW.startswith("measure_")
    assert definition["type"] == "number"
    assert definition["units"]["en"] == "min"
    assert definition["getable"] and not definition["setable"]
    assert definition["uiComponent"] is None
    assert definition["insights"] is False


@pytest.mark.parametrize("reg", [appliances.WASHER, appliances.DRYER])
@pytest.mark.asyncio
async def test_existing_device_gains_alias_and_keeps_legacy_on_refresh(reg):
    resources = {shared.HREF_OPERATIONAL: {"remainingTime": "00:44:00"}}
    current = [c for c in reg.capabilities(resources) if c != NEW]
    values = {OLD: 45}
    added, removed = [], []

    async def add(capability):
        current.append(capability)
        added.append(capability)

    async def remove(capability):
        current.remove(capability)
        removed.append(capability)

    async def set_value(capability, value):
        values[capability] = value

    device = SimpleNamespace(
        _registry=reg, _resources=resources,
        get_capabilities=lambda: list(current),
        add_capability=add, remove_capability=remove, log=Mock(),
        register_capability_listener=Mock(), _make_listener=Mock(),
        get_capability_value=values.get, set_capability_value=set_value,
        _note_on_timeline=AsyncMock(), _maybe_trigger=AsyncMock(),
    )
    sync, apply = _device_method("_sync_capabilities"), _device_method("_apply")
    await sync(device)
    assert added == [NEW]
    assert removed == []
    assert OLD in current
    await apply(device, resources, only_href=shared.HREF_OPERATIONAL)
    assert values[NEW] == values[OLD] == 44

    # Completion updates both; malformed updates must preserve the last good value.
    resources[shared.HREF_OPERATIONAL] = {
        "remainingTime": "00:01:00", "x.com.samsung.da.progress": "Finish"}
    await apply(device, resources, only_href=shared.HREF_OPERATIONAL)
    assert values[NEW] == values[OLD] == 0
    resources[shared.HREF_OPERATIONAL] = {"remainingTime": "invalid"}
    await apply(device, resources, only_href=shared.HREF_OPERATIONAL)
    assert values[NEW] == values[OLD] == 0
    await sync(device)
    assert added == [NEW]
    assert removed == []

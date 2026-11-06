"""The panel display light, on all three encodings boards use for it.

A user asked to switch their air conditioner's display off at night and could
not. The capability existed and worked — on `/light/stateful/vs/0`, which 2 of
the 26 air conditioners in the reference's corpus report, this house's CAC among
them. It was built from the one encoding almost nobody else had, so for most
owners the tile was simply absent. The other boards split between a plain
`/light/vs/0` switch and a `Light_*` token in `/mode/vs/0`'s options array.

Two things here would have shipped broken if taken at face value:

1. **The token is inverted.** `Light_Off` means the panel is lit. Reading it by
   its name would have the user turning the display on to switch it off.
2. **A token write truncates the cache.** The write carries only the changed
   token, and `options` is a flat array of two dozen of them, so folding it in
   with a plain assignment drops the rest and every token-gated capability on the
   unit reads as absent until the next poll.
"""

import json
import sys
import types
from pathlib import Path

import pytest

from lib import registry

OPTIONS_FIELD = "x.com.samsung.da.options"


@pytest.fixture
def device_module():
    """lib.appliance.device with the runtime-provided `homey` module stubbed,
    the same way tests/test_alarm_cache_replace.py reaches it."""
    stub = types.ModuleType("homey")
    device_module = types.ModuleType("homey.device")

    class HomeyDevice:
        def log(self, *args):
            pass

    device_module.Device = HomeyDevice
    stub.device = device_module
    saved = {name: sys.modules.get(name) for name in ("homey", "homey.device")}
    sys.modules["homey"], sys.modules["homey.device"] = stub, device_module
    try:
        import lib.appliance.device as module
        yield module
    finally:
        for name, saved_module in saved.items():
            if saved_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = saved_module

REF_FIXTURES = Path(__file__).parent.parent.parent / "localthings-reference" / "tests" / "fixtures"
CAPABILITY = "localthings_display_light"

pytestmark = pytest.mark.skipif(
    not REF_FIXTURES.is_dir(), reason="reference checkout not present"
)


def _resources(path: Path) -> dict:
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


def _bound(resources):
    reg = registry.resolve(resources)
    if reg is None or reg.name != "airconditioner":
        return None
    spec = reg.spec_for(CAPABILITY, resources)
    return spec if spec is not None and spec.applies(resources) else None


def test_most_air_conditioners_can_now_switch_their_display():
    """Before this, two could. The count is asserted rather than described so a
    regression that quietly drops an encoding fails here."""
    dumps = sorted(REF_FIXTURES.glob("airconditioner*device.json"))
    assert len(dumps) >= 20, "corpus shrank — re-derive this test"

    by_href = {}
    for dump in dumps:
        spec = _bound(_resources(dump))
        if spec is not None:
            by_href.setdefault(spec.href, []).append(dump.name)

    assert set(by_href) == {
        "/light/stateful/vs/0",
        "/light/vs/0",
        "/mode/vs/0",
    }, sorted(by_href)
    assert sum(len(v) for v in by_href.values()) >= 20


def test_each_board_binds_exactly_one_encoding():
    """They are mutually exclusive on every board seen; two binding at once would
    mean one of them is reading a field that is not the display light."""
    for dump in sorted(REF_FIXTURES.glob("airconditioner*device.json")):
        resources = _resources(dump)
        reg = registry.resolve(resources)
        if reg is None or reg.name != "airconditioner":
            continue
        applying = [
            s for s in reg.specs
            if s.capability == CAPABILITY and s.applies(resources)
        ]
        assert len(applying) <= 1, f"{dump.name}: {[s.href for s in applying]}"


def test_the_options_token_is_read_inverted():
    """Light_Off while lit, Light_On while dark — established upstream by a live
    toggle, and the whole reason this is not a plain flag read."""
    lit = {OPTIONS_FIELD: ["Wind_Off", "Light_Off", "Sleep_Off"]}
    dark = {OPTIONS_FIELD: ["Wind_Off", "Light_On", "Sleep_Off"]}
    spec = _bound(_resources(REF_FIXTURES / "airconditioner_device.json"))
    assert spec is not None and spec.href == "/mode/vs/0"

    assert spec.read(lit, {}) is True
    assert spec.read(dark, {}) is False
    # And the write inverts the same way round.
    assert spec.write(True, lit)[1][OPTIONS_FIELD] == ["Light_Off"]
    assert spec.write(False, lit)[1][OPTIONS_FIELD] == ["Light_On"]


def test_a_token_write_keeps_the_other_tokens(device_module):
    """The truncation guard. A real options array carries two dozen tokens and the
    write carries one; everything else has to survive the fold."""
    cached = {OPTIONS_FIELD: ["Wind_Off", "Light_On", "Sleep_Off", "Comode_Off"]}
    device_module._fold_write_into(cached, {OPTIONS_FIELD: ["Light_Off"]})
    assert cached[OPTIONS_FIELD] == ["Wind_Off", "Light_Off", "Sleep_Off", "Comode_Off"]


def test_a_token_the_board_had_not_advertised_is_added(device_module):
    cached = {OPTIONS_FIELD: ["Wind_Off"]}
    device_module._fold_write_into(cached, {OPTIONS_FIELD: ["Light_Off"]})
    assert cached[OPTIONS_FIELD] == ["Wind_Off", "Light_Off"]

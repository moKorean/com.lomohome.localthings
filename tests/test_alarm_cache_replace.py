"""A cleared alarm has to leave the cache, and merging kept it forever.

Pushed updates are shallow-merged onto the cached rep, which is right in general: a
notification can carry only the fields that changed, so an absent key means "keep
what we had". `/alarms/vs/0` is where that reasoning inverts, because **its empty
state is an empty rep**. Measured on this house's own hardware — all three
refrigerators report

    "/alarms/vs/0": {}

with nothing wrong. So `{}` is what the board says when it has no alarm, and merging
it is a no-op: the alarm that was there stays in the cache for as long as the app
runs. A poll would rebuild the rep wholesale and clear it, but a device on push only
gets a summary sweep, so in the normal case nothing ever does.

Found in the reference's fix for the same bug (issue #348), where a live read on a
reporter's washer confirmed the `{}`. The refrigerator dumps here are the local
confirmation that it is our bug too, not just theirs.
"""

import json
import sys
import types
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

ALARMS = "/alarms/vs/0"
ITEMS = "x.com.samsung.da.items"


@pytest.fixture
def device_module():
    """lib.appliance.device with the runtime-provided `homey` module stubbed."""
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


def test_the_refrigerators_really_do_report_an_empty_alarms_rep():
    """The premise, from our own dumps rather than the reference's. If a future
    firmware reported `{items: []}` instead, the merge would have been harmless and
    this whole rule could go."""
    empty = []
    for path in sorted(FIXTURES.glob("refrigerator_*.json")):
        resources = json.loads(path.read_text())
        assert resources.get(ALARMS) == {}, path.name
        empty.append(path.name)
    assert len(empty) == 3, empty


@pytest.mark.parametrize("href", [
    "/alarms/vs/0", "/alarms/vs/1", "/alarms/vs/2", "/prefix/alarms/vs/0",
])
def test_the_alarms_resource_replaces(device_module, href):
    assert device_module._replaces_on_notify(href) is True


@pytest.mark.parametrize("href", [
    "/mode/vs/0",          # the partial-notify case the merge exists for
    "/course/vs/0",
    "/doors/vs/0",
    "/kimchialarms/vs/0",  # no such resource, and a suffix test would claim it
    "/alarms/vs",
])
def test_everything_else_still_merges(device_module, href):
    assert device_module._replaces_on_notify(href) is False


def _notify(device_module, cached, href, rep):
    """The cache half of _on_notification, without the Homey device around it."""
    resources = {href: dict(cached)} if cached is not None else {}
    if device_module._replaces_on_notify(href):
        resources[href] = dict(rep)
    else:
        resources.setdefault(href, {}).update(rep)
    return resources[href]


def test_a_cleared_alarm_leaves_the_cache(device_module):
    live = {ITEMS: [{"x.com.samsung.da.code": "ErrorCode_DC"}]}
    assert _notify(device_module, live, ALARMS, {}) == {}


def test_the_same_empty_update_would_have_been_ignored_by_a_merge(device_module):
    """Pins the bug itself, so the fix cannot be quietly undone by restoring the
    one-line merge: on this resource a merge does not just delay the clear, it never
    clears at all."""
    live = {ITEMS: [{"x.com.samsung.da.code": "ErrorCode_DC"}]}
    merged = dict(live)
    merged.update({})
    assert merged == live


def test_a_replaced_alarm_is_not_left_alongside_the_old_one(device_module):
    """Replacement is not only about the empty case — a rep naming one alarm must
    not read as two because the previous one's keys survived."""
    live = {ITEMS: [{"x.com.samsung.da.code": "ErrorCode_DC"}], "stale": "1"}
    fresh = {ITEMS: [{"x.com.samsung.da.code": "FilterAlarm"}]}
    assert _notify(device_module, live, ALARMS, fresh) == fresh


def test_a_partial_mode_notification_still_keeps_the_rest(device_module):
    """The behaviour the merge exists for, so narrowing the rule to alarms is
    visible as a deliberate boundary rather than an oversight."""
    cached = {
        "x.com.samsung.da.modes": ["Cool"],
        "x.com.samsung.da.supportedModes": ["Cool", "Dry"],
    }
    got = _notify(device_module, cached, "/mode/vs/0", {"x.com.samsung.da.modes": ["Dry"]})
    assert got["x.com.samsung.da.modes"] == ["Dry"]
    assert got["x.com.samsung.da.supportedModes"] == ["Cool", "Dry"]


def test_the_notification_path_uses_the_rule(device_module):
    """The helper is only worth having if _on_notification actually consults it."""
    import ast
    source = Path(device_module.__file__).read_text()
    handler = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_on_notification"
    )
    assert "_replaces_on_notify" in ast.unparse(handler)

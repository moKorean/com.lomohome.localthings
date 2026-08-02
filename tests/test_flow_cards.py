"""The Flow cards, and the fact that they are generated.

Homey generates cards for system capabilities only, so the 70 this app defines had
none — a Flow could not switch a hood's light or read a filter's wear. The cards are
generated from the capability definitions by scripts/make_flow_cards.py, and their
listeners are generated from the same manifest, so nothing here is written twice.

That design has one failure mode worth guarding: the generated tree drifting from the
capability definitions, which would leave a card whose listener never resolves, or a
capability whose card was never emitted. Both are silent — the Flow editor just does
not offer the thing.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).parent.parent
CAPS = APP_ROOT / ".homeycompose/capabilities"
FLOW = APP_ROOT / ".homeycompose/flow"
GENERATOR = APP_ROOT / "scripts/make_flow_cards.py"
DRIVER = APP_ROOT / "lib/appliance/driver.py"
DEVICE = APP_ROOT / "lib/appliance/device.py"


def cards(kind: str) -> dict:
    directory = FLOW / kind
    if not directory.is_dir():
        return {}
    return {p.stem: json.loads(p.read_text()) for p in directory.glob("*.json")}


@pytest.fixture(scope="module")
def capabilities() -> dict:
    return {p.stem: json.loads(p.read_text()) for p in CAPS.glob("*.json")}


def test_the_generated_tree_is_up_to_date():
    """The generator is the source of truth. If this fails, run it."""
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True, text=True, cwd=APP_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_setable_capability_has_an_action(capabilities):
    """Actions are the whole point: without one, a capability can be read in a Flow
    but never changed by it."""
    actions = cards("actions")
    missing = [
        name for name, definition in capabilities.items()
        if definition.get("setable") and f"set_{name[len('localthings_'):]}" not in actions
        and name != "localthings_display_light"   # hand-written as `set_light`
    ]
    assert not missing, f"setable but not actionable: {missing}"


def test_every_capability_has_a_condition(capabilities):
    conditions = cards("conditions")
    missing = [
        name for name, definition in capabilities.items()
        if f"{name[len('localthings_'):]}_is" not in conditions
        and name != "localthings_display_light"   # hand-written as `light_is_on`
    ]
    assert not missing, f"no condition card: {missing}"


def test_no_card_points_at_a_capability_that_does_not_exist(capabilities):
    """A renamed capability leaving its card behind gives a card whose listener can
    never resolve — it appears in the editor and does nothing."""
    for kind in ("actions", "conditions", "triggers"):
        for name, card in cards(kind).items():
            for arg in card.get("args") or ():
                if arg.get("type") != "device":
                    continue
                filt = arg.get("filter") or ""
                for part in filt.split("&"):
                    if part.startswith("capabilities="):
                        wanted = part.split("=", 1)[1]
                        assert wanted in capabilities or not wanted.startswith(
                            "localthings_"
                        ), f"{kind}/{name} filters on unknown {wanted}"


def test_every_card_is_scoped_to_this_driver(capabilities):
    """Without a driver filter a card is offered for every device on the Homey."""
    for kind in ("actions", "conditions", "triggers"):
        for name, card in cards(kind).items():
            device_args = [
                a for a in card.get("args") or () if a.get("type") == "device"
            ]
            assert device_args, f"{kind}/{name} has no device argument"
            for arg in device_args:
                assert "driver_id=appliance" in (arg.get("filter") or ""), (
                    f"{kind}/{name} is not scoped to the appliance driver"
                )


@pytest.mark.parametrize("kind", ["actions", "conditions", "triggers"])
def test_every_card_has_both_languages(kind):
    for name, card in cards(kind).items():
        for field in ("title", "titleFormatted", "hint"):
            value = card.get(field)
            if value is None:
                continue
            assert value.get("en"), f"{kind}/{name}.{field} has no English"
            assert value.get("ko"), f"{kind}/{name}.{field} has no Korean"


@pytest.mark.parametrize("kind", ["actions", "conditions", "triggers"])
def test_titles_follow_the_store_guidelines(kind):
    """Guideline 1.9: no When/And/Then, no device names, no parentheses."""
    for name, card in cards(kind).items():
        for lang in ("en", "ko"):
            title = (card.get("title") or {}).get(lang) or ""
            assert "(" not in title and ")" not in title, f"{kind}/{name}: {title}"
            lowered = title.lower()
            for banned in ("when ", "and ", "then "):
                assert not lowered.startswith(banned), f"{kind}/{name}: {title}"


def test_titleformatted_is_present_wherever_homey_wants_it():
    """Homey warns on a condition or trigger without it and says it will become
    required. Actions carry it too, since that is where the arguments show."""
    for kind in ("actions", "conditions", "triggers"):
        for name, card in cards(kind).items():
            assert card.get("titleFormatted"), f"{kind}/{name} has no titleFormatted"


def test_number_conditions_carry_a_value_argument():
    """A threshold card with nothing to compare against would always be true."""
    for name, card in cards("conditions").items():
        title = (card.get("title") or {}).get("en") or ""
        if "at least" not in title:
            continue
        names = {a.get("name") for a in card.get("args") or ()}
        assert "value" in names, f"conditions/{name} compares against nothing"


def test_boolean_actions_offer_both_states():
    for name, card in cards("actions").items():
        dropdowns = [
            a for a in card.get("args") or () if a.get("name") == "state"
        ]
        for arg in dropdowns:
            ids = {v["id"] for v in arg.get("values") or ()}
            assert ids == {"on", "off"}, f"actions/{name}: {ids}"


# --- the listeners have to exist for the cards to do anything ---------------


def test_the_driver_registers_listeners_generically():
    """One listener per card would be a hundred near-identical functions, and the
    first to drift from its card would fail only for whoever owned that appliance."""
    source = DRIVER.read_text()
    assert "_flow_cards" in source
    assert "_condition_for" in source and "_action_for" in source
    assert "_custom_capabilities" in source


def test_actions_write_through_the_capability_listener():
    """set_capability_value would move Homey's copy and never touch the appliance,
    and would not raise when the appliance refuses — so a Flow would report a success
    it did not get."""
    source = DRIVER.read_text()
    action = source[source.index("def _action_for"):]
    action = action[:action.index("return listener")]
    # Comments out: the code explains why it avoids set_capability_value, and naming
    # it there must not read as using it.
    code = "\n".join(
        line.split("#", 1)[0] for line in action.splitlines()
    )
    assert "trigger_capability_listener" in code
    assert "set_capability_value" not in code


def test_homey_fires_plain_capabilities_and_the_app_only_covers_sub_capabilities():
    """Homey runs a trigger named for a custom capability when its value changes, so
    the cards use those ids and plain capabilities need no dispatch at all.

    Sub-capabilities are the gap: Homey would look for
    `localthings_alarm_hot_surface.2_true`, which cannot exist, so a cooktop's
    per-burner alarm would never fire. Only those are dispatched here — firing plain
    ones too would trigger every Flow twice."""
    source = DEVICE.read_text()
    body = source[source.index("async def _maybe_trigger"):]
    body = body[:body.index("def _trigger_cards")]
    assert 'if "." not in capability:' in body, (
        "plain capabilities are not excluded, so they would fire twice"
    )
    # Still guarded: resolving a card that was never declared raises.
    assert "if card_id not in self._trigger_cards():" in body


def test_the_trigger_cards_use_homeys_naming_convention():
    """`<capability>_true` / `<capability>_false` for a boolean, `<capability>_changed`
    otherwise. A card named anything else is simply never fired by Homey."""
    capabilities = {p.stem for p in CAPS.glob("*.json")}
    for name in cards("triggers"):
        assert name.startswith("localthings_"), f"triggers/{name} is off-convention"
        for suffix in ("_true", "_false", "_changed"):
            if name.endswith(suffix):
                capability = name[: -len(suffix)]
                assert capability in capabilities, (
                    f"triggers/{name} names no capability"
                )
                break
        else:
            raise AssertionError(f"triggers/{name} has no convention suffix")


def test_boolean_capabilities_get_both_directions():
    """One "changed" card would make a Flow that wants the light coming on add a
    condition to discard the other half of the transitions."""
    booleans = {
        p.stem for p in CAPS.glob("*.json")
        if json.loads(p.read_text()).get("type") == "boolean"
    }
    triggers = set(cards("triggers"))
    for name in triggers:
        if not name.endswith("_true"):
            continue
        capability = name[: -len("_true")]
        assert capability in booleans, f"{name} is not a boolean capability"
        assert f"{capability}_false" in triggers, f"{capability} has no _false card"


# --- the run-listener call signature ---------------------------------------
#
# homey-stubs types the contract as
#
#     async def __call__(self, card_arguments: Mapping[str, Any],
#                        **trigger_kwargs: Any) -> ReturnType
#
# One positional parameter; everything else — `manual` among them — arrives as a
# keyword. A listener written JS-style as `(args, state)` declares a second
# *positional* parameter that Homey never fills, and then dies on the first
# keyword it is handed: "unexpected keyword argument 'manual'". Every card fails,
# and only at run time, because registration itself does not inspect the
# signature. Observed in another app; these pin that this one cannot acquire it.
#
# Capability listeners are a different path with a different signature and are
# unaffected — which is why device cards kept working there while Flow cards did not.

def _listener_functions():
    """Every function in the driver that Homey will call as a run listener.

    Found by following `_flow_cards`, so a listener added there is covered without
    this list being maintained by hand.
    """
    import ast
    tree = ast.parse(DRIVER.read_text())
    cards = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_flow_cards"
    )
    # The yielded listeners: `self._on_x` directly, or `self._factory(...)` whose
    # inner function is what actually gets registered.
    named, factories = set(), set()
    for node in ast.walk(cards):
        if isinstance(node, ast.Attribute) and node.attr.startswith("_on_"):
            named.add(node.attr)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr.endswith("_for"):
            factories.add(node.func.attr)
    assert named, "no _on_* listeners found — has _flow_cards been restructured?"
    assert factories, "no listener factories found — has _flow_cards been restructured?"

    found = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in named:
                found[node.name] = node
            if node.name in factories:
                inner = next(
                    (n for n in ast.walk(node)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n is not node),
                    None,
                )
                assert inner is not None, f"{node.name} returns no inner listener"
                found[f"{node.name}:{inner.name}"] = inner
    return found


def test_every_run_listener_matches_the_sdk_signature():
    functions = _listener_functions()
    # Both factories and all three hand-written cards, or the walk missed something.
    assert len(functions) >= 5, sorted(functions)
    for label, fn in sorted(functions.items()):
        arguments = fn.args
        positional = [p.arg for p in arguments.posonlyargs + arguments.args]
        if positional and positional[0] == "self":
            positional = positional[1:]
        assert len(positional) == 1, (
            f"{label} takes {positional}; Homey passes exactly one positional "
            f"argument and sends everything else as a keyword, so a second "
            f"positional parameter is never filled"
        )
        assert arguments.kwarg is not None, (
            f"{label} has no **kwargs, so Homey passing `manual` raises "
            f"'unexpected keyword argument' and the card fails at run time"
        )


def test_every_run_listener_is_async():
    """The SDK awaits the return value; a plain def would hand it a coroutine-less
    result and, for a condition, make every card read as true."""
    for label, fn in sorted(_listener_functions().items()):
        assert isinstance(fn, __import__("ast").AsyncFunctionDef), f"{label} is not async"


@pytest.fixture
def driver_instance():
    """The real driver class, with the runtime-provided `homey` module stubbed.

    Built with __new__ so no Homey session is needed: these listeners read only
    their arguments and the device handed to them.
    """
    import types
    stub = types.ModuleType("homey")
    driver_module = types.ModuleType("homey.driver")

    class Driver:
        def log(self, *args):
            pass

    driver_module.Driver = Driver
    stub.driver = driver_module
    saved = {name: sys.modules.get(name) for name in ("homey", "homey.driver")}
    sys.modules["homey"], sys.modules["homey.driver"] = stub, driver_module
    try:
        from lib.appliance.driver import ApplianceDriver
        yield object.__new__(ApplianceDriver)
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class _FakeDevice:
    def __init__(self):
        self.written = None

    def get_capability_value(self, capability):
        return "Cool"

    def is_pushing(self):
        return True

    async def trigger_capability_listener(self, capability, value):
        self.written = (capability, value)


# What Homey actually sends alongside the card arguments. `manual` is the one that
# broke the other app; the rest are here so nothing depends on it being alone.
TRIGGER_KWARGS = {"manual": True, "tokens": {}, "state": {}}


@pytest.mark.parametrize("label,args", [
    ("condition", {"value": "Cool"}),
    ("action", {"value": "Cool"}),
])
def test_the_generated_listeners_accept_homeys_trigger_arguments(
        driver_instance, label, args):
    import asyncio
    factory = (driver_instance._condition_for if label == "condition"
               else driver_instance._action_for)
    listener = factory("localthings_mode")
    device = _FakeDevice()
    # No pytest.raises: a TypeError here is the bug, and letting it propagate names
    # the missing parameter in the failure output.
    asyncio.run(listener({"device": device, **args}, **TRIGGER_KWARGS))


@pytest.mark.parametrize("name,args", [
    ("_on_is_pushing", {}),
    ("_on_light_is_on", {"state": "on"}),
    ("_on_set_light", {"state": "on"}),
])
def test_the_hand_written_listeners_accept_homeys_trigger_arguments(
        driver_instance, name, args):
    import asyncio
    listener = getattr(driver_instance, name)
    asyncio.run(listener({"device": _FakeDevice(), **args}, **TRIGGER_KWARGS))


def test_no_condition_card_declares_a_state_argument():
    """Conditions rely on Homey inverting them, not on an on/off argument.

    Every condition title carries `!{{is|is not}}`, so the listener reports the value
    and Homey negates it for the second form. A listener that also read a `state`
    argument would be answering a question no card asks — and would invert twice if
    one were ever added without checking this.
    """
    for path in sorted((FLOW / "conditions").glob("*.json")):
        names = {a.get("name") for a in json.loads(path.read_text()).get("args") or ()}
        assert "state" not in names, f"{path.name} declares state; see _condition_for"


def test_boolean_actions_are_the_ones_that_carry_state():
    """The asymmetry is real and load-bearing: _action_for reads `state` because
    boolean *actions* have to say which way to set it, while conditions do not."""
    with_state = [
        path.name for path in sorted((FLOW / "actions").glob("*.json"))
        if any(a.get("name") == "state"
               for a in json.loads(path.read_text()).get("args") or ())
    ]
    assert with_state, "no action carries state, so _action_for's branch is dead"


def test_a_boolean_condition_reports_the_value_for_homey_to_invert(driver_instance):
    """What the removed `state` branch would have broken."""
    import asyncio
    listener = driver_instance._condition_for("localthings_child_lock")
    device = _FakeDevice()
    device.get_capability_value = lambda capability: True
    assert asyncio.run(listener({"device": device}, **TRIGGER_KWARGS)) is True
    device.get_capability_value = lambda capability: False
    assert asyncio.run(listener({"device": device}, **TRIGGER_KWARGS)) is False


def test_a_boolean_action_maps_the_dropdown_onto_the_capability(driver_instance):
    import asyncio
    listener = driver_instance._action_for("localthings_child_lock")
    for choice, expected in (("on", True), ("off", False)):
        device = _FakeDevice()
        asyncio.run(listener({"device": device, "state": choice}, **TRIGGER_KWARGS))
        assert device.written == ("localthings_child_lock", expected)


def test_the_light_condition_reflects_the_capability(driver_instance):
    """The light card has only a device argument, same as every generated condition."""
    import asyncio
    device = _FakeDevice()
    device.get_capability_value = lambda capability: True
    assert asyncio.run(driver_instance._on_light_is_on({"device": device},
                                                      **TRIGGER_KWARGS)) is True
    device.get_capability_value = lambda capability: False
    assert asyncio.run(driver_instance._on_light_is_on({"device": device},
                                                       **TRIGGER_KWARGS)) is False


# --- the combined air-conditioner card -------------------------------------
#
# Chaining the per-capability cards makes each decide what to send from this app's
# cache of /device/0, refreshed by polling and up to OBSERVE_SWEEP_INTERVAL_S old on
# push, so one running straight after another can act on state from before it. The
# combined card re-reads between steps instead.


def _ac_card():
    return json.loads((FLOW / "actions" / "set_ac_settings.json").read_text())


def test_the_combined_card_offers_a_way_to_skip_each_setting():
    """Homey always sends every argument — there is no optional — so "unchanged"
    has to be a value. Without it the card could only ever set all five."""
    args = {a["name"]: a for a in _ac_card()["args"]}
    for name in ("power", "mode", "air_purify", "convenient"):
        ids = [v["id"] for v in args[name]["values"]]
        assert ids[0] == "keep", f"{name} has no skip option first"
    assert args["temperature"]["min"] == 0, "temperature has no skip value"


def test_the_combined_card_is_offered_only_for_air_conditioners():
    device = next(a for a in _ac_card()["args"] if a["type"] == "device")
    assert "localthings_ac_mode" in device["filter"]


def test_its_dropdowns_match_the_single_setting_cards():
    """Two places listing the same appliance values is how one comes to offer a
    value the other does not."""
    combined = {a["name"]: a for a in _ac_card()["args"]}
    for arg_name, card in (("mode", "set_ac_mode"), ("convenient", "set_convenient_mode")):
        single = json.loads((FLOW / "actions" / f"{card}.json").read_text())
        expected = [v["id"] for a in single["args"]
                    if a.get("type") == "dropdown" for v in a["values"]]
        got = [v["id"] for v in combined[arg_name]["values"] if v["id"] != "keep"]
        assert got == expected, f"{arg_name} drifted from {card}"


def test_the_steps_are_ordered_so_the_appliance_accepts_them(driver_instance):
    """Mode decides whether a setpoint is accepted at all, so it has to be applied
    before the temperature — the ordering is the fix, not a preference."""
    order = [name for name, _capability, _convert in driver_instance._AC_STEPS]
    assert order.index("power") < order.index("mode")
    assert order.index("mode") < order.index("temperature")


def test_it_refreshes_between_steps(driver_instance):
    """The whole point: a step must see what the previous one actually did."""
    import ast
    source = DRIVER.read_text()
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_on_set_ac_settings"
    )
    body = ast.unparse(function)
    assert body.count("refresh_now") >= 2, (
        "one refresh only — a later step still decides from a stale cache"
    )


def test_it_applies_every_requested_setting_in_order(driver_instance):
    """Skipped fields stay skipped, and the rest arrive in the declared order."""
    import asyncio

    class _Cool:
        def __init__(self):
            self.written = []

        def get_capability_value(self, capability):
            return "Cool" if capability == "localthings_ac_mode" else None

        async def refresh_now(self):
            pass

        async def trigger_capability_listener(self, capability, value):
            self.written.append((capability, value))

    device = _Cool()
    driver_instance.homey = _StubHomey()
    asyncio.run(driver_instance._on_set_ac_settings({
        "device": device, "power": "on", "mode": "keep",
        "temperature": 28.0, "air_purify": "keep", "convenient": "Nano",
    }))
    assert device.written == [
        ("onoff", True),
        ("target_temperature", 28.0),
        ("localthings_convenient_mode", "Nano"),
    ], device.written


class _StubHomey:
    class settings:
        @staticmethod
        def get(key):
            return None

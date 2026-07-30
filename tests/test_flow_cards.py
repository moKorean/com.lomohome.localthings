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


def test_triggers_only_fire_for_cards_that_exist():
    """Resolving a card that was never declared raises. Attempting it for every
    capability would log a failure on every change of the other sixty."""
    source = DEVICE.read_text()
    dispatch = source[source.index("_changed\""):]
    assert "_trigger_cards()" in source
    assert "if card_id in self._trigger_cards()" in source, dispatch[:200]

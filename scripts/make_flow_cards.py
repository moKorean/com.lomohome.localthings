#!/usr/bin/env python3
"""Generate Flow cards for the custom capabilities.

    python3 scripts/make_flow_cards.py [--check]

Homey generates Flow cards for system capabilities only. Everything this app models
itself — 70 capabilities — had none, so none of it could be automated: a Flow could
not switch a hood's light, read a filter's wear, or react to a burner going hot.

Generated rather than written by hand because there are too many to keep consistent
otherwise, and because the titles have to stay in step with the capability
definitions they come from. `--check` fails if the tree is out of date, so a new
capability cannot be added without its cards.

Scope, deliberately not "one of everything":

  action     every setable capability. This is the gap that actually blocks
             automation, so there are no exceptions.
  condition  every capability. Reading a value in a Flow is what makes the sensors
             worth having.
  trigger    only capabilities that mark an event. A trigger per capability would
             double the list with cards nobody wants — "child lock changed" is not
             something a Flow waits for, while "a burner is hot" is.

The card list stays usable despite the count because every device argument carries a
`capabilities=` filter: a card is only offered for appliances that have that
capability, so an air conditioner's picker shows the air conditioner's cards.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
CAPS = APP / ".homeycompose/capabilities"
FLOW = APP / ".homeycompose/flow"

# Cards written by hand, with wording better than a generator can produce. The
# generator leaves these capabilities alone rather than competing with them.
HAND_WRITTEN = {"localthings_display_light"}

# Capabilities whose change is an event a Flow would wait for. Everything else gets
# no trigger: a settings toggle changing is not an event.
#
# That rule had an unstated assumption — that this app is the only thing that changes
# a setting. It is not: these appliances have a physical remote and a panel, so a
# setting moving is genuinely an external event. A user asked for exactly this
# (2026-08-20), wanting to notice somebody picking up the remote and hold their own
# automation off for a while before taking back over. The three air-conditioner
# settings below are the ones that request named.
EVENT_LIKE = {
    "localthings_alarm_hot_surface",
    "localthings_alarm_dustbag",
    "localthings_safety_shutoff",
    "localthings_probe_connected",
    "localthings_firmware_update",
    "localthings_selfcheck",
    "localthings_burner_any_active",
    "localthings_machine_state",
    "localthings_operation_state",
    "localthings_progress",
    "localthings_remaining_minutes",
    # Writable, unlike everything above — see the note on the hint in `_trigger`.
    "localthings_ac_mode",
    "localthings_fan_mode",
    "localthings_wind_direction",
}

# Already covered by hand-written triggers; adding a generic one would fire twice
# for the same change.
TRIGGERED_ELSEWHERE = {
    "localthings_alarm_code",
    "localthings_alarm_filter",
    "localthings_cycle_active",
}

BOOL_STATES = [
    {"id": "on", "title": {"en": "on", "ko": "켜기"}},
    {"id": "off", "title": {"en": "off", "ko": "끄기"}},
]


def short(capability: str) -> str:
    """Card id stem. `localthings_child_lock` -> `child_lock`."""
    return capability[len("localthings_"):] if capability.startswith("localthings_") \
        else capability


def _flow_safe(title: str) -> str:
    """A capability title with parentheses removed but their contents kept.

    Guideline 1.9 forbids parentheses in Flow card titles, and several capability
    titles carry them — "Dust (PM10)". The capability keeps its own title; only the
    card's copy is cleaned, so "Dust PM10" is what a Flow shows.
    """
    return " ".join(title.replace("(", " ").replace(")", " ").split())


def titles(definition: dict) -> tuple[str, str]:
    title = definition.get("title") or {}
    en = title.get("en") or ""
    ko = title.get("ko") or en
    return _flow_safe(en), _flow_safe(ko)


def device_arg(capability: str) -> dict:
    # The filter is what keeps the card list scoped to appliances that have this.
    return {
        "name": "device",
        "type": "device",
        "filter": f"driver_id=appliance&capabilities={capability}",
    }


def value_arg(definition: dict) -> dict:
    """The argument a card needs to carry a value of this capability's type."""
    kind = definition.get("type")
    if kind == "boolean":
        return {"name": "state", "type": "dropdown", "values": BOOL_STATES}
    if kind == "enum":
        return {
            "name": "value",
            "type": "dropdown",
            "values": [
                {"id": v["id"], "title": v.get("title") or {"en": v["id"]}}
                for v in definition.get("values") or []
            ],
        }
    if kind == "number":
        arg = {"name": "value", "type": "number"}
        for key in ("min", "max", "step"):
            if definition.get(key) is not None:
                arg[key] = definition[key]
        return arg
    return {"name": "value", "type": "text"}


def action_card(capability: str, definition: dict) -> dict | None:
    kind = definition.get("type")
    en, ko = titles(definition)
    if kind == "boolean":
        # Korean reads naturally without a particle here: "조명 켜기".
        formatted = {"en": f"Turn {en} [[state]]", "ko": f"{ko} [[state]]"}
        title = {"en": f"Turn {en} on or off", "ko": f"{ko} 켜기 또는 끄기"}
    elif kind in ("enum", "number", "string"):
        # "풍량 설정: 3" avoids the 을/를 choice a generator cannot make reliably.
        formatted = {"en": f"Set {en} to [[value]]", "ko": f"{ko} 설정: [[value]]"}
        title = {"en": f"Set {en}", "ko": f"{ko} 설정"}
    else:
        return None
    return {
        "title": title,
        "titleFormatted": formatted,
        "hint": {
            "en": "Fails the Flow if the appliance refuses the change, rather than "
                  "reporting a success it did not achieve.",
            "ko": "가전이 변경을 거부하면 플로우를 실패로 처리합니다. 이루지 못한 "
                  "성공을 보고하지 않습니다.",
        },
        "args": [device_arg(capability), value_arg(definition)],
    }


def condition_card(capability: str, definition: dict) -> dict | None:
    kind = definition.get("type")
    en, ko = titles(definition)
    unit = (definition.get("units") or {}).get("en") or ""
    if kind == "boolean":
        title = {"en": f"{en} !{{{{is|is not}}}} on", "ko": f"{ko} !{{{{켜짐|꺼짐}}}}"}
        args = [device_arg(capability)]
    elif kind == "number":
        suffix = f" {unit}" if unit else ""
        title = {
            "en": f"{en} !{{{{is|is not}}}} at least [[value]]{suffix}",
            "ko": f"{ko} [[value]]{suffix} !{{{{이상|미만}}}}",
        }
        args = [device_arg(capability), value_arg(definition)]
    elif kind in ("enum", "string"):
        title = {
            "en": f"{en} !{{{{is|is not}}}} [[value]]",
            "ko": f"{ko} [[value]] !{{{{임|아님}}}}",
        }
        args = [device_arg(capability), value_arg(definition)]
    else:
        return None
    return {
        "title": title,
        # Same string: the title already carries its arguments and the !{{|}} toggle,
        # which is what titleFormatted is for. Homey warns when it is absent and says
        # it will become required.
        "titleFormatted": title,
        "hint": {
            "en": "Checks the value as the appliance last reported it.",
            "ko": "가전이 마지막으로 보고한 값을 확인합니다.",
        },
        "args": args,
    }


# Homey fires a Flow trigger by itself when set_capability_value changes a custom
# capability, provided the card is named for it: `<capability>_changed` for a number,
# enum or string, and `<capability>_true` / `<capability>_false` for a boolean. Using
# those ids means no dispatch code at all for plain capabilities.
#
# Safe against firing on every poll because Device._apply only calls the setter when
# the value actually differs, so the convention cannot see a repeat.
def trigger_cards(capability: str, definition: dict) -> dict:
    """{card id: card} — two for a boolean, one for everything else."""
    en, ko = titles(definition)
    kind = definition.get("type")

    if kind == "boolean":
        # An alarm is raised and cleared, not switched on and off. Keyed on the
        # capability's own name rather than a list, so a new alarm gets it for free.
        alarm = capability.startswith("localthings_alarm_")
        on = {"en": f"{en} was raised", "ko": f"{ko} 발생"} if alarm \
            else {"en": f"{en} turned on", "ko": f"{ko} 켜짐"}
        off = {"en": f"{en} cleared", "ko": f"{ko} 해제"} if alarm \
            else {"en": f"{en} turned off", "ko": f"{ko} 꺼짐"}
        return {
            f"{capability}_true": _trigger(capability, definition, on),
            f"{capability}_false": _trigger(capability, definition, off),
        }
    return {
        f"{capability}_changed": _trigger(
            capability, definition,
            {"en": f"{en} changed", "ko": f"{ko} 변경됨"},
            token=True,
        ),
    }


def _trigger(capability: str, definition: dict, title: dict, token: bool = False) -> dict:
    hint_en = ("Fires on a change, not on every reading that repeats the same "
               "value.")
    hint_ko = ("값이 바뀔 때만 실행됩니다. 같은 값을 다시 읽을 때는 실행되지 "
               "않습니다.")
    # A writable setting can be changed by this app, by the remote, or on the
    # appliance's own panel, and the card cannot tell which. Said on the card
    # because the obvious use for it — noticing that somebody picked up the remote
    # — is the one case where that difference is the whole point, and a Flow built
    # without knowing it would retrigger on its own writes forever.
    if definition.get("setable"):
        hint_en += (" It cannot tell who made the change: a Flow of your own, the "
                    "remote, and the appliance's panel all look the same here. To "
                    "act only on someone else's change, compare the value against "
                    "what your Flow last set.")
        hint_ko += (" 누가 바꿨는지는 구분하지 못합니다 — 내 Flow, 리모컨, 가전 "
                    "본체 조작이 모두 똑같이 보입니다. 남이 바꾼 것에만 반응하려면 "
                    "내 Flow가 마지막으로 지정한 값과 비교하세요.")
    card = {
        "title": title,
        "titleFormatted": title,
        "hint": {"en": hint_en, "ko": hint_ko},
        "args": [device_arg(capability)],
    }
    if token:
        en, ko = titles(definition)
        # Named for the capability, which is what Homey fills in automatically.
        card["tokens"] = [{
            "name": capability,
            "type": "string",
            "title": {"en": en or "Value", "ko": ko or "값"},
        }]
    return card


def build() -> dict[str, dict]:
    """{relative path: card} for everything the policy above asks for."""
    cards: dict[str, dict] = {}
    for path in sorted(CAPS.glob("*.json")):
        capability = path.stem
        if capability in HAND_WRITTEN:
            continue
        definition = json.loads(path.read_text())
        stem = short(capability)

        if definition.get("setable"):
            card = action_card(capability, definition)
            if card:
                cards[f"actions/set_{stem}.json"] = card

        card = condition_card(capability, definition)
        if card:
            cards[f"conditions/{stem}_is.json"] = card

        if capability in EVENT_LIKE and capability not in TRIGGERED_ELSEWHERE:
            for card_id, card in trigger_cards(capability, definition).items():
                cards[f"triggers/{card_id}.json"] = card
    return cards


GENERATED_MARKER = "_generated"


def written_paths() -> set[Path]:
    """Generated files currently on disk, tracked by a marker directory listing."""
    index = FLOW / f"{GENERATED_MARKER}.json"
    if not index.is_file():
        return set()
    return {FLOW / rel for rel in json.loads(index.read_text())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the tree does not match")
    options = parser.parse_args()

    cards = build()
    rendered = {
        rel: json.dumps(card, ensure_ascii=False, indent=2) + "\n"
        for rel, card in cards.items()
    }

    if options.check:
        stale = []
        for rel, text in rendered.items():
            path = FLOW / rel
            if not path.is_file() or path.read_text() != text:
                stale.append(rel)
        orphaned = [p for p in written_paths()
                    if str(p.relative_to(FLOW)) not in rendered]
        if stale or orphaned:
            print("flow cards are out of date. run scripts/make_flow_cards.py")
            for rel in sorted(stale):
                print(f"  stale:    {rel}")
            for path in sorted(orphaned):
                print(f"  orphaned: {path.relative_to(FLOW)}")
            return 1
        print(f"flow cards up to date ({len(rendered)} generated)")
        return 0

    # Remove what a previous run wrote but this one does not, so a renamed
    # capability does not leave a card behind pointing at nothing.
    for path in written_paths():
        rel = str(path.relative_to(FLOW))
        if rel not in rendered and path.is_file():
            path.unlink()
            print(f"  removed {rel}")

    for rel, text in sorted(rendered.items()):
        path = FLOW / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    (FLOW / f"{GENERATED_MARKER}.json").write_text(
        json.dumps(sorted(rendered), ensure_ascii=False, indent=2) + "\n"
    )

    kinds: dict[str, int] = {}
    for rel in rendered:
        kinds[rel.split("/")[0]] = kinds.get(rel.split("/")[0], 0) + 1
    for kind, count in sorted(kinds.items()):
        print(f"  {kind}: {count}")
    print(f"  total: {len(rendered)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

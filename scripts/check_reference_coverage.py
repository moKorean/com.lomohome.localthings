#!/usr/bin/env python3
"""Report what the reference integration supports that this port does not.

Run after pulling ../localthings-reference to see whether upstream has added an
appliance type, a board-family token, or an OCF device type. Compares the routing
tables directly rather than relying on release notes, so one added quietly still
shows up.

The OCF table was not compared for the first several months this script existed,
and on 2026-08-10 the reference was found four entries ahead — `oic.d.range`,
`oic.d.krefrigerator`, `x.com.st.d.dehumidifier` and `x.com.st.d.winecellar` —
while this script printed "no gaps". Every table routing decisions are made from
has to be in here, or the report is about the part nobody forgot.

    python3 scripts/check_reference_coverage.py

Exits 1 when anything is missing, so it can gate CI if wanted.

Divergences this port has decided on are declared below rather than tolerated
silently. An entry there is a promise somebody wrote down a reason; anything not
listed still fails, and an entry that stops applying fails too, so the allowance
cannot quietly become a blanket.
"""

import ast
import importlib
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REFERENCE = HERE.parent / "localthings-reference"

# Appliance types the reference supports and this port deliberately does not, each
# with the reason. Dropping a type in here is a decision, not a backlog entry —
# docs/BACKLOG.md carries what would change it.
UNPORTED_TYPES: dict[str, str] = {
    "soundbar": (
        "35 /sec/networkaudio/* resources and a discovery path for boards that "
        "serve no /device/0 at all; not an appliance, and none here to measure"
    ),
    "robot_vacuum": "POWERbot R7040; no unit here, nothing to verify a mapping against",
}

# Board tokens this port routes somewhere other than the reference does.
DIVERGENT_TOKENS: dict[str, str] = {
    "COOKTOP": (
        "the reference merged its induction and options-array cooktops into one "
        "registry named for the OCF type. Both are kept apart here because only "
        "the induction mapping is measured against hardware in this house. "
        "registry._cooktop_surface_key makes the same split on /cooktop/status/vs/0, "
        "so a device still lands on the right surface — only the name differs"
    ),
}


def load_reference_tables():
    """Import the reference's by_type package without pulling in Home Assistant.

    localthings/__init__.py imports HA, so the parent packages are stubbed and the
    submodule imported directly — the same trick the reference's own
    adding-device-support notes use.
    """
    root = REFERENCE / "custom_components" / "localthings"
    if not root.is_dir():
        sys.exit(
            f"Reference checkout not found at {REFERENCE}.\n"
            "Clone it next to this repo:\n"
            "  git clone https://github.com/mbillow/localthings.git "
            f"{REFERENCE.name}"
        )
    sys.path.insert(0, str(REFERENCE))
    for name, path in (
        ("custom_components", REFERENCE / "custom_components"),
        ("custom_components.localthings", root),
    ):
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module

    # by_type/__init__ imports every registry, which drags in the HA-coupled
    # entity layer. The tables are plain literals, so read them from source
    # instead of importing.
    source = (root / "registry" / "by_type" / "__init__.py").read_text()
    tokens = _parse_dict(source, "_BOARD_TOKEN_TO_KEY")
    consumer = _parse_dict(source, "_CONSUMER_PREFIX_TO_KEY")
    keys = set(_parse_dict(source, "_REGISTRY_BY_KEY", values=False))
    oic = _parse_dict(source, "_OIC_TYPE_TO_KEY")
    return tokens, consumer, keys, oic


def _parse_dict(source: str, name: str, values: bool = True) -> dict:
    """Pull a module-level dict literal out of source, with the parser.

    This was a regex over the source text, and it stopped working silently when
    the reference reformatted with ruff: its string literals went from `'REF'` to
    `"REF"`, the pattern matched nothing, and every table came back empty — so
    this script reported full coverage while comparing against nothing. Quoting
    and line breaks are formatting; the AST does not see them.

    A value that is not a literal (`air_dresser.REGISTRY` in `_REGISTRY_BY_KEY`)
    keeps its key, since only the keys are wanted there.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
        if target != name or not isinstance(node.value, ast.Dict):
            continue
        found = {}
        for key, value in zip(node.value.keys, node.value.values, strict=True):
            if not isinstance(key, ast.Constant):
                continue
            found[key.value] = (
                value.value if isinstance(value, ast.Constant) else None
            )
        if not found:
            raise SystemExit(f"{name} parsed as empty — has it been restructured?")
        return found if values else {k: None for k in found}
    raise SystemExit(f"{name} not found in the reference — has it been renamed?")


def main() -> int:
    sys.path.insert(0, str(HERE))
    ours = importlib.import_module("lib.registry")

    ref_tokens, ref_consumer, ref_keys, ref_oic = load_reference_tables()
    our_tokens = dict(ours._BOARD_TOKEN_TO_KEY)
    our_keys = set(ours._REGISTRY_BY_KEY)
    our_oic = dict(ours._OIC_TYPE_TO_KEY)

    missing_types = sorted(ref_keys - our_keys)
    missing_tokens = sorted(t for t in ref_tokens if t not in our_tokens)
    extra_tokens = sorted(t for t in our_tokens if t not in ref_tokens)
    misrouted = sorted(
        f"{t}: reference={ref_tokens[t]} ours={our_tokens[t]}"
        for t in ref_tokens
        if t in our_tokens and ref_tokens[t] != our_tokens[t]
    )

    missing_oic = sorted(t for t in ref_oic if t not in our_oic)
    misrouted_oic = sorted(
        f"{t}: reference={ref_oic[t]} ours={our_oic[t]}"
        for t in ref_oic
        if t in our_oic and ref_oic[t] != our_oic[t]
    )
    # Ours-only OCF types are deliberate: `oic.d.cooktop` is excluded here on
    # purpose (see lib/registry/__init__.py), so an extra is not reported as a gap.

    print(f"reference: {len(ref_keys)} types, {len(ref_tokens)} board tokens, "
          f"{len(ref_oic)} OCF types")
    print(f"ours:      {len(our_keys)} types, {len(our_tokens)} board tokens, "
          f"{len(our_oic)} OCF types\n")

    if missing_types:
        print(f"appliance types not ported ({len(missing_types)}):")
        for key in missing_types:
            tokens = sorted(t for t, k in ref_tokens.items() if k == key)
            prefixes = sorted(p for p, k in ref_consumer.items() if k == key)
            hint = ", ".join(tokens + [f"{p}*" for p in prefixes]) or "resource signature only"
            print(f"  {key:<20} tokens: {hint}")
        print()

    if missing_tokens:
        print(f"board tokens the reference routes and we do not ({len(missing_tokens)}):")
        for token in missing_tokens:
            key = ref_tokens[token]
            state = "type ported" if key in our_keys else "type NOT ported"
            print(f"  {token:<16} -> {key} ({state})")
        print()

    if missing_oic:
        print(f"OCF device types the reference routes and we do not ({len(missing_oic)}):")
        for oic_type in missing_oic:
            key = ref_oic[oic_type]
            state = "type ported" if key in our_keys else "type NOT ported"
            print(f"  {oic_type:<28} -> {key} ({state})")
        print()

    if misrouted_oic:
        print("OCF types routed differently — check before trusting either:")
        for line in misrouted_oic:
            print(f"  {line}")
        print()

    if misrouted:
        print("tokens routed differently — check before trusting either:")
        for line in misrouted:
            print(f"  {line}")
        print()

    if extra_tokens:
        # Ours-only tokens are contributions upstream hasn't taken yet, not gaps.
        print(f"tokens we route that the reference does not ({len(extra_tokens)}):")
        for token in extra_tokens:
            print(f"  {token} -> {our_tokens[token]}   (worth contributing upstream)")
        print()

    # Declared divergences are reported but do not fail. An OCF type is covered by
    # its own type's allowance: with the type unported there is nothing to route to.
    allowed_types = [k for k in missing_types if k in UNPORTED_TYPES]
    allowed_oic = [t for t in missing_oic if ref_oic[t] in UNPORTED_TYPES]
    allowed_misrouted = [
        line for line in misrouted if line.split(":", 1)[0] in DIVERGENT_TOKENS
    ]
    if allowed_types or allowed_oic or allowed_misrouted:
        print("declared divergences (not failures):")
        for key in allowed_types:
            print(f"  type {key} — {UNPORTED_TYPES[key]}")
        for oic_type in allowed_oic:
            print(f"  oic  {oic_type} — its type {ref_oic[oic_type]} is unported above")
        for line in allowed_misrouted:
            token = line.split(":", 1)[0]
            print(f"  token {token} — {DIVERGENT_TOKENS[token]}")
        print()

    # A declaration that no longer applies is itself a failure: the type got ported,
    # or the routing came back into line, and the allowance is now hiding nothing
    # while looking like it still earns its place.
    stale = [k for k in UNPORTED_TYPES if k in our_keys]
    stale += [
        t for t in DIVERGENT_TOKENS
        if t not in {line.split(":", 1)[0] for line in misrouted}
    ]
    if stale:
        print("declared divergences that no longer apply — remove them:")
        for name in stale:
            print(f"  {name}")
        print()
        return 1

    unexplained = (
        [k for k in missing_types if k not in UNPORTED_TYPES]
        + missing_tokens
        + [t for t in missing_oic if ref_oic[t] not in UNPORTED_TYPES]
        + [line for line in misrouted if line.split(":", 1)[0] not in DIVERGENT_TOKENS]
        + misrouted_oic
    )
    if not unexplained:
        print("no undeclared gaps: everything else the reference routes is routed here.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

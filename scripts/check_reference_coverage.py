#!/usr/bin/env python3
"""Report what the reference integration supports that this port does not.

Run after pulling ../localthings-reference to see whether upstream has added an
appliance type or a board-family token. Compares the two routing tables directly
rather than relying on release notes, so a token added quietly still shows up.

    python3 scripts/check_reference_coverage.py

Exits 1 when anything is missing, so it can gate CI if wanted.
"""

import importlib
import re
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REFERENCE = HERE.parent / "localthings-reference"


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
    return tokens, consumer, keys


def _parse_dict(source: str, name: str, values: bool = True) -> dict:
    """Pull `name = { 'a': 'b', ... }` out of source, ignoring comments."""
    match = re.search(
        rf"^{re.escape(name)}[^=]*=\s*\{{(.*?)^\}}", source, re.DOTALL | re.MULTILINE
    )
    if not match:
        return {}
    body = re.sub(r"#[^\n]*", "", match.group(1))
    pairs = re.findall(r"'([^']+)'\s*:\s*([\w.']+)", body)
    if not values:
        return {key: None for key, _ in pairs}
    return {key: val.strip("'") for key, val in pairs}


def main() -> int:
    sys.path.insert(0, str(HERE))
    ours = importlib.import_module("lib.registry")

    ref_tokens, ref_consumer, ref_keys = load_reference_tables()
    our_tokens = dict(ours._BOARD_TOKEN_TO_KEY)
    our_keys = set(ours._REGISTRY_BY_KEY)

    missing_types = sorted(ref_keys - our_keys)
    missing_tokens = sorted(t for t in ref_tokens if t not in our_tokens)
    extra_tokens = sorted(t for t in our_tokens if t not in ref_tokens)
    misrouted = sorted(
        f"{t}: reference={ref_tokens[t]} ours={our_tokens[t]}"
        for t in ref_tokens
        if t in our_tokens and ref_tokens[t] != our_tokens[t]
    )

    print(f"reference: {len(ref_keys)} types, {len(ref_tokens)} board tokens")
    print(f"ours:      {len(our_keys)} types, {len(our_tokens)} board tokens\n")

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

    if not (missing_types or missing_tokens or misrouted):
        print("no gaps: every reference type and token is routed here.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

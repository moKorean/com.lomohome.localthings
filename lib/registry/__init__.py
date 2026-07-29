"""Appliance-type detection.

Ported from the reference integration's registry/by_type/__init__.py, keeping its
central property: there is no per-model descriptor. The board named in
`modelNum` determines the resource surface, which is what a registry describes,
so a new unit of an already-supported type binds with no code change.

Only the air conditioner is ported so far; the remaining types are mechanical
additions (docs/PORTING.md milestone 7).
"""

import re
from typing import Optional

from . import airconditioner
from .base import Registry
from ..resources import read_identity

_REGISTRY_BY_KEY: dict[str, Registry] = {
    "airconditioner": airconditioner.REGISTRY,
}

# Board-family token -> registry key, matched against whole tokens of
# modelNum/description.
#
# Tokenising rather than substring-matching is what keeps this a table instead of
# a ladder of rules: Samsung spells the same family with either delimiter
# ('TP1X_DA-AC-RAC-01001' and 'TP2X_RAC_20K' are both RAC), so a substring rule
# needs writing once per spelling.
#
# Entries must name the *specific* device type, never the family containing it:
# 'DA-AC-' prefixes RAC/WAC/DHM/AIR alike, so a bare 'AC' entry would swallow the
# dehumidifier and the air purifier once those are ported.
_BOARD_TOKEN_TO_KEY: dict[str, str] = {
    token: "airconditioner" for token in airconditioner.BOARD_TOKENS
}

_TOKEN_SPLIT_RE = re.compile(r"[^A-Z0-9]+")


def _board_tokens(value: str, cut_at: str) -> list[str]:
    """Whole upper-cased tokens of `value` up to the first `cut_at`.

    `cut_at` drops the trailing junk each field carries — everything after
    modelNum's first '|' (a board revision and a capability bitmap, which can
    contain anything) and after description's first '/' (a board part number).
    """
    head = (value or "").split(cut_at, 1)[0].upper()
    return [t for t in _TOKEN_SPLIT_RE.split(head) if t]


def _board_family_key(value: str, cut_at: str) -> Optional[str]:
    for token in _board_tokens(value, cut_at):
        key = _BOARD_TOKEN_TO_KEY.get(token)
        if key is not None:
            return key
    return None


def resolve(resources: dict) -> Optional[Registry]:
    """Registry for a parsed /device/0 dump, or None if unrecognised.

    modelNum first, then description — a device whose two fields disagree is
    typed by its board, which is the field that determines the resource surface.
    """
    identity = read_identity(resources)
    key = _board_family_key(identity["model"], "|") or _board_family_key(
        identity["description"], "/"
    )
    return _REGISTRY_BY_KEY.get(key) if key else None


def unbound_hrefs(resources: dict, registry: Registry) -> list[str]:
    """Resources no Spec reads — the coverage gap for this unit."""
    bound = {spec.href for spec in registry.specs}
    return sorted(h for h in resources if h not in bound)

"""Appliance-type detection.

Ported from the reference integration's registry/by_type/__init__.py, keeping its
central property: there is no per-model descriptor. The board named in
`modelNum` determines the resource surface, which is what a registry describes,
so a new unit of an already-supported type binds with no code change.

All of the reference's appliance types are routed. The air conditioner and induction
cooktop are verified against real hardware and live in their own modules; the rest are
in appliances.py, ported from the reference's field definitions and unverified — see
that module's docstring.
"""

import re

from ..resources import read_identity
from . import airconditioner, appliances, induction_cooktop
from .base import Registry

_REGISTRY_BY_KEY: dict[str, Registry] = {
    "airconditioner": airconditioner.REGISTRY,
    "induction_cooktop": induction_cooktop.REGISTRY,
    **{
        registry.name: registry
        for registry in (
            *appliances.BOARD_TOKENS.values(),
            *appliances.CONSUMER_PREFIXES.values(),
        )
    },
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
    **{token: "airconditioner" for token in airconditioner.BOARD_TOKENS},
    **{token: "induction_cooktop" for token in induction_cooktop.BOARD_TOKENS},
    **{token: registry.name for token, registry in appliances.BOARD_TOKENS.items()},
}

# Consumer-model prefix -> registry key, matched against the start of a
# '_'-delimited segment of `description`. Consulted only after the board tokens: a
# two-letter prefix is the fuzziest evidence available, and 'WAC' (window air
# conditioner) also starts with 'WA' (top-load washer), so it must never outrank a
# specific board token.
_CONSUMER_PREFIX_TO_KEY: dict[str, str] = {
    prefix: registry.name
    for prefix, registry in appliances.CONSUMER_PREFIXES.items()
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


def _board_family_key(value: str, cut_at: str) -> str | None:
    """The table is a flat lookup, not a priority list, so the token order within
    a modelNum must not decide the answer.

    One documented exception (reference #196): AILITE water purifiers spell their
    modelNum '...-REF-WATERPURIFIER-...', where 'REF' names the shared cooling
    board rather than the device type. Both tokens are in the table and both are
    correct on their own, so scanning in order silently routed these to the
    refrigerator — measured, not assumed: before this carve-out
    'AILITE_DA-REF-WATERPURIFIER-24-COMMON' resolved to the fridge registry and
    would have been given door alarms and compartment setpoints. 'WATERPURIFIER'
    is the more specific of the two, so this one known co-occurrence resolves to
    it.
    """
    tokens = _board_tokens(value, cut_at)
    if "REF" in tokens and "WATERPURIFIER" in tokens:
        return "water_purifier"
    for token in tokens:
        key = _BOARD_TOKEN_TO_KEY.get(token)
        if key is not None:
            return key
    return None


def _consumer_model_key(description: str) -> str | None:
    """Registry key from the consumer-model token in `description`.

    Segments are scanned from the end rather than assuming the last is the model: the
    reference documents a dryer whose description pairs two model numbers
    ('..._DVE50A8800_8600'), leaving the real token one segment before the last.

    Splits on '_' only. Widening to '-' would start reading board-family segments as
    consumer models — a dishwasher's 'ADW-WW-RTL-24' would offer a bare 'WW' and
    route to washer.
    """
    segments = (description or "").split("/", 1)[0].split("_")
    for segment in reversed(segments):
        key = _CONSUMER_PREFIX_TO_KEY.get(segment[:2].upper())
        if key is not None:
            return key
    return None


# `/oic/d`'s `rt` — the appliance naming its own OCF device type — to registry key.
# Consulted before any board-part-number parsing, because there is nothing to infer:
# the device is stating what it is.
#
# Measured on this house's nine appliances, all of which populate it:
#
#     4 air conditioners   oic.d.airconditioner
#     3 refrigerators      oic.d.refrigerator
#     1 induction cooktop  oic.d.cooktop        (deliberately absent — see below)
#     1 range hood         x.com.st.d.hood
#
# Every one agreed with what the board token already concluded, so this changes
# nothing here. It earns its place on *other* people's hardware: an unfamiliar
# modelNum currently ends as "unsupported appliance", and this is a second,
# independent way to type the same unit.
#
# `x.com.st.d.*` is SmartThings' vendor extension for categories OCF never gave an
# `oic.d.*` name, the same convention as the `x.com.samsung.da.*` resource fields.
#
# Kept as narrow as the board-token table: every entry is either measured here or
# carried over from the reference, never a guess at what the OCF vocabulary might
# contain.
#
# **`oic.d.cooktop` is excluded on purpose.** Our induction reports it, but
# `cooktop` and `induction_cooktop` are two unrelated registries that happen to
# share the English word — a gas cooktop's burner state lives in `/mode/vs/0`'s
# options array, a completely different resource surface. Nothing in the OCF type
# distinguishes them, so mapping it to either one would silently mis-type the
# other, and as the *primary* signal it would override a board token that had it
# right. The board token keeps deciding between those two.
_OIC_TYPE_TO_KEY: dict[str, str] = {
    "oic.d.airconditioner": "airconditioner",   # measured: 4 units
    "oic.d.refrigerator": "refrigerator",       # measured: 3 units
    "x.com.st.d.hood": "range_hood",            # measured: 1 unit
    "x.com.st.d.airqualitysensor": "air_monitor",
    # From the reference's own table; our keys for these already match.
    "oic.d.airpurifier": "air_purifier",
    "oic.d.dishwasher": "dishwasher",
    "oic.d.dryer": "dryer",
    "oic.d.oven": "oven",
    "oic.d.washer": "washer",
    "x.com.st.d.stickcleaner": "vacuum_station",
    "x.com.st.d.steamcloset": "air_dresser",
}


def _oic_type_key(device_types) -> str | None:
    for device_type in device_types or ():
        key = _OIC_TYPE_TO_KEY.get(str(device_type))
        if key is not None:
            return key
    return None


def resolve(resources: dict, device_types=()) -> Registry | None:
    """Registry for a parsed /device/0 dump, or None if unrecognised.

    `device_types` is `/oic/d`'s `rt`, which has to be read separately — it is
    absent from every `/device/0` batch response. When it names a type we know, it
    wins: the appliance is declaring what it is, rather than us parsing a board
    part number out of a model string.

    Then narrowest evidence first, unchanged: the board token in `modelNum`, then
    the same token in `description` (some units carry it only there), then the
    consumer-model prefix. A device whose fields disagree is typed by its board,
    which is what determines the resource surface.
    """
    identity = read_identity(resources)
    key = (
        _oic_type_key(device_types)
        or _board_family_key(identity["model"], "|")
        or _board_family_key(identity["description"], "/")
        or _consumer_model_key(identity["description"])
    )
    return _REGISTRY_BY_KEY.get(key) if key else None


def unbound_hrefs(resources: dict, registry: Registry) -> list[str]:
    """Resources no Spec reads — the coverage gap for this unit."""
    bound = {spec.href for spec in registry.specs}
    return sorted(h for h in resources if h not in bound)

"""Envelope translation for the 2018-2022 appliances that serve TCP 8888.

These boards speak no OCF at all. They answer a small REST bridge on
`/devices/0/<endpoint>` with **bare field names** and PascalCase wrappers,
where the CoAP boards carry `x.com.samsung.da.*` fields on `/<path>/vs/0`
hrefs. The vocabulary underneath is the same one — the same `options` arrays,
the same `Course_XX` tokens, the same `supportedModes` — so translating the
envelope is enough to hand the whole of `lib/registry/` a device it already
knows how to read.

Pure: no sockets, no Homey. Two mechanical rules carry it — a field takes the
vendor prefix, and a wrapper lands on the canonical href its fields belong in —
and every exception is a row in `RESOURCES`. A wrapper with no row translates
nothing, which is why `unmapped_wrappers` exists: it names what a new row
would have to cover rather than letting the gap go unseen.

**Read-only, and that is the whole of this first cut.** The reference's module
also stages a cycle and the washer's settings to be sent with a start, because
this firmware answers `204` to them on their own and then discards them. None
of that is here. Writes to these boards have never been exercised from this
app, and this repository has removed three controls that a board accepted and
ignored — the induction hob's power, the fridge's AI Energy mode, the air
conditioner's Purify. Shipping a fourth kind blind, on a transport nobody here
can reach, is the one outcome worse than not pairing at all.

What this does buy is verifiable today. The reference committed twenty-five
8888 captures, raw bodies and translated hrefs both, so every mapping below is
checked end to end against a real appliance's own words in
`tests/test_legacy_bridge.py` — the same standard as the fourteen CoAP types
nobody here owns.

Deliberately out of this module, each because it needs something we do not
have yet:

- the divided oven's cavities (`/devices/<n>` siblings) — there is no
  subdevice concept in this app at all
- `model_settings`, which reads a remote-power-control bit out of modelID —
  it only decides whether a *write* is offered
- the panel-unit fix-up a sibling needs from the main unit, for the same
  reason as the cavities

`docs/BACKLOG.md` carries all three with what would settle them.
"""

import re
from dataclasses import dataclass, field
from typing import Any

# The prefix every OCF-side field carries and no 8888-side field does.
PREFIX = "x.com.samsung.da."


@dataclass(frozen=True)
class Resource:
    """One 8888 wrapper and where its fields belong on the OCF side.

    `endpoint` is the path segment under `/devices/0/`, which the transport
    needs to read one resource on its own; `wrapper` is the PascalCase key the
    same resource takes inside the aggregate body.

    `fan_out` and `rename` are the exception tables: a field named in `fan_out`
    lands on that href instead of `href`, and one named in `rename` lands under
    that name instead of its own. Anything named in neither is mechanical.
    """

    endpoint: str
    wrapper: str
    href: str
    fan_out: dict = field(default_factory=dict)
    rename: dict = field(default_factory=dict)
    # True where the appliance serves a bare JSON list and the OCF side carries
    # it as an `items` array — `/alarms/vs/0` on any CoAP dump here.
    as_items: bool = False
    # List fields this firmware packs into one comma-joined string, which the
    # OCF side carries one value per entry.
    joined: frozenset = frozenset()


INFORMATION = Resource(
    endpoint="information",
    wrapper="Information",
    href="/information/vs/0",
    rename={"modelID": "modelNum", "serialNumber": "serialNum"},
)

# Where each wrapper lands. The names are one vocabulary on every 8888
# appliance on record, and each field goes where the CoAP boards keep it:
# power and the child lock on hrefs of their own, the rest of Operation on the
# operational state.
RESOURCES: tuple[Resource, ...] = (
    Resource(
        endpoint="operation",
        wrapper="Operation",
        href="/operational/state/vs/0",
        fan_out={"power": "/power/vs/0", "kidsLock": "/kidslock/vs/0"},
    ),
    Resource(endpoint="mode", wrapper="Mode", href="/mode/vs/0",
             joined=frozenset({"supportedModes"})),
    Resource(endpoint="washer", wrapper="Washer", href="/washer/vs/0"),
    Resource(endpoint="oven", wrapper="Oven", href="/oven/vs/0"),
    # The DONGLE_0281 fridge's rapid-cool flags, where the CoAP fridges keep
    # them (reference #698).
    Resource(endpoint="fridge", wrapper="Fridge", href="/refrigeration/vs/0"),
    Resource(endpoint="temperatures", wrapper="Temperatures",
             href="/temperatures/vs/0", as_items=True),
    Resource(endpoint="doors", wrapper="Doors", href="/doors/vs/0", as_items=True),
    # Wind is `/airflow/vs/0` on the ARTIK051 air conditioners, not
    # `/wind/strength/vs/0`.
    Resource(endpoint="wind", wrapper="Wind", href="/airflow/vs/0"),
    Resource(endpoint="configuration", wrapper="Configuration", href="/remotectrl/vs/0"),
    INFORMATION,
    Resource(endpoint="diagnosis", wrapper="Diagnosis", href="/diagnosis/vs/0"),
    Resource(endpoint="alarms", wrapper="Alarms", href="/alarms/vs/0", as_items=True),
    # The TP6X_VTL_16K purifier's readings, in the CoAP purifiers' shape; its
    # sensors name their reading list `values` where the others say `value`.
    Resource(endpoint="sensors", wrapper="Sensors", href="/sensors/vs/0",
             as_items=True, rename={"values": "value"}),
    Resource(endpoint="consumables", wrapper="Consumables",
             href="/consumable/vs/0", as_items=True),
)

# A washer's or dryer's Mode is its *cycle*, which CoAP laundry serves as
# `/course/vs/0`. Routing it to `/mode/vs/0` would put a cycle token where the
# registry looks for an operating mode.
_LAUNDRY = (
    Resource(endpoint="mode", wrapper="Mode", href="/course/vs/0"),
)

# A Configuration holding only the region. On `/remotectrl/vs/0` the missing
# `remoteControlEnabled` would read as Smart Control **off**, which is not a
# cosmetic difference — it is the flag the whole app checks before touching an
# appliance (reference #563).
_REGION_CONFIGURATION = (
    Resource(endpoint="configuration", wrapper="Configuration", href="/configuration/vs/0"),
)

# Wrappers a device type keeps somewhere else, keyed by the `type` its own
# record reports.
_BY_TYPE: dict[str, tuple[Resource, ...]] = {
    "Washer": _LAUNDRY,
    "Dryer": _LAUNDRY,
    "Air_Conditioner": _REGION_CONFIGURATION,
    "Air_Purifier": _REGION_CONFIGURATION,
    "Refrigerator": _REGION_CONFIGURATION,
}


def table_for(device_type: str | None) -> tuple[Resource, ...]:
    """The resource table for an appliance whose record reports `device_type`."""
    overrides = {r.wrapper: r for r in _BY_TYPE.get(device_type or "", ())}
    return tuple(overrides.get(r.wrapper, r) for r in RESOURCES)


def _canonical_name(name: str, rename: dict) -> str:
    return PREFIX + rename.get(name, name)


def _canonical_value(value: Any, rename: dict) -> Any:
    """Prefix nested maps too — an alarms entry is itself a map of bare field
    names on the wire and of prefixed ones on the OCF side."""
    if isinstance(value, dict):
        return {_canonical_name(k, rename): _canonical_value(v, rename) for k, v in value.items()}
    if isinstance(value, list):
        return [_canonical_value(v, rename) for v in value]
    return value


def _split_joined(value: Any) -> Any:
    """`["a,b,a"]` -> `["a", "b"]`: split, trimmed, first occurrence kept."""
    if not isinstance(value, list):
        return value
    out: list = []
    for entry in value:
        parts = entry.split(",") if isinstance(entry, str) else [entry]
        for part in parts:
            part = part.strip() if isinstance(part, str) else part
            if part != "" and part not in out:
                out.append(part)
    return out


def unwrap(*responses: dict) -> dict:
    """The appliance's responses -> the wrapper-keyed mapping `to_resources` takes.

    Three shapes turn up: the aggregate `{"Device": {...}}`, its plural
    `{"Devices": [{...}]}` from `/devices`, and a single resource's own
    `{"Configuration": {...}}`. The aggregate's non-resource keys (`connected`,
    `description`, the `*Link` entries) are kept and dropped later by
    `to_resources`, since no table row names them.
    """
    out: dict = {}
    for response in responses:
        if not isinstance(response, dict):
            continue
        device = response.get("Device")
        if device is None:
            devices = response.get("Devices")
            if isinstance(devices, list) and devices:
                device = devices[0]
        out.update(device if isinstance(device, dict) else response)
    return out


def to_resources(bodies: dict, table: tuple[Resource, ...]) -> dict[str, dict]:
    """Wrapper-keyed 8888 bodies -> `{canonical href: rep}`.

    A wrapper the appliance did not report is simply absent from the result,
    exactly as an href a `/device/0` batch did not carry — which is what makes
    every `Spec.applies` gate in the registry work unchanged on these boards.
    """
    out: dict[str, dict] = {}
    for resource in table:
        body = bodies.get(resource.wrapper)
        if body is None:
            continue
        if resource.as_items:
            if not isinstance(body, list):
                continue
            out[resource.href] = {
                PREFIX + "items": [_canonical_value(item, resource.rename) for item in body]
            }
            continue
        if not isinstance(body, dict):
            continue
        for name, value in body.items():
            if name in resource.joined:
                value = _split_joined(value)
            href = resource.fan_out.get(name, resource.href)
            out.setdefault(href, {})[_canonical_name(name, resource.rename)] = _canonical_value(
                value, resource.rename
            )
    return out


def unmapped_wrappers(bodies: dict, table: tuple[Resource, ...]) -> list[str]:
    """Wrappers the appliance reported that `table` has no row for.

    The 8888 equivalent of `registry.unbound_hrefs`: what a new row would have
    to cover. Links and the aggregate's own scalars are not resources.
    """
    named = {r.wrapper for r in table}
    return sorted(
        key for key, body in bodies.items()
        if key[:1].isupper()
        and not key.endswith("Link")
        and isinstance(body, dict | list)
        and key not in named
    )


# Record types that stand in for a missing `deviceSubType`. The DONGLE_0281
# fridge, DONGLE_DRY dryer and DONGLE_WM washer report only their record's
# `type`. Other types stay out on purpose: a hood slot's record says
# `Cooktop`, and as a subtype that would outrank the board token that types it.
_RECORD_TYPE_AS_SUBTYPE = frozenset({"Dryer", "Refrigerator", "Washer"})


def with_record_type(bodies: dict, device_type: str | None) -> dict:
    """`bodies` with the record's own `type` as its Information's
    `deviceSubType`, where it names none — that field is what routing reads."""
    information = bodies.get("Information")
    if (
        device_type not in _RECORD_TYPE_AS_SUBTYPE
        or not isinstance(information, dict)
        or information.get("deviceSubType")
    ):
        return dict(bodies)
    return {**bodies, "Information": {**information, "deviceSubType": device_type}}


# Where the cycle catalog reads a washer's course-table id.
COURSE_TABLE_HREF = "/st/washercourse/vs/0"
_COURSE_TABLE_FIELD = PREFIX + "st.courseTable"

# This family serves no `/st/washercourse/vs/0`, so its table is declared per
# family rather than read. TP6X_WASHER is Table_00: upstream walked a WW6500's
# dial through all fourteen panel positions and the codes matched the existing
# Table_00 catalog on thirteen of them, the fourteenth by elimination.
#
# A family that is not here reads raw course codes rather than a borrowed
# catalog — the two laundry families share table ids and disagree on most of
# them, so guessing would name a cycle out of the wrong generation's list.
FAMILY_COURSE_TABLES: dict[str, str] = {"TP6X_WASHER": "Table_00"}

_CAPACITY = re.compile(r"_\d+K$")


def family_key(family: str | None) -> str:
    """The family name without its capacity suffix (`TP6X_WASHER_16K` ->
    `TP6X_WASHER`), which is what varies per unit rather than per generation."""
    return _CAPACITY.sub("", family or "")


def course_table(family: str | None) -> dict[str, dict]:
    """A `/st/washercourse/vs/0` rep for `family`, or empty for a family
    nobody has walked the dial on."""
    table = FAMILY_COURSE_TABLES.get(family_key(family))
    return {COURSE_TABLE_HREF: {_COURSE_TABLE_FIELD: table}} if table else {}


def resources_for(bodies: dict, device_type: str | None = None) -> dict[str, dict]:
    """Everything the registry needs for one 8888 appliance, from its bodies.

    The whole of the read path in one call: the record's type filled in where
    the board names no subtype, the wrappers translated, and the course table
    added for a family that declares one.
    """
    device_type = device_type or bodies.get("type")
    bodies = with_record_type(bodies, device_type)
    resources = to_resources(bodies, table_for(device_type))
    information = resources.get("/information/vs/0") or {}
    resources.update(course_table(information.get(PREFIX + "description")))
    return resources

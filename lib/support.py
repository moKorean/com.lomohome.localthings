"""Build the report a user sends when an appliance is not supported yet.

Adding support for an appliance type needs its /device/0: the resource paths, the
field names, and the advertised value lists. Guessing those instead produced a range
hood that paired and then controlled nothing, because every guessed name missed.

What it does not need is which particular unit it came from. A serial number is the
appliance's identity and it feeds the Homey device id; there is no reason for it to
travel to an issue tracker, so it is replaced before the report is ever shown. The
redaction happens here rather than in the view because a webview is the wrong place
to be trusted with it, and because it needs testing.
"""

import json
import re

# Fields naming one unit or one household rather than one model, taken from every
# resource dump available rather than from what sounded plausible: an earlier version
# of this list matched `macaddress` exactly and so missed the real field names,
# `macaddressBLE` and `macaddressWiFi`, and had no entry at all for
# `connectedApSsid` — which is the name of the user's wireless network.
#
# Prefixes, because the vendor suffixes its own fields (serialNum, serialNumOption).
# Exact matches only where a prefix would swallow unrelated fields: `mac` as a prefix
# would take `machineState`.
_UNIT_FIELD_PREFIXES = (
    "serialnum",     # serialNum, serialNumOption
    "serialnumber",
    "macaddress",    # macaddressBLE, macaddressWiFi
    "otnduid",
    "connectedapssid",
)
_UNIT_FIELD_EXACT = (
    "serial",
    "mac",
    "deviceid",
    "ipaddress",
    "uuid",
    "di",
)

# Deliberately kept: modelId, micomModelId, diagMnid, diagSetupid and diagTsId name
# the model or its service endpoints, not the unit, and are useful when adding support.
# `id` is a row index inside a list. `timezoneid` says nothing a locale does not.

REDACTED = "<redacted>"

# modelNum is 'MODEL-TOKEN|productCode|boardId'. The token is what routing needs and
# the product code is per-model, but the trailing board id is per-unit.
_MODEL_NUM = re.compile(r"^([^|]*\|[^|]*\|).+$")


def _is_unit_field(name: str) -> bool:
    tail = str(name).rsplit(".", 1)[-1].lower()
    return tail in _UNIT_FIELD_EXACT or tail.startswith(_UNIT_FIELD_PREFIXES)


def redact(value):
    """Deep copy of `value` with per-unit identifiers replaced."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if _is_unit_field(key):
                out[key] = REDACTED if item not in (None, "", [], {}) else item
            elif str(key).rsplit(".", 1)[-1].lower() == "modelnum" and isinstance(item, str):
                out[key] = _MODEL_NUM.sub(rf"\1{REDACTED}", item)
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def report(resources: dict, *, model: str, port=None, app_version=None) -> str:
    """The text a user copies into a support request.

    JSON rather than prose: whoever adds the type needs to read it as data, and a
    hand-summarised dump loses exactly the field names that matter. The host address
    is deliberately absent — it says where the appliance is on someone's network and
    is of no use in an issue.
    """
    body = {
        "model": model,
        "port": port,
        "app_version": app_version,
        "resource_count": len(resources or {}),
        "note": (
            "Per-unit identifiers (serial number, device ids) are replaced with "
            f"{REDACTED!r}. Everything needed to add support is kept."
        ),
        "resources": redact(resources or {}),
    }
    return json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True)

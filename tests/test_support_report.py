"""The support report, and what must never be in it.

The report exists so an unsupported appliance can be mapped from its own /device/0
rather than from a guess. It is put on the user's clipboard for pasting into a public
issue tracker, so a redaction that silently stops matching would publish the serial
number of someone's appliance. Nothing about that failure is visible — the report
still looks complete — so it is asserted against real captured dumps.
"""

import json
from pathlib import Path

import pytest

from lib import support

FIXTURES = Path(__file__).parent / "fixtures"
DUMPS = sorted(FIXTURES.glob("*.json"))


def _resources(path: Path) -> dict:
    loaded = json.loads(path.read_text())
    # Two fixture shapes exist: a bare {href: rep} map and one wrapped with metadata.
    return loaded.get("resources", loaded) if isinstance(loaded, dict) else {}


def test_there_are_dumps_to_check():
    """A glob that matches nothing would make every test below pass vacuously."""
    assert DUMPS, "no fixtures found"


# Field name -> why it must not reach a public issue tracker. Every entry was found in
# a real dump; the count is asserted non-empty per fixture so a rename cannot quietly
# turn these checks into no-ops.
MUST_REDACT = {
    "serialnum": "the appliance's serial number, which is also its Homey device id",
    "serialnumoption": "a second serial field on air conditioners",
    "serial": "a bare serial field",
    "otnduid": "a per-unit update identifier",
    "macaddressble": "the unit's Bluetooth MAC",
    "macaddresswifi": "the unit's Wi-Fi MAC",
    "deviceid": "an identifier of a device paired to the appliance",
    "connectedapssid": "the name of the user's wireless network",
}


@pytest.mark.parametrize("path", DUMPS, ids=lambda p: p.stem)
def test_every_identifying_field_in_a_real_dump_is_redacted(path):
    resources = _resources(path)
    redacted = support.redact(resources)

    found = 0
    for href, rep in resources.items():
        if not isinstance(rep, dict):
            continue
        for field, value in rep.items():
            tail = field.rsplit(".", 1)[-1].lower()
            if tail not in MUST_REDACT or value in (None, "", [], {}):
                continue
            found += 1
            assert redacted[href][field] == support.REDACTED, (
                f"{href}.{field} is {MUST_REDACT[tail]} and was not redacted"
            )
    assert found, f"{path.stem} contained none of these fields — check the names"


@pytest.mark.parametrize("path", DUMPS, ids=lambda p: p.stem)
def test_the_report_is_valid_json_and_keeps_the_resources(path):
    resources = _resources(path)
    parsed = json.loads(support.report(resources, model="M", port=49154))
    assert parsed["model"] == "M"
    assert parsed["port"] == 49154
    assert parsed["resource_count"] == len(resources)
    assert set(parsed["resources"]) == set(resources), "hrefs must all be present"


@pytest.mark.parametrize("path", DUMPS, ids=lambda p: p.stem)
def test_field_names_and_supported_value_lists_are_preserved(path):
    """These are the whole point of the report. Redacting them would leave a dump
    that looks fine and is useless — the exact failure the hood suffered."""
    resources = _resources(path)
    redacted = support.redact(resources)
    for href, rep in resources.items():
        if not isinstance(rep, dict):
            continue
        assert set(redacted[href]) == set(rep), f"{href} lost or gained a field"
        for field, value in rep.items():
            if isinstance(value, list) and "supported" in field.lower():
                assert redacted[href][field] == value, f"{href}.{field} was altered"


def test_model_number_keeps_the_routing_token_and_drops_the_board_id():
    """Routing keys on the first segment, so it must survive; the trailing board id
    is per-unit and must not."""
    rep = {"/information/vs/0": {
        "x.com.samsung.da.modelNum":
            "AHD-WW-TP1-22-COMMON|20174352|7800006B001947C22F00090001010000",
    }}
    out = support.redact(rep)["/information/vs/0"]["x.com.samsung.da.modelNum"]
    assert out.startswith("AHD-WW-TP1-22-COMMON|20174352|")
    assert "7800006B001947C22F00090001010000" not in out
    assert support.REDACTED in out


@pytest.mark.parametrize(
    "field",
    ["x.com.samsung.da.serialNum", "x.com.samsung.da.otnDUID",
     "x.com.samsung.da.deviceId", "serialNumber", "mac", "macAddress", "di"],
)
def test_every_unit_identifier_spelling_is_redacted(field):
    out = support.redact({"/r": {field: "SOMETHING-IDENTIFYING"}})
    assert out["/r"][field] == support.REDACTED, field


def test_identifiers_nested_in_lists_are_redacted():
    """`/personality/presence/vs/0` carries device ids inside a list of dicts, so a
    shallow pass over the top-level fields would miss them."""
    rep = {"/personality/presence/vs/0": {"x.com.samsung.da.items": [
        {"x.com.samsung.da.id": "0", "x.com.samsung.da.deviceId": "ABC123"},
    ]}}
    item = support.redact(rep)["/personality/presence/vs/0"]["x.com.samsung.da.items"][0]
    assert item["x.com.samsung.da.deviceId"] == support.REDACTED
    assert item["x.com.samsung.da.id"] == "0", "row indexes are not identifiers"


def test_empty_identifier_fields_are_left_alone():
    """Marking an already-empty field as redacted would suggest something was hidden
    when nothing was there."""
    out = support.redact({"/r": {"x.com.samsung.da.serialNum": ""}})
    assert out["/r"]["x.com.samsung.da.serialNum"] == ""


def test_redact_does_not_mutate_its_input():
    original = {"/r": {"x.com.samsung.da.serialNum": "KEEPME"}}
    support.redact(original)
    assert original["/r"]["x.com.samsung.da.serialNum"] == "KEEPME"


def test_the_host_address_is_not_in_the_report():
    """Where an appliance sits on someone's network is of no use in an issue."""
    text = support.report({"/r": {"x": "y"}}, model="M", port=49154)
    assert "192.168" not in text
    assert "host" not in json.loads(text)

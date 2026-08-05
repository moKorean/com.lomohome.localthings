"""What `/device/0`'s first entry is, and why it cannot be skipped on faith.

`parse_device0` used to drop entry [0] unconditionally, on the premise that a batch
response opens with a device-level collection representation. Most firmware here does.
The induction cooktop does not: it opens directly with `/connectionconfig/vs/0`, so
that resource was discarded on every poll and every dump. Nothing surfaced it, because
a resource missing from the map is indistinguishable from a resource the appliance does
not host — the capability simply stays blank, which is the same failure mode
test_no_dead_mappings.py exists for.

Measured 2026-08-05 by reading raw `/device/0` off all nine paired appliances in one
call, so the shapes below are transcribed rather than imagined:

    refrigerators (3), range hood     [0] == {}
    air conditioners (4)              [0] == {"rt": [...], "if": [...]}
    induction cooktop                 [0] == {"href": "/connectionconfig/vs/0", ...}

The cooktop returned 13 entries while our committed dump of it held 12 — the arithmetic
that turned the reference's NV9000D fixture note into a confirmed bug on our own unit.

Both halves are pinned here. Skipping [0] loses a resource on the third shape; not
skipping it must not invent one on the first two, and it does not, because neither
carries an `href`.
"""

from lib.resources import is_stub_rep, parse_device0


class TestCollectionRepIsIgnoredByShape:
    """The two openers measured here carry no `href`, so the href check drops them
    without needing to know they sit at index 0."""

    def test_bare_empty_dict_opener(self):
        device0 = [{}, {"href": "/power/vs/0", "rep": {"power": "On"}}]

        assert parse_device0(device0) == {"/power/vs/0": {"power": "On"}}

    def test_rt_if_opener(self):
        device0 = [
            {"rt": ["oic.wk.col"], "if": ["oic.if.ll", "oic.if.b"]},
            {"href": "/power/vs/0", "rep": {"power": "Off"}},
        ]

        assert parse_device0(device0) == {"/power/vs/0": {"power": "Off"}}


class TestFirstEntryResourceIsKept:
    def test_firmware_that_opens_with_a_resource(self):
        """The induction cooktop's shape. Before the fix `/connectionconfig/vs/0`
        was the entry paid for by the [1:] slice."""
        device0 = [
            {"href": "/connectionconfig/vs/0", "rep": {"autoReconnection": "true"}},
            {"href": "/cooktop/status/vs/0", "rep": {"power": "Off"}},
        ]

        assert parse_device0(device0) == {
            "/connectionconfig/vs/0": {"autoReconnection": "true"},
            "/cooktop/status/vs/0": {"power": "Off"},
        }


class TestUnchangedBehaviour:
    def test_stub_rep_survives_as_a_stub(self):
        """A stub must stay distinguishable from a confirmed-empty {}: callers use
        is_stub_rep to tell "not fetched yet" from "this model never populates it"."""
        parsed = parse_device0(
            [{}, {"href": "/alarms/vs/0", "rep": {"href": "/alarms/vs/0"}}]
        )

        assert is_stub_rep(parsed["/alarms/vs/0"])

    def test_entries_without_href_or_rep_are_dropped(self):
        device0 = [
            {"href": "/no/rep/vs/0"},
            {"rep": {"orphan": True}},
            "not a dict",
            {"href": "/good/vs/0", "rep": {"ok": 1}},
        ]

        assert parse_device0(device0) == {"/good/vs/0": {"ok": 1}}

    def test_non_list_is_empty(self):
        assert parse_device0({"href": "/device/0"}) == {}

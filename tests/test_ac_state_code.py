"""The third alarm slot on the CAC boards, and why it is not an alarm.

`/alarms/vs/0` carries three independent slots on these units. Slot 0 is the error
channel and reads `ErrorCode_OFF` on every unit here; slot 1 is the filter; slot 2
carries a `DA_SAC_M_*` family of its own. A user reported slot 2's value as an error
because that is how it reached the tile — `localthings_alarm_code` shows the first
live entry, so on the one unit whose filter alarm had cleared, an unrelated slot
surfaced as if it were the appliance's alarm. SmartThings called the same appliance
healthy, and SmartThings was right.

Measured 2026-08-07 across four units. The value moves on its own (0003 to 0004 on
two units at different times), which is the plainest evidence it is a state rather
than a fault, and three explanations for what it tracks were refuted outright — mute
(all four muted, only the odd unit lacked the code), power (turning the odd unit on
left it at `_OFF`), and the Wind-Free setting (that unit was already in Wind-Free and
the write came back `errorCode: "unchanged"`).

So the capability is deliberately named for what it is rather than what it means, and
these tests pin the parsing and the gate, not an interpretation.
"""

import json
from pathlib import Path

import pytest

from lib.registry.airconditioner import (
    REGISTRY,
    _has_state_code,
    _read_state_code,
)

CAPABILITY = "localthings_operation_state_code"
FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "airconditioner_TP1X_DA-AC-CAC-01001.json"
)


def _alarms(*codes):
    return {
        "x.com.samsung.da.items": [
            {
                "x.com.samsung.da.id": str(i),
                "x.com.samsung.da.code": code,
                "x.com.samsung.da.state": "Created",
            }
            for i, code in enumerate(codes)
        ]
    }


class TestReadStateCode:
    @pytest.mark.parametrize(
        "code, expected",
        [
            ("DA_SAC_M_OFF", 0),
            ("DA_SAC_M_0003", 3),
            ("DA_SAC_M_0004", 4),
            ("DA_SAC_M_0012", 12),
        ],
    )
    def test_numeric_half_with_idle_as_zero(self, code, expected):
        assert _read_state_code(_alarms("ErrorCode_OFF", code), {}) == expected

    def test_found_regardless_of_position(self):
        """Slot order is not a contract — the filter slot sits between the error
        slot and this one on the units here, but nothing promises it always will."""
        rep = _alarms("DA_SAC_M_0003", "ErrorCode_OFF", "FilterAlarm")

        assert _read_state_code(rep, {}) == 3

    def test_unparseable_suffix_leaves_the_capability_alone(self):
        """Only OFF and a number have ever been reported. Inventing a value for a
        third would be the guess this registry exists to avoid."""
        assert _read_state_code(_alarms("DA_SAC_M_STANDBY"), {}) is None

    def test_absent_family_reads_nothing(self):
        assert _read_state_code(_alarms("ErrorCode_OFF", "FilterAlarm"), {}) is None

    def test_non_list_items(self):
        assert _read_state_code({"x.com.samsung.da.items": "nope"}, {}) is None


class TestGate:
    def test_present_only_where_the_family_is_reported(self):
        assert _has_state_code(_alarms("DA_SAC_M_OFF"), {}) is True
        assert _has_state_code(_alarms("ErrorCode_OFF", "FilterAlarm"), {}) is False

    def test_bound_on_our_own_unit(self):
        """The committed dump of a verified unit carries the family, idle."""
        resources = json.loads(FIXTURE.read_text(encoding="utf-8"))["resources"]

        assert CAPABILITY in REGISTRY.capabilities(resources)
        assert _read_state_code(resources["/alarms/vs/0"], {}) == 0

    def test_not_bound_on_a_board_without_the_family(self):
        """A capability that can never have a value is worse than none: it looks
        like a reading that is stuck rather than one the board does not report."""
        resources = {"/alarms/vs/0": _alarms("ErrorCode_OFF", "FilterAlarm")}

        assert CAPABILITY not in REGISTRY.capabilities(resources)

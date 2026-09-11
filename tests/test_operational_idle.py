"""An idle machine must not look like a running one.

Two firmware quirks, both adopted from the reference on 2026-09-12 and both
measured here against its committed dumps:

  progressPercentage   Range firmware parks this at 1 while `state` reads Ready.
                       Three range dumps and the washer and dryer all do it, so an
                       idle oven sat at a permanent 1% and a bake that had just
                       started looked exactly the same.
  remainingTime        Frozen at '00:01:00' after a cycle ends rather than cleared,
                       so a finished dishwasher reported "1 minute left" forever.

Both rules are deliberately narrow, and the guard that matters is the third case
below: `washer_wf80h` is *genuinely* at 1% — state Run, progress Delaywash, nine
and a half hours remaining — and must still read 1. A clamp keyed on the value
rather than on the state would eat it, which is the failure this file exists to
prevent.

Skipped when the reference checkout is absent, as the other reference tests are.
"""

import json
from pathlib import Path

import pytest

from lib.registry import shared

REF_FIXTURES = Path(__file__).parent.parent.parent / "localthings-reference" / "tests" / "fixtures"

pytestmark = pytest.mark.skipif(
    not REF_FIXTURES.is_dir(), reason="reference checkout not present"
)

HREF = shared.HREF_OPERATIONAL


def _operational(name: str) -> dict:
    out: dict = {}

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("href"), str) and isinstance(node.get("rep"), dict):
                out[node["href"]] = node["rep"]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads((REF_FIXTURES / name).read_text()))
    rep = out.get(HREF)
    assert rep is not None, f"{name} carries no {HREF}"
    return rep


# Every dump whose board parks a non-zero progressPercentage while idle. Each is
# named rather than globbed: the point is that these specific units misreport, and
# a dump dropping out of the corpus should fail rather than silently pass.
PARKED_WHILE_IDLE = [
    "range_device.json",
    "range_ne63a6511_device.json",
    "range_nx60t8311ss_device.json",
    "washer_device.json",
    "dryer_device.json",
]


@pytest.mark.parametrize("name", PARKED_WHILE_IDLE)
def test_parked_progress_reads_zero_while_idle(name):
    rep = _operational(name)
    assert rep.get("x.com.samsung.da.progressPercentage") == "1", (
        f"{name} no longer parks progressPercentage at 1 — if the corpus changed, "
        "this test's premise needs rechecking rather than the expectation relaxing"
    )
    assert shared._progress_percent(rep, {}) == 0


def test_finished_cycle_reads_complete_and_nothing_remaining():
    """The frozen-remainingTime quirk, on the one dump that captures it."""
    rep = _operational("dishwasher_device.json")
    assert rep.get("x.com.samsung.da.remainingTime") == "00:01:00"
    assert shared._progress_percent(rep, {}) == 100
    assert shared._remaining_minutes(rep, {}) == 0
    assert shared._cycle_active(rep, {}) is False


def test_running_cycle_passes_the_boards_own_numbers_through():
    rep = _operational("dishwasher_dw5000c_cloud_device.json")
    assert shared._progress_percent(rep, {}) == 28
    assert shared._remaining_minutes(rep, {}) == 44
    assert shared._cycle_active(rep, {}) is True


def test_a_genuine_one_percent_survives_the_idle_clamp():
    """The guard against clamping on the value instead of the state.

    This washer really is at 1% — Run, Delaywash, 09:26 left. If this ever reads 0,
    the idle rule has started eating real readings.
    """
    rep = _operational("washer_wf80h_device.json")
    assert shared._progress_percent(rep, {}) == 1
    assert shared._remaining_minutes(rep, {}) == 566

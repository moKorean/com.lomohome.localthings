"""Physical positions and push timings projected from the user's control run."""

import asyncio
import copy
import json
from pathlib import Path

import pytest
import test_observe_state_on_failure as observe_tests

from lib.registry import appliances, fridge_doors, shared

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "sequences"
                     / "combi_door_control_TP1X_REF_21K.json").read_text())


@pytest.fixture
def Device():
    yield from observe_tests.Device.__wrapped__()


def resources(sample=0):
    states = FIXTURE["samples"][sample]["resources"]
    result = {"/information/vs/0": {
        "x.com.samsung.da.modelNum": FIXTURE["model_prefix"],
    }}
    for path, values in states.items():
        if path == fridge_doors.AGGREGATE:
            result[path] = {"x.com.samsung.da.items": [
                {"x.com.samsung.da.id": key, "x.com.samsung.da.openState": value}
                for key, value in values.items()
            ]}
        else:
            result[path] = {"openState": values["state"]}
    return result


@pytest.mark.parametrize("index", range(9))
def test_nine_physical_positions_update_cooler_and_combined_alarm(index):
    sample = FIXTURE["samples"][index]
    actual = fridge_doors.values(resources(index))
    cooler, freezer = (sample["physical"][key] for key in ("cooler_open", "freezer_open"))
    assert actual == {fridge_doors.COOLER_CAP: cooler, "alarm_contact": cooler or freezer}
    # Independent push messages held exactly the same values before each GET.
    for path in fridge_doors.SOURCES:
        assert sample["push_before_get"][path] == sample["resources"][path]
    assert fridge_doors.aggregate_states(resources(index)[fridge_doors.AGGREGATE]) == {
        path: sample["resources"][path]["state"] == "Open" for path in fridge_doors.SOURCES
    }


def test_only_the_measured_board_and_surface_get_the_new_capabilities():
    data = resources()
    capabilities = appliances.REFRIGERATOR.capabilities(data)
    assert fridge_doors.COOLER_CAP in capabilities
    assert "localthings_freezer_door_open" not in capabilities
    for model in ("TP2X_REF_21K", "TP1X_REF_21K_OTHER", "unknown", ""):
        other = copy.deepcopy(data)
        other["/information/vs/0"]["x.com.samsung.da.modelNum"] = model
        assert not fridge_doors.matches(other)
        assert fridge_doors.COOLER_CAP not in appliances.REFRIGERATOR.capabilities(other)
    del data[fridge_doors.COOLER]
    assert not fridge_doors.matches(data)


def test_model_suffixes_do_not_change_the_board_prefix():
    data = resources()
    data["/information/vs/0"]["x.com.samsung.da.modelNum"] += "|variant|flags"
    assert fridge_doors.matches(data)


@pytest.mark.parametrize(("per_door", "aggregate"), [(True, True), (True, False), (False, True)])
def test_third_door_keeps_existing_alarm(Device, per_door, aggregate):
    d = device(Device)
    data = d._resources
    # Layout from the TP1X_REF_21K US reference fixture; third-door-open is simulated.
    if per_door:
        data["/door/cvroom/0"] = {"openState": "Open"}
    if aggregate:
        data[fridge_doors.AGGREGATE]["x.com.samsung.da.items"].append(
            {"x.com.samsung.da.id": "2", "x.com.samsung.da.openState": "Open"}
        )
    assert not fridge_doors.matches(data)
    assert fridge_doors.COOLER_CAP not in d._registry.capabilities(data)
    d._values = {"alarm_contact": False}
    assert fridge_doors.AGGREGATE in d._observable_hrefs()
    asyncio.run(d._apply(data))
    assert d._values["alarm_contact"] is True


def test_stale_open_in_the_non_pushing_aggregate_cannot_latch_the_alarm():
    data = resources()
    data[fridge_doors.AGGREGATE]["x.com.samsung.da.items"][0][
        "x.com.samsung.da.openState"] = "Open"
    assert shared.read_any_door_open({}, data) is False
    # Other models keep the existing union behavior.
    data["/information/vs/0"]["x.com.samsung.da.modelNum"] = "TP2X_REF_21K"
    assert shared.read_any_door_open({}, data) is True


@pytest.mark.parametrize("bad", [None, "unknown", "", 42])
def test_unknown_raw_state_does_not_clear_the_combined_alarm(bad):
    data = resources()
    data[fridge_doors.FREEZER]["openState"] = bad
    values = fridge_doors.values(data)
    assert values["alarm_contact"] is None


def device(Device):
    d = Device()
    d._registry = appliances.REFRIGERATOR
    d._resources = resources()
    d._door_timer = None
    d._door_updates = {}
    d._door_task = None
    d._tasks = set()
    d._settling = {}
    d._notified = set()
    d._values = dict.fromkeys(fridge_doors.CAPABILITIES)
    d.changes = []
    d.get_capabilities = lambda: list(fridge_doors.CAPABILITIES)
    d.get_capability_value = d._values.get

    async def set_value(capability, value):
        d._values[capability] = value
        d.changes.append((capability, value))

    async def noop(*args):
        pass

    d.set_capability_value = set_value
    d._note_on_timeline = noop
    d._maybe_trigger = noop
    return d


class Timer:
    def __init__(self, due, callback):
        self.due, self.callback = due, callback
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class Clock:
    def __init__(self):
        self.now = 0
        self.timers = []

    def call_later(self, delay, callback):
        timer = Timer(self.now + delay, callback)
        self.timers.append(timer)
        return timer

    async def advance(self, seconds, d):
        self.now = seconds
        for timer in self.timers[:]:
            if not timer.cancelled and timer.due <= seconds:
                timer.cancelled = True
                timer.callback()
        if d._tasks:
            await asyncio.gather(*d._tasks)


def test_subscriptions_follow_live_doors_but_other_models_are_unchanged(Device):
    d = device(Device)
    assert set(d._observable_hrefs()) == fridge_doors.SOURCES
    d._resources["/information/vs/0"]["x.com.samsung.da.modelNum"] = "TP2X_REF_21K"
    assert fridge_doors.AGGREGATE in d._observable_hrefs()


def test_recorded_push_sequence_updates_cooler_and_combined_alarm(Device, monkeypatch):
    d, clock = device(Device), Clock()
    reads = []

    class Session:
        async def read_resource(self, path):
            assert path == ["doors", "vs", "0"]
            # Return the recorded direct snapshot for the next confirmed position.
            index = next(
                i for i, snap in enumerate(FIXTURE["samples"]) if snap["seconds"] >= clock.now
            )
            reads.append(index)
            return resources(index)[fridge_doors.AGGREGATE]

    d._session = Session()

    async def run():
        await d._apply(d._resources)
        monkeypatch.setattr(asyncio, "get_running_loop", lambda: clock)
        timeline = [(e["seconds"], "push", e) for e in FIXTURE["notifications"]]
        timeline += [(s["seconds"], "check", s) for s in FIXTURE["samples"]]
        for seconds, kind, event in sorted(timeline, key=lambda item: (item[0], item[1])):
            await clock.advance(seconds, d)
            if kind == "push":
                d._on_notification(event["path"], {"openState": event["state"]})
            else:
                physical = event["physical"]
                assert d._values[fridge_doors.COOLER_CAP] == physical["cooler_open"]
                assert d._values["alarm_contact"] == any(physical.values())
        for capability in fridge_doors.CAPABILITIES:
            assert [v for c, v in d.changes if c == capability] == [
                False, True, False, True, False]
        assert reads == [2, 4, 5, 7]  # Only single-source windows need GET.

    asyncio.run(run())


def test_a_poll_cannot_publish_half_a_pair_during_debounce(Device, monkeypatch):
    d, clock = device(Device), Clock()

    async def run():
        await d._apply(d._resources)
        d.changes.clear()
        monkeypatch.setattr(asyncio, "get_running_loop", lambda: clock)
        d._on_notification(fridge_doors.COOLER, {"openState": "Open"})
        await d._apply(d._resources)
        assert d.changes == []
        clock.now = 2.23
        d._on_notification(fridge_doors.FREEZER, {"openState": "Open"})
        await clock.advance(3.01, d)
        assert d.changes == []  # First timer was cancelled.
        await clock.advance(5.24, d)
        assert d._values == {fridge_doors.COOLER_CAP: True, "alarm_contact": True}

    asyncio.run(run())


@pytest.mark.parametrize("get_result", ["complete", "incomplete", "timeout"])
def test_lost_door_push_verifies_the_pair_with_one_get(Device, monkeypatch, get_result):
    d, clock = device(Device), Clock()
    reads = []

    class Session:
        async def read_resource(self, path):
            reads.append(path)
            if get_result == "timeout":
                raise TimeoutError
            if get_result == "incomplete":
                return {}
            return resources(1)[fridge_doors.AGGREGATE]

    async def run():
        d._session = Session()
        await d._apply(d._resources)
        d.changes.clear()
        monkeypatch.setattr(asyncio, "get_running_loop", lambda: clock)
        d._on_notification(fridge_doors.COOLER, {"openState": "Open"})
        await clock.advance(3.01, d)
        assert reads == [["doors", "vs", "0"]]
        if get_result == "complete":
            assert d._values[fridge_doors.COOLER_CAP] is True
            assert d._values["alarm_contact"] is True
        else:
            assert d.changes == []
            await d._apply(resources(1))  # A later successful poll recovers.
            assert d._values["alarm_contact"] is True

    asyncio.run(run())


def test_fridge_ajar_does_not_update_a_leftover_freezer_capability(Device, monkeypatch):
    d, clock = device(Device), Clock()
    old_freezer_cap = "localthings_freezer_door_open"
    d._values[old_freezer_cap] = False  # A device from the earlier test build.

    async def run():
        await d._apply(d._resources)
        d.changes.clear()
        monkeypatch.setattr(asyncio, "get_running_loop", lambda: clock)
        # These same raw values were observed both with the fridge ajar and
        # with both doors open. They support an alarm, not a freezer claim.
        d._on_notification(fridge_doors.COOLER, {"openState": "Open"})
        d._on_notification(fridge_doors.FREEZER, {"openState": "Close"})
        await clock.advance(fridge_doors.DEBOUNCE_S + 0.01, d)
        assert dict(d.changes) == {fridge_doors.COOLER_CAP: True, "alarm_contact": True}

    asyncio.run(run())


def test_new_push_supersedes_inflight_door_get(Device, monkeypatch):
    d, clock = device(Device), Clock()

    async def run():
        started, finish = asyncio.Event(), asyncio.Event()

        class Session:
            async def read_resource(self, _path):
                started.set()
                await finish.wait()
                return resources(1)[fridge_doors.AGGREGATE]

        d._session = Session()
        await d._apply(d._resources)
        d.changes.clear()
        monkeypatch.setattr(asyncio, "get_running_loop", lambda: clock)
        d._on_notification(fridge_doors.COOLER, {"openState": "Open"})
        read = asyncio.create_task(clock.advance(3.01, d))
        await started.wait()
        d._on_notification(fridge_doors.COOLER, {"openState": "Close"})
        d._on_notification(fridge_doors.FREEZER, {"openState": "Close"})
        finish.set()
        await read
        await clock.advance(6.02, d)
        assert d.changes == []

    asyncio.run(run())


def test_uninit_cancels_a_pending_door_update(Device):
    d, clock = device(Device), Clock()
    d._door_timer = clock.call_later(3, lambda: None)
    timer = d._door_timer
    d._poll_task = None

    class Session:
        async def close(self):
            pass

    d._session = Session()
    asyncio.run(d.on_uninit())
    assert timer.cancelled
    assert d._door_timer is None

"""The EHS cycle log decodes to the values a second resource agrees with.

`/ehscycle/vs/0` is a hex-encoded fixed-width record, and a byte map taken from
a decoding guide is not a measurement — these tests are what make it one. Each
bound offset is checked against something in the same dump that reads the same
quantity another way, and the offsets with no such second source are not bound
at all.

The staleness rule is why the dead-mapping suite sees these as blank: the
reference's dumps were taken in October 2026 and the readings are withheld past
half an hour. So the decoding is exercised here instead, with the clock set to
the sample's own timestamp.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lib import registry
from lib.registry import ehs_cycle

REF_FIXTURES = Path(__file__).parent.parent.parent / "localthings-reference" / "tests" / "fixtures"
MIM = "ehs_mim_h04en_device.json"

pytestmark = pytest.mark.skipif(
    not (REF_FIXTURES / MIM).is_file(), reason="reference dump not present"
)


def _resources(name):
    out: dict = {}

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("href"), str) and isinstance(node.get("rep"), dict):
                out[node["href"]] = node["rep"]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(json.loads((REF_FIXTURES / name).read_text()))
    return out


@pytest.fixture
def at_sample_time(monkeypatch):
    """Freeze the clock at the newest sample's own timestamp."""
    def freeze(rep):
        taken = ehs_cycle._parse_datetime(rep["indoor"][-1]["datetime"])
        monkeypatch.setattr(ehs_cycle, "_now", lambda: taken)
        return taken
    return freeze


def test_the_dump_really_is_too_old_to_read_live():
    """The premise of the allow-list entries in test_no_dead_mappings."""
    rep = _resources(MIM)[ehs_cycle.HREF]
    taken = ehs_cycle._parse_datetime(rep["indoor"][-1]["datetime"])
    assert datetime.now(UTC) - taken > ehs_cycle.STALE_AFTER
    assert ehs_cycle.read_flow_temperature(rep, {}) is None


def test_the_outdoor_temperature_matches_the_resource_that_measures_it(at_sample_time):
    """The cross-check the whole byte map rests on. Outdoor byte 8 decodes to a
    whole degree; `/temperatures/outside/vs/0` reads the same sensor to 0.1."""
    resources = _resources(MIM)
    rep = resources[ehs_cycle.HREF]
    at_sample_time(rep)
    decoded = ehs_cycle.read_outdoor_temperature(rep, resources)
    measured = resources["/temperatures/outside/vs/0"]["x.com.samsung.da.current"]
    assert decoded == 8.0
    assert abs(decoded - measured) < 1.0


def test_the_water_loop_readings(at_sample_time):
    rep = _resources(MIM)[ehs_cycle.HREF]
    at_sample_time(rep)
    assert ehs_cycle.read_flow_temperature(rep, {}) == 33.0
    assert ehs_cycle.read_return_temperature(rep, {}) == 31.0
    assert ehs_cycle.read_pump_speed(rep, {}) == 70.0
    assert ehs_cycle.read_compressor_hz(rep, {}) == 17.0


def test_an_out_of_range_flow_rate_reads_as_unknown(at_sample_time):
    """This dump's bytes 6-7 are 0x6D60, which is 2800 L/min. Some boards scale
    the value up by further powers of ten, so it is withheld rather than
    published — a heat pump does not move 2800 litres a minute."""
    rep = _resources(MIM)[ehs_cycle.HREF]
    at_sample_time(rep)
    assert int.from_bytes(bytes.fromhex(rep["indoor"][-1]["cycledata"])[6:8], "big") == 0x6D60
    assert ehs_cycle.read_flow_rate(rep, {}) is None


def test_a_plausible_flow_rate_does_read(at_sample_time):
    """The other half: byte 6 is the high byte, not a flag, so a flow above
    25.5 L/min has to survive."""
    rep = dict(_resources(MIM)[ehs_cycle.HREF])
    taken = at_sample_time(rep)
    raw = bytearray(bytes.fromhex(rep["indoor"][-1]["cycledata"]))
    raw[6:8] = (301).to_bytes(2, "big")
    rep["indoor"] = [{"datetime": taken.strftime("%Y-%m-%dT%H:%M:%S"), "cycledata": raw.hex()}]
    assert ehs_cycle.read_flow_rate(rep, {}) == 30.1


def test_a_sample_just_past_the_window_stops_reading(at_sample_time, monkeypatch):
    resources = _resources(MIM)
    rep = resources[ehs_cycle.HREF]
    taken = ehs_cycle._parse_datetime(rep["indoor"][-1]["datetime"])
    monkeypatch.setattr(ehs_cycle, "_now", lambda: taken + ehs_cycle.STALE_AFTER)
    assert ehs_cycle.read_flow_temperature(rep, {}) == 33.0
    monkeypatch.setattr(
        ehs_cycle, "_now", lambda: taken + ehs_cycle.STALE_AFTER + timedelta(seconds=1)
    )
    assert ehs_cycle.read_flow_temperature(rep, {}) is None


def test_an_unknown_record_length_is_not_decoded_at_a_guessed_offset(at_sample_time):
    rep = dict(_resources(MIM)[ehs_cycle.HREF])
    taken = at_sample_time(rep)
    rep["indoor"] = [{"datetime": taken.strftime("%Y-%m-%dT%H:%M:%S"), "cycledata": "00" * 24}]
    assert ehs_cycle.read_flow_temperature(rep, {}) is None


def test_the_board_that_measures_outdoor_properly_does_not_get_the_log_copy():
    resources = _resources(MIM)
    assert "/temperatures/outside/vs/0" in resources
    reg = registry.resolve(resources)
    assert reg is not None and reg.name == "ehs"
    assert "measure_temperature.outdoor" not in reg.capabilities(resources)
    assert "measure_temperature.flow" in reg.capabilities(resources)


def test_a_board_without_that_resource_does_get_it():
    found = []
    for path in sorted(REF_FIXTURES.glob("ehs*_device.json")):
        resources = _resources(path.name)
        if ehs_cycle.HREF not in resources or "/temperatures/outside/vs/0" in resources:
            continue
        reg = registry.resolve(resources)
        if reg is None or reg.name != "ehs":
            continue
        assert "measure_temperature.outdoor" in reg.capabilities(resources), path.name
        found.append(path.name)
    assert found, "no dump exercises the other side of the gate"

"""Outdoor temperature, from the AC's `OutdoorTemp_<n>` options token minus 55.

The offset is the reference's, field-validated there over 48 hours against a
weather feed (r=0.92) on boards declaring Celsius. Ours declare Celsius, and the
four units here read 84-87, so 29-32°C.

**The independent check available did not confirm it**, and that is recorded rather
than quietly dropped. A spot query to wttr.in for Seoul answered 13°C at the same
moment, which no plausible reading of a -55 offset reconciles — it would need about
-72. Two things argue for the appliances over that figure: all four units were
actively cooling rooms sitting at 28.5-30.5°C, which is not a 13°C day, and r=0.92
is a *correlation*, so a constant offset error would survive it upstream too.

So the reading ships because a wrong constant still tracks the real curve and is
obvious to anyone who compares it with a window, and docs/BACKLOG.md carries the
experiment that would settle the constant. These tests pin the arithmetic, the
gate and the token, not the truth of the offset.
"""

import json
from pathlib import Path

import pytest

from lib import registry
from lib.registry import airconditioner

FIXTURE = (
    Path(__file__).parent / "fixtures" / "airconditioner_TP1X_DA-AC-CAC-01001.json"
)
CAPABILITY = "measure_temperature.outdoor"
MODE = "/mode/vs/0"
TEMPS = "/temperatures/vs/0"


@pytest.fixture(scope="module")
def resources():
    return json.loads(FIXTURE.read_text())["resources"]


def _spec(resources):
    return registry.resolve(resources, ()).spec_for(CAPABILITY, resources)


def test_the_verified_unit_reads_its_outdoor_temperature(resources):
    """OutdoorTemp_86 on the committed dump, captured on a late-July day in Korea."""
    spec = _spec(resources)
    assert spec.applies(resources)
    assert spec.read(resources[MODE], resources) == 31.0


def test_the_offset_is_the_only_arithmetic(resources):
    """Guards against a scale factor creeping in beside the offset."""
    for raw, expected in (("84", 29.0), ("85", 30.0), ("87", 32.0), ("55", 0.0)):
        rep = dict(resources[MODE])
        rep["x.com.samsung.da.options"] = [f"OutdoorTemp_{raw}"]
        assert airconditioner._read_outdoor_temp(rep, resources) == expected


def test_a_board_without_the_token_gets_no_sensor(resources):
    """Absence of the token is the only signal a board lacks the reading, the same
    rule the other options[] capabilities use."""
    rep = dict(resources[MODE])
    rep["x.com.samsung.da.options"] = ["Sleep_0", "ArtificialWorking_On"]
    assert airconditioner._read_outdoor_temp(rep, resources) is None
    assert airconditioner._has_outdoor_temp(rep, resources) is False


def test_a_fahrenheit_board_is_left_alone(resources):
    """The constant was validated on Celsius boards only. Nothing says a
    Fahrenheit board uses the same additive constant, or reports degrees F through
    it at all, so it reads nothing rather than a number that is wrong twice over."""
    fahrenheit = dict(resources)
    item = dict(fahrenheit[TEMPS]["x.com.samsung.da.items"][0])
    item["x.com.samsung.da.unit"] = "Fahrenheit"
    fahrenheit[TEMPS] = {"x.com.samsung.da.items": [item]}

    assert airconditioner._reports_celsius(fahrenheit) is False
    assert airconditioner._read_outdoor_temp(resources[MODE], fahrenheit) is None


def test_a_board_that_declares_no_unit_is_treated_as_celsius(resources):
    """Matching the reference's own default. Every board on record that carries the
    token and declares a unit says Celsius, so silence is not evidence of the
    exception."""
    silent = dict(resources)
    silent[TEMPS] = {"x.com.samsung.da.items": [{"x.com.samsung.da.current": "29.5"}]}
    assert airconditioner._reports_celsius(silent) is True
    assert airconditioner._read_outdoor_temp(resources[MODE], silent) == 31.0


def test_it_is_a_sub_capability_of_the_room_reading(resources):
    """Homey's built-in measure_temperature, so no new capability is declared and
    the tile inherits its unit and formatting — the same shape the refrigerator's
    per-compartment temperatures already use. The per-instance title is what keeps
    it apart from the room reading in the UI."""
    spec = _spec(resources)
    assert spec.capability.startswith("measure_temperature.")
    assert spec.titles == {"en": "Outdoor", "ko": "실외"}

    reg = registry.resolve(resources, ())
    assert "measure_temperature" in reg.capabilities(resources)
    assert CAPABILITY in reg.capabilities(resources)

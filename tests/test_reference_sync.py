"""Changes ported from the reference integration, last synced against v0.17.2.

Each test names the reference issue it came from. The point is not that the port
happened, but that it stays: a token table and a unit conversion are exactly the
kind of thing a later refactor drops without any visible symptom.

Where a change could not be verified against hardware, the test says so — it pins
the behaviour that was ported, not a claim that the behaviour is right.
"""

import json
from pathlib import Path

import pytest

from lib import probe, registry
from lib.const import PREFERRED_PROBE_PORTS, PROBE_PORT_RANGE
from lib.registry import airconditioner, appliances

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def ac_resources() -> dict:
    loaded = json.loads((FIXTURES / "airconditioner_TP1X_DA-AC-CAC-01001.json").read_text())
    return loaded["resources"]


# --- reference #190: AVT-WW air purifier board token ------------------------


def test_avt_board_routes_to_the_air_purifier():
    """`AVT-WW-TP1-23-AXX500` is the same BESPOKE Cube Air lineage as `A-VTWW-`,
    but the '-WW-' delimiter moved one letter left, so the existing VTWW token
    cannot see it."""
    resolved = registry.resolve({"/information/vs/0": {
        "x.com.samsung.da.modelNum": "AVT-WW-TP1-23-AXX500|1|2",
    }})
    assert resolved is appliances.AIR_PURIFIER


def test_the_older_vtww_spelling_still_routes():
    """Adding AVT must not disturb the token it was split off from."""
    resolved = registry.resolve({"/information/vs/0": {
        "x.com.samsung.da.modelNum": "A-VTWW-TP2-21-COMMON|1|2",
    }})
    assert resolved is appliances.AIR_PURIFIER


# --- reference #191: CAC cassette air conditioner --------------------------


def test_cac_still_routes_to_the_air_conditioner(ac_resources):
    """This app added CAC before the reference did (contributed upstream as
    mbillow/localthings#194, fixed there independently as #191). The reference now
    carries it too, so this asserts the two agree rather than that ours is a
    local-only patch."""
    assert "CAC" in airconditioner.BOARD_TOKENS
    assert registry.resolve(ac_resources) is airconditioner.REGISTRY


# --- reference #192: always retry historically-confirmed DTLS ports --------


def test_preferred_ports_are_attempted_even_when_the_sweep_excludes_them():
    """The sweep's ICMP verdict was observed calling closed ports live while
    missing the one port nmap found open, on a segregated VLAN. A "not live"
    verdict must not overrule that prior."""
    swept = probe.order_candidates([49158])
    rescued = [p for p in PREFERRED_PROBE_PORTS if p in PROBE_PORT_RANGE
               and p not in [49158]]
    assert rescued, "no preferred port to rescue — the fixture is wrong"
    # What find_live_ports returns for a sweep that found only 49158.
    assert swept + rescued == [49158, *PREFERRED_PROBE_PORTS]


def test_rescued_ports_go_last_not_first():
    """A deliberate divergence from the reference, which promotes them. This app
    sweeps a whole subnet where most responders are not Samsung appliances, so
    promoting would spend two guaranteed extra handshakes on each of them."""
    ordered = probe.order_candidates([49158]) + [
        p for p in PREFERRED_PROBE_PORTS if p not in [49158]
    ]
    assert ordered[0] == 49158, "a port the sweep did find must be tried first"


def test_a_port_the_sweep_found_is_not_duplicated():
    """49154 is both preferred and commonly live; it must appear once."""
    ordered = probe.order_candidates([49154, 49158])
    rescued = [p for p in PREFERRED_PROBE_PORTS if p not in [49154, 49158]]
    combined = ordered + rescued
    assert len(combined) == len(set(combined)), combined
    assert combined.count(49154) == 1


# --- reference #193: legacy ARTIK051 cumulativePower scale ----------------


def _legacy_energy_rep(raw: str) -> dict:
    return {
        "x.com.samsung.da.cumulativePower": raw,
        # The legacy board labels this 'Wh' too, so the label cannot discriminate.
        "x.com.samsung.da.cumulativeUnit": "Wh",
    }


def test_legacy_board_energy_uses_the_centiwatt_hour_scale():
    """Reference #193: raw 117430000 against the reporter's authoritative
    SmartThings reading of 1,174.30 kWh is /100000, not /1000.

    Not verified on hardware here — no legacy board was available."""
    spec = airconditioner.REGISTRY.spec_for("meter_power")
    legacy = {"/airflow/vs/0": {}}  # no /wind/strength/vs/0 -> legacy generation
    assert airconditioner.is_legacy_board(legacy)
    assert spec.read(_legacy_energy_rep("117430000"), legacy) == 1174.30


def test_newer_boards_keep_the_plain_wh_scale(ac_resources):
    """The gate has to be narrow: every other family must be untouched."""
    assert not airconditioner.is_legacy_board(ac_resources)
    spec = airconditioner.REGISTRY.spec_for("meter_power")
    assert spec.read(_legacy_energy_rep("117430000"), ac_resources) == 117430.0


def test_the_legacy_discriminator_needs_both_conditions():
    """Presence of /airflow alone is not enough — a board carrying both hrefs is
    not the legacy generation."""
    assert not airconditioner.is_legacy_board(
        {"/airflow/vs/0": {}, "/wind/strength/vs/0": {}}
    )
    assert not airconditioner.is_legacy_board({"/wind/strength/vs/0": {}})
    assert not airconditioner.is_legacy_board({})


# --- sound settings, found unbound while syncing ---------------------------


def test_the_air_conditioner_binds_its_sound_settings(ac_resources):
    """Both resources are present and populated on all three verified units, and
    were listed as coverage gaps until now."""
    for capability, expected in (
        ("localthings_sound_mode", "voice"),
        ("localthings_sound_volume", 2),
    ):
        spec = airconditioner.REGISTRY.spec_for(capability)
        assert spec is not None, f"{capability} is not bound"
        assert spec.applies(ac_resources), f"{capability} does not apply"
        assert spec.read(ac_resources[spec.href], ac_resources) == expected


def test_sound_volume_bounds_come_from_the_appliance(ac_resources):
    spec = airconditioner.REGISTRY.spec_for("localthings_sound_volume")
    rep = ac_resources[spec.href]
    assert (rep["minLevel"], rep["maxLevel"], rep["resolution"]) == ("0", "3", "1")
    assert spec.options(rep, ac_resources) == {"min": 0, "max": 3, "step": 1}


def test_sound_settings_stay_read_only(ac_resources):
    """The volume resource advertises min/max/resolution, which looks writable, but
    no write has been observed and the reference exposes neither as writable."""
    for capability in ("localthings_sound_mode", "localthings_sound_volume"):
        assert not airconditioner.REGISTRY.spec_for(capability).writable, capability


# --- transient failures must not reach the user ---------------------------


def test_a_device_is_not_marked_unavailable_on_the_first_failure():
    """A restarted app leaves the appliance holding an orphaned DTLS association, and
    the first handshake into it is refused — which the app recovers from by itself
    from another source port. Reporting that put "DTLS handshake error" on a tile for
    something self-healing."""
    from lib.const import RELOCATE_AFTER_FAILURES, UNAVAILABLE_AFTER_FAILURES
    assert UNAVAILABLE_AFTER_FAILURES > 1
    # Above the relocation threshold, so relocation gets its attempt before the user
    # sees a fault; otherwise a recovered device would flash unavailable first.
    assert UNAVAILABLE_AFTER_FAILURES > RELOCATE_AFTER_FAILURES


def test_the_poll_loop_gates_set_unavailable_on_that_threshold():
    source = (Path(__file__).parent.parent / "lib/appliance/device.py").read_text()
    loop = source[source.index("async def _poll_loop"):]
    loop = loop[:loop.index("def _unavailable_reason")]
    assert "if self._failures >= UNAVAILABLE_AFTER_FAILURES:" in loop
    assert "set_unavailable(self._unavailable_reason(exc))" in loop
    # The raw exception must not be what the user reads.
    assert "set_unavailable(str(exc))" not in loop


def test_the_fault_message_is_translated_not_the_exception():
    """`str(exc)` is where "DTLS handshake error (SSL routines, tlsv1 alert decode
    error)" came from: accurate, and no help to someone looking at a greyed-out
    tile."""
    import ast

    source = (Path(__file__).parent.parent / "lib/appliance/device.py").read_text()
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_unavailable_reason"
    )
    # Code only. The docstring explains why str(exc) is wrong, and naming it there
    # must not read as using it — the same trap a plain substring check fell into.
    body = [n for n in function.body if not (
        isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
        and isinstance(n.value.value, str)
    )]
    code = "\n".join(ast.unparse(n) for n in body)

    assert "i18n.translate" in code
    assert "peer_holds_stale_session" in code, (
        "the two causes a user can act on are not told apart"
    )
    assert "str(exc)" not in code


@pytest.mark.parametrize("key", ["error.handshake_refused", "error.unreachable"])
def test_both_fault_messages_exist_in_both_languages(key):
    from lib import i18n
    english = i18n.translate(key, "en", host="192.168.1.9")
    korean = i18n.translate(key, "ko", host="192.168.1.9")
    assert english and english != key
    assert korean and korean != key
    assert english != korean, f"{key} is not actually translated"
    # A message that only says what broke, without saying the app is still trying,
    # reads as a dead end.
    assert "retry" in english.lower() or "retrying" in english.lower()
    assert "재시도" in korean


# --- reference #196: AILITE water purifier routes past the REF board token ---


def test_ailite_water_purifier_does_not_route_to_the_refrigerator():
    """These boards spell modelNum '...-REF-WATERPURIFIER-...'. Both tokens are in
    the table, so whichever the scan reaches first decides — and 'REF' comes first
    in the string, which sent a water purifier to the fridge registry."""
    resolved = registry.resolve({"/information/vs/0": {
        "x.com.samsung.da.modelNum": "AILITE_DA-REF-WATERPURIFIER-24-COMMON|1|2",
    }})
    assert resolved is not None
    assert resolved.name == "water_purifier"


def test_the_carve_out_does_not_capture_a_plain_refrigerator():
    """The exception is one documented co-occurrence, not a demotion of 'REF'."""
    resolved = registry.resolve({"/information/vs/0": {
        "x.com.samsung.da.modelNum": "AILITE_DA-REF-NORMAL-24-COMMON|1|2",
    }})
    assert resolved is not None
    assert resolved.name == "refrigerator"


def test_a_misrouted_water_purifier_would_have_had_fridge_controls():
    """Why the mis-route mattered: it is not a cosmetic label. The fridge registry
    binds compartment setpoints and a door alarm, none of which exist on a water
    purifier, so the appliance would have offered controls that write nowhere."""
    fridge = registry._REGISTRY_BY_KEY["refrigerator"]
    purifier = registry._REGISTRY_BY_KEY["water_purifier"]
    fridge_only = {s.capability for s in fridge.specs} - {s.capability for s in purifier.specs}
    assert "target_temperature.fridge" in fridge_only
    assert "alarm_contact" in fridge_only


def test_the_water_purifier_reads_the_sound_resources():
    """Reference #196 found /settings/sound/{mode,volume}/vs/0 on this family."""
    caps = {(s.capability, s.href) for s in registry._REGISTRY_BY_KEY["water_purifier"].specs}
    assert ("localthings_sound_mode", "/settings/sound/mode/vs/0") in caps
    assert ("localthings_sound_volume", "/settings/sound/volume/vs/0") in caps


def test_sound_mode_accepts_a_value_the_other_families_never_report():
    """This board's supportedModes are voice/fixedTone/mute. Reference #196 warns
    that reusing another family's value set would reject a live value; nothing may
    turn our reader into a fixed list without this failing."""
    definition = json.loads(
        (Path(__file__).parent.parent / ".homeycompose" / "capabilities"
         / "localthings_sound_mode.json").read_text()
    )
    assert definition["type"] == "string"
    assert "values" not in definition, "an enum here would reject 'fixedTone'"

    spec = next(s for s in registry._REGISTRY_BY_KEY["water_purifier"].specs
                if s.capability == "localthings_sound_mode")
    assert spec.read({"mode": "fixedTone"}, {}) == "fixedTone"


# --- reference #201: fan speed from a min/max range ------------------------


def _hood_fan_spec(capability="localthings_hood_fan_speed"):
    return next(s for s in appliances.RANGE_HOOD.specs if s.capability == capability)


def test_the_verified_hood_still_uses_its_supported_list():
    """The AHD-WW-TP1-22 lists 14-18 explicitly. The fallback must not displace
    the form that real hardware uses."""
    rep = {"x.com.samsung.da.hood.fanSpeed": "16",
           "x.com.samsung.da.hood.supportedFanSpeed": ["14", "15", "16", "17", "18"]}
    spec = _hood_fan_spec()
    assert spec.read(rep, {}) == 3
    assert spec.options(rep, {}) == {"min": 1, "max": 5, "step": 1}


def test_a_board_without_a_supported_list_falls_back_to_the_range():
    """Reference #201: settableMin/MaxFanSpeed is the only form some boards give."""
    rep = {"x.com.samsung.da.hood.fanSpeed": "2",
           "x.com.samsung.da.hood.settableMinFanSpeed": "1",
           "x.com.samsung.da.hood.settableMaxFanSpeed": "5"}
    spec = _hood_fan_spec()
    assert spec.exists(rep, {}) is True
    assert spec.read(rep, {}) == 2
    assert spec.options(rep, {}) == {"min": 1, "max": 5, "step": 1}
    assert spec.write(4, rep) == (["hood", "fanspeed", "vs", "0"],
                                  {"x.com.samsung.da.hood.fanSpeed": "4"})


def test_an_explicit_list_wins_over_a_range_that_disagrees():
    """Only the list can describe a non-contiguous set, so it is not a tie-break
    by preference — the range cannot represent what the list can."""
    rep = {"x.com.samsung.da.hood.fanSpeed": "30",
           "x.com.samsung.da.hood.supportedFanSpeed": ["10", "20", "30"],
           "x.com.samsung.da.hood.settableMinFanSpeed": "1",
           "x.com.samsung.da.hood.settableMaxFanSpeed": "9"}
    spec = _hood_fan_spec()
    assert spec.read(rep, {}) == 3
    assert spec.options(rep, {}) == {"min": 1, "max": 3, "step": 1}


@pytest.mark.parametrize("rep", [
    {"x.com.samsung.da.hood.fanSpeed": "1"},
    {"x.com.samsung.da.hood.fanSpeed": "1",
     "x.com.samsung.da.hood.settableMinFanSpeed": "1"},
    {"x.com.samsung.da.hood.fanSpeed": "1",
     "x.com.samsung.da.hood.settableMinFanSpeed": "5",
     "x.com.samsung.da.hood.settableMaxFanSpeed": "1"},
    {"x.com.samsung.da.hood.fanSpeed": "1",
     "x.com.samsung.da.hood.settableMinFanSpeed": "low",
     "x.com.samsung.da.hood.settableMaxFanSpeed": "high"},
])
def test_a_board_advertising_no_usable_levels_gets_no_slider(rep):
    """Half a range, an inverted one, or a non-numeric one is not a range. Binding
    the capability anyway is what produced a slider that could not be honoured."""
    spec = _hood_fan_spec()
    assert spec.exists(rep, {}) is False


def test_the_lamp_level_was_not_swept_into_the_fan_fallback():
    """The lamp reads its own range field and has no settableMin/Max form. A
    refactor that pointed both at the fan's resolver would leave the lamp
    reading a field it does not have."""
    rep = {"x.com.samsung.lamp.current": "2", "x.com.samsung.lamp.range": ["1", "2"]}
    spec = _hood_fan_spec("localthings_lamp_brightness")
    assert spec.read(rep, {}) == 2
    assert spec.options(rep, {}) == {"min": 1, "max": 2, "step": 1}

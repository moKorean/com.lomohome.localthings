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
from lib.registry import airconditioner, appliances, shared

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


# --- reference: /oic/d as the primary type signal --------------------------
#
# Measured on nine appliances here, every one of which populates it and every one
# agreeing with the board token: 4x oic.d.airconditioner, 3x oic.d.refrigerator,
# oic.d.cooktop, x.com.st.d.hood. See docs/BACKLOG.md.


def _oicd(*types) -> tuple:
    return tuple(types)


def test_oic_type_beats_an_unrecognised_model_string():
    """The reason to read it at all: a modelNum whose board token means nothing to
    us currently ends as 'unsupported appliance'."""
    resources = {"/information/vs/0": {
        "x.com.samsung.da.modelNum": "SOMETHING_UNRECOGNISED-99-XX|1|2",
    }}
    assert registry.resolve(resources) is None
    resolved = registry.resolve(resources, _oicd("oic.wk.d", "oic.d.refrigerator"))
    assert resolved is not None and resolved.name == "refrigerator"


def test_the_hood_token_this_house_reports_is_mapped():
    """`x.com.st.d.hood` is what the AHD-WW-TP1-22 actually answers with. It is
    absent from the reference's table, so this is measured here, not inherited."""
    resolved = registry.resolve({}, _oicd("oic.wk.d", "x.com.st.d.hood"))
    assert resolved is not None and resolved.name == "range_hood"


@pytest.mark.parametrize("oic_type,expected", [
    ("oic.d.airconditioner", "airconditioner"),
    ("oic.d.refrigerator", "refrigerator"),
    ("x.com.st.d.hood", "range_hood"),
])
def test_every_type_measured_on_real_hardware_routes(oic_type, expected):
    resolved = registry.resolve({}, _oicd("oic.wk.d", oic_type))
    assert resolved is not None and resolved.name == expected


def test_oic_d_cooktop_is_deliberately_not_mapped():
    """The one measured type left out, and the reason it must stay out.

    Our induction answers `oic.d.cooktop`, but `cooktop` is the unrelated gas
    family — burner state in /mode/vs/0's options array, a different resource
    surface entirely. The OCF type cannot tell them apart, so mapping it either
    way silently mis-types the other, and as the *primary* signal it would
    override a board token that had it right.
    """
    assert "oic.d.cooktop" not in registry._OIC_TYPE_TO_KEY
    # The board token still resolves our induction, which is the point.
    resolved = registry.resolve(
        {"/information/vs/0": {"x.com.samsung.da.modelNum": "TP1X_DA-KS-COOKTOP-01001|1|2"}},
        _oicd("oic.wk.d", "oic.d.cooktop"),
    )
    assert resolved is not None and resolved.name == "induction_cooktop"


def test_the_gas_cooktop_is_not_captured_by_the_induction_mapping():
    """The regression the exclusion prevents."""
    resolved = registry.resolve(
        {"/information/vs/0": {
            "x.com.samsung.da.modelNum": "ARTIK051_GLOBAL_CT|1|2",
            "x.com.samsung.da.description": "ARTIK051_GLOBAL_COOKTOP",
        }},
        _oicd("oic.wk.d", "oic.d.cooktop"),
    )
    assert resolved is not None and resolved.name == "cooktop"


def test_every_mapped_oic_type_names_a_registry_that_exists():
    """A typo here would route an appliance to nothing at all."""
    for oic_type, key in registry._OIC_TYPE_TO_KEY.items():
        assert key in registry._REGISTRY_BY_KEY, f"{oic_type} -> unknown key {key}"


def test_the_generic_oic_wk_d_alone_decides_nothing():
    """Every device carries it, so treating it as a type would route everything to
    whichever registry it happened to be mapped to."""
    assert "oic.wk.d" not in registry._OIC_TYPE_TO_KEY
    assert registry.resolve({}, _oicd("oic.wk.d")) is None


def test_absent_oic_d_changes_nothing():
    """The signal is additive. Boards that will not answer /oic/d must resolve
    exactly as they did before it was ever read."""
    resources = {"/information/vs/0": {
        "x.com.samsung.da.modelNum": "AHD-WW-TP1-22-COMMON|1|2",
    }}
    assert registry.resolve(resources).name == registry.resolve(resources, ()).name


def test_probe_never_fails_because_of_the_extra_read():
    """/device/0 has already succeeded when /oic/d is attempted, so a board that
    refuses the path must still pair. Reading the code because the failure mode is
    a raise, which no fixture can provoke."""
    import ast
    source = (Path(__file__).parent.parent / "lib" / "probe.py").read_text()
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_read_device_types"
    )
    handlers = [n for n in ast.walk(function) if isinstance(n, ast.ExceptHandler)]
    assert handlers, "an unguarded GET here turns a supplementary read into a pairing failure"
    assert any(
        isinstance(h.type, ast.Name) and h.type.id == "Exception" for h in handlers
    ), "only catching ConnectionError leaves decode errors able to fail the probe"


def test_the_device_swallows_the_same_read_failure():
    import ast
    source = (Path(__file__).parent.parent / "lib" / "appliance" / "device.py").read_text()
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_read_device_types"
    )
    assert any(
        isinstance(h.type, ast.Name) and h.type.id == "Exception"
        for h in ast.walk(function) if isinstance(h, ast.ExceptHandler)
    )


# --- reference #189: repeated-hex-digit placeholder serials -----------------


@pytest.mark.parametrize("serial", ["FFFFFFFFFFFFFFF", "0000000000", "aaaaaaaa"])
def test_a_repeated_hex_digit_serial_is_a_placeholder(serial):
    """The DA_WM_A51_20_COMMON laundry boards report a flash-unset sentinel. In
    reference #189 a washer and a dryer — two physical units — both reported
    'FFFFFFFFFFFFFFF'. Serial is this app's identity, so sharing one would give
    the two devices the same id and make each poll's serial check pass against
    the wrong appliance."""
    from lib.resources import is_placeholder_serial
    assert is_placeholder_serial(serial) is True


@pytest.mark.parametrize("serial", [
    "0FBC1234ABCD", "AAAAAAA", "--------", "ZZZZZZZZ", "0A0A0A0A0A",
])
def test_a_real_serial_is_not_mistaken_for_one(serial):
    """The rule is deliberately narrow: eight or more characters, all identical,
    all a hex digit. 'AAAAAAA' is seven; '--------' is not hex; 'ZZZZZZZZ' is not
    hex — none of them may be discarded."""
    from lib.resources import is_placeholder_serial
    assert is_placeholder_serial(serial) is False


def test_a_placeholder_serial_falls_back_to_host_and_port():
    from lib.resources import read_serial
    resources = {"/information/vs/0": {"x.com.samsung.da.serialNum": "FFFFFFFFFFFFFFF"}}
    assert read_serial(resources, "192.168.1.5", 49154) == "192.168.1.5:49154"


# --- reference #181/#183: the kids lock is read-only ------------------------


def test_the_vendor_kids_lock_reads_its_own_vocabulary():
    """It reports Ready/Run, and was being read through an On/Off helper — so a
    locked appliance reported unlocked, because 'Run' is not 'On'."""
    spec = next(s for s in shared.CHILD_LOCK if s.href == "/kidslock/vs/0")
    assert spec.read({"x.com.samsung.da.kidsLock": "Run"}, {}) is True
    assert spec.read({"x.com.samsung.da.kidsLock": "Ready"}, {}) is False
    assert spec.read({}, {}) is None


def test_neither_kids_lock_surface_is_writable():
    """#181's reporter confirmed a 4.05 even when writing the correct value, and
    the SmartThings app offers no control either."""
    for spec in shared.CHILD_LOCK:
        assert not spec.writable, f"{spec.href} still offers a write"


def test_the_vendor_kids_lock_yields_to_the_ocf_one():
    """An appliance carrying both would otherwise bind one capability twice."""
    spec = next(s for s in shared.CHILD_LOCK if s.href == "/kidslock/vs/0")
    assert spec.exists({}, {"/kidslock/vs/0": {}}) is True
    assert spec.exists({}, {"/kidslock/0": {}, "/kidslock/vs/0": {}}) is False


def test_the_cooktop_child_lock_is_still_writable():
    """The regression the capability split exists to prevent: this one is verified
    on real hardware here and must not be made read-only along with the others."""
    from lib.registry import induction_cooktop
    spec = next(s for s in induction_cooktop.REGISTRY.specs
                if s.capability == "localthings_child_lock")
    assert spec.writable
    assert spec.write(True, {}) == (["cooktop", "status", "vs", "0"], {"childLock": "on"})


def test_the_two_child_lock_capabilities_look_the_same_to_a_user():
    """Split by writability, not by meaning — so the titles must match."""
    root = Path(__file__).parent.parent / ".homeycompose" / "capabilities"
    writable = json.loads((root / "localthings_child_lock.json").read_text())
    readonly = json.loads((root / "localthings_child_lock_state.json").read_text())
    assert writable["title"] == readonly["title"]
    assert writable["setable"] is True and readonly["setable"] is False


# --- reference: AC odor controller, measured on all four units here ---------


def test_the_odor_controller_reads_the_option_token():
    spec = next(s for s in airconditioner.REGISTRY.specs
                if s.capability == "localthings_odor_controller")
    options = {"x.com.samsung.da.options": ["Sleep_16", "SmartCoolClean_On"]}
    assert spec.read(options, {}) is True
    assert spec.read({"x.com.samsung.da.options": ["SmartCoolClean_Off"]}, {}) is False
    assert not spec.writable, "no write contract is confirmed for it"


def test_the_odor_progress_reads_a_number():
    spec = next(s for s in airconditioner.REGISTRY.specs
                if s.capability == "localthings_odor_progress")
    assert spec.read({"x.com.samsung.da.options": ["ProgressSmartClean_40"]}, {}) == 40


@pytest.mark.parametrize("capability,token", [
    ("localthings_odor_controller", "SmartCoolClean"),
    ("localthings_odor_progress", "ProgressSmartClean"),
])
def test_each_odor_capability_is_gated_on_its_own_token(capability, token):
    """A board that advertises neither must bind neither — token presence is the
    only signal that the feature exists."""
    spec = next(s for s in airconditioner.REGISTRY.specs if s.capability == capability)
    assert spec.exists({"x.com.samsung.da.options": [f"{token}_Off"]}, {}) is True
    assert spec.exists({"x.com.samsung.da.options": ["Sleep_16"]}, {}) is False
    assert spec.exists({}, {}) is False


def test_the_option_token_reader_ignores_a_prefix_that_only_looks_similar():
    """'ProgressSmartClean' starts with neither 'SmartCoolClean' nor the reverse,
    but 'DiagnosisAI' and 'ProgressDiagnosisAI' do overlap that way on these
    units — a substring match would cross them."""
    options = {"x.com.samsung.da.options": ["ProgressDiagnosisAI_7", "DiagnosisAI_Off"]}
    assert airconditioner._option_token(options, "DiagnosisAI") == "Off"
    assert airconditioner._option_token(options, "ProgressDiagnosisAI") == "7"


# --- reference #210: the air quality monitor -------------------------------


def test_the_air_monitor_routes_from_both_signals():
    by_board = registry.resolve({"/information/vs/0": {
        "x.com.samsung.da.modelNum": "ASM-KR-TP1-22-COMMON|1|2"}})
    by_type = registry.resolve({}, ("oic.wk.d", "x.com.st.d.airqualitysensor"))
    assert by_board is not None and by_board.name == "air_monitor"
    assert by_type is not None and by_type.name == "air_monitor"


def test_the_air_monitor_reads_its_sensors():
    reg = registry._REGISTRY_BY_KEY["air_monitor"]
    rep = {"x.com.samsung.da.items": [
        {"x.com.samsung.da.type": "CO2", "x.com.samsung.da.value": [640]},
        {"x.com.samsung.da.type": "FineDust", "x.com.samsung.da.value": [12]},
    ]}
    readings = {s.capability: s.read(rep, {}) for s in reg.specs
                if s.href == "/sensors/vs/0"}
    assert readings["measure_co2"] == 640
    assert readings["measure_pm25"] == 12


def test_the_air_monitor_has_no_power_control():
    """A battery puck with no /power/* resource at all — offering onoff would be a
    switch that writes nowhere."""
    reg = registry._REGISTRY_BY_KEY["air_monitor"]
    assert not [s for s in reg.specs if s.capability == "onoff"]
    assert [s for s in reg.specs if s.capability == "measure_battery"]


# --- a write must not truncate the cached representation -------------------


def _device_module():
    """lib.appliance.device with the runtime-provided `homey` module stubbed."""
    import sys
    import types
    stub = types.ModuleType("homey")
    module = types.ModuleType("homey.device")

    class Device:
        pass

    module.Device = Device
    stub.device = module
    saved = {name: sys.modules.get(name) for name in ("homey", "homey.device")}
    sys.modules["homey"], sys.modules["homey.device"] = stub, module
    try:
        import importlib
        return importlib.import_module("lib.appliance.device")
    finally:
        for name, module_ in saved.items():
            if module_ is not None:
                sys.modules[name] = module_


def _ac_temperature_rep() -> dict:
    """A real /temperatures/vs/0, as all four units here report it."""
    return {"x.com.samsung.da.items": [{
        "x.com.samsung.da.id": "0",
        "x.com.samsung.da.description": "Temperature",
        "x.com.samsung.da.current": "30.0",
        "x.com.samsung.da.desired": "26.5",
        "x.com.samsung.da.minimum": "18",
        "x.com.samsung.da.maximum": "30",
        "x.com.samsung.da.increment": "0.5",
        "x.com.samsung.da.unit": "Celsius",
    }]}


def test_a_setpoint_write_keeps_the_rest_of_the_entry():
    """The write sends only the id and the new setpoint. Folding that in with a
    plain dict.update replaced the whole list, so until the next poll the cached
    entry had lost everything else — `measure_temperature` read None and the
    setpoint's options collapsed to {}."""
    module = _device_module()
    spec = next(s for s in airconditioner.REGISTRY.specs
                if s.capability == "target_temperature")
    current = next(s for s in airconditioner.REGISTRY.specs
                   if s.capability == "measure_temperature")

    rep = _ac_temperature_rep()
    _path, body = spec.write(28.0, rep)
    module._fold_write_into(rep, body)

    assert spec.read(rep, {}) == 28.0, "the written value did not land"
    assert current.read(rep, {}) == 30.0, "the current temperature was lost"
    assert spec.options(rep, {}) == {"min": 18.0, "max": 30.0, "step": 0.5,
                                     "decimals": 1}, "the slider lost its range"


def test_folding_matches_entries_by_id_not_position():
    """Nothing guarantees a write payload lists entries in the order the device
    reports them, and a fridge writes one compartment at a time."""
    module = _device_module()
    cached = {"x.com.samsung.da.items": [
        {"x.com.samsung.da.id": "0", "x.com.samsung.da.desired": "1", "keep": "a"},
        {"x.com.samsung.da.id": "1", "x.com.samsung.da.desired": "2", "keep": "b"},
    ]}
    module._fold_write_into(cached, {"x.com.samsung.da.items": [
        {"x.com.samsung.da.id": "1", "x.com.samsung.da.desired": "9"}]})
    items = {i["x.com.samsung.da.id"]: i for i in cached["x.com.samsung.da.items"]}
    assert items["1"]["x.com.samsung.da.desired"] == "9"
    assert items["1"]["keep"] == "b", "the untouched fields of that entry were lost"
    assert items["0"]["x.com.samsung.da.desired"] == "1", "another entry was disturbed"


def test_a_flat_field_write_still_replaces_it():
    """Only the list-shaped resources need folding; a scalar write is a plain set."""
    module = _device_module()
    cached = {"x.com.samsung.da.power": "Off", "other": "keep"}
    module._fold_write_into(cached, {"x.com.samsung.da.power": "On"})
    assert cached == {"x.com.samsung.da.power": "On", "other": "keep"}


def test_an_entry_the_cache_has_never_seen_is_added():
    module = _device_module()
    cached = {"x.com.samsung.da.items": [{"x.com.samsung.da.id": "0"}]}
    module._fold_write_into(cached, {"x.com.samsung.da.items": [
        {"x.com.samsung.da.id": "7", "x.com.samsung.da.desired": "3"}]})
    ids = [i["x.com.samsung.da.id"] for i in cached["x.com.samsung.da.items"]]
    assert ids == ["0", "7"]


# --- the parity check itself has to keep working ---------------------------


def test_the_reference_token_table_is_parsed_at_all():
    """The reason this exists: the extractor was a regex over the source text, the
    reference reformatted with ruff, its literals went from 'REF' to "REF", and the
    pattern matched nothing. `_reference_tokens()` returned {} and the test that
    walks it passed while checking nothing — for however long it took to notice.

    A parity check that cannot fail is worse than no parity check, because it
    reads as evidence."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from test_all_types import _reference_tokens
    tokens = _reference_tokens()
    assert len(tokens) >= 20, f"parsed only {len(tokens)} tokens"
    assert tokens.get("REF") == "refrigerator", "the table parsed but reads wrong"


@pytest.mark.parametrize("quoting", ["'", '"'])
def test_the_extractor_does_not_care_how_the_reference_quotes_things(quoting):
    """Formatting is not meaning. The AST does not see quoting, line breaks or
    trailing commas."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from test_all_types import _parse_str_dict
    q = quoting
    source = (
        "_T: dict[str, str] = {\n"
        f"    {q}A{q}: {q}one{q},  # a comment\n"
        f"    {q}B{q}: {q}two{q},\n"
        "}\n"
    )
    assert _parse_str_dict(source, "_T") == {"A": "one", "B": "two"}


def test_a_renamed_table_fails_loudly():
    """Silence is what let the last break go unnoticed."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from test_all_types import _parse_str_dict
    with pytest.raises(AssertionError):
        _parse_str_dict("_SOMETHING_ELSE = {'A': 'one'}\n", "_T")


# --- reference: the EHS heat pump ------------------------------------------


def test_the_heat_pump_routes():
    resolved = registry.resolve({"/information/vs/0": {
        "x.com.samsung.da.modelNum": "TP1X_DA_AC_EHS-01001|1|2"}})
    assert resolved is not None and resolved.name == "ehs"


def test_the_heat_pump_does_not_land_on_the_air_conditioner():
    """It shares the DA_AC_ board prefix with the room air conditioners and has a
    completely different resource shape, so a near miss here would bind an AC's
    mode and fan to a heat pump."""
    resolved = registry.resolve({"/information/vs/0": {
        "x.com.samsung.da.modelNum": "TP1X_DA_AC_EHS-01001|1|2"}})
    assert resolved.name != "airconditioner"


def test_the_heat_pump_setpoint_reads_and_writes_its_own_resource():
    reg = registry._REGISTRY_BY_KEY["ehs"]
    spec = next(s for s in reg.specs if s.capability == "target_temperature")
    rep = {"x.com.samsung.da.current": "38.0", "x.com.samsung.da.desired": "40.0"}
    assert spec.read(rep, {}) == 40.0
    assert spec.write(42.0, rep) == (
        ["temperatures", "indoor", "vs", "0"],
        {"x.com.samsung.da.desired": "42.0"},
    )


def test_the_heat_pump_setpoint_bounds_come_from_the_board_when_it_reports_them():
    reg = registry._REGISTRY_BY_KEY["ehs"]
    spec = next(s for s in reg.specs if s.capability == "target_temperature")
    assert spec.options({}, {})["min"] == 5.0, "no fallback range"
    reported = spec.options({"x.com.samsung.da.minimum": "25",
                             "x.com.samsung.da.maximum": "55",
                             "x.com.samsung.da.increment": "1"}, {})
    assert (reported["min"], reported["max"], reported["step"]) == (25.0, 55.0, 1.0)


# --- a dead push channel must not be retried forever -----------------------


def _observe_device():
    """An ApplianceDevice with only the observe state, no Homey session."""
    import sys
    import types
    stub = types.ModuleType("homey")
    module = types.ModuleType("homey.device")

    class Device:
        pass

    module.Device = Device
    stub.device = module
    sys.modules.setdefault("homey", stub)
    sys.modules.setdefault("homey.device", module)
    from lib.appliance.device import ApplianceDevice
    d = object.__new__(ApplianceDevice)
    d._observe_silent_rounds = 0
    return d


def test_a_channel_that_answers_nothing_is_retried_less_and_less():
    """Measured on the living-room air conditioner: 27 resources subscribed, zero
    notifications, ever. At the fixed ten-minute cadence that is 27 CON subscribes
    every ten minutes forever — over five seconds of exclusive session time each
    round, and another 27 observer registrations on an appliance the transport
    library warns remembers them across sessions."""
    from lib.const import OBSERVE_REFRESH_S, OBSERVE_RETRY_S
    d = _observe_device()
    assert d._observe_retry_after() == OBSERVE_RETRY_S
    waits = []
    for _ in range(6):
        d._observe_silent_rounds += 1
        waits.append(d._observe_retry_after())
    assert waits == sorted(waits), waits
    assert waits[0] > OBSERVE_RETRY_S, "the first silent round did not widen it"
    assert waits[-1] <= OBSERVE_REFRESH_S, "the backoff is unbounded"


def test_the_backoff_is_capped():
    from lib.const import OBSERVE_REFRESH_S
    d = _observe_device()
    d._observe_silent_rounds = 500
    assert d._observe_retry_after() == OBSERVE_REFRESH_S


def test_a_partial_channel_keeps_the_normal_cadence():
    """Under the threshold but not silent means the channel works and only
    under-delivers — worth retrying at the usual rate, unlike total silence."""
    from lib.const import OBSERVE_RETRY_S
    d = _observe_device()
    d._observe_silent_rounds = 0      # what a partial round leaves behind
    assert d._observe_retry_after() == OBSERVE_RETRY_S


def test_a_rebuilt_session_starts_the_channel_fresh():
    """Whatever was wrong with the old session is not evidence about a new one."""
    import ast
    source = (Path(__file__).parent.parent / "lib/appliance/device.py").read_text()
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "move_to"
    )
    assert "_observe_silent_rounds = 0" in ast.unparse(function)


# --- earning push must judge the channel, not the appliance's activity -----


def test_push_needs_a_quorum_of_initial_notifications():
    """A registration's response *is* its first notification — the transport
    library's `subscribe` docstring says so, and it carries a comment about the race
    it had to win to make that 2.05 survive. So a healthy channel delivers one per
    subscribed href whatever the appliance is doing, and a quorum is a fair test.

    This briefly required only one, reasoned from "an idle appliance is silent while
    healthy". Four air conditioners read 27, 26, 3 and 6 of 27 while all four were
    switched off, which idleness cannot explain.
    """
    from lib.const import OBSERVE_SUCCESS_FRACTION
    assert 0 < OBSERVE_SUCCESS_FRACTION <= 1
    for count in (27, 22):
        assert max(1, int(count * OBSERVE_SUCCESS_FRACTION)) > 1, (
            "a single notification would qualify a channel again"
        )


def test_a_partial_round_does_not_qualify_and_does_not_reset_the_backoff():
    """`if got:` was truthy for a round delivering 3 of 27, so the backoff reset
    every time and the retry stayed at OBSERVE_RETRY_S forever. That is the
    re-subscribe churn that got attributed to the threshold and fixed at the wrong
    end."""
    import ast
    source = (Path(__file__).parent.parent / "lib/appliance/device.py").read_text()
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_evaluate_observe"
    )
    body = "\n".join(
        line.split("#", 1)[0] for line in ast.unparse(function).splitlines()
    )
    assert "if got >= needed:" in body, "the backoff still resets on any notification"
    assert "needed = max(1, int(len(hrefs) * OBSERVE_SUCCESS_FRACTION))" in body


def test_a_quorum_round_clears_the_backoff():
    import ast
    source = (Path(__file__).parent.parent / "lib/appliance/device.py").read_text()
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_evaluate_observe"
    )
    body = ast.unparse(function)
    assert "_observe_silent_rounds = 0" in body
    assert "_observe_silent_rounds += 1" in body


def test_the_dead_health_check_is_gone():
    """`_push_is_healthy` was defined and called from nowhere, so nothing re-checked
    a channel once push was earned. It cannot simply be wired up — it reads silence
    as failure, and an idle appliance is silent while healthy — so the demotion
    signal has to come from the sweep finding a change push should have delivered.
    Recorded in docs/BACKLOG.md; the dead code goes."""
    source = (Path(__file__).parent.parent / "lib/appliance/device.py").read_text()
    assert "_push_is_healthy" not in source
    from lib import const
    assert not hasattr(const, "PUSH_HEALTH_WINDOW_S"), "its constant outlived it"


def test_the_observe_refresh_interval_is_not_left_lowered():
    """Measuring the observe channel means temporarily lowering this in a dev
    install. Publishing with it lowered would re-subscribe every appliance in the
    house forty times an hour."""
    from lib.const import OBSERVE_REFRESH_S
    assert OBSERVE_REFRESH_S == 6 * 3600.0, (
        "left at a measurement value instead of restored"
    )


def test_silence_still_disqualifies():
    """Zero notifications is the one case the verdict is for, and it must keep
    costing the device its push status."""
    import ast
    source = (Path(__file__).parent.parent / "lib/appliance/device.py").read_text()
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_evaluate_observe"
    )
    body = ast.unparse(function)
    assert "got >= needed" in body
    assert "_observe_silent_rounds += 1" in body, (
        "a silent round no longer widens the retry"
    )


# --- the registration burst was losing the initial notifications ------------


def test_registrations_are_spaced():
    """Measured on the guest-room air conditioner: 0 of 27 initial notifications
    after a subscribe round, then 6 within 25 s of switching the unit on and 7
    within a minute, every value landing on the right capability. The channel works;
    the burst is what was lost. The other three units read 27, 27 and 24 of 27 — a
    lossy burst, not a broken channel.

    The transport library's `subscribe()` is unpaced — `pace()` has one call site,
    inside the Block2 loop — so nothing spaced them before this.
    """
    import ast
    source = (Path(__file__).parent.parent / "lib/appliance/device.py").read_text()
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_try_observe"
    )
    body = ast.unparse(function)
    assert "OBSERVE_SUBSCRIBE_SPACING_S" in body, "the registrations are unspaced again"
    assert "asyncio.sleep" in body, (
        "spacing must not hold an executor thread — nine appliances subscribe at once"
    )
    assert "time.sleep" not in body


def test_the_spacing_matches_the_librarys_own_bulk_path_and_not_its_rate_limit():
    """0.05 s is what `refresh_observes()` uses between subscribes. `pace()`'s 0.2 s
    would occupy the shared executor for 27 x 0.2 s per device, and this app starts
    nine of them together."""
    from lib.const import OBSERVE_SUBSCRIBE_SPACING_S
    assert OBSERVE_SUBSCRIBE_SPACING_S == 0.05
    assert 27 * OBSERVE_SUBSCRIBE_SPACING_S < 2.0, "a subscribe round got expensive"


def test_the_first_registration_is_not_delayed():
    """A device with one observable resource should not wait to send it."""
    import ast
    source = (Path(__file__).parent.parent / "lib/appliance/device.py").read_text()
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_try_observe"
    )
    body = ast.unparse(function)
    assert "if index:" in body, "the gap is applied before the first registration too"

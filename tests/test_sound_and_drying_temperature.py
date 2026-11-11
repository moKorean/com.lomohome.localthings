"""Two gaps the reference's new dumps exposed.

`/settings/sound/*` was bound on four registries and not on the laundry or
refrigerator ones, so the AWM-US-M64 washer-dryer (reference #784) served five
sound resources this app read none of. They are bound through `shared.SOUND`
now, which also gained tone, output and the mute flag.

And `x.com.samsung.da.waterTemperature` means two different things depending on
which appliance reports it: the wash temperature on a washer, the heat setting
on a dryer. Same field name, disjoint value domains — the reason the dryer gets
a capability of its own rather than the washer's.
"""

import json
from pathlib import Path

import pytest

from lib import registry

REF_FIXTURES = Path(__file__).parent.parent.parent / "localthings-reference" / "tests" / "fixtures"
OUR_FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.skipif(
    not REF_FIXTURES.is_dir(), reason="reference checkout not present"
)


def _resources_from(path: Path) -> dict:
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

    walk(json.loads(path.read_text()))
    return out


def _read(name, capability):
    resources = _resources_from(REF_FIXTURES / name)
    reg = registry.resolve(resources)
    assert reg is not None, name
    assert capability in reg.capabilities(resources), f"{name}: {capability} not bound"
    spec = reg.spec_for(capability, resources)
    return spec.read(resources.get(spec.href) or {}, resources)


def test_the_washer_dryer_no_longer_leaves_its_sound_surface_unread():
    resources = _resources_from(REF_FIXTURES / "washer_dryer_awm_m64_device.json")
    reg = registry.resolve(resources)
    assert reg is not None
    unbound = [h for h in registry.unbound_hrefs(resources, reg) if "/settings/sound/" in h]
    # `voice` stays unbound on purpose: its supportedVoices are opaque pack ids.
    assert unbound == ["/settings/sound/voice/vs/0"], unbound


@pytest.mark.parametrize("capability,expected", [
    ("localthings_sound_mode", "tone"),
    ("localthings_sound_volume", 8),
    ("localthings_sound_tone", "11"),
    ("localthings_sound_output", "speaker"),
    ("localthings_sound_muted", True),
])
def test_the_washer_dryers_sound_readings(capability, expected):
    assert _read("washer_dryer_awm_m64_device.json", capability) == expected


def test_the_mute_flag_is_gated_rather_than_guessed():
    """Our own air conditioners serve `/settings/sound/output/vs/0` with
    `deviceType` alone. A mute reading there would have to come from an absent
    field, and False would be an invented answer rather than a missing one."""
    resources = json.loads(
        (OUR_FIXTURES / "airconditioner_TP1X_DA-AC-CAC-01001.json").read_text()
    )["resources"]
    rep = resources["/settings/sound/output/vs/0"]
    assert "alarmInMute" not in rep
    reg = registry.resolve(resources)
    bound = reg.capabilities(resources)
    assert "localthings_sound_output" in bound
    assert "localthings_sound_muted" not in bound
    spec = reg.spec_for("localthings_sound_output", resources)
    assert spec.read(rep, resources) == "speaker"


def test_the_same_field_carries_two_different_domains():
    """The premise of splitting the capability. If both families used one value
    set, one reading would do and this would be over-built."""
    dryer = _resources_from(REF_FIXTURES / "dryer_dve50a8600_device.json")["/washer/vs/0"]
    washer = _resources_from(REF_FIXTURES / "washer_device.json")["/washer/vs/0"]
    field = "x.com.samsung.da.supportedWaterTemperature"
    assert set(dryer[field]) & set(washer[field]) == {"None"}


def test_a_dryer_reads_its_heat_setting_and_not_a_wash_temperature():
    assert _read("dryer_dve50a8600_device.json", "localthings_drying_temperature") == "Medium"
    resources = _resources_from(REF_FIXTURES / "dryer_dve50a8600_device.json")
    reg = registry.resolve(resources)
    assert reg.name == "dryer"
    assert "localthings_wash_temperature" not in reg.capabilities(resources)


def test_a_washer_still_reads_a_wash_temperature():
    assert _read("washer_device.json", "localthings_wash_temperature") == "40"
    resources = _resources_from(REF_FIXTURES / "washer_device.json")
    reg = registry.resolve(resources)
    assert "localthings_drying_temperature" not in reg.capabilities(resources)

"""`/option/airpurify/vs/0` exists on boards that refuse to be written.

The ARTIK051_PRAC generation serves the resource, answers a read from it, and
rejects every write (reference #747); the AR09TXFCAWKNEU manual for a unit of
that family lists no Purify mode at all, and what the phone app calls Purify on
these boards is Wind. So the switch this app published on them could never work.

The gate is deliberately narrow. These tests hold both ends of that: the two
PRAC dumps lose the control, every other dump that carries the resource keeps
it, and this house's own air conditioners are on the keeping side.
"""

import json
from pathlib import Path

import pytest

from lib import registry

APP_ROOT = Path(__file__).parent.parent
REF_FIXTURES = APP_ROOT.parent / "localthings-reference" / "tests" / "fixtures"
OUR_FIXTURES = Path(__file__).parent / "fixtures"

HREF = "/option/airpurify/vs/0"
CAPABILITY = "localthings_air_purify"


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


def _model(resources) -> str:
    info = resources.get("/information/vs/0") or {}
    return str(info.get("x.com.samsung.da.modelNum") or "").upper()


def _carriers():
    """Every reference dump that serves the resource, with its model string."""
    if not REF_FIXTURES.is_dir():
        pytest.skip("reference checkout not present")
    found = []
    for path in sorted(REF_FIXTURES.glob("*_device.json")):
        resources = _resources_from(path)
        if HREF in resources:
            found.append((path.name, resources))
    return found


def test_the_premise_holds_in_the_corpus():
    """Both halves have to exist for the gate to be worth anything: boards that
    refuse the write, and boards that do not."""
    carriers = _carriers()
    prac = [n for n, r in carriers if _model(r).startswith("ARTIK051_PRAC")]
    other = [n for n, r in carriers if not _model(r).startswith("ARTIK051_PRAC")]
    assert len(prac) == 2, prac
    assert len(other) >= 6, other


def test_the_refusing_family_does_not_get_the_switch():
    for name, resources in _carriers():
        if not _model(resources).startswith("ARTIK051_PRAC"):
            continue
        reg = registry.resolve(resources)
        assert reg is not None, name
        assert CAPABILITY not in reg.capabilities(resources), name


def test_every_other_carrier_keeps_it():
    kept = []
    for name, resources in _carriers():
        if _model(resources).startswith("ARTIK051_PRAC"):
            continue
        reg = registry.resolve(resources)
        if reg is None or reg.name != "airconditioner":
            continue
        assert CAPABILITY in reg.capabilities(resources), name
        kept.append(name)
    assert len(kept) >= 6, kept


def test_this_houses_air_conditioner_is_unaffected():
    """The four units here are TP1X_DA-AC-CAC-01001 and carry the resource, so
    the gate must not reach them — this is the regression the narrowness is for."""
    path = OUR_FIXTURES / "airconditioner_TP1X_DA-AC-CAC-01001.json"
    resources = json.loads(path.read_text())["resources"]
    assert HREF in resources
    reg = registry.resolve(resources)
    assert reg is not None and reg.name == "airconditioner"
    assert CAPABILITY in reg.capabilities(resources)

"""The reference-coverage gate runs in CI, so it should run here too.

This file exists because of how it was missed. The script was run by hand after
every step of a large sync, and its output read and judged — but always through a
pipe (`| head`, `| tail`), which replaces its exit status with the pager's. It
printed its gaps, a human agreed they were deliberate, and nobody noticed the
script disagreed. CI, which does not pipe, failed twice.

The suite is what actually gets run before a push, so the gate belongs in it.

Deliberately not asserting *which* divergences are declared: that is the script's
own business and `docs/BACKLOG.md` carries the reasoning. What is pinned here is
that the gate passes, and that it is still capable of failing — an allowance list
that swallowed everything would pass this file just as happily otherwise.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "check_reference_coverage.py"
REFERENCE = ROOT.parent / "localthings-reference"

pytestmark = pytest.mark.skipif(
    not REFERENCE.is_dir(), reason="reference checkout not present"
)


def _run():
    return subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=ROOT
    )


def test_the_gate_passes():
    result = _run()
    assert result.returncode == 0, (
        "scripts/check_reference_coverage.py fails, which is what CI runs:\n"
        f"{result.stdout}{result.stderr}"
    )


def test_the_gate_can_still_fail():
    """An undeclared gap must still be an error.

    Asserted by reading the script's own tables rather than by mutating it: every
    declared divergence has to name a real one, which is the condition the script
    enforces in the other direction too.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("_cov", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    declared = set(module.UNPORTED_TYPES) | set(module.DIVERGENT_TOKENS)
    assert declared, "nothing is declared, so the allowance cannot be keeping anything"

    from lib import registry

    for key in module.UNPORTED_TYPES:
        assert key not in registry._REGISTRY_BY_KEY, (
            f"{key} is declared unported but a registry exists — drop the entry"
        )
    for token in module.DIVERGENT_TOKENS:
        assert token in registry._BOARD_TOKEN_TO_KEY, (
            f"{token} is declared divergent but this port does not route it at all"
        )

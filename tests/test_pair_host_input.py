"""The manual-address field in the pairing view.

The network sweep does not find every appliance, so typing an address by hand is the
path that always works — and the field now prefills everything but the last octet
from the Homey's own subnet.

These are static checks on the view, because the logic is JavaScript that no Python
test can execute. That is a real limit: they prove the wiring exists and the driver
supplies what it needs, not that the browser does the right thing. The parts worth
guarding are the ones that fail silently — a prefix nothing sets, a validator nothing
calls, a string in one language only.
"""

import ast
import json
import re
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).parent.parent
VIEW = APP_ROOT / "drivers/appliance/pair/configure.html"
DRIVER = APP_ROOT / "lib/appliance/driver.py"


@pytest.fixture(scope="module")
def view() -> str:
    return VIEW.read_text()


@pytest.fixture(scope="module")
def strings(view: str) -> dict:
    """STRINGS.en and STRINGS.ko keys, read out of the view's script block."""
    out = {}
    for lang in ("en", "ko"):
        block = re.search(rf"\n[ \t]*{lang}: \{{\n(.*?)\n[ \t]*\}},\n", view, re.DOTALL)
        assert block, f"no STRINGS.{lang}"
        out[lang] = set(re.findall(r"^\s*(\w+):", block.group(1), re.MULTILINE))
    return out


# --- the driver has to supply the subnet ----------------------------------


def test_get_state_reports_a_subnet():
    """The prefix comes from the driver; the view cannot work it out. If this key is
    dropped the field silently falls back to asking for a whole address."""
    tree = ast.parse(DRIVER.read_text())
    handler = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_on_get_state"
    )
    returned = [
        key.value
        for node in ast.walk(handler)
        if isinstance(node, ast.Dict)
        for key in node.keys
        if isinstance(key, ast.Constant)
    ]
    assert "subnet" in returned, returned


def test_subnet_detection_failure_cannot_block_pairing():
    """local_subnet touches a socket. Pairing must survive it raising."""
    source = DRIVER.read_text()
    handler = source[source.index("async def _on_get_state"):]
    handler = handler[:handler.index("def _paired_identity")]
    assert "local_subnet()" in handler
    assert "except Exception" in handler, "subnet detection is not guarded"
    assert 'subnet = ""' in handler, "no fallback when detection fails"


# --- the view has to use it ------------------------------------------------


def test_the_view_stores_the_subnet_it_is_given(view):
    assert "state.subnet" in view, "get_state's subnet is never read"
    assert re.search(r"SUBNET\s*=\s*String\(", view), "SUBNET is never assigned"


def test_the_subnet_is_applied_before_the_strings_are_painted(view):
    """applyStrings decides whether to show the prefix, so it has to run after
    SUBNET is set. Reversed, the field paints as a full-address input every time."""
    assigned = view.index("SUBNET = String(")
    painted = view.index("applyStrings();", assigned)
    assert assigned < painted


def test_the_octet_field_is_focused_when_the_manual_step_opens(view):
    """The prefix is already filled in; the caret belongs in the only field left."""
    handler = view[view.index("'btn-manual'"):]
    handler = handler[:handler.index("addEventListener('keydown'")]
    assert "focus()" in handler


# --- address resolution ---------------------------------------------------


def test_resolved_host_is_what_connect_uses(view):
    """connect() must not read the raw field: with a prefix shown, the field holds
    an octet and probing '185' would fail with a confusing message."""
    body = view[view.index("function connect()"):]
    body = body[:body.index("H.emit('probe'")]
    assert "resolvedHost()" in body
    assert "getElementById('host').value" not in body, (
        "connect() reads the field directly, bypassing the prefix"
    )


def test_a_dot_between_numbers_escapes_the_prefix(view):
    """Without this, an appliance on another subnet is unreachable — the prefix
    would be prepended to an address that already has one."""
    body = view[view.index("function resolvedHost()"):]
    body = body[:body.index("// `prefixed` is true")]
    assert "indexOf('.')" in body


def test_edge_dots_and_whitespace_are_stripped_not_rejected(view):
    """The field sits right after a prefix ending in '.', so typing '.185' is the
    natural mistake. Treating that as a full address — which is what a bare
    indexOf('.') does — turns a perfectly clear input into an error."""
    body = view[view.index("function normalizeTyped"):]
    body = body[:body.index("function resolvedHost")]
    assert ".trim()" in body
    assert re.search(r"replace\(/\^\\\.\+/", body), "leading dots not stripped"
    assert re.search(r"replace\(/\\\.\+\$/", body), "trailing dots not stripped"


def test_resolution_and_the_prefixed_test_use_the_same_normalizer(view):
    """hostWasPrefixed decides which validation applies, so it has to see the same
    string resolvedHost did. Two normalizers would disagree on '.185'."""
    for fn in ("function resolvedHost()", "function hostWasPrefixed()"):
        body = view[view.index(fn):]
        body = body[:body.index("\n  }", body.index("{")) + 4]
        assert "normalizeTyped(" in body, fn


def test_network_and_broadcast_are_rejected_only_for_the_prefixed_path(view):
    """.0 and .255 are the /24's network and broadcast addresses and never a host,
    and both are easy to type when only the last number is being entered. The /24
    assumption is only ours to make when we supplied the prefix — a whole address
    typed by hand belongs to a network whose shape this view does not know."""
    body = view[view.index("function validHost"):]
    body = body[:body.index("function hostWasPrefixed")]
    assert "last > 0" in body and "last < 255" in body
    assert "if (!prefixed) return true;" in body

    call = view[view.index("function connect()"):]
    call = call[:call.index("H.emit('probe'")]
    assert "validHost(host, hostWasPrefixed())" in call


# --- strings ---------------------------------------------------------------


@pytest.mark.parametrize("key", ["hostNoteOctet", "hostNoteFull", "badHost",
                                 "manual", "manualHint"])
def test_every_new_string_exists_in_both_languages(strings, key):
    for lang in ("en", "ko"):
        assert key in strings[lang], f"{key} missing from STRINGS.{lang}"


def test_both_host_notes_are_reachable(view):
    """One is for the prefixed field, the other for the full-address fallback. A
    branch that only ever picks one leaves the other dead."""
    assert "t('hostNoteOctet')" in view
    assert "t('hostNoteFull')" in view
    assert re.search(r"SUBNET \? t\('hostNoteOctet'\) : t\('hostNoteFull'\)", view)


def test_manual_entry_is_a_button_not_a_link(view):
    """It used to be a line of small print. The sweep misses appliances often
    enough that this is the reliable path, and it should look like one."""
    assert re.search(r'<button id="btn-manual"', view)
    assert not re.search(r'<a[^>]*id="btn-manual"', view)


def test_the_manual_hint_says_the_scan_is_not_exhaustive(strings, view):
    """The wording is the point: a user who believes the scan is authoritative
    concludes the appliance is unsupported."""
    en = re.search(r"manualHint: '([^']*)'", view).group(1)
    assert "does not find every appliance" in en, en


# --- the placeholder must match which mode the field is in ----------------


def test_the_placeholder_changes_with_the_prefix(view):
    """A '192.168.1.90' placeholder next to a '192.168.1.' prefix reads as though
    the whole address should be typed again."""
    body = view[view.index("setText('t-host-note'"):]
    body = body[:body.index("}", body.index("field.removeAttribute"))]
    assert "placeholder = '90'" in body
    assert "placeholder = '192.168.1.90'" in body


def test_the_locale_files_are_untouched_by_this(view):
    """These strings live in the view, not in locales/*.json — the view resolves the
    UI language itself. Asserted so a later edit does not split them across both."""
    for lang in ("en", "ko"):
        locale = json.loads((APP_ROOT / f"locales/{lang}.json").read_text())
        flat = json.dumps(locale)
        assert "hostNoteOctet" not in flat
        assert "badHost" not in flat

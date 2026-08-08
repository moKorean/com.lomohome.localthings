"""A messy paste does not break credential loading here, measured 2026-08-08.

The reference fixed this upstream (issue #291): a PEM copied out of a text editor
can carry a UTF-8 BOM, CR or CRLF line endings, or blank lines a paste introduced,
and Home Assistant's config flow refused it with an opaque `InvalidHeader`. The
obvious move was to port the normalization — a small, harmless-looking guard.

It was not ported, because **neither parser this app uses rejects any of it.**
Measured against the versions the app ships:

    cryptography 49.0.0   load_pem_private_key   BOM / CRLF / CR / blank line: all OK
    pyOpenSSL             load_certificate,      BOM / CRLF: all OK
                          load_privatekey

So the guard would have had no user, and a normalization step in the credential
path is not free: it rewrites the exact bytes the user pasted, before the one
place that decides whether they are usable. This repo has done the other thing
once already — the induction cooktop's power-off toggle, built on a capability
list that looked like a write contract and refused every write — and the lesson
recorded there was to take the apparatus out rather than leave an abstraction with
no user.

These tests are the reopening condition. If a parser upgrade makes any of them
fail, the mangling is real for this app and `normalize_pem` is worth porting from
the reference's `config_flow.py`.
"""

import pytest
from cryptography.hazmat.primitives import serialization

from lib import cert

UUID = "7f3c1d90-4b2e-4a61-9c05-2d8ae6114f37"

# What a paste out of an editor adds. The BOM is written as an escape on purpose:
# as a literal it is invisible in a diff, which is how it gets into a PEM.
BOM = "\ufeff"


@pytest.fixture(scope="module")
def minted():
    return cert.mint_self_signed(UUID)


def _mangled(text, style):
    if style == "bom":
        return BOM + text
    if style == "crlf":
        return text.replace("\n", "\r\n")
    if style == "cr":
        return text.replace("\n", "\r")
    if style == "blank_line":
        return text.replace("-----\n", "-----\n\n", 1)
    if style == "everything":
        return BOM + text.replace("-----\n", "-----\n\n", 1).replace("\n", "\r\n")
    raise AssertionError(style)


STYLES = ["bom", "crlf", "cr", "blank_line", "everything"]


@pytest.mark.parametrize("style", STYLES)
def test_the_private_key_parser_tolerates_a_mangled_paste(minted, style):
    """The key is the half that has no regex in front of it, so it is the half a
    BOM would reach. It parses anyway."""
    _, key_pem = minted
    key = serialization.load_pem_private_key(
        _mangled(key_pem, style).encode(), password=None
    )
    assert key.key_size == 2048


@pytest.mark.parametrize("style", STYLES)
def test_the_app_s_own_validator_accepts_a_mangled_paste(minted, style):
    """End to end through the function the settings page actually calls."""
    fullchain, key_pem = minted
    info = cert.inspect_leaf(_mangled(fullchain, style), _mangled(key_pem, style))
    assert info["uuid"] == UUID
    assert info["chain_length"] == 2


def test_nothing_normalizes_the_pem_on_the_way_in():
    """Guards the decision, not just the behaviour. Adding normalization back
    without a measurement that calls for it is the thing this file argues against —
    if a parser starts rejecting a paste, the tests above fail first and say so."""
    assert not hasattr(cert, "normalize_pem"), (
        "normalization was reintroduced; record the parser failure that justifies it"
    )

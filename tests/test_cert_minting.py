"""The app issues its own client certificate, so setup needs no other machine.

What makes this possible is a measurement, not an assumption: the appliance checks
the UUID in the subject and not who signed the certificate. An air conditioner and
a refrigerator both accepted a certificate signed by a CA generated on the spot —
live reads through the app, not merely a completed DTLS handshake — and SHA-256
worked as well as the SHA-1 the real chain uses.

Because the appliance's minimum requirement was never isolated, `mint_self_signed`
reproduces a working certificate's profile field for field. These tests pin that
profile, and they are deliberately built so they can fail:

- Fixed fields are compared against literals stated here, not read back from the
  thing under test.
- UUID-derived fields are asserted through a *different* UUID than any fixture
  uses. An earlier probe compared a minted certificate against a real one while
  reusing the real one's UUID, which held the SAN comparison true for free and
  made "no differences" partly self-fulfilling.
- The signature is verified, not just inspected. `inspect_leaf` does no signature
  checking at all, so asserting through it alone would pass for a certificate that
  cannot work.
"""

import asyncio
import datetime
import sys
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509.oid import ExtensionOID, NameOID

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib import cert, credentials
from lib.const import (
    SETTING_CERT_SOURCE,
    SETTING_LEAF_CERT,
    SETTING_LEAF_KEY,
    SOURCE_MINTED,
    SOURCE_PASTED,
)

# Deliberately not the UUID in any committed fixture.
UUID = "7f3c1d90-4b2e-4a61-9c05-2d8ae6114f37"
OTHER_UUID = "1a2b3c4d-5e6f-4071-8293-a4b5c6d7e8f9"


@pytest.fixture(scope="module")
def minted():
    fullchain, key_pem = cert.mint_self_signed(UUID)
    return fullchain, key_pem


@pytest.fixture(scope="module")
def leaf(minted):
    return x509.load_pem_x509_certificate(_blocks(minted[0])[0])


@pytest.fixture(scope="module")
def issuing_ca(minted):
    return x509.load_pem_x509_certificate(_blocks(minted[0])[1])


def _blocks(pem: str) -> list[bytes]:
    end = "-----END CERTIFICATE-----"
    return [(part + end).encode() for part in pem.split(end) if "BEGIN" in part]


def test_the_app_s_own_validator_accepts_what_the_app_issues(minted):
    """If this ever fails, the app issues certificates it then refuses to store."""
    info = cert.inspect_leaf(*minted)
    assert info["uuid"] == UUID
    assert info["expired"] is False
    # Leaf plus the CA that signed it. `inspect_leaf` rejects a lone certificate,
    # and the appliance is handed a chain, so a second block is required.
    assert info["chain_length"] == 2


def test_the_signature_actually_verifies_under_the_issued_ca(leaf, issuing_ca):
    """A real check. `inspect_leaf` verifies no signatures, so without this the
    suite would pass for a certificate whose signature is garbage."""
    issuing_ca.public_key().verify(
        leaf.signature,
        leaf.tbs_certificate_bytes,
        padding.PKCS1v15(),
        leaf.signature_hash_algorithm,
    )


def test_signing_is_sha256_because_the_appliance_does_not_check_it(leaf):
    """SHA-1 would need pyOpenSSL: `cryptography` 49 refuses to sign with it.
    Measured that SHA-256 is accepted, so there is nothing to buy with that detour."""
    assert leaf.signature_hash_algorithm.name == "sha256"
    assert leaf.signature_algorithm_oid.dotted_string == "1.2.840.113549.1.1.11"


def test_subject_rdns_match_a_working_certificate(leaf):
    assert [
        (attr.oid, attr.value) for rdn in leaf.subject.rdns for attr in rdn
    ] == [
        (NameOID.ORGANIZATIONAL_UNIT_NAME, f"uuid:{UUID}"),
        (NameOID.COMMON_NAME, f"urn:uuid:{UUID}"),
        (NameOID.ORGANIZATION_NAME, "Samsung Electronics"),
        (NameOID.COUNTRY_NAME, "KR"),
    ]


def test_issuer_is_the_ac14k_m_distinguished_name(leaf):
    """Copied so the certificate looks like the ones these appliances see. The
    name is not the signature — nothing here claims Samsung signed it, and the
    appliance does not check that it did."""
    assert [
        (attr.oid, attr.value) for rdn in leaf.issuer.rdns for attr in rdn
    ] == [
        (NameOID.COUNTRY_NAME, "KR"),
        (NameOID.ORGANIZATION_NAME, "Samsung Electronics"),
        (NameOID.COMMON_NAME, "AC14K_M"),
        (NameOID.EMAIL_ADDRESS, "AC14K_M@samsung.com"),
    ]


def test_extension_set_is_exactly_the_seven_a_working_certificate_carries(leaf):
    assert sorted(e.oid.dotted_string for e in leaf.extensions) == [
        "1.3.6.1.4.1.51414.1.3",   # samsung.role.hub
        "2.5.29.14",               # subjectKeyIdentifier
        "2.5.29.15",               # keyUsage
        "2.5.29.17",               # subjectAltName
        "2.5.29.19",               # basicConstraints
        "2.5.29.35",               # authorityKeyIdentifier
        "2.5.29.37",               # extendedKeyUsage
    ]
    assert all(e.critical is False for e in leaf.extensions)


def test_extended_key_usage_carries_the_ocf_oid_alongside_the_standard_two(leaf):
    eku = leaf.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE).value
    assert [oid.dotted_string for oid in eku] == [
        "1.3.6.1.5.5.7.3.2",          # clientAuth
        "1.3.6.1.5.5.7.3.1",          # serverAuth
        "1.3.6.1.4.1.51414.0.1.2",    # OCF
    ]


def test_the_samsung_role_extension_is_the_exact_der_a_working_certificate_has(leaf):
    """A UTF8String holding `samsung.role.hub`. Pinned as bytes because it is
    opaque to `cryptography` and a re-encoding would go unnoticed otherwise."""
    ext = leaf.extensions.get_extension_for_oid(
        x509.ObjectIdentifier("1.3.6.1.4.1.51414.1.3"))
    assert ext.value.value == b"\x0c\x10samsung.role.hub"


def test_key_usage_and_basic_constraints(leaf):
    usage = leaf.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
    assert (usage.digital_signature, usage.key_encipherment) == (True, True)
    assert not any((
        usage.content_commitment, usage.data_encipherment,
        usage.key_agreement, usage.key_cert_sign, usage.crl_sign,
    ))
    basic = leaf.extensions.get_extension_for_oid(
        ExtensionOID.BASIC_CONSTRAINTS).value
    assert basic.ca is False


def test_subject_alt_names_are_derived_from_the_uuid_not_pinned(leaf):
    """Four entries in a working certificate, three URI forms and a DNS name.

    Asserted against a UUID no fixture uses, so a profile that had accidentally
    been pinned to a fixture's UUID would fail here rather than pass silently.
    """
    san = leaf.extensions.get_extension_for_oid(
        ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    uris = san.get_values_for_type(x509.UniformResourceIdentifier)
    assert uris == [f"urn:uuid:{UUID}", f"uri:uuid:{UUID}", f"uuid:{UUID}"]
    assert san.get_values_for_type(x509.DNSName) == [UUID]


def test_key_identifiers_are_derived_from_the_actual_keys(leaf, issuing_ca):
    ski = leaf.extensions.get_extension_for_oid(
        ExtensionOID.SUBJECT_KEY_IDENTIFIER).value
    assert ski.digest == x509.SubjectKeyIdentifier.from_public_key(
        leaf.public_key()).digest
    akid = leaf.extensions.get_extension_for_oid(
        ExtensionOID.AUTHORITY_KEY_IDENTIFIER).value
    assert akid.key_identifier == x509.SubjectKeyIdentifier.from_public_key(
        issuing_ca.public_key()).digest


def test_a_different_uuid_changes_only_the_uuid_bearing_fields():
    """The guard against pinning per-installation data as though it were fixed."""
    first = x509.load_pem_x509_certificate(
        _blocks(cert.mint_self_signed(UUID)[0])[0])
    second = x509.load_pem_x509_certificate(
        _blocks(cert.mint_self_signed(OTHER_UUID)[0])[0])

    varies = {"2.5.29.17", "2.5.29.14", "2.5.29.35"}
    for ext in first.extensions:
        oid = ext.oid.dotted_string
        other = second.extensions.get_extension_for_oid(ext.oid).value
        if oid in varies:
            continue
        assert ext.value == other, f"{oid} should not depend on the UUID or the key"
    assert first.subject != second.subject


def test_validity_is_backdated_and_lasts_a_decade(leaf):
    """Backdated so a Homey clock slightly behind the appliance's does not make the
    certificate not-yet-valid the moment it is issued."""
    now = datetime.datetime.now(datetime.UTC)
    assert leaf.not_valid_before_utc < now
    assert (now - leaf.not_valid_before_utc) < datetime.timedelta(hours=2)
    assert leaf.not_valid_after_utc - leaf.not_valid_before_utc > datetime.timedelta(
        days=365 * 9)


def test_each_mint_uses_a_fresh_key():
    a_chain, a_key = cert.mint_self_signed(UUID)
    b_chain, b_key = cert.mint_self_signed(UUID)
    assert a_key != b_key
    assert _blocks(a_chain)[0] != _blocks(b_chain)[0]


@pytest.mark.parametrize("bad", [
    "", "   ", "not-a-uuid", "uuid:7f3c1d90-4b2e-4a61-9c05-2d8ae6114f37",
    "7f3c1d90-4b2e-4a61-9c05", "7f3c1d90_4b2e_4a61_9c05_2d8ae6114f37",
    "zzzzzzzz-4b2e-4a61-9c05-2d8ae6114f37",
])
def test_a_uuid_that_is_not_a_uuid_is_refused(bad):
    """A bad value from the gateway must fail here, not at pairing time, where it
    would read as a network fault."""
    with pytest.raises(cert.InvalidCredentials):
        cert.mint_self_signed(bad)


class FakeHomey:
    """Just enough of the settings surface for the credential store."""

    class _Settings:
        def __init__(self):
            self.values = {}

        def get(self, key):
            return self.values.get(key)

        def set(self, key, value):
            self.values[key] = value

        def unset(self, key):
            self.values.pop(key, None)

    def __init__(self):
        self.settings = self._Settings()


def test_issuing_records_the_source_so_a_paste_is_never_overwritten():
    homey = FakeHomey()

    async def scenario():
        assert await credentials.stored(homey) is False
        assert await credentials.source(homey) == ""

        info = await credentials.issue(homey, UUID)
        assert info["source"] == SOURCE_MINTED
        assert await credentials.stored(homey) is True
        assert await credentials.source(homey) == SOURCE_MINTED

        chain, key = cert.mint_self_signed(OTHER_UUID)
        pasted = await credentials.accept_pasted(homey, chain, key)
        assert pasted["source"] == SOURCE_PASTED
        assert await credentials.source(homey) == SOURCE_PASTED
        # And the paste really replaced it, rather than only relabelling.
        assert homey.settings.values[SETTING_LEAF_CERT].startswith(
            "-----BEGIN CERTIFICATE-----")
        assert (await credentials.pems(homey))[0].strip() == chain.strip()

    asyncio.run(scenario())


def test_a_certificate_stored_before_this_version_counts_as_pasted():
    """Upgrades carry no source flag, and every certificate then was pasted.
    Reporting it as app-issued would invite re-issue over the user's own."""
    homey = FakeHomey()
    homey.settings.values[SETTING_LEAF_CERT] = "cert"
    homey.settings.values[SETTING_LEAF_KEY] = "key"
    assert asyncio.run(credentials.source(homey)) == SOURCE_PASTED


def test_clearing_removes_the_source_flag_too():
    homey = FakeHomey()
    asyncio.run(credentials.issue(homey, UUID))
    asyncio.run(credentials.clear(homey))
    assert asyncio.run(credentials.stored(homey)) is False
    assert not homey.settings.values.get(SETTING_CERT_SOURCE)


def test_a_bad_pair_leaves_the_previous_certificate_untouched():
    """A failed paste must not cost a working setup."""
    homey = FakeHomey()
    asyncio.run(credentials.issue(homey, UUID))
    before = dict(homey.settings.values)

    with pytest.raises(cert.InvalidCredentials):
        asyncio.run(credentials.accept_pasted(homey, "not a certificate", "nor a key"))

    assert homey.settings.values == before
    assert asyncio.run(credentials.source(homey)) == SOURCE_MINTED


def test_signing_needs_no_ca_key_from_anywhere():
    """The point of the whole change. If `mint_self_signed` ever grows a parameter
    for CA material, setup stops being self-contained and needs another machine."""
    import inspect
    assert list(inspect.signature(cert.mint_self_signed).parameters) == ["uuid"]


def test_the_gateway_unreachable_message_exists_in_both_languages():
    """`mint_credentials` raises it by key; a missing key would surface the key
    itself to the user."""
    import json
    for language in ("en", "ko"):
        path = Path(__file__).parent.parent / "locales" / f"{language}.json"
        messages = json.loads(path.read_text(encoding="utf-8"))
        assert messages["error"]["gateway_unreachable"].strip()
